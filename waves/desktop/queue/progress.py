"""Qt progress emitters supplied to the provider-neutral download engine."""

from dataclasses import dataclass

from PySide6.QtCore import SignalInstance


@dataclass
class ProgressBars:
    """Satisfies waves.model.downloader.ProgressGui without changing the engine."""

    item: SignalInstance
    item_name: SignalInstance
    list_item: SignalInstance
    list_name: SignalInstance
