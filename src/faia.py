"""Simplified FAIA extract.

FAIA (Fichier d'Audit Informatise de l'AED) is the Luxembourg flavour of the
OECD SAF-T file, which the tax authority may request from any taxpayer using
the standard chart of accounts.

What is produced here is a readable *extract* built on the FAIA structure -
Header, MasterFiles, GeneralLedgerEntries. It is meant to show how a ledger
maps onto that structure, not to pass the AED validator: several optional
blocks (source documents, product and asset tables, movement lines) are left
out on purpose.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pandas as pd

from src import config

NAMESPACE = "urn:OECD:StandardAuditFile-Tax:LU_2.01"
AUDIT_FILE_VERSION = "2.01"
SOFTWARE_NAME = "lux-ledger-analytics"
SOFTWARE_VERSION = "0.1.0"


def _sub(parent: ET.Element, tag: str, text=None) -> ET.Element:
    element = ET.SubElement(parent, tag)
    if text is not None:
        element.text = str(text)
    return element


def _amount(value: float) -> str:
    return f"{float(value):.2f}"


def _build_header(root: ET.Element, run_config, journal: pd.DataFrame) -> None:
    header = _sub(root, "Header")
    _sub(header, "AuditFileVersion", AUDIT_FILE_VERSION)
    _sub(header, "AuditFileCountry", "LU")
    _sub(header, "AuditFileDateCreated", date.today().isoformat())
    _sub(header, "SoftwareCompanyName", SOFTWARE_NAME)
    _sub(header, "SoftwareID", SOFTWARE_NAME)
    _sub(header, "SoftwareVersion", SOFTWARE_VERSION)

    company = _sub(header, "Company")
    _sub(company, "RegistrationNumber", config.COMPANY_RCS)
    _sub(company, "Name", run_config.company_name)
    address = _sub(company, "Address")
    _sub(address, "StreetName", "Rue de la Demonstration")
    _sub(address, "Number", "1")
    _sub(address, "City", "Luxembourg")
    _sub(address, "PostalCode", "L-1111")
    _sub(address, "Country", "LU")
    tax = _sub(company, "TaxRegistration")
    _sub(tax, "TaxRegistrationNumber", run_config.vat_number)
    _sub(tax, "TaxAuthority", "AED")

    _sub(header, "DefaultCurrencyCode", config.CURRENCY)
    selection = _sub(header, "SelectionCriteria")
    _sub(selection, "PeriodStart", run_config.fiscal_year_start.isoformat())
    _sub(selection, "PeriodEnd", run_config.fiscal_year_end.isoformat())
    _sub(header, "HeaderComment",
         "Extrait pedagogique produit a partir de donnees synthetiques - "
         "non destine a un depot aupres de l'AED")
    _sub(header, "TaxAccountingBasis", "A")


def _build_master_files(root: ET.Element, journal: pd.DataFrame,
                        pcn: pd.DataFrame, vat_codes: pd.DataFrame,
                        third_parties: pd.DataFrame | None) -> None:
    master = _sub(root, "MasterFiles")

    used = sorted(set(journal["compte"]))
    reference = pcn.set_index("compte")
    accounts = _sub(master, "GeneralLedgerAccounts")
    balances = journal.groupby("compte")[["debit", "credit"]].sum().round(2)
    for account in used:
        node = _sub(accounts, "Account")
        _sub(node, "AccountID", account)
        label = (reference.loc[account, "libelle"]
                 if account in reference.index else "COMPTE HORS PCN")
        _sub(node, "AccountDescription", label)
        _sub(node, "StandardAccountID", account[:2])
        _sub(node, "AccountType", "GL")
        _sub(node, "OpeningDebitBalance", _amount(0))
        _sub(node, "OpeningCreditBalance", _amount(0))
        _sub(node, "ClosingDebitBalance",
             _amount(balances.loc[account, "debit"]))
        _sub(node, "ClosingCreditBalance",
             _amount(balances.loc[account, "credit"]))

    if third_parties is not None and not third_parties.empty:
        customers = _sub(master, "Customers")
        suppliers = _sub(master, "Suppliers")
        for _, row in third_parties.iterrows():
            parent = customers if row["type"] == "CLIENT" else suppliers
            tag = "Customer" if row["type"] == "CLIENT" else "Supplier"
            node = _sub(parent, tag)
            _sub(node, f"{tag}ID", row["code"])
            _sub(node, "AccountID",
                 config.CUSTOMER_ACCOUNT_PREFIX + "100" if row["type"] == "CLIENT"
                 else config.SUPPLIER_ACCOUNT_PREFIX + "100")
            _sub(node, "Name", row["nom"])
            registration = _sub(node, "TaxRegistration")
            _sub(registration, "TaxRegistrationNumber", row.get("numero_tva", ""))
            _sub(registration, "TaxType", "TVA")
            _sub(registration, "TaxCountryRegion", row.get("pays", "LU"))

    table = _sub(master, "TaxTable")
    for _, row in vat_codes.iterrows():
        if row["code"] == "NA":
            continue
        entry = _sub(table, "TaxTableEntry")
        _sub(entry, "TaxType", "TVA")
        _sub(entry, "TaxCountryRegion", "LU")
        _sub(entry, "TaxCode", row["code"])
        _sub(entry, "Description", row["libelle"])
        _sub(entry, "TaxPercentage", f"{row['taux'] * 100:.2f}")


def _build_entries(root: ET.Element, journal: pd.DataFrame) -> None:
    entries = _sub(root, "GeneralLedgerEntries")
    _sub(entries, "NumberOfEntries", journal["piece"].nunique())
    _sub(entries, "TotalDebit", _amount(journal["debit"].sum()))
    _sub(entries, "TotalCredit", _amount(journal["credit"].sum()))

    for journal_code, journal_rows in journal.groupby("journal"):
        node = _sub(entries, "Journal")
        _sub(node, "JournalID", journal_code)
        _sub(node, "Description",
             config.JOURNALS.get(journal_code, journal_code))
        for piece, piece_rows in journal_rows.groupby("piece", sort=True):
            transaction = _sub(node, "Transaction")
            first = piece_rows.iloc[0]
            _sub(transaction, "TransactionID", piece)
            _sub(transaction, "Period", str(pd.Timestamp(first["date"]).month))
            _sub(transaction, "TransactionDate",
                 pd.Timestamp(first["date"]).date().isoformat())
            _sub(transaction, "Description", first["libelle"])
            _sub(transaction, "SystemEntryDate",
                 pd.Timestamp(first["date"]).date().isoformat())
            _sub(transaction, "GLPostingDate",
                 pd.Timestamp(first["date"]).date().isoformat())
            lines = _sub(transaction, "Lines")
            for _, row in piece_rows.iterrows():
                side = "DebitLine" if row["debit"] >= row["credit"] else "CreditLine"
                line = _sub(lines, side)
                _sub(line, "RecordID", str(row["ligne"]))
                _sub(line, "AccountID", row["compte"])
                if row["tiers"]:
                    _sub(line, "CustomerID", row["tiers"])
                _sub(line, "SourceDocumentID", row["reference"])
                _sub(line, "SystemEntryDate",
                     pd.Timestamp(row["date"]).date().isoformat())
                _sub(line, "Description", row["libelle"])
                amount_tag = "DebitAmount" if side == "DebitLine" else "CreditAmount"
                amount = _sub(line, amount_tag)
                _sub(amount, "Amount",
                     _amount(row["debit"] if side == "DebitLine" else row["credit"]))
                if row["code_tva"] not in ("NA", ""):
                    tax = _sub(line, "TaxInformation")
                    _sub(tax, "TaxType", "TVA")
                    _sub(tax, "TaxCode", row["code_tva"])
                    _sub(tax, "TaxCountryRegion", "LU")


def build_faia(journal: pd.DataFrame, pcn: pd.DataFrame, vat_codes: pd.DataFrame,
               run_config, third_parties: pd.DataFrame | None = None) -> ET.ElementTree:
    """Assemble the FAIA-shaped extract as an XML tree."""
    ET.register_namespace("", NAMESPACE)
    root = ET.Element(f"{{{NAMESPACE}}}AuditFile")
    _build_header(root, run_config, journal)
    _build_master_files(root, journal, pcn, vat_codes, third_parties)
    _build_entries(root, journal)
    return ET.ElementTree(root)


def write_faia(path: Path, journal: pd.DataFrame, pcn: pd.DataFrame,
               vat_codes: pd.DataFrame, run_config,
               third_parties: pd.DataFrame | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = build_faia(journal, pcn, vat_codes, run_config, third_parties)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path
