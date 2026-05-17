import random
import re
from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError
from rag_common.enums import ExpectedAnswerType
from rag_common.schemas import ExpectedAnswerSpec, ExpectedEvidenceSpec


@dataclass(frozen=True)
class NumericCandidate:
    value: float
    unit_text: str | None


_NUMBER_RE = re.compile(
    r"(?P<prefix>\$)?(?P<number>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>%|million|billion|trillion|basis\s+points|bps)?",
    re.IGNORECASE,
)


def coerce_answer_spec(raw: object) -> ExpectedAnswerSpec:
    if not isinstance(raw, dict):
        return ExpectedAnswerSpec()
    try:
        return ExpectedAnswerSpec.model_validate(raw)
    except ValidationError:
        return ExpectedAnswerSpec()


def coerce_expected_evidence(raw: object) -> list[ExpectedEvidenceSpec]:
    if not isinstance(raw, list):
        return []
    evidence: list[ExpectedEvidenceSpec] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            evidence.append(ExpectedEvidenceSpec.model_validate(item))
        except ValidationError:
            continue
    return evidence


def score_answer(
    *,
    answer: str,
    insufficiency_reason: str | None,
    raw_spec: object,
) -> dict[str, object]:
    spec = coerce_answer_spec(raw_spec)
    if spec.answer_type is None:
        return {"answer_scoreable": False, "answer_accuracy": None}

    if spec.answer_type == ExpectedAnswerType.INSUFFICIENT:
        correct = _is_insufficient(answer, insufficiency_reason)
        keyword_rate = _keyword_hit_rate(answer, insufficiency_reason, spec.required_reason_keywords)
        return {
            "answer_scoreable": True,
            "answer_type": spec.answer_type,
            "answer_accuracy": 1.0 if correct and keyword_rate == 1.0 else 0.0,
            "insufficient_correct": 1.0 if correct else 0.0,
            "reason_keyword_hit_rate": keyword_rate,
        }

    if spec.answer_type == ExpectedAnswerType.REFUSAL:
        correct = _is_refusal(answer, insufficiency_reason)
        keyword_rate = _keyword_hit_rate(answer, insufficiency_reason, spec.required_reason_keywords)
        return {
            "answer_scoreable": True,
            "answer_type": spec.answer_type,
            "answer_accuracy": 1.0 if correct and keyword_rate == 1.0 else 0.0,
            "refusal_correct": 1.0 if correct else 0.0,
            "reason_keyword_hit_rate": keyword_rate,
        }

    value_scores = [_score_expected_value(answer, expected) for expected in spec.expected_values]
    claim_rate = _required_claim_hit_rate(answer, spec.required_claims)
    score_parts: list[float] = []
    if value_scores:
        value_score_numbers: list[float] = []
        for item in value_scores:
            raw_score = item.get("score")
            if isinstance(raw_score, (int, float)):
                value_score_numbers.append(float(raw_score))
        score_parts.append(sum(value_score_numbers) / len(value_score_numbers))
    if spec.required_claims:
        score_parts.append(claim_rate)
    if not score_parts:
        return {"answer_scoreable": False, "answer_accuracy": None, "answer_type": spec.answer_type}
    missing = [item["label"] for item in value_scores if item.get("score") == 0.0]
    return {
        "answer_scoreable": True,
        "answer_type": spec.answer_type,
        "answer_accuracy": sum(score_parts) / len(score_parts),
        "value_scores": value_scores,
        "missing_expected_values": missing,
        "required_claim_hit_rate": claim_rate,
    }


def strict_evidence_eligible(evidence: Iterable[ExpectedEvidenceSpec]) -> list[ExpectedEvidenceSpec]:
    return [
        item
        for item in evidence
        if item.page_number is not None and (item.document_id is not None or (item.ticker and item.form_type))
    ]


def bootstrap_mean_ci(values: list[float], *, seed: int, samples: int = 500) -> list[float] | None:
    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(seed)  # noqa: S311 - deterministic bootstrap sampling, not security-sensitive.
    means: list[float] = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(draw) / len(draw))
    means.sort()
    lower = means[int(0.025 * (len(means) - 1))]
    upper = means[int(0.975 * (len(means) - 1))]
    return [lower, upper]


def _score_expected_value(answer: str, expected: object) -> dict[str, object]:
    label = getattr(expected, "label", "value")
    value_text = getattr(expected, "value_text", None)
    value_numeric = getattr(expected, "value_numeric", None)
    if value_text:
        hit = _normalize(value_text) in _normalize(answer)
        return {"label": label, "score": 1.0 if hit else 0.0, "match_type": "text"}
    if value_numeric is None:
        return {"label": label, "score": 0.0, "match_type": "missing_gold"}

    tolerance_abs = getattr(expected, "tolerance_abs", None)
    tolerance_pct = getattr(expected, "tolerance_pct", None)
    unit = getattr(expected, "unit", None)
    score = 1.0 if _numeric_value_present(answer, float(value_numeric), unit, tolerance_abs, tolerance_pct) else 0.0
    return {"label": label, "score": score, "match_type": "numeric"}


def _numeric_value_present(
    answer: str,
    expected: float,
    unit: str | None,
    tolerance_abs: float | None,
    tolerance_pct: float | None,
) -> bool:
    candidates = _numeric_candidates(answer)
    if unit:
        unit_candidates = [candidate for candidate in candidates if _unit_matches(unit, candidate.unit_text)]
        if unit_candidates:
            candidates = unit_candidates
    tolerance = _numeric_tolerance(expected, tolerance_abs, tolerance_pct)
    return any(abs(candidate.value - expected) <= tolerance for candidate in candidates)


def _numeric_candidates(answer: str) -> list[NumericCandidate]:
    candidates: list[NumericCandidate] = []
    for match in _NUMBER_RE.finditer(answer):
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


def _unit_matches(expected_unit: str, actual_unit: str | None) -> bool:
    expected = expected_unit.lower().strip()
    actual = (actual_unit or "").lower().strip()
    if expected in {"$", "usd", "dollars"}:
        return actual == "$" or actual in {"million", "billion", "trillion"}
    if expected in {"percent", "percentage"}:
        return actual == "%"
    if expected == "basis points":
        return actual in {"basis points", "bps"}
    return expected == actual


def _numeric_tolerance(expected: float, tolerance_abs: float | None, tolerance_pct: float | None) -> float:
    tolerances = [0.01]
    if tolerance_abs is not None:
        tolerances.append(tolerance_abs)
    if tolerance_pct is not None:
        tolerances.append(abs(expected) * tolerance_pct / 100)
    if tolerance_abs is None and tolerance_pct is None:
        tolerances.append(abs(expected) * 0.005)
    return max(tolerances)


def _required_claim_hit_rate(answer: str, claims: list[str]) -> float:
    if not claims:
        return 1.0
    normalized = _normalize(answer)
    hits = sum(1 for claim in claims if _normalize(claim) in normalized)
    return hits / len(claims)


def _keyword_hit_rate(answer: str, insufficiency_reason: str | None, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    normalized = _normalize(" ".join([answer, insufficiency_reason or ""]))
    hits = sum(1 for keyword in keywords if _normalize(keyword) in normalized)
    return hits / len(keywords)


def _is_insufficient(answer: str, insufficiency_reason: str | None) -> bool:
    text = _normalize(" ".join([answer, insufficiency_reason or ""]))
    return any(phrase in text for phrase in ("insufficient", "not enough evidence", "does not contain"))


def _is_refusal(answer: str, insufficiency_reason: str | None) -> bool:
    text = _normalize(" ".join([answer, insufficiency_reason or ""]))
    return any(phrase in text for phrase in ("refusal", "cannot provide", "personalized", "investment advice"))


def answer_declined_to_respond(answer: str, insufficiency_reason: str | None) -> bool:
    """True when the generator produced a non-answer — either an insufficiency
    note or an outright refusal. Used as the per-result ``insufficient`` metric
    so the rate reflects what the model actually emitted, not what the planner
    upstream flagged."""
    return _is_insufficient(answer, insufficiency_reason) or _is_refusal(answer, insufficiency_reason)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()
