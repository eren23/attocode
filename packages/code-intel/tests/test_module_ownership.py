"""Cross-file navigation must follow declared ownership and survive config edits."""
import json

from attocode_intel.gateway import OperationGateway


def write(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


async def dependents(gateway, path):
    response = await gateway.execute('dependencies', {'path': path})
    assert not response.isError
    return set(response.structuredContent['data']['imported_by'])


async def test_go_module_ownership_all_package_files_and_config_edit(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'go.mod': 'module example.org/app\ngo 1.22\n',
        'pkg/alpha.go': 'package pkg\nfunc Alpha() int { return 1 }\n',
        'pkg/beta.go': 'package pkg\nfunc Beta() int { return 2 }\n',
        'pkg/alpha_test.go': 'package pkg\nfunc testAlpha() {}\n',
        'pkg/nested/no.go': 'package nested\nfunc No() {}\n',
        'cmd/main.go': 'package main\nimport "example.org/app/pkg"\nfunc main() { pkg.Alpha() }\n',
        'cmd/external.go': 'package main\nimport "unrelated.org/app/pkg"\nfunc other() { pkg.Beta() }\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert await dependents(gateway, 'pkg/alpha.go') == {'cmd/main.go'}
        assert await dependents(gateway, 'pkg/beta.go') == {'cmd/main.go'}
        assert not await dependents(gateway, 'pkg/alpha_test.go')
        assert not await dependents(gateway, 'pkg/nested/no.go')
        (tmp_path / 'go.mod').write_text('module unrelated.org/app\ngo 1.22\n')
        assert await dependents(gateway, 'pkg/alpha.go') == {'cmd/external.go'}
    finally:
        await gateway.close()


async def test_typescript_jsonc_paths_and_config_only_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'tsconfig.json': '{ // intentional JSONC\n "compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["one/*"],},},}\n',
        'one/helper.ts': 'export function helper() { return 1; }\n',
        'two/helper.ts': 'export function helper() { return 2; }\n',
        'caller.ts': "import { helper } from '@/helper';\nhelper();\n",
        'negative.ts': "import { helper } from '@other/helper';\nhelper();\n",
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert await dependents(gateway, 'one/helper.ts') == {'caller.ts'}
        assert not await dependents(gateway, 'two/helper.ts')
        (tmp_path / 'tsconfig.json').write_text(json.dumps({'compilerOptions': {'paths': {'@/*': ['two/*']}}}))
        assert await dependents(gateway, 'two/helper.ts') == {'caller.ts'}
        assert not await dependents(gateway, 'one/helper.ts')
    finally:
        await gateway.close()


async def test_rust_declared_path_dependency_alias_does_not_depend_on_folder_name(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'app/Cargo.toml': '[package]\nname="consumer"\nversion="0.1.0"\n[dependencies]\nrenamed = { package="actual", path="../odd-folder" }\n',
        'app/src/main.rs': 'use renamed::helper;\nfn main() { helper(); }\n',
        'odd-folder/Cargo.toml': '[package]\nname="actual"\nversion="0.1.0"\n[lib]\npath="code/entry.rs"\n',
        'odd-folder/code/entry.rs': 'pub fn helper() {}\n',
        'unrelated/src/lib.rs': 'pub fn helper() {}\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert await dependents(gateway, 'odd-folder/code/entry.rs') == {'app/src/main.rs'}
        assert not await dependents(gateway, 'unrelated/src/lib.rs')
    finally:
        await gateway.close()


async def test_namespace_import_binds_only_the_selected_member(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'helper.ts': 'export function helper() { return 1; }\nexport function other() { return 2; }\n',
        'caller.ts': "import * as api from './helper';\napi.helper();\napi.other();\nhelper();\n",
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        result = await gateway.execute('inspect_symbol', {'symbol_name':'helper', 'file_path':'helper.ts', 'line':1})
        rows = result.structuredContent['data']['references']
        assert any(r['file_path'] == 'caller.ts' and r['line'] == 2 for r in rows)
        assert not any(r['file_path'] == 'caller.ts' and r['line'] in {3,4} for r in rows)
    finally:
        await gateway.close()


def test_ambiguous_python_package_roots_do_not_choose_last_discovered_file():
    from attocode_intel._internal.integrations.context.codebase_context import (
        _resolve_python_import,
        python_module_index,
    )
    paths = ['one/src/pkg/__init__.py', 'one/src/pkg/helper.py',
             'two/src/pkg/__init__.py', 'two/src/pkg/helper.py']
    for ordered in (paths, paths[::-1]):
        index = python_module_index(ordered)
        assert _resolve_python_import('pkg.helper', 'outside.py', index) is None
        assert _resolve_python_import('.helper', 'one/src/pkg/main.py', index) == 'one/src/pkg/helper.py'


async def test_declared_namespaces_include_vendor_names_and_multiple_files(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'java/Helper.java': 'package com.google.example; public class Helper {}\n',
        'java/Extra.java': 'package com.google.example; public class Extra {}\n',
        'java/Caller.java': 'package app; import com.google.example.*; class Caller {}\n',
        'java/Wrong.java': 'package unrelated; class Helper {}\n',
        'cs/One.cs': 'namespace Acme.Core; public class One {}\n',
        'cs/Two.cs': 'namespace Acme.Core; public class Two {}\n',
        'cs/Caller.cs': 'using Acme.Core; class Caller {}\n',
        'cs/Wrong.cs': 'namespace Other.Core; public class One {}\n',
        'php/Helper.php': '<?php namespace Acme\\Core; class Helper {}\n',
        'php/Caller.php': '<?php use Acme\\Core\\Helper as Alias; new Alias();\n',
        'kt/helper.kt': 'package acme.core\nfun helper() = 1\n',
        'kt/caller.kt': 'package app\nimport acme.core.helper as alias\nfun call() = alias()\n',
        'scala/Helper.scala': 'package acme.core\nobject Helper {}\n',
        'scala/Caller.scala': 'package app\nimport acme.core.Helper\nobject Caller {}\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for path, caller in [('java/Helper.java','java/Caller.java'), ('java/Extra.java','java/Caller.java'),
                             ('cs/One.cs','cs/Caller.cs'), ('cs/Two.cs','cs/Caller.cs'),
                             ('php/Helper.php','php/Caller.php'), ('kt/helper.kt','kt/caller.kt'),
                             ('scala/Helper.scala','scala/Caller.scala')]:
            assert await dependents(gateway, path) == {caller}, path
        assert not await dependents(gateway, 'java/Wrong.java')
        assert not await dependents(gateway, 'cs/Wrong.cs')
        (tmp_path / 'cs/Two.cs').write_text('namespace Other.Core; public class Two {}\n')
        assert not await dependents(gateway, 'cs/Two.cs')
    finally:
        await gateway.close()


async def test_compilation_database_include_order_and_config_edit(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'src/main.c': '#include "local.h"\n#include <api.h>\n',
        'src/local.h': 'int local(void);\n',
        'first/api.h': 'int first(void);\n',
        'second/api.h': 'int second(void);\n',
        'src/api.h': 'int must_not_shadow_system_include(void);\n',
        'compile_commands.json': json.dumps([{'directory':str(tmp_path), 'file':'src/main.c',
            'arguments':['compiler-must-not-run','-Ifirst','-Isecond','-c','src/main.c']}]),
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        assert await dependents(gateway, 'src/local.h') == {'src/main.c'}
        assert await dependents(gateway, 'first/api.h') == {'src/main.c'}
        assert not await dependents(gateway, 'second/api.h')
        assert not await dependents(gateway, 'src/api.h')
        (tmp_path / 'compile_commands.json').write_text(json.dumps([{'directory':str(tmp_path), 'file':'src/main.c',
            'arguments':['compiler-must-not-run','-Isecond','-Ifirst','-c','src/main.c']}]))
        assert await dependents(gateway, 'second/api.h') == {'src/main.c'}
        assert not await dependents(gateway, 'first/api.h')
    finally:
        await gateway.close()


async def test_literal_modules_and_dynamic_import_negative_controls(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'ruby/helper.rb': 'def helper; 1; end\n',
        'ruby/caller.rb': 'require_relative "helper"\n',
        'lua/helper.lua': 'function helper() return 1 end\n',
        'caller.lua': 'local helper = require("lua.helper")\n',
        'dynamic.lua': 'local helper = require(prefix .. ".helper")\n',
        'shell/helper.sh': 'helper() { echo ok; }\n',
        'shell/caller.sh': 'source ./helper.sh\n',
        'shell/dynamic.sh': 'source "$HELPER_FILE"\necho "./helper.sh"\n',
        'zig/helper.zig': 'pub fn helper() void {}\n',
        'zig/caller.zig': 'const helper = @import("helper.zig");\n',
        'zig/dynamic.zig': 'const helper = @import(selected_path);\n',
        'elixir/core.ex': 'defmodule Acme.Core do\n def run(), do: 1\nend\n',
        'elixir/caller.ex': 'defmodule App do\n alias Acme.Core\n def run(), do: Core.run()\nend\n',
        'Package.swift': 'let package = Package(name: "Demo", targets: [.target(name: "Core", path: "Sources/Engine"), .target(name: "App", dependencies: ["Core"])])',
        'Sources/Engine/core.swift': 'public func helper() -> Int { return 1 }\n',
        'Sources/Engine/extra.swift': 'public func extra() -> Int { return 2 }\n',
        'Sources/App/main.swift': 'import Core\nprint(helper())\n',
        'Sources/App/external.swift': 'import ExternalCore\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for path, caller in [('ruby/helper.rb','ruby/caller.rb'), ('lua/helper.lua','caller.lua'),
                             ('shell/helper.sh','shell/caller.sh'), ('zig/helper.zig','zig/caller.zig'),
                             ('elixir/core.ex','elixir/caller.ex'), ('Sources/Engine/core.swift','Sources/App/main.swift'),
                             ('Sources/Engine/extra.swift','Sources/App/main.swift')]:
            assert await dependents(gateway, path) == {caller}, path
    finally:
        await gateway.close()


async def test_go_package_alias_links_only_qualified_selected_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'go.mod': 'module example.org/app\ngo 1.22\n',
        'odd/helper.go': 'package actual\nfunc Helper() {}\nfunc Other() {}\n',
        'main.go': 'package main\nimport renamed "example.org/app/odd"\nfunc main() {\n renamed.Helper()\n renamed.Other()\n Helper()\n}\n',
        'default.go': 'package main\nimport "example.org/app/odd"\nfunc other() { actual.Helper() }\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        response = await gateway.execute('inspect_symbol', {'symbol_name':'Helper', 'file_path':'odd/helper.go', 'line':2})
        rows = response.structuredContent['data']['references']
        assert any(r['file_path'] == 'main.go' and r['line'] == 4 for r in rows)
        assert any(r['file_path'] == 'default.go' and r['line'] == 3 for r in rows)
        assert not any(r['file_path'] == 'main.go' and r['line'] in {5,6} for r in rows)
    finally:
        await gateway.close()


async def test_literal_namespace_bindings_and_function_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'lib/helper.lua': 'function helper() return 1 end\n',
        'caller.lua': 'local api = require("lib.helper")\napi.helper()\napi.other()\nhelper()\n',
        'helper.zig': 'pub fn helper() void {}\n',
        'caller.zig': 'const api = @import("helper.zig");\npub fn main() void {\n api.helper();\n api.other();\n helper();\n}\n',
        'helper.kt': 'package acme.core\nfun helper() = 1\n',
        'caller.kt': 'package app\nimport acme.core.helper as alias\nfun call() = alias()\nfun other() = helper()\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for target, line, caller, good, bad in [('lib/helper.lua',1,'caller.lua',2,{3,4}),
              ('helper.zig',1,'caller.zig',3,{4,5}), ('helper.kt',2,'caller.kt',3,{4})]:
            response = await gateway.execute('inspect_symbol', {'symbol_name':'helper', 'file_path':target, 'line':line})
            rows = response.structuredContent['data']['references']
            assert any(r['file_path'] == caller and r['line'] == good for r in rows), (target, rows)
            assert not any(r['file_path'] == caller and r['line'] in bad for r in rows), (target, rows)
    finally:
        await gateway.close()


async def test_static_script_and_module_qualified_calls(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'ruby/helper.rb':'def helper; 1; end\n',
        'ruby/caller.rb':'require_relative "helper"\nhelper()\nother()\n',
        'ruby/dynamic.rb':'pretend_require "helper"\nhelper()\n',
        'shell/helper.sh':'helper() { echo ok; }\n',
        'shell/caller.sh':'source ./helper.sh\nhelper\nother\n',
        'elixir/core.ex':'defmodule Acme.Core do\n def helper(), do: 1\nend\n',
        'elixir/caller.ex':'defmodule App do\n alias Acme.Core\n def call(), do: Core.helper()\n def other(), do: Other.helper()\nend\n',
        'Package.swift':'let package = Package(name: "Demo", targets: [.target(name: "Core"), .target(name: "App")])',
        'Sources/Core/helper.swift':'public func helper() -> Int { return 1 }\n',
        'Sources/App/main.swift':'import Core\nlet a = helper()\nlet b = Core.helper()\nlet c = Other.helper()\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for target, line, caller, good, bad in [('ruby/helper.rb',1,'ruby/caller.rb',{2},{3}),
                ('shell/helper.sh',1,'shell/caller.sh',{2},{3}),
                ('elixir/core.ex',2,'elixir/caller.ex',{3},{4}),
                ('Sources/Core/helper.swift',1,'Sources/App/main.swift',{2,3},{4})]:
            response = await gateway.execute('inspect_symbol', {'symbol_name':'helper', 'file_path':target, 'line':line})
            rows = response.structuredContent['data']['references']
            assert good <= {r['line'] for r in rows if r['file_path'] == caller}, (target, rows)
            assert not any(r['file_path'] == caller and r['line'] in bad for r in rows), (target, rows)
            assert not any(r['file_path'] == 'ruby/dynamic.rb' for r in rows)
    finally:
        await gateway.close()


async def test_declared_types_link_static_calls_without_guessing_receivers(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'java/Helper.java':'package acme.core; public class Helper { public static int run() { return 1; } }\n',
        'java/Caller.java':'package app; import acme.core.Helper;\nclass App { int a() { return Helper.run(); }\nint b() { return other.run(); } }\n',
        'cs/Helper.cs':'namespace Acme.Core; public class Helper { public static int Run() { return 1; } }\n',
        'cs/Caller.cs':'using Acme.Core;\nclass App { int A() { return Helper.Run(); }\nint B() { return other.Run(); } }\n',
        'scala/Helper.scala':'package acme.core\nobject Helper { def run(): Int = 1 }\n',
        'scala/Caller.scala':'package app\nimport acme.core.Helper\nobject App { def a() = Helper.run()\ndef b() = other.run() }\n',
        'php/Helper.php':'<?php namespace Acme\\Core; class Helper { public static function run() { return 1; } }\n',
        'php/Caller.php':'<?php use Acme\\Core\\Helper as Alias;\nAlias::run();\nOther::run();\n',
    })
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for target, symbol, line, caller, good, bad in [
                ('java/Helper.java','run',1,'java/Caller.java',2,3),
                ('cs/Helper.cs','Run',1,'cs/Caller.cs',2,3),
                ('scala/Helper.scala','run',2,'scala/Caller.scala',3,4),
                ('php/Helper.php','run',1,'php/Caller.php',2,3)]:
            response = await gateway.execute('inspect_symbol', {'symbol_name':symbol, 'file_path':target, 'line':line})
            rows = response.structuredContent['data']['references']
            assert any(r['file_path'] == caller and r['line'] == good for r in rows), (target, rows)
            assert not any(r['file_path'] == caller and r['line'] == bad for r in rows), (target, rows)
    finally:
        await gateway.close()


async def test_typescript_alias_specificity_is_independent_of_json_key_order(tmp_path, monkeypatch):
    monkeypatch.setenv('ATTOCODE_INTEL_PRECISION', 'off')
    write(tmp_path, {
        'broad/core/helper.ts':'export function helper() {}\n',
        'specific/helper.ts':'export function helper() {}\n',
        'exact.ts':'export function helper() {}\n',
        'caller.ts':"import { helper } from '@app/core/helper';\nhelper();\n",
    })
    paths = {'@app/*':['broad/*'], '@app/core/*':['specific/*'], '@app/core/helper':['exact.ts']}
    gateway = OperationGateway(str(tmp_path), 'daily', watch=False)
    try:
        for ordered in (paths, dict(reversed(list(paths.items())))):
            (tmp_path / 'tsconfig.json').write_text(json.dumps({'compilerOptions':{'paths':ordered}}))
            assert await dependents(gateway, 'exact.ts') == {'caller.ts'}
            assert not await dependents(gateway, 'broad/core/helper.ts')
            assert not await dependents(gateway, 'specific/helper.ts')
    finally:
        await gateway.close()
