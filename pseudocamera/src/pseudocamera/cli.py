"""pseudocamera command line interface."""

import argparse
import sys
from pathlib import Path


def build_parser():
    parser = argparse.ArgumentParser(prog="pseudocamera")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prep", help="Prepare frame directories from source material")
    prep.add_argument("source", nargs="?", default=None)
    prep.add_argument("-o", "--out", default="data/frames")
    prep.add_argument("--overlap", type=float, default=0.35)
    prep.add_argument("--max-width", type=int, default=1024)
    prep.add_argument("--max-height", type=int, default=1040)
    prep.add_argument("--left", default=None)
    prep.add_argument("--right", default=None)

    run = sub.add_parser("run", help="Launch segdete with pseudocamera environment")
    run.add_argument("--camemu", type=int, default=2)
    run.add_argument("--frames", default="data/frames")
    run.add_argument("target", nargs=argparse.REMAINDER)

    harness = sub.add_parser("harness", help="Verify the camera-layer masquerade")
    harness.add_argument("--frames", type=int, default=3)
    harness.add_argument("--frames-dir", default="data/frames")
    harness.add_argument("--camemu", type=int, default=2)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "prep":
        from pseudocamera.prep import prep_independent, prep_side_by_side

        if args.left or args.right:
            if not (args.left and args.right):
                raise SystemExit("--left and --right must be given together")
            prep_independent(args.left, args.right, args.out, args.max_width, args.max_height)
        else:
            if not args.source:
                raise SystemExit("prep needs a source directory or --left/--right")
            prep_side_by_side(args.source, args.out, args.overlap, args.max_width, args.max_height)
        return 0
    if args.command == "run":
        from pseudocamera.run import build_run_env, launch, warn_loudly

        frames_dir = Path(args.frames)
        if not (frames_dir / "left").is_dir() or not (frames_dir / "right").is_dir():
            raise SystemExit(
                f"no prepared frames under {frames_dir}; run "
                f"`pseudocamera prep <source> -o {frames_dir}` first"
            )
        warn_loudly()
        target = list(args.target)
        if target and target[0] == "--":
            target = target[1:]
        if not target:
            backend_python = Path("backend/.venv/bin/python")
            if not backend_python.is_file():
                raise SystemExit(
                    "no command given and backend/.venv/bin/python not found"
                )
            target = [str(backend_python), "-m", "pseudocamera.launcher", "--no-web"]
        return launch(target, build_run_env(frames_dir, args.camemu))
    if args.command == "harness":
        from pseudocamera.harness import main as harness_main

        return harness_main(frames=args.frames, frames_dir=args.frames_dir, camemu=args.camemu)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
