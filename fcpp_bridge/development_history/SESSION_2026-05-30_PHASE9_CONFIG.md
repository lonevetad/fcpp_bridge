# Session: Phase 9 — Project Configuration File

**Date**: May 30, 2026  
**Branch**: `refactoring/transpilation_codegen`  
**Objective**: Add a YAML/JSON configuration file that lets users define default values for all tuneable knobs (C++ standard, compiler paths, optimisation level, …) without hardcoding them or passing command-line arguments every time.

---

## Summary

30 new tests. 789 → **819/819 tests passing**.

---

## Config file formats (context)

Common config-file standards and their typical use-cases:

| Format | Notes |
|--------|-------|
| **YAML** | Readable, comments supported. Precedence 1. |
| **JSON** | Machine-friendly, universal, Python stdlib. Precedence 2. |
| **TOML** | Used by Rust (`Cargo.toml`), Python packaging (`pyproject.toml`). |
| **INI/CFG** | Python's `configparser`; flat key-value, limited nesting. |
| **XML** | Verbose; still common in Java/enterprise ecosystems. |

YAML and JSON were chosen for this project.

---

## New module: `fcpp_bridge/config/`

### `bridge_config.py` — dataclasses

```python
@dataclass
class TranspilerConfig:
    cpp_standard: CppStandard = CppStandard.CPP17

@dataclass
class CompilerConfig:
    cache_dir:      Path      = Path("build")
    cpp_dir:        Path      = Path("cpp_transpiled")
    gcc_path:       str       = "g++"
    std:            str       = "c++26"
    opt_level:      str       = "2"
    extra_includes: List[str] = field(default_factory=list)

@dataclass
class BridgeConfig:
    transpiler: TranspilerConfig = field(default_factory=TranspilerConfig)
    compiler:   CompilerConfig   = field(default_factory=CompilerConfig)
```

### `_loader.py` — `load_config(start_dir=None) → BridgeConfig`

Search algorithm:
1. Walk from `start_dir` (default: `Path.cwd()`) toward the filesystem root.
2. At each directory, check for `fcpp_bridge.yaml` / `fcpp_bridge.yml` first.
3. Then check for `fcpp_bridge.json`.
4. Stop at the first match.  If no file is found anywhere, return `BridgeConfig()` (all defaults).

YAML handling: tries `import yaml`; if `pyyaml` is not installed and a YAML file was found, raises `ImportError` with an install hint.

`cpp_standard` parsing — accepts any of these forms (case-insensitive):

| Input | Result |
|-------|--------|
| `"17"`, `"cpp17"`, `"c++17"`, `"CPP17"`, `"C++17"` | `CppStandard.CPP17` |
| `"14"`, `"cpp14"`, `"c++14"` | `CppStandard.CPP14` |
| `"20"`, `"cpp20"`, `"c++20"` | `CppStandard.CPP20` |
| `"26"`, `"cpp26"`, `"c++26"` | `CppStandard.CPP26` |

An unrecognised value raises `ValueError` with the full list of valid keys.

---

## Config file: `fcpp_bridge.yaml` (project root)

A ready-to-edit config file with all defaults and inline comments was placed at the repository root.  It is auto-discovered by the loader when running scripts from any subdirectory of the project.

```yaml
transpiler:
  cpp_standard: cpp17   # cpp14 | cpp17 | cpp20 | cpp26

compiler:
  cache_dir: build
  cpp_dir: cpp_transpiled
  gcc_path: g++
  std: c++26            # flag passed to g++; independent of transpiler.cpp_standard
  opt_level: "2"        # 0 | 1 | 2 | 3 | s | g
  extra_includes: []
```

---

## Integration: `Transpiler` and `Compiler`

Both constructors now accept `None` as a sentinel for each config-backed parameter.  When a parameter is `None`, `load_config()` is called lazily (only once) and the relevant field is used.  Explicit non-`None` arguments always override the config.

### `Transpiler.__init__`

```python
def __init__(self, aggregate_class, cpp_std: Optional[CppStandard] = None):
    if cpp_std is None:
        from fcpp_bridge.config import load_config
        cpp_std = load_config().transpiler.cpp_standard
    self.cpp_std = cpp_std
    ...
```

### `Compiler.__init__`

All six parameters (`cache_dir`, `cpp_dir`, `gcc_path`, `std`, `opt_level`, `extra_includes`) now default to `None`.  If any of them is `None`, `load_config().compiler` is consulted once and the missing values are filled in.

---

## Precedence chain (highest → lowest)

1. Explicit constructor argument
2. `fcpp_bridge.yaml` / `.yml` (nearest ancestor directory)
3. `fcpp_bridge.json` (nearest ancestor directory)
4. Hard-coded Python defaults

---

## Dependencies

`pyyaml >= 6.0` added to `pyproject.toml` under `[project] dependencies`.  
Also listed under `[project.optional-dependencies] yaml` for explicit extra installs.

---

## Test count

| Milestone | Tests |
|-----------|-------|
| Before Phase 9 | 789 |
| Config dataclasses + loader | +30 |
| Transpiler config integration | +4 |
| Compiler config integration | +4 |
| **After Phase 9** | **819** |

---

## Files created / modified

### New
- `fcpp_bridge/config/__init__.py`
- `fcpp_bridge/config/bridge_config.py`
- `fcpp_bridge/config/_loader.py`
- `fcpp_bridge/tests/config/__init__.py`
- `fcpp_bridge/tests/config/test_config_loader.py`
- `fcpp_bridge.yaml` (project root)
- `development_history/SESSION_2026-05-30_PHASE9_CONFIG.md` (this file)

### Modified
- `fcpp_bridge/transpiler/transpiler_core.py` — `cpp_std` sentinel
- `fcpp_bridge/compiler/compiler_core.py` — all six params sentinel
- `fcpp_bridge/tests/transpiler/test_transpiler_core.py` — +4 config tests
- `fcpp_bridge/tests/compiler/test_compiler_core.py` — +4 config tests
- `pyproject.toml` — pyyaml dependency
- `development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md`
- `claude_code/MEMORY.md`
