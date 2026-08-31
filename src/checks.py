"""Quality checks run on a ledger before anything is reported on it.

Each check returns the same anomaly frame so that they can be concatenated
into a single working list, the way a reviewer would keep one sheet of
points to clear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config

ANOMALY_COLUMNS = ["code_controle", "libelle_controle", "severite", "piece",
                   "ligne", "date", "journal", "compte", "tiers", "montant",
                   "message"]

PIECE_PATTERN = re.compile(r"^(?P<journal>[A-Z]+)(?P<annee>\d{4})(?P<numero>\d+)$")


@dataclass(frozen=True)
class Check:
    code: str
    libelle: str
    severite: str


CHECKS = {
    "PIECE_DESEQUILIBREE": Check("PIECE_DESEQUILIBREE",
                                 "Equilibre debit/credit par piece",
                                 config.SEVERITY.BLOCKING),
    "PERIODE_DESEQUILIBREE": Check("PERIODE_DESEQUILIBREE",
                                   "Equilibre debit/credit par periode",
                                   config.SEVERITY.BLOCKING),
    "COMPTE_INCONNU": Check("COMPTE_INCONNU",
                            "Compte absent du plan comptable normalise",
                            config.SEVERITY.BLOCKING),
    "COMPTE_NON_IMPUTABLE": Check("COMPTE_NON_IMPUTABLE",
                                  "Imputation sur un compte de regroupement",
                                  config.SEVERITY.MAJOR),
    "DOUBLON": Check("DOUBLON", "Ecriture apparaissant en double",
                     config.SEVERITY.MAJOR),
    "DATE_HORS_EXERCICE": Check("DATE_HORS_EXERCICE",
                                "Date hors de l'exercice comptable",
                                config.SEVERITY.BLOCKING),
    "MONTANT_ABERRANT": Check("MONTANT_ABERRANT",
                              "Montant atypique au regard du compte",
                              config.SEVERITY.MINOR),
    "TVA_INCOHERENTE": Check("TVA_INCOHERENTE",
                             "TVA comptabilisee differente de la base x taux",
                             config.SEVERITY.MAJOR),
    "CODE_TVA_INTERDIT": Check("CODE_TVA_INTERDIT",
                               "Code TVA sur un compte qui n'en admet pas",
                               config.SEVERITY.MAJOR),
    "CODE_TVA_INCONNU": Check("CODE_TVA_INCONNU",
                              "Code TVA absent du referentiel",
                              config.SEVERITY.MAJOR),
    "CODE_TVA_MANQUANT": Check("CODE_TVA_MANQUANT",
                               "Compte de charge ou de produit sans code TVA",
                               config.SEVERITY.MINOR),
    "DEBIT_ET_CREDIT": Check("DEBIT_ET_CREDIT",
                             "Ligne servie au debit et au credit",
                             config.SEVERITY.MAJOR),
    "LIGNE_SANS_MONTANT": Check("LIGNE_SANS_MONTANT", "Ligne sans montant",
                                config.SEVERITY.MINOR),
    "SEQUENCE_INTERROMPUE": Check("SEQUENCE_INTERROMPUE",
                                  "Rupture dans la numerotation des pieces",
                                  config.SEVERITY.MINOR),
    "TIERS_MANQUANT": Check("TIERS_MANQUANT",
                            "Compte auxiliaire mouvemente sans tiers",
                            config.SEVERITY.MINOR),
    "LIGNE_ILLISIBLE": Check("LIGNE_ILLISIBLE",
                             "Ligne rejetee a la lecture du fichier",
                             config.SEVERITY.BLOCKING),
}


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=ANOMALY_COLUMNS)


def _anomalies(rows: pd.DataFrame, code: str, message: pd.Series) -> pd.DataFrame:
    """Shape a subset of postings into the common anomaly format."""
    if rows.empty:
        return _empty()
    check = CHECKS[code]
    out = pd.DataFrame({
        "code_controle": code,
        "libelle_controle": check.libelle,
        "severite": check.severite,
        "piece": rows.get("piece"),
        "ligne": rows.get("ligne"),
        "date": rows.get("date"),
        "journal": rows.get("journal"),
        "compte": rows.get("compte"),
        "tiers": rows.get("tiers"),
        "montant": rows.get("montant"),
        "message": message,
    })
    return out[ANOMALY_COLUMNS]


# --------------------------------------------------------------------------
# Individual checks
# --------------------------------------------------------------------------
def check_voucher_balance(journal: pd.DataFrame) -> pd.DataFrame:
    """Every voucher must balance to the cent."""
    grouped = journal.groupby("piece", as_index=False).agg(
        debit=("debit", "sum"), credit=("credit", "sum"),
        date=("date", "min"), journal_code=("journal", "first"),
        ligne=("ligne", "min"))
    grouped["ecart"] = (grouped["debit"] - grouped["credit"]).round(2)
    broken = grouped.loc[grouped["ecart"].abs() > config.BALANCE_TOLERANCE].copy()
    if broken.empty:
        return _empty()
    broken = broken.rename(columns={"journal_code": "journal"})
    broken["compte"] = ""
    broken["tiers"] = ""
    broken["montant"] = broken["ecart"]
    message = broken.apply(
        lambda row: (f"debit {row['debit']:.2f} / credit {row['credit']:.2f} "
                     f"- ecart {row['ecart']:.2f} EUR"), axis=1)
    return _anomalies(broken, "PIECE_DESEQUILIBREE", message)


def check_period_balance(journal: pd.DataFrame) -> pd.DataFrame:
    """Each accounting period must balance as well."""
    grouped = journal.groupby("periode", as_index=False).agg(
        debit=("debit", "sum"), credit=("credit", "sum"))
    grouped["ecart"] = (grouped["debit"] - grouped["credit"]).round(2)
    broken = grouped.loc[grouped["ecart"].abs() > config.BALANCE_TOLERANCE].copy()
    if broken.empty:
        return _empty()
    broken["piece"] = broken["periode"]
    broken["ligne"] = pd.NA
    broken["date"] = pd.NaT
    broken["journal"] = ""
    broken["compte"] = ""
    broken["tiers"] = ""
    broken["montant"] = broken["ecart"]
    message = broken.apply(
        lambda row: f"periode {row['periode']} - ecart {row['ecart']:.2f} EUR",
        axis=1)
    return _anomalies(broken, "PERIODE_DESEQUILIBREE", message)


def check_unknown_accounts(journal: pd.DataFrame) -> pd.DataFrame:
    """Accounts that do not exist in the chart of accounts."""
    rows = journal.loc[~journal["connu"]].copy()
    message = rows["compte"].map(lambda c: f"compte {c} absent du PCN 2020")
    return _anomalies(rows, "COMPTE_INCONNU", message)


def check_non_postable_accounts(journal: pd.DataFrame) -> pd.DataFrame:
    """The PCN 2020 separates grouping accounts from postable accounts."""
    rows = journal.loc[journal["connu"] & ~journal["imputable"].astype(bool)].copy()
    message = rows.apply(
        lambda row: (f"compte {row['compte']} ({row['libelle_compte']}) est un "
                     "compte de regroupement, non imputable"), axis=1)
    return _anomalies(rows, "COMPTE_NON_IMPUTABLE", message)


def check_duplicates(journal: pd.DataFrame) -> pd.DataFrame:
    """Postings repeated with the same voucher, date, account and amounts."""
    keys = ["piece", "date", "journal", "compte", "libelle", "debit", "credit",
            "tiers"]
    duplicated = journal.duplicated(subset=keys, keep="first")
    rows = journal.loc[duplicated].copy()
    message = rows["piece"].map(
        lambda p: f"ligne identique deja presente dans la piece {p}")
    return _anomalies(rows, "DOUBLON", message)


def check_dates(journal: pd.DataFrame, start, end) -> pd.DataFrame:
    """Postings dated outside the financial year under review."""
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    rows = journal.loc[(journal["date"] < start_ts) | (journal["date"] > end_ts)].copy()
    message = rows["date"].dt.strftime("%d/%m/%Y").map(
        lambda d: (f"date {d} hors de l'exercice "
                   f"{start_ts:%d/%m/%Y} - {end_ts:%d/%m/%Y}"))
    return _anomalies(rows, "DATE_HORS_EXERCICE", message)


def check_outliers(journal: pd.DataFrame) -> pd.DataFrame:
    """Amounts far away from what the account usually carries.

    Uses the modified z-score (median absolute deviation), which does not
    collapse when a handful of very large postings sit in the population.
    """
    working = journal.loc[journal["connu"] & journal["journal"].ne("AN")].copy()
    working["valeur"] = working[["debit", "credit"]].max(axis=1)
    working = working.loc[working["valeur"] > 0]
    if working.empty:
        return _empty()

    # A posting is compared with the median of its own account: an invoice
    # of 4 000 EUR among invoices of 400 EUR is ordinary, one of 400 000 EUR
    # is a keying error until proven otherwise.
    by_account = working.groupby("compte")["valeur"]
    median = by_account.transform("median")
    population = by_account.transform("size")
    working["mediane"] = median.round(2)
    working["ratio"] = (working["valeur"] / median.replace(0, np.nan)).fillna(0.0)

    rows = working.loc[
        (population >= config.OUTLIER_MIN_POPULATION)
        & (working["valeur"] >= config.OUTLIER_FLOOR)
        & (working["ratio"] > config.OUTLIER_RATIO)
    ].copy()
    if rows.empty:
        return _empty()
    message = rows.apply(
        lambda row: (f"montant {row['valeur']:,.2f} EUR sur le compte "
                     f"{row['compte']}, soit {row['ratio']:.0f} fois la mediane "
                     f"du compte ({row['mediane']:,.2f} EUR)"), axis=1)
    return _anomalies(rows, "MONTANT_ABERRANT", message)


def check_vat_codes_known(journal: pd.DataFrame, vat_codes: pd.DataFrame) -> pd.DataFrame:
    """VAT codes that are not in the reference table."""
    known = set(vat_codes["code"])
    rows = journal.loc[~journal["code_tva"].isin(known)].copy()
    message = rows["code_tva"].map(lambda c: f"code TVA {c} inconnu")
    return _anomalies(rows, "CODE_TVA_INCONNU", message)


def check_vat_code_placement(journal: pd.DataFrame) -> pd.DataFrame:
    """A VAT code has no business on equity, treasury or VAT accounts."""
    coded = journal["code_tva"].ne("NA") & journal["code_tva"].ne("")
    forbidden_class = journal["classe"].isin(config.NON_VAT_ACCOUNT_CLASSES)
    vat_accounts = list(config.OUTPUT_VAT_ACCOUNTS) + list(config.INPUT_VAT_ACCOUNTS)
    on_vat_account = journal["compte"].isin(vat_accounts)
    rows = journal.loc[coded & (forbidden_class | on_vat_account)].copy()
    message = rows.apply(
        lambda row: (f"code TVA {row['code_tva']} porte par le compte "
                     f"{row['compte']}"), axis=1)
    return _anomalies(rows, "CODE_TVA_INTERDIT", message)


def check_vat_code_missing(journal: pd.DataFrame) -> pd.DataFrame:
    """Revenue and expense postings in a sales or purchase journal need a code."""
    in_scope = journal["journal"].isin(["VE", "AC"])
    profit_and_loss = journal["classe"].isin(["6", "7"])
    without_code = journal["code_tva"].isin(["NA", ""])
    rows = journal.loc[in_scope & profit_and_loss & without_code].copy()
    message = rows.apply(
        lambda row: (f"compte {row['compte']} mouvemente dans le journal "
                     f"{row['journal']} sans code TVA"), axis=1)
    return _anomalies(rows, "CODE_TVA_MANQUANT", message)


def check_vat_amounts(journal: pd.DataFrame, vat_codes: pd.DataFrame) -> pd.DataFrame:
    """Recompute the VAT of each voucher from its taxable base.

    For every voucher, the taxable bases carrying a code are multiplied by
    the rate of that code, and the result is compared with what was actually
    posted to the matching VAT account of the same voucher.
    """
    rates = vat_codes.set_index("code")
    taxed = journal.loc[journal["code_tva"].isin(rates.index)].copy()
    taxed = taxed.loc[taxed["code_tva"].map(rates["taux"]) > 0]
    if taxed.empty:
        return _empty()

    taxed["sens"] = taxed["code_tva"].map(rates["sens"])
    taxed["taux"] = taxed["code_tva"].map(rates["taux"])
    taxed["base"] = np.where(taxed["sens"].eq("VENTE"),
                             taxed["credit"] - taxed["debit"],
                             taxed["debit"] - taxed["credit"])

    expected_rows = []
    for code, group in taxed.groupby("code_tva"):
        account = rates.loc[code, "compte_tva"]
        reverse = rates.loc[code, "compte_tva_autoliquidation"]
        rate = rates.loc[code, "taux"]
        per_piece = group.groupby("piece")["base"].sum().round(2)
        for target, sense in ((account, rates.loc[code, "sens"]),
                              (reverse, "VENTE")):
            if not target:
                continue
            for piece, base in per_piece.items():
                expected_rows.append({"piece": piece, "compte_tva": target,
                                      "sens": sense,
                                      "attendu": round(base * rate, 2),
                                      "base": base, "code_tva": code})
    if not expected_rows:
        return _empty()
    expected = (pd.DataFrame(expected_rows)
                .groupby(["piece", "compte_tva", "sens"], as_index=False)
                .agg(attendu=("attendu", "sum"), base=("base", "sum"),
                     code_tva=("code_tva", lambda s: "/".join(sorted(set(s))))))

    vat_accounts = list(config.OUTPUT_VAT_ACCOUNTS) + list(config.INPUT_VAT_ACCOUNTS)
    booked = journal.loc[journal["compte"].isin(vat_accounts)].copy()
    booked["mouvement"] = np.where(
        booked["compte"].isin(config.OUTPUT_VAT_ACCOUNTS),
        booked["credit"] - booked["debit"],
        booked["debit"] - booked["credit"])
    if booked.empty:
        booked_by_piece = pd.DataFrame(columns=["piece", "compte", "comptabilise",
                                               "ligne", "date", "journal_code",
                                               "tiers"])
    else:
        booked_by_piece = (booked.groupby(["piece", "compte"], as_index=False)
                           .agg(comptabilise=("mouvement", "sum"),
                                ligne=("ligne", "min"), date=("date", "min"),
                                journal_code=("journal", "first"),
                                tiers=("tiers", "first")))

    merged = expected.merge(booked_by_piece, how="left",
                            left_on=["piece", "compte_tva"],
                            right_on=["piece", "compte"])
    merged["comptabilise"] = pd.to_numeric(
        merged["comptabilise"], errors="coerce").fillna(0.0)
    merged["ecart"] = (merged["comptabilise"] - merged["attendu"]).round(2)
    rows = merged.loc[merged["ecart"].abs() > config.VAT_TOLERANCE].copy()
    if rows.empty:
        return _empty()
    rows["compte"] = rows["compte_tva"]
    rows["journal"] = rows["journal_code"].fillna("") if "journal_code" in rows else ""
    rows["montant"] = rows["ecart"]
    message = rows.apply(
        lambda row: (f"base {row['base']:.2f} EUR au code {row['code_tva']} : "
                     f"TVA attendue {row['attendu']:.2f}, comptabilisee "
                     f"{row['comptabilise']:.2f} (ecart {row['ecart']:.2f})"),
        axis=1)
    return _anomalies(rows, "TVA_INCOHERENTE", message)


def check_debit_and_credit(journal: pd.DataFrame) -> pd.DataFrame:
    """A posting is either a debit or a credit, never both."""
    rows = journal.loc[(journal["debit"] > 0) & (journal["credit"] > 0)].copy()
    message = rows.apply(
        lambda row: (f"debit {row['debit']:.2f} et credit {row['credit']:.2f} "
                     "sur la meme ligne"), axis=1)
    return _anomalies(rows, "DEBIT_ET_CREDIT", message)


def check_zero_lines(journal: pd.DataFrame) -> pd.DataFrame:
    """Postings with no amount at all."""
    rows = journal.loc[(journal["debit"] == 0) & (journal["credit"] == 0)].copy()
    message = pd.Series("ligne sans debit ni credit", index=rows.index)
    return _anomalies(rows, "LIGNE_SANS_MONTANT", message)


def check_sequence(journal: pd.DataFrame) -> pd.DataFrame:
    """Gaps in the voucher numbering of each journal."""
    pieces = journal[["piece"]].drop_duplicates("piece")
    parsed = pieces["piece"].str.extract(PIECE_PATTERN).rename(
        columns={"journal": "journal_piece", "annee": "annee_piece"})
    pieces = pieces.join(parsed).dropna(subset=["numero"])
    if pieces.empty:
        return _empty()
    pieces["numero"] = pieces["numero"].astype(int)

    findings = []
    for (journal_code, year), group in pieces.groupby(
            ["journal_piece", "annee_piece"]):
        numbers = sorted(group["numero"].unique())
        if len(numbers) < 2:
            continue
        present = set(numbers)
        missing = [n for n in range(numbers[0], numbers[-1] + 1) if n not in present]
        for number in missing:
            findings.append({
                "piece": f"{journal_code}{year}{number:05d}",
                "ligne": pd.NA, "date": pd.NaT, "journal": journal_code,
                "compte": "", "tiers": "", "montant": 0.0,
                "texte": (f"piece {journal_code}{year}{number:05d} absente entre "
                          f"{numbers[0]:05d} et {numbers[-1]:05d}"),
            })
    if not findings:
        return _empty()
    rows = pd.DataFrame(findings)
    return _anomalies(rows, "SEQUENCE_INTERROMPUE", rows["texte"])


def check_third_parties(journal: pd.DataFrame) -> pd.DataFrame:
    """Sub-ledger accounts moved without a third-party code."""
    sub_ledger = journal["compte"].str.startswith(
        (config.CUSTOMER_ACCOUNT_PREFIX, config.SUPPLIER_ACCOUNT_PREFIX))
    missing = journal["tiers"].fillna("").eq("")
    rows = journal.loc[sub_ledger & missing & journal["journal"].ne("AN")].copy()
    message = rows["compte"].map(
        lambda c: f"compte auxiliaire {c} mouvemente sans code tiers")
    return _anomalies(rows, "TIERS_MANQUANT", message)


def check_ingest_rejects(rejected: pd.DataFrame) -> pd.DataFrame:
    """Rows the parser could not read are anomalies in their own right."""
    if rejected is None or rejected.empty:
        return _empty()
    rows = rejected.copy()
    for column in ("montant", "tiers", "journal", "compte", "piece"):
        if column not in rows.columns:
            rows[column] = ""
    rows["montant"] = 0.0
    message = pd.Series("date ou compte illisible dans le fichier source",
                        index=rows.index)
    return _anomalies(rows, "LIGNE_ILLISIBLE", message)


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
def run_all(journal: pd.DataFrame, vat_codes: pd.DataFrame, run_config,
            rejected: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run every check and return one working list of anomalies."""
    frames = [
        check_ingest_rejects(rejected),
        check_voucher_balance(journal),
        check_period_balance(journal),
        check_unknown_accounts(journal),
        check_non_postable_accounts(journal),
        check_duplicates(journal),
        check_dates(journal, run_config.fiscal_year_start, run_config.fiscal_year_end),
        check_outliers(journal),
        check_vat_codes_known(journal, vat_codes),
        check_vat_code_placement(journal),
        check_vat_code_missing(journal),
        check_vat_amounts(journal, vat_codes),
        check_debit_and_credit(journal),
        check_zero_lines(journal),
        check_sequence(journal),
        check_third_parties(journal),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return _empty()
    anomalies = pd.concat(frames, ignore_index=True)
    order = {config.SEVERITY.BLOCKING: 0, config.SEVERITY.MAJOR: 1,
             config.SEVERITY.MINOR: 2}
    anomalies["rang"] = anomalies["severite"].map(order).fillna(3)
    anomalies = anomalies.sort_values(["rang", "code_controle", "piece"])
    return anomalies.drop(columns="rang").reset_index(drop=True)


def summarise(anomalies: pd.DataFrame) -> pd.DataFrame:
    """One line per check: how many findings, at which severity."""
    rows = []
    counts = (anomalies.groupby("code_controle").size()
              if not anomalies.empty else pd.Series(dtype=int))
    for code, check in CHECKS.items():
        rows.append({
            "code_controle": code,
            "libelle_controle": check.libelle,
            "severite": check.severite,
            "anomalies": int(counts.get(code, 0)),
            "statut": "A CORRIGER" if counts.get(code, 0) else "OK",
        })
    frame = pd.DataFrame(rows)
    order = {config.SEVERITY.BLOCKING: 0, config.SEVERITY.MAJOR: 1,
             config.SEVERITY.MINOR: 2}
    frame["rang"] = frame["severite"].map(order).fillna(3)
    frame = frame.sort_values(["rang", "code_controle"])
    return frame.drop(columns="rang").reset_index(drop=True)


def has_blocking(anomalies: pd.DataFrame) -> bool:
    if anomalies.empty:
        return False
    return bool((anomalies["severite"] == config.SEVERITY.BLOCKING).any())
