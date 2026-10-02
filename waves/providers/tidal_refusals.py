"""TIDAL playback refusal messages, distinguished from expired credentials."""

from __future__ import annotations

from requests.exceptions import HTTPError

# The 11xxx subStatus family refers to credentials, not unavailable music.
_TIDAL_SUBSTATUS_AUTH_MIN = 11000
_TIDAL_SUBSTATUS_AUTH_MAX = 11999


def asset_refusal_message(error: HTTPError) -> str | None:
    """TIDAL's own words when it refuses to serve an item, or None if this is
    something else (a network hiccup, a dead session, a server error).

    The playback-info endpoint answers a track the account cannot play with a
    401 or 403 whose body says why (observed: ``subStatus 4005 "Asset is not
    ready for playback"`` for tracks greyed out in the official apps). The
    same 401 status also announces an expired or invalid token, so the body is
    the only way to tell "TIDAL will not give you this track" from "TIDAL does
    not know who you are"; tidalapi already retried the expired-token case
    once with a refresh, so what reaches here is whatever survived that.

    Args:
        error (HTTPError): The requests error raised for the playback request.

    Returns:
        str | None: TIDAL's user message (or a generic one) when this is a
            refusal of the asset itself, None otherwise.
    """
    response = getattr(error, "response", None)
    if response is None:
        return None
    status = getattr(response, "status_code", None)
    if status not in (401, 403):
        return None
    body: dict = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except Exception:  # noqa: S110  # a body that is not JSON is still a refusal
        pass
    message = str(body.get("userMessage") or "")
    if message.startswith("The token has expired"):
        return None
    sub_status = body.get("subStatus")
    if isinstance(sub_status, int) and _TIDAL_SUBSTATUS_AUTH_MIN <= sub_status <= _TIDAL_SUBSTATUS_AUTH_MAX:
        return None
    return message or f"HTTP {status}"
