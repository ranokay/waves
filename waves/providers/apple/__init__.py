"""Apple Music provider: the catalog/session seam and its engine pieces.

Callers import the provider and its refusals from this package; the internal
modules (engine, files, integrity, runtime, supervision) stay private to it.
"""

from waves.providers.apple.provider import (
    AppleCatalogUnavailable,
    AppleCollectionIncomplete,
    AppleProvider,
)

__all__ = ["AppleCatalogUnavailable", "AppleCollectionIncomplete", "AppleProvider"]
