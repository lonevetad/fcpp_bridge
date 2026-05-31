import ast
from typing import Dict, List, Optional, Set, Tuple

from fcpp_bridge.python_dsl.types import CppType
from fcpp_bridge.log import get_logger
from ._constants import _FCPP_PRIMITIVES
from ._cpp_standard import CppStandard

_log = get_logger(__name__)


class PythonAstVisitor(ast.NodeVisitor):
    """Visit Python AST nodes and translate to C++ expressions and statements."""

    def __init__(self, constants: dict = None, cpp_std: CppStandard = CppStandard.CPP17):
        self.variables: Dict[str, CppType] = {}
        self.errors: List[str] = []
        self.used_primitives: List[str] = []
        self.declared_vars: Set[str] = set()
        self.uses_frozenset: bool = False
        self.uses_ranges_header: bool = False  # True when C++20 <ranges> is needed
        # Tracks Dict[K, V] annotated variables → (key_cpp_type, val_cpp_type).
        # Populated by visit_AnnAssign; used by dict.keys()/values() and comprehensions.
        self.dict_type_env: Dict[str, Tuple[str, str]] = {}
        self.cpp_std: CppStandard = cpp_std
        # Optional namespace for constant-folding dotted attribute chains.
        # When provided (typically the compute() function's __globals__), any
        # dotted name that resolves to an int/float is emitted as a literal,
        # which is required for valid C++ case labels (e.g. WorkerRole.X.value).
        self.constants: dict = constants if constants is not None else {}

    # ── Type-annotation helpers ───────────────────────────────────────────────

    def _annotation_to_cpp(self, node: ast.expr) -> Optional[str]:
        """Convert a Python type-annotation AST node to a C++ type string.

        Handles: int, float, bool, str, Dict[K,V], List[T], Set[T], Tuple[T,...].
        Returns None for unrecognised annotations.
        """
        if isinstance(node, ast.Name):
            return {"int": "int", "float": "double", "str": "std::string",
                    "bool": "bool"}.get(node.id)
        if isinstance(node, ast.Subscript):
            outer = node.value
            if not isinstance(outer, ast.Name):
                return None
            name = outer.id
            # Unwrap ast.Index for Python 3.8 compat (3.9+ drops it)
            sl = node.slice
            if isinstance(sl, ast.Index):  # type: ignore[attr-defined]
                sl = sl.value  # type: ignore[attr-defined]

            if name in ("Dict", "dict"):
                kv = self._annotation_to_dict_types(node)
                if kv:
                    return f"std::map<{kv[0]}, {kv[1]}>"
            elif name in ("List", "list"):
                inner = self._annotation_to_cpp(sl)
                if inner:
                    return f"std::vector<{inner}>"
            elif name in ("Set", "set"):
                inner = self._annotation_to_cpp(sl)
                if inner:
                    return f"std::set<{inner}>"
            elif name in ("Tuple", "tuple"):
                if isinstance(sl, ast.Tuple):
                    parts = [self._annotation_to_cpp(e) for e in sl.elts]
                else:
                    parts = [self._annotation_to_cpp(sl)]
                if all(p is not None for p in parts):
                    return f"std::tuple<{', '.join(parts)}>"  # type: ignore[arg-type]
        return None

    def _annotation_to_dict_types(self, node: ast.Subscript) -> Optional[Tuple[str, str]]:
        """Extract (key_cpp_type, val_cpp_type) from a Dict[K, V] annotation node."""
        if not isinstance(node.value, ast.Name) or node.value.id not in ("Dict", "dict"):
            return None
        sl = node.slice
        if isinstance(sl, ast.Index):  # type: ignore[attr-defined]
            sl = sl.value  # type: ignore[attr-defined]
        if isinstance(sl, ast.Tuple) and len(sl.elts) == 2:
            k = self._annotation_to_cpp(sl.elts[0])
            v = self._annotation_to_cpp(sl.elts[1])
            if k and v:
                return (k, v)
        return None

    # ── Comprehension IIFE helpers ────────────────────────────────────────────

    def _comp_for_header(self, target: ast.expr, iter_node: ast.expr
                         ) -> Tuple[str, str, str]:
        """Return (for_line, deduction_extra, reserve_line) for a comprehension loop.

        ``for_line``        — the ``for (...)`` statement to open the loop body.
        ``deduction_extra`` — extra lines needed before the vector declaration
                              to deduce element type (may be empty string).
        ``reserve_line``    — an optional ``_r.reserve(...)`` line (may be empty).

        The caller still needs to strip the trailing ``{`` from ``for_line`` when
        the loop body is generated separately.
        """
        # ── range() ──────────────────────────────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Name)
            and iter_node.func.id == "range"
        ):
            var = target.id if isinstance(target, ast.Name) else "i"
            args = iter_node.args
            if len(args) == 1:
                end = self.visit(args[0])
                header = f"int {var} = 0; {var} < {end}; ++{var}"
            elif len(args) == 2:
                s, e = self.visit(args[0]), self.visit(args[1])
                header = f"int {var} = {s}; {var} < {e}; ++{var}"
            elif len(args) == 3:
                s, e, step = self.visit(args[0]), self.visit(args[1]), self.visit(args[2])
                header = f"int {var} = {s}; {var} < {e}; {var} += {step}"
            else:
                self.errors.append("range() requires 1-3 args in comprehension")
                return ("", "", "")
            return (f"for ({header})", "", "")

        sb = self.cpp_std.supports_structured_bindings()

        # ── dict.items() with (k, v) target ──────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "items"
            and isinstance(target, ast.Tuple)
            and len(target.elts) == 2
            and all(isinstance(e, ast.Name) for e in target.elts)
        ):
            k, v = target.elts[0].id, target.elts[1].id  # type: ignore[union-attr]
            container = self.visit(iter_node.func.value)
            if sb:
                return (f"for (auto& [{k}, {v}] : {container})", "", "")
            # C++14: iterate pairs, unpack manually
            return (
                f"for (auto& _kv : {container})",
                f"auto& {k} = _kv.first; auto& {v} = _kv.second;",
                "",
            )

        # ── dict.keys() ───────────────────────────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "keys"
            and isinstance(target, ast.Name)
        ):
            var = target.id
            container = self.visit(iter_node.func.value)
            if sb:
                return (f"for (auto& [{var}, _v_{var}] : {container})",
                        "", f"    _r.reserve({container}.size());")
            return (
                f"for (auto& _kv : {container})",
                f"auto& {var} = _kv.first;",
                f"    _r.reserve({container}.size());",
            )

        # ── dict.values() ─────────────────────────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "values"
            and isinstance(target, ast.Name)
        ):
            var = target.id
            container = self.visit(iter_node.func.value)
            if sb:
                return (f"for (auto& [_k_{var}, {var}] : {container})",
                        "", f"    _r.reserve({container}.size());")
            return (
                f"for (auto& _kv : {container})",
                f"auto& {var} = _kv.second;",
                f"    _r.reserve({container}.size());",
            )

        # ── generic sequence ──────────────────────────────────────────────────
        if isinstance(target, ast.Name):
            var = target.id
            iterable = self.visit(iter_node)
            return (f"for (auto& {var} : {iterable})",
                    "", f"    _r.reserve({iterable}.size());")

        self.errors.append(f"Unsupported comprehension target: {ast.dump(target)}")
        return ("", "", "")

    def _comp_elem_type(self, target: ast.expr, iter_node: ast.expr,
                        expr_str: str) -> Tuple[str, str]:
        """Return (type_deduction_lines, elem_type_alias) for a comprehension.

        ``type_deduction_lines`` — C++ lines to emit before the vector declaration
                                    (may be empty).
        ``elem_type_alias``      — the C++ type to use for the container element
                                    (e.g. ``_T``, ``int``).
        """
        # range() → always int
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Name)
            and iter_node.func.id == "range"
        ):
            return ("", "int")

        # dict.items() with (k, v) target — use _expr_fn with two auto& params
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "items"
            and isinstance(target, ast.Tuple)
            and len(target.elts) == 2
            and all(isinstance(e, ast.Name) for e in target.elts)
        ):
            k, v = target.elts[0].id, target.elts[1].id  # type: ignore[union-attr]
            container = self.visit(iter_node.func.value)
            lines = (
                f"    auto _expr_fn = [&](auto& {k}, auto& {v}) {{ return {expr_str}; }};\n"
                f"    using _T = std::decay_t<decltype(_expr_fn("
                f"{container}.begin()->first, {container}.begin()->second))>;"
            )
            return (lines, "_T")

        # dict.keys() — element is the key type
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "keys"
            and isinstance(target, ast.Name)
        ):
            var = target.id
            container = self.visit(iter_node.func.value)
            obj_name = (iter_node.func.value.id
                        if isinstance(iter_node.func.value, ast.Name) else None)
            kv = self.dict_type_env.get(obj_name) if obj_name else None
            key_type = kv[0] if kv else f"decltype({container}.begin()->first)"
            lines = (
                f"    auto _expr_fn = [&](auto& {var}) {{ return {expr_str}; }};\n"
                f"    using _T = std::decay_t<decltype(_expr_fn("
                f"std::declval<{key_type}&>()))>;"
            )
            return (lines, "_T")

        # dict.values() — element is the value type
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "values"
            and isinstance(target, ast.Name)
        ):
            var = target.id
            container = self.visit(iter_node.func.value)
            obj_name = (iter_node.func.value.id
                        if isinstance(iter_node.func.value, ast.Name) else None)
            kv = self.dict_type_env.get(obj_name) if obj_name else None
            val_type = kv[1] if kv else f"decltype({container}.begin()->second)"
            lines = (
                f"    auto _expr_fn = [&](auto& {var}) {{ return {expr_str}; }};\n"
                f"    using _T = std::decay_t<decltype(_expr_fn("
                f"std::declval<{val_type}&>()))>;"
            )
            return (lines, "_T")

        # generic — use _expr_fn(*iter.begin()) for type deduction
        if isinstance(target, ast.Name):
            var = target.id
            iterable = self.visit(iter_node)
            lines = (
                f"    auto _expr_fn = [&](auto& {var}) {{ return {expr_str}; }};\n"
                f"    using _T = std::decay_t<decltype(_expr_fn(*{iterable}.begin()))>;"
            )
            return (lines, "_T")

        return ("", "auto")

    def _make_comprehension_iife(self, target: ast.expr, iter_node: ast.expr,
                                  ifs: list, expr_str: str,
                                  result_container: str,
                                  insert_method: str) -> str:
        """Build the IIFE string for a list or set comprehension."""
        for_line, body_preamble, reserve_line = self._comp_for_header(target, iter_node)
        if not for_line:
            return "0"
        type_lines, elem_type = self._comp_elem_type(target, iter_node, expr_str)

        cond_str = " && ".join(self.visit(c) for c in ifs) if ifs else ""
        if cond_str:
            body_line = f"        if ({cond_str}) _r.{insert_method}({expr_str});"
        else:
            body_line = f"        _r.{insert_method}({expr_str});"

        parts = ["([&]() {"]
        if type_lines:
            parts.append(type_lines)
        parts.append(f"    {result_container}<{elem_type}> _r;")
        if reserve_line:
            parts.append(reserve_line)
        parts.append(f"    {for_line} {{")
        if body_preamble:
            parts.append(f"        {body_preamble}")
        parts.append(body_line)
        parts.append("    }")
        parts.append("    return _r;")
        parts.append("}())")
        return "\n".join(parts)

    def _make_dict_comprehension_iife(self, target: ast.expr, iter_node: ast.expr,
                                       ifs: list, key_str: str, val_str: str) -> str:
        """Build the IIFE string for a dict comprehension → std::map."""
        cond_str = " && ".join(self.visit(c) for c in ifs) if ifs else ""
        if cond_str:
            assign_line = f"        if ({cond_str}) _r[{key_str}] = {val_str};"
        else:
            assign_line = f"        _r[{key_str}] = {val_str};"

        # ── range() ──────────────────────────────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Name)
            and iter_node.func.id == "range"
        ):
            var = target.id if isinstance(target, ast.Name) else "i"
            args = iter_node.args
            if len(args) == 1:
                end = self.visit(args[0])
                for_header = f"int {var} = 0; {var} < {end}; ++{var}"
            elif len(args) == 2:
                s, e = self.visit(args[0]), self.visit(args[1])
                for_header = f"int {var} = {s}; {var} < {e}; ++{var}"
            else:
                self.errors.append("range() in dict comprehension requires 1-2 args")
                return "0"
            return "\n".join([
                "([&]() {",
                f"    auto _kfn = [&](int {var}) {{ return {key_str}; }};",
                f"    auto _vfn = [&](int {var}) {{ return {val_str}; }};",
                "    using _K = std::decay_t<decltype(_kfn(0))>;",
                "    using _V = std::decay_t<decltype(_vfn(0))>;",
                "    std::map<_K, _V> _r;",
                f"    for ({for_header}) {{",
                assign_line,
                "    }",
                "    return _r;",
                "}())",
            ])

        # ── dict.items() with (k, v) target ──────────────────────────────────
        if (
            isinstance(iter_node, ast.Call)
            and isinstance(iter_node.func, ast.Attribute)
            and iter_node.func.attr == "items"
            and isinstance(target, ast.Tuple)
            and len(target.elts) == 2
            and all(isinstance(e, ast.Name) for e in target.elts)
        ):
            k, v = target.elts[0].id, target.elts[1].id  # type: ignore[union-attr]
            container = self.visit(iter_node.func.value)
            if self.cpp_std.supports_structured_bindings():
                for_line = f"    for (auto& [{k}, {v}] : {container}) {{"
                unpack = ""
            else:
                for_line = f"    for (auto& _kv : {container}) {{"
                unpack = f"        auto& {k} = _kv.first; auto& {v} = _kv.second;\n"
            return "\n".join([
                "([&]() {",
                f"    auto _kfn = [&](auto& {k}, auto& {v}) {{ return {key_str}; }};",
                f"    auto _vfn = [&](auto& {k}, auto& {v}) {{ return {val_str}; }};",
                f"    using _K = std::decay_t<decltype(_kfn({container}.begin()->first, {container}.begin()->second))>;",
                f"    using _V = std::decay_t<decltype(_vfn({container}.begin()->first, {container}.begin()->second))>;",
                "    std::map<_K, _V> _r;",
                for_line + ("\n" + unpack.rstrip() if unpack else ""),
                assign_line,
                "    }",
                "    return _r;",
                "}())",
            ])

        # ── generic ───────────────────────────────────────────────────────────
        if isinstance(target, ast.Name):
            var = target.id
            iterable = self.visit(iter_node)
            return "\n".join([
                "([&]() {",
                f"    auto _kfn = [&](auto& {var}) {{ return {key_str}; }};",
                f"    auto _vfn = [&](auto& {var}) {{ return {val_str}; }};",
                f"    using _K = std::decay_t<decltype(_kfn(*{iterable}.begin()))>;",
                f"    using _V = std::decay_t<decltype(_vfn(*{iterable}.begin()))>;",
                "    std::map<_K, _V> _r;",
                f"    for (auto& {var} : {iterable}) {{",
                assign_line,
                "    }",
                "    return _r;",
                "}())",
            ])

        self.errors.append("Unsupported dict comprehension target")
        return "0"

    def visit_BinOp(self, node: ast.BinOp) -> str:
        """Translate binary operations: +, -, *, /, etc."""
        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return f"({left} + {right})"
        elif isinstance(node.op, ast.Sub):
            return f"({left} - {right})"
        elif isinstance(node.op, ast.Mult):
            return f"({left} * {right})"
        elif isinstance(node.op, ast.Div):
            return f"({left} / {right})"
        elif isinstance(node.op, ast.Mod):
            return f"({left} % {right})"
        elif isinstance(node.op, ast.Pow):
            return f"std::pow({left}, {right})"
        elif isinstance(node.op, ast.FloorDiv):
            return f"({left} / {right})"
        elif isinstance(node.op, ast.BitOr):
            return f"({left} | {right})"
        elif isinstance(node.op, ast.BitAnd):
            return f"({left} & {right})"
        elif isinstance(node.op, ast.BitXor):
            return f"({left} ^ {right})"
        elif isinstance(node.op, ast.LShift):
            return f"({left} << {right})"
        elif isinstance(node.op, ast.RShift):
            return f"({left} >> {right})"
        else:
            self.errors.append(f"Unsupported binary operator: {node.op}")
            return "0"

    def visit_Compare(self, node: ast.Compare) -> str:
        """Translate comparisons: <, >, ==, etc."""
        left = self.visit(node.left)
        comparisons = []

        for op, comp in zip(node.ops, node.comparators):
            right = self.visit(comp)

            if isinstance(op, ast.Lt):
                comparisons.append(f"({left} < {right})")
            elif isinstance(op, ast.Gt):
                comparisons.append(f"({left} > {right})")
            elif isinstance(op, ast.Eq):
                comparisons.append(f"({left} == {right})")
            elif isinstance(op, ast.NotEq):
                comparisons.append(f"({left} != {right})")
            elif isinstance(op, ast.LtE):
                comparisons.append(f"({left} <= {right})")
            elif isinstance(op, ast.GtE):
                comparisons.append(f"({left} >= {right})")
            elif isinstance(op, ast.In):
                comparisons.append(f"(({right}).count({left}) > 0)")
            elif isinstance(op, ast.NotIn):
                comparisons.append(f"(({right}).count({left}) == 0)")
            elif isinstance(op, ast.Is):
                # `x is None` → `x == nullptr`; identity check otherwise → ==
                comparisons.append(f"({left} == {right})")
            elif isinstance(op, ast.IsNot):
                # `x is not None` → `x != nullptr`
                comparisons.append(f"({left} != {right})")
            else:
                self.errors.append(f"Unsupported comparison: {op}")

            left = right

        return " && ".join(comparisons)

    def visit_Call(self, node: ast.Call) -> str:
        """Translate function calls (positional and keyword arguments)."""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id

            # frozenset({x, y}) → set_t{x, y};  frozenset() → set_t{}
            # Must be checked before generic arg-visiting (inner Set literal has no visitor).
            if func_name == "frozenset":
                self.uses_frozenset = True
                if node.args and isinstance(node.args[0], ast.Set):
                    elems = [self.visit(e) for e in node.args[0].elts]
                    return f"set_t{{{', '.join(elems)}}}" if elems else "set_t{}"
                return "set_t{}"

            # min_hood/max_hood with a single Tuple arg → std::make_tuple(...)
            # Avoids the C++ comma-expression pitfall: (a, b) evaluates to b.
            # Note: callers that use a component of the result still need
            # std::get<N>(tup) manually — that extraction cannot be automated
            # without type inference.
            if func_name in ("min_hood", "max_hood") and len(node.args) == 1:
                if isinstance(node.args[0], ast.Tuple):
                    elems = [self.visit(e) for e in node.args[0].elts]
                    if func_name not in self.used_primitives:
                        self.used_primitives.append(func_name)
                    return f"{func_name}(CALL, std::make_tuple({', '.join(elems)}))"

            args = [self.visit(arg) for arg in node.args]
            # keyword args: emit values positionally (keyword names are discarded)
            args += [self.visit(kw.value)
                     for kw in node.keywords if kw.arg is not None]

            if func_name in _FCPP_PRIMITIVES:
                if func_name not in self.used_primitives:
                    self.used_primitives.append(func_name)
                if args:
                    return f"{func_name}(CALL, {', '.join(args)})"
                return f"{func_name}(CALL)"

            if func_name == "self_uid":
                # self_uid() → node.uid (direct field access; no CALL counter)
                return "node.uid"

            if func_name == "max":
                return f"std::max({', '.join(args)})"
            elif func_name == "min":
                return f"std::min({', '.join(args)})"
            elif func_name == "sum":
                return f"std::accumulate({args[0]}.begin(), {args[0]}.end(), 0)"
            elif func_name == "len":
                return f"({args[0]}).size()"
            elif func_name == "abs":
                return f"std::abs({args[0]})"
            elif func_name == "float":
                return f"static_cast<double>({args[0]})"
            elif func_name == "int":
                return f"static_cast<int>({args[0]})"
            elif func_name == "bool":
                return f"static_cast<bool>({args[0]})"
            elif func_name == "dict":
                # dict(x) → x  (C++ copy semantics; dict() → empty initializer)
                return args[0] if args else "{}"
            elif func_name == "set":
                # set(d.keys()) / set(d.values()) → typed std::set directly
                if node.args and isinstance(node.args[0], ast.Call):
                    inner = node.args[0]
                    if (
                        isinstance(inner.func, ast.Attribute)
                        and inner.func.attr in ("keys", "values")
                        and not inner.args
                    ):
                        self.uses_frozenset = True  # ensures <set> is included
                        container = self.visit(inner.func.value)
                        obj_name = (inner.func.value.id
                                    if isinstance(inner.func.value, ast.Name) else None)
                        kv = self.dict_type_env.get(obj_name) if obj_name else None
                        sb = self.cpp_std.supports_structured_bindings()
                        if inner.func.attr == "keys":
                            k_type = kv[0] if kv else f"decltype({container}.begin()->first)"
                            loop = (
                                f"for (auto& [_k, _v] : {container}) _r.insert(_k);"
                                if sb else
                                f"for (auto& _kv : {container}) _r.insert(_kv.first);"
                            )
                            return (
                                f"([&]() {{ std::set<{k_type}> _r; "
                                f"{loop} return _r; }}())"
                            )
                        else:  # values
                            v_type = kv[1] if kv else f"decltype({container}.begin()->second)"
                            loop = (
                                f"for (auto& [_k, _v] : {container}) _r.insert(_v);"
                                if sb else
                                f"for (auto& _kv : {container}) _r.insert(_kv.second);"
                            )
                            return (
                                f"([&]() {{ std::set<{v_type}> _r; "
                                f"{loop} return _r; }}())"
                            )
                # set(iterable) → set_t from iterator range; set() → empty set_t
                self.uses_frozenset = True  # set_t alias needed
                if args:
                    return f"set_t({args[0]}.begin(), {args[0]}.end())"
                return "set_t{}"
            elif func_name == "list":
                # list(iterable) → std::vector from iterator range; list() → {}
                if args:
                    return f"std::vector<decltype(*{args[0]}.begin())>({args[0]}.begin(), {args[0]}.end())"
                return "{}"
            else:
                return f"{func_name}({', '.join(args)})"

        if isinstance(node.func, ast.Attribute):
            obj = self.visit(node.func.value)
            method = node.func.attr
            args = [self.visit(arg) for arg in node.args]
            args += [self.visit(kw.value)
                     for kw in node.keywords if kw.arg is not None]

            # dict.keys() / dict.values() in expression context (not for-loop)
            if method in ("keys", "values") and not args:
                obj_name = (node.func.value.id
                            if isinstance(node.func.value, ast.Name) else None)
                kv = self.dict_type_env.get(obj_name) if obj_name else None
                sb = self.cpp_std.supports_structured_bindings()
                if method == "keys":
                    if self.cpp_std.supports_ranges():
                        self.uses_ranges_header = True
                        return f"std::views::keys({obj})"
                    elem_type = kv[0] if kv else f"decltype({obj}.begin()->first)"
                    loop = (f"for (auto& [_k, _v] : {obj}) _r.push_back(_k);"
                            if sb else
                            f"for (auto& _kv : {obj}) _r.push_back(_kv.first);")
                    return (
                        f"([&]() {{ std::vector<{elem_type}> _r; "
                        f"_r.reserve({obj}.size()); {loop} return _r; }}())"
                    )
                else:  # values
                    if self.cpp_std.supports_ranges():
                        self.uses_ranges_header = True
                        return f"std::views::values({obj})"
                    elem_type = kv[1] if kv else f"decltype({obj}.begin()->second)"
                    loop = (f"for (auto& [_k, _v] : {obj}) _r.push_back(_v);"
                            if sb else
                            f"for (auto& _kv : {obj}) _r.push_back(_kv.second);")
                    return (
                        f"([&]() {{ std::vector<{elem_type}> _r; "
                        f"_r.reserve({obj}.size()); {loop} return _r; }}())"
                    )

            # dict.get(key) / dict.get(key, default) → find/at pattern
            if method == "get" and len(args) >= 1:
                key = args[0]
                if len(args) == 1:
                    # dict.get(key) → value if present else value-initialised
                    return f"({obj}.count({key}) ? {obj}.at({key}) : decltype({obj}.begin()->second){{}})"
                default = args[1]
                return f"({obj}.count({key}) ? {obj}.at({key}) : {default})"

            return f"{obj}.{method}({', '.join(args)})"

        return "0"

    def visit_Constant(self, node: ast.Constant) -> str:
        """Translate constants: numbers, strings, booleans."""
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        if isinstance(node.value, (int, float)):
            return str(node.value)
        elif isinstance(node.value, str):
            escaped = node.value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        elif node.value is None:
            return "nullptr"
        return str(node.value)

    def visit_Name(self, node: ast.Name) -> str:
        """Translate variable names."""
        return node.id

    def _resolve_dotted_chain(self, node: ast.Attribute):
        """Walk an Attribute chain and resolve it against self.constants.

        Returns the resolved Python value if the full chain resolves, else None.
        Only the root name is looked up in self.constants; subsequent attrs are
        resolved via getattr().  Useful for folding IntEnum member values to
        integer literals so that C++ case labels remain compile-time constants.
        """
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(current.id)
        parts.reverse()  # [root, attr1, attr2, ...]

        root = parts[0]
        if root not in self.constants:
            return None
        obj = self.constants[root]
        try:
            for attr in parts[1:]:
                obj = getattr(obj, attr)
        except AttributeError:
            return None
        return obj

    def visit_Attribute(self, node: ast.Attribute) -> str:
        """Translate attribute access: obj.attr.

        When a constants dict is available, attempts to resolve the full dotted
        chain (e.g. ``WorkerRole.RECEIVER.value``) to its numeric literal value.
        This is required for C++ case labels, which must be compile-time constants.
        bool is mapped to 1/0 rather than true/false to preserve integer type.
        """
        if self.constants:
            resolved = self._resolve_dotted_chain(node)
            if resolved is True:
                return "1"
            elif resolved is False:
                return "0"
            elif isinstance(resolved, int):
                return str(resolved)
            elif isinstance(resolved, float):
                return str(resolved)
        obj = self.visit(node.value)
        return f"{obj}.{node.attr}"

    def visit_Subscript(self, node: ast.Subscript) -> str:
        """Translate subscripts: arr[i]."""
        obj = self.visit(node.value)
        index = self.visit(node.slice)
        return f"{obj}[{index}]"

    def visit_Lambda(self, node: ast.Lambda) -> str:
        """Translate a Python lambda to a C++14 generic lambda for G&& parameters.

        ``lambda a, b: a + b``  →  ``[=](auto a, auto b) { return (a + b); }``
        """
        params = ", ".join(f"auto {arg.arg}" for arg in node.args.args)
        body = self.visit(node.body)
        _log.debug(
            "Transpiling lambda(%s) → [=](%s) { return %s; }", params, params, body)
        return f"[=]({params}) {{ return {body}; }}"

    # ── Expression nodes ──────────────────────────────────────────────────────

    def visit_IfExp(self, node: ast.IfExp) -> str:
        """Translate Python ternary `a if cond else b` → `(cond ? a : b)`."""
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        return f"({test} ? {body} : {orelse})"

    def visit_BoolOp(self, node: ast.BoolOp) -> str:
        """Translate `and`/`or` → `&&`/`||`."""
        op = "&&" if isinstance(node.op, ast.And) else "||"
        parts = [self.visit(v) for v in node.values]
        return "(" + f" {op} ".join(parts) + ")"

    def visit_UnaryOp(self, node: ast.UnaryOp) -> str:
        """Translate unary `not`/`-`/`+`/`~` → C++ `!`/`-`/`+`/`~`."""
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return f"(!{operand})"
        elif isinstance(node.op, ast.USub):
            return f"(-{operand})"
        elif isinstance(node.op, ast.UAdd):
            return f"(+{operand})"
        elif isinstance(node.op, ast.Invert):
            return f"(~{operand})"
        else:
            self.errors.append(
                f"Unsupported unary operator: {type(node.op).__name__}")
            return "0"

    def visit_List(self, node: ast.List) -> str:
        """Translate Python list literal `[a, b]` → `{a, b}`."""
        elements = [self.visit(e) for e in node.elts]
        return "{" + ", ".join(elements) + "}"

    def visit_Set(self, node: ast.Set) -> str:
        """Translate Python set literal `{a, b}` → `set_t{a, b}`."""
        self.uses_frozenset = True
        elements = [self.visit(e) for e in node.elts]
        return f"set_t{{{', '.join(elements)}}}"

    def visit_Tuple(self, node: ast.Tuple) -> str:
        """Translate Python tuple `(a, b)` → `{a, b}` (struct-init style)."""
        elements = [self.visit(e) for e in node.elts]
        return "{" + ", ".join(elements) + "}"

    # ── Statement nodes ───────────────────────────────────────────────────────

    def visit_Expr(self, node: ast.Expr) -> str:
        """Translate expression statement (e.g. bare function call)."""
        return f"{self.visit(node.value)};"

    def visit_Return(self, node: ast.Return) -> str:
        """Translate `return expr` → `return expr;`."""
        if node.value is None:
            return "return;"
        return f"return {self.visit(node.value)};"

    def visit_Assign(self, node: ast.Assign) -> str:
        """Translate `x = expr` → `auto x = expr;` (first use) or `x = expr;`."""
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = self.visit(node.value)
            if name not in self.declared_vars:
                self.declared_vars.add(name)
                return f"auto {name} = {value};"
            return f"{name} = {value};"
        self.errors.append(
            f"Unsupported assignment target: {ast.dump(node.targets[0])}")
        return ""

    def visit_AnnAssign(self, node: ast.AnnAssign) -> str:
        """Translate annotated assignment `x: T = expr` → `auto x = expr;`.

        Also records Dict[K, V] annotations in dict_type_env so that
        subsequent dict.keys()/values() calls can emit concrete C++ types.
        """
        # Track Dict[K, V] annotations (even for bare `x: Dict[K, V]` without value)
        if isinstance(node.target, ast.Name) and isinstance(node.annotation, ast.Subscript):
            kv = self._annotation_to_dict_types(node.annotation)
            if kv is not None:
                self.dict_type_env[node.target.id] = kv

        if node.value is None:
            return ""
        if not isinstance(node.target, ast.Name):
            self.errors.append("Unsupported annotated assignment target")
            return ""
        name = node.target.id
        value = self.visit(node.value)
        if name not in self.declared_vars:
            self.declared_vars.add(name)
            return f"auto {name} = {value};"
        return f"{name} = {value};"

    def visit_AugAssign(self, node: ast.AugAssign) -> str:
        """Translate `x += y` → `x += y;`."""
        target = self.visit(node.target)
        value = self.visit(node.value)
        _ops = {
            ast.Add: "+=", ast.Sub: "-=", ast.Mult: "*=",
            ast.Div: "/=", ast.Mod: "%=",
            ast.BitOr: "|=", ast.BitAnd: "&=", ast.BitXor: "^=",
            ast.LShift: "<<=", ast.RShift: ">>=",
            ast.FloorDiv: "/=",  # C++ integer division
        }
        op_str = _ops.get(type(node.op), "+=")
        return f"{target} {op_str} {value};"

    def visit_If(self, node: ast.If) -> str:
        """Translate if/elif/else to C++ if/else if/else."""
        test = self.visit(node.test)
        body = self.transpile_statements(node.body)
        result = f"if ({test}) {{\n{body}\n}}"
        if node.orelse:
            if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
                # elif chain
                inner = self.visit(node.orelse[0])
                result += f" else {inner}"
            else:
                orelse = self.transpile_statements(node.orelse)
                result += f" else {{\n{orelse}\n}}"
        return result

    def visit_While(self, node: ast.While) -> str:
        """Translate `while cond: ...` → C++ `while (cond) { ... }`."""
        test = self.visit(node.test)
        body = self.transpile_statements(node.body)
        return f"while ({test}) {{\n{body}\n}}"

    def visit_For(self, node: ast.For) -> str:
        """Translate Python for loops to C++ equivalents.

        Supported forms:
        - ``for i in range(...)``      → C-style ``for (int i = ...)``
        - ``for (k, v) in x.items():`` → structured binding (C++17+) or
                                          ``.first``/``.second`` (C++14)
        - ``for k in x.keys():``       → structured binding or ``.first``
        - ``for x in container:``      → ``for (auto& x : container)``
        """
        body = self.transpile_statements(node.body)
        sb = self.cpp_std.supports_structured_bindings()

        # ── range() → classic C for loop ─────────────────────────────────────
        if (
            isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "range"
        ):
            var = node.target.id if isinstance(node.target, ast.Name) else "i"
            args = node.iter.args
            if len(args) == 1:
                end = self.visit(args[0])
                header = f"int {var} = 0; {var} < {end}; ++{var}"
            elif len(args) == 2:
                start, end = self.visit(args[0]), self.visit(args[1])
                header = f"int {var} = {start}; {var} < {end}; ++{var}"
            elif len(args) == 3:
                start, end, step = (self.visit(a) for a in args)
                header = f"int {var} = {start}; {var} < {end}; {var} += {step}"
            else:
                self.errors.append("range() requires 1-3 arguments")
                return ""
            return f"for ({header}) {{\n{body}\n}}"

        # ── dict.items() with 2-tuple target ─────────────────────────────────
        if (
            isinstance(node.target, ast.Tuple)
            and len(node.target.elts) == 2
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "items"
        ):
            t0, t1 = node.target.elts[0], node.target.elts[1]
            container = self.visit(node.iter.func.value)

            # nested tuple unpacking: for (k1, k2), v in d.items()
            if isinstance(t0, ast.Tuple) and isinstance(t1, ast.Name):
                v = t1.id
                inner_names = [
                    e.id for e in t0.elts if isinstance(e, ast.Name)
                ]
                self.declared_vars.update(inner_names)
                self.declared_vars.add(v)
                if sb:
                    # C++17: double structured binding
                    inner_bind = ", ".join(inner_names)
                    unpacked_body = f"    auto& [{inner_bind}] = _kvkey;\n{body}"
                    return (
                        f"for (auto& [_kvkey, {v}] : {container}) {{\n"
                        f"{unpacked_body}\n}}"
                    )
                else:
                    # C++14: std::get<> on first element (key must be pair/tuple)
                    get_lines = "\n".join(
                        f"    auto& {n} = std::get<{i}>(_kv.first);"
                        for i, n in enumerate(inner_names)
                    )
                    return (
                        f"for (auto& _kv : {container}) {{\n"
                        f"    auto& {v} = _kv.second;\n"
                        f"{get_lines}\n"
                        f"{body}\n}}"
                    )

            # flat 2-tuple: for k, v in d.items()
            if isinstance(t0, ast.Name) and isinstance(t1, ast.Name):
                k, v = t0.id, t1.id
                self.declared_vars.add(k)
                self.declared_vars.add(v)
                if sb:
                    return f"for (auto& [{k}, {v}] : {container}) {{\n{body}\n}}"
                else:
                    return (
                        f"for (auto& _kv : {container}) {{\n"
                        f"    auto& {k} = _kv.first;\n"
                        f"    auto& {v} = _kv.second;\n"
                        f"{body}\n}}"
                    )

        # ── dict.keys() ───────────────────────────────────────────────────────
        if (
            isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "keys"
        ):
            var = node.target.id
            container = self.visit(node.iter.func.value)
            self.declared_vars.add(var)
            if sb:
                return f"for (auto& [{var}, _kv_{var}] : {container}) {{\n{body}\n}}"
            return (
                f"for (auto& _kv : {container}) {{\n"
                f"    auto& {var} = _kv.first;\n"
                f"{body}\n}}"
            )

        # ── dict.values() ─────────────────────────────────────────────────────
        if (
            isinstance(node.target, ast.Name)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Attribute)
            and node.iter.func.attr == "values"
        ):
            var = node.target.id
            container = self.visit(node.iter.func.value)
            self.declared_vars.add(var)
            if sb:
                return f"for (auto& [_kv_{var}, {var}] : {container}) {{\n{body}\n}}"
            return (
                f"for (auto& _kv : {container}) {{\n"
                f"    auto& {var} = _kv.second;\n"
                f"{body}\n}}"
            )

        # ── generic range-based for ───────────────────────────────────────────
        if isinstance(node.target, ast.Name):
            var = node.target.id
            iterable = self.visit(node.iter)
            self.declared_vars.add(var)
            return f"for (auto& {var} : {iterable}) {{\n{body}\n}}"

        self.errors.append(
            "Unsupported for-loop pattern (tuple target without .items())")
        return ""

    def visit_Match(self, node: ast.Match) -> str:
        """Translate Python ``match/case`` (3.10+) → C++ ``switch``.

        Supported patterns:
        - ``case X:``          — value pattern → ``case X:``
        - ``case _:``          — wildcard     → ``default:``
        - ``case X | Y:``      — OR pattern   → ``case X: case Y:`` (C++ fallthrough labels)
        - ``case X if cond:``  — guard clause → ``case X: if (cond) { ... }``

        Guard clauses wrap the case body in an ``if`` block; the ``break`` still
        follows so unmatched guards fall out of the switch rather than falling
        through.  This mirrors C++17 ``[[fallthrough]]`` avoidance and keeps
        the generated code compatible with C++14.
        """
        subject = self.visit(node.subject)
        cases_cpp: List[str] = []
        for case in node.cases:
            body = self.transpile_statements(case.body)
            pattern = case.pattern

            # Guard clause: `case X if cond:` → wrap body in `if (cond) { ... }`
            if case.guard is not None:
                guard_cpp = self.visit(case.guard)
                body = f"if ({guard_cpp}) {{\n{body}\n    }}"

            if (
                isinstance(pattern, ast.MatchAs)
                and pattern.name is None
                and pattern.pattern is None
            ):
                # wildcard `case _:` → default
                cases_cpp.append(f"default:\n{body}\n    break;")
            elif isinstance(pattern, ast.MatchValue):
                val = self.visit(pattern.value)
                cases_cpp.append(f"case {val}:\n{body}\n    break;")
            elif isinstance(pattern, ast.MatchOr):
                # OR pattern `case A | B | C:` → `case A: case B: case C:` (shared body)
                labels: List[str] = []
                for sub in pattern.patterns:
                    if isinstance(sub, ast.MatchValue):
                        labels.append(f"case {self.visit(sub.value)}:")
                    else:
                        self.errors.append(
                            f"Unsupported OR sub-pattern: {type(sub).__name__}"
                        )
                if labels:
                    cases_cpp.append(
                        "\n".join(labels) + f"\n{body}\n    break;"
                    )
            else:
                self.errors.append(
                    f"Unsupported match pattern: {type(pattern).__name__}"
                )
        if not any(c.startswith("default") for c in cases_cpp):
            cases_cpp.append("default: break;")
        inner = "\n".join(cases_cpp)
        return f"switch ({subject}) {{\n{inner}\n}}"

    def visit_ListComp(self, node: ast.ListComp) -> str:
        """Translate ``[expr for var in iter if cond]`` → IIFE returning std::vector."""
        if len(node.generators) != 1:
            self.errors.append("Only single-generator list comprehensions are supported")
            return "0"
        gen = node.generators[0]
        if gen.is_async:
            self.errors.append("Async comprehensions are not supported")
            return "0"
        expr_str = self.visit(node.elt)
        return self._make_comprehension_iife(
            gen.target, gen.iter, gen.ifs, expr_str,
            result_container="std::vector", insert_method="push_back",
        )

    def visit_SetComp(self, node: ast.SetComp) -> str:
        """Translate ``{expr for var in iter if cond}`` → IIFE returning std::set."""
        if len(node.generators) != 1:
            self.errors.append("Only single-generator set comprehensions are supported")
            return "0"
        gen = node.generators[0]
        if gen.is_async:
            self.errors.append("Async comprehensions are not supported")
            return "0"
        self.uses_frozenset = True  # ensures <set> include
        expr_str = self.visit(node.elt)
        return self._make_comprehension_iife(
            gen.target, gen.iter, gen.ifs, expr_str,
            result_container="std::set", insert_method="insert",
        )

    def visit_DictComp(self, node: ast.DictComp) -> str:
        """Translate ``{k: v for var in iter if cond}`` → IIFE returning std::map."""
        if len(node.generators) != 1:
            self.errors.append("Only single-generator dict comprehensions are supported")
            return "0"
        gen = node.generators[0]
        if gen.is_async:
            self.errors.append("Async comprehensions are not supported")
            return "0"
        key_str = self.visit(node.key)
        val_str = self.visit(node.value)
        return self._make_dict_comprehension_iife(
            gen.target, gen.iter, gen.ifs, key_str, val_str,
        )

    def visit_Pass(self, node: ast.Pass) -> str:
        """Translate `pass` → empty (C++ needs no statement)."""
        return ""

    def visit_Break(self, node: ast.Break) -> str:
        """Translate `break` → `break;`."""
        return "break;"

    def visit_Continue(self, node: ast.Continue) -> str:
        """Translate `continue` → `continue;`."""
        return "continue;"

    # ── Statement list helper ─────────────────────────────────────────────────

    def transpile_statements(self, stmts: list, indent: int = 4) -> str:
        """Transpile a list of AST statement nodes into indented C++ lines."""
        indent_str = " " * indent
        lines: List[str] = []
        for stmt in stmts:
            code = self.visit(stmt)
            if not code:
                continue
            for line in code.split("\n"):
                lines.append(f"{indent_str}{line}")
        return "\n".join(lines)

    # ── Fallback ──────────────────────────────────────────────────────────────

    def generic_visit(self, node: ast.AST) -> str:
        """Fallback for unsupported nodes."""
        self.errors.append(f"Unsupported AST node: {type(node).__name__}")
        return "0"
