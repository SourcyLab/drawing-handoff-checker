"""Command-line entry point."""

import argparse
import csv
from pathlib import Path
from typing import Optional

from .checker import check_handoff, load_patterns, read_sheets
from .exports import render_summary, write_exports

CTA = (
    "Florida project coming up? Optional scope conversation with Pineland Engineering: "
    "https://pinelandengineering.com/quote/"
    "?utm_source=github&utm_medium=oss&utm_campaign=drawing-handoff-checker"
)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="drawing-handoff-check",
        description="Compare a sheet list against filenames in a local drawing folder.",
    )
    parser.add_argument("sheet_list", type=Path, help="sheet list CSV")
    parser.add_argument("drawing_folder", type=Path, help="folder to scan")
    parser.add_argument("--project", default="Drawing package", help="project name for the reports")
    parser.add_argument("--rules", type=Path, help="custom filename rules JSON")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("handoff-output"), help="export folder"
    )
    parser.add_argument("--no-cta", action="store_true", help="hide the optional closing line")
    args = parser.parse_args(argv)

    try:
        sheets = read_sheets(args.sheet_list)
        patterns = load_patterns(args.rules)
        report = check_handoff(args.project, sheets, args.drawing_folder, patterns)
        inputs = [args.sheet_list]
        if args.rules is not None:
            inputs.append(args.rules)
        write_exports(report, args.output_dir, args.drawing_folder, inputs)
    except (OSError, ValueError, csv.Error, RuntimeError) as error:
        parser.exit(2, f"{parser.prog}: {error}\n")

    print(render_summary(report, args.output_dir))
    if not args.no_cta:
        print(CTA)
    return int(any(report["findings"].values()))
