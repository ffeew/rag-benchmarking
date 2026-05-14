import logging
import sys
from typing import TYPE_CHECKING

import structlog

from rag_common.config import get_settings

if TYPE_CHECKING:
    from structlog.typing import Processor


def configure_logging() -> None:
    """Configure stdlib logging and structlog to share an output pipeline.

    Both ``logging.getLogger(__name__).info("event", extra={...})`` and
    ``structlog.get_logger(__name__).info("event", **kwargs)`` route through the
    same :class:`structlog.stdlib.ProcessorFormatter`, so ``extra`` keys and
    bound kwargs both surface as fields in one record.

    The level and final renderer are driven by ``Settings.log_level`` and
    ``Settings.log_format`` so an operator can set ``LOG_LEVEL=INFO`` for a
    readable mass-ingestion view, then flip to ``LOG_LEVEL=DEBUG`` to recover
    full per-batch traces. ``LOG_FORMAT=auto`` picks a colored console renderer
    when stdout is a TTY and falls back to JSON when piped — keeping container
    log shippers happy without sacrificing local readability.
    """
    settings = get_settings()
    level = logging.getLevelNamesMapping()[settings.log_level]

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

    use_console = settings.log_format == "console" or (
        settings.log_format == "auto" and sys.stdout.isatty()
    )
    renderer: Processor = (
        structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
        if use_console
        else structlog.processors.JSONRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # ExtraAdder lifts ``logger.info("event", extra={...})`` kwargs into the
        # event dict — without it stdlib records lose their extras entirely.
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *shared_processors],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
