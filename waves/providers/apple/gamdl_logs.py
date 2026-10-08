"""gamdl's logging, held to warnings and routed into Waves' own logger.

gamdl logs through structlog, and at debug level it records whole Apple
replies: the wrapper's account reply carries the music-user token, the
developer token and the account identifier. structlog left unconfigured prints
every record to stdout. gamdl is the only structlog user in the process, so
configuring structlog configures gamdl and nothing else.

Every factory that builds a gamdl client calls :func:`quiet_gamdl_logs` before
anything else, so whichever runs first quiets gamdl for the process.
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
        processors=[_event_and_action],
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        logger_factory=lambda *_args: logger,
    )


def _event_and_action(_logger: WrappedLogger, _method: str, event_dict: EventDict):
    """gamdl's event and the operation it names, as one stdlib message.

    The rest of gamdl's bound context is Apple data (whole replies, decryption
    keys, media ids, paths) and stays out of the line. ``exc_info`` passes
    through as a keyword, so the diagnostics filter formats and scrubs the
    traceback.
    """
    message = str(event_dict.get("event", ""))
    action = event_dict.get("action")
    if action:
        message = f"{message} action={action}"
    return (message,), {"exc_info": event_dict.get("exc_info")}
