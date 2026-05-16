"""In-process catalog of bundled eval YAML packs shipped with the repo.

Packs live under ``backend/eval_cases/*.yaml``. The frontend uses these endpoints
to list available packs and import them into a dataset on demand, replacing the
CLI-only ``seed_eval_cases`` workflow.

The actual YAML parsing reuses ``rag_benchmarking.scripts.seed_eval_cases`` so
that the import endpoint and the CLI stay byte-for-byte equivalent.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from threading import Lock

from rag_common.enums import VerificationStatus
from rag_common.schemas import EvalPackSummary

from rag_benchmarking.scripts.seed_eval_cases import SeedEvalCase, load_cases

logger = logging.getLogger(__name__)

EVAL_PACKS_DIR: Path = Path(__file__).resolve().parents[1] / "eval_cases"
_PACK_ID_RE = re.compile(r"^[a-z0-9_\-]+$")
_PACK_SUFFIXES = (".yaml", ".yml")

_cache_lock = Lock()
_summary_cache: list[EvalPackSummary] | None = None


def _humanize(pack_id: str) -> str:
    return pack_id.replace("_", " ").replace("-", " ")


def _build_summary(pack_id: str, cases: list[SeedEvalCase]) -> EvalPackSummary:
    categories = sorted({case.category for case in cases if case.category})
    difficulties = sorted({case.difficulty for case in cases if case.difficulty})
    tags = sorted({tag for case in cases for tag in case.tags})
    verified_count = sum(1 for case in cases if case.verification_status == VerificationStatus.VERIFIED)
    gold_version = cases[0].gold_version if cases else None
    return EvalPackSummary(
        id=pack_id,
        name=_humanize(pack_id),
        description=None,
        gold_version=gold_version,
        case_count=len(cases),
        verified_count=verified_count,
        categories=categories,
        difficulties=difficulties,
        tags=tags,
    )


def _scan_packs() -> list[EvalPackSummary]:
    if not EVAL_PACKS_DIR.exists():
        logger.warning("eval_packs_dir_missing path=%s", EVAL_PACKS_DIR)
        return []
    summaries: list[EvalPackSummary] = []
    for path in sorted(EVAL_PACKS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _PACK_SUFFIXES:
            continue
        pack_id = path.stem
        if not _PACK_ID_RE.match(pack_id):
            logger.warning("eval_pack_id_invalid pack_id=%s", pack_id)
            continue
        try:
            cases = load_cases(path)
        except (OSError, ValueError) as exc:
            logger.warning("eval_pack_load_failed pack_id=%s error=%s", pack_id, exc)
            continue
        summaries.append(_build_summary(pack_id, cases))
    return summaries


def list_packs() -> list[EvalPackSummary]:
    """Return summaries for every loadable YAML pack under ``EVAL_PACKS_DIR``.

    Results are cached in-process after the first successful scan because the
    bundled files are read-only at runtime (deploys restart the process).
    """
    global _summary_cache
    if _summary_cache is not None:
        return _summary_cache
    with _cache_lock:
        if _summary_cache is None:
            _summary_cache = _scan_packs()
    return _summary_cache


def get_pack(pack_id: str) -> tuple[EvalPackSummary, list[SeedEvalCase]]:
    """Return the summary + parsed cases for a single pack.

    Raises ``KeyError`` for unknown / invalid ids. Callers translate to HTTP 404.
    """
    if not _PACK_ID_RE.match(pack_id):
        raise KeyError(pack_id)
    path = EVAL_PACKS_DIR / f"{pack_id}.yaml"
    if not path.is_file():
        path = EVAL_PACKS_DIR / f"{pack_id}.yml"
    if not path.is_file():
        raise KeyError(pack_id)
    try:
        cases = load_cases(path)
    except (OSError, ValueError) as exc:
        raise KeyError(pack_id) from exc
    return _build_summary(pack_id, cases), cases
