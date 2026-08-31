"""Shared configuration for the lux-ledger-analytics pipeline.

All business constants that a Luxembourg bookkeeper would want to change
without touching the code live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"

PCN_FILE = DATA_DIR / "pcn_2020.csv"
VAT_CODES_FILE = DATA_DIR / "tva_codes.csv"

CSV_SEPARATOR = ";"
DECIMAL_SEPARATOR = ","
DATE_FORMAT = "%d/%m/%Y"

# --------------------------------------------------------------------------
# Accounting entity
# --------------------------------------------------------------------------
COMPANY_NAME = "DEMO LUX SARL"
COMPANY_VAT_NUMBER = "LU12345678"
COMPANY_RCS = "B123456"
CURRENCY = "EUR"

FISCAL_YEAR_START = date(2025, 1, 1)
FISCAL_YEAR_END = date(2025, 12, 31)

# --------------------------------------------------------------------------
# Tolerances
# --------------------------------------------------------------------------
# Rounding tolerance, in euros, when checking that a voucher balances.
BALANCE_TOLERANCE = 0.01
# Rounding tolerance, in euros, when recomputing VAT from its taxable base.
VAT_TOLERANCE = 0.02
# How many times the median of its own account a posting may reach before
# it is flagged as atypical.
OUTLIER_RATIO = 60.0
# Absolute floor, in euros, below which an atypical ratio is not worth raising.
OUTLIER_FLOOR = 1000.0
# Minimum number of postings on an account before outlier detection applies.
OUTLIER_MIN_POPULATION = 5

# --------------------------------------------------------------------------
# Luxembourg VAT rates in force (Memorial A, standard regime)
# --------------------------------------------------------------------------
VAT_RATES = {
    "normal": 0.17,
    "intermediaire": 0.14,
    "reduit": 0.08,
    "super_reduit": 0.03,
}

# PCN account ranges that must never carry a VAT code.
NON_VAT_ACCOUNT_CLASSES = ("1", "5")

# PCN accounts holding VAT itself (output / input), by direction.
OUTPUT_VAT_ACCOUNTS = ("461411", "461412", "461413", "461414")
INPUT_VAT_ACCOUNTS = ("421611", "421612", "421613", "421614")
VAT_SETTLEMENT_ACCOUNT = "461500"

# Journals expected in the ledger.
JOURNALS = {
    "AN": "A-nouveaux",
    "VE": "Ventes",
    "AC": "Achats",
    "BQ": "Banque",
    "OD": "Operations diverses",
}

# Sub-ledger prefixes used for the auxiliary balances.
CUSTOMER_ACCOUNT_PREFIX = "401"
SUPPLIER_ACCOUNT_PREFIX = "441"


@dataclass(frozen=True)
class Severity:
    """Severity levels used by the quality checks."""

    BLOCKING: str = "bloquant"
    MAJOR: str = "majeur"
    MINOR: str = "mineur"


SEVERITY = Severity()


@dataclass
class RunConfig:
    """Runtime options resolved from the command line."""

    journal_file: Path
    output_dir: Path = OUTPUT_DIR
    pcn_file: Path = PCN_FILE
    vat_codes_file: Path = VAT_CODES_FILE
    fiscal_year_start: date = FISCAL_YEAR_START
    fiscal_year_end: date = FISCAL_YEAR_END
    company_name: str = COMPANY_NAME
    vat_number: str = COMPANY_VAT_NUMBER
    with_faia: bool = False
    fail_on_blocking: bool = False
    tags: list[str] = field(default_factory=list)
