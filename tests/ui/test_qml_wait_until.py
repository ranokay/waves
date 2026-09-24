"""Unit test for support.qml.wait_until: polling wins, timeout fails by name."""

from __future__ import annotations

import pytest
from support.qml import wait_until


def test_wait_until_returns_once_the_predicate_holds():
    calls = {"n": 0}

    def predicate():
        calls["n"] += 1
        return calls["n"] >= 3

    elapsed = wait_until(predicate, timeout_ms=2000, interval_ms=5, message="becomes true")
    assert calls["n"] >= 3
    assert elapsed >= 0


def test_wait_until_fails_on_timeout_naming_the_checkpoint():
    with pytest.raises(AssertionError, match=r"CHECKPOINT never-true"):
        wait_until(lambda: False, timeout_ms=50, interval_ms=5, message="never-true")
