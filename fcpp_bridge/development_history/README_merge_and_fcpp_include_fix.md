# README consolidation and FCPP include-path fix plan

## Problem

Running `python -m fcpp_bridge.examples.scattered_database` fails during compilation with:

```text
fatal error: fcpp/fcpp.hpp: No such file or directory
```

This indicates that the C++ compiler was not given a valid include path to the FCPP headers.

## Root cause

The bridge uses the environment variable `FCPP_INCLUDE_PATH` to pass `-I <path>` to `g++`.
If that variable is not set, not exported in the current shell session, or points to the wrong directory, the generated C++ code cannot find `fcpp/fcpp.hpp`.

## Suggested fix plan

1. Add a clear preflight validation step in the compiler pipeline.
   - In `fcpp_bridge/compiler/compiler_core.py`, detect whether `FCPP_INCLUDE_PATH` is present.
   - Verify that it points to an existing directory and that a recognized FCPP header exists under it.
   - If not, raise an early, user-friendly error pointing the user to the correct FCPP source tree.

2. Consolidate documentation into the root-level `README.md`.
   - Merge the important information from `fcpp_bridge/README.md` into the root `README.md`.
   - Keep the root README as the single source of truth for installation, examples, architecture, and project structure.
   - Delete `fcpp_bridge/README.md` after the merge to avoid confusion and duplication.

3. Strengthen the root README with explicit troubleshooting.
   - Document that `FCPP_INCLUDE_PATH` must point at the FCPP source tree and show verification commands.
   - Use a real path check that matches the local repository layout, e.g. `lib/fcpp.hpp`.
   - Emphasize that the variable must be exported in the same shell where `python -m ...` is executed.

4. Validate locally.
   - Re-run `python -m fcpp_bridge.examples.scattered_database` after setting `FCPP_INCLUDE_PATH`.
   - Add a regression test for invalid `FCPP_INCLUDE_PATH` so the error is raised before invoking `g++`.

## Execution

- Root `README.md` was updated with the new initialization and troubleshooting guidance.
- Duplicate `fcpp_bridge/README.md` was removed after merging its content into the root README.
- `Compiler.compile()` now validates `FCPP_INCLUDE_PATH` if set, ensuring the directory exists and contains a recognizable FCPP header (`lib/fcpp.hpp`, `fcpp/fcpp.hpp`, or `fcpp.hpp`).
- A regression test was added in `fcpp_bridge/tests/compiler/test_compiler_core.py` to catch invalid `FCPP_INCLUDE_PATH` early.

## Result

The root README is now the canonical entrypoint, the FCPP include-path failure is easier to diagnose, and compilation fails with a clearer message when the environment is misconfigured.
