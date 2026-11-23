"""Event text loses private values before display, history or copy."""

from __future__ import annotations

import pytest

from waves import redaction
from waves.events import EventDomain, application_event


@pytest.fixture()
def event_redactor(monkeypatch):
    # Keep registrations local without replacing the module used by other owners.
    monkeypatch.setattr(redaction, "_redactor", redaction._Redactor())
    return redaction


@pytest.mark.parametrize(
    "path",
    [
        "/Users/carol/Music/Secret Artist/Private Album/Track One.flac",
        "/home/carol/Music/Secret Artist/Private Album/Track One.flac",
        "/Volumes/Private Share/Secret Artist/Private Album/Track One.flac",
        "/mnt/Private Share/Secret Artist/Private Album/Track One.flac",
        "/arbitrary-mount/Secret Artist/Private Album/Track One.flac",
        "/arbitrary-mount/‹Secret Artist›/Track One.flac",
        "/arbitrary-mount/«Secret Artist»/Track One.flac",
        "/arbitrary-mount/Secret Artist/Track [One] (Live).flac",
        "/arbitrary-mount/Secret Artist/Don't Stop.flac",
        "/run/user/1000/gvfs/smb-share:server=nas,share=private/Secret Artist/Track.flac",
        r"C:\Users\Carol Adams\Music\Secret Artist\Track One.flac",
        r"D:\Private Share\Secret Artist\Track One.flac",
        r"\\private-nas\Private Share\Secret Artist\Track One.flac",
        "//private-nas/Private Share/Secret Artist/Track One.flac",
        "~/Music/Secret Artist/Track One.flac",
        "../Secret Artist/Track One.flac",
        "./Secret Artist/Track One.flac",
        "Music/Secret Artist/Track One.flac",
        r"Music\Secret Artist\Track One.flac",
        "file:///Volumes/Private%20Share/Secret%20Artist/Track%20One.flac",
        "file:/Volumes/Private%20Share/Secret%20Artist/Track%20One.flac",
        "file:///backup/Track One.flac",
        "smb://private-nas/Private Share/Track One.flac",
    ],
)
def test_full_private_paths_and_their_suffixes_are_removed(event_redactor, path):
    for text in (f"Could not open {path}", f'Could not open "{path}"'):
        result = event_redactor.scrub_event_text(text)
        assert "Could not open" in result
        assert "‹path›" in result
        for private in ("carol", "Carol", "private-nas", "Private", "Secret", "Track", "nas,share"):
            assert private not in result
        assert event_redactor.scrub_event_text(result) == result


def test_paths_in_tracebacks_and_renames_keep_the_diagnosis(event_redactor):
    text = (
        'Permission denied: "/Volumes/Share/Secret Artist/Track One.flac" -> '
        '"/backup/Other Artist/Second Track.flac"\n'
        '  File "/Users/carol/Private Project/main.py", line 42'
    )
    result = event_redactor.scrub_event_text(text)
    assert "Permission denied" in result
    assert "line 42" in result
    assert "->" in result
    assert result.count("‹path›") == 3
    assert "Artist" not in result and "Track" not in result and "main.py" not in result


@pytest.mark.parametrize(
    "text, private",
    [
        ('password="a private phrase with spaces" rejected', "private phrase"),
        ("{'access_token': 'short value with spaces'}", "short value"),
        (r'password="a private \"quoted\" phrase" rejected', "private"),
        ('Cookie="session=one; csrftoken=two; secret=three"', "csrftoken"),
        ("Cookie: session=one; csrftoken=two; secret=three", "csrftoken"),
        ("cookie session=one; csrftoken=two; secret=three", "csrftoken"),
        ("password=ab rejected", "ab"),
        ("token: x rejected", " x "),
        ('passphrase "one two three" rejected', "one two three"),
        ('token="first private line\nsecond private line" rejected', "private"),
        ('Cookie="session=first private line\nsecond private line"', "private"),
    ],
)
def test_labelled_secrets_include_short_and_quoted_values(event_redactor, text, private):
    result = event_redactor.scrub_event_text(text)
    assert private not in result
    assert "‹redacted›" in result
    assert event_redactor.scrub_event_text(result) == result


@pytest.mark.parametrize("quoted", [False, True])
def test_url_credentials_query_and_fragment_are_removed(event_redactor, quoted):
    url = "https://carol:private-password@api.example.test/v1/search?needle=private-search#private-account"
    text = f'Request failed for "{url}"' if quoted else f"Request failed for {url}"
    result = event_redactor.scrub_event_text(text)
    assert "Request failed" in result
    assert "api.example.test/v1/search" in result
    for private in ("carol", "private-password", "private-search", "private-account"):
        assert private not in result
    assert "‹credentials›" in result and "‹query›" in result and "‹fragment›" in result
    assert event_redactor.scrub_event_text(result) == result


def test_quoted_urls_with_spaces_do_not_leave_query_suffixes(event_redactor):
    text = 'Request failed for "https://carol:my password@api.example.test/search?q=my private phrase#private section"'
    result = event_redactor.scrub_event_text(text)
    assert "api.example.test/search" in result
    assert "password" not in result and "private" not in result
    assert event_redactor.scrub_event_text(result) == result


def test_every_registered_sensitive_value_is_hidden_without_changing_log_policy(event_redactor):
    event_redactor.register_secret("private arbitrary phrase", "‹account›")
    event_redactor.register_secret("ab")
    event_redactor.register_secret("secret")
    text = "Failure for private arbitrary phrase with code ab and secret"
    result = event_redactor.scrub_event_text(text)
    assert "private arbitrary phrase" not in result and "ab" not in result
    assert result.count("‹secret›") == 3
    assert event_redactor.scrub_event_text(result) == result
    assert event_redactor.scrub("code ab") == "code ab"


def test_plain_recovery_text_and_legacy_log_paths_stay_useful(event_redactor):
    text = "Search failed. Check your connection and try again. Secret Song was not downloaded."
    assert event_redactor.scrub_event_text(text) == text
    path = "/Music/Some Artist/Private Album/Track One.flac"
    assert event_redactor.scrub(path) == path
    assert event_redactor.scrub_event_text(path) == "‹path›"


def test_arbitrary_marker_text_does_not_hide_a_registered_secret(event_redactor):
    event_redactor.register_secret("private-value")
    result = event_redactor.scrub_event_text("Request context: ‹private-value›")
    assert "private-value" not in result
    assert event_redactor.scrub_event_text(result) == result


@pytest.mark.parametrize(
    "credential, private",
    [
        ("Authorization: Basic dXNlcjpwYXNz", ("Basic", "dXNlcjpwYXNz")),
        (
            'Authorization: Digest username="private-user", realm="private realm", '
            'nonce="private-nonce", response="private-response"',
            ("Digest", "private-user", "private realm", "private-nonce", "private-response"),
        ),
        ("Authorization Basic dXNlcjpwYXNz", ("Basic", "dXNlcjpwYXNz")),
        ("Proxy-Authorization: Basic dXNlcjpwYXNz", ("Basic", "dXNlcjpwYXNz")),
        ("password=correct horse battery staple", ("correct", "horse", "battery", "staple")),
        (
            "password: private-red,private-blue;private-green&private-tail",
            ("private-red", "private-blue", "private-green", "private-tail"),
        ),
        (
            "token=pieceAlpha;pieceBeta,pieceGamma&pieceDelta",
            ("pieceAlpha", "pieceBeta", "pieceGamma", "pieceDelta"),
        ),
        (
            "Bearer pieceAlpha;pieceBeta,pieceGamma&pieceDelta",
            ("pieceAlpha", "pieceBeta", "pieceGamma", "pieceDelta"),
        ),
        ("api_key=short private suffix", ("short", "private", "suffix")),
    ],
)
def test_credential_tails_are_hidden_in_visible_stored_and_copied_events(event_redactor, credential, private):
    event = application_event(
        EventDomain.CONFIGURATION,
        f"Request failed: {credential}",
        title=f"Could not connect: {credential}",
        details=(f"Credential rejected: {credential}",),
        exception=ValueError(credential),
    )
    visible = (
        event.title,
        event.summary,
        *event.details,
        event.diagnostics,
        event.copy_text(),
        event_redactor.scrub_event_text(credential),
    )
    for text in (*visible, repr(event.payload())):
        for value in private:
            assert value not in text
    for text in visible:
        assert event_redactor.scrub_event_text(text) == text
    assert "Request failed" in event.summary
    assert "Credential rejected" in event.details[0]


def test_full_credential_redaction_does_not_change_legacy_log_rules(event_redactor):
    assert event_redactor.scrub("Authorization: Basic dXNlcjpwYXNz") == "Authorization: ‹redacted› dXNlcjpwYXNz"
    assert event_redactor.scrub("password=correct horse battery staple") == "password=‹redacted› horse battery staple"
    assert event_redactor.scrub_event_text("password=correct horse battery staple") == "password=‹redacted›"
