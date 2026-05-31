"""C++ language standard selector used by the transpiler and AST visitor."""

from enum import Enum


class CppStandard(Enum):
    """Supported C++ standards for code generation.

    Values correspond to the year of the standard.  Use ``flag()`` to obtain
    the compiler flag (``-std=c++NN``) and the ``supports_*`` predicates to
    gate language features that are not universally available.
    """

    CPP14 = 14
    CPP17 = 17
    CPP20 = 20
    CPP26 = 26

    def supports_structured_bindings(self) -> bool:
        """True for C++17+ — ``auto& [k, v] = pair;`` syntax available."""
        return self.value >= 17

    def supports_ranges(self) -> bool:
        """True for C++20+ — ``std::views::keys/values`` and ``<ranges>`` available."""
        return self.value >= 20

    def flag(self) -> str:
        """Compiler flag string for this standard (e.g. ``-std=c++17``)."""
        return f"-std=c++{self.value}"

    def __str__(self) -> str:
        return f"C++{self.value}"
