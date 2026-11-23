"""A notification's prefilled issue draft: plain-language body, redacted, reviewable by the user."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from waves.desktop.diagnostics.notifications import compose_report, issue_draft_url
from waves.redaction import register_secret


def _entry(**overrides) -> dict:
    entry = {
        "id": "a" * 32,
        "code": "operation_failed",
        "title": "Download",
        "summary": "The download could not finish. Try again or open the logs.",
        "details": ["Retried the same engine once", "The provider refused the request"],
        "diagnostics": "Traceback (most recent call last):\nRuntimeError: wrapper exited",
        "lifecycle": "active",
    }
    entry.update(overrides)
    return entry


def test_compose_report_carries_plain_cause_details_and_advanced_trace():
    title, body = compose_report(_entry(), version="0.1.40", platform_name="macOS 15.3")
    assert title == "[operation_failed] Download"
    assert "The download could not finish." in body
    assert "- Retried the same engine once" in body
    assert "RuntimeError: wrapper exited" in body
    assert body.rstrip().endswith("Waves 0.1.40 · macOS 15.3")


def test_report_draft_never_carries_registered_secrets():
    register_secret("report-private-value")
    entry = _entry(
        title="report-private-value",
        summary="report-private-value",
        details=["report-private-value"],
        diagnostics="report-private-value",
    )
    title, body = compose_report(entry, version="0.1.40", platform_name="macOS 15.3")
    url = issue_draft_url("https://github.com/example/repo", title, body)
    for payload in (title, body, url):
        assert "report-private-value" not in payload


def test_issue_draft_url_encodes_and_rejects_non_http_repositories():
    assert issue_draft_url("git@github.com:example/repo", "t", "b") == ""
    assert issue_draft_url("", "t", "b") == ""
    url = issue_draft_url("https://github.com/example/repo/", "A title", "A body\nwith lines")
    parsed = urlparse(url)
    assert parsed.scheme == "https" and parsed.path == "/example/repo/issues/new"
    query = parse_qs(parsed.query)
    assert query["title"] == ["A title"]
    assert query["body"] == ["A body\nwith lines"]


def test_issue_draft_url_caps_overlong_bodies():
    url = issue_draft_url("https://github.com/example/repo", "t", "x" * 20000)
    body = parse_qs(urlparse(url).query)["body"][0]
    assert len(body) < 8000
    assert body.endswith("…(draft truncated)")
