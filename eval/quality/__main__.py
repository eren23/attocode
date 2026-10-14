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
    args = parser.parse_args()
    if args.command == "cloud":
        from eval.quality.cloud import main as cloud_main
        return cloud_main(args.target or "quote", root=args.root)
    if args.command == "report":
        from pathlib import Path
        report = Path(args.target or "")
        if report.is_dir():
            report /= "report.json"
        print(report.read_text())
    elif args.command == "storage":
        print(json.dumps(inventory(args.root), indent=2))
    elif args.command == "gc":
        print(json.dumps(prune(args.root, apply=args.apply), indent=2))
    else:
        from eval.quality.runner import LIMITS
        if args.seconds is not None and not 1 <= args.seconds <= LIMITS[args.command]:
            parser.error("--seconds must be positive and no greater than the tier limit")
        path, report = run(args.command, args.root, seconds=args.seconds)
        print(path)
        return 0 if report["status"] == "passed" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
