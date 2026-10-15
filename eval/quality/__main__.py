"""python -m eval.quality quick|local|broad|storage|report|gc|cloud."""
import argparse
import json

from eval.quality.runner import REPO, inventory, prune, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["quick", "local", "broad", "storage", "report", "gc", "cloud"])
    parser.add_argument("target", nargs="?")
    parser.add_argument("--root", default=str(REPO / ".attocode/quality"))
    parser.add_argument("--apply", action="store_true", help="Apply owned, expired report cleanup")
    parser.add_argument("--seconds", type=int, help="Lower the tier's runtime limit")
    parser.add_argument("--pack", action="append", default=[], help="Select a pinned workflow pack (repeatable)")
    parser.add_argument("--shard", help="Deterministic workflow shard I/N")
    parser.add_argument("--resume", help="Reuse compatible completed workflow evidence")
    parser.add_argument("--suite", choices=["all", "workflows", "ranking"], default="all")
    parser.add_argument("--merge", action="append", default=[], help="Aggregate workflow reports with report TARGET")
    args = parser.parse_args()
    selected = args.pack or args.shard or args.resume or args.suite != "all"
    if selected and args.command not in {"broad", "cloud"}:
        parser.error("Workflow selection requires broad or cloud run")
    if args.command == "cloud" and selected and args.target not in {"run", "probe"}:
        parser.error("Cloud selection requires run or probe")
    if args.merge and args.command != "report":
        parser.error("--merge requires the report command")
    if args.command == "broad" or (args.command == "cloud" and args.target == "run"):
        import yaml

        from eval.quality.corpus import PACK
        from eval.quality.evidence import select_packs
        if args.suite == "ranking" and (args.pack or args.shard or args.resume):
            parser.error("Ranking uses its unchanged complete frozen gate")
        try:
            select_packs(yaml.safe_load(PACK.read_text())["repositories"], args.pack, args.shard)
        except ValueError as exc:
            parser.error(str(exc))
    if args.command == "cloud":
        from eval.quality.cloud import main as cloud_main
        return cloud_main(args.target or "quote", root=args.root,
                          packs=args.pack, shard=args.shard, suite=args.suite, resume=args.resume)
    if args.command == "report":
        from pathlib import Path
        report = Path(args.target or "")
        if report.is_dir():
            report /= "report.json"
        if args.merge:
            from eval.quality.evidence import merge_reports
            merged = merge_reports([json.loads(p.read_text()) for p in [report, *map(Path, args.merge)]])
            print(json.dumps(merged, indent=2))
            return 0 if merged["passed"] else 1
        print(report.read_text())
    elif args.command == "storage":
        print(json.dumps(inventory(args.root), indent=2))
    elif args.command == "gc":
        print(json.dumps(prune(args.root, apply=args.apply), indent=2))
    else:
        from eval.quality.runner import LIMITS
        if args.seconds is not None and not 1 <= args.seconds <= LIMITS[args.command]:
            parser.error("--seconds must be positive and no greater than the tier limit")
        path, report = run(args.command, args.root, seconds=args.seconds, packs=args.pack,
                           shard=args.shard, resume=args.resume, suite=args.suite)
        print(path)
        return 0 if report["status"] == "passed" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
