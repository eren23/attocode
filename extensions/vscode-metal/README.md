# Metal Shading Language - VS Code Extension

Syntax highlighting for Apple Metal Shading Language (`.metal`) files.

## Features

- Full syntax highlighting for Metal Shading Language (MSL)
- Metal-specific keywords: `kernel`, `vertex`, `fragment`, `compute`
- Address space qualifiers: `device`, `constant`, `threadgroup`, `thread`
- Vector/matrix types: `float4`, `half3`, `float4x4`, `simdgroup_float8x8`
- Texture types: `texture2d`, `depth2d`, `texture_buffer`
- Attribute syntax: `[[buffer(0)]]`, `[[thread_position_in_grid]]`
- SIMD group operations and barriers
- Atomic operations
- Built-in math functions
- C++14 base syntax (comments, strings, preprocessor, control flow)

## Install

Package the extension first:

```bash
cd extensions/vscode-metal
npx @vscode/vsce package
```

Then install the `.vsix`:

```bash
# VS Code
code --install-extension metal-shading-language-0.1.0.vsix

# Cursor
cursor --install-extension metal-shading-language-0.1.0.vsix
```

## Known Shortcomings

- **Standalone grammar** --- the TextMate grammar defines its own C++ base patterns rather than inheriting from VS Code's built-in `source.cpp`. Edge cases in deeply nested C++ template syntax may not highlight perfectly.
- **No LSP features** --- this extension provides syntax highlighting only. There is no go-to-definition, hover, diagnostics, or auto-completion for Metal APIs.
- **No semantic tokens** --- highlighting is pattern-based (TextMate), not semantic. Identifiers that happen to match Metal built-in names will be highlighted regardless of context.
- **Metal 3.1+ gaps** --- newer Metal features (mesh shaders, ray tracing types, visible function tables) may not be fully covered in the grammar.

## Future Updates

- **Inherit from `source.cpp`** --- switch the grammar to extend VS Code's built-in C++ grammar, improving coverage of standard C++ constructs.
- **Semantic token provider** --- provide richer, context-aware highlighting using the VS Code semantic tokens API.
- **Snippets** --- add code snippets for common Metal patterns (kernel definitions, threadgroup setup, SIMD matrix ops).
- **VS Code Marketplace publishing** --- make the extension installable via `ext install` without manual `.vsix` packaging.
- **Metal 3.1+ coverage** --- add support for mesh/object shaders, ray tracing types, visible function tables, and intersection function tables.
