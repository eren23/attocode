"""Tests for codebase AST analysis — enhanced types and incremental updates."""

from __future__ import annotations

from pathlib import Path

import pytest

from attocode.integrations.context.codebase_ast import (
    ClassDef,
    DependencyChanges,
    FileAST,
    FileChangeResult,
    FunctionDef,
    ImportDef,
    ParamDef,
    PropertyDef,
    SymbolChange,
    diff_file_ast,
    diff_imports,
    parse_file,
    parse_javascript,
    parse_python,
)


# ============================================================
# ParamDef Extraction Tests
# ============================================================


class TestParamDefExtraction:
    def test_simple_params(self) -> None:
        code = "def foo(a, b, c):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.params == ["a", "b", "c"]
        assert len(func.parameters) == 3
        assert func.parameters[0].name == "a"
        assert func.parameters[0].type_annotation == ""
        assert func.parameters[0].default_value == ""

    def test_typed_params(self) -> None:
        code = "def foo(a: int, b: str, c: float = 3.14):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.params == ["a", "b", "c"]
        assert func.parameters[0].type_annotation == "int"
        assert func.parameters[1].type_annotation == "str"
        assert func.parameters[2].type_annotation == "float"
        assert func.parameters[2].default_value == "3.14"

    def test_default_values(self) -> None:
        code = 'def foo(x=42, y="hello", z=None):\n    pass\n'
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.parameters[0].default_value == "42"
        assert func.parameters[1].default_value == '"hello"'
        assert func.parameters[2].default_value == "None"

    def test_star_args(self) -> None:
        code = "def foo(*args):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.parameters[0].name == "args"
        assert func.parameters[0].is_rest is True

    def test_double_star_kwargs(self) -> None:
        code = "def foo(**kwargs):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.parameters[0].name == "kwargs"
        assert func.parameters[0].is_kwargs is True

    def test_kwonly_params(self) -> None:
        code = "def foo(a, *, b, c=1):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.parameters[0].name == "a"
        assert func.parameters[0].is_kwonly is False
        assert func.parameters[1].name == "b"
        assert func.parameters[1].is_kwonly is True
        assert func.parameters[2].name == "c"
        assert func.parameters[2].is_kwonly is True

    def test_complex_type_annotation(self) -> None:
        code = "def foo(x: dict[str, int], y: list[tuple[int, ...]]):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.parameters[0].type_annotation == "dict[str, int]"
        assert func.parameters[1].type_annotation == "list[tuple[int, ...]]"

    def test_full_signature(self) -> None:
        code = "def foo(self, a: int, *args: str, key: bool = False, **kwargs: Any):\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.params == ["self", "a", "args", "key", "kwargs"]
        params = func.parameters
        assert params[0].name == "self"
        assert params[1].type_annotation == "int"
        assert params[2].is_rest is True
        assert params[2].type_annotation == "str"
        assert params[3].is_kwonly is True
        assert params[3].default_value == "False"
        assert params[4].is_kwargs is True

    def test_no_params(self) -> None:
        code = "def foo():\n    pass\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.params == []
        assert func.parameters == []


# ============================================================
# Visibility Detection Tests
# ============================================================


class TestVisibilityDetection:
    def test_public_function(self) -> None:
        code = "def public_func():\n    pass\n"
        ast = parse_python(code)
        assert ast.functions[0].visibility == "public"

    def test_private_function(self) -> None:
        code = "def _private_func():\n    pass\n"
        ast = parse_python(code)
        assert ast.functions[0].visibility == "private"

    def test_name_mangled_function(self) -> None:
        code = "class Foo:\n    def __mangled(self):\n        pass\n"
        ast = parse_python(code)
        method = ast.classes[0].methods[0]
        assert method.visibility == "name_mangled"

    def test_dunder_method_is_public(self) -> None:
        code = "class Foo:\n    def __init__(self):\n        pass\n"
        ast = parse_python(code)
        method = ast.classes[0].methods[0]
        assert method.visibility == "public"


# ============================================================
# Generator Detection Tests
# ============================================================


class TestGeneratorDetection:
    def test_generator_function(self) -> None:
        code = "def gen():\n    yield 1\n    yield 2\n"
        ast = parse_python(code)
        assert ast.functions[0].is_generator is True

    def test_non_generator_function(self) -> None:
        code = "def normal():\n    return 1\n"
        ast = parse_python(code)
        assert ast.functions[0].is_generator is False

    def test_async_generator(self) -> None:
        code = "async def agen():\n    yield 1\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.is_async is True
        assert func.is_generator is True


# ============================================================
# Decorator Flag Tests
# ============================================================


class TestDecoratorFlags:
    def test_staticmethod(self) -> None:
        code = "class Foo:\n    @staticmethod\n    def bar():\n        pass\n"
        ast = parse_python(code)
        method = ast.classes[0].methods[0]
        assert method.is_staticmethod is True
        assert method.is_classmethod is False

    def test_classmethod(self) -> None:
        code = "class Foo:\n    @classmethod\n    def bar(cls):\n        pass\n"
        ast = parse_python(code)
        method = ast.classes[0].methods[0]
        assert method.is_classmethod is True
        assert method.is_staticmethod is False

    def test_property(self) -> None:
        code = "class Foo:\n    @property\n    def value(self):\n        return self._value\n"
        ast = parse_python(code)
        method = ast.classes[0].methods[0]
        assert method.is_property is True

    def test_abstractmethod_marks_class_abstract(self) -> None:
        code = "class Foo:\n    @abstractmethod\n    def bar(self):\n        pass\n"
        ast = parse_python(code)
        assert ast.classes[0].is_abstract is True


# ============================================================
# Class Properties Tests
# ============================================================


class TestClassProperties:
    def test_init_properties(self) -> None:
        code = (
            "class Foo:\n"
            "    def __init__(self):\n"
            "        self.name = ''\n"
            "        self.count = 0\n"
            "        self._internal = None\n"
        )
        ast = parse_python(code)
        props = ast.classes[0].properties
        names = [p.name for p in props]
        assert "name" in names
        assert "count" in names
        assert "_internal" in names
        # Check visibility
        internal = next(p for p in props if p.name == "_internal")
        assert internal.visibility == "private"

    def test_class_level_annotations(self) -> None:
        code = (
            "class Foo:\n"
            "    x: int\n"
            "    y: str = 'hello'\n"
        )
        ast = parse_python(code)
        props = ast.classes[0].properties
        assert len(props) >= 2
        x = next(p for p in props if p.name == "x")
        assert x.type_annotation == "int"
        assert x.has_default is False
        y = next(p for p in props if p.name == "y")
        assert y.has_default is True


# ============================================================
# Abstract Class Detection Tests
# ============================================================


class TestAbstractClassDetection:
    def test_abc_base(self) -> None:
        code = "class MyABC(ABC):\n    pass\n"
        ast = parse_python(code)
        assert ast.classes[0].is_abstract is True

    def test_metaclass_abcmeta(self) -> None:
        code = "class MyABC(metaclass=ABCMeta):\n    pass\n"
        ast = parse_python(code)
        cls = ast.classes[0]
        assert cls.is_abstract is True
        assert cls.metaclass == "ABCMeta"
        # metaclass=ABCMeta should be filtered from bases
        assert "metaclass=ABCMeta" not in cls.bases

    def test_not_abstract(self) -> None:
        code = "class Foo:\n    pass\n"
        ast = parse_python(code)
        assert ast.classes[0].is_abstract is False


# ============================================================
# PEP 695 Type Params Tests
# ============================================================


class TestTypeParams:
    def test_function_type_params(self) -> None:
        code = "def foo[T](x: T) -> T:\n    return x\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.type_params == ["T"]
        assert func.parameters[0].type_annotation == "T"

    def test_multiple_type_params(self) -> None:
        code = "def foo[T, U](x: T, y: U) -> T:\n    return x\n"
        ast = parse_python(code)
        func = ast.functions[0]
        assert func.type_params == ["T", "U"]


# ============================================================
# diff_file_ast Tests
# ============================================================


class TestDiffFileAST:
    def test_added_function(self) -> None:
        old = FileAST(path="test.py", language="python")
        new = FileAST(
            path="test.py", language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=2)],
        )
        changes = diff_file_ast(old, new)
        assert len(changes) == 1
        assert changes[0].kind == "added"
        assert changes[0].symbol_name == "foo"

    def test_removed_function(self) -> None:
        old = FileAST(
            path="test.py", language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=2)],
        )
        new = FileAST(path="test.py", language="python")
        changes = diff_file_ast(old, new)
        assert len(changes) == 1
        assert changes[0].kind == "removed"
        assert changes[0].symbol_name == "foo"
        assert changes[0].previous is not None

    def test_modified_function(self) -> None:
        old = FileAST(
            path="test.py", language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=2, params=["a"])],
        )
        new = FileAST(
            path="test.py", language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=3, params=["a", "b"])],
        )
        changes = diff_file_ast(old, new)
        assert len(changes) == 1
        assert changes[0].kind == "modified"

    def test_unchanged_function(self) -> None:
        func = FunctionDef(name="foo", start_line=1, end_line=2, params=["a"])
        old = FileAST(path="test.py", language="python", functions=[func])
        new = FileAST(
            path="test.py", language="python",
            functions=[FunctionDef(name="foo", start_line=1, end_line=2, params=["a"])],
        )
        changes = diff_file_ast(old, new)
        assert len(changes) == 0

    def test_class_method_changes(self) -> None:
        old_cls = ClassDef(
            name="Foo", start_line=1, end_line=10,
            methods=[FunctionDef(name="bar", start_line=2, end_line=4)],
        )
        new_cls = ClassDef(
            name="Foo", start_line=1, end_line=12,
            methods=[
                FunctionDef(name="bar", start_line=2, end_line=4),
                FunctionDef(name="baz", start_line=5, end_line=7),
            ],
        )
        old = FileAST(path="test.py", language="python", classes=[old_cls])
        new = FileAST(path="test.py", language="python", classes=[new_cls])
        changes = diff_file_ast(old, new)
        # class modified (new method), method added
        kinds = [(c.kind, c.symbol_name) for c in changes]
        assert ("modified", "Foo") in kinds
        assert ("added", "Foo.baz") in kinds


# ============================================================
# diff_imports Tests
# ============================================================


class TestDiffImports:
    def test_added_import(self) -> None:
        old = FileAST(path="test.py", language="python")
        new = FileAST(
            path="test.py", language="python",
            imports=[ImportDef(module="os", is_from=False)],
        )
        changes = diff_imports(old, new)
        assert len(changes.added) == 1
        assert changes.added[0].module == "os"
        assert len(changes.removed) == 0

    def test_removed_import(self) -> None:
        old = FileAST(
            path="test.py", language="python",
            imports=[ImportDef(module="os", is_from=False)],
        )
        new = FileAST(path="test.py", language="python")
        changes = diff_imports(old, new)
        assert len(changes.removed) == 1
        assert len(changes.added) == 0

    def test_no_changes(self) -> None:
        imp = ImportDef(module="os", is_from=False)
        old = FileAST(path="test.py", language="python", imports=[imp])
        new = FileAST(
            path="test.py", language="python",
            imports=[ImportDef(module="os", is_from=False)],
        )
        changes = diff_imports(old, new)
        assert len(changes.added) == 0
        assert len(changes.removed) == 0


# ============================================================
# JavaScript Parameter Type Tests
# ============================================================


class TestJSParameterTypes:
    def test_js_params_with_types(self) -> None:
        code = "function greet(name: string, age: number): void {\n}\n"
        ast = parse_javascript(code, "test.ts")
        func = ast.functions[0]
        assert func.params == ["name", "age"]
        assert func.parameters[0].type_annotation == "string"
        assert func.parameters[1].type_annotation == "number"

    def test_js_params_with_defaults(self) -> None:
        code = 'function greet(name = "world"): void {\n}\n'
        ast = parse_javascript(code, "test.js")
        func = ast.functions[0]
        assert func.parameters[0].default_value == '"world"'

    def test_js_rest_params(self) -> None:
        code = "function sum(...nums: number[]): number {\n}\n"
        ast = parse_javascript(code, "test.ts")
        func = ast.functions[0]
        assert func.parameters[0].is_rest is True
        assert func.parameters[0].name == "nums"

    def test_js_class_endline(self) -> None:
        code = "class Foo {\n  bar() {}\n  baz() {}\n}\n"
        ast = parse_javascript(code, "test.js")
        cls = ast.classes[0]
        assert cls.end_line == 4  # closing brace on line 4

    def test_ts_abstract_class(self) -> None:
        code = "export abstract class Base {\n  abstract foo(): void;\n}\n"
        ast = parse_javascript(code, "test.ts")
        cls = ast.classes[0]
        assert cls.is_abstract is True


# ============================================================
# Incremental Update Pipeline Tests
# ============================================================


class TestIncrementalUpdatePipeline:
    def test_mark_and_update_dirty(self, tmp_path: Path) -> None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        # Create initial file
        (tmp_path / "app.py").write_text("def foo():\n    pass\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()

        # Modify file
        (tmp_path / "app.py").write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")

        # Mark dirty and update
        mgr.mark_file_dirty(str(tmp_path / "app.py"))
        results = mgr.update_dirty_files()

        assert len(results) >= 1
        assert results[0].was_incremental is True

    def test_invalidate_clears_cache(self, tmp_path: Path) -> None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        (tmp_path / "app.py").write_text("def foo():\n    pass\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        repo_map = mgr.get_repo_map()
        assert repo_map is not None

        mgr.invalidate_file(str(tmp_path / "app.py"))
        # Repo map cache should be cleared
        assert mgr._repo_map is None

    def test_dirty_files_cleared_after_update(self, tmp_path: Path) -> None:
        from attocode.integrations.context.codebase_context import CodebaseContextManager

        (tmp_path / "app.py").write_text("x = 1\n")

        mgr = CodebaseContextManager(root_dir=str(tmp_path))
        mgr.discover_files()
        mgr.mark_file_dirty(str(tmp_path / "app.py"))
        assert len(mgr._dirty_files) == 1

        mgr.update_dirty_files()
        assert len(mgr._dirty_files) == 0


# ============================================================
# CodeAnalyzer invalidate/update_file Tests
# ============================================================


class TestCodeAnalyzerInvalidateAndUpdate:
    def test_invalidate_removes_cache_entry(self, tmp_path: Path) -> None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        f = tmp_path / "test.py"
        f.write_text("def foo(): pass\n")

        analyzer = CodeAnalyzer()
        analyzer.analyze_file(str(f))
        assert analyzer.cache_stats["entries"] == 1

        analyzer.invalidate(str(f))
        assert analyzer.cache_stats["entries"] == 0

    def test_invalidate_nonexistent_is_noop(self) -> None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        analyzer = CodeAnalyzer()
        analyzer.invalidate("/nonexistent/path.py")
        assert analyzer.cache_stats["entries"] == 0

    def test_update_file_with_content(self, tmp_path: Path) -> None:
        from attocode.integrations.context.code_analyzer import CodeAnalyzer

        f = tmp_path / "test.py"
        f.write_text("def foo(): pass\n")

        analyzer = CodeAnalyzer()
        result = analyzer.update_file(
            str(f), "def bar(): pass\ndef baz(): pass\n"
        )
        assert result.line_count == 2
        names = [c.name for c in result.chunks]
        assert "bar" in names
        assert "baz" in names

        # Should be in cache now
        assert analyzer.cache_stats["entries"] == 1
