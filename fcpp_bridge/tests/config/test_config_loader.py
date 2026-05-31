"""Tests for fcpp_bridge.config — BridgeConfig loading from YAML / JSON."""

import json
from pathlib import Path

import pytest

from fcpp_bridge.config import BridgeConfig, CompilerConfig, load_config
from fcpp_bridge.transpiler import CppStandard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(directory: Path, content: str) -> Path:
    p = directory / "fcpp_bridge.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _write_json(directory: Path, content: dict) -> Path:
    p = directory / "fcpp_bridge.json"
    p.write_text(json.dumps(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Default (no file)
# ---------------------------------------------------------------------------


def test_load_config_no_file_returns_defaults(tmp_path):
    cfg = load_config(start_dir=tmp_path)
    assert isinstance(cfg, BridgeConfig)
    assert cfg.cpp_standard == CppStandard.CPP17
    assert cfg.compiler.opt_level == "2"
    assert cfg.compiler.gcc_path == "g++"
    assert cfg.compiler.extra_includes == []


def test_load_config_no_file_compiler_paths(tmp_path):
    cfg = load_config(start_dir=tmp_path)
    assert cfg.compiler.cache_dir == Path("build")
    assert cfg.compiler.cpp_dir == Path("cpp_transpiled")


# ---------------------------------------------------------------------------
# YAML loading — cpp_standard (top-level, unified)
# ---------------------------------------------------------------------------


def test_load_config_yaml_cpp17(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp17\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP17


def test_load_config_yaml_cpp14(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp14\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP14


def test_load_config_yaml_cpp20(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp20\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP20


def test_load_config_yaml_cpp26(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp26\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP26


def test_load_config_yaml_numeric_notation(tmp_path):
    """'17' is a valid shorthand for cpp17."""
    _write_yaml(tmp_path, "cpp_standard: '17'\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP17


def test_load_config_yaml_cxx_notation(tmp_path):
    """'c++20' is a valid way to spell cpp20."""
    _write_yaml(tmp_path, "cpp_standard: c++20\n")
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP20


def test_load_config_yaml_compiler_section(tmp_path):
    _write_yaml(tmp_path, (
        "cpp_standard: cpp17\n"
        "compiler:\n"
        "  gcc_path: /usr/bin/g++-13\n"
        "  opt_level: '0'\n"
        "  extra_includes:\n"
        "    - /opt/mylib/include\n"
    ))
    cfg = load_config(start_dir=tmp_path)
    assert cfg.compiler.gcc_path == "/usr/bin/g++-13"
    assert cfg.compiler.opt_level == "0"
    assert cfg.compiler.extra_includes == ["/opt/mylib/include"]


def test_load_config_yaml_compiler_cache_and_cpp_dirs(tmp_path):
    _write_yaml(tmp_path, (
        "compiler:\n"
        "  cache_dir: /tmp/cache\n"
        "  cpp_dir: /tmp/cpp\n"
    ))
    cfg = load_config(start_dir=tmp_path)
    assert cfg.compiler.cache_dir == Path("/tmp/cache")
    assert cfg.compiler.cpp_dir == Path("/tmp/cpp")


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------


def test_load_config_json_cpp14(tmp_path):
    _write_json(tmp_path, {"cpp_standard": "cpp14"})
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP14


def test_load_config_json_compiler_section(tmp_path):
    _write_json(tmp_path, {
        "cpp_standard": "cpp20",
        "compiler": {
            "gcc_path": "/usr/bin/g++",
            "opt_level": "3",
            "extra_includes": ["/a", "/b"],
        }
    })
    cfg = load_config(start_dir=tmp_path)
    assert cfg.cpp_standard == CppStandard.CPP20
    assert cfg.compiler.gcc_path == "/usr/bin/g++"
    assert cfg.compiler.opt_level == "3"
    assert cfg.compiler.extra_includes == ["/a", "/b"]


def test_load_config_json_empty_object(tmp_path):
    """An empty JSON object is valid and yields all defaults."""
    _write_json(tmp_path, {})
    cfg = load_config(start_dir=tmp_path)
    assert cfg.cpp_standard == CppStandard.CPP17


# ---------------------------------------------------------------------------
# YAML takes precedence over JSON
# ---------------------------------------------------------------------------


def test_yaml_takes_precedence_over_json(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp14\n")
    _write_json(tmp_path, {"cpp_standard": "cpp26"})
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP14


def test_json_used_when_no_yaml(tmp_path):
    _write_json(tmp_path, {"cpp_standard": "cpp20"})
    assert load_config(start_dir=tmp_path).cpp_standard == CppStandard.CPP20


# ---------------------------------------------------------------------------
# Search walks parent directories
# ---------------------------------------------------------------------------


def test_load_config_found_in_parent(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp26\n")
    child = tmp_path / "sub" / "dir"
    child.mkdir(parents=True)
    assert load_config(start_dir=child).cpp_standard == CppStandard.CPP26


def test_load_config_child_shadows_parent(tmp_path):
    """Config in the closer directory wins."""
    _write_yaml(tmp_path, "cpp_standard: cpp14\n")
    child = tmp_path / "project"
    child.mkdir()
    _write_yaml(child, "cpp_standard: cpp20\n")
    assert load_config(start_dir=child).cpp_standard == CppStandard.CPP20


# ---------------------------------------------------------------------------
# Invalid config raises ValueError
# ---------------------------------------------------------------------------


def test_unknown_cpp_standard_raises(tmp_path):
    _write_yaml(tmp_path, "cpp_standard: cpp99\n")
    with pytest.raises(ValueError, match="cpp99"):
        load_config(start_dir=tmp_path)


# ---------------------------------------------------------------------------
# Dataclass types
# ---------------------------------------------------------------------------


def test_bridge_config_default_types():
    cfg = BridgeConfig()
    assert isinstance(cfg.compiler, CompilerConfig)
    assert cfg.cpp_standard == CppStandard.CPP17


def test_compiler_config_defaults():
    c = CompilerConfig()
    assert c.gcc_path == "g++"
    assert c.opt_level == "2"
    assert c.extra_includes == []


# ---------------------------------------------------------------------------
# network_size
# ---------------------------------------------------------------------------


def test_load_config_default_network_size(tmp_path):
    cfg = load_config(start_dir=tmp_path)
    assert cfg.network_size == 20


def test_load_config_yaml_network_size(tmp_path):
    _write_yaml(tmp_path, "network_size: 50\n")
    assert load_config(start_dir=tmp_path).network_size == 50


def test_load_config_json_network_size(tmp_path):
    _write_json(tmp_path, {"network_size": 8})
    assert load_config(start_dir=tmp_path).network_size == 8


def test_network_size_zero_is_valid(tmp_path):
    _write_yaml(tmp_path, "network_size: 0\n")
    assert load_config(start_dir=tmp_path).network_size == 0


# ---------------------------------------------------------------------------
# area_size
# ---------------------------------------------------------------------------


def test_load_config_default_area_size(tmp_path):
    cfg = load_config(start_dir=tmp_path)
    assert cfg.area_size == (500.0, 500.0)


def test_load_config_yaml_area_size(tmp_path):
    _write_yaml(tmp_path, "area_size: [1000.0, 250.0]\n")
    cfg = load_config(start_dir=tmp_path)
    assert cfg.area_size == (1000.0, 250.0)


def test_load_config_json_area_size(tmp_path):
    _write_json(tmp_path, {"area_size": [300.0, 400.0]})
    cfg = load_config(start_dir=tmp_path)
    assert cfg.area_size == (300.0, 400.0)


def test_load_config_area_size_integer_values(tmp_path):
    """Integer elements in area_size are coerced to float."""
    _write_yaml(tmp_path, "area_size: [200, 150]\n")
    cfg = load_config(start_dir=tmp_path)
    assert cfg.area_size == (200.0, 150.0)
    assert isinstance(cfg.area_size[0], float)


def test_load_config_area_size_wrong_length_raises(tmp_path):
    _write_yaml(tmp_path, "area_size: [100.0]\n")
    with pytest.raises(ValueError, match="area_size"):
        load_config(start_dir=tmp_path)


def test_load_config_area_size_non_numeric_raises(tmp_path):
    _write_yaml(tmp_path, "area_size: [100.0, hello]\n")
    with pytest.raises((ValueError, TypeError)):
        load_config(start_dir=tmp_path)


# ---------------------------------------------------------------------------
# BridgeConfig dataclass defaults
# ---------------------------------------------------------------------------


def test_bridge_config_default_network_size():
    assert BridgeConfig().network_size == 20


def test_bridge_config_default_area_size():
    assert BridgeConfig().area_size == (500.0, 500.0)
