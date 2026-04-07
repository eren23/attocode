"""Tests for Go symbol extraction improvements.

Tests Go-specific features: doc comments, method receivers, visibility,
and var_types config.
"""

from __future__ import annotations

import pytest

from attocode.integrations.context.ts_parser import (
    LANGUAGE_CONFIGS,
    _get_visibility,
    ts_parse_file,
)


def _has_grammar(lang: str) -> bool:
    """Check if tree-sitter grammar is installed."""
    from attocode.integrations.context.ts_parser import is_available

    return is_available(lang)


# ============================================================
# Go visibility (unit — no grammar needed)
# ============================================================


class TestGoVisibility:
    """Test Go visibility detection based on capitalization."""

    def test_exported_function_is_public(self) -> None:
        assert _get_visibility("HandleRequest", "go") == "public"

    def test_single_uppercase_letter(self) -> None:
        assert _get_visibility("X", "go") == "public"

    def test_unexported_function_is_private(self) -> None:
        assert _get_visibility("handleRequest", "go") == "private"

    def test_single_lowercase_letter(self) -> None:
        assert _get_visibility("x", "go") == "private"

    def test_underscore_prefix_is_private(self) -> None:
        assert _get_visibility("_internal", "go") == "private"

    def test_empty_name_is_private(self) -> None:
        assert _get_visibility("", "go") == "private"

    def test_uppercase_all_caps(self) -> None:
        assert _get_visibility("MAX_RETRIES", "go") == "public"


# ============================================================
# Go config (unit — no grammar needed)
# ============================================================


class TestGoConfig:
    """Test Go language config has var_types for const/var extraction."""

    def test_go_config_exists(self) -> None:
        assert "go" in LANGUAGE_CONFIGS

    def test_go_config_has_var_types(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert cfg.var_types is not None
        assert len(cfg.var_types) > 0

    def test_go_var_types_includes_const(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert "const_declaration" in cfg.var_types

    def test_go_var_types_includes_var(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert "var_declaration" in cfg.var_types

    def test_go_function_types_include_method(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert "method_declaration" in cfg.function_types
        assert "function_declaration" in cfg.function_types

    def test_go_class_types(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert "type_declaration" in cfg.class_types

    def test_go_import_types(self) -> None:
        cfg = LANGUAGE_CONFIGS["go"]
        assert "import_declaration" in cfg.import_types


# ============================================================
# Go doc comments (requires tree-sitter-go)
# ============================================================


@pytest.mark.skipif(not _has_grammar("go"), reason="tree-sitter-go not installed")
class TestGoDocComments:
    """Test Go doc comment extraction via _find_go_doc_comment."""

    def test_single_line_doc_comment(self) -> None:
        code = (
            "package main\n"
            "\n"
            "// HandleRequest processes an HTTP request.\n"
            "func HandleRequest() {}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        funcs = result["functions"]
        handle = next(fn for fn in funcs if fn["name"] == "HandleRequest")
        assert "docstring" in handle
        assert "processes an HTTP request" in handle["docstring"]

    def test_multi_line_doc_comment(self) -> None:
        code = (
            "package main\n"
            "\n"
            "// HandleRequest processes an incoming HTTP request\n"
            "// and returns a response.\n"
            "func HandleRequest() {}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        funcs = result["functions"]
        handle = next(fn for fn in funcs if fn["name"] == "HandleRequest")
        assert "docstring" in handle
        assert "processes an incoming HTTP request" in handle["docstring"]
        assert "returns a response" in handle["docstring"]

    def test_function_without_doc_comment(self) -> None:
        code = (
            "package main\n"
            "\n"
            "func helper() {}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        funcs = result["functions"]
        h = next(fn for fn in funcs if fn["name"] == "helper")
        # No docstring key, or empty string
        assert h.get("docstring", "") == ""

    def test_comment_separated_by_blank_line_not_attached(self) -> None:
        code = (
            "package main\n"
            "\n"
            "// This is a stray comment.\n"
            "\n"
            "func Standalone() {}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        funcs = result["functions"]
        fn = next(fn for fn in funcs if fn["name"] == "Standalone")
        assert fn.get("docstring", "") == ""

    def test_doc_comment_on_type_declaration(self) -> None:
        code = (
            "package main\n"
            "\n"
            "// Server is the main HTTP server.\n"
            "type Server struct {\n"
            "    Port int\n"
            "}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        classes = result["classes"]
        server = next((c for c in classes if c["name"] == "Server"), None)
        assert server is not None
        assert "docstring" in server
        assert "main HTTP server" in server["docstring"]


# ============================================================
# Go method receiver extraction (requires tree-sitter-go)
# ============================================================


@pytest.mark.skipif(not _has_grammar("go"), reason="tree-sitter-go not installed")
class TestGoMethodReceiver:
    """Test Go method receiver type extraction via _extract_go_receiver."""

    def test_pointer_receiver(self) -> None:
        code = (
            "package main\n"
            "\n"
            "type Server struct {\n"
            "    Port int\n"
            "}\n"
            "\n"
            "// Start launches the server.\n"
            "func (s *Server) Start() error {\n"
            "    return nil\n"
            "}\n"
        )
        result = ts_parse_file("server.go", content=code, language="go")
        assert result is not None
        # Method should be attached to Server class or have parent_class set
        classes = result["classes"]
        server_cls = next((c for c in classes if c["name"] == "Server"), None)
        if server_cls and any(m["name"] == "Start" for m in server_cls.get("methods", [])):
            start = next(m for m in server_cls["methods"] if m["name"] == "Start")
            assert start["parent_class"] == "Server"
        else:
            # Recorded as standalone function with parent_class
            funcs = result["functions"]
            start = next((fn for fn in funcs if fn["name"] == "Start"), None)
            assert start is not None
            assert start["parent_class"] == "Server"

    def test_value_receiver(self) -> None:
        code = (
            "package main\n"
            "\n"
            "type Config struct {\n"
            "    Name string\n"
            "}\n"
            "\n"
            "func (c Config) GetName() string {\n"
            "    return c.Name\n"
            "}\n"
        )
        result = ts_parse_file("config.go", content=code, language="go")
        assert result is not None
        found = False
        for cls in result["classes"]:
            if cls["name"] == "Config":
                for m in cls.get("methods", []):
                    if m["name"] == "GetName":
                        found = True
                        assert m["parent_class"] == "Config"
        if not found:
            for fn in result["functions"]:
                if fn["name"] == "GetName":
                    found = True
                    assert fn["parent_class"] == "Config"
        assert found, "GetName method not found in classes or functions"

    def test_receiver_without_struct_in_same_file(self) -> None:
        """Method whose receiver type is not defined in the same file."""
        code = (
            "package handlers\n"
            "\n"
            "func (h *Handler) ServeHTTP() {}\n"
        )
        result = ts_parse_file("handlers.go", content=code, language="go")
        assert result is not None
        # No Handler class in this file, so method should appear in functions
        funcs = result["functions"]
        serve = next((fn for fn in funcs if fn["name"] == "ServeHTTP"), None)
        assert serve is not None
        assert serve["parent_class"] == "Handler"

    def test_multiple_methods_same_receiver(self) -> None:
        code = (
            "package main\n"
            "\n"
            "type DB struct{}\n"
            "\n"
            "func (d *DB) Connect() error { return nil }\n"
            "func (d *DB) Close() error { return nil }\n"
        )
        result = ts_parse_file("db.go", content=code, language="go")
        assert result is not None
        # Both methods should reference DB
        all_methods = []
        for cls in result["classes"]:
            if cls["name"] == "DB":
                all_methods.extend(cls.get("methods", []))
        for fn in result["functions"]:
            if fn.get("parent_class") == "DB":
                all_methods.append(fn)
        names = [m["name"] for m in all_methods]
        assert "Connect" in names
        assert "Close" in names
        for m in all_methods:
            assert m["parent_class"] == "DB"


# ============================================================
# Go visibility integration (requires tree-sitter-go)
# ============================================================


@pytest.mark.skipif(not _has_grammar("go"), reason="tree-sitter-go not installed")
class TestGoVisibilityIntegration:
    """Test that Go visibility is applied to parsed symbols."""

    def test_exported_vs_unexported_functions(self) -> None:
        code = (
            "package main\n"
            "\n"
            "func PublicFunc() {}\n"
            "func privateFunc() {}\n"
        )
        result = ts_parse_file("vis.go", content=code, language="go")
        assert result is not None
        funcs = {fn["name"]: fn for fn in result["functions"]}
        assert funcs["PublicFunc"]["visibility"] == "public"
        assert funcs["privateFunc"]["visibility"] == "private"

    def test_exported_method_on_receiver(self) -> None:
        code = (
            "package main\n"
            "\n"
            "type Svc struct{}\n"
            "\n"
            "func (s *Svc) Run() {}\n"
            "func (s *Svc) init() {}\n"
        )
        result = ts_parse_file("svc.go", content=code, language="go")
        assert result is not None
        # Collect all methods from classes and functions
        all_methods = {}
        for cls in result["classes"]:
            for m in cls.get("methods", []):
                all_methods[m["name"]] = m
        for fn in result["functions"]:
            if fn.get("parent_class"):
                all_methods[fn["name"]] = fn
        assert all_methods["Run"]["visibility"] == "public"
        assert all_methods["init"]["visibility"] == "private"


# ============================================================
# Go const/var extraction (requires tree-sitter-go)
# ============================================================


@pytest.mark.skipif(not _has_grammar("go"), reason="tree-sitter-go not installed")
class TestGoConstVar:
    """Test Go const/var extraction via var_types config."""

    def test_const_block_extracted(self) -> None:
        code = (
            "package main\n"
            "\n"
            "const (\n"
            "    MaxRetries = 3\n"
            "    DefaultTimeout = 30\n"
            ")\n"
        )
        result = ts_parse_file("consts.go", content=code, language="go")
        assert result is not None
        var_names = result["top_level_vars"]
        assert "MaxRetries" in var_names
        assert "DefaultTimeout" in var_names

    def test_single_const(self) -> None:
        code = (
            "package main\n"
            "\n"
            "const Version = \"1.0.0\"\n"
        )
        result = ts_parse_file("version.go", content=code, language="go")
        assert result is not None
        assert "Version" in result["top_level_vars"]

    def test_var_declaration(self) -> None:
        code = (
            "package main\n"
            "\n"
            "var GlobalConfig = Config{}\n"
        )
        result = ts_parse_file("vars.go", content=code, language="go")
        assert result is not None
        assert "GlobalConfig" in result["top_level_vars"]

    @pytest.mark.xfail(
        reason="Parenthesized var blocks use var_spec_list wrapper; "
        "current code only checks direct children for var_spec",
    )
    def test_var_block(self) -> None:
        code = (
            "package main\n"
            "\n"
            "var (\n"
            "    ErrNotFound = errors.New(\"not found\")\n"
            "    ErrTimeout  = errors.New(\"timeout\")\n"
            ")\n"
        )
        result = ts_parse_file("errors.go", content=code, language="go")
        assert result is not None
        var_names = result["top_level_vars"]
        assert "ErrNotFound" in var_names
        assert "ErrTimeout" in var_names


# ============================================================
# Full integration (requires tree-sitter-go)
# ============================================================


@pytest.mark.skipif(not _has_grammar("go"), reason="tree-sitter-go not installed")
class TestGoFullIntegration:
    """Integration test: parse a realistic Go file and verify all improvements."""

    def test_realistic_go_file(self) -> None:
        code = (
            "package server\n"
            "\n"
            'import "net/http"\n'
            "\n"
            "const DefaultPort = 8080\n"
            "\n"
            "// Server handles HTTP requests.\n"
            "type Server struct {\n"
            "    Port int\n"
            "}\n"
            "\n"
            "// NewServer creates a new Server with the given port.\n"
            "func NewServer(port int) *Server {\n"
            "    return &Server{Port: port}\n"
            "}\n"
            "\n"
            "// Start begins listening for requests.\n"
            "func (s *Server) Start() error {\n"
            "    return http.ListenAndServe(\":8080\", nil)\n"
            "}\n"
            "\n"
            "func (s *Server) stop() {\n"
            "    // internal cleanup\n"
            "}\n"
        )
        result = ts_parse_file("server.go", content=code, language="go")
        assert result is not None

        # Language detected
        assert result["language"] == "go"

        # Imports found
        assert len(result["imports"]) >= 1

        # Const extracted
        assert "DefaultPort" in result["top_level_vars"]

        # Type declaration found
        classes = result["classes"]
        server_cls = next((c for c in classes if c["name"] == "Server"), None)
        assert server_cls is not None
        assert "docstring" in server_cls
        assert "handles HTTP requests" in server_cls["docstring"]

        # NewServer is a top-level function (constructor pattern)
        funcs = {fn["name"]: fn for fn in result["functions"]}
        assert "NewServer" in funcs
        assert funcs["NewServer"]["visibility"] == "public"
        assert "docstring" in funcs["NewServer"]
        assert "creates a new Server" in funcs["NewServer"]["docstring"]

        # Methods: Start and stop attached to Server
        all_methods = {}
        if server_cls:
            for m in server_cls.get("methods", []):
                all_methods[m["name"]] = m
        for fn in result["functions"]:
            if fn.get("parent_class") == "Server":
                all_methods[fn["name"]] = fn

        assert "Start" in all_methods
        assert all_methods["Start"]["visibility"] == "public"
        assert all_methods["Start"]["parent_class"] == "Server"
        # Start has a doc comment
        assert "docstring" in all_methods["Start"]
        assert "begins listening" in all_methods["Start"]["docstring"]

        assert "stop" in all_methods
        assert all_methods["stop"]["visibility"] == "private"
        assert all_methods["stop"]["parent_class"] == "Server"

    def test_interface_methods(self) -> None:
        code = (
            "package main\n"
            "\n"
            "// Handler defines a request handler.\n"
            "type Handler interface {\n"
            "    Handle(req Request) Response\n"
            "    Close() error\n"
            "}\n"
        )
        result = ts_parse_file("iface.go", content=code, language="go")
        assert result is not None
        classes = result["classes"]
        handler = next((c for c in classes if c["name"] == "Handler"), None)
        assert handler is not None
        method_names = [m["name"] for m in handler.get("methods", [])]
        assert "Handle" in method_names
        assert "Close" in method_names
        # Doc comment on interface type
        assert "docstring" in handler
        assert "request handler" in handler["docstring"]

    def test_return_format_keys(self) -> None:
        """Verify the returned dict has all expected top-level keys."""
        code = "package main\n\nfunc main() {}\n"
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        assert "functions" in result
        assert "classes" in result
        assert "imports" in result
        assert "top_level_vars" in result
        assert "line_count" in result
        assert "language" in result
        assert isinstance(result["functions"], list)
        assert isinstance(result["classes"], list)
        assert isinstance(result["imports"], list)
        assert isinstance(result["top_level_vars"], list)
        assert isinstance(result["line_count"], int)

    def test_function_dict_fields(self) -> None:
        """Verify function dicts have all expected fields."""
        code = (
            "package main\n"
            "\n"
            "func Hello() {}\n"
        )
        result = ts_parse_file("main.go", content=code, language="go")
        assert result is not None
        fn = result["functions"][0]
        assert "name" in fn
        assert "parameters" in fn
        assert "return_type" in fn
        assert "start_line" in fn
        assert "end_line" in fn
        assert "is_async" in fn
        assert "decorators" in fn
        assert "visibility" in fn
        assert "parent_class" in fn
