"""Each control is exercised on a ledger built for it."""

from __future__ import annotations

import pandas as pd

from src import checks, config
from tests.conftest import make_journal


def codes(anomalies: pd.DataFrame) -> set:
    return set(anomalies["code_controle"]) if not anomalies.empty else set()


def test_a_compliant_invoice_raises_nothing(balanced_sale, vat_codes, run_config):
    anomalies = checks.run_all(balanced_sale, vat_codes, run_config)
    assert anomalies.empty, anomalies.to_string()


def test_unbalanced_voucher_is_blocking(pcn, vat_codes, run_config):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "401100", "Client", 1170.00, 0.0,
         "NA", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 900.00,
         "S17", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "461411", "TVA", 0.0, 170.00, "NA",
         "C0001"),
    ], pcn)
    anomalies = checks.check_voucher_balance(journal)
    assert len(anomalies) == 1
    assert anomalies.iloc[0]["severite"] == config.SEVERITY.BLOCKING
    assert anomalies.iloc[0]["montant"] == 100.00


def test_account_outside_the_chart_is_flagged(pcn):
    journal = make_journal([
        ("AC202500001", "2025-05-02", "AC", "606999", "Achat", 500.0, 0.0, "A17"),
        ("AC202500001", "2025-05-02", "AC", "441100", "Fournisseur", 0.0, 500.0,
         "NA", "F0001"),
    ], pcn)
    anomalies = checks.check_unknown_accounts(journal)
    assert list(anomalies["compte"]) == ["606999"]


def test_posting_on_a_grouping_account_is_flagged(pcn):
    journal = make_journal([
        ("AC202500001", "2025-05-02", "AC", "61", "Charges externes", 500.0, 0.0,
         "A17"),
        ("AC202500001", "2025-05-02", "AC", "441100", "Fournisseur", 0.0, 500.0,
         "NA", "F0001"),
    ], pcn)
    anomalies = checks.check_non_postable_accounts(journal)
    assert list(anomalies["compte"]) == ["61"]


def test_identical_postings_are_reported_once(pcn):
    row = ("OD202500001", "2025-06-30", "OD", "648000", "Charge", 120.0, 0.0, "NA")
    journal = make_journal([row, row], pcn)
    anomalies = checks.check_duplicates(journal)
    assert len(anomalies) == 1


def test_dates_outside_the_year_are_flagged(pcn, run_config):
    journal = make_journal([
        ("VE202500001", "2024-12-30", "VE", "704000", "Avant", 0.0, 100.0, "S17"),
        ("VE202500002", "2025-06-30", "VE", "704000", "Dedans", 0.0, 100.0, "S17"),
        ("VE202500003", "2026-01-05", "VE", "704000", "Apres", 0.0, 100.0, "S17"),
    ], pcn)
    anomalies = checks.check_dates(journal, run_config.fiscal_year_start,
                                   run_config.fiscal_year_end)
    assert set(anomalies["piece"]) == {"VE202500001", "VE202500003"}


def test_a_thousandfold_amount_stands_out(pcn):
    rows = [("AC20250{:04d}".format(i), "2025-04-15", "AC", "607100", "Fourniture",
             100.0 + i, 0.0, "A17") for i in range(1, 21)]
    rows.append(("AC202500999", "2025-04-15", "AC", "607100", "Saisie erronee",
                 110000.0, 0.0, "A17"))
    journal = make_journal(rows, pcn)
    anomalies = checks.check_outliers(journal)
    assert list(anomalies["piece"]) == ["AC202500999"]


def test_vat_recomputed_from_the_base(pcn, vat_codes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "401100", "Client", 1140.00, 0.0,
         "NA", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.00,
         "S17", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "461411", "TVA a 14 au lieu de 17",
         0.0, 140.00, "NA", "C0001"),
    ], pcn)
    anomalies = checks.check_vat_amounts(journal, vat_codes)
    assert len(anomalies) == 1
    assert anomalies.iloc[0]["montant"] == -30.00


def test_reverse_charge_is_not_reported_as_an_error(pcn, vat_codes):
    journal = make_journal([
        ("AC202500001", "2025-07-08", "AC", "606000", "Achat intracom", 2000.00,
         0.0, "AIC", "F0002"),
        ("AC202500001", "2025-07-08", "AC", "421611", "TVA deductible", 340.00,
         0.0, "NA", "F0002"),
        ("AC202500001", "2025-07-08", "AC", "461411", "TVA due", 0.0, 340.00,
         "NA", "F0002"),
        ("AC202500001", "2025-07-08", "AC", "441100", "Fournisseur", 0.0,
         2000.00, "NA", "F0002"),
    ], pcn)
    assert checks.check_vat_amounts(journal, vat_codes).empty


def test_vat_code_on_a_bank_account_is_flagged(pcn):
    journal = make_journal([
        ("BQ202500001", "2025-08-01", "BQ", "511100", "Encaissement", 100.0, 0.0,
         "A17"),
        ("BQ202500001", "2025-08-01", "BQ", "401100", "Client", 0.0, 100.0, "NA",
         "C0001"),
    ], pcn)
    anomalies = checks.check_vat_code_placement(journal)
    assert list(anomalies["compte"]) == ["511100"]


def test_line_served_on_both_sides_is_flagged(pcn):
    journal = make_journal([
        ("OD202500001", "2025-09-01", "OD", "648000", "Charge", 100.0, 40.0, "NA"),
    ], pcn)
    assert len(checks.check_debit_and_credit(journal)) == 1


def test_line_without_amount_is_flagged(pcn):
    journal = make_journal([
        ("OD202500001", "2025-09-01", "OD", "648000", "Vide", 0.0, 0.0, "NA"),
    ], pcn)
    assert len(checks.check_zero_lines(journal)) == 1


def test_missing_voucher_number_is_reported(pcn):
    journal = make_journal([
        ("AC202500001", "2025-02-01", "AC", "606000", "Achat", 100.0, 0.0, "A17"),
        ("AC202500003", "2025-02-02", "AC", "606000", "Achat", 100.0, 0.0, "A17"),
    ], pcn)
    anomalies = checks.check_sequence(journal)
    assert list(anomalies["piece"]) == ["AC202500002"]


def test_sub_ledger_account_without_third_party(pcn):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "401100", "Client sans code",
         1170.0, 0.0, "NA", ""),
    ], pcn)
    assert len(checks.check_third_parties(journal)) == 1


def test_summary_lists_every_control(balanced_sale, vat_codes, run_config):
    anomalies = checks.run_all(balanced_sale, vat_codes, run_config)
    summary = checks.summarise(anomalies)
    assert len(summary) == len(checks.CHECKS)
    assert set(summary["statut"]) == {"OK"}
