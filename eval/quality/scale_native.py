"""Short prospective native checks; no historical attribution or scored queries."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

from eval.quality.scale_evidence import require, write


def admit_grammars(inventory):
    require(
        all(inventory.get(name) is True for name in ("ocaml", "rust", "perl", "crystal")),
        "required native grammar missing",
    )


def run(root, output):
    import tree_sitter_language_pack as pack
    import yaml
    from attocode_intel._internal.integrations.context import ts_parser

    from eval.quality.corpus import evaluate, materialize
    from eval.quality.corpus_capture import journal_events
    from eval.quality.experiment_evidence import Journal
    from eval.quality.fixture_identity import source_manifest
    from eval.quality.native_capture import NativeCapture, read_capture

    root, output = Path(root), Path(output)
    output.mkdir(parents=True)
    pack.configure(cache_dir=os.environ["QUALITY_GRAMMAR_CACHE"])
    inventory = {
        name: ts_parser.is_available(name) for name in ("ocaml", "rust", "perl", "crystal")
    }
    admit_grammars(inventory)
    write(
        output / "grammars.json",
        {
            "available": inventory,
            "cache_files": {
                p.relative_to(Path(os.environ["QUALITY_GRAMMAR_CACHE"])).as_posix(): hashlib.sha256(
                    p.read_bytes()
                ).hexdigest()
                for p in Path(os.environ["QUALITY_GRAMMAR_CACHE"]).rglob("*")
                if p.is_file()
            },
        },
    )
    packs = yaml.safe_load(Path("eval/quality/workflows.yaml").read_text())["repositories"]
    report = {"complete": False, "queries": 0, "repositories": []}
    for name in ("ocaml", "deno", "perl", "crystal"):
        spec = dict(next(s for s in packs if s["id"] == name))
        spec.pop("queries", None)
        tree, folder = root / "work" / ("native-" + name), output / name
        tree.mkdir(parents=True)
        folder.mkdir()
        receipt = {}
        materialize(spec, tree, root / "cache" / ("native-" + name), receipt=receipt)
        write(folder / "pinned-source.json", receipt)
        if name == "perl":
            # Explicitly exercise the labeled source under the published ignore contract.
            ignore = tree / ".gitignore"
            original = ignore.read_text() if ignore.exists() else ""
            ignore.write_text(original + "\n!dist/\ndist/*\n!dist/Carp/\n")
        before = source_manifest(tree)
        write(folder / "actual-source.json", before)
        journal = Journal(folder / "journal", 4 * 2**20)
        capture = NativeCapture(
            folder / "native-ocaml.jsonl" if name == "ocaml" else None, tree, spec
        )
        try:
            with capture.capture():
                checks = asyncio.run(evaluate(tree, spec, journal=journal))
            if name == "ocaml":
                capture.require_complete()
                trace = read_capture(folder / "native-ocaml.jsonl", tree, spec, capture.summary())
                write(folder / "native-admission.json", trace)
            require(source_manifest(tree) == before, "native fixture source changed")
            events = journal_events(folder / "journal")
            require(
                events and all(c["outcome"] in {"passed", "limited"} for c in checks),
                "native compatibility failed or unsupported",
            )
            row = {
                "id": name,
                "complete": True,
                "checks": checks,
                "raw_events": len(events),
                "native_capture": capture.summary() if name == "ocaml" else None,
                "limitation": None
                if name == "ocaml"
                else "Raw gateway/grammar identity only; no new LSP or generic native parser trace",
            }
            report["repositories"].append(row)
            write(folder / "result.json", row)
        finally:
            write(output / "result.json", report)
    report["complete"] = len(report["repositories"]) == 4
    write(output / "result.json", report)
    return report
