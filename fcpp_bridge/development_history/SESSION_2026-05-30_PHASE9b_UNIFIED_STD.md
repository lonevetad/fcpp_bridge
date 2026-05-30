# Session: Phase 9b — Unified C++ Standard

**Date**: May 30, 2026  
**Branch**: `refactoring/transpilation_codegen`  
**Objective**: Enforce a single C++ standard setting that drives both transpiler code generation and the compiler `-std=` flag, eliminating the previous silent split between the two.

---

## Motivation

Phase 9 introduced `transpiler.cpp_standard` and `compiler.std` as two separate config keys.  A user could accidentally set them to different values, causing the transpiler to generate C++17 structured bindings while the compiler was told to use C++14 — silently broken output.

**Fix**: collapse both into a single top-level `cpp_standard` key.  Setting it once is guaranteed to flow to both components.

---

## Changes

### `bridge_config.py`

- Removed `TranspilerConfig` dataclass (it only held `cpp_standard`, now moved up).
- Removed `CompilerConfig.std` field (now derived from `BridgeConfig.cpp_standard`).
- Added `BridgeConfig.cpp_standard: CppStandard = CppStandard.CPP17`.

```python
@dataclass
class CompilerConfig:
    cache_dir:      Path      = Path("build")
    cpp_dir:        Path      = Path("cpp_transpiled")
    gcc_path:       str       = "g++"
    opt_level:      str       = "2"
    extra_includes: List[str] = field(default_factory=list)

@dataclass
class BridgeConfig:
    cpp_standard: CppStandard = CppStandard.CPP17   # single source of truth
    compiler: CompilerConfig   = field(default_factory=CompilerConfig)
```

### `_loader.py`

`cpp_standard` is now parsed from the **top level** of the config dict (not nested under `transpiler:`).

```yaml
# Before (Phase 9):
transpiler:
  cpp_standard: cpp17
compiler:
  std: c++26

# After (Phase 9b):
cpp_standard: cpp17          # one key, drives both components
compiler:
  ...                        # no std here
```

### `config/__init__.py`

Removed `TranspilerConfig` from the public export list.

### `transpiler_core.py`

```python
# Before:
cpp_std = load_config().transpiler.cpp_standard
# After:
cpp_std = load_config().cpp_standard
```

### `compiler_core.py`

```python
# Before (Phase 9):
std = cfg.std   # came from CompilerConfig.std

# After (Phase 9b):
std = f"c++{bridge.cpp_standard.value}"  # derived from unified enum
```

An explicit `std=` argument to `Compiler()` still overrides the derived value — useful as an escape hatch.

### `fcpp_bridge.yaml`

Removed `transpiler:` section and `compiler: std:` key.  Now:

```yaml
cpp_standard: cpp17   # controls both code gen and -std= compiler flag

compiler:
  cache_dir: build
  cpp_dir: cpp_transpiled
  gcc_path: g++
  opt_level: "2"
  extra_includes: []
```

---

## Precedence chain (unchanged)

1. Explicit constructor argument (`cpp_std=` or `std=`)
2. `fcpp_bridge.yaml` / `.yml`  `cpp_standard:` key  
3. `fcpp_bridge.json`  `cpp_standard:` key  
4. Hard-coded Python default (`CppStandard.CPP17`)

---

## Test count

| Milestone | Tests |
|-----------|-------|
| Phase 9 (config system) | 819 |
| Phase 9b — removed `TranspilerConfig` test | −1 |
| Phase 9b — consolidated `extra_includes_independent` | −1 |
| **After Phase 9b** | **817** |

No new tests were needed: existing tests were updated in-place.

---

## Files modified

- `fcpp_bridge/config/bridge_config.py`
- `fcpp_bridge/config/_loader.py`
- `fcpp_bridge/config/__init__.py`
- `fcpp_bridge/transpiler/transpiler_core.py`
- `fcpp_bridge/compiler/compiler_core.py`
- `fcpp_bridge.yaml`
- `fcpp_bridge/tests/config/test_config_loader.py`
- `fcpp_bridge/tests/transpiler/test_transpiler_core.py`
- `fcpp_bridge/tests/compiler/test_compiler_core.py`
- `development_history/SESSION_2026-05-30_PHASE9b_UNIFIED_STD.md` (this file)
- `development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md`
- `claude_code/MEMORY.md`
