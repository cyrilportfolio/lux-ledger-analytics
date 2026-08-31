"""Reading and typing of the ledger and of the reference files.

Everything a French-language accounting export throws at a parser is handled
here: semicolon separator, comma as decimal mark, day-first dates, blank
cells for zero amounts, account numbers that must stay strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src import config

JOURNAL_COLUMNS = ["piece", "date", "journal", "compte", "libelle", "debit",
                   "credit", "code_tva", "tiers", "reference"]


@dataclass
class IngestReport:
    """What happened while reading the ledger."""

    source: Path
    rows_read: int = 0
    rows_kept: int = 0
    rejected: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def rows_rejected(self) -> int:
        return int(len(self.rejected))

    def summary(self) -> str:
        return (f"{self.source.name} : {self.rows_read} lignes lues, "
                f"{self.rows_kept} retenues, {self.rows_rejected} rejetees")


def _to_amount(series: pd.Series) -> pd.Series:
    """Convert a French-formatted amount column into floats."""
    cleaned = (series.astype("string")
               .fillna("")
               .str.replace(" ", "", regex=False)
               .str.replace(" ", "", regex=False)
               .str.replace(config.DECIMAL_SEPARATOR, ".", regex=False)
               .str.replace("€", "", regex=False)
               .str.strip())
    cleaned = cleaned.replace({"": None, "-": None})
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0).round(2)


def load_pcn(path: Path | None = None) -> pd.DataFrame:
    """Load the chart of accounts, indexed by account number as a string."""
    path = Path(path or config.PCN_FILE)
    frame = pd.read_csv(path, sep=config.CSV_SEPARATOR, dtype=str,
                        keep_default_na=False, encoding="utf-8")
    frame.columns = [c.strip().lower() for c in frame.columns]
    required = {"compte", "libelle", "classe", "type", "sens_normal",
                "rubrique", "poste"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name} : colonnes manquantes {sorted(missing)}")
    frame["compte"] = frame["compte"].str.strip()
    frame["type"] = frame["type"].str.strip().str.upper()
    frame["imputable"] = frame["type"].eq("I")
    frame["classe"] = frame["classe"].str.strip()
    for column in ("libelle", "rubrique", "poste", "sens_normal"):
        frame[column] = frame[column].str.strip()
    if frame["compte"].duplicated().any():
        doubles = frame.loc[frame["compte"].duplicated(), "compte"].tolist()
        raise ValueError(f"{path.name} : comptes en double {doubles}")
    return frame


def load_vat_codes(path: Path | None = None) -> pd.DataFrame:
    """Load the VAT code table (rate, direction, matching PCN account)."""
    path = Path(path or config.VAT_CODES_FILE)
    frame = pd.read_csv(path, sep=config.CSV_SEPARATOR, dtype=str,
                        keep_default_na=False, encoding="utf-8")
    frame.columns = [c.strip().lower() for c in frame.columns]
    frame["code"] = frame["code"].str.strip().str.upper()
    frame["taux"] = pd.to_numeric(frame["taux"], errors="coerce").fillna(0.0)
    frame["deductible"] = frame["deductible"].str.strip().eq("1")
    frame["sens"] = frame["sens"].str.strip().str.upper()
    frame["compte_tva"] = frame["compte_tva"].str.strip()
    if "compte_tva_autoliquidation" not in frame.columns:
        frame["compte_tva_autoliquidation"] = ""
    frame["compte_tva_autoliquidation"] = (
        frame["compte_tva_autoliquidation"].str.strip())
    return frame


def load_third_parties(path: Path) -> pd.DataFrame:
    """Load the customer and supplier directory, when one is provided."""
    path = Path(path)
    if not path.exists():
        return pd.DataFrame(columns=["code", "nom", "type", "numero_tva", "pays"])
    frame = pd.read_csv(path, sep=config.CSV_SEPARATOR, dtype=str,
                        keep_default_na=False, encoding="utf-8")
    frame.columns = [c.strip().lower() for c in frame.columns]
    for column in frame.columns:
        frame[column] = frame[column].str.strip()
    return frame


def load_journal(path: Path) -> tuple[pd.DataFrame, IngestReport]:
    """Read a ledger export and return a typed frame plus an ingest report.

    Rows whose date or account cannot be read at all are set aside in the
    report rather than silently dropped: a bookkeeper needs to see them.
    """
    path = Path(path)
    raw = pd.read_csv(path, sep=config.CSV_SEPARATOR, dtype=str,
                      keep_default_na=False, encoding="utf-8")
    raw.columns = [c.strip().lower() for c in raw.columns]

    missing = set(JOURNAL_COLUMNS) - set(raw.columns)
    if missing:
        raise ValueError(f"{path.name} : colonnes manquantes {sorted(missing)}")

    report = IngestReport(source=path, rows_read=len(raw))

    frame = raw.copy()
    frame["ligne"] = range(1, len(frame) + 1)
    for column in ("piece", "journal", "compte", "libelle", "code_tva",
                   "tiers", "reference"):
        frame[column] = frame[column].astype("string").fillna("").str.strip()
    frame["journal"] = frame["journal"].str.upper()
    frame["code_tva"] = frame["code_tva"].str.upper().replace({"": "NA"})
    frame["compte"] = frame["compte"].str.replace(" ", "", regex=False)

    frame["date"] = pd.to_datetime(frame["date"], format=config.DATE_FORMAT,
                                   errors="coerce")
    frame["debit"] = _to_amount(frame["debit"])
    frame["credit"] = _to_amount(frame["credit"])

    unreadable = frame["date"].isna() | frame["compte"].eq("")
    report.rejected = frame.loc[unreadable].copy()
    frame = frame.loc[~unreadable].copy()

    frame["montant"] = (frame["debit"] - frame["credit"]).round(2)
    frame["classe"] = frame["compte"].str[0]
    frame["periode"] = frame["date"].dt.to_period("M").astype(str)
    frame["annee"] = frame["date"].dt.year

    report.rows_kept = len(frame)
    return frame.reset_index(drop=True), report


def enrich_with_pcn(journal: pd.DataFrame, pcn: pd.DataFrame) -> pd.DataFrame:
    """Attach the chart-of-accounts attributes to every posting."""
    columns = ["compte", "libelle", "type", "imputable", "rubrique", "poste",
               "sens_normal"]
    reference = pcn[columns].rename(columns={
        "libelle": "libelle_compte",
        "type": "type_compte",
        "sens_normal": "sens_compte",
    })
    merged = journal.merge(reference, on="compte", how="left", validate="many_to_one")
    merged["connu"] = merged["libelle_compte"].notna()
    merged["imputable"] = merged["imputable"].fillna(False)
    return merged
