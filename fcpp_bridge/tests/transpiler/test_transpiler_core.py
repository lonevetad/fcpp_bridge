"""Tests for Transpiler — full code generation and state type handling."""

import pytest
from dataclasses import dataclass
from fcpp_bridge.python_dsl import aggregate_function, Neighborhood, AggregateType, CppType
from fcpp_bridge.transpiler import Transpiler


# ============================================================================
# Test 2: Basic transpilation
# ============================================================================


def test_transpiler_simple_float():
    @aggregate_function
    class SimpleFloat:
        def initial_state(self) -> float:
            return 0.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return self_state + 1.0

    cpp_code = Transpiler(SimpleFloat).generate()
    assert isinstance(cpp_code, str)
    assert len(cpp_code) > 0
    assert "#include <lib/fcpp.hpp>" in cpp_code
    assert "AGGREGATE_TEMPLATE(main)" in cpp_code


def test_transpiler_int_state():
    @aggregate_function
    class IntAggregate:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    assert "int" in Transpiler(IntAggregate).generate()


def test_transpiler_custom_struct():
    @dataclass
    class CustomState:
        x: float
        y: int

    @aggregate_function
    class StructAggregate:
        def initial_state(self) -> CustomState:
            return CustomState(0.0, 0)

        def compute(self, self_state: CustomState, neighbors: Neighborhood[CustomState]) -> CustomState:
            return self_state

    cpp_code = Transpiler(StructAggregate).generate()
    assert "struct CustomState" in cpp_code
    assert "double x" in cpp_code
    assert "int y" in cpp_code


# ============================================================================
# Test 4: Code generation
# ============================================================================


def test_transpiler_code_structure():
    @aggregate_function
    class TestAggregate:
        def initial_state(self) -> float:
            return 1.5

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return self_state

    cpp_code = Transpiler(TestAggregate).generate()
    assert cpp_code.count("#include") > 0
    assert "AGGREGATE_TEMPLATE" in cpp_code
    assert "compute_next_state" in cpp_code


def test_transpiler_preserves_state_type():
    @aggregate_function
    class TypedAggregate:
        def initial_state(self) -> float:
            return 0.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return self_state

    t = Transpiler(TypedAggregate)
    state_cpp_type = t.get_state_type_cpp()
    assert state_cpp_type.name == "double"
    assert state_cpp_type.is_primitive


# ============================================================================
# Test 9: AggregateType inference
# ============================================================================


def test_aggregate_type_infer_float():
    t = AggregateType.infer(float)
    assert t.name == "double"
    assert t.is_primitive


def test_aggregate_type_infer_int():
    t = AggregateType.infer(int)
    assert t.name == "int"
    assert t.is_primitive


def test_aggregate_type_infer_bool():
    t = AggregateType.infer(bool)
    assert t.name == "bool"
    assert t.is_primitive


def test_aggregate_type_infer_str():
    t = AggregateType.infer(str)
    assert t.name == "std::string"


def test_aggregate_type_infer_list_float():
    t = AggregateType.infer(list[float])
    assert "std::vector" in t.name
    assert "double" in t.name


def test_aggregate_type_infer_list_int():
    assert AggregateType.infer(list[int]).name == "std::vector<int>"


def test_aggregate_type_infer_tuple():
    t = AggregateType.infer(tuple[float, int])
    assert "std::tuple" in t.name
    assert "double" in t.name
    assert "int" in t.name


def test_aggregate_type_infer_dict():
    assert "std::map" in AggregateType.infer(dict[str, float]).name


def test_aggregate_type_infer_dataclass():
    @dataclass
    class Vec2:
        x: float
        y: float

    t = AggregateType.infer(Vec2)
    assert t.name == "Vec2"
    assert t.is_struct
    assert "x" in t.fields
    assert "y" in t.fields


def test_aggregate_type_is_numeric():
    assert AggregateType.is_numeric(CppType("double"))
    assert AggregateType.is_numeric(CppType("int"))
    assert not AggregateType.is_numeric(CppType("std::string"))


def test_aggregate_type_is_container():
    assert AggregateType.is_container(CppType("std::vector<int>"))
    assert AggregateType.is_container(CppType("std::map<int, int>"))
    assert not AggregateType.is_container(CppType("double"))


def test_cpp_type_declaration_primitive():
    t = CppType("double", is_primitive=True)
    assert t.cpp_declaration() == ""


def test_cpp_type_declaration_struct():
    fields = {"x": CppType("double"), "n": CppType("int")}
    t = CppType("MyState", is_struct=True, is_primitive=False, fields=fields)
    decl = t.cpp_declaration()
    assert "struct MyState" in decl
    assert "double x" in decl
    assert "int n" in decl


# ============================================================================
# Test 10: Transpiler with various state types
# ============================================================================


def test_transpiler_bool_state():
    @aggregate_function
    class BoolAggregate:
        def initial_state(self) -> bool:
            return False

        def compute(self, self_state: bool, neighbors: Neighborhood[bool]) -> bool:
            return self_state

    assert "bool" in Transpiler(BoolAggregate).generate()


def test_transpiler_str_state():
    @aggregate_function
    class StrAggregate:
        def initial_state(self) -> str:
            return ""

        def compute(self, self_state: str, neighbors: Neighborhood[str]) -> str:
            return self_state

    assert "std::string" in Transpiler(StrAggregate).generate()


def test_transpiler_list_state():
    @aggregate_function
    class ListAggregate:
        def initial_state(self) -> list[float]:
            return []

        def compute(self, self_state: list[float], neighbors: Neighborhood[list[float]]) -> list[float]:
            return self_state

    assert "std::vector" in Transpiler(ListAggregate).generate()


def test_transpiler_includes_fcpp():
    @aggregate_function
    class FloatAgg:
        def initial_state(self) -> float:
            return 0.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return self_state

    assert Transpiler(FloatAgg).generate().startswith("#include")


def test_transpiler_generate_returns_string():
    @aggregate_function
    class FloatAgg2:
        def initial_state(self) -> float:
            return 1.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return self_state

    assert isinstance(Transpiler(FloatAgg2).generate(), str)


COMM_VALUE = 150
PI_RATIO = 3.14
USE_FLAG = True
STRING_LABEL = "test_const"


def test_transpiler_state_type_int():
    @aggregate_function
    class IntAgg2:
        def initial_state(self) -> int:
            return 42

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    assert Transpiler(IntAgg2).get_state_type_cpp().name == "int"


def test_transpiler_module_constants_are_exported():
    @aggregate_function
    class ConstAggregate:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return COMM_VALUE + int(PI_RATIO)

    cpp_code = Transpiler(ConstAggregate).generate()
    assert "constexpr int COMM_VALUE = 150;" in cpp_code
    assert "constexpr double PI_RATIO = 3.14;" in cpp_code
    assert "constexpr bool USE_FLAG = true;" in cpp_code
    assert "constexpr const char STRING_LABEL[] = \"test_const\";" in cpp_code


def test_transpiler_state_type_bool():
    @aggregate_function
    class BoolAgg2:
        def initial_state(self) -> bool:
            return True

        def compute(self, self_state: bool, neighbors: Neighborhood[bool]) -> bool:
            return self_state

    assert Transpiler(BoolAgg2).get_state_type_cpp().name == "bool"


def test_transpiler_custom_struct_field_types():
    @dataclass
    class Pos:
        x: float
        y: float
        count: int

    @aggregate_function
    class PosAggregate:
        def initial_state(self) -> Pos:
            return Pos(0.0, 0.0, 0)

        def compute(self, self_state: Pos, neighbors: Neighborhood[Pos]) -> Pos:
            return self_state

    cpp = Transpiler(PosAggregate).generate()
    assert "struct Pos" in cpp
    assert "double x" in cpp
    assert "double y" in cpp
    assert "int count" in cpp


def test_transpiler_adds_header_for_used_primitive():
    @aggregate_function
    class MinHoodAgg:
        def initial_state(self) -> float:
            return 0.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return min_hood(self_state)  # noqa: F821

    cpp = Transpiler(MinHoodAgg).generate()
    assert "<lib/coordination/utils.hpp>" in cpp


def test_transpiler_adds_geometry_header_for_rectangle_walk():
    @aggregate_function
    class WalkAgg:
        def initial_state(self) -> float:
            return 0.0

        def compute(self, self_state: float, neighbors: Neighborhood[float]) -> float:
            return rectangle_walk(lo, hi, 1.0, 0.1)  # noqa: F821

    cpp = Transpiler(WalkAgg).generate()
    assert "<lib/coordination/geometry.hpp>" in cpp


# ============================================================================
# Phase 3: set_t alias emission when frozenset() is used
# ============================================================================


def test_transpiler_frozenset_emits_set_t_alias():
    @aggregate_function
    class FrozenSetAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            s = frozenset({self_uid()})  # noqa: F821
            return self_state

    cpp = Transpiler(FrozenSetAgg).generate()
    assert "using set_t = std::set<int>;" in cpp
    assert "<set>" in cpp


def test_transpiler_frozenset_empty_emits_set_t_alias():
    @aggregate_function
    class EmptyFrozenSetAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            s = frozenset()  # noqa: F821
            return self_state

    cpp = Transpiler(EmptyFrozenSetAgg).generate()
    assert "using set_t = std::set<int>;" in cpp


def test_transpiler_no_set_t_alias_without_frozenset():
    @aggregate_function
    class NoFrozenSetAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    cpp = Transpiler(NoFrozenSetAgg).generate()
    assert "set_t" not in cpp


def test_transpiler_uses_frozenset_flag_tracked_by_visitor():
    import ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(ast.parse("frozenset()").body[0].value)
    assert v.uses_frozenset is True


def test_transpiler_uses_frozenset_flag_false_without_frozenset():
    import ast
    from fcpp_bridge.transpiler import PythonAstVisitor
    v = PythonAstVisitor()
    v.visit(ast.parse("nbr(x)").body[0].value)
    assert v.uses_frozenset is False


# ============================================================================
# Phase 8: CppStandard — Transpiler integration
# ============================================================================


def test_transpiler_accepts_cpp14():
    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class Cpp14Agg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(Cpp14Agg, cpp_std=CppStandard.CPP14)
    assert t.cpp_std == CppStandard.CPP14
    cpp = t.generate()
    assert isinstance(cpp, str) and len(cpp) > 0


def test_transpiler_accepts_cpp26():
    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class Cpp26Agg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(Cpp26Agg, cpp_std=CppStandard.CPP26)
    assert t.cpp_std == CppStandard.CPP26


def test_transpiler_default_cpp_standard_is_cpp17():
    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class StdAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(StdAgg)
    assert t.cpp_std == CppStandard.CPP17


def test_transpiler_accepts_cpp20():
    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class Cpp20Agg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(Cpp20Agg, cpp_std=CppStandard.CPP20)
    assert t.cpp_std == CppStandard.CPP20


def test_transpiler_cpp20_dict_keys_emits_ranges_include():
    """With C++20, d.keys() in compute body triggers #include <ranges>."""
    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class RangesAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            ks = local_db.keys()  # noqa: F821
            return self_state

    cpp = Transpiler(RangesAgg, cpp_std=CppStandard.CPP20).generate()
    assert "<ranges>" in cpp
    assert "std::views::keys" in cpp


def test_transpiler_cpp17_dict_keys_emits_iife():
    """With C++17 (default), d.keys() emits an IIFE, not std::views."""

    @aggregate_function
    class IifeAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            ks = local_db.keys()  # noqa: F821
            return self_state

    cpp = Transpiler(IifeAgg).generate()
    assert "std::views::keys" not in cpp
    assert "[&]()" in cpp
    assert "push_back(_k)" in cpp


def test_transpiler_list_comp_in_compute():
    """List comprehension in compute() body is transpiled to vector IIFE."""

    @aggregate_function
    class ListCompAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            xs = [i for i in range(10)]  # noqa: F821
            return self_state

    cpp = Transpiler(ListCompAgg).generate()
    assert "std::vector<int>" in cpp
    assert "push_back(i)" in cpp


def test_transpiler_set_comp_in_compute():
    """Set comprehension in compute() body triggers <set> include."""

    @aggregate_function
    class SetCompAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            s = {i for i in range(5)}  # noqa: F821
            return self_state

    cpp = Transpiler(SetCompAgg).generate()
    assert "#include <set>" in cpp
    assert "std::set<int>" in cpp
    assert "_r.insert(i)" in cpp


def test_transpiler_dict_comp_in_compute():
    """Dict comprehension in compute() body emits std::map IIFE."""

    @aggregate_function
    class DictCompAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            d = {i: i * 2 for i in range(5)}  # noqa: F821
            return self_state

    cpp = Transpiler(DictCompAgg).generate()
    assert "std::map<_K, _V>" in cpp
    assert "_r[i] = (i * 2)" in cpp


# ============================================================================
# Phase 9: config file integration
# ============================================================================


def test_transpiler_config_yaml_sets_cpp_std(monkeypatch, tmp_path):
    """Transpiler reads cpp_standard from top-level YAML key when not given explicitly."""
    (tmp_path / "fcpp_bridge.yaml").write_text(
        "cpp_standard: cpp14\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class CfgYamlAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(CfgYamlAgg)
    assert t.cpp_std == CppStandard.CPP14


def test_transpiler_config_json_sets_cpp_std(monkeypatch, tmp_path):
    """Transpiler falls back to JSON config when no YAML file is present."""
    import json
    (tmp_path / "fcpp_bridge.json").write_text(
        json.dumps({"cpp_standard": "cpp20"}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class CfgJsonAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(CfgJsonAgg)
    assert t.cpp_std == CppStandard.CPP20


def test_transpiler_explicit_arg_overrides_config(monkeypatch, tmp_path):
    """An explicit cpp_std argument takes precedence over the config file."""
    (tmp_path / "fcpp_bridge.yaml").write_text(
        "cpp_standard: cpp14\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class ExplicitAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(ExplicitAgg, cpp_std=CppStandard.CPP26)
    assert t.cpp_std == CppStandard.CPP26


def test_transpiler_yaml_beats_json_for_std(monkeypatch, tmp_path):
    """When both YAML and JSON config exist, YAML wins."""
    import json as _json
    (tmp_path / "fcpp_bridge.yaml").write_text(
        "cpp_standard: cpp14\n", encoding="utf-8"
    )
    (tmp_path / "fcpp_bridge.json").write_text(
        _json.dumps({"cpp_standard": "cpp26"}), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    from fcpp_bridge.transpiler import CppStandard

    @aggregate_function
    class YamlWinsAgg:
        def initial_state(self) -> int:
            return 0

        def compute(self, self_state: int, neighbors: Neighborhood[int]) -> int:
            return self_state

    t = Transpiler(YamlWinsAgg)
    assert t.cpp_std == CppStandard.CPP14
