import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from .compilation_error import CompilationError
from .compilation_result import CompilationResult
from .program_cache import ProgramCache
from fcpp_bridge.log import get_logger

_log = get_logger(__name__)


class Compiler:
    """Invoke GCC to compile C++ code.

    Constructor parameters
    ----------------------
    cache_dir        Where compiled binaries are cached.
    cpp_dir          Where generated C++ source files are written.
    gcc_path         Path to the g++ executable.
    std              C++ standard flag value — e.g. "c++14", "c++17", "c++26".
    opt_level        Optimisation level digit/letter — "0", "1", "2", "3",
                     "s", "g".
    extra_includes   Additional include directories prepended with -I.

    Any parameter left as *None* is read from ``fcpp_bridge.yaml`` /
    ``fcpp_bridge.json`` if such a file is found (searching from CWD upward).
    When no config file exists the built-in defaults are used:
    cache_dir="build", cpp_dir="cpp_transpiled", gcc_path="g++",
    std="c++26", opt_level="2", extra_includes=[].
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        cpp_dir: Optional[Path] = None,
        gcc_path: Optional[str] = None,
        std: Optional[str] = None,
        opt_level: Optional[str] = None,
        extra_includes: Optional[List[str]] = None,
    ):
        if any(v is None for v in (cache_dir, cpp_dir, gcc_path, std, opt_level)):
            from fcpp_bridge.config import load_config
            bridge = load_config()
            cfg = bridge.compiler
            if cache_dir is None:
                cache_dir = cfg.cache_dir
            if cpp_dir is None:
                cpp_dir = cfg.cpp_dir
            if gcc_path is None:
                gcc_path = cfg.gcc_path
            if std is None:
                # Derive from the unified cpp_standard setting.
                std = f"c++{bridge.cpp_standard.value}"
            if opt_level is None:
                opt_level = cfg.opt_level
            if extra_includes is None:
                extra_includes = list(cfg.extra_includes)

        self.cache_dir: Path = cache_dir
        self.cpp_dir: Path = cpp_dir
        self.gcc_path: str = gcc_path
        self.std: str = std
        self.opt_level: str = opt_level
        self.extra_includes: List[str] = list(extra_includes)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cpp_dir.mkdir(parents=True, exist_ok=True)
        self.cache = ProgramCache(cache_dir)

    def compile(
        self,
        cpp_file: Path,
        output_binary: Path,
        extra_flags: List[str] = None,
    ) -> CompilationResult:
        """Compile C++ file to executable.

        extra_flags are appended after all other flags so they can override
        defaults (e.g. pass ["-O0"] to override the constructor's opt_level
        for a single file without recreating the Compiler).
        """
        if not cpp_file.exists():
            raise CompilationError(f"C++ source not found: {cpp_file}")

        start = time.time()

        flags = [
            f"-std={self.std}",
            "-Wall",
            "-Wextra",
            f"-O{self.opt_level}",
        ]
        fcpp_include = os.environ.get("FCPP_INCLUDE_PATH")
        if fcpp_include:
            fcpp_path = Path(fcpp_include)
            if not fcpp_path.is_dir():
                raise CompilationError(
                    f"FCPP_INCLUDE_PATH is set to {fcpp_include} but the directory does not exist"
                )
            header_candidates = [
                fcpp_path / "lib" / "fcpp.hpp",
                fcpp_path / "fcpp" / "fcpp.hpp",
                fcpp_path / "fcpp.hpp",
            ]
            if not any(candidate.exists() for candidate in header_candidates):
                raise CompilationError(
                    "FCPP_INCLUDE_PATH is set but does not contain a recognized FCPP header. "
                    "Verify it points to the FCPP source tree (for example, the directory that contains "
                    "lib/fcpp.hpp or fcpp/fcpp.hpp)."
                )
            flags.extend(["-I", fcpp_include])
        for inc in self.extra_includes:
            flags.extend(["-I", inc])

        _sys = platform.system()
        if _sys == "Windows" or (_sys == "Linux" and shutil.which("lld") is not None):
            flags.append("-fuse-ld=lld")

        if extra_flags:
            flags.extend(extra_flags)

        cmd = [
            self.gcc_path,
            *flags,
            str(cpp_file),
            "-o", str(output_binary),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            elapsed = time.time() - start

            if result.returncode != 0:
                return CompilationResult(
                    success=False,
                    binary_path=None,
                    stderr=result.stderr,
                    stdout=result.stdout,
                    compile_time_seconds=elapsed,
                )

            if not output_binary.exists():
                return CompilationResult(
                    success=False,
                    binary_path=None,
                    stderr="Binary not created",
                    stdout=result.stdout,
                    compile_time_seconds=elapsed,
                )

            return CompilationResult(
                success=True,
                binary_path=output_binary,
                stderr=result.stderr,
                stdout=result.stdout,
                compile_time_seconds=elapsed,
            )

        except subprocess.TimeoutExpired:
            return CompilationResult(
                success=False,
                binary_path=None,
                stderr="Compilation timeout (>120s)",
                stdout="",
                compile_time_seconds=120.0,
            )
        except Exception as e:
            return CompilationResult(
                success=False,
                binary_path=None,
                stderr=str(e),
                stdout="",
                compile_time_seconds=0.0,
            )

    def get_or_compile(self, cpp_code: str, program_name: str = "program") -> Path:
        """Get cached binary, or compile if not cached."""
        cached = self.cache.lookup(cpp_code)
        if cached and cached.exists():
            _log.debug("Cache hit: %s", cached)
            return cached

        cache_key = self.cache.get_key(cpp_code)
        cpp_file = self.cpp_dir / f"{program_name}_{cache_key}.cpp"
        binary_path = self.cache_dir / f"{program_name}_{cache_key}"

        cpp_file.write_text(cpp_code)
        _log.info("Generated: %s", cpp_file)

        _log.info("Compiling %s ...", cpp_file)
        result = self.compile(cpp_file, binary_path)

        if not result.success:
            _log.error("Compilation failed")
            if result.stderr:
                _log.error("  stderr: %s", result.stderr[:500])
            if result.stdout:
                _log.error("  stdout: %s", result.stdout[:500])
            raise CompilationError(
                f"Compilation failed: {result.stderr or result.stdout}"
            )

        _log.info("Success: %s (%.2fs)", binary_path,
                  result.compile_time_seconds)

        self.cache.store(cpp_code, binary_path)

        return binary_path

    def clear_cache(self) -> None:
        """Clear all cached binaries."""
        for f in self.cache_dir.glob("*"):
            if f.is_file() and f.name != ".cache_manifest":
                f.unlink()
        self.cache.manifest.clear()
        self.cache._save_manifest()
        _log.info("Cache cleared")

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            "cached_binaries": len(self.cache.manifest),
            "cache_dir_size_bytes": sum(
                f.stat().st_size for f in self.cache_dir.glob("*") if f.is_file()
            ),
        }
