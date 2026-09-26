import pathlib
from dataclasses import dataclass
from typing import Protocol

from requests import HTTPError
from tidalapi.media import Stream, StreamManifest


class _Emitter(Protocol):
    """Anything the engine can ``.emit(...)`` progress through (Qt signal or stand-in)."""

    def emit(self, *args: object) -> None: ...


class ProgressGui(Protocol):
    """The neutral progress-signal shape the engine drives.

    Satisfied structurally by the Qt-backed ``ProgressBars`` in
    waves.model.gui_data (built from live ``_ProgressSignals`` in the
    desktop layer) and by any stand-in carrying the same four emitters.
    Lives here, beside the engine's other neutral types, so
    ``waves.download`` never imports Qt to name it.
    """

    item: _Emitter
    item_name: _Emitter
    list_item: _Emitter
    list_name: _Emitter


@dataclass
class DownloadSegmentResult:
    result: bool
    url: str
    path_segment: pathlib.Path
    id_segment: int
    error: HTTPError | None = None


@dataclass
class TrackStreamInfo:
    """Container for track stream information."""

    stream_manifest: StreamManifest | None
    file_extension: str
    requires_flac_extraction: bool
    media_stream: Stream | None
