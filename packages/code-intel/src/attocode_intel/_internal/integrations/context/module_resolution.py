"""Repository-local JavaScript/TypeScript project configuration.

No package installation or execution is needed to resolve local path aliases.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


class FileIndex(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.js_projects = []

    def configure_javascript(self, root):
        for name in list(self):
            if Path(name).name != "tsconfig.json":
                continue
            try:
                options = json.loads((Path(root) / name).read_text()).get("compilerOptions", {})
            except (OSError, ValueError, AttributeError):
                continue
            if not isinstance(options, dict) or not isinstance(options.get("baseUrl", "."), str):
                continue
            directory = str(Path(name).parent)
            base = os.path.normpath(str(Path(directory) / options.get("baseUrl", ".")))
            paths = options.get("paths", {})
            self.js_projects.append((directory, base, paths if isinstance(paths, dict) else {}))
        self.js_projects.sort(key=lambda item: len(item[0]), reverse=True)

    def javascript_candidates(self, module, source):
        for directory, base, paths in self.js_projects:
            if directory != "." and not source.startswith(directory + "/"):
                continue
            for pattern, targets in paths.items():
                prefix, wildcard, suffix = pattern.partition("*")
                if wildcard:
                    if not module.startswith(prefix) or not module.endswith(suffix):
                        continue
                    middle = module[len(prefix):len(module) - len(suffix) if suffix else None]
                elif module == pattern:
                    middle = ""
                else:
                    continue
                if isinstance(targets, list):
                    for target in targets:
                        if isinstance(target, str):
                            yield os.path.normpath(str(Path(base) / target.replace("*", middle)))
            yield os.path.normpath(str(Path(base) / module))
            break
