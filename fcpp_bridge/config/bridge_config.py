from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from fcpp_bridge.transpiler._cpp_standard import CppStandard


@dataclass
class CompilerConfig:
    cache_dir: Path = Path("build")
    cpp_dir: Path = Path("cpp_transpiled")
    gcc_path: str = "g++"
    opt_level: str = "2"
    extra_includes: List[str] = field(default_factory=list)


@dataclass
class BridgeConfig:
    """Root project configuration.

    ``cpp_standard`` is the single source of truth for both transpiler code
    generation and the compiler ``-std=`` flag.  Set it once; both components
    read it automatically.

    ``network_size`` and ``area_size`` are simulation defaults that
    :class:`~fcpp_bridge.examples.abstract_example.AbstractExample` subclasses
    can read via ``load_config()`` instead of hardcoding values.
    """
    cpp_standard: CppStandard = CppStandard.CPP17
    compiler: CompilerConfig = field(default_factory=CompilerConfig)
    # Default initial node count for simulations.
    network_size: int = 20
    # Default simulation area as (width, height) in the same units used by
    # FCPP's geometry primitives (e.g. rectangle_walk).
    area_size: Tuple[float, float] = (500.0, 500.0)
