"""The log redaction protocol: identity scrubbing and user-content marking.

Both layers of the app log through this module, so it lives below them: the
engine marks user content (:func:`content`) and registers runtime secrets
(:func:`register_secret`) without importing the UI, and the UI's diagnostics
layer (:mod:`waves.desktop.diagnostics`) attaches :class:`_RedactingFilter` to
every handler and reuses :func:`scrub` for the crash log and the export bundle.

Content markers («…», produced by content()) and identity placeholders (‹…›)
never collide: the export's optional content pass hashes «…» spans only, and
identity PII is always scrubbed.
"""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import re
import socket
import threading

# Content markers («…», produced by content()). Identity placeholders use ‹…›
# so the two never collide: the export content pass hashes «…» spans only.
_C_OPEN, _C_CLOSE = "«", "»"
_CONTENT_RE = re.compile(f"{_C_OPEN}([^{_C_OPEN}{_C_CLOSE}]*){_C_CLOSE}")


def content(text: object) -> str:
    """Mark ``text`` as user content (search text, a title) in a log message.

    The markers survive into the on-disk log (harmless, greppable) and let the
    export's optional "also redact content" pass replace exactly these spans
    with opaque hashes, nothing else.
    """
    # A marker inside the text would end the span early and leave the rest
    # readable under the content switch (a title like "Nothing » Everything"),
    # so the text gives up the two marker characters before it is wrapped.
    body = str(text).replace(_C_OPEN, "<<").replace(_C_CLOSE, ">>")
    return f"{_C_OPEN}{body}{_C_CLOSE}"


class _Redactor:
    """Recall-first identity scrubber applied to every persisted log line.

    Denylist shapes (paths/IPs/emails/tokens) plus literal values learned at
    runtime (this machine's username/hostname/home, registered secrets). Both
    passes are idempotent so the export can safely re-scrub already-scrubbed
    lines. Over-redaction is accepted by design: a version string that looks
    like an IP is a smaller loss than one leaked address.
    """

    _EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    _IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    _MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
    # Colon-hex runs, including the compressed "::" form; the callback keeps
    # timestamps (12:34:56) by requiring a hex letter, a "::", or 4+ groups
    # before treating a match as an address.
    _IPV6 = re.compile(r"(?<![\w.:-])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:%\w+)?(?![\w.:-])")
    # "Bearer <token>" first, so the token itself (not the word Bearer) is the
    # value the key/value pattern below would otherwise consume.
    _BEARER = re.compile(r"(?i)\bbearer\s+[^\s'\"&;,]+")
    # "key: value" secrets, whatever the surrounding syntax (JSON, URLs, repr).
    #
    # Two arms, because the two separators carry very different evidence. A
    # colon or an equals sign SAYS the next run is a value, so anything after
    # it goes. A plain space says nothing of the sort: a word after a word is
    # far more often a title than a credential, and treating it as one turned
    # a track called "Secret Song" into "Secret ‹redacted›" and a playlist
    # called "Token Ring" into "Token ‹redacted›", destroying exactly the
    # diagnostic value the content marker exists to preserve. So the spaced
    # arm asks the VALUE to look like a credential: six or more characters
    # carrying a digit or token punctuation, or a sixteen-character run of
    # anything. Over-redaction is still the design; this only stops it eating
    # ordinary prose. ("Bearer <token>" has its own pattern above, and every
    # value learned at runtime is replaced literally by register_secret.)
    _KV_SECRET = re.compile(
        r"(?i)\b(bearer|authorization|auth|token|api[_-]?key|apikey|secret|password|passwd|"
        r"cookie|set-cookie|session[_-]?id|access[_-]?token|refresh[_-]?token|client[_-]?secret)\b"
        r"(?:"
        r"(['\"]?\s*[:=]\s*)(['\"]?)([^\s'\"&;,]+)"
        r"|"
        r"(\s+)(['\"]?)((?=[^\s'\"&;,]*[\d\-_./+=])[^\s'\"&;,]{6,}|[^\s'\"&;,]{16,})"
        r")"
    )
    # A labelled cookie header is a list of pairs, and the key/value pattern
    # above stops at the first ";": the pairs after it are cookie values too,
    # so the whole header goes, to end of line. The colon-less "cookie <value>"
    # form stays with the key/value pass.
    _COOKIE_HEADER = re.compile(r"(?i)\b(set-cookie|cookie)\s*:\s*[^\r\n]+")
    # Bare high-entropy blobs: long hex (ids, digests) and long base64ish runs.
    _LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
    _B64ISH = re.compile(
        r"\b(?=[A-Za-z0-9+/_-]*[A-Z])(?=[A-Za-z0-9+/_-]*[a-z])(?=[A-Za-z0-9+/_-]*\d)[A-Za-z0-9+/_-]{24,}={0,2}\b"
    )
    _UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
    # Any OS's user-directory form, including ones from *other* machines that
    # arrive in server messages: /Users/<x>, /home/<x>, C:\Users\<x>,
    # \\host\Users\<x>, and the %USERPROFILE% expansion style.
    # A Windows profile name can hold spaces ("Eve Adams"): inside a path (a
    # separator follows) the name runs to that separator, otherwise it is a
    # single run.
    _USER_PATH = re.compile(
        r"(?i)((?:[A-Z]:)?[\\/](?:Users|home)[\\/]+)([^\\/\s\"';]+(?: [^\\/\s\"';]+)*(?=[\\/])|[^\\/\s\"';]+)"
    )
    # A network share named by its host: the Windows UNC form \\host\share
    # (also doubled in a repr, \\\\host\\share) and the forward-slash form
    # //host/share a folder dialog or a cifs mount line uses. A UNC or gvfs
    # folder never goes through secret registration, so the shape itself is
    # scrubbed. The lookbehind keeps a URL's scheme separator ("https://host")
    # and a doubled slash inside a path ("/a//b") out of it.
    _UNC_SHARE = re.compile(r"(?<![\w:/\\])(?:\\{2,}|//)[^\\/\s\"';,]+[\\/]+[^\\/\s\"';,]+")
    # A GNOME gvfs mount spells the share as key=value pairs inside the path
    # (/run/user/1000/gvfs/smb-share:server=nas,share=music, or
    # sftp:host=nas,user=carol). The keys stay, the values go.
    _MOUNT_KV = re.compile(r"(?i)\b(server|host|domain|share|user)=([^,/\\\s\"']+)")
    # A URL query string carries whatever the caller put in it: a search term,
    # an email, an account id. Our own code marks user content with content()
    # so the export can hash it, but a THIRD-PARTY line never does: urllib3's
    # "Retrying ... after connection broken by ...: /v1/search?query=..."
    # reaches the breadcrumb ring and the disk log with the raw needle in it,
    # past the "also hide titles and searches" export switch (which only
    # touches marked spans). No query string is worth keeping, so the whole
    # thing goes; the path in front of it stays, which is what makes the line
    # useful. Requires a "=" so ordinary prose ("why? x") is left alone.
    _URL_QUERY = re.compile(r"(?<![\s'\"])\?[^\s'\"<>|]*=[^\s'\"<>|]*")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: list[tuple[str, str]] = []  # (value, placeholder), longest first
        home = os.path.expanduser("~")
        self._homes = [h for h in {home, os.path.realpath(home)} if h and h != "/"]
        try:
            user = getpass.getuser()
        except Exception:
            user = ""
        self._user_re = re.compile(rf"(?i)\b{re.escape(user)}\b") if len(user) >= 3 else None
        try:
            host = socket.gethostname()
        except Exception:
            host = ""
        names = {host, host.split(".", 1)[0]}
        self._host_res = [re.compile(rf"(?i)\b{re.escape(n)}\b") for n in names if len(n) >= 3]

    def register_secret(self, value: str, placeholder: str = "‹secret›") -> None:
        value = str(value or "")
        if len(value) < 4:  # too short to redact without shredding the text
            return
        with self._lock:
            if all(value != v for v, _ in self._secrets):
                self._secrets.append((value, placeholder))
                self._secrets.sort(key=lambda p: len(p[0]), reverse=True)

    @staticmethod
    def _kv_sub(m: re.Match) -> str:
        """Keep the key and the separator, replace the value. Whichever of
        _KV_SECRET's two arms matched, its three groups are the ones that are
        not None."""
        separator = m.group(2) if m.group(2) is not None else m.group(5)
        quote = m.group(3) if m.group(2) is not None else m.group(6)
        return f"{m.group(1)}{separator}{quote or ''}‹redacted›"

    @staticmethod
    def _ipv6_sub(m: re.Match) -> str:
        s = m.group(0)
        hexish = any(c in "abcdefABCDEF" for c in s)
        if hexish or "::" in s or s.count(":") >= 4:
            return "‹ip›"
        return s  # a clock time such as 12:34:56

    @staticmethod
    def _mount_kv_sub(m: re.Match) -> str:
        key = m.group(1)
        placeholder = {"share": "‹share›", "user": "‹user›"}.get(key.lower(), "‹host›")
        return f"{key}={placeholder}"

    def scrub(self, text: str) -> str:
        with self._lock:
            secrets = list(self._secrets)
        for value, placeholder in secrets:
            text = text.replace(value, placeholder)
        text = self._URL_QUERY.sub("?‹query›", text)
        text = self._BEARER.sub("Bearer ‹redacted›", text)
        text = self._KV_SECRET.sub(self._kv_sub, text)
        text = self._COOKIE_HEADER.sub(r"\1: ‹redacted›", text)
        text = self._MAC.sub("‹mac›", text)
        text = self._IPV6.sub(self._ipv6_sub, text)
        text = self._IPV4.sub("‹ip›", text)
        text = self._EMAIL.sub("‹email›", text)
        text = self._UUID.sub("‹uuid›", text)
        text = self._LONG_HEX.sub("‹hex›", text)
        text = self._B64ISH.sub("‹b64›", text)
        for h in self._homes:
            text = text.replace(h, "~")
        text = self._USER_PATH.sub(r"\1‹user›", text)
        # After the user-path rule: \\host\Users\x must lose the name first,
        # then the host and share in front of it.
        text = self._UNC_SHARE.sub("‹share›", text)
        text = self._MOUNT_KV.sub(self._mount_kv_sub, text)
        if self._user_re is not None:
            text = self._user_re.sub("‹user›", text)
        for host_re in self._host_res:
            text = host_re.sub("‹host›", text)
        return text

    @staticmethod
    def scrub_content(text: str) -> str:
        """The optional second tier: content spans become short stable hashes,
        so distinct values stay distinguishable without being readable."""

        def _hash(m: re.Match) -> str:
            digest = hashlib.sha1(m.group(1).encode("utf-8", "replace"), usedforsecurity=False).hexdigest()[:8]
            return f"{_C_OPEN}#{digest}{_C_CLOSE}"

        return _CONTENT_RE.sub(_hash, text)


_redactor = _Redactor()


def register_secret(value: str, placeholder: str = "‹secret›") -> None:
    """Register a runtime secret (token, account id) for literal redaction.

    Call once whenever a new sensitive value is acquired; every handler scrubs
    it from that moment on. Values shorter than 4 characters are ignored.
    """
    _redactor.register_secret(value, placeholder)


def scrub(text: str, redact_content: bool = False) -> str:
    """Scrub identity PII from ``text`` (and content spans when asked)."""
    text = _redactor.scrub(text)
    if redact_content:
        text = _redactor.scrub_content(text)
    return text


class _RedactingFilter(logging.Filter):
    """Collapses each record to a pre-scrubbed message before any handler
    formats it. Attached to every handler; running twice is harmless because
    the scrub is idempotent."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        scrubbed = _redactor.scrub(message)
        if scrubbed != message or record.args:
            record.msg = scrubbed
            record.args = None
        if record.exc_info and not record.exc_text:
            # Pre-format the traceback so its file paths pass through the
            # scrubber; the formatter then reuses exc_text as-is.
            import traceback as _tb

            record.exc_text = _redactor.scrub("".join(_tb.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = _redactor.scrub(record.exc_text)
        return True
