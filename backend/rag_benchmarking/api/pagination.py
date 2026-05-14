from typing import Annotated, Any

from fastapi import Query
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

LimitParam = Annotated[int, Query(ge=1, le=200)]
OffsetParam = Annotated[int, Query(ge=0)]


def paged_query(
    session: Session,
    *,
    base: Select[Any],
    ordered: Select[Any],
    limit: int,
    offset: int,
) -> tuple[list[Any], int]:
    """Run ``ordered`` with limit/offset alongside a COUNT(*) over ``base``.

    ``base`` must be the filter-only statement (no eager-load options, no
    ``ORDER BY``) so the count is cheap. ``ordered`` is ``base`` with options
    and ``order_by`` applied; pagination is layered on top here.
    """
    count_stmt = select(func.count()).select_from(base.subquery())
    total = session.scalar(count_stmt) or 0
    rows = list(session.scalars(ordered.limit(limit).offset(offset)))
    return rows, total
