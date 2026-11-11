"""Command line: `blackout build | evaluate | lockbox | export` (docs/plan.md, Tasks 5, 7, 9 and 10)."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from blackout.storms import get_storm, load_storms

if TYPE_CHECKING:
    import pandas as pd


def _build(args: argparse.Namespace) -> int:
    from blackout.table import READ_ERRORS, build_storm, extract_eaglei, log, table_path

    storms = load_storms() if args.all else [get_storm(args.storm)]
    failed = []
    for storm in storms:
        if args.extract_only:
            log(f"{storm.id}: extract at {extract_eaglei(storm)}")
            continue
        if table_path(storm, args.satellite).exists() and not args.force:
            log(f"{storm.id}: {table_path(storm, args.satellite).name} exists (use --force to rebuild)")
            continue
        try:
            build_storm(storm, satellite=args.satellite)
        except READ_ERRORS as err:  # one storm's network failure must not stop --all; rerun it later
            log(f"{storm.id}: FAILED {type(err).__name__}: {err}")
            failed.append(storm.id)
    if failed:
        log(f"failed storms (rerun them): {' '.join(failed)}")
    return 1 if failed else 0


def _evaluate(args: argparse.Namespace) -> int:
    from blackout.evaluate import write_scorecard

    write_scorecard()
    return 0


def saved_scorecards() -> pd.DataFrame | None:
    """Score tables written by `blackout evaluate` (main storms) and `blackout lockbox` (Helene, Milton, Uri)."""
    import pandas as pd

    from blackout.table import PROCESSED, SCORES_FINAL_FILE, SCORES_LOSO_FILE

    paths = (PROCESSED / SCORES_LOSO_FILE, PROCESSED / SCORES_FINAL_FILE)
    frames = [pd.read_parquet(p) for p in paths if p.exists()]
    return pd.concat(frames, ignore_index=True) if frames else None


def _export(args: argparse.Namespace) -> int:
    from blackout.export import export_sample, export_storm

    scores = saved_scorecards()
    if args.sample:
        export_sample(scorecard=scores)
    else:
        export_storm(args.storm, scorecard=scores)
    return 0


def _lockbox(args: argparse.Namespace) -> int:
    """Open the lockbox once. Opened already, it refuses and says why; `--reopen "<reason>"` writes a new, timestamped
    result beside the first one, which stays the record (decision log, D-12)."""
    import json

    from blackout.final import LockboxOpenedError, run_final

    if args.reopen is not None and not args.reopen.strip():
        print("blackout lockbox refused: --reopen needs a reason, in words, for looking again (D-12)", file=sys.stderr)
        return 1
    try:
        result = run_final(reopen_reason=args.reopen)
    except LockboxOpenedError as err:
        print(f"blackout lockbox refused: {err}", file=sys.stderr)
        return 1
    summary = {"verdict": result["verdict"], "pass_bar": {k: v.get(60, v) for k, v in result["pass_bar"].items()}}
    if args.reopen is None:
        from blackout.evaluate import write_scorecard

        write_scorecard()  # re-render docs/scorecard.md with the lockbox section
    else:
        summary["reopen"] = result["reopen"]
        print(f"reopened: wrote {result['reopen']['result']} and {result['reopen']['outputs']}/; the first result is "
              "unchanged. Log the reason in docs/decision-log.md (D-12).", file=sys.stderr)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blackout", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build county x night tables")
    which = build.add_mutually_exclusive_group(required=True)
    which.add_argument("--storm", help="storm id from config/storms.yaml, e.g. ian2022")
    which.add_argument("--all", action="store_true", help="every storm in config/storms.yaml")
    build.add_argument("--satellite", default=None, choices=["VNP46A2", "VJ146A2"],
                       help="default: the storm's own (VNP46A2, or VJ146A2 where Suomi NPP has a gap)")
    build.add_argument("--force", action="store_true", help="rebuild tables that already exist")
    build.add_argument("--extract-only", action="store_true", help="only copy the EAGLE-I rows for each storm")
    build.set_defaults(func=_build)
    evaluate = sub.add_parser("evaluate", help="leave-one-storm-out scorecard -> docs/scorecard.md")
    evaluate.set_defaults(func=_evaluate)
    export = sub.add_parser("export", help="static JSON for the app")
    target = export.add_mutually_exclusive_group(required=True)
    target.add_argument("--storm")
    target.add_argument("--sample", action="store_true", help="the bundled Ian sample (no downloads)")
    export.set_defaults(func=_export)
    lockbox = sub.add_parser("lockbox", help="final fit; score Helene and Milton once against the committed pass bar")
    lockbox.add_argument("--reopen", metavar="REASON", default=None,
                         help="look again after the one opening: writes lockbox_result_<UTC time>.json beside the first "
                              "result, never over it; the reason is recorded inside and must be logged (D-12)")
    lockbox.set_defaults(func=_lockbox)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
