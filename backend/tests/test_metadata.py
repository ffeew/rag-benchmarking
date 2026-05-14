from datetime import date
from pathlib import Path

from rag_benchmarking.ingestion.metadata import parse_filing_filename, raw_object_key


def test_parse_filing_filename_extracts_sec_metadata() -> None:
    metadata = parse_filing_filename(Path("sec_filings_pdf/MSFT/MSFT_10-K_20250730.pdf"))

    assert metadata.ticker == "MSFT"
    assert metadata.form_type == "10-K"
    assert metadata.filing_date == date(2025, 7, 30)


def test_raw_object_key_is_deterministic() -> None:
    key = raw_object_key(
        dataset_id="dataset-1",
        ticker="NVDA",
        form_type="10-Q",
        filing_date=date(2026, 5, 28),
        checksum="abc123",
    )

    assert key == "raw/dataset-1/NVDA/10-Q/2026-05-28/abc123.pdf"
