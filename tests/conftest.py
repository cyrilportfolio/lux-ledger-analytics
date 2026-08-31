"""Fixtures shared by the test suite."""

from __future__ import annotations


import pandas as pd
import pytest

from src import config, ingest, reports

COLUMNS = ["piece", "date", "journal", "compte", "libelle", "debit", "credit",
           "code_tva", "tiers", "reference"]


@pytest.fixture(scope="session")
def pcn() -> pd.DataFrame:
    return ingest.load_pcn()


@pytest.fixture(scope="session")
def vat_codes() -> pd.DataFrame:
    return ingest.load_vat_codes()


@pytest.fixture(scope="session")
def postes() -> pd.DataFrame:
    return reports.load_postes()


@pytest.fixture(scope="session")
def run_config() -> config.RunConfig:
    return config.RunConfig(journal_file=config.DATA_DIR / "journal_clean.csv")


def make_journal(rows: list[tuple], pcn: pd.DataFrame) -> pd.DataFrame:
    """Build an enriched ledger frame from compact tuples.

    Each row is (piece, date, journal, account, label, debit, credit,
    vat code, third party).
    """
    frame = pd.DataFrame([
        {"piece": r[0], "date": pd.Timestamp(r[1]), "journal": r[2],
         "compte": r[3], "libelle": r[4], "debit": float(r[5]),
         "credit": float(r[6]), "code_tva": r[7],
         "tiers": r[8] if len(r) > 8 else "", "reference": "TEST"}
        for r in rows
    ])
    frame["ligne"] = range(1, len(frame) + 1)
    frame["montant"] = (frame["debit"] - frame["credit"]).round(2)
    frame["classe"] = frame["compte"].str[0]
    frame["periode"] = frame["date"].dt.to_period("M").astype(str)
    frame["annee"] = frame["date"].dt.year
    return ingest.enrich_with_pcn(frame, pcn)


@pytest.fixture
def balanced_sale(pcn) -> pd.DataFrame:
    """One compliant sales invoice: 1 000 EUR of services at 17 %."""
    return make_journal([
        ("VE202500001", "2025-03-14", "VE", "401100", "Client X", 1170.00, 0.0,
         "NA", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.00,
         "S17", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "461411", "TVA collectee", 0.0,
         170.00, "NA", "C0001"),
    ], pcn)
