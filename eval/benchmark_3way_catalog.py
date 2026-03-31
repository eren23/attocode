"""Repo catalog and slice helpers for the 3-way benchmark."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

REPOS: dict[str, dict[str, object]] = {
    "attocode": {
        "source": "project_root",
        "lang": "python",
        "symbol": "CodebaseContextManager",
        "dep_file": "src/attocode/core/loop.py",
        "nav_file": "src/attocode/core/loop.py",
        "nav_function": "check_iteration_budget",
        "search_query": "token budget management enforcement",
    },
    "fastapi": {
        "repo_dir": "fastapi",
        "lang": "python",
        "symbol": "FastAPI",
        "dep_file": "fastapi/applications.py",
        "nav_file": "fastapi/routing.py",
        "nav_function": "APIRouter",
        "search_query": "dependency injection request validation",
    },
    "pandas": {
        "repo_dir": "pandas",
        "lang": "python",
        "symbol": "DataFrame",
        "dep_file": "pandas/core/frame.py",
        "nav_file": "pandas/core/frame.py",
        "nav_function": "DataFrame",
        "search_query": "missing data handling NaN propagation",
    },
    "deno": {
        "repo_dir": "deno",
        "lang": "rust",
        "symbol": "JsRuntime",
        "dep_file": "runtime/worker.rs",
        "nav_file": "runtime/worker.rs",
        "nav_function": "JsRuntime",
        "search_query": "V8 isolate creation module loading",
    },
    "aspnetcore": {
        "repo_dir": "aspnetcore",
        "lang": "csharp",
        "symbol": "WebApplication",
        "dep_file": "src/Http/Http.Abstractions/src/HttpContext.cs",
        "nav_file": "src/Http/Http.Abstractions/src/HttpContext.cs",
        "nav_function": "WebApplication",
        "search_query": "middleware pipeline request handling",
    },
    "laravel": {
        "repo_dir": "framework",
        "lang": "php",
        "symbol": "Application",
        "dep_file": "src/Illuminate/Foundation/Application.php",
        "nav_file": "src/Illuminate/Routing/Router.php",
        "nav_function": "dispatch",
        "search_query": "service container dependency injection",
    },
    "swiftformat": {
        "repo_dir": "SwiftFormat",
        "lang": "swift",
        "symbol": "FormatRule",
        "dep_file": "Sources/FormatRule.swift",
        "nav_file": "Sources/FormatRule.swift",
        "nav_function": "FormatRule",
        "search_query": "formatting rules token parsing",
    },
    "okhttp": {
        "repo_dir": "okhttp",
        "lang": "kotlin",
        "symbol": "OkHttpClient",
        "dep_file": "okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt",
        "nav_file": "okhttp/src/commonJvmAndroid/kotlin/okhttp3/OkHttpClient.kt",
        "nav_function": "OkHttpClient",
        "search_query": "connection pooling request interceptors",
    },
    "gh-cli": {
        "repo_dir": "gh-cli",
        "lang": "go",
        "symbol": "exitCode",
        "dep_file": "internal/ghcmd/cmd.go",
        "nav_file": "internal/gh/gh.go",
        "nav_function": "Config",
        "search_query": "CLI command factory command execution",
    },
    "faker": {
        "repo_dir": "faker",
        "lang": "ruby",
        "symbol": "Base",
        "dep_file": "lib/faker.rb",
        "nav_file": "lib/faker/default/internet.rb",
        "nav_function": "Internet",
        "search_query": "data generation fake data providers",
    },
    "redis": {
        "repo_dir": "redis",
        "lang": "c",
        "symbol": "redisServer",
        "dep_file": "src/server.h",
        "nav_file": "src/server.c",
        "nav_function": "initServer",
        "search_query": "event driven server command handling",
    },
    "spdlog": {
        "repo_dir": "spdlog",
        "lang": "cpp",
        "symbol": "logger",
        "dep_file": "include/spdlog/spdlog.h",
        "nav_file": "include/spdlog/logger.h",
        "nav_function": "log",
        "search_query": "logging sinks formatters pattern",
    },
    "cats-effect": {
        "repo_dir": "cats-effect",
        "lang": "scala",
        "symbol": "IO",
        "dep_file": "core/shared/src/main/scala/cats/effect/IO.scala",
        "nav_file": "core/shared/src/main/scala/cats/effect/unsafe/IORuntimeConfig.scala",
        "nav_function": "IORuntimeConfig",
        "search_query": "effectful computation async runtime",
    },
    "luarocks": {
        "repo_dir": "luarocks",
        "lang": "lua",
        "symbol": "loader",
        "dep_file": "src/luarocks/loader.lua",
        "nav_file": "src/luarocks/cmd.lua",
        "nav_function": "cmd",
        "search_query": "package manager module loading",
    },
    "phoenix": {
        "repo_dir": "phoenix",
        "lang": "elixir",
        "symbol": "Router",
        "dep_file": "lib/phoenix/router.ex",
        "nav_file": "lib/phoenix/endpoint.ex",
        "nav_function": "Endpoint",
        "search_query": "web routing request pipeline",
    },
    "postgrest": {
        "repo_dir": "postgrest",
        "lang": "haskell",
        "symbol": "postgrest",
        "dep_file": "src/PostgREST/App.hs",
        "nav_file": "src/PostgREST/AppState.hs",
        "nav_function": "AppState",
        "search_query": "HTTP PostgreSQL request mapping",
    },
    "acme-sh": {
        "repo_dir": "acme-sh",
        "lang": "bash",
        "symbol": "_main",
        "dep_file": "acme.sh",
        "nav_file": "acme.sh",
        "nav_function": "main",
        "search_query": "certificate issuance renewal automation",
    },
    "terraform-eks": {
        "repo_dir": "terraform-eks",
        "lang": "hcl",
        "symbol": "aws_eks_cluster",
        "dep_file": "main.tf",
        "nav_file": "variables.tf",
        "nav_function": "resource",
        "search_query": "EKS cluster node group provisioning",
    },
    "zls": {
        "repo_dir": "zls",
        "lang": "zig",
        "symbol": "Server",
        "dep_file": "src/Server.zig",
        "nav_file": "src/main.zig",
        "nav_function": "Server",
        "search_query": "language server protocol analysis",
    },
    "cockroach": {
        "repo_dir": "cockroach",
        "lang": "go",
        "symbol": "NewServer",
        "dep_file": "go.mod",
        "nav_file": "pkg/server/server.go",
        "nav_function": "Server",
        "search_query": "distributed SQL transaction consensus",
    },
    "express": {
        "repo_dir": "express",
        "lang": "javascript",
        "symbol": "Router",
        "dep_file": "package.json",
        "nav_file": "lib/application.js",
        "nav_function": "app",
        "search_query": "middleware routing request handling",
    },
    "prisma": {
        "repo_dir": "prisma",
        "lang": "typescript",
        "symbol": "PrismaClient",
        "dep_file": "packages/client/package.json",
        "nav_file": "packages/client/src/runtime/getPrismaClient.ts",
        "nav_function": "getPrismaClient",
        "search_query": "database ORM query engine client",
    },
    "rails": {
        "repo_dir": "rails",
        "lang": "ruby",
        "symbol": "Application",
        "dep_file": "railties/lib/rails/application.rb",
        "nav_file": "railties/lib/rails/application.rb",
        "nav_function": "Application",
        "search_query": "MVC routing ActiveRecord middleware",
    },
    "requests": {
        "repo_dir": "requests",
        "lang": "python",
        "symbol": "Session",
        "dep_file": "src/requests/sessions.py",
        "nav_file": "src/requests/sessions.py",
        "nav_function": "Session",
        "search_query": "HTTP session connection pooling",
    },
    "cosmopolitan": {
        "repo_dir": "cosmopolitan",
        "lang": "c",
        "symbol": "open",
        "dep_file": "Makefile",
        "nav_file": "libc/calls/calls.h",
        "nav_function": "syscall",
        "search_query": "portable libc system call emulation",
    },
    "ripgrep": {
        "repo_dir": "ripgrep",
        "lang": "rust",
        "symbol": "SearchWorker",
        "dep_file": "Cargo.toml",
        "nav_file": "crates/core/search.rs",
        "nav_function": "search",
        "search_query": "parallel file search regex matching",
    },
    "starship": {
        "repo_dir": "starship",
        "lang": "rust",
        "symbol": "Module",
        "dep_file": "Cargo.toml",
        "nav_file": "src/module.rs",
        "nav_function": "Module",
        "search_query": "shell prompt module configuration",
    },
    "spring-boot": {
        "repo_dir": "spring-boot",
        "lang": "java",
        "symbol": "SpringApplication",
        "dep_file": "build.gradle",
        "nav_file": "core/spring-boot/src/main/java/org/springframework/boot/SpringApplication.java",
        "nav_function": "SpringApplication",
        "search_query": "auto configuration dependency injection",
    },
    "spark": {
        "repo_dir": "spark",
        "lang": "scala",
        "symbol": "SparkContext",
        "dep_file": "pom.xml",
        "nav_file": "core/src/main/scala/org/apache/spark/SparkContext.scala",
        "nav_function": "SparkContext",
        "search_query": "distributed data processing RDD",
    },
    "vapor": {
        "repo_dir": "vapor",
        "lang": "swift",
        "symbol": "Application",
        "dep_file": "Package.swift",
        "nav_file": "Sources/Vapor/Application.swift",
        "nav_function": "Application",
        "search_query": "HTTP server routing middleware",
    },
    "wordpress": {
        "repo_dir": "WordPress",
        "lang": "php",
        "symbol": "apply_filters",
        "dep_file": "wp-settings.php",
        "nav_file": "wp-includes/plugin.php",
        "nav_function": "add_filter",
        "search_query": "WordPress hook filter plugin system",
    },
    "protobuf": {
        "repo_dir": "protobuf",
        "lang": "cpp",
        "symbol": "FileDescriptor",
        "dep_file": "CMakeLists.txt",
        "nav_file": "src/google/protobuf/descriptor.h",
        "nav_function": "Descriptor",
        "search_query": "protocol buffer serialization encoding",
    },
    "crystal-lang": {
        "repo_dir": "crystal",
        "lang": "crystal",
        "symbol": "NonGenericClassType",
        "dep_file": "shard.yml",
        "nav_file": "src/compiler/crystal/types.cr",
        "nav_function": "Type",
        "search_query": "compiler type system inference",
    },
    "dart-sdk": {
        "repo_dir": "dart-sdk",
        "lang": "dart",
        "symbol": "ClassElementImpl",
        "dep_file": "pubspec.yaml",
        "nav_file": "pkg/analyzer/lib/src/dart/element/element.dart",
        "nav_function": "ClassElementImpl",
        "search_query": "analyzer element model resolution",
    },
    "elixir-lang": {
        "repo_dir": "elixir",
        "lang": "elixir",
        "symbol": "Kernel",
        "dep_file": "lib/elixir/mix.exs",
        "nav_file": "lib/elixir/lib/kernel.ex",
        "nav_function": "defmacro",
        "search_query": "macro metaprogramming pattern matching",
    },
    "emqx": {
        "repo_dir": "emqx",
        "lang": "erlang",
        "symbol": "emqx_channel",
        "dep_file": "mix.exs",
        "nav_file": "apps/emqx/src/emqx_channel.erl",
        "nav_function": "handle_in",
        "search_query": "MQTT broker message routing",
    },
    "fsharp": {
        "repo_dir": "fsharp",
        "lang": "fsharp",
        "symbol": "CheckDeclarations",
        "dep_file": "src/Compiler/FSharp.Compiler.Service.fsproj",
        "nav_file": "src/Compiler/Checking/CheckDeclarations.fs",
        "nav_function": "MutRecShape",
        "search_query": "type checking declaration compilation",
    },
    "ggplot2": {
        "repo_dir": "ggplot2",
        "lang": "r",
        "symbol": "continuous_scale",
        "dep_file": "DESCRIPTION",
        "nav_file": "R/scale-.R",
        "nav_function": "ScaleContinuous",
        "search_query": "grammar graphics plot layer aesthetic",
    },
    "iterm2": {
        "repo_dir": "iTerm2",
        "lang": "objc",
        "symbol": "iTermController",
        "dep_file": "iTerm2.xcodeproj/project.pbxproj",
        "nav_file": "sources/PTYSession.m",
        "nav_function": "PTYSession",
        "search_query": "terminal emulator session management",
    },
    "julia": {
        "repo_dir": "julia",
        "lang": "julia",
        "symbol": "Base",
        "dep_file": "base/Base.jl",
        "nav_file": "base/array.jl",
        "nav_function": "Array",
        "search_query": "multiple dispatch type system JIT",
    },
    "kemal": {
        "repo_dir": "kemal",
        "lang": "crystal",
        "symbol": "Kemal",
        "dep_file": "shard.yml",
        "nav_file": "src/kemal/router.cr",
        "nav_function": "Router",
        "search_query": "web framework routing HTTP handler",
    },
    "metabase": {
        "repo_dir": "metabase",
        "lang": "clojure",
        "symbol": "describe-database",
        "dep_file": "deps.edn",
        "nav_file": "src/metabase/driver.clj",
        "nav_function": "dispatch-on-initialized-driver",
        "search_query": "database driver query analytics",
    },
    "mojo-perl": {
        "repo_dir": "mojo",
        "lang": "perl",
        "symbol": "Mojolicious",
        "dep_file": "Makefile.PL",
        "nav_file": "lib/Mojolicious.pm",
        "nav_function": "dispatch",
        "search_query": "web framework real-time request",
    },
    "nickel": {
        "repo_dir": "nickel",
        "lang": "rust",
        "symbol": "VirtualMachine",
        "dep_file": "core/Cargo.toml",
        "nav_file": "core/src/eval/operation.rs",
        "nav_function": "continue_op",
        "search_query": "configuration language evaluation contracts",
    },
    "nim": {
        "repo_dir": "Nim",
        "lang": "nim",
        "symbol": "semExprWithType",
        "dep_file": "nim.nimble",
        "nav_file": "compiler/semexprs.nim",
        "nav_function": "semExprCheck",
        "search_query": "compiler semantic analysis expression",
    },
    "ocaml": {
        "repo_dir": "ocaml",
        "lang": "ocaml",
        "symbol": "type_exp",
        "dep_file": "stdlib/stdlib.ml",
        "nav_file": "typing/typecore.ml",
        "nav_function": "type_expression",
        "search_query": "type inference pattern matching module",
    },
    "otp": {
        "repo_dir": "otp",
        "lang": "erlang",
        "symbol": "gen_server",
        "dep_file": "lib/stdlib/src/gen_server.erl",
        "nav_file": "lib/stdlib/src/gen_server.erl",
        "nav_function": "call",
        "search_query": "OTP behavior supervision process",
    },
    "perl5": {
        "repo_dir": "perl5",
        "lang": "perl",
        "symbol": "Perl_newOP",
        "dep_file": "perl.h",
        "nav_file": "op.c",
        "nav_function": "Perl_op_free",
        "search_query": "optree compilation regex parsing",
    },
    "ring": {
        "repo_dir": "ring",
        "lang": "clojure",
        "symbol": "redirect",
        "dep_file": "ring-core/project.clj",
        "nav_file": "ring-core/src/ring/util/response.clj",
        "nav_function": "response",
        "search_query": "HTTP ring adapter middleware handler",
    },
    "linux": {
        "repo_dir": "linux",
        "clone_url": "https://github.com/torvalds/linux.git",
        "lang": "c",
        "symbol": "task_struct",
        "dep_file": "kernel/sched/core.c",
        "nav_file": "kernel/sched/core.c",
        "nav_function": "schedule",
        "search_query": "scheduler task wakeup runqueue",
    },
}

PUBLISHED_20 = [
    "fastapi",
    "pandas",
    "requests",
    "gh-cli",
    "cockroach",
    "deno",
    "ripgrep",
    "starship",
    "redis",
    "spdlog",
    "protobuf",
    "spring-boot",
    "express",
    "prisma",
    "rails",
    "faker",
    "vapor",
    "phoenix",
    "spark",
    "wordpress",
]

ALL_LOCAL = [repo_id for repo_id in REPOS if repo_id != "linux"]

SLICES: dict[str, list[str]] = {
    "published_20": PUBLISHED_20,
    "published_20_plus_linux": [*PUBLISHED_20, "linux"],
    "all_local": ALL_LOCAL,
}


def default_repo_roots(extra_roots: list[str] | None = None) -> list[Path]:
    """Return deduplicated benchmark repo roots."""
    default_root = Path(
        os.environ.get("BENCHMARK_REPOS_DIR", "/Users/eren/Documents/AI/benchmark-repos")
    ).expanduser().resolve()
    roots = [default_root]
    for raw in extra_roots or []:
        candidate = Path(raw).expanduser().resolve()
        if candidate not in roots:
            roots.append(candidate)
    return roots


def resolve_repo_path(repo_id: str, cfg: dict[str, object], repo_roots: list[Path]) -> Path | None:
    """Resolve a repo id to a concrete local path."""
    if cfg.get("source") == "project_root":
        return PROJECT_ROOT

    repo_dir = str(cfg["repo_dir"])
    for root in repo_roots:
        candidate = root / repo_dir
        if candidate.is_dir():
            return candidate
    return None


def clone_repo_if_missing(repo_id: str, cfg: dict[str, object], repo_roots: list[Path]) -> Path | None:
    """Clone a missing repo into the first configured repo root when possible."""
    existing = resolve_repo_path(repo_id, cfg, repo_roots)
    if existing is not None:
        return existing

    clone_url = str(cfg.get("clone_url", "")).strip()
    repo_dir = str(cfg.get("repo_dir", "")).strip()
    if not clone_url or not repo_dir or not repo_roots:
        return None

    target_root = repo_roots[0]
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / repo_dir
    if target.exists():
        return target if target.is_dir() else None

    subprocess.run(
        ["git", "clone", "--depth", "1", clone_url, str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return target
