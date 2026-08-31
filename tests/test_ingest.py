"""Reading a French-formatted ledger export."""

from __future__ import annotations

import pandas as pd
import pytest

from src import ingest


def test_pcn_has_no_duplicate_accounts(pcn):
    assert pcn["compte"].is_unique


def test_pcn_separates_grouping_from_postable_accounts(pcn):
    assert pcn["imputable"].any()
    assert (~pcn["imputable"]).any()
    # A two-digit account is always a grouping account under the PCN 2020.
    two_digits = pcn.loc[pcn["compte"].str.len() == 2]
    assert not two_digits["imputable"].any()


def test_vat_codes_cover_the_four_luxembourg_rates(vat_codes):
    rates = set(vat_codes.loc[vat_codes["sens"].eq("VENTE"), "taux"])
    assert {0.17, 0.14, 0.08, 0.03}.issubset(rates)


def test_amounts_written_with_a_comma_are_read_as_floats():
    series = pd.Series(["1 234,56", "12,00", "", "-", "890,10"])
    result = ingest._to_amount(series)
    assert list(result) == [1234.56, 12.0, 0.0, 0.0, 890.10]


def test_journal_is_typed_and_dated(tmp_path):
    path = tmp_path / "journal.csv"
    path.write_text(
        "piece;date;journal;compte;libelle;debit;credit;code_tva;tiers;reference\n"
        "VE202500001;14/03/2025;ve; 704000 ;Prestation;;1 000,00;s17;C0001;FV1\n"
        "VE202500001;14/03/2025;VE;401100;Client;1170,00;;NA;C0001;FV1\n",
        encoding="utf-8")
    frame, report = ingest.load_journal(path)

    assert report.rows_read == 2
    assert report.rows_kept == 2
    assert frame.loc[0, "compte"] == "704000"
    assert frame.loc[0, "journal"] == "VE"
    assert frame.loc[0, "code_tva"] == "S17"
    assert frame.loc[0, "credit"] == 1000.0
    assert frame.loc[0, "date"] == pd.Timestamp("2025-03-14")
    assert frame.loc[0, "periode"] == "2025-03"


def test_unreadable_rows_are_set_aside_not_dropped(tmp_path):
    path = tmp_path / "journal.csv"
    path.write_text(
        "piece;date;journal;compte;libelle;debit;credit;code_tva;tiers;reference\n"
        "OD202500001;31/02/2025;OD;704000;Date impossible;;100,00;NA;;X\n"
        "OD202500002;15/04/2025;OD;;Compte absent;100,00;;NA;;X\n"
        "OD202500003;15/04/2025;OD;704000;Correcte;;100,00;NA;;X\n",
        encoding="utf-8")
    frame, report = ingest.load_journal(path)

    assert report.rows_kept == 1
    assert report.rows_rejected == 2


def test_missing_column_is_refused(tmp_path):
    path = tmp_path / "journal.csv"
    path.write_text("piece;date;journal;compte\nVE1;01/01/2025;VE;704000\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="colonnes manquantes"):
        ingest.load_journal(path)


def test_enrichment_marks_unknown_accounts(pcn):
    frame = pd.DataFrame({"compte": ["704000", "999999"]})
    enriched = ingest.enrich_with_pcn(frame, pcn)
    assert list(enriched["connu"]) == [True, False]
