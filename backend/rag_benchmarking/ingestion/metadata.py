import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

FILENAME_RE = re.compile(
    r"^(?P<ticker>[A-Za-z0-9.-]+)_(?P<form>10-K|10-Q|8-K)_(?P<date>\d{8})\.pdf$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FilingMetadata:
    ticker: str
    form_type: str
    filing_date: date | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_filing_filename(path: Path) -> FilingMetadata:
    match = FILENAME_RE.match(path.name)
    if not match:
        ticker = path.parent.name.upper()
        return FilingMetadata(ticker=ticker, form_type="UNKNOWN", filing_date=None)
    raw_date = match.group("date")
    filing_date = date(int(raw_date[:4]), int(raw_date[4:6]), int(raw_date[6:8]))
    return FilingMetadata(
        ticker=match.group("ticker").upper(),
        form_type=match.group("form").upper(),
        filing_date=filing_date,
    )


def raw_object_key(*, dataset_id: str, ticker: str, form_type: str, filing_date: date | None, checksum: str) -> str:
    date_part = filing_date.isoformat() if filing_date else "unknown-date"
    return f"raw/{dataset_id}/{ticker}/{form_type}/{date_part}/{checksum}.pdf"
