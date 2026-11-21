"""Render the text summary and the local handoff exports."""

import csv
import io
import json
import re
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile

from .checker import CSV_FIELDS, DISCIPLINES, FINDING_LABELS

DISCLAIMER = "Design and scope decisions remain with the project professionals."


def display(value: str) -> str:
    """Keep values on one line and escape control characters."""
    return "".join(char if char.isprintable() else ascii(char)[1:-1] for char in value)


def markdown(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()!#~|])", r"\\\1", escape(display(value), quote=False))


def summary_details(kind: str, finding: dict) -> str:
    if kind in ("missing_sheets", "unresolved_ownership"):
        return f"{display(finding['sheet_number'])} (CSV line {finding['csv_line']})"
    if kind == "duplicate_files":
        names = ", ".join(display(file["filename"]) for file in finding["files"])
        return f"{display(finding['sheet_number'])} — {names}"
    if kind == "duplicate_sheets":
        lines = ", ".join(str(sheet["csv_line"]) for sheet in finding["sheets"])
        return f"{display(finding['sheet_number'])} (CSV lines {lines})"
    if kind == "revision_mismatches":
        sheet, file = finding["sheet"], finding["file"]
        return (
            f"{display(sheet['sheet_number'])} (CSV line {sheet['csv_line']}) — "
            f"{display(file['filename'])}, found {display(file['revision'])}, "
            f"required {display(sheet['required_revision'])}"
        )
    reason = {
        "filename_did_not_match_rules": "filename did not match rules",
        "sheet_not_in_list": "sheet not in list",
    }[finding["reason"]]
    return f"{display(finding['filename'])} ({reason})"


def render_summary(report: dict, output: Path) -> str:
    lines = [
        f"Drawing handoff check — {display(report['project'])}",
        f"Sheet list rows: {report['sheet_count']} | Files scanned: {report['file_count']}",
    ]
    for kind, label in FINDING_LABELS.items():
        findings = report["findings"][kind]
        lines.append(f"{label}: {len(findings)}")
        lines.extend(f"  - {summary_details(kind, finding)}" for finding in findings)
    lines.extend((f"Exports: {display(str(output))}", DISCLAIMER))
    return "\n".join(lines)


def render_transmittal(rows: list[dict]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow([*CSV_FIELDS, "csv_line", "filename", "found_revision", "findings"])
    for row in rows:
        sheet_fields = [row[field] for field in (*CSV_FIELDS, "csv_line")]
        if row["files"]:
            for file in row["files"]:
                issues = row["issues"]
                if file["revision"].casefold() == row["required_revision"].casefold():
                    issues = [issue for issue in issues if issue != "revision_mismatches"]
                writer.writerow(
                    [*sheet_fields, file["filename"], file["revision"], ", ".join(issues)]
                )
        else:
            writer.writerow([*sheet_fields, "", "", ", ".join(row["issues"])])
    return buffer.getvalue()


def render_checklist(project: str, packages: dict, findings: dict) -> str:
    lines = [f"# {markdown(project)} — handoff checklist", "", DISCLAIMER]
    for discipline, rows in packages.items():
        lines.extend(("", f"## {discipline}", ""))
        if not rows:
            lines.append("No sheets listed.")
        for row in rows:
            mark = " " if row["issues"] else "x"
            owner = markdown(row["owner"]) if row["owner"] else "Unassigned"
            lines.append(
                f"- [{mark}] **{markdown(row['sheet_number'])}** "
                f"{markdown(row['title'])} (CSV line {row['csv_line']}) — "
                f"{owner}, required revision {markdown(row['required_revision'])}"
            )
            for file in row["files"]:
                lines.append(
                    f"  - {markdown(file['filename'])} — revision {markdown(file['revision'])}"
                )
            if row["issues"]:
                labels = ", ".join(FINDING_LABELS[issue] for issue in row["issues"])
                lines.append(f"  - Review {labels.lower()}.")
    extras = findings.get("unmatched_extra_files", [])
    if extras:
        lines.extend(("", "## Unmatched extra files", ""))
        lines.extend(
            f"- [ ] {markdown(summary_details('unmatched_extra_files', extra))}"
            for extra in extras
        )
    return "\n".join(lines) + "\n"


def write_exports(
    report: dict, output: Path, drawing_folder: Path, input_paths: list[Path]
) -> None:
    packages = report["disciplines"]
    all_rows = sorted(
        (row for rows in packages.values() for row in rows), key=lambda row: row["csv_line"]
    )
    exports = {
        output / "report.json": json.dumps(report, indent=2) + "\n",
        output / "transmittal.csv": render_transmittal(all_rows),
        output / "handoff-checklist.md": render_checklist(
            report["project"], packages, report["findings"]
        ),
    }
    for discipline, rows in packages.items():
        directory = output / DISCIPLINES[discipline]
        exports[directory / "transmittal.csv"] = render_transmittal(rows)
        exports[directory / "handoff-checklist.md"] = render_checklist(
            report["project"], {discipline: rows}, {}
        )

    resolved_inputs = {path.resolve() for path in input_paths}
    resolved_folder = drawing_folder.resolve()
    for destination in exports:
        if destination.parent.resolve() == resolved_folder:
            raise ValueError(f"export would write into the scanned folder: {destination}")
        if destination.is_symlink() or destination.resolve() in resolved_inputs:
            raise ValueError(f"export would overwrite an input or symlink: {destination}")
        if destination.exists() and not destination.is_file():
            raise ValueError(f"export path is not a regular file: {destination}")

    for destination, content in exports.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Replace complete reports so an interrupted write leaves the previous file intact.
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            try:
                temporary.write(content)
                temporary.close()
                temporary_path.replace(destination)
            finally:
                temporary_path.unlink(missing_ok=True)
