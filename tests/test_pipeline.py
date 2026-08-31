"""End to end: the two shipped datasets, read through the command line."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src import checks, config, faia, ingest, main, reports

CLEAN = config.DATA_DIR / "journal_clean.csv"
DIRTY = config.DATA_DIR / "journal_dirty.csv"
EXPECTED = config.DATA_DIR / "anomalies_attendues.csv"

pytestmark = pytest.mark.skipif(
    not CLEAN.exists(),
    reason="jeux de donnees absents : lancer python -m src.generate_data")


def _analyse(path: Path, pcn, vat_codes, run_config):
    journal, report = ingest.load_journal(path)
    journal = ingest.enrich_with_pcn(journal, pcn)
    anomalies = checks.run_all(journal, vat_codes, run_config, report.rejected)
    return journal, anomalies


def test_clean_ledger_raises_no_anomaly(pcn, vat_codes, run_config):
    _, anomalies = _analyse(CLEAN, pcn, vat_codes, run_config)
    assert anomalies.empty, anomalies[["code_controle", "piece", "message"]].to_string()


def test_clean_ledger_balance_sheet_balances(pcn, vat_codes, postes, run_config):
    journal, _ = _analyse(CLEAN, pcn, vat_codes, run_config)
    control = reports.balance_sheet_control(reports.balance_sheet(journal, postes))
    assert control["equilibre"]


def test_clean_ledger_is_balanced_overall(pcn, vat_codes, run_config):
    journal, _ = _analyse(CLEAN, pcn, vat_codes, run_config)
    assert round(journal["debit"].sum() - journal["credit"].sum(), 2) == 0.0


def test_every_injected_defect_is_detected(pcn, vat_codes, run_config):
    _, anomalies = _analyse(DIRTY, pcn, vat_codes, run_config)
    expected = pd.read_csv(EXPECTED, sep=config.CSV_SEPARATOR, dtype=str)
    detected = set(anomalies["code_controle"])
    missing = set(expected["code_controle"]) - detected
    assert not missing, f"controles muets : {sorted(missing)}"


def test_dirty_ledger_has_blocking_findings(pcn, vat_codes, run_config):
    _, anomalies = _analyse(DIRTY, pcn, vat_codes, run_config)
    assert checks.has_blocking(anomalies)


def test_command_line_writes_its_outputs(tmp_path):
    code = main.main(["--journal", str(CLEAN), "--output", str(tmp_path),
                      "--faia", "--silencieux"])
    assert code == 0
    assert (tmp_path / "journal_clean_etats.xlsx").exists()
    assert (tmp_path / "journal_clean_anomalies.txt").exists()
    assert (tmp_path / "journal_clean_faia.xml").exists()


def test_strict_mode_fails_on_a_defective_ledger(tmp_path):
    code = main.main(["--journal", str(DIRTY), "--output", str(tmp_path),
                      "--strict", "--silencieux"])
    assert code == 2


def test_workbook_holds_every_sheet(tmp_path):
    main.main(["--journal", str(CLEAN), "--output", str(tmp_path), "--silencieux"])
    workbook = pd.ExcelFile(tmp_path / "journal_clean_etats.xlsx")
    for sheet in ("Synthese", "Controles", "Balance generale", "Bilan",
                  "Compte de resultat", "TVA declaration"):
        assert sheet in workbook.sheet_names


def test_faia_extract_is_well_formed(tmp_path, pcn, vat_codes, run_config):
    import xml.etree.ElementTree as ET

    journal, _ = _analyse(CLEAN, pcn, vat_codes, run_config)
    third_parties = ingest.load_third_parties(config.DATA_DIR / "tiers.csv")
    path = faia.write_faia(tmp_path / "faia.xml", journal, pcn, vat_codes,
                           run_config, third_parties)
    root = ET.parse(path).getroot()
    assert root.tag.endswith("AuditFile")
    tags = [child.tag.split("}")[-1] for child in root]
    assert tags == ["Header", "MasterFiles", "GeneralLedgerEntries"]
