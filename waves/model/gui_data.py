from dataclasses import dataclass

from waves.constants import QualityTier, QualityVideo

try:
    from PySide6 import QtCore

    @dataclass
    class ProgressBars:
        """Qt-backed progress emitters; satisfies ``ProgressGui`` structurally."""

        item: QtCore.SignalInstance
        item_name: QtCore.SignalInstance
        list_item: QtCore.SignalInstance
        list_name: QtCore.SignalInstance

except (ImportError, OSError):
    # Qt-less imports (the engine side): same shape so call sites type-check
    # against either branch (the values are only emitted where Qt exists).
    @dataclass
    class ProgressBars:
        item: object
        item_name: object
        list_item: object
        list_name: object


@dataclass
class ResultItem:
    position: int
    artist: str
    title: str
    album: str
    duration_sec: int
    obj: object
    quality: str
    explicit: bool
    date_user_added: str
    date_release: str


@dataclass
class QueueDownloadItem:
    status: str
    name: str
    type_media: str
    quality_audio: QualityTier
    quality_video: QualityVideo
    obj: object
