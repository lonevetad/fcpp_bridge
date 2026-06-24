# Open Questions — v2.0 Plan

**Created:** 2026-05-30  
**Branch:** `refactoring/transpilation_codegen`  
**Status:** PENDING — all items below are open  
**Priority:** HIGH (raised by developer after reviewing provided_prompt.txt)

---

## Context

After completing Phases 1–9b of the transpiler code-generation refactor (all 817 tests
passing), several deeper architectural questions were raised. They concern the shape of the
**generated C++ output**, the **role of Jinja2 templates**, and the **overall usability
of the bridge** for real-world aggregate programming.

---

## Open Questions & Proposed Solutions

---

### OQ-1 — C++ Code Generation via Jinja2 Templates

**Problem statement (Italian original):**
> "la generazione del codice C++ dovrebbe riempire un template, il quale deve essere
> estratto dagli esempi già forniti da Giorgio e da me stesso — e il template deve anche
> prevedere la definizione di 0+ funzioni di supporto e 0+ f.d.s. aggregate"

**Summary:**
The current transpiler assembles C++ by concatenating strings inside `transpiler_core.py`.
This makes the output structure hard to read, test, and evolve.
The correct approach is to define one or more Jinja2 template files that mirror the
structure of a real FCPP program (as seen in Giorgio's examples and in the project's own
`fcpp-exercises/`) and then *hydrate* those templates with the data extracted by the
Python AST visitor.

**Scope of a single template:**
- A file-level template (e.g., `aggregate_program.cpp.j2`) that renders the complete
  `.cpp` file.
- Slots for: `includes`, `using_declarations`, `constexpr_constants`, `type_aliases`,
  `helper_functions` (0+), `aggregate_helper_functions` (0+, decorated with `AGGREGATE`
  macro), and the **mandatory main aggregate function**.

**Proposed implementation steps:**

1. Create `fcpp_bridge/transpiler/templates/` directory.
2. Write `aggregate_program.cpp.j2` capturing the canonical FCPP program skeleton.
3. Introduce a `TemplateRenderer` class (or a `render_cpp` function) that accepts a
   `CppRenderContext` dataclass and returns the filled string via `jinja2.Environment`.
4. Replace the current string-concatenation logic in `CppCodeBuilder.generate()` with a
   call to `render_cpp(context)`.
5. Add unit tests that compare rendered output against known-good `.cpp` snapshots.

**Prerequisite:** `Jinja2 >= 3.0` must be listed in `pyproject.toml` (see OQ-1a below).

---

### OQ-1a — Add Jinja2 as an Explicit Dependency

**Problem:** `Jinja2` is not currently listed in `pyproject.toml` dependencies.

**Fix:** Add `Jinja2>=3.0` to the `dependencies` list and update all "installation and
prerequisites" documentation sections:

- `README.md` — Prerequisites table
- `TUTORIAL_simple.md` — Prerequisites table
- `TUTORIAL_in_depth.md` — Prerequisites section
- `DEPLOYMENT.md` — if a prerequisites section exists

---

### OQ-2 — Missing Explicit Definition of the Main Aggregate Function

**Problem statement:**
> "manca infatti una esplicita definizione della 'main aggregate function'"

**Summary:**
The current generated C++ output wraps the algorithm inside an `AGGREGATE_TEMPLATE(main)`
block, but the *entry-point aggregate function* is not visibly named or exposed with the
signature that FCPP expects. In a real FCPP program the user defines something like:

```cpp
AGGREGATE_TEMPLATE(main) { ... }    // correct skeleton
```

The transpiler must guarantee that exactly one such function is emitted with the
`AGGREGATE_TEMPLATE(main)` (or equivalent) macro, and that it is the last function in the
file so that any helper aggregate functions it calls are already declared.

**Proposed implementation steps:**

1. Extend the Jinja2 template (from OQ-1) with a dedicated `main_aggregate` block.
2. Ensure the `@aggregate_function`-decorated class that is marked as the entry point
   is rendered into this block (and only this block).
3. Add a validation step in `Transpiler.validate()` that rejects sources with zero or
   more than one `@aggregate_function` marked as `is_main=True`.

---

### OQ-3 — Storage Management in the Compiled C++ Code

**Problem statement:**
> "come viene gestito lo storage, nel codice compilato? Sembra del tutto assente ..."

**Summary:**
FCPP programs store per-node state in typed "storage" fields accessible via
`node.storage(tag{})`. The current generated C++ does not emit the `using` alias that
registers each field with the FCPP storage system, nor does it populate those fields at
the end of the `main` aggregate function.

In a real FCPP program the pattern is:

```cpp
// 1. Declare storage tags:
DECLARE_OPTIONS(options, exports<output_t<double>>);

// 2. At the end of the aggregate body:
node.storage(output_tag{}) = result_value;
```

**Proposed implementation steps:**

1. Survey the existing FCPP exercises (`fcpp-exercises/`) to catalogue all storage
   patterns used (tags, types, assignment sites).
2. Extend the state-type extraction logic in the transpiler to also emit:
   - `struct <fieldname>_tag {};` declarations for each exported field
   - `using exports_t = fcpp::common::exports<...>;` alias
   - Storage assignments at the end of the `AGGREGATE_TEMPLATE(main)` body
3. Document the mapping: Python `@dataclass` field → FCPP storage tag.

---

### OQ-4 — Role of the Python Simulation in Examples

**Problem statement:**
> "a che serve la simulazione nel sorgente Python? Non dovrebbe bastare definire:
>  la funzione aggregata main, la definizione del tipo di storage,
>  il modo in cui si definisce la ricezione ed il consumo degli 'node updates'"

**Summary:**
Several examples contain a *pure-Python re-simulation* of the aggregate algorithm that
runs without any FCPP toolchain. This was added as a no-install fallback, but it
duplicates the algorithm and misleads developers into thinking the Python simulation
*is* the aggregate program.

The correct architecture (as clarified in the v1.9 plan, Steps E + F) is:
1. Define the algorithm once using `@aggregate_function` in Python DSL.
2. Transpile → compile → run the C++ binary.
3. Consume node updates via `OutputChannel` / log files.

The pure-Python simulation fallback should either be:
- **Removed** from production examples, or
- **Kept only** as an explicit, separate, clearly-labelled `_simulate_pure_python()` method
  with a comment explaining it is not the real algorithm.

**Proposed implementation steps:**

1. Audit all files under `examples/` for `_demo_simulate` / `_simulate` / equivalent
   pure-Python loops that re-implement the aggregate algorithm.
2. For each such file, decide (with developer) whether to keep or remove the pure-Python path.
3. Update `AbstractExample` to remove or isolate the simulation scaffold.
4. Update the tutorials and `README.md` to describe the correct toolchain-only workflow.

---

### OQ-5 — Transpilation of FCPP `field<T>` Types

**Problem statement:**
> "come vengono traspilati 'field'?"

**Summary:**
FCPP's `field<T>` is the distributed data type that represents a "field" over the
neighbourhood — each neighbour can hold a different value of type `T`. The Python DSL
currently represents neighbourhood data implicitly (via `nbr`, `old`, etc.), but it has
no explicit `field<T>` type annotation or transpilation rule.

**Proposed implementation steps:**

1. Investigate how `field<T>` appears in the FCPP C++ headers and exercises.
2. Decide whether the Python DSL needs a `Field[T]` type alias (e.g., wrapping
   `nbr(default_value)` return type) or whether it is always implicit.
3. If explicit annotation is needed, add `Field[T]` to `python_dsl/types.py` and map it
   to `field<T>` in the type mapper.
4. Update the Jinja2 template to emit `field<T>` in parameter and return-type positions.

---

### OQ-6 — Exported Function Types as `make_tuple` Aliases

**Problem statement:**
> "le classi che verranno usate come 'tipo di dato esportato da una funzione aggregata'
>  non dovrebbe essere definito come 'using nome_funzione_t = make_tuple<...>;'?"

**Summary:**
In real FCPP programs the "exported type" of an aggregate function is often defined as:

```cpp
using scattered_db_t = std::tuple<int, fcpp::common::map_dev<int, pos_t>>;
```

rather than as a `struct`. The current transpiler emits a `struct` for the state type,
which may not match FCPP's `export_list` mechanism (which expects `std::tuple`-compatible
types).

**Proposed implementation steps:**

1. Check the FCPP `export_list` documentation in the exercises and headers.
2. Add a code-gen option (`emit_as_tuple: bool`, default `false`) that, when set,
   renders the state type as a `using <name>_t = std::tuple<...>` alias rather than
   a `struct`.
3. Update the Jinja2 template to support both forms.
4. Provide guidance in the DSL docs on when each form is required.

---

### OQ-7 — Network Size and Area Size as Configurable Items ✅ DONE (2026-05-30)

**Problem statement:**
> "aggiungere la dimensione iniziale del network e la dimensione dell'area alle
>  'cose configurabili'"

**Summary:**
The initial node count and the simulation area dimensions are currently hardcoded in each
example file. They should be first-class configuration keys so that a developer can tune
them from `fcpp_bridge.yaml` without touching source files.

**Implementation (completed):**

1. Added to `BridgeConfig` (`bridge_config.py`):
   - `network_size: int = 20`
   - `area_size: Tuple[float, float] = (500.0, 500.0)`
2. `_loader.py`: `_parse_area_size()` helper + `_build_config()` reads both keys from
   YAML/JSON; validation raises `ValueError` on wrong shape/type.
3. `fcpp_bridge.yaml`: two new documented keys at the top level (`network_size`,
   `area_size`).
4. `AbstractExample` gained two lazy config-backed properties:
   - `default_network_size` → `load_config().network_size`
   - `default_area_size` → `load_config().area_size`
   Individual examples keep their own module-level constants (which are intentionally
   algorithm-specific); the config keys serve as a global default for new examples and
   for developers tuning runs without editing source.
5. 12 new tests added to `test_config_loader.py`; **829/829 tests pass** (up from 817).

---

### OQ-8 — Single Entry Point for the Bridge Pipeline

**Problem statement:**
> "invece di invocare gli 'esempi' direttamente e richiedere che esso venga auto-letto,
>  traspilato, etc., non converrebbe invece invocare un singolo punto di accesso e
>  fornirgli il nome/path del file da 'digerire, transpilare, etc.'"

**Summary:**
Currently each example is run directly (`python -m fcpp_bridge.examples.scattered_database`).
There is no universal CLI that accepts a Python file path and runs the full pipeline on it.
A single entry point would look like:

```bash
python -m fcpp_bridge run path/to/my_algorithm.py
# or:
fcpp-bridge run path/to/my_algorithm.py
```

**Proposed implementation steps:**

1. Create `fcpp_bridge/__main__.py` with a `run` sub-command (use `argparse` or `click`).
2. The `run` sub-command should:
   a. Load the Python file as a module (or parse its `@aggregate_function` class).
   b. Run the full pipeline: validate → transpile → write C++ → compile → execute.
   c. Accept `--steps` / `--from-step` arguments (already planned in the tutorials).
3. Register a console-script entry point in `pyproject.toml`:
   ```toml
   [project.scripts]
   fcpp-bridge = "fcpp_bridge.__main__:main"
   ```
4. Update tutorials and README to show the new CLI invocation style.
5. Keep the `python -m fcpp_bridge.examples.X` path working for backward compatibility.

---

## Implementation Order

| Priority | Item  | Depends on    | Estimated effort |
|----------|-------|---------------|-----------------|
| 1        | OQ-1a | —             | 1 h (docs + pyproject) |
| 2        | OQ-1  | OQ-1a         | 1–2 days        |
| 3        | OQ-2  | OQ-1          | 0.5 days        |
| 4        | OQ-3  | OQ-1, OQ-2    | 1–2 days        |
| 5        | OQ-7  | —             | 2–3 h           |
| 6        | OQ-8  | OQ-7          | 0.5–1 day       |
| 7        | OQ-5  | OQ-1          | 0.5 days        |
| 8        | OQ-6  | OQ-3, OQ-5    | 0.5 days        |
| 9        | OQ-4  | OQ-2, OQ-3    | 0.5 days (cleanup) |

**Total estimated effort:** ~6–8 days

---

## Success Criteria

- [ ] `Jinja2>=3.0` in `pyproject.toml`; `pip install -e .` installs it automatically
- [ ] All C++ is rendered from Jinja2 template(s), not string concatenation
- [ ] Template supports 0-N helper functions and 0-N aggregate helper functions
- [ ] `main` aggregate function is always emitted last and clearly labelled
- [ ] Storage tags and assignments are emitted correctly
- [ ] `field<T>` is handled in type mapper and template
- [x] `network_size` and `area_size` are top-level YAML keys ✅
- [ ] `fcpp-bridge run <file>` CLI works end-to-end
- [x] All 829+ tests still pass after each item is completed ✅ (OQ-7: 829/829)

---

## Files Expected to Change

| File | Change |
|------|--------|
| `fcpp_bridge/transpiler/transpiler_core.py` | Replace string concat with Jinja2 `render_cpp()` |
| `fcpp_bridge/transpiler/templates/aggregate_program.cpp.j2` | New Jinja2 template |
| `fcpp_bridge/transpiler/template_renderer.py` | New `TemplateRenderer` / `render_cpp` |
| `fcpp_bridge/config/bridge_config.py` | Add `network_size`, `area_size` |
| `fcpp_bridge/config/_loader.py` | Parse new config keys |
| `fcpp_bridge/__main__.py` | New CLI entry point |
| `pyproject.toml` | `Jinja2>=3.0`, `fcpp-bridge` script |
| `fcpp_bridge.yaml` | New keys: `network_size`, `area_size` |
| `README.md` | Jinja2 prerequisite, CLI docs |
| `TUTORIAL_simple.md` | Jinja2 prerequisite |
| `TUTORIAL_in_depth.md` | Jinja2 prerequisite |
