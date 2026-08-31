"""Statements: balance, balance sheet, profit and loss, VAT."""

from __future__ import annotations

from src import config, reports
from tests.conftest import make_journal


def test_trial_balance_totals_match_the_ledger(balanced_sale, pcn):
    balance = reports.trial_balance(balanced_sale, pcn)
    assert round(balance["debit"].sum(), 2) == round(balance["credit"].sum(), 2)
    assert set(balance["compte"]) == {"401100", "704000", "461411"}


def test_trial_balance_labels_unknown_accounts(pcn):
    journal = make_journal([
        ("AC202500001", "2025-05-02", "AC", "606999", "Achat", 500.0, 0.0, "A17"),
    ], pcn)
    balance = reports.trial_balance(journal, pcn)
    assert balance.loc[0, "libelle"] == "COMPTE HORS PCN"


def test_auxiliary_balance_shows_the_open_item(balanced_sale):
    aux = reports.auxiliary_balance(balanced_sale,
                                    config.CUSTOMER_ACCOUNT_PREFIX, "CLIENT")
    assert list(aux["tiers"]) == ["C0001"]
    assert aux.loc[0, "solde"] == 1170.00


def test_balance_sheet_balances_once_the_result_is_posted(pcn, postes):
    journal = make_journal([
        ("AN202500001", "2025-01-01", "AN", "511100", "Ouverture", 10000.0, 0.0,
         "NA"),
        ("AN202500001", "2025-01-01", "AN", "101100", "Capital", 0.0, 10000.0,
         "NA"),
        ("VE202500001", "2025-03-14", "VE", "401100", "Client", 1170.0, 0.0,
         "NA", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.0,
         "S17", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "461411", "TVA", 0.0, 170.0, "NA",
         "C0001"),
    ], pcn)
    bilan = reports.balance_sheet(journal, postes)
    control = reports.balance_sheet_control(bilan)
    assert control["equilibre"]
    assert control["total_actif"] == 11170.00


def test_result_of_the_period_is_carried_to_the_liabilities(pcn, postes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "401100", "Client", 1170.0, 0.0,
         "NA", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.0,
         "S17", "C0001"),
        ("VE202500001", "2025-03-14", "VE", "461411", "TVA", 0.0, 170.0, "NA",
         "C0001"),
    ], pcn)
    bilan = reports.balance_sheet(journal, postes)
    line = bilan.loc[bilan["poste"].eq("A.VI. Resultat de l'exercice"), "montant"]
    assert float(line.iloc[0]) == reports.net_result(journal) == 1000.0


def test_income_statement_adds_up(pcn, postes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.0,
         "S17", "C0001"),
        ("AC202500001", "2025-04-02", "AC", "606000", "Achat", 400.0, 0.0, "A17",
         "F0001"),
        ("OD202500001", "2025-12-31", "OD", "621000", "Salaires", 250.0, 0.0,
         "NA"),
    ], pcn)
    cpp = reports.income_statement(journal, postes)
    total = cpp.loc[cpp["poste"].eq("17. Resultat de l'exercice"), "montant"]
    assert float(total.iloc[0]) == 350.0
    charges = cpp.loc[cpp["sens"].eq("-"), "montant"]
    assert (charges >= 0).all()


def test_vat_return_nets_output_against_input(pcn, vat_codes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "704000", "Prestation", 0.0, 1000.0,
         "S17", "C0001"),
        ("AC202500001", "2025-04-02", "AC", "606000", "Achat", 400.0, 0.0, "A17",
         "F0001"),
    ], pcn)
    detail = reports.vat_detail(journal, vat_codes)
    declaration = reports.vat_return(detail)
    solde = declaration.loc[declaration["rubrique"].eq("SOLDE")]
    assert float(solde["taxe"].iloc[0]) == round(170.0 - 68.0, 2)
    assert solde["libelle"].iloc[0] == "TVA due"


def test_exempt_supplies_appear_with_a_nil_tax(pcn, vat_codes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "704000", "Intracom", 0.0, 5000.0,
         "SIC", "C0002"),
    ], pcn)
    declaration = reports.vat_return(reports.vat_detail(journal, vat_codes))
    line = declaration.loc[declaration["code"].eq("SIC")]
    assert float(line["base"].iloc[0]) == 5000.0
    assert float(line["taxe"].iloc[0]) == 0.0


def test_monthly_vat_view_has_one_row_per_period(pcn, vat_codes):
    journal = make_journal([
        ("VE202500001", "2025-03-14", "VE", "704000", "Mars", 0.0, 1000.0, "S17"),
        ("VE202500002", "2025-04-14", "VE", "704000", "Avril", 0.0, 2000.0, "S17"),
    ], pcn)
    monthly = reports.vat_monthly(reports.vat_detail(journal, vat_codes))
    assert list(monthly["periode"]) == ["2025-03", "2025-04"]
    assert list(monthly["taxe_collectee"]) == [170.0, 340.0]
