"""Project-level configuration: load fcpp_bridge.yaml / fcpp_bridge.json."""

from .bridge_config import BridgeConfig, CompilerConfig
from ._loader import load_config

__all__ = [
    "BridgeConfig",
    "CompilerConfig",
    "load_config",
]
