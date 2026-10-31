# Metal Language Support

Attocode provides code intelligence for Apple Metal Shading Language (`.metal`) files used in GPU-accelerated workloads.

## Overview

Metal Shading Language (MSL) is Apple's GPU programming language, based on C++14 with extensions for parallel compute, graphics, and ray tracing. It is used in projects like [synapse](https://github.com/eren23/synapse) for GPU-accelerated LLM inference on Apple Silicon.

Metal files (`.metal`) are not natively supported by most editors or code intelligence tools. Attocode maps `.metal` files to the C++ tree-sitter parser, enabling symbol extraction, cross-references, search, and repo map integration.

## Code Intelligence

### How It Works

Metal files are mapped to the C++ parser at every layer of the code intelligence stack:

| Layer | File | Mapping |
|-------|------|---------|
| AST extraction | `codebase_ast.py` | `LANG_EXTENSIONS[".metal"] = "cpp"` |
| Tree-sitter config | `ts_parser.py` | `LANGUAGE_CONFIGS["metal"] = LANGUAGE_CONFIGS["cpp"]` |
| Indexing parser | `indexing/parser.py` | `_EXT_TO_LANG[".metal"] = "cpp"` |
| HTTP API | `api/utils.py` | `LANG_MAP[".metal"] = "cpp"` |

### What Works

- **Symbol extraction** --- functions, structs, enums, unions, and `#include` directives are extracted from Metal files.
- **Cross-references** --- definitions and references in Metal files are indexed and queryable.
- **Search** --- Metal files appear in `fast_search`, `semantic_search`, and `search_symbols` results.
- **Repo map** --- Metal files and their symbols appear in `repo_map` and `repo_map_ranked` output.
- **Impact analysis** --- changes to Metal files are tracked in the dependency graph.
- **Churn analysis** --- Metal files participate in `churn_hotspots` and `change_coupling` analysis.

### What Metal Constructs Look Like in the AST

Since the C++ parser handles Metal files, Metal-specific syntax maps to generic C++ AST nodes:

| Metal Construct | C++ AST Node | Example |
|----------------|-------------|---------|
| `kernel void func(...)` | `function_definition` | Kernel entry points appear as regular functions |
| `struct Params { ... }` | `struct_specifier` | Unchanged from C++ |
| `device float* buf` | parameter with type | `device` parsed as identifier, not address-space qualifier |
| `[[buffer(0)]]` | `attribute_declaration` | Parsed as C++ attribute, not Metal-specific |
| `#include <metal_stdlib>` | `preproc_include` | Works identically to C++ |

## Known Shortcomings

- **No Metal-aware AST** --- the C++ parser does not understand Metal semantics. `kernel void` is just a function, not a GPU entry point. There is no distinction between kernel, vertex, and fragment functions in the symbol index.
- **Address space qualifiers are invisible** --- `device`, `constant`, and `threadgroup` appear as regular identifiers, not storage class specifiers. The AST cannot track which buffers are in device vs. threadgroup memory.
- **Attribute validation missing** --- `[[buffer(0)]]` is parsed as a generic C++ attribute. Invalid Metal attribute names (e.g., `[[nonexistent(0)]]`) would not be flagged.
- **No Metal stdlib awareness** --- built-in functions like `threadgroup_barrier`, `simdgroup_load`, and math functions are not distinguishable from user-defined functions in the AST.

## Future Updates

### Near-Term

- **Broader C-family alias mapping** --- generalize the `.metal` → C++ pattern for CUDA (`.cu`), OpenCL (`.cl`), HLSL (`.hlsl`), and GLSL (`.glsl`, `.frag`, `.vert`). These are all C/C++-derived languages that would benefit from the same approach.

### Medium-Term

- **Metal-specific symbol kinds** --- post-process C++ AST output to detect `kernel`/`vertex`/`fragment` qualifiers and annotate symbols accordingly. This would enable filtering GPU entry points in symbol search.
- **CodeMirror Metal mode** --- add Metal syntax highlighting to the attocode frontend.

### Long-Term

- **Dedicated `tree-sitter-metal` grammar** --- a proper Metal parser that understands address spaces, function qualifiers, attribute bindings, and SIMD types as first-class AST nodes. No such grammar exists in the tree-sitter ecosystem today.
- **Metal LSP** --- language server providing go-to-definition, hover documentation for Metal stdlib functions, diagnostic checks for common Metal errors (mismatched buffer indices, invalid threadgroup sizes).

## Related

- [AST & Code Intelligence](../ast-and-code-intelligence.md) --- full language support table and code intelligence architecture
