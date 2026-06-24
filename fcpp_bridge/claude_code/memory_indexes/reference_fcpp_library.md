---
name: reference-fcpp-library
description: "FCPP C++14 aggregate programming library — all primitives, CALL macro, state/export_list, Python DSL rules, project layout; skill at <project>/.claude/commands/fcpp-library.md"
metadata:
  node_type: memory
  type: reference
  originSessionId: 30462d41-0a8b-4ed3-9933-02f384ad3e82
---

FCPP implements **Field Calculus** — an aggregate programming model. Each node runs
the same program, shares values with 1-hop neighbours each round, and distributed
algorithms emerge from these local interactions.

## Primary skill file

`<project>/.claude/commands/fcpp-library.md` — invoke with `/fcpp-library` for full reference.

## FCPP headers

```cpp
#include <fcpp/fcpp.hpp>                   // umbrella header
#include <lib/coordination/basics.hpp>     // nbr, old, spawn, count_hood
#include <lib/coordination/utils.hpp>      // min_hood, max_hood, fold_hood
#include <lib/coordination/spreading.hpp>  // bis_distance, abf_distance, broadcast
#include <lib/coordination/collection.hpp> // sp_collection, mp_collection
#include <lib/coordination/geometry.hpp>   // rectangle_walk, follow_target
```

## CALL macro pattern (critical)

Every FCPP aggregate primitive must be called in the **same order** at every node every round.

- `FUN void MAIN(ARGS) { CODE ... }` — aggregate function boilerplate
- `bis_distance(CALL, ...)` — CALL expands to `node, trace_t{trace, ++call_point}`
- `self_uid()` → `node.uid` — **not a CALL-counter primitive**; safe inside switch/if
- **Never** call any primitive inside a conditional; all primitives unconditional, branching after

## All primitives (Python DSL → C++)

| Python DSL                                 | C++                                          | Header         |
| ------------------------------------------ | -------------------------------------------- | -------------- |
| `nbr(value)`                               | `nbr(CALL, value)` → field<T>                | basics.hpp     |
| `old(init, lambda)`                        | `old(CALL, init, fn)` → T                    | basics.hpp     |
| `count_hood()`                             | `count_hood(CALL)` → int                     | basics.hpp     |
| `spawn(lambda, key)`                       | `spawn(CALL, fn, key)` → map<K,V>            | basics.hpp     |
| `min_hood(field)`                          | `min_hood(CALL, field)` → T                  | utils.hpp      |
| `max_hood(field)`                          | `max_hood(CALL, field)` → T                  | utils.hpp      |
| `fold_hood(fn, field, init)`               | `fold_hood(CALL, fn, field, init)` → T       | utils.hpp      |
| `bis_distance(is_src, speed, comm)`        | `bis_distance(CALL, is_src, spd, com)` → dbl | spreading.hpp  |
| `abf_distance(is_src)`                     | `abf_distance(CALL, is_src)` → double        | spreading.hpp  |
| `broadcast(is_src, value)`                 | `broadcast(CALL, dist, value)` → T           | spreading.hpp  |
| `sp_collection(dist, loc, null, fn)`       | `sp_collection(CALL, d, l, n, fn)` → T       | collection.hpp |
| `mp_collection(dist, loc, null, acc, div)` | `mp_collection(CALL, ...)` → T               | collection.hpp |
| `rectangle_walk(min, max, spd, period)`    | `rectangle_walk(CALL, ...)` → void           | geometry.hpp   |
| `follow_target(pos, speed)`                | `follow_target(CALL, pos, spd)` → void       | geometry.hpp   |
| `self_uid()`                               | `node.uid` → device_t (no CALL)              | —              |

## Spawn status codes (must match fcpp::status enum exactly)

```python
SPAWN_STATUS_BORDER     = 0   # fcpp::status::border — off routing path
SPAWN_STATUS_INTERNAL   = 1   # fcpp::status::internal — actively routing
SPAWN_STATUS_TERMINATED = 2   # fcpp::status::terminated_output — answer at destination
```

Import from: `fcpp_bridge.examples._example_utils`

## export_list rule (C++ compile error prevention)

If `nbr(CALL, X)` is called and `X`'s type is not in `main_t`'s `export_list`, the C++
binary won't compile. Fix: add the type to `export_list` in CMakeLists.  
See memory entry [[project-fcpp-export-list-rule]] for details.

## Python DSL rules (fcpp_bridge transpiler constraints)

1. **No `from __future__ import annotations`** — turns all annotations to strings; transpiler fails
2. **No `Tuple[float, ...]`** — Ellipsis in tuple args not handled; use `Tuple[float, float]`
3. **No `Any`** — no C++ mapping; use concrete types
4. **All primitives unconditional** — call before any if/match branching
5. **State dataclass fields** must use C++-compatible types from `typing`
6. `old(0, lambda prev: prev+1)` — two-arg form is preferred over one-arg

## fcpp_bridge key files

- `python_dsl/` — `@aggregate_function`, `Neighborhood`, primitive stubs
- `transpiler/transpiler_core.py` — Python AST → C++ source
- `python_dsl/types/aggregate_type.py` — Python type → C++ type inference
- `compiler/` — CMake/g++ invocation, SHA-256 cache
- `ipc/swarm_process.py` — launch binary, JSON IPC
- `examples/abstract_example.py` — Template Method base class
- `examples/_example_utils.py` — SPAWN*STATUS*\*, neighbors_of, build_positions

## Exercises (FE-9/10/11) — implemented 2026-05-29

- `examples/ex_utils/tiles.py` — Sutherland-Hodgman tile grid + clipping
- `examples/scattered_database.py` — FE-9: distributed shard query via spawn
- `examples/area_discovery.py` — FE-10: nbr+fold_hood tile-centre sharing
- `examples/iteratively_area_discovery.py` — FE-11: 4-state machine, 2 scatter_databases, election

## Field Calculus primitives (theory)

- `nbr(e)` → neighbouring field: each device sees `e` from its 1-hop neighbours
- `old(e)` → temporal lift: value of `e` from the previous round
- `spawn(key, fn)` → distributed sub-program scoped to a device subset
- Composition yields self-healing distributed algorithms without explicit message passing

## spawn — deep-dive reference

Full documentation: `fcpp_bridge/explanations/SPAWN_explanation.md`
Sections: Quick Reference · §1 Keys · §2 Round/Propagation/Termination · §3 Returned Map · §4 Protocols · §5 FUN_EXPORT · §6 Multiple Parallel Processes

### Critical facts

- Key is **immutable** for the process lifetime; evolving state → `old`/`nbr` inside body or a second spawn
- `bool` status → **ALL** processed keys in returned map; `status` → only `*_output` keys
- Result appears on the node that returned `*_output`, not the injector
- Termination is a **wave** (1 hop/round from T to I); border nodes stop naturally, not via the wave; quiescence ≈ `distance(T,I)` extra rounds
- Re-injection (keeping K in `key_set` every round) blocks quiescence — use `common::option<K>` + `old`
- `message_dispatch.hpp` is **one-way** (fire-and-forget), NOT request-reply
- For request-reply: two spawns preferred (reply key carries snapshot); single spawn works but needs nested exports
- Discarding the return value is safe — `unordered_map` destructor, no heap leak
- **Map type layout** — spawn returns `unordered_map<KeyType, ValueType>` (KEY first, VALUE second); inverting them in a `using` alias is the #1 beginner mistake; compiler error: `conversion from map<K,V,...> to map<V,K,...>`
- **Never call spawn inside a loop** — the CALL counter must advance identically on every node every round; a loop over per-node data desynchronizes the network (see §6)

### Multiple parallel processes — three-phase pattern (§6)

When a node needs to start N independent processes in one round, collect all keys first,
then call spawn once:

```cpp
// Phase A: pure logic, no FCPP primitives
std::vector<K> keys_to_inject;
for (auto const& entry : per_node_data) {
    if (should_start(entry))
        keys_to_inject.push_back(build_key(entry));
}

// Phase B: single spawn — one process per key, all independent
auto results = spawn(CALL, [&](K const& k) { ... }, keys_to_inject);

// Phase C: consume results
for (auto const& [k, v] : results) { ... }
```

- Empty `keys_to_inject` is correct — node still calls spawn and stays synchronized
- Each key → isolated `old`/`nbr` history, separate propagation wave, separate termination
- `FUN_EXPORT` unchanged: `spawn_t<K, B>` covers any number of simultaneous processes
- Use `std::vector<K>` (simplest, no extra operators needed) or `std::set`/`std::unordered_set<K>` to de-duplicate

### Aggregate primitives inside spawn — per-message routing (§7)

`bis_distance` and `sp_collection`/`mp_collection` can be called **inside the spawn
body**. Each key's trace slot is isolated → independent spanning trees per key.
Mandatory when the routing tree must depend on the message (e.g. rooted at sender):

```cpp
spawn(CALL, [&](message const& m) {
    double ds_m    = bis_distance(CALL, node.uid == m.from, 1, 100);
    set_t  below_m = sp_collection(CALL, ds_m, set_t{node.uid}, set_t{}, accumulate);
    bool inpath    = below_m.count(m.to) > 0;
    ...
}, m);
```

**Multi-source Voronoi trap:** `bis_distance` with multiple sources outside spawn
fragments `below` into Voronoi cells. Neither `sp_collection` nor `mp_collection`
outside spawn can route across cell boundaries. Fix: move primitives inside spawn.

**`mp_collection` does NOT fix multi-source routing on its own.** It is a
fault-tolerance upgrade (multi-path vs single-path) applicable *within* the
per-message pattern. Use with `divide = identity` for set accumulators.

Full analysis: `SPAWN_explanation.md §7`, `sp_collection.md §"Multiple sources"`.

### Use-and-consume (ping-pong) — query floods, response routes (§8)

`scattered_database` pattern: requester fires query → floods O(N) to find unknown holder →
holder sends response back → response terminates at requester. Query = search (must flood);
response = route (both endpoints known → O(path length) participants).

**Eternal-internal fix:** without a termination signal, non-holder `internal` nodes stay alive
indefinitely. Use `gossip` inside the query spawn to propagate "found" and self-terminate:

```cpp
bool can_terminate = gossip(CALL, has_data, [](bool x, bool y){ return x || y; });
status s = has_data ? status::terminated_output
         : can_terminate ? status::terminated : status::internal;
```

`gossip` is in `collection.hpp`. Its `nbr<bool>` requires `bool` in `FUN_EXPORT`.

**Termination failure — two modes (critical):**
1. *Holder exists but slow:* `gossip(CALL, has_data, OR)` spreads "found" → `terminated` before wave.
2. *Data absent:* `has_data` always `false`; `gossip` alone never fires → eternal `internal`. Fix: hop-count timeout.

**Absent-data timeout (fully aggregate, no hardcoded size assumptions):**
```cpp
// Outside spawns — diameter upper bound via elected leader
device_t net_leader   = gossip_min(CALL, node.uid);
hops_t   dist_ldr     = abf_hops(CALL, node.uid == net_leader);
hops_t   eccentricity = gossip_max(CALL, dist_ldr);
hops_t   timeout_hops = static_cast<hops_t>(
    static_cast<real_t>(2 * eccentricity) * (1.0f + TIMEOUT_TOLERANCE) + 1.0f);
// Inside query spawn — unconditional
hops_t flood_frontier = gossip_max(CALL, abf_hops(CALL, is_req));
bool   can_terminate  = gossip(CALL, has_data || (flood_frontier > timeout_hops), OR);
```
`diameter ≤ 2 × eccentricity(any node)` (graph theory). `TIMEOUT_TOLERANCE` = named `constexpr real_t`.
Primitives: `gossip_min` / `gossip_max` / `gossip` in `collection.hpp`; `abf_hops` in `spreading.hpp`.
Add `device_t` and `hops_t` to `FUN_EXPORT`.

**Three designs for the response leg:**

- **Solution A (two spawns, recommended):** Response spawn separate from query. Move
  `bis_distance + sp_collection` inside response spawn, rooted at **holder**.
  `inpath = subtree_from_holder.count(requester) > 0`. O(path length) nodes participate.
- **Solution B (matrioska):** Inner response spawn called inside outer query spawn body
  (three-phase pattern). Outer terminates at holder; inner routes back. O(N) outer nodes
  invoke inner spawn machinery every round regardless.
- **Solution C (state machine):** Single spawn, `old` tracks `(found, holder, data)`.
  All primitives called unconditionally; phase-gated results only. O(diameter) extra rounds
  between phases (gossip propagation). Use when single key type is required.

**Global gradient with multiple requesters is broken for the response** — same Voronoi
fragmentation trap as §7. Always move `bis_distance` inside the response spawn.

Full code + comparison table: `SPAWN_explanation.md §8`, `scattered_database_fix_plan.md § Ping-pong`.

## FCPP type and template rules (derived from compiler diagnostics)

### `fcpp::vec<N>` — subscript, not `get<N>`
`fcpp::vec<N>` is array-like; it does NOT implement the tuple-protocol. Use `v[0]`, `v[1]`.
`fcpp::get<N>` works only on `fcpp::tuple<...>`, not `fcpp::vec<N>`.

### `sp_collection` / `mp_collection` accumulator constraint
Both use `if_signature<G, T(T,T)>` = `is_convertible<G, std::function<T(T,T)>>`.
- Lambda params must be **by value** (or at most `const T&`). Non-const `T&` fails.
- A generic `[](auto a, auto b)` lambda fails if the body (e.g. `a | b`) doesn't compile for `T`.
- `std::set` has no `operator|`; set union: `a.insert(b.begin(), b.end()); return a;`

### `gossip` combiner must return `T` — beware `bool | bool → int`

`gossip` exports its combiner's return type via `nbr`. `bool | bool` (bitwise OR) returns
`int` in C++, which is NOT `bool`. If `int` is not in the `export_list`, FCPP fires:
```
error: unsupported type access (add type A to exports type list)
```
**Fix:** use `||` (logical OR) so the combiner returns `bool`:
```cpp
// WRONG:  [](bool x, bool y){ return x | y; }   → int
// CORRECT:[](bool x, bool y){ return x || y; }  → bool
```
Same applies to any combiner that widens the type (e.g. arithmetic on `short` → `int`).

### FCPP node must be non-const
Every FCPP primitive modifies `node.stack_trace`. Any function using FCPP primitives must
take `node_t& node` (non-const). `node_t const& node` causes "discards qualifiers" deep
in FCPP headers.

### `std::result_of` / `std::invoke_result` require argument types
```cpp
using V = std::result_of<F>;         // Wrong — incomplete type
using V = std::invoke_result<F>;     // Wrong — incomplete type
using V = std::invoke_result_t<F, node_t&>;  // Correct (C++17+)
using V = decltype(std::declval<F>()(std::declval<node_t&>()));  // Also correct
```

### Prefer template default `T` + `if_signature` over `auto` + trailing `->`

FCPP coding style for callable-accepting functions — declare `T` as a template default, not via `auto`:
```cpp
template <
    typename node_t,
    typename G,
#if __cplusplus <= 201402L
    typename T = typename std::result_of<G(node_t&)>::type,
#else
    typename T = std::invoke_result_t<G, node_t&>,
#endif
    typename = common::if_signature<G, T(node_t&)>
>
std::map<device_t, T> my_function(node_t& node, G value_fn) { ... }
```
`#if` guard goes in template params only; body and return type stay clean.
