"""The Provider seam: one fused interface every music provider implements
(the wayfinder map's destination design), with the neutral types the engine,
bridge, and tests share. TIDAL is the first implementation; Apple Music is
the second, behind the same methods.
"""

from waves.providers.base import (
    AudioType,
    Capability,
    Provider,
    QualityTier,
    Refusal,
    RefusalKind,
    StreamInfo,
    quality_rank,
)
from waves.providers.tidal import TidalProvider, tier_from_tidal

__all__ = [
    "AudioType",
    "Capability",
    "Provider",
    "QualityTier",
    "Refusal",
    "RefusalKind",
    "StreamInfo",
    "TidalProvider",
    "quality_rank",
    "tier_from_tidal",
]
