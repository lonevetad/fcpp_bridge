# fcpp-bridge

Python-to-FCPP-C++ transpilation and IPC bridge for aggregate programming.

Defines aggregate algorithms in Python, transpiles them to C++14 for the
[FCPP](https://github.com/fcpp/fcpp) runtime, and communicates with the compiled
swarm via JSON IPC — all from Python.

## Prerequisites

| Requirement            | Notes                                                          |
| ---------------------- | -------------------------------------------------------------- |
| Python ≥ 3.10          | `python3 --version`                                            |
| g++ with C++14 support | `g++ --version`                                                |
| CMake ≥ 3.14           | `cmake --version` (optional — only needed by `CmakeGenerator`) |
| FCPP C++ library       | Apache 2.0 — see setup below                                   |

### FCPP Library Setup

`fcpp-bridge` does **not** bundle FCPP source files. Clone it once and export the path:

```bash
git clone https://github.com/fcpp/fcpp.git /path/to/fcpp
export FCPP_INCLUDE_PATH=/path/to/fcpp/src
# If you want this to be available in every new shell:
echo 'export FCPP_INCLUDE_PATH=/path/to/fcpp/src' >> ~/.bashrc
source ~/.bashrc
```

This environment variable must point to the FCPP `src/` directory. The compiler checks for a recognizable FCPP header path such as `lib/fcpp.hpp` or `fcpp/fcpp.hpp`.
In the current checkout the valid header path is `lib/fcpp.hpp`, and theoretically only one of these layouts should be the correct one for a given FCPP source tree.
If compilation fails with:

```text
fatal error: fcpp/fcpp.hpp: No such file or directory
```

then verify that the variable is set correctly:

```bash
python -c "import os; print(os.environ.get('FCPP_INCLUDE_PATH'))"
ls "$FCPP_INCLUDE_PATH/lib/fcpp.hpp"
```

Set `FCPP_INCLUDE_PATH` in the same shell session where you run `python -m fcpp_bridge.examples...`.

> Reminder: if you open a new terminal after exporting `FCPP_INCLUDE_PATH`, re-export it or source your shell profile again before running the example.

## Installation

```bash
git clone <this-repo-url> fcpp_bridge
cd fcpp_bridge

# Create a virtual environment and install in editable mode
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

After this, `import fcpp_bridge` works from any directory without any `PYTHONPATH` prefix.

## Verify your environment

Before running examples, make sure `FCPP_INCLUDE_PATH` is visible to the current shell and points to the FCPP `src/` directory:

```bash
python -c "import os; print(os.environ.get('FCPP_INCLUDE_PATH'))"
ls "$FCPP_INCLUDE_PATH/lib/fcpp.hpp"
```

If this check fails, export `FCPP_INCLUDE_PATH` again in the same terminal session before continuing.

## Running Tests

```bash
# All 817 tests are pure Python — no C++ compiler or FCPP headers needed
pytest fcpp_bridge/tests/ -v
```

## Configuration

Project-wide defaults live in a `fcpp_bridge.yaml` (or `.yml`) file placed in your project directory.
The library walks up from the current working directory to the filesystem root searching for this file;
`fcpp_bridge.json` is used as a fallback when no YAML file is found.

```yaml
# fcpp_bridge.yaml
cpp_standard: cpp17    # drives both transpiler code-gen AND -std= compiler flag
                       # accepted values: cpp14 | cpp17 (default) | cpp20 | cpp26

compiler:
  cache_dir: build
  cpp_dir: cpp_transpiled
  gcc_path: g++
  opt_level: "2"
  extra_includes: []
```

**Precedence** (highest → lowest): explicit constructor argument → YAML config → JSON config → built-in default (`cpp17`).

When `Transpiler()` or `Compiler()` are constructed without explicit arguments they load the nearest config file automatically.
Passing an explicit value always overrides the config — the two components are always kept in sync.

> **PyYAML**: YAML support requires `pyyaml>=6.0`, which is installed automatically by `pip install -e .`.

## Running Examples

```bash
# Requires g++ and FCPP_INCLUDE_PATH set (see Prerequisites)
python -m fcpp_bridge.examples.spreading_collection
python -m fcpp_bridge.examples.worker_role_assignment
python -m fcpp_bridge.examples.scattered_database

# Validate + transpile only (no C++ toolchain required):
python -c "
from fcpp_bridge.examples.scattered_database import ScatteredDBAggregate
from fcpp_bridge.examples._example_utils import report_validation, report_transpilation
report_validation(ScatteredDBAggregate)
report_transpilation(ScatteredDBAggregate)
"
```

## Overview

`fcpp_bridge` is a production-ready bridge between Python and the FCPP C++ runtime.
It lets Python programs:

1. Define aggregate functions using a Python DSL
2. Transpile those functions to optimized C++ code
3. Compile dynamically with caching
4. Execute compiled swarms
5. Communicate with swarms via IPC
6. Monitor metrics
7. Visualize swarm output live or replay

## Known Limitations

### Transpiler Code Generation ✅ (Phases 1–9b complete)

Previously known code-generation issues are now resolved:

- **FCPP primitive qualification** — All coordination primitives receive automatic `using`-declarations and `CALL` macro injection (Phase 1).
- **Module-level constants** — Constants defined at module level are emitted as `constexpr` declarations in generated C++ (Phases 2–3).
- **Python syntax in C++** — `True`/`False`/`None` and Python-only operators are correctly mapped to C++ equivalents (Phases 2–3).
- **Custom state types** — Common collection annotations (`Dict`, `List`, `Set`, `Tuple`, `FrozenSet`) are translated to C++ type aliases (Phases 4–8).
- **C++ standard selection** — Four standards are supported: `cpp14`, `cpp17` (default), `cpp20`, `cpp26`.  Set once in `fcpp_bridge.yaml` and both the transpiler and compiler use it automatically (Phases 8b, 9–9b).

See [TRANSPILER_CODEGEN_REFACTOR_PLAN.md](fcpp_bridge/development_history/TRANSPILER_CODEGEN_REFACTOR_PLAN.md) for the complete refactor history (817/817 tests passing).

## Project Phases

This repository is organized into phased components:

- Phase 1: Python DSL layer
- Phase 2: Transpiler (Python → C++)
- Phase 3: Compiler pipeline
- Phase 4: Runtime & IPC
- Phase 5: Language parser
- Phase 6: Scaling & backends
- Phase 7: Visualization & ANTLR generation

## Architecture

```
Python Program
    ↓ (DSL definition / parser)
AggregateProgram (Python class)
    ↓ (transpile)
C++ source code
    ↓ (compile + cache)
Executable binary
    ↓ (spawn subprocess)
Swarm process
    ↓ (IPC: JSON, HTTP, gRPC)
Python receives state updates
    ↓ (MetricsCollector)
Statistics / JSON / CSV export
```

## File Structure

```
fcpp_bridge/
├── python_dsl/
├── transpiler/
├── compiler/
├── runtime/
├── ipc/
├── grammar/
├── metrics/
├── visualization/
├── examples/
├── tests/
├── cpp_transpiled/   ← generated sources
└── build/            ← compiled binaries
```

## No-Install Alternative

If you prefer not to use a virtual environment, prefix every command:

```bash
PYTHONPATH=. python -m fcpp_bridge.examples.worker_role_assignment
PYTHONPATH=. pytest fcpp_bridge/tests/ -v
```

## License

Apache License 2.0 — see [LICENSE.txt](LICENSE.txt).

This project requires the FCPP library (also Apache 2.0) as an external dependency.
See [NOTICE.md](NOTICE.md) for third-party attribution.
