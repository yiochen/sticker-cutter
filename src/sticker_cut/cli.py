from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .geometry import PreparationError, build_layout, page_spec, parse_mm
from .output import write_outputs
from .silhouette import run_dry_run
from .verify import write_verify_report


def _positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sticker-cut", description="Prepare raster sticker sheets for Silhouette Print & Cut")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="detect stickers and write print/cut artifacts")
    prepare.add_argument("input", type=Path, help="input raster sticker sheet (PNG recommended)")
    prepare.add_argument("-o", "--output", type=Path, default=Path("output"), help="output directory (default: output)")
    prepare.add_argument("--border", type=parse_mm, default=2.0, metavar="LENGTH", help="physical cut border (default: 2mm)")
    prepare.add_argument("--page", default="letter", help="letter, a4, or WIDTHxHEIGHT in mm")
    prepare.add_argument("--input-dpi", type=_positive_float, help="override source physical resolution")
    prepare.add_argument("--dpi", type=_positive_float, default=300.0, help="print raster DPI (default: 300)")
    prepare.add_argument("--alpha-threshold", type=int, default=16, help="foreground alpha threshold 0-255")
    prepare.add_argument("--background-threshold", type=float, default=24.0, help="opaque-image RGB distance threshold")
    prepare.add_argument("--min-area", type=float, default=1.0, metavar="MM2", help="ignore components smaller than this area")
    prepare.add_argument("--closing", type=parse_mm, default=0.3, metavar="LENGTH", help="mask closing radius (default: 0.3mm)")
    prepare.add_argument("--simplify", type=parse_mm, default=0.12, metavar="LENGTH", help="contour simplification tolerance")
    prepare.add_argument("--reg-origin", type=parse_mm, default=10.0, metavar="LENGTH", help="registration origin from top/left")

    verify = subparsers.add_parser("verify", help="validate agreement and safety of an output directory")
    verify.add_argument("output", type=Path)

    dry = subparsers.add_parser("silhouette-dry-run", help="exercise inkscape-silhouette without a cutter")
    dry.add_argument("svg", type=Path)
    dry.add_argument("--driver", type=Path, help="path to sendto_silhouette.py")
    dry.add_argument("--python", type=Path, help="Python interpreter containing inkex and driver dependencies")
    dry.add_argument("--force-hardware", default="Silhouette_Cameo3", help="driver hardware name for deterministic command generation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            if not args.input.is_file():
                raise PreparationError(f"Input file does not exist: {args.input}")
            layout = build_layout(
                args.input,
                page=page_spec(args.page),
                border_mm=args.border,
                input_dpi=args.input_dpi,
                output_dpi=args.dpi,
                alpha_threshold=args.alpha_threshold,
                background_threshold=args.background_threshold,
                min_area_mm2=args.min_area,
                closing_mm=args.closing,
                simplify_mm=args.simplify,
                reg_origin_mm=args.reg_origin,
            )
            artifacts = write_outputs(layout, args.output)
            report = write_verify_report(args.output)
            summary = {
                "output": str(args.output.resolve()),
                "sticker_count": len(layout.stickers),
                "verified": report["passed"],
                "warnings": layout.warnings,
                "files": {name: str(path.resolve()) for name, path in artifacts.items()},
            }
            print(json.dumps(summary, indent=2))
            return 0 if report["passed"] else 2
        if args.command == "verify":
            report = write_verify_report(args.output)
            print(json.dumps(report, indent=2))
            return 0 if report["passed"] else 2
        if args.command == "silhouette-dry-run":
            result = run_dry_run(
                args.svg,
                driver=args.driver,
                python_executable=args.python,
                force_hardware=args.force_hardware,
            )
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 3
    except (PreparationError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
