"""gamdl's debug logs never reach a terminal, and its warnings reach Waves' logger.

gamdl logs whole Apple replies at debug level through structlog, the wrapper's
account reply (music-user token, developer token, account identifier) among
them. Each test starts from structlog's unconfigured default, the state a fresh
process is in when Waves first reaches gamdl.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
import structlog

from waves.providers.apple import AppleProvider, engine
from waves.providers.apple.gamdl_logs import quiet_gamdl_logs

_MUSIC_USER_TOKEN = "sentinel-music-user-token-7f3a"  # noqa: S105 - a sentinel, never a real token
_DEV_TOKEN = "sentinel-dev-token-91c2"  # noqa: S105 - a sentinel, never a real token
_ACCOUNT_ID = "sentinel-dsid-4408"
_SENTINELS = (_MUSIC_USER_TOKEN, _DEV_TOKEN, _ACCOUNT_ID)


@pytest.fixture(autouse=True)
def _unconfigured_structlog():
    structlog.reset_defaults()
    quiet_gamdl_logs.cache_clear()
    yield
    structlog.reset_defaults()
    quiet_gamdl_logs.cache_clear()


def _wrapper_reply(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/me":
        return httpx.Response(
            200,
            json={
                "version": "0.0.2",
                "auth": {
                    "state": "logged_in",
                    "music_user_token": _MUSIC_USER_TOKEN,
                    "dev_token": _DEV_TOKEN,
                    "dsid": _ACCOUNT_ID,
                },
            },
        )
    if request.url.path == "/playback":
        return httpx.Response(200, json={"adam_id": request.url.params["adam_id"], "dsid": _ACCOUNT_ID})
    return httpx.Response(404)


def _assert_no_sentinel(capfd) -> None:
    out, err = capfd.readouterr()
    for sentinel in _SENTINELS:
        assert sentinel not in out
        assert sentinel not in err


class _FakeWrapperClient(httpx.AsyncClient):
    def __init__(self, **kwargs):
        super().__init__(transport=httpx.MockTransport(_wrapper_reply), **kwargs)


def test_wrapper_session_prints_no_account_token(monkeypatch, capfd):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeWrapperClient)

    async def session_and_fetch():
        wrapper = await engine._open_wrapper_session(
            base_url="http://wrapper.test", decrypt_host="127.0.0.1", decrypt_port=10020
        )
        try:
            playback = await wrapper.get_playback("1440833098")
        finally:
            await wrapper.client.aclose()
        return wrapper, playback

    wrapper, playback = asyncio.run(session_and_fetch())

    # The session read the fake replies, so gamdl had both to log.
    assert wrapper.me["auth"]["music_user_token"] == _MUSIC_USER_TOKEN
    assert playback["dsid"] == _ACCOUNT_ID
    _assert_no_sentinel(capfd)


def _debug_logging_create(module_logger, result):
    async def create(*_args, **_kwargs):
        module_logger.bind(action="create").debug("success", account_info={"dev_token": _DEV_TOKEN})
        return result

    return create


def test_catalog_session_prints_no_account_token(monkeypatch, capfd):
    from gamdl.api import apple_music

    catalog = object()
    monkeypatch.setattr(apple_music.AppleMusicApi, "create", _debug_logging_create(apple_music.logger, catalog))

    assert asyncio.run(AppleProvider._create_catalog()) is catalog
    _assert_no_sentinel(capfd)


def test_cookies_session_prints_no_account_token(monkeypatch, capfd):
    from gamdl.api import apple_music
    from gamdl.interface import base

    api, interface = object(), object()
    monkeypatch.setattr(
        apple_music.AppleMusicApi, "create_from_netscape_cookies", _debug_logging_create(apple_music.logger, api)
    )
    monkeypatch.setattr(base.AppleMusicBaseInterface, "create", _debug_logging_create(base.logger, interface))

    assert asyncio.run(engine._create_cookies_stack("cookies.txt")) == (api, interface)
    _assert_no_sentinel(capfd)


def _hang_up() -> None:
    raise RuntimeError("wrapper hung up")


def test_gamdl_warning_reaches_the_waves_logger_without_its_data(caplog, capfd):
    quiet_gamdl_logs()
    gamdl_log = structlog.get_logger("gamdl.interface.base").bind(
        action="get_decryption_key", decryption_key=_DEV_TOKEN, account_info={"dsid": _ACCOUNT_ID}
    )

    with caplog.at_level(logging.DEBUG, logger="waves"):
        gamdl_log.debug("success")
        gamdl_log.warning("key slow")
        try:
            _hang_up()
        except RuntimeError:
            gamdl_log.exception("key failed")

    records = [record for record in caplog.records if record.name.startswith("waves.")]
    assert [record.levelno for record in records] == [logging.WARNING, logging.ERROR]
    for record, event in zip(records, ("key slow", "key failed"), strict=True):
        message = record.getMessage()
        assert event in message
        assert "get_decryption_key" in message
        assert not any(sentinel in message for sentinel in _SENTINELS)
    assert records[1].exc_info is not None
    assert records[1].exc_info[0] is RuntimeError
    _assert_no_sentinel(capfd)
