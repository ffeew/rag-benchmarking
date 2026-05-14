import logging
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.typing import Processor


def configure_logging() -> None:
    """Configure stdlib logging and structlog to share a JSON output pipeline.

    Both ``logging.getLogger(__name__).info("event", extra={...})`` and
    ``structlog.get_logger(__name__).info("event", **kwargs)`` route through the
    same :class:`structlog.stdlib.ProcessorFormatter`, so ``extra`` keys and
    bound kwargs both surface as fields in one JSON line per record.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # ExtraAdder lifts ``logger.info("event", extra={...})`` kwargs into the
        # event dict — without it stdlib records lose their extras entirely.
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *shared_processors],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
