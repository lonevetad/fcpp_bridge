# fcpp-bridge

Python-to-FCPP-C++ transpilation and IPC bridge for aggregate programming.

Defines aggregate algorithms in Python, transpiles them to C++14 for the
[FCPP](https://github.com/fcpp/fcpp) runtime, and communicates with the compiled
swarm via JSON IPC — all from Python.

## Prerequisites

| Requirement | Notes |
|---|---|
| Python ≥ 3.10 | `python3 --version` |
| g++ with C++14 support | `g++ --version` |
| CMake ≥ 3.14 | `cmake --version` (optional — only needed by `CmakeGenerator`) |
| FCPP C++ library | Apache 2.0 — see setup below |

### FCPP Library Setup

`fcpp-bridge` does **not** bundle FCPP source files.  Clone it once and export the path:

```bash
git clone https://github.com/fcpp/fcpp.git /path/to/fcpp
export FCPP_INCLUDE_PATH=/path/to/fcpp/src
# Add to ~/.bashrc or ~/.zshrc to make permanent
```

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

## Running Tests

```bash
# All 675 tests are pure Python — no C++ compiler or FCPP headers needed
pytest fcpp_bridge/tests/ -v
```

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
