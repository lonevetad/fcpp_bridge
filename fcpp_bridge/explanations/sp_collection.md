# `sp_collection` — Spanning-Tree Aggregation in FCPP

## What it does (one line)

`sp_collection` collects and **aggregates values from every node in the network
up toward a designated root**, using a gradient-based spanning tree.  
Each node ends up holding the accumulated value of its own **subtree** — itself
plus all descendant nodes.

---

## The Mental Model

Imagine a tree of nodes rooted at one fixed node (say, node 0):

```
            node 0  (root, dist = 0)
           /       \
       node 2       node 1      (dist ≈ 1 hop)
      /     \            \
  node 4   node 5      node 3   (dist ≈ 2 hops)
```

Each node has a **local value** (e.g. its own UID inside a set).  
`sp_collection` lets values flow **up** the tree, accumulating at each node:

```
node 5 → sends {5} up to node 2
node 4 → sends {4} up to node 2
node 2 → receives {4}, {5}, adds own {2} → holds {2, 4, 5}  ← its subtree
node 2 → sends {2, 4, 5} up to node 0

node 3 → sends {3} up to node 1
node 1 → receives {3}, adds own {1} → holds {1, 3}
node 1 → sends {1, 3} up to node 0

node 0 → receives {2,4,5} and {1,3}, adds own {0} → holds {0,1,2,3,4,5}
```

The root sees **everyone**; each leaf sees only **itself**.

---

## Signature

### Python DSL (fcpp_bridge)

```python
result = sp_collection(dist, local_val, null_val, lambda a, b: ...)
```

| Parameter   | Type                | Meaning |
|-------------|---------------------|---------|
| `dist`      | `float` (from `bis_distance`) | Gradient field — defines the tree structure. Smaller = closer to root. |
| `local_val` | `T`                 | This node's own contribution. |
| `null_val`  | `T`                 | Identity element of the accumulation (e.g. `frozenset()` for set-union, `0` for sum). |
| `lambda a, b: ...` | `(T, T) → T` | How to combine two accumulated values. Must be **associative** and **commutative**. |

**Returns:** The accumulated value of this node's subtree.

### C++ (FCPP)

```cpp
// Header: <lib/coordination/collection.hpp>
auto result = sp_collection(CALL,
    dist_to_root,              // double — gradient
    local_value,               // T       — this node's contribution
    null_value,                // T       — identity element
    [](auto a, auto b) { return combine(a, b); }   // C++14 generic lambda
);
```

`sp_collection` = **s**panning-tree **p**ath **collection**.  
It is the dual of `broadcast`: `broadcast` sends data *down* from root to leaves;
`sp_collection` sends data *up* from leaves to root.

---

## How the spanning tree is built

The tree comes from the `bis_distance` gradient:

1. `bis_distance(is_source, speed, comm)` computes the **distance from the nearest
   source node** for every node in the network.
2. Each non-source node picks its **parent** as the neighbour with the smallest
   distance value.  These parent pointers form a spanning tree toward the source(s).
3. `sp_collection` routes data along this tree — children send to parent, parent
   accumulates and forwards further up.

If the source moves or the topology changes, the tree self-repairs within a few
rounds (FCPP primitives are self-healing by construction).

---

## Usage in `scattered_database.py`

```python
# Step 1 — build the gradient rooted at node 0
dist_from_root = bis_distance(self_uid() == 0, 1.0, COMM)   # noqa: F821

# Step 2 — collect the set of UIDs in this node's subtree
routing_set = sp_collection(                                  # noqa: F821
    dist_from_root,
    frozenset({self_uid()}),   # local value: my own UID      # noqa: F821
    frozenset(),               # null: empty set
    lambda a, b: a | b,        # accumulate: set union
)
```

### What `routing_set` contains at each node

| Node position in tree | `routing_set` value |
|-----------------------|---------------------|
| Root (node 0)         | All UIDs in the network |
| Internal node         | Its own UID + UIDs of all descendants |
| Leaf node             | Just its own UID: `frozenset({self_uid()})` |

### Why it's needed — routing queries with `spawn`

The `routing_set` is then used in the `spawn` step as a routing table:

```python
active_spawns = spawn(
    lambda key: (
        self_state.local_db.get(key[1]),    # payload: the data value
        # key = (requester_uid, target_id)
        STATUS_TERMINATED  if key[1] in self_state.local_db   # I hold the data → done
        else STATUS_INTERNAL if (
            key[0] in routing_set or         # requester is in my subtree
            key[1] in routing_set            # target   is in my subtree
        )
        else STATUS_BORDER,                  # neither → skip me
    ),
    new_query_key,
)
```

The logic is:

```
       node 0 (root)
      /      \
  node A    node B
    |
  node Q (requester, wants data from node T)
          …
      node T (holder)
```

- Node A's `routing_set` contains `{A, Q, T}` (both are in its subtree).
  → STATUS_INTERNAL — it relays the query token.
- Node B's `routing_set` contains `{B}` — neither Q nor T is below B.
  → STATUS_BORDER — it ignores the token entirely.
- Node T's `local_db` contains the target key.
  → STATUS_TERMINATED — it is the answer node; FCPP now routes the payload
    back toward Q along the same spanning tree.

In short, **`sp_collection` turns each node's routing_set into a local routing
table**: a node only participates in a query if the sender or receiver are
somewhere "below" it in the tree.

---

## Comparison with related primitives

| Primitive | Direction | What it computes |
|-----------|-----------|-----------------|
| `bis_distance` | root → leaves (gradient) | Distance to nearest source |
| `broadcast` | root → leaves | Pushes a value from root outward |
| `sp_collection` | leaves → root | Pulls aggregated values toward root |
| `mp_collection` | leaves → root | Same but routes along **multiple** paths (redundancy) |
| `nbr` | 1-hop only | Shares a value with immediate neighbours |
| `fold_hood` | 1-hop only | Folds a function over immediate neighbours' values |

`sp_collection` is the right choice when you need **global aggregation** along the
tree (e.g. gathering all UIDs, computing a sum/max over the whole network) and you
already have a `bis_distance` gradient available.  
Use `fold_hood` when you only need **1-hop** neighbourhood aggregation.

---

## Common accumulators

```python
# Set union (as in scattered_database)
sp_collection(d, frozenset({self_uid()}), frozenset(), lambda a, b: a | b)

# Sum
sp_collection(d, 1, 0, lambda a, b: a + b)

# Maximum
sp_collection(d, my_value, float('-inf'), lambda a, b: max(a, b))

# Count of nodes in subtree
sp_collection(d, 1, 0, lambda a, b: a + b)
```

---

## Key constraints

1. **The accumulator must be associative and commutative** — FCPP may combine
   values in any order along the tree.
2. **`null_val` must be the identity element** of the accumulator  
   (i.e. `f(null_val, x) == x` for all `x`).
3. **`sp_collection` must be called unconditionally** (before any `if`/`match`)
   so that the CALL counter is incremented at the same position on every node
   every round — a hard requirement of the FCPP runtime.
4. **Self-healing**: if the gradient changes (e.g. source moves), the spanning
   tree re-forms automatically and `sp_collection` re-aggregates within a few
   rounds.

---

## Multiple sources — the Voronoi fragmentation trap

### What happens

`bis_distance` with multiple source nodes (`is_source` true for more than one node)
computes distance to the **nearest** source. The network is silently partitioned into
Voronoi cells, one per source. `sp_collection` then builds a separate spanning tree
within each cell. Each node's result only reflects UIDs in its own Voronoi cell.

This is often surprising: no error is raised, the aggregation appears to work, but
each node's `result` is missing all descendants that happen to be in other cells.

### When it matters for routing

The `message_dispatch.hpp` (FCPP sample project) pattern uses `sp_collection` to
build `below[v]` = the set of all node UIDs in `v`'s subtree, then checks:

```python
inpath = (sender_uid in routing_set) or (receiver_uid in routing_set)
```

With a single global source this is correct: the spanning tree connects all nodes and
every `routing_set` reflects the true subtree. With multiple sources the routing
logic silently fails for any message whose sender and receiver are in different
Voronoi cells — the message process never propagates across the boundary.

### The fix — move `bis_distance` + `sp_collection` inside `spawn`

Primitives inside a `spawn` body run with fully isolated per-key history (each key
pushes its own hash onto the trace stack). The solution is to build the spanning tree
**per-message**, rooted at the message's own sender, inside the spawn body:

```cpp
// C++ (message_dispatch.hpp corrected)
map_t r = spawn(CALL, [&](message const& m) {
    bool is_sender = (node.uid == m.from);
    double ds_m    = bis_distance(CALL, is_sender, 1, 100);   // tree rooted at sender
    set_t  below_m = sp_collection(CALL, ds_m, set_t{node.uid}, set_t{},
                         [](set_t x, set_t const& y){
                             x.insert(y.begin(), y.end()); return x;
                         });
    bool inpath = below_m.count(m.to) > 0;   // receiver in subtree = on path
    status s = node.uid == m.to ? status::terminated_output :
               inpath            ? status::internal          : status::border;
    return make_tuple(node.current_time(), s);
}, m);
```

```python
# Python DSL equivalent (fcpp_bridge)
def _route_message(msg_key):
    sender, receiver, _ = msg_key
    dist_from_sender = bis_distance(self_uid() == sender, 1.0, COMM)
    routing_set = sp_collection(dist_from_sender, frozenset({self_uid()}),
                                frozenset(), lambda a, b: a | b)
    inpath = receiver in routing_set
    if self_uid() == receiver:
        return (None, STATUS_TERMINATED)
    elif inpath:
        return (None, STATUS_INTERNAL)
    else:
        return (None, STATUS_BORDER)
```

Each spawn process builds its own independent spanning tree. CALL synchronization
is preserved: all nodes that hold the process for key `m` always execute
`bis_distance` and `sp_collection` once, in order, within the key's trace slot.

### Does `mp_collection` solve the problem without moving inside spawn?

**No.** `mp_collection` (multi-path) changes *how many paths* data flows along, not
*which root* or *which direction*. Both `sp_collection` and `mp_collection` are
gradient-based — they aggregate data flowing toward lower-distance nodes. With a
Voronoi-fragmented distance field, data from one cell cannot reliably reach another
cell regardless of which collection primitive is used:

- `sp_collection`: single parent strictly within cell.
- `mp_collection`: flows to all lower-distance neighbours. At the Voronoi boundary,
  distances from different roots are compared (`d_A` vs `d_B`) — geometrically
  arbitrary; cross-cell flow is unreliable.

**`mp_collection` IS beneficial *after* the fix is applied** (inside spawn): it
provides multi-path routing toward the message sender, improving fault tolerance when
links drop mid-delivery. For `set_t` the divide function is identity (sets
deduplicate automatically). The `inpath` check is unchanged.

| Scenario | `sp_collection` outside spawn | `mp_collection` outside spawn | Primitives inside spawn |
|---|---|---|---|
| Single source | ✓ Correct | ✓ Correct | ✓ Correct |
| Multiple sources | ✗ Voronoi fragmentation | ✗ Same failure | ✓ Correct |
| Fault tolerance | Lower | Higher | Higher (with `mp_collection`) |

**Rule:** The fix (primitives inside spawn) is mandatory for multiple-source
correctness. The `sp_collection` vs `mp_collection` choice is a robustness
trade-off within the per-message pattern.
