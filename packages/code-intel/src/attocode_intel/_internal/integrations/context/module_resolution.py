"""Repository-local module ownership without package installation or execution."""
from __future__ import annotations

import json
import os
import re
import tomllib
from collections import defaultdict
from pathlib import Path


def _jsonc(text):
    token = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/')
    text = token.sub(lambda m: m[0] if m[0].startswith('"') else ' ', text)
    return json.loads(re.sub(r'("(?:\\.|[^"\\])*"\s*)|,\s*(?=[}\]])',
                            lambda m: m[1] or '', text))


class FileIndex(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.js_projects = []
        self.go_modules = []
        self.go_packages = defaultdict(set)
        self.rust_projects = []
        self.namespace_files = {}
        self.include_dirs = {}
        self.swift_projects = []

    def _read(self, root, name):
        path = Path(root) / name
        if not path.resolve().is_relative_to(Path(root).resolve()) or path.stat().st_size > 1_000_000:
            raise ValueError('Configuration outside indexed workspace or oversized')
        return path.read_text()

    def configure_javascript(self, root):
        self.js_projects = []
        for name in sorted(set(self.values())):
            if Path(name).name not in {'tsconfig.json', 'jsconfig.json'}:
                continue
            try:
                base, paths = self._js_options(root, name, set())
            except (OSError, ValueError, AttributeError, TypeError):
                continue
            self.js_projects.append((str(Path(name).parent), base, paths))
        self.js_projects.sort(key=lambda item: (-len(item[0]), item[0]))

    def _js_options(self, root, name, seen):
        if name in seen or len(seen) >= 8:
            raise ValueError('Configuration inheritance is cyclic or too deep')
        seen = seen | {name}
        data = _jsonc(self._read(root, name))
        directory = str(Path(name).parent)
        base, paths = directory, {}
        parent = data.get('extends')
        if isinstance(parent, str) and parent.startswith('.'):
            inherited = os.path.normpath(str(Path(directory) / parent))
            if not inherited.endswith('.json'):
                inherited += '.json'
            if inherited in self:
                base, paths = self._js_options(root, inherited, seen)
        options = data.get('compilerOptions', {})
        if not isinstance(options, dict):
            raise ValueError('Invalid compilerOptions')
        if 'baseUrl' in options:
            if not isinstance(options['baseUrl'], str):
                raise ValueError('Invalid baseUrl')
            base = os.path.normpath(str(Path(directory) / options['baseUrl']))
        if 'paths' in options:
            paths = options['paths'] if isinstance(options['paths'], dict) else {}
        return base, paths

    def javascript_candidates(self, module, source):
        for directory, base, paths in self.js_projects:
            if directory != '.' and not source.startswith(directory + '/'):
                continue
            # Exact aliases precede wildcard aliases; otherwise the longest
            # matching literal prefix owns resolution, independent of JSON order.
            for pattern in sorted(paths, key=lambda p: ('*' in p, -len(p.partition('*')[0]), p)):
                targets = paths[pattern]
                prefix, wildcard, suffix = pattern.partition('*')
                if wildcard:
                    if not module.startswith(prefix) or not module.endswith(suffix):
                        continue
                    middle = module[len(prefix):len(module) - len(suffix) if suffix else None]
                elif module == pattern:
                    middle = ''
                else:
                    continue
                if isinstance(targets, list):
                    for target in targets:
                        if isinstance(target, str):
                            yield os.path.normpath(str(Path(base) / target.replace('*', middle)))
                break
            yield os.path.normpath(str(Path(base) / module))
            break

    def configure_go(self, root):
        self.go_modules = []
        self.go_packages.clear()
        for name in sorted(set(self.values())):
            if name.endswith('.go') and not name.endswith('_test.go'):
                self.go_packages[str(Path(name).parent)].add(name)
            if Path(name).name != 'go.mod':
                continue
            try:
                text = self._read(root, name)
            except (OSError, ValueError):
                continue
            match = re.search(r'^\s*module\s+(?:"([^"\n]+)"|([^\s/][^\s]*))\s*(?://[^\n]*)?$', text, re.M)
            if match:
                self.go_modules.append((str(Path(name).parent), match[1] or match[2]))

    def go_candidates(self, module, source):
        if module.startswith(('./', '../')):
            directory = os.path.normpath(str(Path(source).parent / module))
        else:
            matches = [(directory, name) for directory, name in self.go_modules
                       if module == name or module.startswith(name + '/')]
            if not matches:
                return []
            longest = max(len(name) for _, name in matches)
            matches = [(d, n) for d, n in matches if len(n) == longest]
            if len(matches) != 1:
                return []
            base, name = matches[0]
            directory = str(Path(base) / module[len(name):].lstrip('/'))
        if directory == '..' or directory.startswith('../'):
            return []
        return sorted(self.go_packages.get(directory, ()))

    def configure_rust(self, root):
        self.rust_projects = []
        for name in sorted(set(self.values())):
            if Path(name).name != 'Cargo.toml':
                continue
            try:
                data = tomllib.loads(self._read(root, name))
                directory = str(Path(name).parent)
                library = data.get('lib', {}).get('path', 'src/lib.rs')
                entry = os.path.normpath(str(Path(directory) / library))
                if entry not in self:
                    entry = os.path.normpath(str(Path(directory) / 'src/main.rs'))
                package = data.get('package', {}).get('name')
                if not isinstance(package, str) or entry not in self:
                    continue
                aliases = {}
                for section in ('dependencies', 'dev-dependencies', 'build-dependencies'):
                    for alias, dep in data.get(section, {}).items():
                        if isinstance(dep, dict) and isinstance(dep.get('path'), str):
                            aliases[alias.replace('-', '_')] = os.path.normpath(str(Path(directory) / dep['path']))
                self.rust_projects.append((directory, entry, aliases))
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        self.rust_projects.sort(key=lambda item: (-len(item[0]), item[0]))

    def rust_dependency_entry(self, alias, source):
        for directory, _entry, aliases in self.rust_projects:
            if directory != '.' and not source.startswith(directory + '/'):
                continue
            target = aliases.get(alias)
            matches = {entry for base, entry, _ in self.rust_projects if base == target}
            return next(iter(matches)) if len(matches) == 1 else None
        return None

    def configure_namespaces(self, asts):
        self.namespace_files = defaultdict(lambda: defaultdict(dict))
        for path, ast in asts.items():
            names = {c.name for c in ast.classes} | {f.name for f in ast.functions}
            for namespace in ast.namespaces + ([c.name for c in ast.classes] if ast.language == "elixir" else []):
                self.namespace_files[ast.language][namespace.replace('\\', '.')][path] = names

    def namespace_candidates(self, language, module):
        module = module.replace('\\', '.').lstrip('.')
        entries = self.namespace_files.get(language, {})
        if language in {'csharp', 'elixir'} and module in entries:
            return sorted(entries[module])
        matches = []
        for namespace, files in entries.items():
            if not module.startswith(namespace + '.'):
                continue
            imported = module[len(namespace) + 1:]
            symbol = imported.split('.')[0]
            for path, names in files.items():
                if imported in {'*', '_'} or symbol in names:
                    matches.append(path)
        # Namespace declarations can intentionally span multiple files.
        return sorted(set(matches))

    def configure_native_includes(self, root):
        """Read compilation flags as data; never execute a compiler command."""
        import shlex
        self.include_dirs = {}
        workspace = Path(root).resolve()
        def relative(path):
            resolved = path.resolve()
            return str(resolved.relative_to(workspace)) if resolved.is_relative_to(workspace) else None
        for name in sorted(set(self.values())):
            if Path(name).name != 'compile_commands.json':
                continue
            try:
                commands = json.loads(self._read(root, name))
            except (OSError, ValueError):
                continue
            if not isinstance(commands, list):
                continue
            for entry in commands:
                try:
                    directory = Path(root) / entry.get('directory', '.')
                    source = relative(directory / entry['file'])
                    if source not in self:
                        continue
                    args = entry.get('arguments')
                    if args is None:
                        args = shlex.split(entry.get('command', ''))
                    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                        continue
                    dirs = []
                    cursor = 0
                    while cursor < len(args):
                        arg = args[cursor]
                        cursor += 1
                        flag = next((f for f in ('-iquote', '-isystem', '-I') if arg.startswith(f)), None)
                        if flag is None:
                            continue
                        path = arg[len(flag):]
                        if not path and cursor < len(args):
                            path, cursor = args[cursor], cursor + 1
                        rel = relative(directory / path)
                        if path and rel is not None:
                            dirs.append((rel, flag == '-iquote'))
                    # Conflicting build configurations stay ambiguous.
                    if source in self.include_dirs and self.include_dirs[source] != dirs:
                        self.include_dirs[source] = None
                    else:
                        self.include_dirs[source] = dirs
                except (KeyError, TypeError, ValueError, OSError):
                    continue

    def c_candidates(self, module, source, *, system=False):
        if not system:
            relative = os.path.normpath(str(Path(source).parent / module))
            if relative in self:
                return [self[relative]]
        if source in self.include_dirs:
            for directory, quote_only in self.include_dirs[source] or []:
                if system and quote_only:
                    continue
                candidate = os.path.normpath(str(Path(directory) / module))
                if candidate in self:
                    return [self[candidate]]
            return []
        candidates = {self[key] for directory in (['include', 'inc'] if system else ['.', 'include', 'inc', 'src'])
                      if (key := os.path.normpath(str(Path(directory) / module))) in self}
        return sorted(candidates) if len(candidates) == 1 else []

    def configure_swift(self, root):
        from .ts_parser import _get_parser, _node_text
        self.swift_projects = []
        manifests = [name for name in sorted(set(self.values())) if Path(name).name == 'Package.swift']
        if not manifests:
            return
        parser = _get_parser('swift')
        if parser is None:
            return
        for name in manifests:
            try:
                source = self._read(root, name).encode()
            except (OSError, ValueError):
                continue
            stack = [parser.parse(source).root_node]
            targets = {}
            while stack:
                node = stack.pop()
                stack.extend(node.named_children)
                if node.type != 'call_expression' or not node.named_children:
                    continue
                kind = _node_text(node.named_children[0], source)
                if kind not in {'.target', '.executableTarget', '.testTarget'}:
                    continue
                values = {}
                for suffix in node.named_children:
                    if suffix.type != 'call_suffix':
                        continue
                    for arguments in suffix.named_children:
                        if arguments.type != 'value_arguments':
                            continue
                        for argument in arguments.named_children:
                            label, value = argument.child_by_field_name('name'), argument.child_by_field_name('value')
                            if label is not None and value is not None and value.type == 'line_string_literal':
                                children = value.named_children
                                if len(children) == 1 and children[0].type == 'line_str_text':
                                    values[_node_text(label, source)] = _node_text(children[0], source)
                target = values.get('name')
                if target:
                    path = values.get('path', ('Tests/' if kind == '.testTarget' else 'Sources/') + target)
                    base = os.path.normpath(str(Path(name).parent / path))
                    targets[target] = sorted({f for f in self.values() if f.startswith(base + '/') and f.endswith('.swift')})
            self.swift_projects.append((str(Path(name).parent), targets))
        self.swift_projects.sort(key=lambda row: (-len(row[0]), row[0]))

    def swift_candidates(self, module, source):
        for base, targets in self.swift_projects:
            if base == '.' or source.startswith(base + '/'):
                return targets.get(module, [])
        return []
