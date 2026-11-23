"""Apple Music provider: the catalog/session seam and its engine pieces.

Callers import the provider and its refusals from this package; the engine
pieces (engine, files, integrity, runtime, supervision) are addressed by the
bridge's Apple runner directly.
"""

from waves.providers.apple.provider import (
    AppleCatalogUnavailable,
    AppleCollectionIncomplete,
    AppleProvider,
)

__all__ = ["AppleCatalogUnavailable", "AppleCollectionIncomplete", "AppleProvider"]
