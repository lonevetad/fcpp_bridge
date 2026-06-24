# scattered_database.cpp — Error Analysis & Fix Plan

Build errors captured in `scattered_database_build_errors.log`.

## How to capture build errors

From the `fcpp-exercises/` directory:

```bash
./make.sh gui run -O scattered_database > build_errors.log 2>&1
```

`2>&1` redirects stderr (where the compiler writes diagnostics) into the same file as stdout. Equivalent with `tee` if you also want live terminal output:

```bash
./make.sh gui run -O scattered_database 2>&1 | tee build_errors.log
```

---

## Error catalogue

### E1 — `fcpp::get<N>(fcpp::vec<2>)` — lines 200, 200

**Error:**
```
error: no matching function for call to 'get<1>(s_db_data&)'
error: no matching function for call to 'get<0>(s_db_data&)'
```

**Location:** static `hash(s_db_data)` method inside the `scattered_db_response` hash helper (around line 197).

**Root cause:**  
`s_db_data = fcpp::vec<2>`. `fcpp::vec<N>` is an array-like type; it does **not** implement
`std::tuple_element` / `std::get<N>` — those are tuple-protocol traits. `fcpp::get<N>` works
on `fcpp::tuple` but not on `fcpp::vec`.

**FCPP/C++ rule learned:**  
> `fcpp::vec<N>` uses subscript access (`v[0]`, `v[1]`, …), NOT `get<N>(v)`.
> Only `fcpp::tuple<...>` supports `get<N>`.

**Fix:**
```cpp
// Before (wrong):
return (size_t(fcpp::get<1>(data_to_hash)) << offs) | size_t(fcpp::get<0>(data_to_hash));
// After (correct):
return (size_t(data_to_hash[1]) << offs) | size_t(data_to_hash[0]);
```

---

### E2 — `sp_collection` accumulator lambda by non-const reference — lines 396, 510

**Error:**
```
error: no matching function for call to 'sp_collection(..., <lambda(set_nodes_to_source_t&, set_nodes_to_source_t&)>)'
note: candidate: template<...> T sp_collection(...) [with typename = common::if_signature<G, T(T,T)>]
```

**Root cause:**  
`sp_collection` uses an FCPP SFINAE guard:
```cpp
// collection.hpp:73
template <..., typename G, typename = common::if_signature<G, T(T,T)>>
```
which expands to:
```cpp
typename = std::enable_if_t<std::is_convertible<G, std::function<T(T,T)>>::value>
```

`std::function<T(T,T)>` passes its arguments by value. A lambda that takes parameters
by **non-const reference** (`T& a, T& b`) cannot bind to the rvalue arguments that
`std::function` dispatch produces — so `is_convertible` returns `false` and the template is
SFINAE'd away (zero candidates → "no matching function").

Also: `std::set` has no `operator|`, so a generic `[](auto a, auto b){ return a | b; }` also
fails the `is_convertible` check (the lambda body would not compile for `std::set`).

**FCPP/C++ rule learned:**  
> `sp_collection`'s accumulator must satisfy `if_signature<G, T(T,T)>`.  
> Lambda parameters must be **by value** (or at most `const T&`).  
> Never use `operator|` on `std::set` — use `insert(begin, end)`.  
> Generic `auto` lambdas can fail the `is_convertible` check if the body doesn't compile  
> for the deduced `T`; use explicit types to make the check unambiguous.

**Fix:**
```cpp
// Both occurrences (line 401 and line 510):
// Before (wrong — by ref, no operator| on set):
[](set_nodes_to_source_t& a, set_nodes_to_source_t& b){ a.insert(b.begin(), b.end()); return a; }
// After (correct — by value):
[](set_nodes_to_source_t a, set_nodes_to_source_t b){ a.insert(b.begin(), b.end()); return a; }
```

---

### E3 — `spawn_res_query_map` key/value types swapped — lines 319, 422, 467, 468

**Error:**
```
error: conversion from
  'unordered_map<scattered_db_query, spawn_res_query, ...>'   ← what spawn actually returns
to
  'unordered_map<spawn_res_query, scattered_db_query, ...>'   ← what the alias claims
```

**Root cause:**  
FCPP `spawn(CALL, body, key_set)` returns:
```cpp
std::unordered_map<KEY_TYPE, BODY_RETURN_TYPE>
//                 ^KEY      ^VALUE
```
The spawn at line 422 has:
- Key type: `scattered_db_query` (the type of elements in `key_set`)
- Body return: `tuple<spawn_res_query, status>` → extracted value type = `spawn_res_query`

So spawn returns `unordered_map<scattered_db_query, spawn_res_query>`.

The existing definition was written with key and value **reversed** (the comment
`// map< returned_thing , key , hash_robe >` shows the confusion):
```cpp
// Wrong:
using spawn_res_query_map = std::unordered_map<spawn_res_query, scattered_db_query,
                                               common::hash<spawn_res_query>>;
```

Consequence: the for-loop at lines 466-469 had variable assignments **deliberately inverted**
(with a frustrated comment "LI HO INVETITI, PERCHé NON SI SA !!!! MALEDETTO COMPILATORE")
to compensate — which still didn't compile because the types are not symmetric.

**FCPP rule learned:**  
> `spawn(CALL, body, key_set)` → `std::unordered_map<KeyType, BodyReturnType>`  
> The FIRST template argument of the returned map is always the **KEY** (the type of  
> elements in `key_set`), the SECOND is the **value** (what the body returns, minus status).  
> Inverting them is a very common beginner mistake.

**Fix — line 319:**
```cpp
// Before (wrong):
using spawn_res_query_map = std::unordered_map<spawn_res_query, scattered_db_query,
                                               common::hash<spawn_res_query>>;
// After (correct):
using spawn_res_query_map = std::unordered_map<scattered_db_query, spawn_res_query,
                                               common::hash<scattered_db_query>>;
```

**Fix — lines 466-469 (C++14 branch):**  
With the corrected map, `kv.first = scattered_db_query`, `kv.second = spawn_res_query`.
The variable assignments are now correct as written — remove the compensating comment and
the wrong commented-out swapped version:
```cpp
// Correct after map fix:
scattered_db_query k = kv.first;
spawn_res_query    v = kv.second;
```

---

### E4 + E5 combined — `storage_init.hpp` rewrite (Steps 2)

**Error (propagated):**
```
basics.hpp:214:33: error: passing 'const node_t' as 'this' argument discards qualifiers [-fpermissive]
```

**Root cause:**  
`new_coprime_nbr_data` in `storage_init.hpp` is declared:
```cpp
template <typename node_t, typename F>
auto new_coprime_nbr_data(node_t const& node, trace_t call_point, F value_fn)
```

Every FCPP aggregate primitive (including `for_each_nbr`) internally calls
`node.stack_trace.push(...)` and similar **mutable** operations that update the call-trace
for the current round. Taking `node_t const&` prevents this — the compiler rejects it.

**FCPP rule learned:**  
> Every function that calls an FCPP primitive (even indirectly via CALL) **must** take  
> `node_t& node` (non-const mutable reference). `node_t const& node` is always wrong  
> for functions that use FCPP primitives internally.

**Fix — storage_init.hpp line 44:**
```cpp
// Before (wrong):
auto new_coprime_nbr_data(node_t const& node, trace_t call_point, F value_fn)
// After (correct):
auto new_coprime_nbr_data(node_t& node, trace_t call_point, F value_fn)
```

---

### E5 — `std::result_of<F>` / `std::invoke_result<F>` missing argument types — storage_init.hpp lines 46-54

**Error:**
```
type_traits:1151: error: invalid use of incomplete type 'struct std::result_of<lambda>'
type_traits:1159: error: static assertion failed: template argument must be a complete class
```

**Root cause:**  
`std::result_of<F>` and `std::invoke_result<F>` are **not** complete types on their own.
They are template metafunctions that require the call signature (argument types) to determine
the return type:

```cpp
// Wrong — argument types missing; result_of<F> is an incomplete type:
-> std::map<device_t, std::result_of<F>>       // C++14 branch
-> std::map<device_t, std::invoke_result<F>>   // C++17 branch

// Also wrong inside the body:
using V = std::result_of<F>;
using V = std::invoke_result<F>;
```

Correct forms:
- **C++14**: `typename std::result_of<F(node_t&)>::type`
- **C++17+**: `std::invoke_result_t<F, node_t&>`
- **Any standard via `decltype`**: `decltype(std::declval<F>()(std::declval<node_t&>()))`

The `#if __cplusplus <= 201402L` guards are intentional — the codebase is migrating from
C++14 toward C++26 and must compile correctly under both standards. The guards stay.
The fix is to add the missing call-signature argument type inside each branch:

**Fix — storage_init.hpp line 46 (C++14 trailing return type):**
```cpp
// Before: -> std::map<device_t, std::result_of<F>>
// After:
-> std::map<device_t, typename std::result_of<F(node_t&)>::type>
```

**Fix — storage_init.hpp line 48 (C++17+ trailing return type):**
```cpp
// Before: -> std::map<device_t, std::invoke_result<F>>
// After:
-> std::map<device_t, std::invoke_result_t<F, node_t&>>
```

**Fix — storage_init.hpp line 52 (C++14 body using-decl):**
```cpp
// Before: using V = std::result_of<F>;
// After:
using V = typename std::result_of<F(node_t&)>::type;
```

**Fix — storage_init.hpp line 54 (C++17+ body using-decl):**
```cpp
// Before: using V = std::invoke_result<F>;
// After:
using V = std::invoke_result_t<F, node_t&>;
```

---

## Fix plan (ordered by dependency)

All changes are minimal and surgical — no refactoring beyond what fixes the error.

`get<N>` on vec errors come first (Step 1), followed by `storage_init.hpp` fixes, then
the remaining `scattered_database.cpp` fixes.

| Step | File | Line(s) | Change |
|------|------|---------|--------|
| 1 | `run/scattered_database.cpp` | 200 | `fcpp::get<1>(data_to_hash)` → `data_to_hash[1]`; `fcpp::get<0>(data_to_hash)` → `data_to_hash[0]` |
| 2 | `run/storage_init.hpp` | 43-63 | Rewrite `new_coprime_nbr_data`: remove `auto` + trailing `->`, lift return type into template default `T`, add `if_signature` guard, keep `#if` guards (E4+E5) |
| 3 | `run/scattered_database.cpp` | 319 | Swap key/value in `spawn_res_query_map` alias |
| 4 | `run/scattered_database.cpp` | 401 | Lambda params `T& a, T& b` → `T a, T b` (by value) |
| 5 | `run/scattered_database.cpp` | 510 | Same lambda fix inside the response spawn |
| 6 | `run/scattered_database.cpp` | 466-469 | Clean up the compensating comment; variable assignments are now correct |

**Step 2 detail** — full rewrite of `new_coprime_nbr_data` following FCPP coding style:

```cpp
// BEFORE (broken — auto + trailing ->, const node, incomplete result_of):
template <typename node_t, typename F>
auto new_coprime_nbr_data(node_t const& node, trace_t call_point, F value_fn)
#if __cplusplus <= 201402L
    -> std::map<device_t, std::result_of<F>>
#else
    -> std::map<device_t, std::invoke_result<F>>
#endif
{
#if __cplusplus <= 201402L
    using V = std::result_of<F>;
#else
    using V = std::invoke_result<F>;
#endif
    std::map<device_t, V> result;
    ...
}

// AFTER (correct — explicit return type, if_signature guard, #if only in template params):
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
std::map<device_t, T> new_coprime_nbr_data(node_t& node, trace_t call_point, G value_fn)
{
    std::map<device_t, T> result;
    for_each_nbr(node, call_point, [&](device_t nbr_id) -> common::unit {
        if (is_coprime(nbr_id, node.uid))
            result.emplace(nbr_id, value_fn(node));
        return {};
    });
    return result;
}
```

Fixes both E4 (`const&` → `&`) and E5 (`result_of<F>` → correct signatures) in one rewrite.
`#if` guard appears exactly once (in template params); body has no conditionals.
`if_signature<G, T(node_t&)>` matches FCPP style for callables accepting a node reference.

### `get<N>` usage audit

All `get<N>` calls in `scattered_database.cpp` (excluding commented-out lines):

| Line | Call | Argument type | Verdict |
|------|------|---------------|---------|
| 200 (×2) | `fcpp::get<0>(data_to_hash)` / `fcpp::get<1>(data_to_hash)` | `s_db_data = fcpp::vec<2>` | **ERROR** — fix is Step 1 |
| 481 | `get<1>(v)` | `v: tuple<scattered_db_query, bool, s_db_data>` | Correct — `get` is on the tuple |
| 482 | `get<2>(v)` | same tuple `v` | Correct — element is `vec<2>` but `get` targets the tuple |

Steps 2, 3a, 3b must all be applied to `storage_init.hpp` before the cascade errors reduce.
Steps are otherwise independent and can be applied in any order within the same file.

---

## FCPP rules distilled from these errors

These rules are not in any FCPP tutorial; they were derived from compiler diagnostics:

1. **`fcpp::vec<N>` uses `[i]`, not `get<N>(v)`** — `get<N>` is for `fcpp::tuple` only.
2. **`sp_collection`/`mp_collection` accumulator must be `T(T,T)` compatible** — the SFINAE guard `if_signature<G, T(T,T)>` means the lambda must be convertible to `std::function<T(T,T)>`. Non-const ref parameters break this.
3. **`spawn` returns `map<KEY, VALUE>`** — KEY = key_set element type, VALUE = body return (minus status). Inverting them is the #1 beginner mistake.
4. **Every function using FCPP primitives must take `node_t&` (non-const)** — FCPP's trace stack is mutable. `const` qualification propagates and breaks all nested primitive calls.
5. **`std::result_of<F>` / `std::invoke_result<F>` require argument types** — `result_of<F(ArgType)>` / `invoke_result_t<F, ArgType>`. Without them the template specialization is incomplete and causes cascading `static_assert` failures.
6. **Prefer template default `T` + `if_signature` over `auto` with trailing `->` for callable-accepting functions** — FCPP style: declare `typename T = invoke_result_t<G, ArgType>` and `typename = common::if_signature<G, T(ArgType)>` as template parameters. The explicit return type `std::map<device_t, T>` replaces `auto`. When multi-standard `#if` guards are needed (C++14 vs C++17+), place the single guard inside the template parameter list — the function body and return type remain clean and guard-free.

---

## Ping-pong communication design

The query-response flow in `scattered_database.cpp` is a **use-and-consume (ping-pong)**
pattern: a requester fires a query process, the process floods the network until it reaches
the data holder, the holder fires a response back toward the requester, and both processes
terminate cleanly. No long-lived channels; each query–response pair lives for the minimum
necessary number of rounds.

---

### `v1` analysis — what apparently works and what is actually broken

`scattered_database_v1.cpp` (with the `&&` syntax fix at line 472 applied) compiles and
produces visible behaviour in the simulator, but carries structural problems that only
manifest with multiple concurrent requesters:

**What works:**
- Query spawn correctly floods the network and returns `terminated_output` at the holder.
- Response spawn delivers data back to the requester (floods, but terminates there).
- `gossip` in the current refactored file (`scattered_database.cpp`) correctly propagates
  the "holder found" signal across all active nodes so non-holders can self-terminate
  (`status::terminated`) instead of idling as `internal` until message retention expires.

**What is latently broken in v1 (Voronoi fragmentation):**

`abf_distance(CALL, is_enabled_to_request)` with two or more requesters produces a
Voronoi-partitioned gradient: each node's distance is measured to its *nearest* requester,
not to a fixed single root. `sp_collection` then builds a separate spanning tree inside
each Voronoi cell. `nodes_to_source` at any node only contains UIDs from its own cell.

In v1 the response spawn computes `in_path` from `nodes_to_source` but then **ignores it**:

```cpp
status s = is_requester ? status::terminated_output
        : status::internal;  // in_path ? status::internal : status::border;  ← ignored
```

The bug is hidden because the response floods everything (`status::internal` for all
non-requesters). With a single requester (v1 uses only node 7 and node 50) and a fully
connected network, flooding reaches both. The Voronoi fragmentation never causes a visible
failure because the flood bypasses it.

**What is inefficient in v1:**
- **Response spawn floods O(N) nodes** per response, when the actual path from holder to
  requester involves O(diameter) nodes. With R concurrent responses: O(N × R) active nodes.
- **Query spawn may idle as `internal` indefinitely** on non-holder nodes if the holder's
  `terminated_output` wave is too slow. The `gossip`-based `can_terminate` in the refactored
  file addresses this (active self-termination), but v1 relies on message-retention expiry.

---

### Prerequisite fixes (apply to all three solutions)

Fix the build errors from the catalogue above before choosing a design:

| Step | Location | Change |
|------|----------|--------|
| E1 | `scattered_db_response::hash` | `data_to_hash[1]` / `data_to_hash[0]` (not `fcpp::get<N>`) |
| E2 | all `sp_collection` lambdas | Params by value: `[](T a, T b){...}` (not `T& a, T& b`) |
| E3 | `spawn_res_query_map` alias | Key first: `unordered_map<scattered_db_query, spawn_res_query, ...>` |
| E4 | `storage_init.hpp:43` | `node_t& node` (non-const) |
| E5 | `storage_init.hpp:46,48,52,54` | Complete `result_of` / `invoke_result` call-signature |
| E6 | line 472 (v1) / current file | Complete `can_fire_request_data` condition (add `!= node.uid && !has_requested_data`) |

The `gossip` call in the current file is **valid** — `gossip` is defined in
`collection.hpp` and spreads a value 1 hop/round via `nbr + fold_hood`. It requires
`bool` in `FUN_EXPORT` (which is already present). Keep it for faster self-termination
of the query spawn. The `bool` in `FUN_EXPORT` is specifically for `gossip`'s `nbr<bool>`.

---

### Solution A — Two spawns, fixed (minimal change from v1)

Keep the two-spawn architecture. Remove the globally-computed `abf_distance + sp_collection`
(they produce a Voronoi-fragmented gradient and are not needed). Move `bis_distance +
sp_collection` *inside the response spawn*, rooted at the **holder**. The query spawn
continues to flood (correct — the holder location is unknown at query time).

**Why the query must still flood:** There is no a-priori knowledge of where the holder is.
Every node potentially holds the requested key (the database is *scattered*). A flood is
the only search strategy that guarantees finding the holder regardless of topology.

**Why the response can be routed:** Both endpoints are known — `resp.holder` and
`resp.requester` are fields in the response key. Build a per-spawn spanning tree rooted at
the holder; the requester is in the holder's subtree along the path.

#### Termination when data is absent — timeout via hop-count frontier

`gossip` alone cannot terminate the query spawn when no holder exists: `has_data` is
always `false`, so `can_terminate` never becomes `true`. The process runs forever.

**Fix:** track the *flood frontier* (how far the spawn has spread in hops from the
requester) inside the spawn body. When the frontier exceeds the estimated network diameter
(plus a tolerance), the entire network has been searched without finding the holder →
declare data absent → all nodes return `status::terminated`.

The diameter is computed fully aggregate, with no hardcoded assumptions:

1. Elect the minimum-UID node as reference: `gossip_min(CALL, node.uid)`.
2. Compute hop distance from that node: `abf_hops(CALL, node.uid == net_leader)`.
3. Gossip the maximum: `gossip_max(CALL, dist_ldr)` = eccentricity of the leader.
4. `diameter ≤ 2 × eccentricity(any node)` (graph theory: diameter ≤ 2 × radius ≤
   2 × eccentricity). Apply tolerance: `timeout = 2 × eccentricity × (1 + tolerance)`.

Inside the query spawn, track the frontier with `abf_hops + gossip_max`. Both must be
called **unconditionally** (before any `if` branch) to keep the CALL trace synchronized.

`TIMEOUT_TOLERANCE` is a named `constexpr` (not a magic number):
```cpp
constexpr real_t TIMEOUT_TOLERANCE = 0.25;  // 25% headroom above diameter estimate
```

```cpp
// REMOVE: global abf_distance + sp_collection (lines 447-464 in v1)
// Reason: Voronoi-fragmented with multiple requesters; not needed for correct routing.

// ── Network diameter estimate (outside spawns, captured in query-spawn lambda) ──────
// gossip_min elects the minimum UID as a globally-consistent reference node.
// abf_hops gives each node its hop distance from that reference.
// gossip_max spreads the maximum → eccentricity of the reference node.
// 2 × eccentricity(v) ≥ diameter for any v (graph-theoretic upper bound).
// +1 guards against convergence lag on the first few rounds.
device_t net_leader   = gossip_min(CALL, node.uid);
hops_t   dist_ldr     = abf_hops(CALL, node.uid == net_leader);
hops_t   eccentricity = gossip_max(CALL, dist_ldr);
hops_t   timeout_hops = static_cast<hops_t>(
    static_cast<real_t>(2 * eccentricity) * (1.0f + TIMEOUT_TOLERANCE) + 1.0f
);

// Query spawn — flood (holder unknown); gossip + timeout for self-termination
spawn_res_query_map query_res = spawn(CALL, [&](scattered_db_query const& message_query) {
    bool is_req   = (node.uid == message_query.requester);
    bool has_data = has_requested_data(CALL, message_query.key);
    if (is_req)
        node.storage(tags::node_last_requested_data{}) = message_query.to_string();

    // ── Flood frontier (unconditional) ──────────────────────────────────────────────
    // abf_hops measures hop distance from the requester within the active spawn nodes.
    // gossip_max spreads the maximum → how far the flood has reached.
    // When frontier > timeout_hops the whole network has been covered: data absent.
    hops_t hops_from_req  = abf_hops(CALL, is_req);
    hops_t flood_frontier = gossip_max(CALL, hops_from_req);
    bool   timed_out      = (flood_frontier > timeout_hops);

    // Unified termination signal: holder found OR data declared absent
    bool can_terminate = gossip(CALL, has_data || timed_out,
                                [](bool x, bool y){ return x || y; });
    status s = has_data        ? status::terminated_output  // holder found
             : can_terminate   ? status::terminated         // data absent (timeout) or
             :                   status::internal;          //   termination wave passing
    return make_tuple(
        static_cast<spawn_res_query>(make_tuple(
            message_query, has_data,
            has_data ? get_data(CALL, message_query.key)
                     : static_cast<s_db_data>(node.position())
        )), s
    );
}, query);

// Phase A — collect responses_to_inject (unchanged from v1)

// Response spawn — FIXED: routed from holder to requester
spawn_res_response_map response_res = spawn(CALL, [&](scattered_db_response const& resp) {
    bool is_requester = (node.uid == resp.requester);
    bool is_holder    = (node.uid == resp.holder);
    // Per-spawn tree rooted at holder — no Voronoi fragmentation
    real_t dist_from_holder = bis_distance(CALL, is_holder, 1, communication_range);
    set_nodes_to_source_t subtree_from_holder = sp_collection(CALL,
        dist_from_holder,
        set_nodes_to_source_t{node.uid}, set_nodes_to_source_t{},
        [](set_nodes_to_source_t a, set_nodes_to_source_t b){
            a.insert(b.begin(), b.end()); return a;
        }
    );
    // requester in subtree ↔ this node is on the holder→requester path
    bool inpath = subtree_from_holder.count(resp.requester) > 0;
    status s = is_requester ? status::terminated_output
             : inpath       ? status::internal : status::border;
    if (is_requester) {
        node.storage(tags::node_data_requested{}) = false;
        node.storage(tags::node_color{}) = color(BLACK);
    }
    return make_tuple(resp, s);
}, responses_to_inject);
```

**Why `subtree_from_holder.count(resp.requester) > 0` routes correctly:**  
On path requester→A→B→holder: `dist_from_holder[holder]=0`, `dist_from_holder[B]=1`,
`dist_from_holder[A]=2`, `dist_from_holder[requester]=3`. B's subtree (toward holder)
contains both A and the requester → `inpath=true` for B. Off-path node X's subtree never
contains the requester → `border`. Only O(path length) nodes participate in the response.

**Why `flood_frontier > timeout_hops` is the right termination criterion:**  
`hops_from_req` at a node = its hop distance from the requester, measured within the
active spawn population. `gossip_max` propagates the global maximum back to everyone.
When the frontier exceeds `2 × eccentricity × (1 + tolerance)`, every reachable node has
been visited (eccentricity is at most the diameter; 2× is a proven upper bound).
The `gossip` spreads `timed_out = true` in one more pass, causing all remaining `internal`
nodes to return `terminated`.

**Convergence note:** The diameter estimate converges in O(diameter) rounds after startup
(gossip_min + abf_hops + gossip_max all need time to spread). A query that fires on the
very first round may have a slightly underestimated `timeout_hops`. The `+ 1` in the
timeout formula adds a one-hop safety margin; for critical deployments, a larger additive
offset (e.g., `+ 3`) can be used.

**Updated `FUN_EXPORT` for Solution A:**
```cpp
FUN_EXPORT execute_scattered_db_query_t = export_list<
    compute_key_query_t,
    device_t,                                          // gossip_min<device_t> outside spawns
    hops_t,                                            // abf_hops + gossip_max (outside AND inside query spawn)
    bool,                                              // gossip<bool> inside query spawn
    uint,
    bis_distance_t,                                    // inside response spawn
    sp_collection_t<real_t, set_nodes_to_source_t>,   // inside response spawn
    spawn_t<scattered_db_query, status>,
    spawn_t<spawn_res_response, status>
>;
```
`abf_distance_t`, standalone `real_t` (unduplicated), and standalone
`set_nodes_to_source_t` are removed (no global gradient computation). `device_t` is re-added
for `gossip_min`. `hops_t` covers `abf_hops_t`, `gossip_max_t<hops_t>` (both outside
and inside the query spawn). `bis_distance_t` and `sp_collection_t` remain for the response
spawn. The three new outer primitives (`gossip_min`, `abf_hops`, `gossip_max`) must appear
before any `spawn` call in `execute_scattered_db_query` to keep the CALL order consistent.

---

### Solution B — Matrioska (inner spawn inside outer spawn)

The outer query spawn floods the network searching for the holder. When the holder is found,
it injects a key into an **inner response spawn** (called inside the outer spawn body, using
the three-phase pattern). The inner spawn routes the response from holder back to requester.
The outer spawn terminates at the holder (`status::terminated`, no output); the inner spawn
terminates at the requester (`status::terminated_output`).

```cpp
spawn_res_query_map query_res = spawn(CALL, [&](scattered_db_query const& message_query) {
    bool has_data   = has_requested_data(CALL, message_query.key);
    bool is_req     = (node.uid == message_query.requester);
    bool can_term   = gossip(CALL, has_data, [](bool x, bool y){ return x || y; });

    // INNER three-phase: every outer-active node calls inner spawn once per round
    common::option<scattered_db_response> inner_key;
    if (has_data) {
        inner_key.emplace(
            message_query.key, get_data(CALL, message_query.key),
            message_query.requester, node.uid, 0u, node.current_time()
        );
    }
    auto inner_res = spawn(CALL, [&](scattered_db_response const& resp) {
        bool is_r = (node.uid == resp.requester);
        bool is_h = (node.uid == resp.holder);
        real_t d  = bis_distance(CALL, is_h, 1, communication_range);
        set_nodes_to_source_t sub = sp_collection(CALL, d,
            set_nodes_to_source_t{node.uid}, set_nodes_to_source_t{},
            [](set_nodes_to_source_t a, set_nodes_to_source_t b){
                a.insert(b.begin(), b.end()); return a;
            });
        bool inpath = sub.count(resp.requester) > 0;
        status s_in = is_r     ? status::terminated_output
                    : inpath   ? status::internal : status::border;
        return make_tuple(resp, s_in);
    }, inner_key);

    // Consume inner result at requester
    if (is_req) {
        for (auto const& [k_r, v_r] : inner_res) {
            node.storage(tags::node_data_got{})[k_r.to_string()] = v_r.data;
            node.storage(tags::node_data_requested{}) = false;
        }
    }

    // Outer status: terminate at holder (no output); active self-terminate once found
    status s_out = has_data   ? status::terminated
                 : can_term   ? status::terminated
                 :              status::internal;
    return make_tuple(
        static_cast<spawn_res_query>(make_tuple(
            message_query, has_data,
            has_data ? get_data(CALL, message_query.key)
                     : static_cast<s_db_data>(node.position())
        )), s_out
    );
}, query);
// No second top-level spawn needed — inner spawn handles delivery
```

**`FUN_EXPORT` for Solution B:**
```cpp
FUN_EXPORT execute_scattered_db_query_t = export_list<
    compute_key_query_t,
    bool,                                              // gossip
    uint,
    bis_distance_t,                                    // inside inner spawn
    sp_collection_t<real_t, set_nodes_to_source_t>,   // inside inner spawn
    spawn_t<scattered_db_query, status>,               // outer spawn
    spawn_t<scattered_db_response, status>             // inner spawn (nested inside outer)
>;
```

**Trade-off vs Solution A:**  
Every node holding the outer query process (O(N) during the search phase) calls the inner
spawn every round. Most rounds the inner key set is empty, but the CALL invocation still
occurs on all O(N) active outer nodes. Solution A's response spawn only touches O(N) nodes
on the round the holder is found, then O(path length) nodes each subsequent round.

---

### Solution C — State machine (recycle first spawn)

One spawn body manages both phases using `old` inside the spawn body to persist per-process
state. Phase 1 (search): all nodes `internal`, flooding the network. When the holder is
detected, its UID is stored in the per-process state. Phase 2 (response): all nodes switch
routing — `bis_distance + sp_collection` now rooted at the stored holder UID.

**Critical invariant:** All FCPP primitives (`old`, `bis_distance`, `sp_collection`) must be
called **unconditionally** in the same order every round, even when their results are only
used in one phase. Move the conditional on their results, not the calls themselves:

```cpp
using query_state_t = tuple<bool, device_t, s_db_data>;
// fields: <found, holder_uid, data>

spawn(CALL, [&](scattered_db_query const& message_query) {
    bool has_data = has_requested_data(CALL, message_query.key);
    bool is_req   = (node.uid == message_query.requester);

    // Phase state: persisted per-process per-node via old
    query_state_t state = old(CALL,
        static_cast<query_state_t>(make_tuple(false, (device_t)0, s_db_data{})),
        [&](query_state_t const& prev) -> query_state_t {
            if (get<0>(prev)) return prev;   // already found, keep
            if (has_data) return make_tuple(true, node.uid, get_data(CALL, message_query.key));
            return prev;
        }
    );
    bool     found  = get<0>(state);
    device_t holder = get<1>(state);
    s_db_data data  = get<2>(state);

    // UNCONDITIONAL primitive calls — results used only in phase 2
    bool is_holder  = found && (node.uid == holder);
    real_t d        = bis_distance(CALL, is_holder, 1, communication_range);
    set_nodes_to_source_t sub = sp_collection(CALL, d,
        set_nodes_to_source_t{node.uid}, set_nodes_to_source_t{},
        [](set_nodes_to_source_t a, set_nodes_to_source_t b){
            a.insert(b.begin(), b.end()); return a;
        }
    );
    bool gossip_found = gossip(CALL, found, [](bool x, bool y){ return x || y; });

    if (!gossip_found) {
        // Phase 1: search — flood
        return make_tuple(
            static_cast<spawn_res_query>(make_tuple(message_query, false, s_db_data{})),
            status::internal
        );
    }

    // Phase 2: response — route from holder to requester
    bool inpath = sub.count(message_query.requester) > 0;
    status s = is_req  ? status::terminated_output
             : inpath  ? status::internal : status::border;
    if (is_req) {
        node.storage(tags::node_data_got{})[message_query.to_string()] = data;
        node.storage(tags::node_data_requested{}) = false;
    }
    return make_tuple(
        static_cast<spawn_res_query>(make_tuple(message_query, found, data)),
        s
    );
}, query);
```

**`FUN_EXPORT` for Solution C:**
```cpp
FUN_EXPORT execute_scattered_db_query_t = export_list<
    compute_key_query_t,
    query_state_t,                                     // old<query_state_t> inside spawn
    bool,                                              // gossip's nbr<bool>
    uint,
    bis_distance_t,
    sp_collection_t<real_t, set_nodes_to_source_t>,
    spawn_t<scattered_db_query, status>                // single spawn
>;
```

**Trade-off vs Solutions A/B:**  
After the holder is found, `gossip_found` must propagate to ALL active nodes (~O(N)) before
they switch to phase 2. This takes O(diameter) extra rounds. During that window, phase 1
nodes still return `internal` (flooding). Solution A/B start the response in the same round
the holder fires. Solution C also carries `(found, holder, data)` state on every active node.
Use it when a single key type is a strict requirement (e.g., exactly-once delivery tracking).

---

### Recommendation

**Use Solution A** for `scattered_database.cpp`. It is the smallest departure from the
working v1 structure, correctly handles any number of simultaneous requesters (no Voronoi
problem), and routes the response efficiently (O(path length) participating nodes). The
query flood is unavoidable; only the response benefits from routing, and Solution A achieves
that with a clean two-spawn separation.

**Solution B** (matrioska) is the idiomatic aggregate choice when the response must be
logically contained within the query process (e.g., for exactly-once semantics on the key).
The cost is that all O(N) outer-active nodes invoke the inner spawn machinery every round.

**Solution C** (state machine) is theoretically the most elegant (one key, one process) but
introduces an O(diameter)-round phase-switch delay and higher per-process memory footprint.

---

## Implementation status — Solution A applied (2026-06-11)

`scattered_database.cpp` has been updated to implement Solution A. All changes are in
`execute_scattered_db_query`:

| Change | Location | Description |
|--------|----------|-------------|
| `TIMEOUT_TOLERANCE` constant | namespace scope | `constexpr real_t TIMEOUT_TOLERANCE = 0.25` |
| Diameter estimation | before query spawn | `gossip_min + abf_hops + gossip_max` → `timeout_hops` |
| Query spawn body | inside spawn lambda | `abf_hops + gossip_max` flood frontier; `gossip(has_data \|\| timed_out)` |
| Response spawn body | inside spawn lambda | `bis_distance(is_holder)` + `sp_collection` → `inpath`; proper `border` status |
| `FUN_EXPORT` | after function | Removed `abf_distance_t`, `set_nodes_to_source_t`, `real_t` (standalone); added `hops_t` |

Build command (from `fcpp-exercises/`):
```bash
./make.sh gui run -O scattered_database
```

