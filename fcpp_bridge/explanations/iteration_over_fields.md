# Field Construction and Iteration in FCPP

This document explains two practical operations on FCPP fields: building a `field<V>` from a `std::map`, and iterating over a field's values for side effects without returning a value.

---

## Background: `field<T>` Internal Layout

A `field<T>` (defined in [fcpp/src/lib/data/field.hpp](../../fcpp/src/lib/data/field.hpp)) stores:

- `m_vals[0]` — the **default** ("other") value, used for every device that is not explicitly listed.
- `m_ids[i]` — the device UID of the i-th exception, sorted in ascending order.
- `m_vals[i+1]` — the corresponding value for `m_ids[i]`.

So a field is a sparse map: a default value plus a finite set of *exception* (device, value) pairs. The `device_t` type is `uint32_t` on general systems (`FCPP_DEVICE 32`).

The internal construction function is:
```cpp
// friend of field<A>, lives in fcpp::details
template <typename A>
field<A> fcpp::details::make_field(std::vector<device_t>&& ids, std::vector<A>&& vals);
```
`ids` must be **sorted ascending** and `vals` must have exactly `ids.size() + 1` elements (index 0 is the default).

Accessor helpers (also in `fcpp::details`, usable from any translation unit that includes `field.hpp`):
```cpp
fcpp::details::get_ids(f)   // → std::vector<device_t> const&
fcpp::details::get_vals(f)  // → std::vector<T> const&
fcpp::details::other(f)     // → T const& — the default value
fcpp::details::self(f, uid) // → T const& — the value for a specific device
```

---

## 1. Converting `std::map` to `field<V>`

### Case A: Map keys ARE device UIDs

The map has the form `std::map<device_t, V>`. Each key is already a device UID, and each value is what that device contributes to the field.

`std::map` is sorted by key, so no additional sorting is needed.

```cpp
#include "lib/data/field.hpp"
#include <map>

// Builds a field<V> from a map whose keys are device UIDs.
// `default_val` is used for every device NOT present in the map.
template <typename V>
fcpp::field<V> map_keys_to_field(V default_val, std::map<fcpp::device_t, V> const& m) {
    std::vector<fcpp::device_t> ids;
    std::vector<V> vals;
    ids.reserve(m.size());
    vals.reserve(m.size() + 1);
    vals.push_back(default_val);           // index 0: default
    for (auto const& [uid, v] : m) {       // std::map iterates in key order
        ids.push_back(uid);
        vals.push_back(v);
    }
    return fcpp::details::make_field(std::move(ids), std::move(vals));
}
```

**Example:**
```cpp
std::map<fcpp::device_t, float> readings = {{1, 3.14f}, {4, 2.71f}, {7, 1.41f}};
fcpp::field<float> f = map_keys_to_field(0.0f, readings);
// f has default=0.0, device 1→3.14, device 4→2.71, device 7→1.41
```

### Case B: Map values contain a reference to a device UID

The map has the form `std::map<K, SomeStruct>` where `SomeStruct` carries a `device_t` member (or an accessor returning one). The field value type `V` can be `SomeStruct` itself, or a derived scalar extracted from it.

Because the map's keys are **not** device UIDs, the entries must be re-sorted by UID before building the field.

```cpp
#include "lib/data/field.hpp"
#include <algorithm>
#include <map>

// Builds a field<V> from a map where each value contains a device UID.
//   get_uid : SomeStruct → device_t    (extract the UID from a value)
//   get_val : SomeStruct → V           (extract the field value from a value)
// `default_val` is used for every device NOT represented.
template <typename K, typename Struct, typename V>
fcpp::field<V> map_vals_to_field(
    V default_val,
    std::map<K, Struct> const& m,
    std::function<fcpp::device_t(Struct const&)> get_uid,
    std::function<V(Struct const&)>              get_val)
{
    // collect (uid, field-value) pairs
    std::vector<std::pair<fcpp::device_t, V>> entries;
    entries.reserve(m.size());
    for (auto const& [key, s] : m)
        entries.emplace_back(get_uid(s), get_val(s));

    // field<T> requires ids sorted ascending
    std::sort(entries.begin(), entries.end(),
              [](auto const& a, auto const& b){ return a.first < b.first; });

    std::vector<fcpp::device_t> ids;
    std::vector<V> vals;
    ids.reserve(entries.size());
    vals.reserve(entries.size() + 1);
    vals.push_back(default_val);
    for (auto const& [uid, v] : entries) {
        ids.push_back(uid);
        vals.push_back(v);
    }
    return fcpp::details::make_field(std::move(ids), std::move(vals));
}
```

**Example:**
```cpp
struct DeviceRecord {
    fcpp::device_t uid;
    float          temperature;
};
std::map<std::string, DeviceRecord> registry = {
    {"sensor-A", {3, 21.5f}},
    {"sensor-B", {1, 19.0f}},
    {"sensor-C", {7, 23.3f}},
};
fcpp::field<float> temps = map_vals_to_field<std::string, DeviceRecord, float>(
    0.0f, registry,
    [](DeviceRecord const& r){ return r.uid; },
    [](DeviceRecord const& r){ return r.temperature; }
);
// temps: default=0.0, device 1→19.0, device 3→21.5, device 7→23.3
```

---

## 2. Iterating Over a Field for Side Effects

FCPP fields are not containers in the STL sense. There is no `begin()`/`end()` pair exposed. There are three ways to iterate depending on context.

### 2a. Inside an aggregate function — using `fold_hood` with `common::unit`

Within a `node_t` computation (the standard FCPP aggregate programming context), the idiomatic side-effect iteration is to use `fold_hood` with `common::unit` as the accumulator. This pattern is also used internally by `list_hood` in [fcpp/src/lib/coordination/utils.hpp](../../fcpp/src/lib/coordination/utils.hpp).

`common::unit` (defined in [fcpp/src/lib/common/traits.hpp](../../fcpp/src/lib/common/traits.hpp)) is an empty struct used as a "void" accumulator type when you only want side effects from a fold.

```cpp
#include "lib/coordination/utils.hpp"
#include "lib/common/traits.hpp"

// Inside an FCPP aggregate function:
// iterate over all neighbours' values of `my_field`, performing a side effect on each.
fold_hood(node, call_point,
    [&](to_local<decltype(my_field)> const& val, fcpp::common::unit) -> fcpp::common::unit {
        // side effect: e.g., log, accumulate into an external container, etc.
        std::cout << "neighbour value: " << val << "\n";
        return {};
    },
    my_field,
    fcpp::common::unit{}   // initial / "self" accumulator
);
```

The lambda receives each neighbour's value and the running accumulator (`unit`), and returns `unit`. The result of `fold_hood` is itself discarded (`unit`).

To also see the device UID alongside the value, use the three-argument form of the internal `fold_hood` (from `field.hpp`, called through the node context):
```cpp
// The internal details::fold_hood overload with ids is invoked automatically
// when the operator takes (device_t, value, accumulator):
fold_hood(node, call_point,
    [&](fcpp::device_t uid, float val, fcpp::common::unit) -> fcpp::common::unit {
        std::cout << "device " << uid << " → " << val << "\n";
        return {};
    },
    my_field,
    fcpp::common::unit{}
);
```

### 2b. Inside an aggregate function — using `map_hood` and discarding the result

`map_hood` applies a function pointwise and **always returns** a new field. If you only need side effects, call `map_hood` and ignore the return value. This is less efficient than `fold_hood` (it allocates a result field), but may be more readable for simple cases.

```cpp
// Result is intentionally unused; cast to void to silence warnings.
(void)fcpp::map_hood([&](float val) -> bool {
    std::cout << val << "\n";
    return true;   // dummy return
}, my_field);
```

### 2c. Outside any node context — using `details::field_iterator` directly

For code that does not have access to a `node_t` (e.g., utility functions that manipulate fields directly), use the low-level `details::field_iterator` from `field.hpp`. This iterator walks only the *exception* entries (devices with non-default values).

**Important:** the iterator does NOT visit the default value. You must handle it separately via `details::other(f)`.

```cpp
#include "lib/data/field.hpp"

template <typename T, typename F>
void for_each_field(fcpp::field<T> const& f, F&& func) {
    // handle the default value (for all devices NOT in the exception list)
    // pass max uid as a sentinel meaning "every other device"
    func(std::numeric_limits<fcpp::device_t>::max(), fcpp::details::other(f));

    // iterate over exception entries
    for (fcpp::details::field_iterator<fcpp::field<T> const> it(f); not it.end(); ++it) {
        func(it.id(), it.value());
    }
}
```

**Usage:**
```cpp
fcpp::field<float> f = /* ... */;
for_each_field(f, [](fcpp::device_t uid, float val) {
    if (uid == std::numeric_limits<fcpp::device_t>::max())
        std::cout << "default: " << val << "\n";
    else
        std::cout << "device " << uid << ": " << val << "\n";
});
```

Alternatively, if you only need to visit exception entries (and handle the default separately), use `get_ids` / `get_vals` directly:

```cpp
auto const& ids  = fcpp::details::get_ids(f);   // sorted vector of exception UIDs
auto const& vals = fcpp::details::get_vals(f);  // vals[0] = default, vals[i+1] = ids[i]'s value

// default:
T default_val = vals[0];

// exceptions:
for (size_t i = 0; i < ids.size(); ++i) {
    fcpp::device_t uid = ids[i];
    T const& val       = vals[i + 1];
    // ... do something ...
}
```

---

## Summary

| Goal | Recommended API | Where |
|---|---|---|
| Build from `std::map<device_t, V>` | `details::make_field` with pre-sorted ids/vals | `field.hpp` |
| Build from `std::map<K, Struct>` (uid in value) | sort by uid, then `details::make_field` | `field.hpp` |
| Side-effect iteration inside aggregate | `fold_hood` with `common::unit` accumulator | `coordination/basics.hpp` |
| Pointwise iteration (result discarded) | `map_hood`, discard return | `data/field.hpp` |
| Low-level iteration outside node context | `details::field_iterator` or `details::get_ids`/`get_vals` | `data/field.hpp` |

### Key invariants to respect

- `ids` passed to `make_field` must be **sorted ascending** and **unique**; violating this silently corrupts the field.
- The `vals` vector must have exactly `ids.size() + 1` elements; `vals[0]` is always the default.
- The default value represents every device not listed in `ids`. If the map does not cover all devices in the network, choose `default_val` to represent "no data".
- `field_iterator` on a mutable field (`field<T>&`) provides an `emplace(uid, value)` method to insert/overwrite entries during iteration — useful for in-place construction but requires care with ordering.
