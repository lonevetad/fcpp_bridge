"""Config file loader: YAML (preferred) > JSON fallback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

from fcpp_bridge.transpiler._cpp_standard import CppStandard

_YAML_NAMES = ("fcpp_bridge.yaml", "fcpp_bridge.yml")
_JSON_NAMES = ("fcpp_bridge.json",)

# Mapping from normalised user strings → CppStandard enum member.
_STD_MAP: Dict[str, CppStandard] = {}
for _s in CppStandard:
    _v = str(_s.value)
    _n = _s.name.lower()       # "cpp14", "cpp17", …
    _STD_MAP[_v] = _s          # "17"
    _STD_MAP[_n] = _s          # "cpp17"
    _STD_MAP[f"c++{_v}"] = _s  # "c++17"


def _find_config(names: tuple, start: Path) -> Optional[Path]:
    """Walk from *start* toward root; return first matching filename."""
    cur = start.resolve()
    while True:
        for name in names:
            candidate = cur / name
            if candidate.is_file():
                return candidate
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return None


def _parse_file(path: Path) -> dict:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError(
                f"Config file '{path}' is YAML but PyYAML is not installed. "
                "Run: pip install pyyaml   (or: pip install fcpp-bridge[yaml])"
            ) from None
        return yaml.safe_load(text) or {}
    elif suffix == ".json":
        return json.loads(text)
    return {}


def _parse_std(raw_value: object) -> CppStandard:
    key = str(raw_value).lower().strip()
    result = _STD_MAP.get(key)
    if result is None:
        valid = ", ".join(sorted(_STD_MAP))
        raise ValueError(
            f"Unknown cpp_standard {raw_value!r} in config. "
            f"Valid values: {valid}"
        )
    return result


def _build_config(raw: dict) -> "BridgeConfig":
    from .bridge_config import BridgeConfig, CompilerConfig

    # cpp_standard is top-level — single source of truth for both components.
    cpp_std = (
        _parse_std(raw["cpp_standard"])
        if "cpp_standard" in raw
        else CppStandard.CPP17
    )

    c_raw: dict = raw.get("compiler") or {}
    compiler = CompilerConfig(
        cache_dir=Path(c_raw.get("cache_dir", "build")),
        cpp_dir=Path(c_raw.get("cpp_dir", "cpp_transpiled")),
        gcc_path=str(c_raw.get("gcc_path", "g++")),
        opt_level=str(c_raw.get("opt_level", "2")),
        extra_includes=list(c_raw.get("extra_includes") or []),
    )

    return BridgeConfig(cpp_standard=cpp_std, compiler=compiler)


def load_config(start_dir: Optional[Path] = None) -> "BridgeConfig":
    """Load project config from YAML or JSON file, or return all-defaults.

    Search order (YAML always beats JSON at the same directory level):
    1. ``fcpp_bridge.yaml`` / ``fcpp_bridge.yml``  in *start_dir* or any
       ancestor directory.
    2. ``fcpp_bridge.json`` in the same search path.

    If no file is found, a :class:`BridgeConfig` with factory defaults is
    returned — callers are never required to create a config file.
    """
    from .bridge_config import BridgeConfig

    start = (start_dir or Path.cwd()).resolve()
    yaml_path = _find_config(_YAML_NAMES, start)
    json_path = _find_config(_JSON_NAMES, start)

    config_path = yaml_path or json_path
    if config_path is None:
        return BridgeConfig()

    raw = _parse_file(config_path)
    return _build_config(raw)
