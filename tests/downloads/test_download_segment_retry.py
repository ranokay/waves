"""Body-read retry inside one segment fetch.

The shared session's ``Retry(total=5)`` covers connection setup, redirects and
response headers only. A body that drops mid-stream raises inside the chunk
loop, so ``Download._download_segment`` owns a bounded three-attempt retry of
its own: a failed attempt rewinds exactly the progress steps it added, every
attempt rewrites the segment file from byte zero, and Stop/Cancel ends the
fetch quietly.

The HTTP boundary is faked; the progress table, the segment file and the
threading events are real.
"""

from __future__ import annotations

import pathlib
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from waves.download import Download
from waves.model.downloader import DownloadSegmentResult
from waves.progress import Progress

URL = "https://cdn.example/secret-token/seg_0"
PATH_SEGMENT = "seg_0"


class _Response:
    """A streamed response double: headers pass, chunks arrive, then it fails."""

    def __init__(
        self,
        chunks: tuple[bytes, ...] = (),
        *,
        status: int = 200,
        error: Exception | None = None,
        before_error=None,
        on_chunk=None,
    ) -> None:
        self.chunks = chunks
        self.status_code = status
        self.error = error
        self.before_error = before_error
        self.on_chunk = on_chunk
        self.url = URL
        self.closed = False

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc) -> bool:
        self.closed = True
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            # Real requests puts the response on the error; the retry classifier
            # and DownloadSegmentResult.error read it.
            raise requests.HTTPError(f"{self.status_code} error for url: {self.url}", response=self)

    def iter_content(self, chunk_size: int | None = None):
        for chunk in self.chunks:
            yield chunk
            if self.on_chunk is not None:
                self.on_chunk()
        if self.before_error is not None:
            self.before_error()
        if self.error is not None:
            raise self.error


class _Session:
    """The faked HTTP boundary: ordered responses, or one script per URL."""

    def __init__(
        self,
        responses: list[_Response] | None = None,
        *,
        routes: dict[str, list[_Response]] | None = None,
        on_get=None,
    ) -> None:
        if responses and routes:
            raise ValueError("script either ordered responses or per-URL routes, not both")
        self.responses = list(responses or ())
        self.routes = {url: list(items) for url, items in (routes or {}).items()}
        self.calls: list[str] = []
        self._used = dict.fromkeys(self.routes, 0)
        self._lock = threading.Lock()
        self._on_get = on_get

    def get(self, url: str, **_kwargs) -> _Response:
        with self._lock:
            index = len(self.calls)
            self.calls.append(url)
            if self.routes:
                used = self._used.get(url)
                if used is None:
                    raise AssertionError(f"segment made an unexpected GET for {url}")
                self._used[url] = used + 1
                responses = self.routes[url]
            else:
                used = index
                responses = self.responses
            if used >= len(responses):
                raise AssertionError(f"segment made an extra GET for {url}")
            response = responses[used]
        if self._on_get is not None:
            self._on_get(index)
        return response


class _Harness:
    def __init__(
        self,
        responses: list[_Response] | None = None,
        *,
        routes: dict[str, list[_Response]] | None = None,
        completed: float = 0,
        on_get=None,
    ) -> None:
        self.download = Download.__new__(Download)  # bypass __init__; drive the download methods only
        self.download.settings = MagicMock()
        self.download.settings.data.downloads_simultaneous_per_track_max = 4
        self.download.event_abort = threading.Event()
        self.download.event_run = threading.Event()
        self.download.event_run.set()
        self.download.fn_logger = MagicMock()
        self.download.progress = Progress()
        self.download.progress_gui = MagicMock()
        self.download._segment_executor = None
        self.download._segment_executor_lock = threading.Lock()
        self.download._http = _Session(responses, routes=routes, on_get=on_get)
        self.task = self.download.progress.add_task("test", total=100, completed=completed)

    @property
    def calls(self) -> list[str]:
        return self.download._http.calls

    @property
    def completed(self) -> float:
        return self.download.progress.tasks[self.task].completed

    @property
    def errors(self) -> list[str]:
        return [call.args[0] for call in self.download.fn_logger.error.call_args_list]

    @property
    def warnings(self) -> list[str]:
        return [call.args[0] for call in self.download.fn_logger.warning.call_args_list]

    def run(self, tmp_path: pathlib.Path, event_stop: threading.Event | None = None) -> DownloadSegmentResult:
        return self.download._download_segment(URL, tmp_path, None, self.task, True, event_stop)

    def run_track(
        self,
        tmp_path: pathlib.Path,
        urls: list[str],
        n_tail_spurious: int | None = None,
        event_stop: threading.Event | None = None,
    ) -> tuple[bool, list[DownloadSegmentResult]]:
        return self.download._download_segments(urls, tmp_path, None, self.task, True, event_stop, n_tail_spurious)

    def segment(self, tmp_path: pathlib.Path, name: str = PATH_SEGMENT) -> pathlib.Path:
        return tmp_path / name


def _urls(count: int) -> list[str]:
    return [f"https://cdn.example/secret-token/seg_{index}" for index in range(count)]


def _drop(message: str = "Connection broken: IncompleteRead(8 bytes read, 2 more expected)") -> Exception:
    return requests.exceptions.ChunkedEncodingError(message)


def test_a_dropped_body_retries_and_returns_only_the_second_body(tmp_path):
    """A half-read body must not fail the segment when the next GET lands."""
    h = _Harness(
        [
            _Response((b"first-", b"attempt"), error=_drop()),
            _Response((b"second", b"-attempt")),
        ]
    )

    result = h.run(tmp_path)

    assert result.result is True
    assert h.segment(tmp_path).read_bytes() == b"second-attempt"
    assert len(h.calls) == 2
    assert len(h.warnings) == 1
    assert h.errors == []
    assert "ChunkedEncodingError" in h.warnings[0]
    assert "secret-token" not in h.warnings[0]


def test_every_dropped_attempt_makes_three_gets_and_logs_one_class_only_error(tmp_path):
    """A required segment's third failure logs one class-only error; the existing
    corrupt line for the failed track stays.
    """
    h = _Harness([_Response((b"x" * 8,), error=_drop()) for _ in range(3)])

    ok, results = h.run_track(tmp_path, [URL])

    assert ok is False
    assert results[0].result is False
    assert len(h.calls) == 3
    class_errors = [line for line in h.errors if "ChunkedEncodingError" in line]
    assert len(class_errors) == 1
    assert "secret-token" not in class_errors[0]
    assert "IncompleteRead" not in class_errors[0]
    assert any("File is corrupt" in line for line in h.errors)
    assert h.completed == 0  # every attempt took its 8 chunks back


def test_a_retry_rewinds_only_the_failed_attempts_steps(tmp_path):
    """Bar at 3, first attempt streams 8 of 10 chunks then drops, retry streams
    all 10: the bar reads 13, not 21."""
    h = _Harness(
        [
            _Response((b"a" * 8,), error=_drop()),
            _Response(tuple(b"b" for _ in range(10))),
        ],
        completed=3,
    )

    result = h.run(tmp_path)

    assert result.result is True
    assert h.completed == 13


def test_exhausted_attempts_leave_the_bar_where_the_retry_started(tmp_path):
    """Bar at 3, all three attempts drop after 8 chunks: the bar stays at 3."""
    h = _Harness([_Response((b"x" * 8,), error=_drop()) for _ in range(3)], completed=3)

    result = h.run(tmp_path)

    assert result.result is False
    assert len(h.calls) == 3
    assert h.completed == 3


def test_a_4xx_is_not_retried_and_carries_the_http_error(tmp_path):
    """A refusal is permanent: one GET, and the caller receives the HTTPError."""
    h = _Harness([_Response(status=404)])

    result = h.run(tmp_path)

    assert result.result is False
    assert len(h.calls) == 1
    assert isinstance(result.error, requests.HTTPError)
    assert result.error.response.status_code == 404


def test_a_5xx_is_retried_and_succeeds_on_the_next_get(tmp_path):
    """A server fault is transient: the next GET's body is the result."""
    h = _Harness([_Response(status=503), _Response((b"final", b"-body"))])

    result = h.run(tmp_path)

    assert result.result is True
    assert len(h.calls) == 2
    assert h.segment(tmp_path).read_bytes() == b"final-body"
    assert result.error is None


def test_a_stop_during_a_failing_attempt_ends_the_fetch_quietly(tmp_path):
    """The attempt fails while a Stop is in force: fail without an error log."""
    event_stop = threading.Event()
    h = _Harness(
        [
            _Response(
                (b"one",),
                error=_drop(),
                before_error=event_stop.set,
            )
        ],
        completed=3,
    )

    result = h.run(tmp_path, event_stop)

    assert result.result is False
    assert len(h.calls) == 1
    assert h.errors == []
    assert h.warnings == []  # no retry is claimed when the stop rules it out
    assert h.completed == 3  # the failed attempt's step is taken back


def test_a_stop_during_the_retry_wait_does_not_issue_another_get(tmp_path):
    """A Stop between attempts must end the fetch before the retry GET."""
    event_stop = threading.Event()
    timer = threading.Timer(0.05, event_stop.set)
    h = _Harness(
        [
            _Response(
                (b"one", b"two"),
                error=_drop(),
                before_error=timer.start,
            ),
            _Response((b"never",)),
        ],
        completed=3,
    )

    result = h.run(tmp_path, event_stop)
    timer.join(1)

    assert result.result is False
    assert len(h.calls) == 1
    assert h.errors == []
    assert h.completed == 3  # the failed attempt's steps are taken back
    assert not h.segment(tmp_path).read_bytes().startswith(b"never")


def test_every_attempt_rewrites_the_segment_file_from_zero(tmp_path):
    """A partial first body is never appended to; the retry's bytes replace it."""
    h = _Harness(
        [
            _Response((b"stale-partial-body",), error=_drop()),
            _Response((b"fresh",)),
        ]
    )

    result = h.run(tmp_path)

    assert result.result is True
    assert h.segment(tmp_path).read_bytes() == b"fresh"


def test_a_non_request_failure_is_not_retried_and_rewinds_its_steps(tmp_path):
    """A disk-side OSError is permanent: no retry, no raise, class-only log."""
    h = _Harness(
        [
            _Response((b"step",), error=OSError("disk full at /secret/volume")),
            _Response((b"never",)),
        ],
        completed=3,
    )

    ok, results = h.run_track(tmp_path, [URL])

    assert ok is False
    assert results[0].result is False
    assert results[0].error is None
    assert len(h.calls) == 1
    assert h.completed == 3
    class_errors = [line for line in h.errors if "OSError" in line]
    assert len(class_errors) == 1
    assert "/secret/volume" not in class_errors[0]
    assert any("File is corrupt" in line for line in h.errors)


@pytest.mark.parametrize(
    ("status", "tail_gets", "n_tail_spurious"),
    [
        (500, 3, 1),  # proven padding, body/status failure retried
        (404, 1, 1),  # proven padding, permanent status not retried
        (500, 3, None),  # manifest proved nothing: legacy leniency
    ],
)
def test_a_tolerated_tail_failure_logs_no_error(tmp_path, status, tail_gets, n_tail_spurious):
    """A multi-URL track's spurious tail is padding: the track succeeds with no
    segment failure logged, whatever its status did.
    """
    urls = _urls(2)
    h = _Harness(
        routes={
            urls[0]: [_Response((b"audio",))],
            urls[1]: [_Response(status=status) for _ in range(tail_gets)],
        }
    )

    ok, results = h.run_track(tmp_path, urls, n_tail_spurious=n_tail_spurious)

    assert ok is True
    assert h.calls.count(urls[1]) == tail_gets
    assert h.errors == []
    assert h.segment(tmp_path, "seg_0").read_bytes() == b"audio"
    tail = next(result for result in results if result.url == urls[1])
    assert tail.result is False  # tolerated, not silently successful


def test_a_stopped_track_logs_no_segment_failure(tmp_path):
    """A Stop during the failing attempt leaves the track seam silent too."""
    event_stop = threading.Event()
    h = _Harness([_Response((b"one",), error=_drop(), before_error=event_stop.set)])

    ok, _results = h.run_track(tmp_path, [URL], event_stop=event_stop)

    assert ok is False
    assert len(h.calls) == 1
    assert h.errors == []


def test_a_stop_during_the_retry_wait_logs_no_segment_failure(tmp_path):
    """The same silence holds when the failed attempt did name a class and the
    Stop arrives in the wait before the retry.
    """
    event_stop = threading.Event()
    timer = threading.Timer(0.05, event_stop.set)
    h = _Harness([_Response((b"one",), error=_drop(), before_error=timer.start)])

    ok, results = h.run_track(tmp_path, [URL], event_stop=event_stop)
    timer.join(1)

    assert ok is False
    assert len(h.calls) == 1
    assert h.errors == []
    assert results[0].failure_class == "ChunkedEncodingError"  # the carrier was populated


def test_the_failed_response_is_closed_before_the_retry_get(tmp_path):
    """A waiting segment must hold no connection from the blocking shared pool."""
    first = _Response(status=500)
    h = _Harness([first, _Response((b"ok",))])

    def assert_closed_before_retry(index: int) -> None:
        if index == 1:
            assert first.closed is True

    h.download._http._on_get = assert_closed_before_retry

    result = h.run(tmp_path)

    assert result.result is True
    assert len(h.calls) == 2


def test_a_paused_job_never_starts_the_retry_get(tmp_path):
    """A retry GET waits on _wait_while_paused; aborting there ends quietly."""
    failed_once = threading.Event()

    def pause_after_failure() -> None:
        h.download.event_run.clear()
        failed_once.set()

    h = _Harness(
        [
            _Response((b"one",), error=_drop(), before_error=pause_after_failure),
            _Response((b"never",)),
        ]
    )
    results: list[DownloadSegmentResult] = []
    worker = threading.Thread(target=lambda: results.append(h.run(tmp_path)), daemon=True)

    worker.start()
    assert failed_once.wait(2)
    # Longer than the retry delay: an unpaused job would have issued the GET.
    time.sleep(Download._SEGMENT_RETRY_DELAY_SEC + 0.3)
    assert len(h.calls) == 1
    assert worker.is_alive()

    h.download.event_abort.set()
    worker.join(2)

    assert not worker.is_alive()
    assert len(h.calls) == 1
    assert len(results) == 1
    assert results[0].result is False
    assert h.errors == []
    assert h.completed == 0  # the failed attempt's step is taken back
