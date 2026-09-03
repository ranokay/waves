"""The Provider seam: one fused interface every music provider implements
(the wayfinder map's destination design), with the neutral types the engine,
bridge, and tests share. TIDAL is the first implementation; Apple Music is
the second, behind the same methods.

The concrete provider modules are loaded lazily (PEP 562): importing
``waves.providers.base`` -- the neutral half -- must never drag an
implementation in, because the implementations import the engine module
(``waves.download``) for the bodies they delegate to, and the engine imports
this package's base. An eager re-export here would make that import order a
cycle; a lazy one keeps every direction working.
"""

from waves.constants import QualityTier, quality_rank, tier_from_word
from waves.providers.base import (
    AudioType,
    BrowseWindow,
    Capability,
    FavoritesUnavailable,
    Provider,
    Refusal,
    RefusalKind,
    StreamInfo,
)

_LAZY = {
    "TidalProvider": ("waves.providers.tidal", "TidalProvider"),
}


def __getattr__(name: str):
    try:
        module_name, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None  # noqa: TRY003 from None
    import importlib

    return getattr(importlib.import_module(module_name), attr)


def __dir__() -> list[str]:
    return sorted(list(globals()) + list(_LAZY))


__all__ = [
    "AudioType",
    "BrowseWindow",
    "Capability",
    "FavoritesUnavailable",
    "Provider",
    "QualityTier",
    "Refusal",
    "RefusalKind",
    "StreamInfo",
    "TidalProvider",
    "quality_rank",
    "tier_from_word",
]
