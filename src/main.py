"""Command line entry point: read a ledger, check it, report on it."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src import checks, config, faia, ingest, reports


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"date illisible : {value} (attendu AAAA-MM-JJ ou JJ/MM/AAAA)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lux-ledger",
        description=("Controle qualite et restitutions sur un grand livre tenu "
                     "au plan comptable normalise luxembourgeois."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--journal", type=Path,
                        default=config.DATA_DIR / "journal_clean.csv",
                        help="fichier d'ecritures a analyser")
    parser.add_argument("--pcn", type=Path, default=config.PCN_FILE,
                        help="referentiel du plan comptable")
    parser.add_argument("--tva", type=Path, default=config.VAT_CODES_FILE,
                        help="referentiel des codes TVA")
    parser.add_argument("--postes", type=Path,
                        default=config.DATA_DIR / "postes.csv",
                        help="tableau de passage vers le bilan et le compte de resultat")
    parser.add_argument("--tiers", type=Path, default=config.DATA_DIR / "tiers.csv",
                        help="annuaire des clients et fournisseurs")
    parser.add_argument("--output", type=Path, default=config.OUTPUT_DIR,
                        help="repertoire de sortie")
    parser.add_argument("--debut", type=_parse_date,
                        default=config.FISCAL_YEAR_START,
                        help="premier jour de l'exercice")
    parser.add_argument("--fin", type=_parse_date, default=config.FISCAL_YEAR_END,
                        help="dernier jour de l'exercice")
    parser.add_argument("--entite", default=config.COMPANY_NAME,
                        help="denomination portee dans les etats")
    parser.add_argument("--numero-tva", default=config.COMPANY_VAT_NUMBER,
                        help="numero de TVA porte dans l'extrait FAIA")
    parser.add_argument("--faia", action="store_true",
                        help="produire aussi l'extrait FAIA simplifie")
    parser.add_argument("--strict", action="store_true",
                        help="code de sortie 2 si une anomalie bloquante est detectee")
    parser.add_argument("--silencieux", action="store_true",
                        help="n'ecrire sur la sortie standard que l'essentiel")
    return parser


def _print_table(frame: pd.DataFrame, columns: list[str]) -> None:
    widths = {c: max(len(c), int(frame[c].astype(str).str.len().max() or 0))
              for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    print("  " + header)
    print("  " + "-" * len(header))
    for _, row in frame.iterrows():
        print("  " + "  ".join(str(row[c]).ljust(widths[c]) for c in columns))


def run(args) -> int:
    run_config = config.RunConfig(
        journal_file=args.journal, output_dir=args.output, pcn_file=args.pcn,
        vat_codes_file=args.tva, fiscal_year_start=args.debut,
        fiscal_year_end=args.fin, company_name=args.entite,
        vat_number=args.numero_tva, with_faia=args.faia,
        fail_on_blocking=args.strict)

    verbose = not args.silencieux
    if verbose:
        print(f"Entite    : {run_config.company_name}")
        print(f"Exercice  : {run_config.fiscal_year_start:%d/%m/%Y} - "
              f"{run_config.fiscal_year_end:%d/%m/%Y}")
        print(f"Journal   : {run_config.journal_file}")
        print()

    pcn = ingest.load_pcn(run_config.pcn_file)
    vat_codes = ingest.load_vat_codes(run_config.vat_codes_file)
    postes = reports.load_postes(args.postes)
    third_parties = ingest.load_third_parties(args.tiers)

    journal, report = ingest.load_journal(run_config.journal_file)
    journal = ingest.enrich_with_pcn(journal, pcn)
    if verbose:
        print(report.summary())

    anomalies = checks.run_all(journal, vat_codes, run_config, report.rejected)
    summary = checks.summarise(anomalies)

    statements = reports.build_all(journal, pcn, vat_codes, postes, third_parties)
    control = statements.pop("_controle_bilan")

    vat_declaration = statements["tva_declaration"]
    net_vat = (float(vat_declaration.loc[vat_declaration["rubrique"].eq("SOLDE"),
                                         "taxe"].sum())
               if not vat_declaration.empty else 0.0)

    context = {
        "company": run_config.company_name,
        "vat_number": run_config.vat_number,
        "start": run_config.fiscal_year_start,
        "end": run_config.fiscal_year_end,
        "source": run_config.journal_file.name,
        "run_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "rows_read": report.rows_read,
        "rows_kept": report.rows_kept,
        "pieces": int(journal["piece"].nunique()),
        "total_debit": round(float(journal["debit"].sum()), 2),
        "total_credit": round(float(journal["credit"].sum()), 2),
        "ecart": round(float(journal["debit"].sum() - journal["credit"].sum()), 2),
        "total_actif": control["total_actif"],
        "total_passif": control["total_passif"],
        "resultat": reports.net_result(journal),
        "tva_nette": round(net_vat, 2),
        "anomalies": int(len(anomalies)),
        "anomalies_bloquantes": int(
            (anomalies["severite"] == config.SEVERITY.BLOCKING).sum()
            if not anomalies.empty else 0),
    }

    stem = run_config.journal_file.stem
    output_dir = Path(run_config.output_dir)
    workbook = reports.write_workbook(output_dir / f"{stem}_etats.xlsx",
                                      statements, anomalies, summary, context)
    anomaly_report = reports.write_anomaly_report(
        output_dir / f"{stem}_anomalies.txt", anomalies, summary, context)

    produced = [workbook, anomaly_report]
    if run_config.with_faia:
        produced.append(faia.write_faia(output_dir / f"{stem}_faia.xml", journal,
                                        pcn, vat_codes, run_config, third_parties))

    if verbose:
        print()
        print("CONTROLES")
        _print_table(summary, ["statut", "severite", "anomalies", "libelle_controle"])
        print()
        print("SYNTHESE")
        print(f"  Pieces                 : {context['pieces']}")
        print(f"  Total debit / credit   : {context['total_debit']:,.2f} / "
              f"{context['total_credit']:,.2f} EUR")
        print(f"  Total actif / passif   : {context['total_actif']:,.2f} / "
              f"{context['total_passif']:,.2f} EUR "
              f"({'equilibre' if control['equilibre'] else 'DESEQUILIBRE'})")
        print(f"  Resultat de l'exercice : {context['resultat']:,.2f} EUR")
        print(f"  TVA nette              : {context['tva_nette']:,.2f} EUR")
        print(f"  Anomalies              : {context['anomalies']} "
              f"(dont {context['anomalies_bloquantes']} bloquantes)")
        print()
        print("SORTIES")
        for path in produced:
            print(f"  {path}")

    if run_config.fail_on_blocking and checks.has_blocking(anomalies):
        return 2
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
