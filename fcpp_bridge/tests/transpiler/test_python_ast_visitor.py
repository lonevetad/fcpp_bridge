"""Tests for PythonAstVisitor — all operator, control-flow, and FCPP primitive handling."""

import ast
import inspect
import textwrap
import pytest
from enum import IntEnum
from fcpp_bridge.transpiler import PythonAstVisitor, _FCPP_PRIMITIVES


# Module-level test enum used by constant-folding tests.
class _TestRole(IntEnum):
    UNASSIGNED = 0
    RECEIVER = 1
    SENSOR = 2


def _v(expr_str: str) -> str:
    """Parse expr_str and visit with PythonAstVisitor."""
    v = PythonAstVisitor()
    return v.visit(ast.parse(expr_str).body[0].value)


def _ve(src: str) -> str:
    """Parse src as an eval-mode expression."""
    tree = ast.parse(src, mode="eval")
    return PythonAstVisitor().visit(tree.body)


def _stmt(src: str) -> str:
    """Parse a single statement and return its C++ equivalent."""
    v = PythonAstVisitor()
    return v.visit(ast.parse(src).body[0])


def _body(fn) -> str:
    """Transpile the full body of a zero-argument function to C++."""
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
    func_def = tree.body[0]
    stmts = func_def.body
    # skip docstring
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]
    v = PythonAstVisitor()
    return v.transpile_statements(stmts)


def _body_with_consts(fn, constants: dict) -> str:
    """Transpile the full body of fn using a PythonAstVisitor with constants."""
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
    func_def = tree.body[0]
    stmts = func_def.body
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
        and isinstance(stmts[0].value.value, str)
    ):
        stmts = stmts[1:]
    v = PythonAstVisitor(constants=constants)
    return v.transpile_statements(stmts)


# ============================================================================
# Test 3: AST visitor — built-ins and constants
# ============================================================================


def test_ast_visitor_binary_ops():
    v = PythonAstVisitor()
    node = ast.parse("a + b").body[0].value
    result = v.visit(node)
    assert "+" in result and "a" in result and "b" in result

    node = ast.parse("x * y").body[0].value
    result = v.visit(node)
    assert "*" in result


def test_ast_visitor_function_calls():
    v = PythonAstVisitor()
    assert "std::max" in v.visit(ast.parse("max(a, b)").body[0].value)
    assert "std::min" in v.visit(ast.parse("min(x, y)").body[0].value)


def test_ast_visitor_self_uid():
    """self_uid() → node.uid (no CALL counter)."""
    v = PythonAstVisitor()
    result = v.visit(ast.parse("self_uid()").body[0].value)
    assert result == "node.uid"
    assert "CALL" not in result
    assert "self_uid" not in result


def test_ast_visitor_constants():
    v = PythonAstVisitor()
    assert "42" in v.visit(ast.parse("42").body[0].value)
    assert "3.14" in v.visit(ast.parse("3.14").body[0].value)


# ============================================================================
# Test 5: Arithmetic operators
# ============================================================================


def test_ast_visitor_subtraction():
    result = _v("a - b")
    assert "-" in result and "a" in result and "b" in result


def test_ast_visitor_multiplication():
    assert "*" in _v("a * b")


def test_ast_visitor_division():
    assert "/" in _v("x / y")


def test_ast_visitor_modulo():
    assert "%" in _v("x % 3")


def test_ast_visitor_power():
    assert "std::pow" in _v("x ** 2")


def test_ast_visitor_floor_div():
    assert _v("x // 2") == "(x / 2)"


def test_ast_visitor_bitwise_or():
    assert _v("a | b") == "(a | b)"


def test_ast_visitor_bitwise_and():
    assert _v("a & b") == "(a & b)"


def test_ast_visitor_bitwise_xor():
    assert _v("a ^ b") == "(a ^ b)"


def test_ast_visitor_lshift():
    assert _v("x << 2") == "(x << 2)"


def test_ast_visitor_rshift():
    assert _v("x >> 1") == "(x >> 1)"


def test_ast_visitor_set_union_via_bitwise_or():
    """set_t union: s | {x} → (s | set_t{x})"""
    result = _v("s | frozenset({x})")
    assert "|" in result
    assert "set_t" in result


# ============================================================================
# Test 6: Comparison operators
# ============================================================================


def test_ast_visitor_less_than():
    assert "<" in _v("a < b")


def test_ast_visitor_greater_than():
    assert ">" in _v("a > b")


def test_ast_visitor_equal():
    assert "==" in _v("a == b")


def test_ast_visitor_not_equal():
    assert "!=" in _v("a != b")


def test_ast_visitor_less_equal():
    assert "<=" in _v("a <= b")


def test_ast_visitor_greater_equal():
    assert ">=" in _v("a >= b")


def test_ast_visitor_in_operator():
    result = _v("x in container")
    assert "container" in result
    assert ".count(x)" in result
    assert "> 0" in result


def test_ast_visitor_not_in_operator():
    result = _v("x not in container")
    assert "container" in result
    assert ".count(x)" in result
    assert "== 0" in result


def test_ast_visitor_in_operator_key_in_map():
    result = _v("key in local_db")
    assert "local_db.count(key) > 0" in result or "(local_db).count(key) > 0" in result


# ============================================================================
# Test 7: Miscellaneous nodes
# ============================================================================


def test_ast_visitor_string_constant():
    assert '"hello"' in _v('"hello"')


def test_ast_visitor_none_constant():
    assert _v("None") == "nullptr"


def test_ast_visitor_bool_constants():
    assert _v("True") == "true"
    assert _v("False") == "false"


def test_ast_visitor_attribute_access():
    assert "obj.attr" in _v("obj.attr")


def test_ast_visitor_subscript():
    assert "arr[0]" in _v("arr[0]")


def test_ast_visitor_len_call():
    assert "size()" in _v("len(arr)")


def test_ast_visitor_sum_call():
    assert "accumulate" in _v("sum(arr)")


def test_ast_visitor_unknown_call():
    assert "custom_fn" in _v("custom_fn(x, y)")


def test_ast_visitor_variable_name():
    v = PythonAstVisitor()
    node = ast.parse("my_var").body[0].value
    assert v.visit(node) == "my_var"


# ============================================================================
# Test 11: FCPP primitives inject CALL
# ============================================================================


def test_ast_visitor_nbr_injects_call():
    assert _v("nbr(x)") == "nbr(CALL, x)"


def test_ast_visitor_old_injects_call():
    assert _v("old(s)") == "old(CALL, s)"


def test_ast_visitor_min_hood_injects_call():
    assert _v("min_hood(x)") == "min_hood(CALL, x)"


def test_ast_visitor_max_hood_injects_call():
    assert _v("max_hood(x)") == "max_hood(CALL, x)"


def test_ast_visitor_count_hood_no_args():
    assert _v("count_hood()") == "count_hood(CALL)"


def test_ast_visitor_fold_hood_two_args():
    assert "fold_hood(CALL," in _v("fold_hood(f, init)")


def test_ast_visitor_broadcast_two_args():
    assert _v("broadcast(dist, val)") == "broadcast(CALL, dist, val)"


def test_ast_visitor_gossip_two_args():
    assert _v("gossip(v, acc)") == "gossip(CALL, v, acc)"


def test_ast_visitor_abf_distance_injects_call():
    assert _v("abf_distance(src)") == "abf_distance(CALL, src)"


def test_ast_visitor_bis_distance_injects_call():
    assert _v("bis_distance(src, p, s)") == "bis_distance(CALL, src, p, s)"


def test_ast_visitor_sp_collection_injects_call():
    assert _v("sp_collection(d, v, n, acc)") == "sp_collection(CALL, d, v, n, acc)"


def test_ast_visitor_mp_collection_injects_call():
    assert _v(
        "mp_collection(d, v, n, acc, div)") == "mp_collection(CALL, d, v, n, acc, div)"


def test_ast_visitor_wmp_collection_injects_call():
    assert _v(
        "wmp_collection(d, r, v, acc, mul)") == "wmp_collection(CALL, d, r, v, acc, mul)"


def test_ast_visitor_rectangle_walk_injects_call():
    assert _v(
        "rectangle_walk(lo, hi, mv, p)") == "rectangle_walk(CALL, lo, hi, mv, p)"


def test_ast_visitor_follow_target_injects_call():
    assert _v("follow_target(tgt, mv, p)") == "follow_target(CALL, tgt, mv, p)"


def test_ast_visitor_spawn_injects_call():
    assert _v("spawn(f, keys)") == "spawn(CALL, f, keys)"


def test_ast_visitor_tracks_used_primitives():
    v = PythonAstVisitor()
    v.visit(ast.parse("nbr(x)").body[0].value)
    v.visit(ast.parse("min_hood(y)").body[0].value)
    assert "nbr" in v.used_primitives
    assert "min_hood" in v.used_primitives


# ============================================================================
# Test 12: New FCPP primitives inject CALL — grouped by header
# ============================================================================


def test_nbr_uid_injects_call():
    assert _v("nbr_uid()") == "nbr_uid(CALL)"


def test_oldnbr_injects_call():
    assert _v("oldnbr(x, op)") == "oldnbr(CALL, x, op)"


def test_align_injects_call():
    assert _v("align(x)") == "align(CALL, x)"


def test_align_inplace_injects_call():
    assert _v("align_inplace(x)") == "align_inplace(CALL, x)"


def test_sum_hood_injects_call():
    assert _v("sum_hood(x)") == "sum_hood(CALL, x)"


def test_mean_hood_injects_call():
    assert _v("mean_hood(x)") == "mean_hood(CALL, x)"


def test_all_hood_injects_call():
    assert _v("all_hood(x)") == "all_hood(CALL, x)"


def test_any_hood_injects_call():
    assert _v("any_hood(x)") == "any_hood(CALL, x)"


def test_list_hood_injects_call():
    assert "list_hood(CALL," in _v("list_hood(c, x)")


def test_abf_hops_injects_call():
    assert _v("abf_hops(s)") == "abf_hops(CALL, s)"


def test_flex_distance_injects_call():
    assert "flex_distance(CALL," in _v("flex_distance(s, e, r, d, f)")


def test_bis_ksource_broadcast_injects_call():
    assert "bis_ksource_broadcast(CALL," in _v(
        "bis_ksource_broadcast(s, v, k, p, sp)")


def test_gossip_min_injects_call():
    assert _v("gossip_min(v)") == "gossip_min(CALL, v)"


def test_gossip_max_injects_call():
    assert _v("gossip_max(v)") == "gossip_max(CALL, v)"


def test_gossip_mean_injects_call():
    assert _v("gossip_mean(v)") == "gossip_mean(CALL, v)"


def test_list_idem_collection_injects_call():
    assert "list_idem_collection(CALL," in _v(
        "list_idem_collection(d, v, r, s, n, e, a)")


def test_list_arith_collection_injects_call():
    assert "list_arith_collection(CALL," in _v(
        "list_arith_collection(d, v, r, s, n, e, a)")


def test_follow_path_injects_call():
    assert "follow_path(CALL," in _v("follow_path(p, v, t)")


def test_follow_track_injects_call():
    assert _v("follow_track(t)") == "follow_track(CALL, t)"


def test_random_rectangle_target_injects_call():
    assert "random_rectangle_target(CALL," in _v(
        "random_rectangle_target(lo, hi)")


def test_neighbour_elastic_force_injects_call():
    assert "neighbour_elastic_force(CALL," in _v(
        "neighbour_elastic_force(l, s)")


def test_diameter_election_injects_call():
    assert "diameter_election(CALL," in _v("diameter_election(v, d)")


def test_color_election_injects_call():
    assert _v("color_election(v)") == "color_election(CALL, v)"


def test_wave_election_injects_call():
    assert _v("wave_election(v)") == "wave_election(CALL, v)"


def test_constant_injects_call():
    assert _v("constant(v)") == "constant(CALL, v)"


def test_counter_no_args_injects_call():
    assert _v("counter()") == "counter(CALL)"


def test_delay_injects_call():
    assert "delay(CALL," in _v("delay(v, n)")


def test_toggle_injects_call():
    assert "toggle(CALL," in _v("toggle(c)")


def test_shared_clock_injects_call():
    assert _v("shared_clock()") == "shared_clock(CALL)"


def test_timed_decay_injects_call():
    assert "timed_decay(CALL," in _v("timed_decay(v, n, dt)")


# ============================================================================
# Test 13: Primitive header mapping correctness
# ============================================================================


def test_all_basics_map_to_correct_header():
    for name in ("nbr", "old", "nbr_uid", "oldnbr", "align", "fold_hood", "count_hood", "spawn"):
        assert "<lib/coordination/basics.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_utils_map_to_correct_header():
    for name in ("min_hood", "max_hood", "sum_hood", "mean_hood", "all_hood", "any_hood", "list_hood"):
        assert "<lib/coordination/utils.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_spreading_map_to_correct_header():
    for name in ("broadcast", "abf_distance", "abf_hops", "bis_distance", "flex_distance", "bis_ksource_broadcast"):
        assert "<lib/coordination/spreading.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_collection_map_to_correct_header():
    for name in ("gossip", "gossip_min", "gossip_max", "gossip_mean",
                 "sp_collection", "mp_collection", "wmp_collection",
                 "list_idem_collection", "list_arith_collection"):
        assert "<lib/coordination/collection.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_geometry_map_to_correct_header():
    for name in ("follow_target", "follow_path", "rectangle_walk",
                 "neighbour_elastic_force", "point_elastic_force"):
        assert "<lib/coordination/geometry.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_election_map_to_correct_header():
    for name in ("diameter_election", "color_election", "wave_election",
                 "diameter_election_distance", "color_election_distance", "wave_election_distance"):
        assert "<lib/coordination/election.hpp>" in _FCPP_PRIMITIVES[name], name


def test_all_time_map_to_correct_header():
    for name in ("constant", "counter", "delay", "toggle", "shared_clock",
                 "timed_decay", "exponential_filter", "round_since", "time_since"):
        assert "<lib/coordination/time.hpp>" in _FCPP_PRIMITIVES[name], name


def test_fcpp_primitives_total_count():
    assert len(_FCPP_PRIMITIVES) == 64


# ============================================================================
# v0.9: visit_Lambda — G&& callable support
# ============================================================================


def test_visit_lambda_no_args():
    assert _ve("lambda: 42") == "[=]() { return 42; }"


def test_visit_lambda_one_arg():
    assert _ve("lambda x: x + 1") == "[=](auto x) { return (x + 1); }"


def test_visit_lambda_two_args():
    assert _ve(
        "lambda a, b: a + b") == "[=](auto a, auto b) { return (a + b); }"


def test_visit_lambda_nested_expression():
    cpp = _ve("lambda a, b: a * b + 1")
    assert "[=](auto a, auto b)" in cpp
    assert "return" in cpp


def test_visit_lambda_comparison():
    cpp = _ve("lambda a, b: a < b")
    assert "[=](auto a, auto b)" in cpp
    assert "a < b" in cpp


def test_fcpp_call_with_lambda_arg_fold_hood():
    src = "fold_hood(0, lambda a, b: a + b)"
    assert _ve(
        src) == "fold_hood(CALL, 0, [=](auto a, auto b) { return (a + b); })"


def test_fcpp_call_with_lambda_arg_gossip():
    src = "gossip(val, lambda a, b: a + b)"
    assert _ve(
        src) == "gossip(CALL, val, [=](auto a, auto b) { return (a + b); })"


def test_fcpp_call_with_lambda_arg_split():
    src = "split(key, lambda x: x * 2)"
    assert _ve(src) == "split(CALL, key, [=](auto x) { return (x * 2); })"


# ============================================================================
# Phase 6: expressions — ternary, bool ops, unary, keyword args
# ============================================================================


def test_ternary_expression():
    assert _ve("a if cond else b") == "(cond ? a : b)"


def test_ternary_nested():
    result = _ve("1 if x > 0 else 0")
    assert "?" in result and ":" in result


def test_bool_op_and():
    assert "&&" in _ve("a and b")


def test_bool_op_or():
    assert "||" in _ve("a or b")


def test_bool_op_chain():
    result = _ve("a and b and c")
    assert result.count("&&") == 2


def test_unary_not():
    result = _ve("not x")
    assert "!" in result and "x" in result


def test_unary_neg():
    assert "(-x)" == _ve("-x")


def test_keyword_args_in_call():
    result = _v("MyState(value=v, distance=d)")
    assert "MyState(" in result
    assert "v" in result and "d" in result


def test_list_literal():
    result = _ve("[1, 2, 3]")
    assert "{" in result and "1" in result


def test_method_call_on_object():
    result = _ve("obj.method(x, y)")
    assert "obj.method(x, y)" == result


# ============================================================================
# Phase 6: statements — assign, augassign, return, pass
# ============================================================================


def test_assign_first_use_declares_auto():
    result = _stmt("x = 42")
    assert result == "auto x = 42;"


def test_assign_second_use_no_auto():
    v = PythonAstVisitor()
    v.declared_vars.add("x")
    node = ast.parse("x = 99").body[0]
    assert v.visit(node) == "x = 99;"


def test_augassign_add():
    assert _stmt("x += 1") == "x += 1;"


def test_augassign_sub():
    assert _stmt("x -= 2") == "x -= 2;"


def test_augassign_mul():
    assert _stmt("x *= 3") == "x *= 3;"


def test_return_statement():
    assert _stmt("return x") == "return x;"


def test_return_none():
    assert _stmt("return") == "return;"


def test_pass_statement():
    assert _stmt("pass") == ""


def test_break_statement():
    assert _stmt("break") == "break;"


def test_continue_statement():
    assert _stmt("continue") == "continue;"


# ============================================================================
# Phase 6: if / elif / else
# ============================================================================


def test_if_simple():
    result = _stmt("if x > 0:\n    y = 1")
    assert "if (" in result and "x > 0" in result


def test_if_with_else():
    def fn():
        if x > 0:  # noqa: F821
            y = 1  # noqa: F821
        else:
            y = 0  # noqa: F821
    result = _body(fn)
    assert "if (" in result
    assert "} else {" in result


def test_if_elif_else():
    def fn():
        if a == 1:  # noqa: F821
            x = 10  # noqa: F821
        elif a == 2:  # noqa: F821
            x = 20  # noqa: F821
        else:
            x = 0  # noqa: F821
    result = _body(fn)
    assert "if (" in result
    assert "else if (" in result
    assert "} else {" in result


def test_if_early_return():
    def fn():
        if not values:  # noqa: F821
            return s  # noqa: F821
        return s + 1  # noqa: F821
    result = _body(fn)
    assert "if (" in result
    assert result.count("return") == 2


# ============================================================================
# Phase 6: while loop
# ============================================================================


def test_while_loop():
    def fn():
        while i < 10:  # noqa: F821
            i += 1  # noqa: F821
    result = _body(fn)
    assert "while (" in result
    assert "i < 10" in result
    assert "i += 1" in result


def test_while_with_break():
    def fn():
        while True:  # noqa: F821
            if done:  # noqa: F821
                break
    result = _body(fn)
    assert "while (true)" in result
    assert "break;" in result


# ============================================================================
# Phase 6: for-range loop
# ============================================================================


def test_for_range_one_arg():
    def fn():
        for i in range(10):
            x = i  # noqa: F821
    result = _body(fn)
    assert "for (int i = 0; i < 10; ++i)" in result


def test_for_range_two_args():
    def fn():
        for i in range(2, 8):
            x = i  # noqa: F821
    result = _body(fn)
    assert "for (int i = 2; i < 8; ++i)" in result


def test_for_range_three_args():
    def fn():
        for i in range(0, 20, 2):
            x = i  # noqa: F821
    result = _body(fn)
    assert "for (int i = 0; i < 20; i += 2)" in result


# ============================================================================
# Phase 6: Generic for-loop (non-range iteration)
# ============================================================================


def test_for_generic_container():
    """for x in container → for (auto& x : container)"""
    def fn():
        for item in collection:  # noqa: F821
            process(item)  # noqa: F821
    result = _body(fn)
    assert "for (auto& item : collection)" in result


def test_for_dict_items_structured_binding():
    """for (k, v) in d.items() → for (auto& [k, v] : d)"""
    def fn():
        for k, v in mapping.items():  # noqa: F821
            use(k, v)  # noqa: F821
    result = _body(fn)
    assert "for (auto& [k, v] : mapping)" in result


def test_for_dict_keys_structured_binding():
    """for k in d.keys() → for (auto& [k, _kv_k] : d)"""
    def fn():
        for k in mapping.keys():  # noqa: F821
            use(k)  # noqa: F821
    result = _body(fn)
    assert "for (auto& [k, _kv_k] : mapping)" in result


def test_for_dict_values_structured_binding():
    """for v in d.values() → for (auto& [_kv_v, v] : d)"""
    def fn():
        for v in mapping.values():  # noqa: F821
            use(v)  # noqa: F821
    result = _body(fn)
    assert "for (auto& [_kv_v, v] : mapping)" in result


def test_for_generic_body_indented():
    """Generic for body is correctly indented."""
    def fn():
        for x in items:  # noqa: F821
            if x > 0:  # noqa: F821
                y = x  # noqa: F821
    result = _body(fn)
    assert "for (auto& x : items)" in result
    assert "if (" in result


def test_for_nested_tuple_unpacking_items():
    """for (k1, k2), v in d.items() → structured binding with nested unpack."""
    def fn():
        for (a, b), v in d.items():  # noqa: F821
            use(a, b, v)  # noqa: F821
    result = _body(fn)
    assert "for (auto& [_kvkey, v] : d)" in result
    assert "auto& [a, b] = _kvkey" in result


# ============================================================================
# Phase 5+: is / is not operators
# ============================================================================


def test_is_none():
    """`x is None` → `(x == nullptr)`"""
    result = _v("x is None")
    assert "(x == nullptr)" == result


def test_is_not_none():
    """`x is not None` → `(x != nullptr)`"""
    result = _v("x is not None")
    assert "(x != nullptr)" == result


def test_is_not_none_in_if():
    """`if val is not None:` produces correct C++ condition."""
    def fn():
        if val is not None:  # noqa: F821
            use(val)  # noqa: F821
    result = _body(fn)
    assert "val != nullptr" in result


# ============================================================================
# Phase 6: match/case → switch
# ============================================================================


def test_match_case_switch():
    def fn():
        match mode:  # noqa: F821
            case 1:
                x = 10  # noqa: F821
            case 2:
                x = 20  # noqa: F821
            case _:
                x = 0  # noqa: F821
    result = _body(fn)
    assert "switch (" in result
    assert "case 1:" in result
    assert "case 2:" in result
    assert "default:" in result


# ============================================================================
# Phase 6: transpile_statements multi-statement body
# ============================================================================


def test_transpile_full_compute_body():
    def fn():
        is_src = node_id == 0  # noqa: F821
        dist = bis_distance(is_src, 1.0, 100.0)  # noqa: F821
        return dist  # noqa: F821
    result = _body(fn)
    assert "auto is_src" in result
    assert "auto dist" in result
    assert "return dist;" in result


def test_transpile_indentation():
    def fn():
        if x:  # noqa: F821
            return 1
        return 0
    result = _body(fn)
    lines = result.split("\n")
    # outer if is indented 4 spaces
    assert lines[0].startswith("    if (")
    # inner return is indented 8 spaces
    inner = [l for l in lines if "return 1" in l][0]
    assert inner.startswith("        ")


# ============================================================================
# Constant-folding: IntEnum / dotted-attribute chains
# ============================================================================


def test_enum_value_attribute_folds_to_integer():
    """WorkerRole.RECEIVER.value → "1" when constants dict is supplied."""
    v = PythonAstVisitor(constants={"_TestRole": _TestRole})
    node = ast.parse("_TestRole.RECEIVER.value").body[0].value
    assert v.visit(node) == "1"


def test_enum_member_folds_to_integer():
    """IntEnum member without .value also folds (IntEnum IS an int)."""
    v = PythonAstVisitor(constants={"_TestRole": _TestRole})
    node = ast.parse("_TestRole.SENSOR").body[0].value
    assert v.visit(node) == "2"


def test_attribute_no_fold_when_constants_empty():
    """Without a constants dict the dotted chain is emitted verbatim."""
    v = PythonAstVisitor()
    node = ast.parse("_TestRole.RECEIVER.value").body[0].value
    assert v.visit(node) == "_TestRole.RECEIVER.value"


def test_enum_value_in_compare_folds():
    """role == _TestRole.RECEIVER.value → (role == 1)."""
    v = PythonAstVisitor(constants={"_TestRole": _TestRole})
    node = ast.parse("role == _TestRole.RECEIVER.value").body[0].value
    assert v.visit(node) == "(role == 1)"


def test_enum_value_in_match_case_folds():
    """match/case with enum .value patterns emits integer case labels."""
    def fn():
        match mode:  # noqa: F821
            case _TestRole.UNASSIGNED.value:
                x = 0  # noqa: F821
            case _TestRole.RECEIVER.value:
                x = 1  # noqa: F821
            case _:
                x = 99  # noqa: F821
    result = _body_with_consts(fn, {"_TestRole": _TestRole})
    assert "switch (mode)" in result
    assert "case 0:" in result
    assert "case 1:" in result
    assert "default:" in result
    assert "_TestRole" not in result


# ============================================================================
# v2.0: match guard clauses — `case X if cond:` → `case X: if (cond) { ... }`
# ============================================================================


def test_match_guard_simple():
    """case X if cond: → case X: if (cond) { body } break;"""
    def fn():
        match mode:  # noqa: F821
            case 1 if active:  # noqa: F821
                x = 10  # noqa: F821
            case 2:
                x = 20  # noqa: F821
            case _:
                x = 0  # noqa: F821
    result = _body(fn)
    assert "switch (" in result
    assert "case 1:" in result
    assert "if (active)" in result
    assert "case 2:" in result
    assert "default:" in result


def test_match_guard_expression():
    """Guard expressions with comparisons are emitted correctly."""
    def fn():
        match value:  # noqa: F821
            case 0 if dist < threshold:  # noqa: F821
                result = 1  # noqa: F821
            case _:
                result = 0  # noqa: F821
    result = _body(fn)
    assert "case 0:" in result
    assert "if ((dist < threshold))" in result


def test_match_guard_body_indented():
    """Guard body is nested inside the if block."""
    def fn():
        match status:  # noqa: F821
            case 1 if enabled:  # noqa: F821
                y = 42  # noqa: F821
    result = _body(fn)
    # body must appear inside the if block, before the break
    guard_pos = result.index("if (enabled)")
    body_pos = result.index("y = 42", guard_pos)
    break_pos = result.index("break;", guard_pos)
    assert guard_pos < body_pos < break_pos


def test_match_guard_default_with_guard():
    """default: with guard works (wraps body in if block)."""
    def fn():
        match x:  # noqa: F821
            case 1:
                a = 1  # noqa: F821
            case _ if fallback:  # noqa: F821
                a = 0  # noqa: F821
    result = _body(fn)
    assert "default:" in result
    assert "if (fallback)" in result


# ============================================================================
# v2.0: OR patterns — `case A | B:` → `case A: case B:` (C++ fallthrough labels)
# ============================================================================


def test_match_or_pattern_two_values():
    """case A | B: → case A: case B: with shared body."""
    def fn():
        match mode:  # noqa: F821
            case 1 | 2:
                x = 10  # noqa: F821
            case _:
                x = 0  # noqa: F821
    result = _body(fn)
    assert "case 1:" in result
    assert "case 2:" in result
    assert result.count("break;") >= 1


def test_match_or_pattern_three_values():
    """case A | B | C: → three case labels sharing the same body."""
    def fn():
        match role:  # noqa: F821
            case 1 | 2 | 3:
                active = True  # noqa: F821
            case _:
                active = False  # noqa: F821
    result = _body(fn)
    assert "case 1:" in result
    assert "case 2:" in result
    assert "case 3:" in result


def test_match_or_pattern_body_once():
    """The shared body appears only once, not once per label."""
    def fn():
        match mode:  # noqa: F821
            case 0 | 1:
                val = 99  # noqa: F821
    result = _body(fn)
    assert result.count("val = 99") == 1


def test_match_or_pattern_with_enum_folding():
    """OR patterns with enum folding emit integer case labels."""
    def fn():
        match role:  # noqa: F821
            case _TestRole.UNASSIGNED.value | _TestRole.RECEIVER.value:
                ok = True  # noqa: F821
            case _:
                ok = False  # noqa: F821
    result = _body_with_consts(fn, {"_TestRole": _TestRole})
    assert "case 0:" in result
    assert "case 1:" in result
    assert "_TestRole" not in result


# ── Step A — Transpiler completeness (frozenset, min_hood tuple, broadcast) ──


def test_frozenset_with_element():
    """frozenset({self_uid()}) → set_t{node.uid}"""
    result = _v("frozenset({self_uid()})")
    assert result == "set_t{node.uid}"


def test_frozenset_empty():
    """frozenset() → set_t{}"""
    result = _v("frozenset()")
    assert result == "set_t{}"


def test_min_hood_tuple_to_make_tuple():
    """min_hood((x, y)) → min_hood(CALL, std::make_tuple(x, y))"""
    result = _v("min_hood((x, y))")
    assert result == "min_hood(CALL, std::make_tuple(x, y))"


def test_max_hood_tuple_to_make_tuple():
    """max_hood((a, b, c)) → max_hood(CALL, std::make_tuple(a, b, c))"""
    result = _v("max_hood((a, b, c))")
    assert result == "max_hood(CALL, std::make_tuple(a, b, c))"


def test_broadcast_with_self_uid():
    """broadcast(is_receiver, self_uid()) → broadcast(CALL, is_receiver, node.uid)"""
    result = _v("broadcast(is_receiver, self_uid())")
    assert result == "broadcast(CALL, is_receiver, node.uid)"


# ── Step A — Phase 7: collection constructors, set literal, dict.get ─────────


def test_dict_call_identity():
    """dict(x) → x  (C++ copy semantics)"""
    assert _v("dict(x)") == "x"


def test_dict_call_empty():
    """dict() → {}"""
    assert _v("dict()") == "{}"


def test_set_call_from_iterable():
    """set(iterable) → set_t{iterable.begin(), iterable.end()}"""
    result = _v("set(items)")
    assert "set_t(" in result
    assert "items.begin()" in result
    assert "items.end()" in result


def test_set_call_empty():
    """set() → set_t{}"""
    assert _v("set()") == "set_t{}"


def test_set_literal_to_set_t():
    """Python set literal {a, b} → set_t{a, b}"""
    result = _v("{x, y}")
    assert result == "set_t{x, y}"


def test_set_literal_single_element():
    """Python set literal {uid()} → set_t{uid()}"""
    result = _v("{uid()}")
    assert result.startswith("set_t{")


def test_set_call_marks_uses_frozenset():
    """set() call triggers set_t alias emission (uses_frozenset flag)."""
    import ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(ast.parse("set(items)").body[0].value)
    assert v.uses_frozenset is True


def test_set_literal_marks_uses_frozenset():
    """Set literal triggers set_t alias emission (uses_frozenset flag)."""
    import ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(ast.parse("{x, y}").body[0].value)
    assert v.uses_frozenset is True


def test_dict_get_no_default():
    """dict.get(key) → (dict.count(key) ? dict.at(key) : default_init)"""
    result = _v("d.get(k)")
    assert "d.count(k)" in result
    assert "d.at(k)" in result


def test_dict_get_with_default():
    """dict.get(key, default) → (dict.count(key) ? dict.at(key) : default)"""
    result = _v("d.get(k, 0)")
    assert "d.count(k)" in result
    assert "d.at(k)" in result
    assert "0" in result


# ============================================================================
# Phase 4 extension: short-circuit booleans + bitwise negation + bitwise augassign
# ============================================================================


def test_bool_and_short_circuit():
    """Python `and` already maps to C++ `&&` (short-circuit)."""
    result = _ve("a and b")
    assert "&&" in result
    assert "||" not in result


def test_bool_or_short_circuit():
    """Python `or` already maps to C++ `||` (short-circuit)."""
    result = _ve("a or b")
    assert "||" in result
    assert "&&" not in result


def test_bool_chain_and_or():
    """Mixed and/or chain preserves precedence via parenthesisation."""
    result = _ve("a and b or c")
    assert "&&" in result
    assert "||" in result


def test_unary_invert():
    """`~x` → `(~x)` (bitwise NOT)."""
    assert _ve("~x") == "(~x)"


def test_unary_invert_on_expression():
    """`~(a & b)` → `(~(a & b))`."""
    result = _ve("~(a & b)")
    assert result == "(~(a & b))"


def test_unary_invert_in_assign():
    """`mask = ~flags` → `auto mask = (~flags);`"""
    result = _stmt("mask = ~flags")
    assert "auto mask = (~flags);" == result


def test_augassign_bitwise_or():
    assert _stmt("x |= y") == "x |= y;"


def test_augassign_bitwise_and():
    assert _stmt("x &= y") == "x &= y;"


def test_augassign_bitwise_xor():
    assert _stmt("x ^= y") == "x ^= y;"


def test_augassign_lshift():
    assert _stmt("x <<= 1") == "x <<= 1;"


def test_augassign_rshift():
    assert _stmt("x >>= 1") == "x >>= 1;"


def test_augassign_floor_div():
    """`x //= 2` → `x /= 2;` (C++ integer division)."""
    assert _stmt("x //= 2") == "x /= 2;"


# ============================================================================
# Phase 8: CppStandard enum
# ============================================================================


def test_cpp_standard_default_is_cpp17():
    from fcpp_bridge.transpiler import CppStandard, PythonAstVisitor
    v = PythonAstVisitor()
    assert v.cpp_std == CppStandard.CPP17


def test_cpp_standard_all_values_present():
    from fcpp_bridge.transpiler import CppStandard
    values = {s.value for s in CppStandard}
    assert {14, 17, 20, 26} == values


def test_cpp_standard_flag_cpp14():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP14.flag() == "-std=c++14"


def test_cpp_standard_flag_cpp17():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP17.flag() == "-std=c++17"


def test_cpp_standard_flag_cpp20():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP20.flag() == "-std=c++20"


def test_cpp_standard_flag_cpp26():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP26.flag() == "-std=c++26"


def test_cpp_standard_str_cpp14():
    from fcpp_bridge.transpiler import CppStandard
    assert str(CppStandard.CPP14) == "C++14"


def test_cpp_standard_str_cpp26():
    from fcpp_bridge.transpiler import CppStandard
    assert str(CppStandard.CPP26) == "C++26"


def test_cpp_standard_cpp14_supports_ranges_false():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP14.supports_ranges() is False


def test_cpp_standard_cpp17_supports_ranges_false():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP17.supports_ranges() is False


def test_cpp_standard_cpp20_supports_ranges_true():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP20.supports_ranges() is True


def test_cpp_standard_cpp26_supports_ranges_true():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP26.supports_ranges() is True


def test_cpp_standard_cpp14_supports_structured_bindings_false():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP14.supports_structured_bindings() is False


def test_cpp_standard_cpp17_supports_structured_bindings_true():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP17.supports_structured_bindings() is True


def test_cpp_standard_cpp20_supports_structured_bindings_true():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP20.supports_structured_bindings() is True


def test_cpp_standard_cpp26_supports_structured_bindings_true():
    from fcpp_bridge.transpiler import CppStandard
    assert CppStandard.CPP26.supports_structured_bindings() is True


# ============================================================================
# Phase 8 extension: C++14 structured-binding fallbacks
# ============================================================================


def _v14(expr_str: str) -> str:
    """Visit expression with C++14 standard."""
    from fcpp_bridge.transpiler import CppStandard, PythonAstVisitor
    import ast as _ast
    v = PythonAstVisitor(cpp_std=CppStandard.CPP14)
    return v.visit(_ast.parse(expr_str).body[0].value)


def _body14(fn) -> str:
    """Transpile function body with C++14 standard."""
    import ast as _ast, inspect, textwrap
    from fcpp_bridge.transpiler import CppStandard, PythonAstVisitor
    source = textwrap.dedent(inspect.getsource(fn))
    tree = _ast.parse(source)
    stmts = tree.body[0].body
    v = PythonAstVisitor(cpp_std=CppStandard.CPP14)
    return v.transpile_statements(stmts)


def test_cpp14_for_dict_items_uses_first_second():
    """C++14: `for k, v in d.items()` → `.first/.second` instead of structured binding."""
    def fn():
        for k, v in d.items():  # noqa: F821
            use(k, v)  # noqa: F821
    result = _body14(fn)
    assert "auto& _kv : d" in result
    assert "_kv.first" in result
    assert "_kv.second" in result
    assert "[k, v]" not in result


def test_cpp14_for_dict_keys_uses_first():
    """C++14: `for k in d.keys()` → `.first` instead of structured binding."""
    def fn():
        for k in d.keys():  # noqa: F821
            use(k)  # noqa: F821
    result = _body14(fn)
    assert "auto& _kv : d" in result
    assert "_kv.first" in result
    assert "[k," not in result


def test_cpp14_for_dict_values_uses_second():
    """C++14: `for v in d.values()` → `.second` instead of structured binding."""
    def fn():
        for v in d.values():  # noqa: F821
            use(v)  # noqa: F821
    result = _body14(fn)
    assert "auto& _kv : d" in result
    assert "_kv.second" in result


def test_cpp14_for_nested_tuple_uses_std_get():
    """C++14: `for (k1, k2), v in d.items()` → `std::get<>` on pair key."""
    def fn():
        for (a, b), v in d.items():  # noqa: F821
            use(a, b, v)  # noqa: F821
    result = _body14(fn)
    assert "auto& _kv : d" in result
    assert "std::get<0>(_kv.first)" in result
    assert "std::get<1>(_kv.first)" in result
    assert "_kv.second" in result


def test_cpp14_dict_keys_expr_uses_first():
    """C++14: `d.keys()` expression IIFE uses `_kv.first`."""
    result = _v14("d.keys()")
    assert "auto& _kv : d" in result
    assert "_kv.first" in result
    assert "[_k, _v]" not in result


def test_cpp14_dict_values_expr_uses_second():
    """C++14: `d.values()` expression IIFE uses `_kv.second`."""
    result = _v14("d.values()")
    assert "auto& _kv : d" in result
    assert "_kv.second" in result


def test_cpp14_set_of_dict_keys_uses_first():
    """C++14: `set(d.keys())` IIFE uses `_kv.first`."""
    result = _v14("set(d.keys())")
    assert "_kv.first" in result
    assert "[_k, _v]" not in result


def test_cpp14_list_comp_dict_items_uses_first_second():
    """C++14: `[k for k, v in d.items()]` comprehension uses `.first/.second`."""
    result = _v14("[k for k, v in d.items()]")
    assert "_kv.first" in result
    assert "_kv.second" in result
    assert "[k, v]" not in result


def test_cpp14_dict_comp_items_uses_first_second():
    """C++14: `{k: v for k, v in d.items()}` dict comprehension uses `.first/.second`."""
    result = _v14("{k: v for k, v in d.items()}")
    assert "_kv.first" in result or "_r[k] = v" in result  # unpack then assign
    assert "std::map<_K, _V>" in result


def test_cpp26_for_dict_items_uses_structured_bindings():
    """C++26 still uses structured bindings (C++17+ feature)."""
    from fcpp_bridge.transpiler import CppStandard, PythonAstVisitor
    import ast as _ast, inspect, textwrap
    def fn():
        for k, v in d.items():  # noqa: F821
            use(k, v)  # noqa: F821
    source = textwrap.dedent(inspect.getsource(fn))
    tree = _ast.parse(source)
    v = PythonAstVisitor(cpp_std=CppStandard.CPP26)
    result = v.transpile_statements(tree.body[0].body)
    assert "auto& [k, v] : d" in result


def test_cpp26_dict_keys_uses_ranges():
    """C++26 dict.keys() expression → std::views::keys (ranges available)."""
    from fcpp_bridge.transpiler import CppStandard, PythonAstVisitor
    import ast as _ast
    v = PythonAstVisitor(cpp_std=CppStandard.CPP26)
    result = v.visit(_ast.parse("d.keys()").body[0].value)
    assert "std::views::keys(d)" == result


# ============================================================================
# Phase 8: Type annotation tracking
# ============================================================================


def test_annotation_dict_type_tracked():
    """Dict[int, float] annotation populates dict_type_env."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(_ast.parse("d: Dict[int, float]").body[0])
    assert "d" in v.dict_type_env
    assert v.dict_type_env["d"] == ("int", "double")


def test_annotation_dict_nested_type():
    """Dict[int, Tuple[float, float]] → key=int, val=std::tuple<double, double>."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(_ast.parse("db: Dict[int, Tuple[float, float]]").body[0])
    assert "db" in v.dict_type_env
    k, val = v.dict_type_env["db"]
    assert k == "int"
    assert "tuple" in val.lower() and "double" in val


def test_annotation_non_dict_not_tracked():
    """Non-dict annotations don't pollute dict_type_env."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(_ast.parse("x: int = 0").body[0])
    assert "x" not in v.dict_type_env


# ============================================================================
# Phase 8: dict.keys() / dict.values() in expression context
# ============================================================================


def test_dict_keys_expression_cpp17():
    """d.keys() in expression context → C++17 IIFE."""
    from fcpp_bridge.transpiler import CppStandard
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor(cpp_std=CppStandard.CPP17)
    result = v.visit(_ast.parse("d.keys()").body[0].value)
    assert "[&]()" in result
    assert "push_back(_k)" in result
    assert "std::vector" in result


def test_dict_keys_expression_cpp20():
    """d.keys() in expression context → C++20 std::views::keys."""
    from fcpp_bridge.transpiler import CppStandard
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor(cpp_std=CppStandard.CPP20)
    result = v.visit(_ast.parse("d.keys()").body[0].value)
    assert "std::views::keys(d)" == result
    assert v.uses_ranges_header is True


def test_dict_values_expression_cpp17():
    """d.values() in expression context → C++17 IIFE."""
    from fcpp_bridge.transpiler import CppStandard
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor(cpp_std=CppStandard.CPP17)
    result = v.visit(_ast.parse("d.values()").body[0].value)
    assert "[&]()" in result
    assert "push_back(_v)" in result
    assert "std::vector" in result


def test_dict_values_expression_cpp20():
    """d.values() in expression context → C++20 std::views::values."""
    from fcpp_bridge.transpiler import CppStandard
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor(cpp_std=CppStandard.CPP20)
    result = v.visit(_ast.parse("d.values()").body[0].value)
    assert "std::views::values(d)" == result


def test_dict_keys_with_annotation_uses_concrete_type():
    """Dict[int, float] annotation → keys IIFE uses `int` not `decltype`."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    src = "d: Dict[int, float]\nkeylist = d.keys()"
    tree = _ast.parse(src)
    v.visit(tree.body[0])  # process annotation
    result = v.visit(tree.body[1].value)  # visit d.keys()
    assert "std::vector<int>" in result
    assert "decltype" not in result


def test_dict_values_with_annotation_uses_concrete_type():
    """Dict[str, double] annotation → values IIFE uses `double` not `decltype`."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    src = "d: Dict[int, float]\nvallist = d.values()"
    tree = _ast.parse(src)
    v.visit(tree.body[0])
    result = v.visit(tree.body[1].value)
    assert "std::vector<double>" in result
    assert "decltype" not in result


def test_set_of_dict_keys():
    """set(d.keys()) → typed std::set IIFE."""
    result = _v("set(d.keys())")
    assert "std::set<" in result
    assert "_k" in result
    assert "[&]()" in result


def test_set_of_dict_values():
    """set(d.values()) → typed std::set IIFE."""
    result = _v("set(d.values())")
    assert "std::set<" in result
    assert "_v" in result


# ============================================================================
# Phase 8: List comprehensions
# ============================================================================


def test_list_comp_range_no_cond():
    """[i for i in range(N)] → IIFE with int vector and C-style for."""
    result = _v("[i for i in range(N)]")
    assert "std::vector<int>" in result
    assert "for (int i = 0; i < N; ++i)" in result
    assert "_r.push_back(i)" in result


def test_list_comp_range_with_cond():
    """[i for i in range(N) if i not in known] — the scattered_database.py gap."""
    result = _v("[i for i in range(N) if i not in known]")
    assert "std::vector<int>" in result
    assert "if (" in result
    assert "known" in result
    assert "_r.push_back(i)" in result


def test_list_comp_range_two_arg():
    """[i for i in range(2, N)]"""
    result = _v("[i for i in range(2, N)]")
    assert "int i = 2" in result
    assert "i < N" in result


def test_list_comp_generic_no_cond():
    """[x for x in collection] → IIFE with auto& for loop."""
    result = _v("[x for x in collection]")
    assert "for (auto& x : collection)" in result
    assert "_r.push_back(x)" in result
    assert "std::vector" in result


def test_list_comp_generic_with_cond():
    """[tc for tc in tile_shapes if tc not in tile_owner] — area_discovery.py gap."""
    result = _v("[tc for tc in tile_shapes if tc not in tile_owner]")
    assert "for (auto& tc : tile_shapes)" in result
    assert "tile_owner" in result
    assert "_r.push_back(tc)" in result


def test_list_comp_transform():
    """[f(x) for x in collection] — element type deduced via _expr_fn."""
    result = _v("[f(x) for x in collection]")
    assert "_expr_fn" in result
    assert "_T" in result
    assert "push_back(f(x))" in result


def test_list_comp_dict_items():
    """[k for k, v in d.items()] — structured binding."""
    result = _v("[k for k, v in d.items()]")
    assert "for (auto& [k, v] : d)" in result
    assert "_r.push_back(k)" in result


def test_list_comp_dict_keys_iter():
    """[k for k in d.keys()] — iterates dict keys via structured binding."""
    result = _v("[k for k in d.keys()]")
    assert "for (auto& [k, _v_k] : d)" in result
    assert "_r.push_back(k)" in result


def test_list_comp_dict_values_iter():
    """[v for v in d.values()] — iterates dict values via structured binding."""
    result = _v("[v for v in d.values()]")
    assert "for (auto& [_k_v, v] : d)" in result
    assert "_r.push_back(v)" in result


def test_list_comp_is_expression():
    """List comprehension as argument to another call."""
    result = _v("len([i for i in range(5)])")
    assert "size()" in result  # len() → .size()
    assert "std::vector<int>" in result


# ============================================================================
# Phase 8: Set comprehensions
# ============================================================================


def test_set_comp_basic():
    """{x for x in collection} → IIFE returning std::set."""
    result = _v("{x for x in collection}")
    assert "std::set<" in result
    assert "for (auto& x : collection)" in result
    assert "_r.insert(x)" in result


def test_set_comp_with_cond():
    """{x for x in collection if x > 0}"""
    result = _v("{x for x in collection if x > 0}")
    assert "std::set<" in result
    assert "if (" in result
    assert "_r.insert(x)" in result


def test_set_comp_range():
    """{i for i in range(N)} → std::set<int>."""
    result = _v("{i for i in range(N)}")
    assert "std::set<int>" in result
    assert "_r.insert(i)" in result


def test_set_comp_marks_frozenset():
    """Set comprehension sets uses_frozenset (triggers <set> include)."""
    import ast as _ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(_ast.parse("{x for x in c}").body[0].value)
    assert v.uses_frozenset is True


# ============================================================================
# Phase 8: Dict comprehensions
# ============================================================================


def test_dict_comp_range():
    """{i: i*2 for i in range(N)} → IIFE returning std::map."""
    result = _v("{i: i*2 for i in range(N)}")
    assert "std::map<_K, _V>" in result
    assert "for (int i = 0; i < N; ++i)" in result
    assert "_r[i] = (i * 2)" in result


def test_dict_comp_items():
    """{k: v*2 for k, v in d.items()} → structured binding."""
    result = _v("{k: v*2 for k, v in d.items()}")
    assert "for (auto& [k, v] : d)" in result
    assert "_r[k] = (v * 2)" in result
    assert "std::map<_K, _V>" in result


def test_dict_comp_generic():
    """{x: f(x) for x in collection} — generic iteration."""
    result = _v("{x: f(x) for x in collection}")
    assert "for (auto& x : collection)" in result
    assert "_r[x] = f(x)" in result
    assert "std::map<_K, _V>" in result


def test_dict_comp_with_cond():
    """{k: v for k, v in d.items() if k > 0}"""
    result = _v("{k: v for k, v in d.items() if k > 0}")
    assert "if (" in result
    assert "_r[k] = v" in result
