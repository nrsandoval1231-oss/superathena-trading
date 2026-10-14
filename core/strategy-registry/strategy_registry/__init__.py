"""Strategy manifest discovery."""
from .registry import StrategyManifest, discover, load_entrypoint

__all__ = ["StrategyManifest", "discover", "load_entrypoint"]
