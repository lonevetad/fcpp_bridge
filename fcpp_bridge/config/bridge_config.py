from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

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
    """
    cpp_standard: CppStandard = CppStandard.CPP17
    compiler: CompilerConfig = field(default_factory=CompilerConfig)
