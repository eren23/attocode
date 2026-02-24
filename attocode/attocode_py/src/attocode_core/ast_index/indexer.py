"""Lightweight AST + dependency index with snapshot support."""

from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(slots=True)
class SymbolDef:
    name: str
    kind: str
    file_path: str
    line: int


@dataclass(slots=True)
class FileIndex:
    file_path: str
    language: str
    imports: list[str] = field(default_factory=list)
    symbols: list[SymbolDef] = field(default_factory=list)


@dataclass(slots=True)
class CodeIndex:
    root: str
    files: list[FileIndex] = field(default_factory=list)

    @classmethod
    def build(cls, root: Path) -> "CodeIndex":
        files: list[FileIndex] = []
        for path in root.rglob("*.py"):
            if ".git" in path.parts or ".venv" in path.parts:
                continue
            files.append(_index_python(path, root))
        for path in root.rglob("*.ts"):
            if ".git" in path.parts:
                continue
            files.append(_index_ts_like(path, root, language="typescript"))
        for path in root.rglob("*.js"):
            if ".git" in path.parts:
                continue
            files.append(_index_ts_like(path, root, language="javascript"))
        return cls(root=str(root), files=files)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "root": self.root,
            "files": [
                {
                    "file_path": f.file_path,
                    "language": f.language,
                    "imports": f.imports,
                    "symbols": [asdict(s) for s in f.symbols],
                }
                for f in self.files
            ],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _index_python(path: Path, root: Path) -> FileIndex:
    rel = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8", errors="replace")
    idx = FileIndex(file_path=rel, language="python")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return idx

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            idx.imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                idx.imports.append(node.module)
        elif isinstance(node, ast.FunctionDef):
            idx.symbols.append(SymbolDef(name=node.name, kind="function", file_path=rel, line=node.lineno))
        elif isinstance(node, ast.AsyncFunctionDef):
            idx.symbols.append(SymbolDef(name=node.name, kind="async_function", file_path=rel, line=node.lineno))
        elif isinstance(node, ast.ClassDef):
            idx.symbols.append(SymbolDef(name=node.name, kind="class", file_path=rel, line=node.lineno))
    return idx


def _index_ts_like(path: Path, root: Path, language: str) -> FileIndex:
    rel = str(path.relative_to(root))
    text = path.read_text(encoding="utf-8", errors="replace")
    idx = FileIndex(file_path=rel, language=language)
    for line_no, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if s.startswith("import ") and " from " in s:
            module = s.split(" from ", 1)[1].strip().strip(";\"")
            idx.imports.append(module)
        if s.startswith("export function "):
            name = s[len("export function "):].split("(", 1)[0].strip()
            idx.symbols.append(SymbolDef(name=name, kind="function", file_path=rel, line=line_no))
        if s.startswith("function "):
            name = s[len("function "):].split("(", 1)[0].strip()
            idx.symbols.append(SymbolDef(name=name, kind="function", file_path=rel, line=line_no))
        if s.startswith("class ") or s.startswith("export class "):
            prefix = "export class " if s.startswith("export class ") else "class "
            name = s[len(prefix):].split("{", 1)[0].strip()
            idx.symbols.append(SymbolDef(name=name, kind="class", file_path=rel, line=line_no))
    return idx
