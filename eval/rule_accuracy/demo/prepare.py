"""Derive display inputs from an explicitly refreshed scoring directory."""
import argparse
import json
from pathlib import Path

from eval.rule_accuracy.demo.scan import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads((args.directory / "findings.json").read_text())
    timeline = json.loads((args.directory / "timeline.json").read_text())
    compact = [{"r": r["rule"], "f": r["file"], "l": r["line"],
                "sec": int(r["rule"].startswith("security/") or r["cwe"].startswith("CWE")),
                "tp": int(r["is_tp"]), "c": r["constant"], "j": r["jev"],
                "m": r["llm"], "s": r["snippet"]} for r in rows]
    race = [{"r": r["rule"], "f": r["file"], "l": r["line"], "sec": r["sec"],
             "tp": r["tp"], "c": r["constant"], "js": r["jev"]["s"], "je": r["jev"]["e"],
             "jp": r["jev"]["p"], "ms": r["llm"]["s"], "me": r["llm"]["e"],
             "mp": r["llm"]["p"], "w": r["llm"]["why"]} for r in timeline["findings"]]
    write_json(args.directory / "compact.json", compact)
    write_json(args.directory / "race.json", race)


if __name__ == "__main__":
    main()
