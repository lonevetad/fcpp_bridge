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
