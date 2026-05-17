"""LLM-judged text matching for answer-correctness scoring.

The numeric scoring path in ``scoring.py`` uses regex + tolerance — robust
to phrasing. Text-based scoring (``value_text`` and ``required_claims``)
used lowercased substring containment, which gave 0.0 to any paraphrase
and could silently pass a negation flip ("did not increase" vs "increased").

This module replaces that substring match with an LLM call against the
Z.AI judge model using a binary rubric. The judge returns a JSON
``{"score", "rationale"}`` verdict per (statement, answer) pair; callers
in ``scoring.py`` use the score directly and surface the rationale in
the per-case metrics for audit.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from rag_common.config import Settings

logger = logging.getLogger(__name__)


_JUDGE_SYSTEM_PROMPT = """\
You are an expert evaluator. Decide whether a model's answer asserts a specific required statement.

SCORING RUBRIC (binary):
- Score 1.0 if the answer asserts the statement. Paraphrase, synonyms, alternate phrasing, and word reordering are acceptable as long as the propositional meaning is preserved.
- Score 0.0 if the statement is absent from the answer, contradicted by the answer, or only ambiguously implied.

Be lenient about phrasing; be strict about negation. "X did not happen" must not match an answer that says "X happened" (and vice versa).

If the statement contains a number, treat the answer as asserting it only when the same value appears (an equivalent representation is fine — "$1.5 billion" matches "$1,500 million").

Respond as a single JSON object: {"score": <0.0 or 1.0>, "rationale": "<one short sentence explaining the score>"}.
Do not include any text outside the JSON object."""


@dataclass(frozen=True)
class JudgeVerdict:
    score: float
    rationale: str
    judge_model: str


class TextJudge:
    """Binary text-match judge backed by an OpenAI-compatible chat client.

    One instance per eval run. Stateless across calls; safe to share.
    """

    def __init__(self, *, client: Any, model: str, temperature_zero: bool = True) -> None:
        self._client = client
        self._model = model
        self._temperature_zero = temperature_zero

    def judge(self, *, statement: str, answer: str) -> JudgeVerdict:
        user_prompt = f"STATEMENT TO LOOK FOR:\n{statement}\n\nMODEL ANSWER:\n{answer}"
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self._temperature_zero:
            kwargs["temperature"] = 0.0
        try:
            response = self._client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001 — judge failure must not abort the case
            logger.warning("text_judge_call_failed", extra={"error": str(exc), "model": self._model})
            return JudgeVerdict(score=0.0, rationale=f"judge_error: {type(exc).__name__}", judge_model=self._model)
        score, rationale = _parse_verdict(content)
        return JudgeVerdict(score=score, rationale=rationale, judge_model=self._model)


def build_text_judge(settings: Settings) -> TextJudge | None:
    """Return a TextJudge if Z.AI is configured for live scoring, else None.

    None means "fall back to deterministic substring matching" — used by the
    test suite (``allow_mock_providers=True``) and any environment without a
    judge model. The runner threads ``None`` into ``score_answer`` and the
    substring path runs as before.
    """
    if settings.allow_mock_providers:
        return None
    if settings.zai_api_key is None or not settings.zai_judge_model:
        return None
    try:
        from openai import OpenAI
    except ImportError as exc:
        logger.warning("text_judge_openai_unavailable", extra={"error": str(exc)})
        return None
    client = OpenAI(
        base_url=settings.zai_base_url,
        api_key=settings.zai_api_key.get_secret_value(),
        timeout=settings.zai_timeout_seconds,
    )
    return TextJudge(
        client=client,
        model=settings.zai_judge_model,
        temperature_zero=settings.eval_temperature_zero,
    )


def _parse_verdict(content: str) -> tuple[float, str]:
    """Extract ``(score, rationale)`` from the judge's response.

    With ``response_format=json_object`` Z.AI/OpenAI returns a JSON string,
    but models occasionally wrap it in markdown fences or prose. We strip
    fences and fall back to a permissive ``{...}`` regex before giving up
    so a single ill-formed response doesn't crash the per-case loop.
    """
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed: Any = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match is not None:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        return 0.0, f"parse_error: {text[:160]}"
    score_raw = parsed.get("score")
    rationale = str(parsed.get("rationale") or "").strip() or "<no rationale>"
    if not isinstance(score_raw, (int, float)):
        return 0.0, f"invalid_score: {score_raw!r}"
    score = float(score_raw)
    # The rubric is binary; coerce non-binary outputs to the nearest endpoint
    # so a model that returns 0.7 doesn't silently shift the pass rate.
    if score not in (0.0, 1.0):
        score = 1.0 if score >= 0.5 else 0.0
    return score, rationale
