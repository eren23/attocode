"""Hand-authored static workflows: declared links must not leak across namesakes.

These fixtures check navigation evidence, not execution of foreign-language tests.
Removing import ownership or merging namesake references must fail these cases.
"""

import pytest
from attocode_intel.gateway import OperationGateway

# Each tuple independently records the written definition range/source and the
# cross-file call site. No parser/resolver helper constructs expected answers.
WORKFLOWS = {
    "python": {
        "files": {
            "codec.py": "def encode(value):\n    return value + 1\n\ndef decode(value):\n    return value - 1\n",
            "unrelated.py": "def encode(value):\n    return value * 2\n",
            "tests/test_encode.py": "from codec import encode\ndef test_encode():\n    assert encode(2) == 3\n",
            "tests/test_decode.py": "from codec import decode\ndef test_decode():\n    assert decode(3) == 2\n",
            "tests/test_unrelated.py": "from unrelated import encode\ndef test_unrelated():\n    assert encode(2) == 4\n",
        },
        "cases": [
            ("encode", "codec.py", 1, 2, "def encode(value):\n    return value + 1", "tests/test_encode.py", 3),
            ("decode", "codec.py", 4, 5, "def decode(value):\n    return value - 1", "tests/test_decode.py", 3),
            ("encode", "unrelated.py", 1, 2, "def encode(value):\n    return value * 2", "tests/test_unrelated.py", 3),
        ],
    },
    "typescript": {
        "files": {
            "codec.ts": "export function encode(value: number) { return value + 1; }\n\nexport function decode(value: number) { return value - 1; }\n",
            "unrelated.ts": "export function encode(value: number) { return value * 2; }\n",
            "tests/encode.test.ts": "import { encode } from '../codec';\nfunction test_encode() {\n  return encode(2);\n}\n",
            "tests/decode.test.ts": "import { decode } from '../codec';\nfunction test_decode() {\n  return decode(3);\n}\n",
            "tests/unrelated.test.ts": "import { encode } from '../unrelated';\nfunction test_unrelated() {\n  return encode(2);\n}\n",
        },
        "cases": [
            ("encode", "codec.ts", 1, 1, "export function encode(value: number) { return value + 1; }", "tests/encode.test.ts", 3),
            ("decode", "codec.ts", 3, 3, "export function decode(value: number) { return value - 1; }", "tests/decode.test.ts", 3),
            ("encode", "unrelated.ts", 1, 1, "export function encode(value: number) { return value * 2; }", "tests/unrelated.test.ts", 3),
        ],
    },
    "go": {
        "files": {
            "go.mod": "module example.test/workflow\n\ngo 1.22\n",
            "codec/codec.go": "package codec\nfunc Encode(value int) int { return value + 1 }\n\nfunc Decode(value int) int { return value - 1 }\n",
            "unrelated/codec.go": "package unrelated\nfunc Encode(value int) int { return value * 2 }\n",
            "tests/encode_test.go": 'package tests\nimport "example.test/workflow/codec"\nfunc TestEncode() {\n codec.Encode(2)\n}\n',
            "tests/decode_test.go": 'package tests\nimport "example.test/workflow/codec"\nfunc TestDecode() {\n codec.Decode(3)\n}\n',
            "tests/unrelated_test.go": 'package tests\nimport "example.test/workflow/unrelated"\nfunc TestUnrelated() {\n unrelated.Encode(2)\n}\n',
        },
        "cases": [
            ("Encode", "codec/codec.go", 2, 2, "func Encode(value int) int { return value + 1 }", "tests/encode_test.go", 4),
            ("Decode", "codec/codec.go", 4, 4, "func Decode(value int) int { return value - 1 }", "tests/decode_test.go", 4),
            ("Encode", "unrelated/codec.go", 2, 2, "func Encode(value int) int { return value * 2 }", "tests/unrelated_test.go", 4),
        ],
    },
    "rust": {
        "files": {
            "Cargo.toml": '[package]\nname="workflow"\nversion="0.1.0"\nedition="2021"\n',
            "src/lib.rs": "pub mod codec;\npub mod unrelated;\n#[cfg(test)]\nmod test_encode;\n#[cfg(test)]\nmod test_decode;\n#[cfg(test)]\nmod test_unrelated;\n",
            "src/codec.rs": "pub fn encode(value: i32) -> i32 { value + 1 }\n\npub fn decode(value: i32) -> i32 { value - 1 }\n",
            "src/unrelated.rs": "pub fn encode(value: i32) -> i32 { value * 2 }\n",
            "src/test_encode.rs": "use crate::codec::encode;\n#[test]\nfn test_encode() {\n let _value = encode(2);\n}\n",
            "src/test_decode.rs": "use crate::codec::decode;\n#[test]\nfn test_decode() {\n let _value = decode(3);\n}\n",
            "src/test_unrelated.rs": "use crate::unrelated::encode;\n#[test]\nfn test_unrelated() {\n let _value = encode(2);\n}\n",
        },
        "cases": [
            ("encode", "src/codec.rs", 1, 1, "pub fn encode(value: i32) -> i32 { value + 1 }", "src/test_encode.rs", 4),
            ("decode", "src/codec.rs", 3, 3, "pub fn decode(value: i32) -> i32 { value - 1 }", "src/test_decode.rs", 4),
            ("encode", "src/unrelated.rs", 1, 1, "pub fn encode(value: i32) -> i32 { value * 2 }", "src/test_unrelated.rs", 4),
        ],
    },
    "ruby": {
        "files": {
            "lib/codec.rb": "def encode(value)\n  value + 1\nend\n\ndef decode(value)\n  value - 1\nend\n",
            "lib/unrelated.rb": "def encode(value)\n  value * 2\nend\n",
            "spec/encode_spec.rb": 'require_relative "../lib/codec"\ndef test_encode\n  encode(2)\nend\n',
            "spec/decode_spec.rb": 'require_relative "../lib/codec"\ndef test_decode\n  decode(3)\nend\n',
            "spec/dynamic_spec.rb": "require_relative selected_path\ndef test_dynamic\n  encode(2)\nend\n",
            "spec/unrelated_spec.rb": 'require_relative "../lib/unrelated"\ndef test_unrelated\n  encode(2)\nend\n',
        },
        "cases": [
            ("encode", "lib/codec.rb", 1, 3, "def encode(value)\n  value + 1\nend", "spec/encode_spec.rb", 3),
            ("decode", "lib/codec.rb", 5, 7, "def decode(value)\n  value - 1\nend", "spec/decode_spec.rb", 3),
            ("encode", "lib/unrelated.rb", 1, 3, "def encode(value)\n  value * 2\nend", "spec/unrelated_spec.rb", 3),
        ],
    },
    "elixir": {
        "files": {
            "lib/codec.ex": "defmodule Wire.Codec do\n  def encode(value), do: value + 1\n  def decode(value), do: value - 1\nend\n",
            "lib/unrelated.ex": "defmodule Other.Codec do\n  def encode(value), do: value * 2\nend\n",
            "test/encode_test.exs": "defmodule EncodeTest do\n  alias Wire.Codec\n  def test_encode() do\n    Codec.encode(2)\n  end\nend\n",
            "test/decode_test.exs": "defmodule DecodeTest do\n  alias Wire.Codec\n  def test_decode() do\n    Codec.decode(3)\n  end\nend\n",
            "test/unrelated_test.exs": "defmodule UnrelatedTest do\n  alias Other.Codec\n  def test_unrelated() do\n    Codec.encode(2)\n  end\nend\n",
        },
        "cases": [
            ("encode", "lib/codec.ex", 2, 2, "  def encode(value), do: value + 1", "test/encode_test.exs", 4),
            ("decode", "lib/codec.ex", 3, 3, "  def decode(value), do: value - 1", "test/decode_test.exs", 4),
            ("encode", "lib/unrelated.ex", 2, 2, "  def encode(value), do: value * 2", "test/unrelated_test.exs", 4),
        ],
    },
}


IMPORTS = {
    "python": [("codec", 1), ("codec", 1), ("unrelated", 1)],
    "typescript": [("../codec", 1), ("../codec", 1), ("../unrelated", 1)],
    "go": [("example.test/workflow/codec", 2), ("example.test/workflow/codec", 2),
           ("example.test/workflow/unrelated", 2)],
    "rust": [("crate::codec::encode", 1), ("crate::codec::decode", 1),
             ("crate::unrelated::encode", 1)],
    "ruby": [("../lib/codec", 1), ("../lib/codec", 1), ("../lib/unrelated", 1)],
    "elixir": [("Wire.Codec", 2), ("Wire.Codec", 2), ("Other.Codec", 2)],
}


@pytest.mark.parametrize("language", WORKFLOWS)
@pytest.mark.parametrize("relationship", [0, 1, 2], ids=["encode", "decode", "same_name_control"])
async def test_declared_workflow_links_and_same_name_control(tmp_path, monkeypatch, language, relationship):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    workflow = WORKFLOWS[language]
    for name, text in workflow["files"].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    symbol, target, start, end, source, caller, call_line = workflow["cases"][relationship]
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        response = await gateway.execute("inspect_symbol", {
            "symbol_name": symbol, "file_path": target, "line": start,
        })
        assert not response.isError, response.content
        data = response.structuredContent["data"]
        assert data["status"] == "found"
        assert (data["definition"]["file_path"], data["definition"]["start_line"],
                data["definition"]["end_line"]) == (target, start, end)
        assert data["source"]["text"] == source
        calls = {(ref["file_path"], ref["line"]) for ref in data["references"] if ref["ref_kind"] == "call"}
        assert calls == {(caller, call_line)}, data
        assert all(ref["resolution"] in {"import_binding", "same_file"} for ref in data["references"])
        linked_tests = {row["file_path"] for row in data["tests"]
                        if row["evidence"]["selected_symbol_reference"]}
        assert linked_tests == {caller}, data["tests"]
        deps_response = await gateway.execute("dependencies", {"path": target})
        assert not deps_response.isError
        imported_by = set(deps_response.structuredContent["data"]["imported_by"])
        expected_importers = {workflow["cases"][2][5]} if relationship == 2 else {
            workflow["cases"][0][5], workflow["cases"][1][5]}
        if language == "rust":
            expected_importers.add("src/lib.rs")
        assert imported_by == expected_importers
        service = next(iter(gateway._stores.values()))["service"]
        caller_ast = service._get_ast_service()._ast_cache[caller]
        assert [(entry.module, entry.line) for entry in caller_ast.imports] == [IMPORTS[language][relationship]]
        # Same-name evidence may be shown as candidates; it must stay explicitly
        # unresolved and must never be promoted into selected-symbol callers.
        if language == "ruby" and relationship in {0, 2}:
            assert ("spec/dynamic_spec.rb", 3) in {
                (row["file_path"], row["line"]) for row in data["reference_candidates"]
            }
            dynamic_ast = service._get_ast_service()._ast_cache["spec/dynamic_spec.rb"]
            assert dynamic_ast.imports == []
        for row in data["reference_candidates"]:
            assert row["resolution"] == "same_name_candidate"
        assert response.structuredContent["metadata"]["analysis"]["absence_proven"] is False
        assert response.structuredContent["metadata"]["analysis"]["precision"]["status"] == "disabled"
    finally:
        await gateway.close()


def test_elixir_declaration_heads_are_not_calls_but_bodies_and_guards_are():
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates

    content = (
        "defmodule Wire.Codec do\n"
        "  def encode(value), do: encode_impl(value)\n"
        "  defp encode_impl(value) do\n"
        "    encode(value)\n"
        "  end\n"
        "  def guarded(value) when is_integer(value), do: encode(value)\n"
        "  def recurse(value), do: recurse(value)\n"
        "end\n"
    )
    actual = reference_candidates("codec.ex", content, "elixir")
    selected = [row for row in actual if row[0] in {
        "encode", "encode_impl", "guarded", "is_integer", "recurse",
    }]
    assert selected == [
        ("encode_impl", "call", 2),
        ("encode", "call", 4),
        ("is_integer", "call", 6),
        ("encode", "call", 6),
        ("recurse", "call", 7),
    ]


def test_ruby_only_literal_receiverless_requires_are_imports():
    from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file

    source = (
        'require_relative "../lib/codec"\n'
        'require_relative selected_path\n'
        'object.require_relative "../lib/unrelated"\n'
        'encode(2)\n'
    )
    parsed = ts_parse_file("spec/codec_spec.rb", source)
    assert [(row["module"], row["start_line"]) for row in parsed["imports"]] == [
        ("../lib/codec", 1),
    ]


def test_elixir_guarded_definition_heads_preserve_names_spans_and_calls():
    from attocode_intel._internal.integrations.context.syntax_evidence import reference_candidates
    from attocode_intel._internal.integrations.context.ts_parser import ts_parse_file

    source = (
        "defmodule Wire.Codec do\n"
        "  def encode(value, opts \\\\ []) when is_integer(value) do\n"
        "    finish(value, opts)\n"
        "  end\n"
        "  defp finish(value, _opts) when is_integer(value), do: value\n"
        "end\n"
    )
    parsed = ts_parse_file("lib/codec.ex", source)
    assert [(f["name"], f["parent_class"], f["start_line"], f["end_line"], f["visibility"])
            for f in parsed["functions"]] == [
        ("encode", "Wire.Codec", 2, 4, "public"),
        ("finish", "Wire.Codec", 5, 5, "private"),
    ]
    assert [r for r in reference_candidates("lib/codec.ex", source, "elixir")
            if r[0] in {"encode", "finish", "is_integer"}] == [
        ("is_integer", "call", 2),
        ("finish", "call", 3),
        ("is_integer", "call", 5),
    ]


async def test_elixir_guarded_selected_definition_links_real_body_call(tmp_path, monkeypatch):
    monkeypatch.setenv("ATTOCODE_INTEL_PRECISION", "off")
    source = (
        "defmodule Wire.Codec do\n"
        "  def encode(value) when is_integer(value) do\n"
        "    finish(value)\n"
        "  end\n"
        "  defp finish(value) when is_integer(value), do: value\n"
        "end\n"
    )
    (tmp_path / "codec.ex").write_text(source)
    (tmp_path / "codec_test.exs").write_text(
        "defmodule CodecTest do\n"
        "  alias Wire.Codec\n"
        "  def test_encode(), do: Codec.encode(2)\n"
        "end\n"
    )
    gateway = OperationGateway(str(tmp_path), "daily", watch=False)
    try:
        for symbol, start, end, caller, call_line in [
            ("encode", 2, 4, "codec_test.exs", 3),
            ("finish", 5, 5, "codec.ex", 3),
        ]:
            response = await gateway.execute("inspect_symbol", {
                "symbol_name": symbol, "file_path": "codec.ex", "line": start,
            })
            assert not response.isError, response.content
            data = response.structuredContent["data"]
            assert data["status"] == "found"
            assert (data["definition"]["qualified_name"], data["definition"]["start_line"],
                    data["definition"]["end_line"]) == (symbol, start, end)
            assert data["source"]["text"] == "\n".join(source.splitlines()[start - 1:end])
            assert {(r["file_path"], r["line"]) for r in data["references"]
                    if r["ref_kind"] == "call"} == {(caller, call_line)}
    finally:
        await gateway.close()
