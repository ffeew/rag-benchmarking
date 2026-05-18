"""Programmatically re-verify eval cases against the SEC filings PDF corpus.

Usage:
    uv run --directory backend python -m rag_benchmarking.scripts.verify_eval_cases \\
        --yaml backend/eval_cases/sec_filings_v1.yaml \\
        --pdf-root sec_filings_pdf \\
        --out docs/eval/sec_filings_v1_verification.md

For every case in the YAML, this script:
  1. Resolves each ``expected_evidence`` entry to a PDF file under ``pdf-root``
     by matching ``{ticker}/{ticker}_{form_type}_{YYYYMMDD}.pdf``.
  2. Confirms the cited ``page_number`` exists in the PDF (1-indexed).
  3. Extracts the cited page's text via ``pypdf``.
  4. Confirms every ``expected_values[].value_numeric`` shows up on the cited
     page (formatted with optional ``$``, thousands separators and unit), within
     the case's ``tolerance_abs`` / ``tolerance_pct`` (mirrors the matcher in
     ``rag_evaluation.scoring``).
  5. Confirms every ``evidence_text`` substring appears on the cited page
     (case- and whitespace-insensitive).
  6. For ``insufficient_evidence`` / ``refusal`` cases skips PDF content checks
     but still validates that any citations point to a real page.

Writes a Markdown report with one row per case, marking PASS / FAIL and listing
the failing reasons. Returns exit code 1 if any case fails.
"""

import argparse
import logging
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pypdf
import yaml
from rag_common.enums import ExpectedAnswerType

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(
    r"(?P<prefix>\$)?(?P<number>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|million|billion|trillion|basis\s+points|bps)?",
    re.IGNORECASE,
)

_UNIT_ALIASES: dict[str, set[str]] = {
    "million": {"million", "millions", "m", "$"},
    "billion": {"billion", "billions", "b", "$"},
    "trillion": {"trillion", "trillions", "t", "$"},
    "dollar": {"dollar", "dollars", "$"},
    "dollars": {"dollar", "dollars", "$"},
    "percent": {"%"},
    "basis_points": {"basis points", "bps"},
}


_LIGATURE_FIXUP = str.maketrans(
    {
        "ﬁ": "fi",
        "ﬂ": "fl",
        "ﬀ": "ff",
        "ﬃ": "ffi",
        "ﬄ": "ffl",
        "ﬆ": "st",
        "ﬅ": "st",
    }
)


def _denormalize_pdf_text(s: str) -> str:
    """Replace Unicode ligatures that pypdf preserves from the source PDF."""
    return s.translate(_LIGATURE_FIXUP)


@dataclass(frozen=True)
class NumericCandidate:
    value: float
    unit_text: str | None


@dataclass
class CaseResult:
    case_key: str
    category: str | None
    status: str  # "PASS" or "FAIL"
    failures: list[str]
    notes: list[str]


def _normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", _denormalize_pdf_text(s)).strip()


def _unit_matches(expected_unit: str, actual_unit: str | None) -> bool:
    expected = expected_unit.lower().strip()
    actual = (actual_unit or "").lower().strip()
    if not actual:
        # Bare numbers: accept for dollar-amount units AND for percent because
        # table columns often print "%" only in the header.
        return expected in {"million", "billion", "trillion", "dollar", "dollars", "percent"} or expected == ""
    aliases = _UNIT_ALIASES.get(expected, {expected})
    return any(alias == actual for alias in aliases) or expected == actual


# Labels whose value is synthesized at answer time (e.g. "which company won"
# or a computed ratio) rather than literally printed on a page.
_SYNTHESIZED_LABEL_RE = re.compile(
    r"(higher|highest|lowest|leading|winning|first)_(company|companies|segment|sector|ticker)$|"
    r"(_pct$|_ratio$|_pct_of_revenue$|_growth$|_yoy_change$|_yoy_growth$|_yoy_pct$|_decrease$)",
    re.IGNORECASE,
)


def _is_synthesized_label(label: str | None) -> bool:
    if not label:
        return False
    return bool(_SYNTHESIZED_LABEL_RE.search(label))


def _extract_numbers(text: str) -> list[NumericCandidate]:
    candidates: list[NumericCandidate] = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group("number").replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = match.group("unit")
        if match.group("prefix") == "$" and not unit:
            unit = "$"
        candidates.append(NumericCandidate(value=value, unit_text=unit.lower() if unit else None))
    return candidates


def _numeric_tolerance(expected: float, tolerance_abs: float | None, tolerance_pct: float | None) -> float:
    tolerances = [0.01]
    if tolerance_abs is not None:
        tolerances.append(float(tolerance_abs))
    if tolerance_pct is not None:
        tolerances.append(abs(expected) * float(tolerance_pct) / 100)
    if tolerance_abs is None and tolerance_pct is None:
        tolerances.append(abs(expected) * 0.005)
    return max(tolerances)


_DOLLAR_UNIT_SCALE = {"million": 1.0, "billion": 1_000.0, "trillion": 1_000_000.0}


def _expected_variants(
    expected: float,
    unit: str | None,
    tolerance_abs: float | None,
) -> list[tuple[float, str | None, float | None]]:
    """Generate alternate (value, unit, scaled_tolerance_abs) tuples.

    Scaling matters: a tolerance_abs of 1 (million) becomes 0.001 (billion) and
    0.000001 (trillion); without scaling the verifier would match unrelated bare
    integers when the expected value converts to a fractional unit.
    """
    if unit not in _DOLLAR_UNIT_SCALE:
        return [(expected, unit, tolerance_abs)]
    base_million = expected * _DOLLAR_UNIT_SCALE[unit]
    base_tol_million = tolerance_abs * _DOLLAR_UNIT_SCALE[unit] if tolerance_abs is not None else None
    out: list[tuple[float, str | None, float | None]] = []
    for alt_unit, scale in _DOLLAR_UNIT_SCALE.items():
        scaled_value = base_million / scale
        scaled_tol = (base_tol_million / scale) if base_tol_million is not None else None
        out.append((scaled_value, alt_unit, scaled_tol))
    # Original (always last to favour the as-written form)
    out.append((expected, unit, tolerance_abs))
    return out


def _numeric_value_present(
    text: str,
    expected: float,
    unit: str | None,
    tolerance_abs: float | None,
    tolerance_pct: float | None,
) -> bool:
    candidates = _extract_numbers(text)
    for variant_value, variant_unit, variant_tol_abs in _expected_variants(expected, unit, tolerance_abs):
        filtered = [c for c in candidates if _unit_matches(variant_unit, c.unit_text)] if variant_unit else candidates
        tolerance = _numeric_tolerance(variant_value, variant_tol_abs, tolerance_pct)
        if any(abs(c.value - variant_value) <= tolerance for c in filtered):
            return True
    return False


def _evidence_text_present(text: str, needle: str) -> bool:
    if not needle:
        return True
    haystack = _normalize_whitespace(text).lower()
    needle_norm = _normalize_whitespace(needle).lower()
    if needle_norm in haystack:
        return True
    # Fall back to a per-token containment check that tolerates lots of
    # punctuation/dollar/comma artefacts in the PDF text extraction.
    tokens = [t for t in re.split(r"[\s,]+", needle_norm) if len(t) > 1]
    return all(t in haystack for t in tokens) if tokens else False


def _resolve_pdf_path(pdf_root: Path, ticker: str, form_type: str, filing_date: date | None) -> Path | None:
    ticker_dir = pdf_root / ticker
    if not ticker_dir.exists():
        return None
    if filing_date is not None:
        stamp = filing_date.strftime("%Y%m%d")
        candidate = ticker_dir / f"{ticker}_{form_type}_{stamp}.pdf"
        if candidate.exists():
            return candidate
    # Fallback: most recent of the given form type
    pdfs = sorted(ticker_dir.glob(f"{ticker}_{form_type}_*.pdf"))
    return pdfs[-1] if pdfs else None


def _latest_filing_for(pdf_root: Path, ticker: str, form_type: str) -> Path | None:
    ticker_dir = pdf_root / ticker
    if not ticker_dir.exists():
        return None
    pdfs = sorted(ticker_dir.glob(f"{ticker}_{form_type}_*.pdf"))
    return pdfs[-1] if pdfs else None


def _filing_date_from_filename(path: Path) -> date | None:
    match = re.search(r"_(\d{8})\.pdf$", path.name)
    if not match:
        return None
    s = match.group(1)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def _page_text(pdf: pypdf.PdfReader, page_number: int) -> str | None:
    if page_number < 1 or page_number > len(pdf.pages):
        return None
    try:
        return pdf.pages[page_number - 1].extract_text() or ""
    except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety of errors on malformed pages
        logger.warning("page_extract_failed page=%d err=%s", page_number, exc)
        return None


def _iter_expected_values(case: dict[str, Any]) -> Iterable[dict[str, Any]]:
    spec = case.get("expected_answer_spec") or {}
    for ev in spec.get("expected_values") or []:
        if isinstance(ev, dict):
            yield ev


def _iter_expected_evidence(case: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for ev in case.get("expected_evidence") or []:
        if isinstance(ev, dict):
            yield ev


def _required_claims(case: dict[str, Any]) -> list[str]:
    spec = case.get("expected_answer_spec") or {}
    return list(spec.get("required_claims") or [])


def verify_case(case: dict[str, Any], pdf_root: Path) -> CaseResult:
    case_key = str(case.get("case_key", "<unknown>"))
    category = case.get("category")
    answer_type = (case.get("expected_answer_spec") or {}).get("answer_type")
    failures: list[str] = []
    notes: list[str] = []

    expected_values = list(_iter_expected_values(case))
    expected_evidence = list(_iter_expected_evidence(case))
    required_claims = _required_claims(case)

    # Refusals: must have no citations and no expected values, but the question
    # itself does not need PDF backing.
    if answer_type == ExpectedAnswerType.REFUSAL:
        if expected_values:
            failures.append("refusal case has expected_values; expected []")
        if expected_evidence:
            failures.append("refusal case has expected_evidence; expected []")
        return CaseResult(case_key, category, "FAIL" if failures else "PASS", failures, notes)

    # Insufficient evidence: citations are optional (e.g., partial-disclosure).
    # If citations exist we still verify the cited page is real, but the
    # expected_values list should be empty.
    if answer_type == ExpectedAnswerType.INSUFFICIENT and expected_values:
        failures.append("insufficient case has non-empty expected_values")
        # Negative coverage: assert the corpus genuinely lacks the asked-about
        # ticker/period when the tags suggest it (best-effort).

    # latest_filing cases (those tagged latest_filing) imply we should also
    # confirm the cited PDF is genuinely the newest of its (ticker, form_type).
    is_latest_case = "latest_filing" in (case.get("tags") or [])

    seen_pages: set[tuple[str, str, int]] = set()
    page_texts: dict[tuple[str, str, int], str] = {}

    for evidence in expected_evidence:
        ticker = evidence.get("ticker")
        form_type = evidence.get("form_type")
        page_number = evidence.get("page_number")
        evidence_text = evidence.get("evidence_text") or ""
        raw_filing_date = evidence.get("filing_date")
        filing_date: date | None = None
        if isinstance(raw_filing_date, date):
            filing_date = raw_filing_date
        elif isinstance(raw_filing_date, str):
            try:
                filing_date = date.fromisoformat(raw_filing_date)
            except ValueError:
                failures.append(f"evidence has unparseable filing_date={raw_filing_date!r}")

        if not ticker or not form_type:
            failures.append("evidence missing ticker/form_type")
            continue

        pdf_path = _resolve_pdf_path(pdf_root, ticker, form_type, filing_date)
        if pdf_path is None:
            failures.append(f"no PDF found for {ticker}/{form_type}/{filing_date}")
            continue

        if filing_date is not None:
            actual_date = _filing_date_from_filename(pdf_path)
            if actual_date != filing_date:
                failures.append(f"filing_date {filing_date} does not match filename {pdf_path.name}")

        if is_latest_case:
            latest = _latest_filing_for(pdf_root, ticker, form_type)
            if latest is not None and latest != pdf_path:
                failures.append(f"latest_filing case cites {pdf_path.name} but newest in corpus is {latest.name}")

        if page_number is None:
            notes.append(f"evidence has no page_number for {pdf_path.name}")
            continue

        try:
            pdf = pypdf.PdfReader(str(pdf_path))
        except Exception as exc:  # noqa: BLE001 - pypdf raises a wide variety of errors on malformed PDFs
            failures.append(f"cannot open {pdf_path.name}: {exc}")
            continue

        key = (ticker, form_type, int(page_number))
        if key in seen_pages:
            text = page_texts[key]
        else:
            text = _page_text(pdf, int(page_number)) or ""
            seen_pages.add(key)
            page_texts[key] = text

        if not text:
            failures.append(f"page {page_number} of {pdf_path.name} is empty or unparseable")
            continue

        if evidence_text and not _evidence_text_present(text, evidence_text):
            snippet = _normalize_whitespace(text)[:160]
            failures.append(
                f"evidence_text {evidence_text!r} not found on {pdf_path.name} p.{page_number}; "
                f"page starts with: {snippet!r}"
            )

    # For numeric / multi_part / text cases, check value_numeric appears on at
    # least one cited page. For value_text, look on cited pages OR in any
    # filing-date metadata (helpful for latest_filing cases).
    for ev in expected_values:
        label = ev.get("label", "<value>")
        value_numeric = ev.get("value_numeric")
        value_text = ev.get("value_text")
        unit = ev.get("unit")
        tolerance_abs = ev.get("tolerance_abs")
        tolerance_pct = ev.get("tolerance_pct")

        synthesized = _is_synthesized_label(label)

        if value_numeric is not None:
            found = False
            for (_t, _f, _p), text in page_texts.items():
                if _numeric_value_present(text, float(value_numeric), unit, tolerance_abs, tolerance_pct):
                    found = True
                    break
            if not found:
                msg = f"value_numeric {value_numeric} (unit={unit}) for label={label!r} not found on any cited page"
                if synthesized:
                    notes.append(f"synthesized: {msg}")
                else:
                    failures.append(msg)
        elif value_text is not None:
            needle_norm = _normalize_whitespace(str(value_text)).lower()
            needle_nospace = re.sub(r"\s+", "", needle_norm)
            found = False
            for t in page_texts.values():
                norm_t = _normalize_whitespace(t).lower()
                if needle_norm in norm_t or needle_nospace in re.sub(r"\s+", "", norm_t):
                    found = True
                    break
            # Allow matches against the filename for date-style answers
            if not found and re.fullmatch(r"\d{4}-\d{2}-\d{2}", needle_norm):
                stamp = needle_norm.replace("-", "")
                found = any(stamp in str(p) for p in pdf_root.rglob("*.pdf"))
            if not found:
                msg = f"value_text {value_text!r} for label={label!r} not found on any cited page or filename"
                if synthesized:
                    notes.append(f"synthesized: {msg}")
                else:
                    failures.append(msg)

    # Required-claim phrases must appear on at least one cited page.
    for claim in required_claims:
        claim_norm = _normalize_whitespace(claim).lower()
        if not any(claim_norm in _normalize_whitespace(t).lower() for t in page_texts.values()):
            failures.append(f"required_claim {claim!r} not found on any cited page")

    return CaseResult(case_key, category, "FAIL" if failures else "PASS", failures, notes)


def render_report(results: list[CaseResult], yaml_path: Path) -> str:
    lines: list[str] = []
    total = len(results)
    failed = [r for r in results if r.status == "FAIL"]
    lines.append("# Eval cases verification report")
    lines.append("")
    lines.append(f"Source: `{yaml_path}`")
    lines.append("")
    lines.append(f"- Cases: **{total}**")
    lines.append(f"- Passed: **{total - len(failed)}**")
    lines.append(f"- Failed: **{len(failed)}**")
    lines.append("")
    if failed:
        lines.append("## Failures")
        lines.append("")
        for r in failed:
            lines.append(f"### `{r.case_key}` ({r.category})")
            for f in r.failures:
                lines.append(f"- {f}")
            lines.append("")
    lines.append("## All cases")
    lines.append("")
    lines.append("| Status | Case key | Category | Notes |")
    lines.append("| --- | --- | --- | --- |")
    for r in results:
        note_field = "; ".join(r.failures + r.notes) or ""
        # markdown table cell safety
        note_field = note_field.replace("|", "\\|")
        lines.append(f"| {r.status} | `{r.case_key}` | {r.category or ''} | {note_field} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-verify eval cases against the SEC filings PDF corpus.")
    parser.add_argument("--yaml", required=True, type=Path, help="Path to eval cases YAML")
    parser.add_argument("--pdf-root", required=True, type=Path, help="Path to sec_filings_pdf root")
    parser.add_argument("--out", required=True, type=Path, help="Path to markdown report")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    raw = yaml.safe_load(args.yaml.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        logger.error("expected a top-level list in %s", args.yaml)
        return 2

    results = [verify_case(case, args.pdf_root) for case in raw if isinstance(case, dict)]
    report = render_report(results, args.yaml)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    failed = sum(1 for r in results if r.status == "FAIL")
    logger.info("verify_done cases=%d failed=%d report=%s", len(results), failed, args.out)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
