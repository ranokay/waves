"""gamdl's logging, held to warnings and routed into Waves' own logger.

gamdl logs through structlog, and at debug level it records whole Apple
replies: the wrapper's account reply carries the music-user token, the
developer token and the account identifier. structlog left unconfigured prints
every record to stdout. gamdl is the only structlog user in the process, so
configuring structlog configures gamdl and nothing else.

Waves first calls into gamdl from one of three factories (the catalog API, the
cookies stack and the wrapper session), and each calls :func:`quiet_gamdl_logs`
before anything else.
"""

from __future__ import annotations

import logging
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from structlog.typing import EventDict, WrappedLogger

logger = logging.getLogger("waves.providers.apple.gamdl")


@cache
def quiet_gamdl_logs() -> None:
    """Configure gamdl's logging once, before Waves first reaches gamdl.

    Debug and info calls become no-ops where gamdl makes them, so a reply never
    reaches a processor or a handler. Warnings and errors land on this module's
    logger, where the diagnostics handlers scrub them like any Waves record.
    structlog loads here rather than at import: it comes with gamdl, which
    Waves keeps off the boot path.
    """
    import structlog

    structlog.configure(
        processors=[_one_line],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=lambda *_args: logger,
    )


def _one_line(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> tuple[tuple[str], dict[str, object]]:
    """gamdl's event and its bound context as one stdlib message.

    The reply bodies gamdl binds whole (the dicts and lists it parsed) stay out
    of the line. ``exc_info`` passes through as a keyword, so the diagnostics
    filter formats and scrubs the traceback.
    """
    exc_info = event_dict.pop("exc_info", None)
    words = [str(event_dict.pop("event", ""))]
    words += [f"{key}={value!r}" for key, value in event_dict.items() if not isinstance(value, dict | list)]
    return (" ".join(words),), {"exc_info": exc_info}
