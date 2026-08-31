"""Synthetic ledger generator.

Produces two CSV files that mimic what a Luxembourg accounting package
exports for a small trading company:

* ``journal_clean.csv`` - a full financial year, every voucher balanced;
* ``journal_dirty.csv`` - the same year with deliberately injected defects,
  each one listed in ``anomalies_attendues.csv`` so the checks can be
  scored against a known truth.

No client data is involved: names, amounts and dates are generated.
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from src import config

SEED = 20250101

fake = Faker("fr_FR")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _money(value: float) -> float:
    """Round to the cent the way an accounting package does."""
    return float(f"{value:.2f}")


def _fr(value: float) -> str:
    """Format an amount with the French decimal comma, blank when zero."""
    if value is None or abs(value) < 1e-9:
        return ""
    return f"{value:.2f}".replace(".", config.DECIMAL_SEPARATOR)


@dataclass
class Line:
    piece: str
    date_ecriture: date
    journal: str
    compte: str
    libelle: str
    debit: float = 0.0
    credit: float = 0.0
    code_tva: str = "NA"
    tiers: str = ""
    reference: str = ""


@dataclass
class Ledger:
    lines: list[Line] = field(default_factory=list)
    counters: dict = field(default_factory=dict)

    def next_piece(self, journal: str, year: int) -> str:
        self.counters[journal] = self.counters.get(journal, 0) + 1
        return f"{journal}{year}{self.counters[journal]:05d}"

    def add(self, **kwargs) -> None:
        self.lines.append(Line(**kwargs))


# --------------------------------------------------------------------------
# Reference data used by the generator
# --------------------------------------------------------------------------
SALES_PROFILES = [
    # (account, VAT code, weight, label)
    ("704000", "S17", 40, "Prestation de services"),
    ("702000", "S17", 25, "Vente de marchandises"),
    ("702000", "S8", 8, "Vente de marchandises - taux reduit"),
    ("702000", "S3", 6, "Vente de biens - taux super-reduit"),
    ("705000", "S17", 8, "Vente de produits finis"),
    ("704000", "SIC", 8, "Prestation intracommunautaire"),
    ("702000", "SEX", 3, "Exportation hors UE"),
    ("708000", "S14", 2, "Produit annexe - taux intermediaire"),
]

PURCHASE_PROFILES = [
    # (account, VAT code, weight, label, minimum, maximum)
    ("606000", "A17", 20, "Achat de marchandises", 1800, 14000),
    ("606000", "A8", 6, "Achat de marchandises - taux reduit", 900, 6500),
    ("601000", "A17", 5, "Achat de matieres premieres", 700, 5200),
    ("607100", "A17", 6, "Fournitures de bureau", 90, 850),
    ("607200", "A8", 7, "Electricite et gaz", 380, 1900),
    ("607300", "A17", 5, "Carburant", 120, 900),
    ("611000", "A0", 6, "Loyer du mois", 3200, 3200),
    ("611500", "A17", 4, "Charges locatives", 180, 720),
    ("612000", "A17", 5, "Entretien et reparations", 250, 3400),
    ("613000", "A0", 4, "Prime d'assurance", 400, 2600),
    ("614100", "A17", 5, "Honoraires comptables", 650, 3800),
    ("614200", "A17", 3, "Honoraires juridiques", 500, 4200),
    ("614300", "A17", 5, "Abonnements logiciels", 120, 1600),
    ("615000", "A17", 4, "Campagne de publicite", 300, 5200),
    ("616100", "A17", 4, "Transport sur achats", 150, 1400),
    ("616200", "A3", 5, "Frais de restaurant", 45, 380),
    ("617000", "A17", 5, "Telecommunications", 160, 1100),
    ("606000", "AIC", 5, "Acquisition intracommunautaire", 1500, 11000),
]

VAT_BY_CODE = {
    "S17": ("461411", 0.17),
    "S14": ("461412", 0.14),
    "S8": ("461413", 0.08),
    "S3": ("461414", 0.03),
    "SIC": (None, 0.0),
    "SEX": (None, 0.0),
    "A17": ("421611", 0.17),
    "A14": ("421612", 0.14),
    "A8": ("421613", 0.08),
    "A3": ("421614", 0.03),
    "A0": (None, 0.0),
    "AIC": ("421611", 0.17),
}


def _weighted_choice(rng: random.Random, profiles):
    total = sum(p[2] for p in profiles)
    draw = rng.uniform(0, total)
    running = 0.0
    for profile in profiles:
        running += profile[2]
        if draw <= running:
            return profile
    return profiles[-1]


def _business_days(rng: random.Random, start: date, end: date) -> date:
    span = (end - start).days
    while True:
        candidate = start + timedelta(days=rng.randint(0, span))
        if candidate.weekday() < 5:
            return candidate


# --------------------------------------------------------------------------
# Voucher builders
# --------------------------------------------------------------------------
def build_opening_balances(ledger: Ledger, start: date) -> None:
    """Opening entries, class 1 to 5, balanced through retained earnings."""
    piece = ledger.next_piece("AN", start.year)
    rows = [
        ("221200", "Constructions", 180000.0, 0.0),
        ("222100", "Installations techniques et machines", 62000.0, 0.0),
        ("223100", "Mobilier et materiel de bureau", 18500.0, 0.0),
        ("223200", "Materiel informatique", 24800.0, 0.0),
        ("223300", "Materiel roulant", 41000.0, 0.0),
        ("211100", "Logiciels et licences", 12400.0, 0.0),
        ("221900", "Corrections de valeur sur constructions", 0.0, 43200.0),
        ("222900", "Corrections de valeur sur installations", 0.0, 28900.0),
        ("223900", "Corrections de valeur sur autres installations", 0.0, 39600.0),
        ("211900", "Corrections de valeur sur logiciels", 0.0, 7440.0),
        ("236000", "Depots et cautionnements verses", 6000.0, 0.0),
        ("361000", "Stocks de marchandises", 48750.0, 0.0),
        ("401100", "Clients - solde d'ouverture", 74300.0, 0.0),
        ("511100", "Banque - compte courant principal", 52180.0, 0.0),
        ("516000", "Caisse", 940.0, 0.0),
        ("481000", "Charges a reporter", 3200.0, 0.0),
        ("441100", "Fournisseurs - solde d'ouverture", 0.0, 58420.0),
        ("101100", "Capital souscrit", 0.0, 100000.0),
        ("131000", "Reserve legale", 0.0, 10000.0),
        ("138000", "Autres reserves disponibles", 0.0, 25000.0),
        ("192100", "Emprunt a moyen et long terme", 0.0, 96000.0),
        ("462000", "Centre commun de la securite sociale", 0.0, 9350.0),
        ("471000", "Personnel - remunerations dues", 0.0, 14100.0),
        ("461500", "TVA due - decompte de decembre", 0.0, 7830.0),
    ]
    total_debit = sum(r[2] for r in rows)
    total_credit = sum(r[3] for r in rows)
    balancing = _money(total_debit - total_credit)

    for account, label, debit, credit in rows:
        ledger.add(
            piece=piece,
            date_ecriture=start,
            journal="AN",
            compte=account,
            libelle=label,
            debit=_money(debit),
            credit=_money(credit),
            code_tva="NA",
            reference="AN-2025",
        )
    ledger.add(
        piece=piece,
        date_ecriture=start,
        journal="AN",
        compte="141000",
        libelle="Resultats reportes",
        debit=_money(-balancing) if balancing < 0 else 0.0,
        credit=_money(balancing) if balancing > 0 else 0.0,
        code_tva="NA",
        reference="AN-2025",
    )


def build_sales(ledger: Ledger, rng: random.Random, customers, start, end, count):
    """Sales invoices: customer debited VAT inclusive, revenue and VAT credited."""
    invoices = []
    for _ in range(count):
        account, vat_code, _, label = _weighted_choice(rng, SALES_PROFILES)
        vat_account, rate = VAT_BY_CODE[vat_code]
        base = _money(rng.choice([1, 1, 1, 2, 4]) * rng.uniform(180, 4200))
        vat = _money(base * rate)
        gross = _money(base + vat)
        when = _business_days(rng, start, end)
        piece = ledger.next_piece("VE", start.year)
        customer = rng.choice(customers)
        reference = f"FV{when.strftime('%Y%m')}-{piece[-4:]}"

        ledger.add(piece=piece, date_ecriture=when, journal="VE", compte="401100",
                   libelle=f"{customer['nom']} - {label}", debit=gross, credit=0.0,
                   code_tva="NA", tiers=customer["code"], reference=reference)
        ledger.add(piece=piece, date_ecriture=when, journal="VE", compte=account,
                   libelle=label, debit=0.0, credit=base,
                   code_tva=vat_code, tiers=customer["code"], reference=reference)
        if vat_account and vat > 0:
            ledger.add(piece=piece, date_ecriture=when, journal="VE", compte=vat_account,
                       libelle=f"TVA collectee {int(rate * 100)}%", debit=0.0, credit=vat,
                       code_tva="NA", tiers=customer["code"], reference=reference)
        invoices.append({"piece": piece, "date": when, "tiers": customer["code"],
                         "montant": gross, "reference": reference,
                         "nom": customer["nom"]})
    return invoices


def build_purchases(ledger: Ledger, rng: random.Random, suppliers, start, end, count):
    """Purchase invoices: expense and input VAT debited, supplier credited."""
    invoices = []
    for _ in range(count):
        account, vat_code, _, label, low, high = _weighted_choice(
            rng, PURCHASE_PROFILES)
        vat_account, rate = VAT_BY_CODE[vat_code]
        base = _money(rng.uniform(low, high))
        vat = _money(base * rate)
        when = _business_days(rng, start, end)
        piece = ledger.next_piece("AC", start.year)
        supplier = rng.choice(suppliers)
        reference = f"FA{when.strftime('%Y%m')}-{piece[-4:]}"

        if vat_code == "AIC":
            # Reverse charge: the invoice itself carries no VAT, both sides
            # of the tax are booked so the voucher stays balanced.
            gross = base
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte=account,
                       libelle=label, debit=base, credit=0.0, code_tva=vat_code,
                       tiers=supplier["code"], reference=reference)
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte="421611",
                       libelle="TVA deductible sur acquisition intracommunautaire",
                       debit=vat, credit=0.0, code_tva="NA",
                       tiers=supplier["code"], reference=reference)
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte="461411",
                       libelle="TVA due sur acquisition intracommunautaire",
                       debit=0.0, credit=vat, code_tva="NA",
                       tiers=supplier["code"], reference=reference)
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte="441100",
                       libelle=f"{supplier['nom']} - {label}", debit=0.0, credit=gross,
                       code_tva="NA", tiers=supplier["code"], reference=reference)
        else:
            gross = _money(base + vat)
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte=account,
                       libelle=label, debit=base, credit=0.0, code_tva=vat_code,
                       tiers=supplier["code"], reference=reference)
            if vat_account and vat > 0:
                ledger.add(piece=piece, date_ecriture=when, journal="AC", compte=vat_account,
                           libelle=f"TVA deductible {int(rate * 100)}%", debit=vat,
                           credit=0.0, code_tva="NA", tiers=supplier["code"],
                           reference=reference)
            ledger.add(piece=piece, date_ecriture=when, journal="AC", compte="441100",
                       libelle=f"{supplier['nom']} - {label}", debit=0.0, credit=gross,
                       code_tva="NA", tiers=supplier["code"], reference=reference)
        invoices.append({"piece": piece, "date": when, "tiers": supplier["code"],
                         "montant": gross, "reference": reference,
                         "nom": supplier["nom"]})
    return invoices


def build_settlements(ledger: Ledger, rng: random.Random, sales, purchases, end):
    """Bank settlements, partial by design so sub-ledgers keep open items."""
    for invoice in sales:
        if rng.random() < 0.82:
            when = min(invoice["date"] + timedelta(days=rng.randint(12, 75)), end)
            piece = ledger.next_piece("BQ", end.year)
            amount = invoice["montant"]
            if rng.random() < 0.06:  # part payment
                amount = _money(amount * rng.uniform(0.4, 0.7))
            ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="511100",
                       libelle=f"Encaissement {invoice['reference']}", debit=amount,
                       credit=0.0, code_tva="NA", tiers=invoice["tiers"],
                       reference=invoice["reference"])
            ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="401100",
                       libelle=f"{invoice['nom']} - reglement", debit=0.0, credit=amount,
                       code_tva="NA", tiers=invoice["tiers"],
                       reference=invoice["reference"])

    for invoice in purchases:
        if rng.random() < 0.78:
            when = min(invoice["date"] + timedelta(days=rng.randint(10, 60)), end)
            piece = ledger.next_piece("BQ", end.year)
            amount = invoice["montant"]
            ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="441100",
                       libelle=f"{invoice['nom']} - reglement", debit=amount, credit=0.0,
                       code_tva="NA", tiers=invoice["tiers"],
                       reference=invoice["reference"])
            ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="511100",
                       libelle=f"Paiement {invoice['reference']}", debit=0.0,
                       credit=amount, code_tva="NA", tiers=invoice["tiers"],
                       reference=invoice["reference"])


def build_bank_charges(ledger: Ledger, rng: random.Random, start: date):
    """Monthly bank fees and loan instalments."""
    for month in range(1, 13):
        when = date(start.year, month, 28)
        piece = ledger.next_piece("BQ", start.year)
        fee = _money(rng.uniform(28, 74))
        ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="618000",
                   libelle="Frais de tenue de compte", debit=fee, credit=0.0,
                   code_tva="NA", reference=f"BQ-FRAIS-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="511100",
                   libelle="Frais bancaires", debit=0.0, credit=fee,
                   code_tva="NA", reference=f"BQ-FRAIS-{month:02d}")

        piece = ledger.next_piece("BQ", start.year)
        principal = 1600.0
        interest = _money((96000 - (month - 1) * principal) * 0.031 / 12)
        ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="192100",
                   libelle="Remboursement emprunt - capital", debit=principal,
                   credit=0.0, code_tva="NA", reference=f"EMP-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="655000",
                   libelle="Interets de l'emprunt", debit=interest, credit=0.0,
                   code_tva="NA", reference=f"EMP-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="BQ", compte="511100",
                   libelle="Echeance emprunt", debit=0.0,
                   credit=_money(principal + interest), code_tva="NA",
                   reference=f"EMP-{month:02d}")


def build_payroll(ledger: Ledger, rng: random.Random, start: date):
    """Monthly payroll posting plus its settlement the following month."""
    for month in range(1, 13):
        when = date(start.year, month, 25)
        gross = _money(rng.uniform(21000, 24500))
        employer = _money(gross * 0.13)
        employee = _money(gross * 0.125)
        net = _money(gross - employee)
        social = _money(employer + employee)

        piece = ledger.next_piece("OD", start.year)
        ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="621000",
                   libelle=f"Salaires bruts {month:02d}/{start.year}", debit=gross,
                   credit=0.0, code_tva="NA", reference=f"PAIE-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="622000",
                   libelle=f"Charges patronales {month:02d}/{start.year}",
                   debit=employer, credit=0.0, code_tva="NA",
                   reference=f"PAIE-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="462000",
                   libelle="Cotisations CCSS", debit=0.0, credit=social,
                   code_tva="NA", reference=f"PAIE-{month:02d}")
        ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="471000",
                   libelle="Net a payer", debit=0.0, credit=net, code_tva="NA",
                   reference=f"PAIE-{month:02d}")

        pay_date = date(start.year, month, 28)
        piece = ledger.next_piece("BQ", start.year)
        ledger.add(piece=piece, date_ecriture=pay_date, journal="BQ", compte="471000",
                   libelle="Virement des salaires", debit=net, credit=0.0,
                   code_tva="NA", reference=f"PAIE-{month:02d}")
        ledger.add(piece=piece, date_ecriture=pay_date, journal="BQ", compte="511100",
                   libelle="Virement des salaires", debit=0.0, credit=net,
                   code_tva="NA", reference=f"PAIE-{month:02d}")

        piece = ledger.next_piece("BQ", start.year)
        ledger.add(piece=piece, date_ecriture=pay_date, journal="BQ", compte="462000",
                   libelle="Paiement CCSS", debit=social, credit=0.0, code_tva="NA",
                   reference=f"CCSS-{month:02d}")
        ledger.add(piece=piece, date_ecriture=pay_date, journal="BQ", compte="511100",
                   libelle="Paiement CCSS", debit=0.0, credit=social, code_tva="NA",
                   reference=f"CCSS-{month:02d}")


def build_depreciation(ledger: Ledger, start: date):
    """Quarterly depreciation charge, straight line, per asset class."""
    schedule = [
        ("221900", 180000.0, 40),
        ("222900", 62000.0, 10),
        ("223900", 84300.0, 5),
        ("211900", 12400.0, 4),
    ]
    for quarter, month in enumerate((3, 6, 9, 12), start=1):
        when = date(start.year, month, 1) + timedelta(days=27)
        piece = ledger.next_piece("OD", start.year)
        total = 0.0
        for account, base_value, life in schedule:
            charge = _money(base_value / life / 4)
            total = _money(total + charge)
            ledger.add(piece=piece, date_ecriture=when, journal="OD", compte=account,
                       libelle=f"Amortissement T{quarter}", debit=0.0, credit=charge,
                       code_tva="NA", reference=f"AMORT-T{quarter}")
        ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="631000",
                   libelle=f"Dotation aux amortissements T{quarter}", debit=total,
                   credit=0.0, code_tva="NA", reference=f"AMORT-T{quarter}")


def build_income_tax(ledger: Ledger, rng: random.Random, end: date):
    """Year-end tax accrual on the pre-tax result.

    Rates used are the Luxembourg City combination in force for a resident
    company: corporate income tax at 17 % increased by the 7 % employment
    fund contribution, plus municipal business tax at 6.75 %.
    """
    pre_tax = _money(sum(
        line.credit - line.debit for line in ledger.lines
        if line.compte[:1] in ("6", "7")))
    if pre_tax <= 0:
        return
    corporate = _money(pre_tax * 0.17 * 1.07)
    municipal = _money(pre_tax * 0.0675)
    wealth = _money(rng.uniform(3200, 5400))

    piece = ledger.next_piece("OD", end.year)
    ledger.add(piece=piece, date_ecriture=end, journal="OD", compte="671000",
               libelle="Impot sur le revenu des collectivites", debit=corporate,
               credit=0.0, code_tva="NA", reference="IMPOT-2025")
    ledger.add(piece=piece, date_ecriture=end, journal="OD", compte="672000",
               libelle="Impot commercial communal", debit=municipal, credit=0.0,
               code_tva="NA", reference="IMPOT-2025")
    ledger.add(piece=piece, date_ecriture=end, journal="OD", compte="461700",
               libelle="Impots sur le resultat a payer", debit=0.0,
               credit=_money(corporate + municipal), code_tva="NA",
               reference="IMPOT-2025")

    piece = ledger.next_piece("OD", end.year)
    ledger.add(piece=piece, date_ecriture=end, journal="OD", compte="681000",
               libelle="Impot sur la fortune", debit=wealth, credit=0.0,
               code_tva="NA", reference="IF-2025")
    ledger.add(piece=piece, date_ecriture=end, journal="OD", compte="461700",
               libelle="Impot sur la fortune a payer", debit=0.0, credit=wealth,
               code_tva="NA", reference="IF-2025")


def build_vat_returns(ledger: Ledger, start: date):
    """Monthly VAT clearing entry, computed from the postings already made."""
    for month in range(1, 13):
        period_lines = [
            line for line in ledger.lines
            if line.date_ecriture.month == month
            and line.journal in ("VE", "AC")
            and (line.compte in config.OUTPUT_VAT_ACCOUNTS
                 or line.compte in config.INPUT_VAT_ACCOUNTS)
        ]
        if not period_lines:
            continue
        # The period is cleared on the last day of the month it relates to,
        # so that the balance sheet shows the VAT actually owed at closing.
        if month == 12:
            when = date(start.year, 12, 31)
        else:
            when = date(start.year, month + 1, 1) - timedelta(days=1)
        piece = ledger.next_piece("OD", start.year)

        collected = {}
        deductible = {}
        for line in period_lines:
            if line.compte in config.OUTPUT_VAT_ACCOUNTS:
                collected[line.compte] = _money(
                    collected.get(line.compte, 0.0) + line.credit - line.debit)
            else:
                deductible[line.compte] = _money(
                    deductible.get(line.compte, 0.0) + line.debit - line.credit)

        total_collected = _money(sum(collected.values()))
        total_deductible = _money(sum(deductible.values()))
        due = _money(total_collected - total_deductible)
        if abs(due) < 0.01 and not collected and not deductible:
            continue

        for account, amount in collected.items():
            if abs(amount) < 0.01:
                continue
            ledger.add(piece=piece, date_ecriture=when, journal="OD", compte=account,
                       libelle=f"Solde TVA collectee {month:02d}/{start.year}",
                       debit=amount, credit=0.0, code_tva="NA",
                       reference=f"TVA-{month:02d}")
        for account, amount in deductible.items():
            if abs(amount) < 0.01:
                continue
            ledger.add(piece=piece, date_ecriture=when, journal="OD", compte=account,
                       libelle=f"Solde TVA deductible {month:02d}/{start.year}",
                       debit=0.0, credit=amount, code_tva="NA",
                       reference=f"TVA-{month:02d}")
        if due >= 0:
            ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="461500",
                       libelle=f"TVA due {month:02d}/{start.year}", debit=0.0,
                       credit=due, code_tva="NA", reference=f"TVA-{month:02d}")
        else:
            ledger.add(piece=piece, date_ecriture=when, journal="OD", compte="421617",
                       libelle=f"Credit de TVA {month:02d}/{start.year}",
                       debit=_money(-due), credit=0.0, code_tva="NA",
                       reference=f"TVA-{month:02d}")


# --------------------------------------------------------------------------
# Defect injection
# --------------------------------------------------------------------------
def inject_anomalies(lines: list[Line], rng: random.Random, fiscal_end: date):
    """Return a defective copy of the ledger plus the list of what was done."""
    dirty = [Line(**vars(line)) for line in lines]
    expected: list[dict] = []

    def note(code, piece, detail):
        expected.append({"code_controle": code, "piece": piece, "detail": detail})

    by_piece: dict[str, list[Line]] = {}
    for line in dirty:
        by_piece.setdefault(line.piece, []).append(line)

    sales_pieces = [p for p, ls in by_piece.items() if p.startswith("VE")]
    purchase_pieces = [p for p, ls in by_piece.items() if p.startswith("AC")]
    bank_pieces = [p for p, ls in by_piece.items() if p.startswith("BQ")]

    # 1. Unbalanced vouchers -------------------------------------------------
    for piece in rng.sample(sales_pieces, 3) + rng.sample(purchase_pieces, 2):
        target = by_piece[piece][0]
        if target.debit:
            target.debit = _money(target.debit + rng.choice([12.5, 100.0, 0.9]))
        else:
            target.credit = _money(target.credit + rng.choice([12.5, 100.0, 0.9]))
        note("PIECE_DESEQUILIBREE", piece, "montant modifie sur une ligne")

    # 2. Accounts absent from the chart of accounts ---------------------------
    for piece in rng.sample(purchase_pieces, 3):
        target = by_piece[piece][0]
        target.compte = rng.choice(["606999", "999000", "615999"])
        note("COMPTE_INCONNU", piece, f"compte {target.compte} hors PCN")

    # 3. Postings on a grouping account (not allowed by the PCN 2020) --------
    for piece in rng.sample(purchase_pieces, 3):
        target = by_piece[piece][0]
        target.compte = rng.choice(["61", "614", "60"])
        note("COMPTE_NON_IMPUTABLE", piece, f"compte de regroupement {target.compte}")

    # 4. Duplicated vouchers -------------------------------------------------
    for piece in rng.sample(sales_pieces, 2):
        for line in by_piece[piece]:
            dirty.append(Line(**vars(line)))
        note("DOUBLON", piece, "piece dupliquee a l'identique")

    # 5. Dates outside the financial year -------------------------------------
    for piece in rng.sample(sales_pieces, 2):
        for line in by_piece[piece]:
            line.date_ecriture = fiscal_end + timedelta(days=rng.randint(4, 40))
        note("DATE_HORS_EXERCICE", piece, "date posterieure a la cloture")
    for piece in rng.sample(purchase_pieces, 1):
        for line in by_piece[piece]:
            line.date_ecriture = date(fiscal_end.year - 1, 12, 27)
        note("DATE_HORS_EXERCICE", piece, "date anterieure a l'ouverture")

    # 6. Outlier amounts -----------------------------------------------------
    for piece in rng.sample(purchase_pieces, 2):
        for line in by_piece[piece]:
            line.debit = _money(line.debit * 1000)
            line.credit = _money(line.credit * 1000)
        note("MONTANT_ABERRANT", piece, "montants multiplies par mille")

    # 7. VAT amount inconsistent with the code --------------------------------
    fixed = 0
    for piece in sales_pieces:
        lines_of_piece = by_piece[piece]
        vat_line = next((l for l in lines_of_piece
                         if l.compte in config.OUTPUT_VAT_ACCOUNTS), None)
        base_line = next((l for l in lines_of_piece if l.code_tva == "S17"), None)
        if vat_line and base_line and fixed < 4:
            vat_line.credit = _money(base_line.credit * 0.14)
            note("TVA_INCOHERENTE", piece, "TVA calculee a 14% pour un code a 17%")
            fixed += 1
        if fixed >= 4:
            break

    # 8. VAT code on a treasury account ---------------------------------------
    for piece in rng.sample(bank_pieces, 2):
        target = next((l for l in by_piece[piece] if l.compte.startswith("511")), None)
        if target:
            target.code_tva = "A17"
            note("CODE_TVA_INTERDIT", piece, "code TVA sur un compte de tresorerie")

    # 9. Both debit and credit filled on the same posting ---------------------
    for piece in rng.sample(purchase_pieces, 2):
        target = by_piece[piece][0]
        target.credit = _money(target.debit / 2)
        note("DEBIT_ET_CREDIT", piece, "ligne servie des deux cotes")

    # 10. Postings with no amount ---------------------------------------------
    for piece in rng.sample(sales_pieces, 2):
        model = by_piece[piece][0]
        dirty.append(Line(piece=model.piece, date_ecriture=model.date_ecriture,
                          journal=model.journal, compte="748000",
                          libelle="Ligne sans montant", debit=0.0, credit=0.0,
                          code_tva="NA", tiers=model.tiers,
                          reference=model.reference))
        note("LIGNE_SANS_MONTANT", piece, "ligne a zero ajoutee")

    # 11. Missing vouchers, which break the numbering sequence ----------------
    touched = {entry["piece"] for entry in expected}
    candidates = [p for p in purchase_pieces if p not in touched]
    for piece in rng.sample(candidates, 2):
        dirty = [line for line in dirty if line.piece != piece]
        note("SEQUENCE_INTERROMPUE", piece, "piece absente du journal")

    return dirty, expected


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------
HEADER = ["piece", "date", "journal", "compte", "libelle", "debit", "credit",
          "code_tva", "tiers", "reference"]


def write_journal(lines: list[Line], path: Path) -> None:
    ordered = sorted(lines, key=lambda l: (l.date_ecriture, l.journal, l.piece))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=config.CSV_SEPARATOR)
        writer.writerow(HEADER)
        for line in ordered:
            writer.writerow([
                line.piece,
                line.date_ecriture.strftime(config.DATE_FORMAT),
                line.journal,
                line.compte,
                line.libelle,
                _fr(line.debit),
                _fr(line.credit),
                line.code_tva,
                line.tiers,
                line.reference,
            ])


def write_expected(expected: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["code_controle", "piece", "detail"],
                                delimiter=config.CSV_SEPARATOR)
        writer.writeheader()
        writer.writerows(expected)


def write_third_parties(customers, suppliers, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=config.CSV_SEPARATOR)
        writer.writerow(["code", "nom", "type", "numero_tva", "pays"])
        for entry in customers:
            writer.writerow([entry["code"], entry["nom"], "CLIENT",
                             entry["tva"], entry["pays"]])
        for entry in suppliers:
            writer.writerow([entry["code"], entry["nom"], "FOURNISSEUR",
                             entry["tva"], entry["pays"]])


def _make_third_parties(rng: random.Random, prefix: str, count: int):
    countries = ["LU"] * 6 + ["BE", "FR", "DE"]
    entries = []
    for index in range(1, count + 1):
        country = rng.choice(countries)
        entries.append({
            "code": f"{prefix}{index:04d}",
            "nom": fake.company().replace(";", " ").upper(),
            "tva": f"{country}{rng.randint(10000000, 99999999)}",
            "pays": country,
        })
    return entries


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic Luxembourg ledgers.")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR,
                        help="directory where the CSV files are written")
    parser.add_argument("--sales", type=int, default=300,
                        help="number of sales invoices")
    parser.add_argument("--purchases", type=int, default=250,
                        help="number of purchase invoices")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    Faker.seed(args.seed)

    start = config.FISCAL_YEAR_START
    end = config.FISCAL_YEAR_END

    customers = _make_third_parties(rng, "C", 28)
    suppliers = _make_third_parties(rng, "F", 22)

    ledger = Ledger()
    build_opening_balances(ledger, start)
    sales = build_sales(ledger, rng, customers, start, end, args.sales)
    purchases = build_purchases(ledger, rng, suppliers, start, end, args.purchases)
    build_settlements(ledger, rng, sales, purchases, end)
    build_bank_charges(ledger, rng, start)
    build_payroll(ledger, rng, start)
    build_depreciation(ledger, start)
    build_income_tax(ledger, rng, end)
    build_vat_returns(ledger, start)

    args.out.mkdir(parents=True, exist_ok=True)
    write_journal(ledger.lines, args.out / "journal_clean.csv")
    write_third_parties(customers, suppliers, args.out / "tiers.csv")

    dirty, expected = inject_anomalies(ledger.lines, rng, end)
    write_journal(dirty, args.out / "journal_dirty.csv")
    write_expected(expected, args.out / "anomalies_attendues.csv")

    print(f"journal_clean.csv : {len(ledger.lines)} lignes, "
          f"{len({l.piece for l in ledger.lines})} pieces")
    print(f"journal_dirty.csv : {len(dirty)} lignes, "
          f"{len(expected)} anomalies injectees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
