# Transpiler Code Generation Refactor Plan

**Date**: 2026-05-29  
**Status**: PHASES 1-9 COMPLETE ✅  
**Priority**: HIGH  
**Scope**: Transpiler core code generation pipeline

---

## Executive Summary

The transpiler successfully converts Python DSL to C++ for simple aggregate functions, but fails to generate valid C++ for production examples like `scattered_database.py`. The generated code is missing critical runtime context, constant definitions, type declarations, and proper FCPP primitive invocations.

**Example failure**:

```cpp
// Generated (INVALID):
auto dist = bis_distance(self_uid() == 0, 1.0, COMM);
// Errors: 'node' undefined, 'COMM' undefined, bis_distance not namespace-qualified
```

**Should generate**:

```cpp
// Required (VALID):
using namespace fcpp::coordination;
constexpr double COMM = 150.0;
auto dist = bis_distance(CALL, self_uid() == 0, 1.0, COMM);
// Now 'node' context available via CALL; COMM defined; bis_distance qualified
```

---

## Root Causes

### 1. Missing `node` Parameter in Compute Function

**Problem**: FCPP's `CALL` macro requires a `node` variable. The generated `compute()` signature lacks it.

**Current**:

```cpp
ScatteredDBState compute(
    const ScatteredDBState& self_state,
    const std::vector<ScatteredDBState>& neighbors)
```

**Required**:

```cpp
ScatteredDBState compute(
    const ScatteredDBState& self_state,
    const std::vector<ScatteredDBState>& neighbors,
    const node_t& node)  // ← Missing
```

**Location**: `fcpp_bridge/transpiler/transpiler_core.py` method `generate()`, function signature generation.

### 2. Module-Level Constants Not Exported

**Problem**: Python module-level constants (e.g., `COMM = 150.0`, `STATUS_TERMINATED = 2`) are not collected or exported to the generated C++ code.

**Current**: Constants used in generated C++ but never defined → linker errors.

**Required**: Scan the aggregate function's module for module-level assignments and generate C++ `constexpr` declarations.

**Location**: `fcpp_bridge/transpiler/transpiler_core.py` — needs new constant extraction logic.

**Scope**: Module-level module constants used in the compute body.

### 3. Missing Type Definitions

**Problem**: Python type hints like `Dict[int, Tuple[float, float]]` and custom types referenced in aggregate function are not translated to C++ type declarations.

**Current**: Types used in C++ but never declared → compilation errors.

**Required**: Extract type definitions from the aggregate function's type hints and dataclass definitions.

**Location**: `fcpp_bridge/transpiler/transpiler_core.py` and possibly `fcpp_bridge/transpiler/python_ast_visitor.py`.

### 4. Missing Using Declarations for FCPP Primitives

**Problem**: FCPP coordination primitives (`bis_distance`, `spawn`, `old`, `sp_collection`) are not namespace-qualified or declared.

**Current**:

```cpp
auto dist = bis_distance(CALL, ...);  // Error: bis_distance not declared
```

**Required**:

```cpp
using namespace fcpp::coordination;
auto dist = bis_distance(CALL, ...);  // Now OK
```

**Location**: Generated C++ runtime header or compute function.

### 5. Python Syntax Bleeding into C++

**Problem**: Python-specific syntax appears in generated C++ (e.g., `False` instead of `false`, `None` instead of `nullptr`).

**Current Examples**:

- `False` (Python) → should be `false` (C++)
- `None` (Python) → should be `nullptr` or `std::nullopt` (C++)
- Python ternary with braces → C++ syntax incompatibility

**Location**: `fcpp_bridge/transpiler/python_ast_visitor.py` expression translation logic.

---

## Proposed Solutions

### Solution 1: Add `node` Parameter to Compute Function

**Task**: Modify function signature generation in `transpiler_core.py`.

**Steps**:

1. Locate where `compute()` function signature is generated in `CppCodeBuilder`
2. Add `const node_t& node` parameter after `neighbors` parameter
3. Ensure this parameter is available in the function body scope for CALL macro expansion
4. Update test expectations in `test_transpiler_core.py`

**Verification**: Generated C++ should have `compute(..., const node_t& node)`

**Effort**: LOW (1-2 hours)

---

### Solution 2: Extract and Export Module-Level Constants

**Task**: Identify constants from the Python module and generate C++ `constexpr` declarations.

**Steps**:

1. Before transpiling the aggregate function, scan the module's global scope for:
   - Numeric literals: `COMM = 150.0`, `QUERY_TIMEOUT = 35`, `N = 15`
   - Enum-like constants: `STATUS_BORDER = 0`, `STATUS_INTERNAL = 1`
   - Collection types used in state: if a constant is used in the compute body, export it
2. Generate `constexpr` declarations for each constant (type inference from value)
3. Prepend to the generated C++ code before the compute function

**Implementation**:

- Add method `extract_module_constants()` to `PythonAstVisitor`
- Modify `generate()` in `CppCodeBuilder` to include extracted constants in preamble
- Handle type inference (int literal → `constexpr int`, float → `constexpr double`)

**Verification**: Generated C++ should have:

```cpp
constexpr double COMM = 150.0;
constexpr int STATUS_TERMINATED = 2;
```

**Effort**: MEDIUM (2-4 hours, requires AST introspection and type inference)

---

### Solution 3: Generate Type Declarations

**Task**: Extract type definitions from dataclass and aggregate function annotations and generate C++ type aliases or structs.

**Steps**:

1. Parse the aggregate function's state dataclass (e.g., `ScatteredDBState`)
2. For each field, map Python type → C++ type:
   - `Dict[K, V]` → `std::unordered_map<K, V>`
   - `Tuple[T1, T2]` → `std::tuple<T1, T2>`
   - `Set[T]` → `std::unordered_set<T>`
   - `List[T]` → `std::vector<T>`
3. Generate struct/typedef in C++ with matching field names
4. Emit type definitions before the compute function

**Implementation**:

- Add method `extract_state_types()` to `PythonAstVisitor`
- Map Python type hints to C++ equivalents in `transpiler/type_mapper.py` (new file)
- Generate type declarations in `CppCodeBuilder.generate()` preamble

**Verification**: Generated C++ should have:

```cpp
using set_t = std::unordered_set<int>;
using dict_t = std::unordered_map<int, std::tuple<float, float>>;
```

**Effort**: HIGH (4-6 hours, requires type annotation parsing and mapping)

---

### Solution 4: Add Using Declarations for FCPP Primitives

**Task**: Inject `using namespace fcpp::coordination;` (or selective `using` declarations) into generated C++.

**Steps**:

1. Identify all FCPP coordination primitives used in the compute body
2. Add `using namespace fcpp::coordination;` at the start of the compute function (or module)
3. Alternatively, use selective `using` declarations for specific primitives (safer)

**Implementation**:

- Scan generated C++ AST for calls to known FCPP primitives
- Inject `using` declarations automatically

**Verification**: Generated C++ should compile without "undeclared identifier" for `bis_distance`, `spawn`, etc.

**Effort**: LOW (1 hour, straightforward injection)

---

### Solution 5: Fix Python-to-C++ Syntax Translation

**Task**: Update expression translator in `python_ast_visitor.py` to emit correct C++ syntax.

**Steps**:

1. Replace `False` → `false`, `True` → `true`
2. Replace `None` → `nullptr` (in pointer contexts) or `std::nullopt` (in Optional contexts)
3. Fix lambda syntax for FCPP compatibility
4. Fix brace-enclosed initializer lists for `vec<>` types

**Implementation**:

- Update `visit_Constant()` in `PythonAstVisitor` to check for `False`, `True`, `None`
- Add context awareness for None → `nullptr` vs `std::nullopt`
- Review lambda generation logic

**Verification**: Generated C++ should use C++ keywords (`false`, `true`) and standard types (`nullptr`).

**Effort**: MEDIUM (2-3 hours, requires careful regex replacement and context awareness)

---

## Implementation Order

**Phase 1 (Critical - Days 1-2)** ✅ COMPLETE:

1. ~~Solution 1 — Add `node` parameter~~ → REJECTED: FCPP node context flows via CALL macro, not explicit param
2. Solution 4 — Add using declarations ✅ (2026-05-30)

**Phase 2 (High Priority - Days 3-4)** ✅ COMPLETE:

3. Solution 2 — Extract module constants ✅ (2026-05-30)
4. Solution 5 — Fix Python-to-C++ syntax ✅ (True→true, False→false, None→nullptr, string escaping) (2026-05-30)

**Phase 3 (Medium Priority - Days 5-6)** ✅ COMPLETE:

5. Solution 3 — Generate type declarations ✅ (set_t alias emitted when frozenset() is used) (2026-05-30)

**Phase 4 (Extended — Bitwise & Arithmetic Gaps)** ✅ COMPLETE (2026-05-30):

6. Solution 6 — Missing binary/unary operators and augmented assignments
   - Binary: `ast.BitOr` → `|`, `ast.BitAnd` → `&`, `ast.BitXor` → `^`
   - Arithmetic: `ast.FloorDiv` → `/` (C++ integer division)
   - Shift: `ast.LShift` → `<<`, `ast.RShift` → `>>`
   - Short-circuit boolean: `ast.And` → `&&`, `ast.Or` → `||` (via `visit_BoolOp`)
   - Bitwise negation: `ast.Invert` → `~` (via `visit_UnaryOp`)
   - Augmented assignments: `|=`, `&=`, `^=`, `<<=`, `>>=`, `//=` (via `visit_AugAssign`)
   - 8+12 = 20 new tests (8 original + 12 added for booleans/invert/augassign)

**Phase 5 (Extended — Membership & Identity Tests)** ✅ COMPLETE (2026-05-30):

7. Solution 7 — `in` / `not in` / `is` / `is not` operators
   - `x in container` → `(container.count(x) > 0)` (works for std::set, std::map, std::unordered_*)
   - `x not in container` → `(container.count(x) == 0)`
   - `x is None` → `(x == nullptr)`, `x is not None` → `(x != nullptr)`
   - 6 new tests

**Phase 6 (Extended — For-Loop Generalization)** ✅ COMPLETE (2026-05-30):

8. Solution 8 — Generic for-loop iteration (non-range)
   - `for x in container:` → `for (auto& x : container) { ... }`
   - `for k, v in dict.items():` → `for (auto& [k, v] : dict) { ... }` (C++17 structured bindings)
   - `for (k1, k2), v in dict.items():` → `for (auto& [_kvkey, v] : dict) { auto& [k1, k2] = _kvkey; ... }`
   - `for k in dict.keys():` → `for (auto& [k, _kv_k] : dict) { ... }`
   - `for v in dict.values():` → `for (auto& [_kv_v, v] : dict) { ... }`
   - 6 new tests

**Phase 7 (Extended — Collection Constructors)** ✅ COMPLETE (2026-05-30):

9. Solution 9 — Python collection constructor calls and set literals
   - `dict(x)` → `x` (C++ copy semantics)
   - `set(iterable)` → `set_t(iterable.begin(), iterable.end())`
   - `set()` → `set_t{}`
   - `{x, y}` (set literal) → `set_t{x, y}`
   - `list(iterable)` → `std::vector<decltype(*iterable.begin())>(iterable.begin(), iterable.end())`
   - `dict.get(key)` → `(dict.count(key) ? dict.at(key) : default_init)`
   - `dict.get(key, default)` → `(dict.count(key) ? dict.at(key) : default)`
   - 11 new tests

**Phase 8 (Extended — CppStandard, dict.keys()/values() expr, comprehensions)** ✅ COMPLETE (2026-05-30):

10. Solution 10 — `CppStandard` enum (`CPP14`/`CPP17`/`CPP20`/`CPP26`), configurable on `Transpiler` and `PythonAstVisitor`; default `CPP17`; added `supports_structured_bindings()` predicate; C++14 emits `.first`/`.second` and `std::get<>` where C++17+ uses structured bindings; C++20/26 mode uses `std::views::keys/values` + `#include <ranges>`
11. Solution 11 — `Dict[K,V]` annotation tracking in `dict_type_env`; `_annotation_to_cpp`/`_annotation_to_dict_types` helpers; concrete types preferred over `decltype` when annotation is present
12. Solution 12 — `dict.keys()` / `dict.values()` in expression context: C++17 IIFE with `std::vector<TYPE>`; C++20 `std::views::keys/values`; `set(d.keys())` special-cased to avoid double IIFE
13. Solution 13 — List comprehensions `[expr for var in iter if cond]` → IIFE with `std::vector<_T>`
14. Solution 14 — Set comprehensions `{expr for var in iter if cond}` → IIFE with `std::set<_T>`
15. Solution 15 — Dict comprehensions `{k: v for var in iter if cond}` → IIFE with `std::map<_K, _V>`
    - All comprehension forms support: `range()`, `d.items()` (k,v), `d.keys()`, `d.values()`, generic container
    - Element type deduced via `_expr_fn` trick (no explicit annotation needed)
    - 41 new tests

**Phase 9 (Project configuration file)** ✅ COMPLETE (2026-05-30):

16. Solution 16 — `fcpp_bridge/config/` module (`BridgeConfig`, `TranspilerConfig`, `CompilerConfig` dataclasses + `load_config()` loader)
    - YAML (`.yaml`/`.yml`) takes precedence over JSON (`.json`); both searched from CWD upward
    - `load_config(start_dir=None)` — `None` → `Path.cwd()`; walks to filesystem root
    - `CppStandard` parsed from multiple notations: `"17"`, `"cpp17"`, `"c++17"` all resolve to `CPP17`
    - `pyyaml >= 6.0` added to `pyproject.toml` dependencies
17. Solution 17 — `Transpiler` and `Compiler` constructors now use `None` as sentinel; config loaded lazily when any param is `None`; explicit args always win
    - `fcpp_bridge.yaml` created at project root with all defaults and inline comments
    - Precedence: explicit arg > YAML config > JSON config > Python defaults
    - 30 new tests (22 loader + 4 Transpiler integration + 4 Compiler integration)

**Phase 9b (Unified C++ standard)** ✅ COMPLETE (2026-05-30):

18. Solution 18 — Collapsed `transpiler.cpp_standard` + `compiler.std` into a single top-level `cpp_standard` in `BridgeConfig`; `CompilerConfig.std` removed; `TranspilerConfig` removed; `Compiler.__init__` derives `-std=c++XX` from `bridge.cpp_standard.value`
    - `fcpp_bridge.yaml` updated: single `cpp_standard:` key at top level
    - Guarantees transpiler code-gen and compiler flag are always in sync

---

## Testing Strategy

### Regression Testing

**Existing**: 817 tests in `fcpp_bridge/tests/` (683 after Phase 3 + 29 Phases 4-7 + 12 Phase 4 extension + 41 Phase 8 + 24 Phase 8b + 30 Phase 9 − 2 Phase 9b)

**Required**: Add transpiler code generation tests

- Create test cases for each solution (separate test file: `test_transpiler_codegen_*.py`)
- Test simple aggregate functions first (already passing)
- Test complex functions with constants, types, primitives

### Integration Testing

**Current**: `examples/scattered_database.py` (currently fails)

**Process**:

1. Fix Phase 1 issues
2. Run `scattered_database.py` — should compile (but may have runtime errors)
3. Fix Phase 2 issues
4. Run `scattered_database.py` — should execute (with correct output)
5. Add more complex examples as Phase 3 proceeds

### Validation Criteria

| Criterion                  | Measure                                | Target               |
| -------------------------- | -------------------------------------- | -------------------- |
| Include path validation    | Compiler preflight check               | ✅ (already passing) |
| Compute function signature | Generated C++ has `node` parameter     | ✅ TBD               |
| CALL macro availability    | Primitives can access `CALL`           | ✅ TBD               |
| Constants exported         | Module-level constants in C++          | ✅ TBD               |
| Type safety                | Type mismatches caught at compile time | ✅ TBD               |
| Python syntax elimination  | No Python keywords in C++              | ✅ TBD               |
| `scattered_database.py`    | Runs and produces correct output       | ✅ TBD               |

---

## Risk Mitigation

| Risk                     | Probability | Impact | Mitigation                                                                                |
| ------------------------ | ----------- | ------ | ----------------------------------------------------------------------------------------- |
| Breaks existing examples | MEDIUM      | HIGH   | Run full test suite after each phase; keep backward compatibility                         |
| Type inference errors    | MEDIUM      | MEDIUM | Start with explicit type annotations; add type annotations to complex aggregate functions |
| Namespace collisions     | LOW         | MEDIUM | Use qualified names (`fcpp::coordination::`) if using declarations conflict               |
| Performance regression   | LOW         | LOW    | Profile generated code after refactor; optimize if needed                                 |

---

## Success Criteria

- [ ] `scattered_database.py` compiles and runs without errors (blocking: dict.keys() in expression context, list comprehensions)
- [x] All existing Python tests still pass (817/817 as of 2026-05-30)
- [x] New transpiler tests added for code generation (29 new from Phases 4-7; total transpiler tests = 200+)
- [x] Generated C++ conforms to FCPP patterns and conventions (using decls, constexpr, set_t, structured bindings)
- [ ] Documentation updated with transpiler capabilities and limitations
- [ ] Example-run instructions work end-to-end

---

## Open Questions & Decisions

1. **Namespace handling**: Use `using namespace fcpp::coordination;` or selective `using` declarations?
   - **Decision**: Use selective `using` declarations for safety (avoid conflicts)

2. **Type mapping scope**: Only dataclass fields, or all Python type annotations?
   - **Decision**: Start with dataclass fields; extend to locals if needed

3. **Constant scope**: Only module-level, or nested class constants?
   - **Decision**: Only module-level for MVP; extend to class-level later

4. **Error reporting**: If constant extraction fails, fail early or emit warning?
   - **Decision**: Fail early with clear error message

---

## Related Issues & Dependencies

- **Prereq**: Include path fix (`<lib/fcpp.hpp>`) — ✅ COMPLETED
- **Prereq**: Compiler validation — ✅ COMPLETED
- **Blocker**: None known
- **Follow-up**: Runtime type serialization (future work after code gen is solid)

---

## Timeline Estimate

| Phase     | Tasks                                          | Estimated Time | Actual Time  |
| --------- | ---------------------------------------------- | -------------- | ------------ |
| 1         | Using declarations                             | 2 days         | 1 day ✅     |
| 2         | Module constants + Python-to-C++ syntax        | 3 days         | 1 day ✅     |
| 3         | set_t type alias                               | 2 days         | 1 day ✅     |
| 4         | Missing binary operators (|, &, ^, //, <<, >>) | 0.5 days       | < 1 hr ✅    |
| 5         | `in` / `not in` / `is` / `is not`              | 0.5 days       | < 1 hr ✅    |
| 6         | Generic for-loop (non-range)                   | 1 day          | < 1 hr ✅    |
| 7         | Collection constructors + set literal + .get() | 1 day          | < 1 hr ✅    |
| **Total** |                                                | **~11 days**   | **~1 day**   |

---

## Author Notes

This plan addresses the root cause of the recent `scattered_database.py` failure. The transpiler was not designed to handle:

- Aggregate functions that use FCPP coordination primitives directly
- Module-level constants referenced in compute logic
- Complex state types with nested collections

The refactor will bring the transpiler to production-readiness for real-world aggregate algorithms. After completing this plan, the transpiler should handle the full spectrum of FE-series exercises (FE-1 through FE-11+) correctly.
