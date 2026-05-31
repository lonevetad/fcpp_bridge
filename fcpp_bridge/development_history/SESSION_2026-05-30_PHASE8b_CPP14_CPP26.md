# Session: Phase 8b — CPP14 and CPP26 in CppStandard + C++14 Fallbacks

**Date**: May 30, 2026  
**Branch**: `refactoring/transpilation_codegen`  
**Objective**: Extend `CppStandard` with `CPP14` and `CPP26` entries and update all code-generation sites that emit structured bindings to provide correct C++14 alternatives.

---

## Summary

24 new tests. 765 → **789/789 tests passing**.

---

## Changes

### `transpiler/_cpp_standard.py`

Added two new enum members:

| Member | Value | `flag()` | `supports_structured_bindings()` | `supports_ranges()` |
|--------|-------|----------|----------------------------------|---------------------|
| `CPP14` | 14 | `-std=c++14` | `False` | `False` |
| `CPP17` | 17 | `-std=c++17` | `True` (default) | `False` |
| `CPP20` | 20 | `-std=c++20` | `True` | `True` |
| `CPP26` | 26 | `-std=c++26` | `True` | `True` |

New method added: **`supports_structured_bindings()`** — returns `True` for C++17 and above.  
`supports_ranges()` already covered C++26 via `>= 20`.

---

### `transpiler/python_ast_visitor.py` — Six code-generation sites updated

All sites that previously always emitted C++17 structured bindings now branch on `self.cpp_std.supports_structured_bindings()`.

#### 1. `visit_For` — flat dict.items()

| Standard | Generated code |
|----------|----------------|
| C++17+ | `for (auto& [k, v] : d) { body }` |
| C++14 | `for (auto& _kv : d) { auto& k = _kv.first; auto& v = _kv.second; body }` |

#### 2. `visit_For` — nested tuple dict.items()

| Standard | Generated code |
|----------|----------------|
| C++17+ | `for (auto& [_kvkey, v] : d) { auto& [k1, k2] = _kvkey; body }` |
| C++14 | `for (auto& _kv : d) { auto& v = _kv.second; auto& k1 = std::get<0>(_kv.first); auto& k2 = std::get<1>(_kv.first); body }` |

`std::get<>` works on both `std::pair` and `std::tuple` since C++11.

#### 3. `visit_For` — dict.keys() / dict.values()

| Standard | `.keys()` | `.values()` |
|----------|-----------|-------------|
| C++17+ | `for (auto& [k, _kv_k] : d)` | `for (auto& [_kv_v, v] : d)` |
| C++14 | `for (auto& _kv : d) { auto& k = _kv.first; }` | `for (auto& _kv : d) { auto& v = _kv.second; }` |

#### 4. `_comp_for_header` — comprehension for-loop headers

Same branching as `visit_For`; the body preamble slot (second return value, previously always `""`) is now populated for C++14 dict iteration. `_make_comprehension_iife` was updated to insert this preamble at the start of the loop body.

#### 5. `_make_dict_comprehension_iife` — dict comprehension dict.items() case

C++17+: `for (auto& [k, v] : d) { assign }`  
C++14: `for (auto& _kv : d) { auto& k = _kv.first; auto& v = _kv.second; assign }`

#### 6. `visit_Call` — `dict.keys()`/`dict.values()` expression IIFEs and `set(d.keys())`

All three IIFE templates now use `_kv.first`/`_kv.second` for C++14 instead of `[_k, _v]` structured bindings.

---

## Feature matrix (all standards)

| Feature | C++14 | C++17 | C++20 | C++26 |
|---------|-------|-------|-------|-------|
| Generic lambdas (`auto` params) | ✓ | ✓ | ✓ | ✓ |
| Structured bindings | ✗ | ✓ | ✓ | ✓ |
| `std::decay_t`, `decltype` | ✓ | ✓ | ✓ | ✓ |
| `std::get<>` on pair/tuple | ✓ | ✓ | ✓ | ✓ |
| `std::optional` | ✗ | ✓ | ✓ | ✓ |
| `std::views::keys/values` | ✗ | ✗ | ✓ | ✓ |
| IIFE comprehensions | ✓ | ✓ | ✓ | ✓ |

---

## Test count

| Milestone | Tests |
|-----------|-------|
| Before Phase 8b | 765 |
| Phase 8b enum values (CPP14/CPP26) | +7 |
| Phase 8b `supports_structured_bindings` | +4 |
| Phase 8b C++14 code-gen | +11 |
| Phase 8b C++26 code-gen | +2 |
| **After Phase 8b** | **789** |

---

## Files modified

- `transpiler/_cpp_standard.py`
- `transpiler/python_ast_visitor.py`
- `tests/transpiler/test_python_ast_visitor.py`
- `tests/transpiler/test_transpiler_core.py`
- `development_history/SESSION_2026-05-30_PHASE8b_CPP14_CPP26.md` (this file)
- `development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md`
- `claude_code/MEMORY.md`
