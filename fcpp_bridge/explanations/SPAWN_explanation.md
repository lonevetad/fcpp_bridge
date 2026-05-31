# `spawn` — How It Works

## Signature

Defined in [`fcpp/src/lib/coordination/basics.hpp`](fcpp/src/lib/coordination/basics.hpp):

```cpp
spawn(node, call_point, process, key_set, xs...)
  -> std::unordered_map<K, R>
```

- `key_set` — a set of values of type `K` (the "keys")
- `process` — a callable `(K, xs...) -> tuple<R, B>` where `R` is the result and `B` is a status
- `xs...` — extra arguments forwarded to every `process` call

---

## What "keys" are

A key is the **identity of one independent aggregate process instance**. `spawn` lets many logically distinct sub-computations run concurrently on the same network, each identified by its key. You can think of keys the same way you would think of process IDs in an OS: each key owns its own trace slot, so the `old`/`nbr` state inside `process` is completely isolated per key — different keys never read each other's exports.

This isolation is enforced at the trace level:

```cpp
internal::trace_key trace_process(node.stack_trace, common::hash_to<trace_t>(k));
```

Each key `k` pushes a distinct hash onto the trace stack before running `process(k, ...)`, so the FCPP runtime treats each `(call_point, key)` pair as a separate history.

---

## What `spawn` does — step by step

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

---

## The three status flavours

| `B` type | Meaning | Typical use |
|---|---|---|
| `bool` | `true` = `internal_output`, `false` = `border_output` | simple yes/no propagation |
| `field<bool>` | per-neighbour propagation flag | asymmetric spreading |
| `status` | full control: `internal`, `border`, `terminated`, `+output` | fine-grained lifecycle |

### `status` enum values

```
terminated        — process ending; propagate termination signal to neighbours
border            — part of the process, but do not expand to new neighbours
internal          — part of the process; propagate to neighbours
*_output suffix   — same as above, but also include this node's result in the return map
output            — synonym for internal_output
```

---

## Concrete mental model

Imagine a query propagating through the network, initiated by one or more nodes:

```cpp
spawn(CALL,
    [&](device_t initiator, ...) -> tuple<double, status> {
        // this body runs independently for EACH key = initiator
        double my_result = ...;
        bool still_alive = ...;
        return {my_result, still_alive ? status::internal_output
                                       : status::terminated};
    },
    my_initiated_queries   // keys this node is starting this round
);
```

- Node 3 adds key `7` to `my_initiated_queries` — it starts a sub-computation with ID 7.
- Node 3's neighbours see key `7` in its exports next round and also run `process(7, ...)`.
- The wave spreads as long as nodes return `internal`; it stops when they return `terminated`.
- Results for key `7` appear in the returned map only on nodes that returned an `_output` status.

Each key is a completely independent wave with its own `old`/`nbr` history — that isolation is the entire point of keys.

---

## `FUN_EXPORT`

```cpp
// K = key type, B = status type (bool, field<bool>, or status)
using my_spawn_t = export_list<spawn_t<K, B>, /* exports of process body */>;
```

`spawn_t<K, B>` covers the key-propagation bookkeeping; you still need to add the export types of whatever `process` does internally (its own `old`/`nbr` calls).
