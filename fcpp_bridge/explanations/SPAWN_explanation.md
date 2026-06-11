# `spawn` — Reference Manual

## Quick Reference

**C++ signature** (defined in `fcpp/src/lib/coordination/basics.hpp`):

```cpp
spawn(node, call_point, process, key_set, xs...)
  -> std::unordered_map<K, R>
```

- `key_set` — a set of values of type `K` (the "keys")
- `process` — a callable `(K, xs...) -> tuple<R, B>` where `R` is the result and `B` is a status
- `xs...` — extra arguments forwarded to every `process` call

**Status codes:**

| Code | Propagation | In returned map |
|---|---|---|
| `border` | Not propagated | `bool`/`field<bool>` only |
| `internal` | Propagated to neighbours | `bool`/`field<bool>` only |
| `terminated` | Sends kill signal | `bool`/`field<bool>` only |
| `border_output` | Not propagated | ✓ |
| `internal_output` / `output` | Propagated | ✓ |
| `terminated_output` | Sends kill signal | ✓ |

With `bool`/`field<bool>`: `true` = `internal_output`, `false` = `border_output`.

**FUN_EXPORT:**

```cpp
using my_spawn_t = export_list<spawn_t<K, B>, /* exports of process body */>;
```

**Critical facts:**
- Key is **immutable** for the process lifetime; evolving state → `old`/`nbr` inside the body, or a second spawn
- `bool` status → **ALL** processed keys in returned map; `status` → only `*_output` keys
- Result appears on the node that returned `*_output`, **not** necessarily the injector
- Termination is a **wave** (1 hop/round from T toward I); border nodes stop naturally, not via the wave
- `message_dispatch.hpp` is **one-way only** — NOT a request-reply model
- Discarding the return value is safe — `unordered_map` destructor, no heap leak

---

## 1. Process Identity — Keys

### What a key is

A key is the **identity of one independent aggregate process instance**. `spawn` lets many logically distinct sub-computations run concurrently on the same network, each identified by its key. You can think of keys the same way you would think of process IDs in an OS: each key owns its own trace slot, so the `old`/`nbr` state inside `process` is completely isolated per key — different keys never read each other's exports.

This isolation is enforced at the trace level:

```cpp
internal::trace_key trace_process(node.stack_trace, common::hash_to<trace_t>(k));
```

Each key `k` pushes a distinct hash onto the trace stack before running `process(k, ...)`, so the FCPP runtime treats each `(call_point, key)` pair as a separate history.

### Key type requirements

`spawn` stores its active-key bookkeeping in an `std::unordered_set<K>` (or `std::unordered_map<K, status>`), so a valid key type `K` must provide:

1. **Equality** — `operator==`
2. **Hash** — `std::hash<K>` specialisation (or `fcpp::common::hash<K>`)
3. **Serialisation** — a `serialize(S&)` method (both const and non-const) so the key set can be exchanged in FCPP messages

### Injecting keys via `common::option`

A node originates a new process instance only when it has something to inject. The idiomatic pattern is `common::option<K>` (FCPP's optional), which is empty most rounds and filled only when the node decides to start a process:

```cpp
common::option<K> key;
if (condition_to_originate)
    key.emplace(/* construct key */);

spawn(CALL, [&](K const& k) { ... }, key);
```

`common::option<K>` satisfies the `key_set` requirement because FCPP treats it as a 0-or-1 element set: when empty no new process is started; when filled exactly one key is injected this round.

---

### Style 1 — `device_t` key (`es_01.hpp`)

The simplest case: the key **is** the originating node's UID.

```cpp
common::option<device_t> key;
if (isSpecial)
    key.emplace(node.uid);

std::unordered_map<device_t, unit> res = spawn(CALL,
    [&](device_t const& k) {
        status s = abf_distance(CALL, node.uid == k) < MAX_RANGE
                   ? status::internal_output : status::external;
        return make_tuple(unit{}, s);
    }, key);

// FUN_EXPORT: spawn_t<device_t, status>
```

---

### Style 2 — Custom struct key (`message_dispatch.hpp`)

When the key must carry richer identity, define a struct with the three required pieces:

```cpp
struct message {
    device_t from, to;
    times_t  time;
    bool operator==(message const& m) const { return from==m.from && to==m.to && time==m.time; }
    size_t hash() const {
        constexpr size_t offs = sizeof(size_t)*CHAR_BIT/3;
        return (size_t(time) << (2*offs)) | (size_t(from) << offs) | size_t(to);
    }
    template <typename S> S& serialize(S& s)       { return s & from & to & time; }
    template <typename S> S& serialize(S& s) const { return s << from << to << time; }
};
namespace std { template <> struct hash<message> {
    size_t operator()(message const& m) const { return m.hash(); }
}; }
```

```cpp
map_t r = spawn(CALL, [&](message const& m) {
    bool inpath = below.count(m.from) + below.count(m.to) > 0;
    status s = node.uid == m.to ? status::terminated_output :
               inpath            ? status::internal          : status::border;
    return make_tuple(node.current_time(), s);
}, current_message);   // common::option<message>
// FUN_EXPORT: spawn_t<message, status>
```

The key uniquely identifies "the message from `from` to `to` created at `time`", so separate concurrent deliveries never collide.

---

### Style 3 — `fcpp::tuple` key (compound identity, zero boilerplate)

`fcpp::tuple<...>` gives compound keys immediately — no struct, no `std::hash` specialisation needed:

```cpp
using query_key_t = fcpp::tuple<device_t, device_t>;  // (requester, target)

common::option<query_key_t> key;
if (wants_to_query)
    key.emplace(make_tuple(node.uid, target_node));

auto results = spawn(CALL, [&](query_key_t const& k) {
    auto [requester, target] = k;
    bool found = (node.uid == target);
    status s = found ? status::terminated_output :
               on_path_to(requester, target) ? status::internal : status::border;
    return make_tuple(node.position(), s);
}, key);
// FUN_EXPORT: spawn_t<query_key_t, status>
```

---

### When to use each style

| Style | Use when |
|---|---|
| `device_t` | one process per originating node; identity is just the UID |
| Custom struct | key has several semantically distinct fields; named members improve readability |
| `fcpp::tuple<...>` | compound identity, no need for named fields; fastest to write |

---

### Minimum required interface for a custom key type

```cpp
bool operator==(K const&) const;
size_t hash() const;
template <typename S> S& serialize(S& s);
template <typename S> S& serialize(S& s) const;
// plus: namespace std { template<> struct hash<K> { size_t operator()(K const&) const; }; }
```

---

## 2. Round Execution, Propagation, and Termination

### Step-by-step round

```
Round N on a given node:

1. Collect keys
   own key_set  ∪  keys propagated by all neighbours
         ↓
   full set "ky" of keys this node will run

2. For each key k in ky:
       (result, status) = process(k, xs...)

3. Based on status:
   ┌──────────────────────────────────────────────────────┐
   │ internal        → propagate k to neighbours          │
   │ border          → do NOT propagate k                 │
   │ terminated      → send termination signal, then stop │
   │ *_output suffix → also include result in return map  │
   └──────────────────────────────────────────────────────┘

4. Export propagated keys to neighbours via nbr_context

5. Return unordered_map<K, R>  (only output-flagged keys)
```

### The three status flavours

| `B` type      | Meaning                                                     | Typical use               |
| ------------- | ----------------------------------------------------------- | ------------------------- |
| `bool`        | `true` = `internal_output`, `false` = `border_output`       | simple yes/no propagation |
| `field<bool>` | per-neighbour propagation flag                              | asymmetric spreading      |
| `status`      | full control: `internal`, `border`, `terminated`, `+output` | fine-grained lifecycle    |

```
terminated        — process ending; propagate termination signal to neighbours
border            — part of the process, but do not expand to new neighbours
internal          — part of the process; propagate to neighbours
*_output suffix   — same as above, but also include this node's result in the return map
output            — synonym for internal_output
```

### Wave propagation — mental model

Imagine a query propagating through the network, initiated by one or more nodes:

```cpp
spawn(CALL,
    [&](device_t initiator, ...) -> tuple<double, status> {
        double my_result = ...;
        bool still_alive = ...;
        return {my_result, still_alive ? status::internal_output : status::terminated};
    },
    my_initiated_queries
);
```

- Node 3 adds key `7` → starts a sub-computation with ID 7.
- Neighbours see key `7` next round and also run `process(7, ...)`.
- The wave spreads as long as nodes return `internal`; stops when they return `terminated`.
- Results appear in the returned map only on nodes that returned an `_output` status.

Each key is a completely independent wave with its own `old`/`nbr` history.

### Termination propagation in depth

No, the process **does not stop instantly** when one node returns `terminated`. Termination is a wave that propagates hop-by-hop from the terminating node back toward the injector. Internal nodes continue running for approximately `distance_to_terminator` additional rounds; border nodes stop naturally when their internal neighbours stop propagating the key — the `terminated` signal never enters the border fringe.

#### The mechanics (status overload)

The `status` overload splits neighbour exports into two sets each round:

```cpp
for (auto const& m : fcpp::details::get_vals(ctx.nbr({})))
    for (auto const& k : m) {
        if (k.second == status::terminated)
            kn.insert(k.first);   // "kill" set
        else
            ky.insert(k.first);   // "run" set
    }
```

The run loop:

```cpp
for (K const& k : ky)
    if (kn.count(k) == 0) {
        // run the process body normally
    } else {
        km.emplace(k, status::terminated);  // skip body, forward termination
    }
```

Two rules follow directly:

1. **A node skips the body and forwards `terminated` only when K is in BOTH `ky` and `kn`.**
   If K is only in `kn` (no non-terminated neighbour, not self-injecting), the node drops K silently.

2. **Border nodes never forward `terminated`.**
   Border exports are empty for K; neighbours beyond the border never have K in their `ky` from that direction.

#### Round-by-round trace for `I → A → B → T`, with D (border) off B

| Round | T | B | A | I | D (border) |
|---|---|---|---|---|---|
| R   | **terminates** → `{K:terminated}` | runs → `{K:internal}` | runs → `{K:internal}` | runs → `{K:internal}` | runs → no export |
| R+1 | sees B's `internal` → runs → `{K:terminated}` | sees T's `terminated`+A's `internal` → **skips** → `{K:terminated}` | sees B's `internal` → runs | sees A's `internal` → runs | sees B's `internal` → runs → no export |
| R+2 | sees B's `terminated` → ky={} → **stops** | skips → `{K:terminated}` | sees B's `terminated`+I's `internal` → **skips** → `{K:terminated}` | sees A's `internal` → runs | sees B's `terminated` → ky={} → **stops** |
| R+3 | — | ky={} → stops | — | sees A's `terminated` → **skips** | — |

Full quiescence at round R + `distance(T, I)` = R + 3.

#### Key observations

**Internal nodes run for `distance_to_T` additional rounds.**
The wave travels at 1 hop/round; a node at distance *d* from T runs *d* more rounds after T terminates.

**T itself continues running until its neighbours stop.**
T stops ~1 round after its nearest `internal` neighbour stops (that neighbour then sends `terminated` back).

**Border nodes stop when their `ky` empties, not when `terminated` arrives.**
D stopped because B stopped exporting K, not because it received a `terminated` signal. The wave does not cross the border fringe.

**Total extra rounds ≤ network diameter.**

#### `bool`/`field<bool>` overloads — no explicit termination

```cpp
tie(rm[k], b) = process(k, xs...);
if (b) km.insert(k);   // b = false → k not propagated; no terminated signal
```

The wave contracts naturally; process fades out hop by hop over ~diameter rounds.

#### Practical implications

- **Stale output rounds**: result map may contain entries on intermediate nodes for a few rounds after `terminated_output`. Accumulation logic (`old` outside `spawn`) must tolerate trailing results.
- **Re-injection prevents termination**: keeping K in `key_set` every round prevents quiescence. Use `common::option<K>` + `old` guard to inject once only.
- **Termination is per-key**: `terminated` for K1 has no effect on K2.

---

## 3. Working with the Returned Map

`spawn` returns `std::unordered_map<K, R, common::hash<K>>`.

### Map type layout — common mistake

```cpp
using result_map = std::unordered_map<K, R, common::hash<K>>;
//                                    ^KEY  ^VALUE (body return, minus status)
```

**K** = key-set element type. **R** = body return value (first element of `tuple<R, B>`).

> **Pitfall:** inverting K and R in the type alias is the most common beginner mistake.
> Compiler error: `conversion from unordered_map<K,R,...> to unordered_map<R,K,...>`.

```cpp
// Wrong:
using my_map = std::unordered_map<SpawnReturnType, KeyType, common::hash<SpawnReturnType>>;
// Correct:
using my_map = std::unordered_map<KeyType, SpawnReturnType, common::hash<KeyType>>;
```

---

### What ends up in the map — critical difference by status type

| Status type `B` | Keys in the returned map |
|---|---|
| `bool` | **Every key that ran** — regardless of `true`/`false`; the bool only controls propagation |
| `field<bool>` | Same as `bool` |
| `status` | **Only keys that returned `*_output`** |

With `bool`: `tie(rm[k], b) = process(k, xs...);` — `rm[k]` always written.
With `status`: `if ((char)s >= 4) rm.emplace(k, std::move(r));` — explicit guard.

### Who sees the result?

The result appears on the node that returned `*_output` — **not** necessarily the injector.

- `es_01.hpp` (`bool`): the originating node sees every key that ran on it.
- `message_dispatch.hpp` (`status`): only the **destination** sees the entry (it returned `terminated_output`); the sender sees nothing.

### Typical use patterns

#### 1. Presence check

```cpp
if (results.count(target_key) > 0) { /* this node is an output node */ }
```

#### 2. Iterate / random-access

```cpp
for (auto const& [k, v] : results) { node.storage(tags::received{}) += v; }
times_t t = results.at(my_key);  // safe after count() with status; always valid with bool
```

#### 3. Count active processes

With `bool` status: `results.size()` = number of process instances that ran this round.

```cpp
if (isSpecial) node.storage(special_in_range{}) = (int)res.size() - 1;
```

#### 4. Persist across rounds with `old`

```cpp
map_t r = spawn(CALL, [&](message const& m){ ... }, current_message);
r = old(CALL, map_t{}, [&](map_t prev) {
    for (auto const& [msg, t] : r)
        if (!prev.count(msg)) { node.storage(delivery_count{}) += 1; prev[msg] = t; }
    return prev;
});
```

### Safely discarding the return value

`spawn(CALL, process, key_set);` — no capture, no heap leak. The temporary `unordered_map` is destroyed at the semicolon. Use this when only the side effects inside `process` matter.

---

## 4. Protocols — Implementing Request-Reply

### Why `message_dispatch.hpp` is not a model

It is **one-way delivery only**: the destination returns `terminated_output` and the result is only in the destination's map — the sender never sees a reply.

### Key immutability constraint

A `spawn` key is fixed for the entire lifetime of that process instance. Evolving state must use `old`/`nbr` inside the process body, or be encoded in the key of a second spawn.

---

### Option A — Two spawns (snapshot reply)

**Spawn 1 — query** (querier → target):

```cpp
using query_key_t = fcpp::tuple<device_t, device_t>;  // (querier_id, target_id)

common::option<query_key_t> query;
if (should_ask && !already_started)
    query.emplace(make_tuple(node.uid, target_id));

auto q_res = spawn(CALL, [&](query_key_t const& k) {
    auto [querier, target] = k;
    real_t d = abf_distance(CALL, node.uid == querier);
    status s = node.uid == target ? status::terminated_output
             : d < INF            ? status::internal : status::border;
    return make_tuple(unit{}, s);
}, query);
```

**Spawn 2 — reply**, data in key (target → querier):

```cpp
using reply_key_t = fcpp::tuple<device_t, vec<2>>;  // (querier_id, snapshot_data)

bool reply_started = old(CALL, false, [&](bool prev){ return prev || q_res.count(my_key) > 0; });
common::option<reply_key_t> reply;
if (q_res.count(my_key) > 0 && !reply_started)
    reply.emplace(make_tuple(querier_id, node.position()));  // snapshot now

auto r_res = spawn(CALL, [&](reply_key_t const& k) {
    auto [querier, data] = k;
    real_t d = abf_distance(CALL, node.uid == querier);
    status s = node.uid == querier ? status::terminated_output
             : d < INF             ? status::internal_output : status::border;
    return make_tuple(data, s);
}, reply);

if (r_res.count(my_reply_key) > 0) received_data = r_res.at(my_reply_key);
```

Data is in the key — available on every relay without `nbr` propagation. Use `old` to prevent re-injection.

---

### Option B — Single spawn, live data via `nbr`

Key = `(querier, target)` — fixed. Both search and reply handled internally via `abf_distance` + `fold_hood`. Data is **live** (updated every round), not a snapshot. Nested exports make `FUN_EXPORT` non-trivial.

---

### Comparison

| | Two spawns | Single spawn |
|---|---|---|
| Clarity | Explicit phases | Compact |
| Data | Snapshot in reply key | Live via `nbr`/`fold_hood` |
| FUN_EXPORT | Two `spawn_t<…>` | One `spawn_t` + inner exports |
| Latency | 2 wave propagations | 1 wave + data flows back |
| Data freshness | Point-in-time snapshot | Current value each round |

**Recommendation:** two spawns for a UDP-like snapshot protocol. Single spawn if live data is required.

---

## 5. Reference

### FUN_EXPORT

```cpp
// K = key type, B = status type (bool, field<bool>, or status)
using my_spawn_t = export_list<spawn_t<K, B>, /* exports of process body */>;
```

`spawn_t<K, B>` covers the key-propagation bookkeeping; you still need to add the export types of whatever `process` does internally (its own `old`/`nbr` calls).

---

## 6. Spawning Multiple Independent Parallel Processes

### The desynchronization trap — spawn inside a loop

A fundamental FCPP invariant: **every aggregate primitive must be called the same
number of times, in the same order, on every node every round.** The CALL call-point
counter is used to match `old`/`nbr` history between nodes; diverging call sequences
produce silently wrong results or runtime crashes.

Calling `spawn` inside a loop over runtime data breaks this invariant:

```cpp
// WRONG — breaks CALL trace synchronization
for (auto const& kv : per_node_data) {
    spawn(CALL, body, make_key(kv));  // called 0× on some nodes, N× on others
}
```

- A node with 0 entries loops 0 times → 0 spawn calls.
- A node with 3 entries loops 3 times → 3 spawn calls.
- The CALL counter diverges across nodes → processes on different nodes no longer
  correspond to each other → silent mismatch, wrong state, or assertion failures.

### The fix — collect keys first, then call spawn once

`spawn`'s third argument (`key_set`) is **any iterable range** whose element type is `K`
— not only `common::option<K>`. Pass a `std::vector<K>` containing all keys to inject;
FCPP starts one independent process per element in a single call:

```cpp
// Phase A: pure logic, no FCPP primitives
std::vector<K> keys_to_inject;
for (auto const& kv : per_node_data) {
    if (should_start_process(kv))
        keys_to_inject.push_back(build_key(kv));
}

// Phase B: single spawn call — every node reaches this exactly once per round
auto results = spawn(CALL, [&](K const& k) {
    // ... routing logic — abf_distance, sp_collection, etc. are fine here ...
    return make_tuple(value, s);
}, keys_to_inject);

// Phase C: consume — pure logic, no FCPP primitives
for (auto const& [k, v] : results) {
    // ... handle received results
}
```

Nodes with nothing to inject pass an empty `keys_to_inject` — they still call spawn
and stay synchronized. Each element in `keys_to_inject` starts its own fully independent
process.

### Why each element becomes an independent process

Inside `spawn`, FCPP pushes a distinct hash of each key onto the trace stack before
running the process body:

```cpp
internal::trace_key trace_process(node.stack_trace, common::hash_to<trace_t>(k));
```

Every key gets its own trace slot → completely isolated `old`/`nbr` history →
separate propagation wave → separate termination. There is no interaction between
processes keyed by different values. From the network's perspective they are fully
parallel, independent sub-computations.

### Container type choices

| Container | Notes |
|-----------|-------|
| `common::option<K>` | 0 or 1 key; the standard idiom for single-process injection |
| `std::vector<K>` | Simplest multi-key container; no extra operators required on `K` |
| `std::set<K>` | De-duplicates automatically; requires `operator<` on `K` |
| `std::unordered_set<K>` | De-duplicates; requires `std::hash<K>` on `K` |

`std::vector<K>` is the pragmatic default when keys are already structurally unique
(the key struct carries enough fields to distinguish all concurrent processes).

### FUN_EXPORT — no change needed

`spawn_t<K, B>` covers **any number** of simultaneously active processes regardless
of how many keys were injected in a given round. No additional export entry is needed
when switching from `common::option<K>` to `std::vector<K>`.

### Real-world example — scattered database response spawn

A data-holder node may receive multiple simultaneous query requests. Each response
needs its own independent routing wave back to the respective requester. The
three-phase pattern handles this correctly:

```cpp
// Phase A — decide which responses to inject (no FCPP primitives)
std::vector<scattered_db_response> responses_to_inject;
for (auto const& [k, v] : query_res) {
    bool has_data = get<1>(v);
    if (has_data && not_already_answered(k)) {
        scattered_db_response resp(k.key, get<2>(v), k.requester,
                                   node.uid, round_tick, node.current_time());
        node.storage(tags::node_responses_provided{})[...] = resp;
        responses_to_inject.push_back(resp);
    }
}

// Phase B — single spawn: one independent routing wave per response
spawn_res_response_map response_res = spawn(CALL,
    [&](scattered_db_response const& resp) {
        real_t dist = abf_distance(CALL, node.uid == resp.requester);
        set_nodes_to_source_t path = sp_collection(CALL, dist,
            set_nodes_to_source_t{node.uid}, set_nodes_to_source_t{},
            [](set_nodes_to_source_t a, set_nodes_to_source_t b){
                a.insert(b.begin(), b.end()); return a;
            });
        bool on_path = path.count(resp.holder) > 0;
        status s = (node.uid == resp.requester) ? status::terminated_output
                 : on_path ? status::internal : status::border;
        return make_tuple(resp, s);
    },
    responses_to_inject   // ← was: common::option<scattered_db_response>
);

// Phase C — consume results (no FCPP primitives)
for (auto const& [k_r, v_r] : response_res) {
    if (node.uid == v_r.requester)
        node.storage(tags::node_data_got{})[k_r.to_string()] = v_r.data;
}
```

Each `scattered_db_response` in `responses_to_inject` becomes a completely
independent routing wave back to its requester. All waves propagate in parallel,
terminate independently, and never share state.

### Summary rules

1. **Never call `spawn` inside a loop over runtime data.** The CALL counter must
   advance identically on every node every round.
2. **Collect all keys before calling spawn.** The preparation loop (Phase A) does
   pure data logic; the single spawn call (Phase B) is always reached exactly once.
3. **An empty injection container is correct and safe.** Nodes with nothing to inject
   pass an empty vector; they still participate in existing active processes they
   received from neighbours.
4. **One key = one independent process.** Multiple keys in the same spawn call start
   separate processes with isolated state — they do not share `old`/`nbr` history.
5. **`FUN_EXPORT` does not change.** `spawn_t<K, B>` already covers multiple
   simultaneous processes.

---

## §7. Aggregate Primitives Inside the `spawn` Body — Per-Message Routing

### The problem with a global spanning tree

`message_dispatch.hpp` (FCPP sample project) pre-computes a single spanning tree
*outside* the spawn call and lets all concurrent messages share it:

```cpp
bool is_src = node.uid == src_id;               // only one root
double ds   = bis_distance(CALL, is_src, 1, 100);
set_t below = sp_collection(CALL, ds, set_t{node.uid}, set_t{}, ...);

map_t r = spawn(CALL, [&](message const& m) {
    bool inpath = below.count(m.from) + below.count(m.to) > 0;
    status s = node.uid == m.to ? status::terminated_output :
               inpath            ? status::internal          : status::border;
    return make_tuple(node.current_time(), s);
}, m);
```

This works when exactly one node is the source. Node `v` is "on path" between
`m.from` and `m.to` when either endpoint is in `v`'s subtree — correct because
on a single-rooted spanning tree the path between any two nodes passes through
their LCA, and a node is on that path iff either endpoint is a descendant.

### What breaks with multiple sources

If `is_src` is `true` for more than one node (e.g. `(node.uid % 31) == 0`):

1. `bis_distance` computes distance to the **nearest** source → Voronoi partition.
2. `sp_collection` builds a separate spanning tree per cell. `below[v]` only contains
   UIDs in `v`'s own Voronoi cell.
3. For a message where `m.from` and `m.to` are in different cells, every cross-cell
   node has `below.count(m.from)==0` and `below.count(m.to)==0` → `inpath=false` →
   status `border` → process cannot propagate across the cell boundary.

**Result: cross-cell messages are silently dropped.** No exception is raised.

### The fix — primitives inside spawn

Because every spawn key runs the process body with its own isolated `old`/`nbr`
history (§1 — key hash is pushed onto the trace stack), `bis_distance` and
`sp_collection` inside the body behave as fully independent aggregate sub-programs
per key. Each message can build its own spanning tree rooted at `m.from`:

```cpp
map_t r = spawn(CALL, [&](message const& m) {
    // Per-message spanning tree rooted at m.from
    bool is_sender = (node.uid == m.from);
    double ds_m    = bis_distance(CALL, is_sender, 1, 100);
    set_t  below_m = sp_collection(CALL, ds_m, set_t{node.uid}, set_t{},
                         [](set_t x, set_t const& y){
                             x.insert(y.begin(), y.end()); return x;
                         });
    // On a tree rooted at m.from: on-path iff receiver is in subtree
    bool inpath = below_m.count(m.to) > 0;
    status s = node.uid == m.to ? status::terminated_output :
               inpath            ? status::internal          : status::border;
    return make_tuple(node.current_time(), s);
}, m);
```

Key changes: tree root is `m.from` (not a hardcoded `src_id`); `inpath` checks
only the receiver (not both endpoints — checking the sender side is redundant on a
tree rooted at the sender); no global `below` or `parent` computed outside spawn.

### FUN_EXPORT

`bis_distance_t` and `sp_collection_t<double, set_t>` remain in `FUN_EXPORT`
regardless of whether they are called inside or outside spawn — they still
contribute `nbr` communication types that must be declared at the export level.
`device_t` can be removed if the external `parent` computation is dropped:

```cpp
FUN_EXPORT main_t = export_list<rectangle_walk_t<3>, bis_distance_t,
    sp_collection_t<double, set_t>, spawn_t<message, status>, map_t>;
```

### Could `mp_collection` avoid this fix?

**No.** `mp_collection` (multi-path) differs from `sp_collection` (single-path)
only in *how many paths* data flows along toward the root — not in which *direction*
or *which root*. Both are gradient-based: they aggregate values flowing toward the
lowest-distance node. With a Voronoi-fragmented distance field (multiple sources),
data still cannot reliably cross cell boundaries with either primitive:

- `sp_collection`: single parent per node, strictly within cell.
- `mp_collection`: flows toward all lower-distance neighbours. At the Voronoi
  boundary, the comparison `d_B > d_A` (distance to source B vs. source A) is
  geometrically arbitrary — not a reliable cross-cell routing criterion.

`mp_collection` IS a meaningful upgrade **after** the fix is applied. Inside spawn,
rooted at `m.from`, multi-path collection provides better fault tolerance:

```cpp
// mp_collection as drop-in for sp_collection inside spawn
set_t below_m = mp_collection(CALL, ds_m,
    set_t{node.uid}, set_t{},
    [](set_t x, set_t const& y){ x.insert(y.begin(), y.end()); return x; },
    [](set_t s, size_t) { return s; }  // divide: identity (set union is idempotent)
);
// inpath check unchanged: below_m.count(m.to) > 0
```

| | `sp_collection` inside spawn | `mp_collection` inside spawn |
|---|---|---|
| Path count | One per node | Multiple (all lower-distance neighbours) |
| Fault tolerance | Single-link failure loses path | Survives partial link failures |
| `divide` param | Not needed | Required (identity for sets) |
| `FUN_EXPORT` | `sp_collection_t<P,T>` includes `device_t` | `mp_collection_t<P,T>` — no `device_t` |
| Correctness | ✓ | ✓ |

**Rule:** `mp_collection` is a robustness trade-off *within* the per-message pattern,
not an escape from it. The fix (primitives inside spawn) is mandatory either way.

---

## §8 — Use-and-consume (ping-pong) pattern: query → hold → respond

### The pattern

A **requester** fires a query for data it does not hold. The query spreads until it reaches
the **holder**. The holder sends the data back. Both the query and response terminate after
delivery — no persistent channels. This differs from a channel (§4) in that neither node
keeps its role across query-response pairs.

The key asymmetry: **query = search** (flood, holder unknown); **response = route** (both
endpoints known, O(path length) participants possible).

---

### Termination failures — two modes

1. **Holder exists but slow:** `gossip(CALL, has_data, OR)` propagates "found" actively →
   `status::terminated` before the built-in wave arrives.

2. **Data absent — process runs forever:** `has_data` is always `false`; `gossip` never
   fires. The process stays alive on O(N) nodes indefinitely. `gossip` alone cannot fix this.

**Fix for absent data — hop-count timeout:**  
Compute the network diameter fully aggregate (no hardcoded assumptions), then terminate
when the flood frontier exceeds `diameter × (1 + tolerance)`:

```cpp
// Outside spawns — diameter estimate, updated every round
device_t net_leader   = gossip_min(CALL, node.uid);   // elect min-UID as reference
hops_t   dist_ldr     = abf_hops(CALL, node.uid == net_leader);
hops_t   eccentricity = gossip_max(CALL, dist_ldr);   // eccentricity of leader
// diameter ≤ 2 × eccentricity(any node) — graph-theoretic upper bound
hops_t   timeout_hops = static_cast<hops_t>(
    static_cast<real_t>(2 * eccentricity) * (1.0f + TIMEOUT_TOLERANCE) + 1.0f
);

// Inside query spawn body — unconditional calls (CALL trace invariant)
hops_t hops_from_req  = abf_hops(CALL, is_req);          // frontier hop distance
hops_t flood_frontier = gossip_max(CALL, hops_from_req);  // max frontier globally
bool   timed_out      = (flood_frontier > timeout_hops);
bool   can_terminate  = gossip(CALL, has_data || timed_out,
                               [](bool x, bool y){ return x || y; });
status s = has_data      ? status::terminated_output
         : can_terminate ? status::terminated
         :                 status::internal;
```

`TIMEOUT_TOLERANCE` is a named `constexpr real_t` (e.g., `0.25` for 25%).  
`hops_t`, `device_t`, and `bool` must be added to `FUN_EXPORT`.

`gossip_min` / `gossip_max` / `gossip` all in `collection.hpp`.  
`abf_hops` in `spreading.hpp`.

---

### Three solutions

#### Solution A — two spawns, fixed (recommended)

Remove any globally-computed gradient. Keep the query spawn as a flood with the timeout
above. Add `bis_distance + sp_collection` **inside the response spawn**, rooted at the
holder. Only O(path length) nodes participate in the response.

```cpp
// Response spawn — routed from holder to requester
spawn(CALL, [&](scattered_db_response const& resp) {
    bool is_holder    = (node.uid == resp.holder);
    bool is_requester = (node.uid == resp.requester);
    real_t d = bis_distance(CALL, is_holder, 1, comm_range);
    set_t sub = sp_collection(CALL, d, set_t{node.uid}, set_t{},
        [](set_t a, set_t b){ a.insert(b.begin(), b.end()); return a; });
    bool inpath = sub.count(resp.requester) > 0;
    status s = is_requester ? status::terminated_output
             : inpath       ? status::internal : status::border;
    return make_tuple(resp, s);
}, responses_to_inject);
```

`FUN_EXPORT` adds `device_t`, `hops_t` (diameter primitives) and keeps `bis_distance_t`,
`sp_collection_t` (response spawn), `bool` (gossip), `spawn_t` for both key types.

#### Solution B — matrioska (inner spawn inside outer)

Inner response spawn called inside the outer query spawn body, using the three-phase
pattern. Outer terminates at holder (`status::terminated`); inner routes response back.
All O(N) outer-active nodes invoke inner spawn machinery every round (empty key most rounds).

#### Solution C — state machine (single spawn, phase reversal)

`old` inside spawn body tracks `(found, holder_uid, data)`. Phase 1 floods; phase 2 routes.
All FCPP primitives called unconditionally every round — only results are phase-gated:

```cpp
real_t d = bis_distance(CALL, found && (node.uid == holder), 1, comm_range);
set_t sub = sp_collection(CALL, d, ...);
bool gossip_found = gossip(CALL, found, [](bool x, bool y){ return x || y; });
// if (!gossip_found): return internal; else: use d/sub for routing
```

O(diameter) extra rounds between phase 1 and phase 2 (gossip propagation delay).

---

### Comparison

| | Solution A | Solution B | Solution C |
|---|---|---|---|
| Spawns | 2 sequential | 1 outer + 1 inner | 1 |
| Response participants | O(path length) | O(path length) inner; O(N) outer | O(N) during gossip; O(path length) after |
| Phase-switch delay | None | None | O(diameter) rounds |
| Key types needed | 2 | 2 (nested) | 1 |
| Recommended for | General use | Single-key requirement | Exactly-once by key |

Full analysis and code in `fcpp-exercises/run/scattered_database_fix_plan.md § Ping-pong`
and `fcpp-exercises/SPAWN_explanation.md §8`.

