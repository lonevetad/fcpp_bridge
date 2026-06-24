import inspect
import ast
import re
import textwrap as _tw
from typing import Type, Optional

from fcpp_bridge.python_dsl.validators import AggregateValidator, ValidationError
from fcpp_bridge.python_dsl.types import AggregateType, CppType
from fcpp_bridge.log import get_logger
from .cpp_code_builder import CppCodeBuilder
from .python_ast_visitor import PythonAstVisitor
from ._constants import _FCPP_PRIMITIVES
from ._cpp_standard import CppStandard

_log = get_logger(__name__)


class Transpiler:
    """Main transpiler class: Python DSL → C++ code."""

    def __init__(self, aggregate_class: Type,
                 cpp_std: Optional[CppStandard] = None):
        """Initialize transpiler with aggregate function class.

        Args:
            aggregate_class: The Python aggregate function class to transpile.
            cpp_std: Target C++ standard for generated code.  When *None*
                     (default) the value is read from ``fcpp_bridge.yaml`` /
                     ``fcpp_bridge.json`` if present, otherwise C++17 is used.
        """
        if cpp_std is None:
            from fcpp_bridge.config import load_config
            cpp_std = load_config().cpp_standard
        self.aggregate_class = aggregate_class
        self.cpp_std: CppStandard = cpp_std
        self.state_type: Optional[CppType] = None
        self._validate()

    def _validate(self) -> None:
        """Pre-flight checks."""
        warnings = AggregateValidator.validate(self.aggregate_class)
        for warning in warnings:
            _log.warning("DSL: %s", warning)

        self.state_type = AggregateType.infer(
            AggregateValidator.get_state_type(self.aggregate_class)
        )

    def _extract_module_constants(self) -> list[str]:
        """Collect simple module-level constants for generated C++ code."""
        module = inspect.getmodule(self.aggregate_class)
        if module is None:
            return []

        decls: list[str] = []
        for name, value in sorted(module.__dict__.items()):
            if not name.isupper() or name.startswith("_"):
                continue
            if isinstance(value, bool):
                decls.append(
                    f"constexpr bool {name} = {'true' if value else 'false'};")
            elif isinstance(value, int):
                decls.append(f"constexpr int {name} = {value};")
            elif isinstance(value, float):
                decls.append(f"constexpr double {name} = {value};")
            elif isinstance(value, str):
                escaped = value.replace('\\', '\\\\').replace('"', '\\"')
                decls.append(f'constexpr const char {name}[] = "{escaped}";')
        return decls

    def generate(self) -> str:
        """Generate C++ code for this aggregate function."""
        _log.debug("Generating C++ for %s", self.aggregate_class.__name__)
        builder = CppCodeBuilder()

        builder.add_include("<lib/fcpp.hpp>")

        for inc in (self.state_type.required_includes or []):
            builder.add_include(inc)

        module_constants = self._extract_module_constants()
        for decl in module_constants:
            builder.add_declaration(decl)

        if self.state_type.is_struct and self.state_type.fields:
            builder.add_declaration(self.state_type.cpp_declaration())

        compute_code, used_prims, uses_frozenset, uses_ranges = self._generate_compute()
        for prim in used_prims:
            header = _FCPP_PRIMITIVES.get(prim)
            if header:
                builder.add_include(header)

        if uses_frozenset:
            builder.add_include("<set>")
            builder.add_declaration("using set_t = std::set<int>;")
        if uses_ranges:
            builder.add_include("<ranges>")

        builder.add_helper(compute_code)

        initial_code = self._generate_initial_state()
        main_agg = self._generate_main_aggregate(initial_code, used_prims)
        builder.set_main_aggregate(main_agg)

        return builder.build()

    def _generate_initial_state(self) -> str:
        """Generate C++ code for initial_state() logic."""
        method = getattr(self.aggregate_class, "initial_state")
        source = inspect.getsource(method)

        lines = source.split("\n")
        for line in lines:
            if "return" in line:
                return_expr = line.split("return")[1].strip()
                return return_expr.rstrip(":")

        return "0"

    def _generate_compute(self):
        """Transpile the Python compute() body to a C++ helper function."""
        state_type_name = self.state_type.name if self.state_type else "double"
        method = getattr(self.aggregate_class, "compute")

        cpp_body, used_prims, uses_frozenset, uses_ranges = self._transpile_method_body(method, {
            "self_state": "self_state",
            "state": "self_state",
            "s": "self_state",
            "neighbors": "neighbor_states",
            "nbrs": "neighbor_states",
            "neighborhood": "neighbor_states",
        })

        code = (
            f"\n// Generated compute helper (transpiled from Python)\n"
            f"{state_type_name} compute_next_state(\n"
            f"    const {state_type_name}& self_state,\n"
            f"    const std::vector<{state_type_name}>& neighbor_states) {{\n"
            f"{cpp_body}\n"
            f"}}\n"
        )
        return code, used_prims, uses_frozenset, uses_ranges

    def _transpile_method_body(self, method, param_remap: dict):
        """Transpile the full body of a Python method to C++ statements."""
        try:
            source = inspect.getsource(method)
            source = _tw.dedent(source)
            tree = ast.parse(source)
            func_def = tree.body[0]
        except (OSError, SyntaxError, IndexError):
            return "    return self_state;", []

        stmts = func_def.body
        # skip leading docstring
        if (
            stmts
            and isinstance(stmts[0], ast.Expr)
            and isinstance(stmts[0].value, ast.Constant)
            and isinstance(stmts[0].value.value, str)
        ):
            stmts = stmts[1:]

        # Pass the function's globals so constant chains (e.g. IntEnum .value
        # references) can be folded to integer literals in C++ case labels.
        fn_globals = getattr(method, "__globals__", {})
        visitor = PythonAstVisitor(constants=fn_globals, cpp_std=self.cpp_std)
        cpp_body = visitor.transpile_statements(stmts)

        for py_name, cpp_name in param_remap.items():
            cpp_body = re.sub(rf'\b{re.escape(py_name)}\b', cpp_name, cpp_body)

        if not cpp_body.strip():
            cpp_body = "    return self_state;"

        return cpp_body, visitor.used_primitives, visitor.uses_frozenset, visitor.uses_ranges_header

    def _generate_main_aggregate(self, initial_expr: str, used_prims: list = None) -> str:
        """Generate the main FCPP aggregate function."""
        state_type_name = self.state_type.name if self.state_type else "double"
        class_name = self.aggregate_class.__name__

        # Generate using declarations for coordination primitives
        using_declarations = ""
        if used_prims:
            using_decls = []
            for prim in set(used_prims):
                using_decls.append(f"    using fcpp::coordination::{prim};")
            if using_decls:
                using_declarations = "\n" + \
                    "\n".join(sorted(using_decls)) + "\n"

        return f"""
// Generated FCPP aggregate program — {class_name}
namespace fcpp_generated {{

AGGREGATE_TEMPLATE(main) : void {{
    using state_t = {state_type_name};{using_declarations}
    // Initialize or retrieve persistent state
    auto& current_state = old(CALL, static_cast<state_t>({initial_expr}));

    // Collect neighbor states via nbr
    auto nbr_states = nbr(CALL, current_state);

    // Flatten field to vector for compute helper
    std::vector<state_t> neighbor_vec;
    fold_hood(CALL, [&](state_t v, fcpp::unit) {{
        neighbor_vec.push_back(v);
        return fcpp::unit{{}};
    }}, fcpp::unit{{}}, nbr_states);

    // Compute next state from transpiled Python logic
    current_state = compute_next_state(current_state, neighbor_vec);
}}

}}  // namespace fcpp_generated

// Entry point — spawns IPC server then runs simulation
int main(int argc, char* argv[]) {{
    int num_nodes = (argc > 1) ? std::atoi(argv[1]) : 100;
    int ipc_port  = (argc > 2) ? std::atoi(argv[2]) : 8765;

    // TODO: initialise FCPPSimulator with num_nodes and ipc_port
    return 0;
}}
"""

    def get_state_type_cpp(self) -> CppType:
        """Get the inferred C++ state type."""
        return self.state_type or CppType("double")
