"""Read the sheet register and compare it against a directory listing."""

import csv
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Optional

DISCIPLINES = {
    "Architectural Drawings": "architectural-drawings",
    "Existing Conditions": "existing-conditions",
    "Survey": "survey",
}
DISCIPLINE_NAMES = {label.casefold(): label for label in DISCIPLINES}
DISCIPLINE_NAMES["architectural"] = "Architectural Drawings"
CSV_FIELDS = ("sheet_number", "title", "discipline", "owner", "required_revision")
FINDING_LABELS = {
    "missing_sheets": "Missing sheets",
    "duplicate_files": "Duplicate files",
    "duplicate_sheets": "Duplicate sheets",
    "revision_mismatches": "Revision mismatches",
    "unresolved_ownership": "Unresolved ownership",
    "unmatched_extra_files": "Unmatched extra files",
}


@dataclass(frozen=True)
class Sheet:
    sheet_number: str
    title: str
    discipline: str
    owner: str
    required_revision: str
    csv_line: int


@dataclass(frozen=True)
class Drawing:
    filename: str
    sheet_number: str
    revision: str


def read_sheets(path: Path) -> list[Sheet]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        header = next(reader, [])
        if len(header) != len(CSV_FIELDS) or set(header) != set(CSV_FIELDS):
            raise ValueError(f"{path} must have these CSV headers: {', '.join(CSV_FIELDS)}")

        sheets = []
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                return sheets
            if not values:
                continue
            if len(values) != len(header):
                raise ValueError(f"{path}:{line}: expected {len(header)} CSV fields")
            row = {field: value.strip() for field, value in zip(header, values)}
            for field in ("sheet_number", "discipline", "required_revision"):
                if not row[field]:
                    raise ValueError(f"{path}:{line}: {field} must have a value")
            discipline = DISCIPLINE_NAMES.get(" ".join(row["discipline"].split()).casefold())
            if discipline is None:
                raise ValueError(
                    f"{path}:{line}: unknown discipline {row['discipline']!r}; "
                    f"expected {', '.join(DISCIPLINES)}"
                )
            row["discipline"] = discipline
            sheets.append(Sheet(**row, csv_line=line))


def load_patterns(path: Optional[Path]) -> list[re.Pattern]:
    source = path if path is not None else files(__package__).joinpath("filename-rules.json")
    with source.open(encoding="utf-8-sig") as config:
        rules = json.load(config)
    patterns = rules.get("patterns") if isinstance(rules, dict) else None
    if not isinstance(patterns, list) or not patterns:
        raise ValueError(f"{source}: patterns must be a nonempty list of regex strings")

    compiled = []
    for index, pattern in enumerate(patterns, start=1):
        if not isinstance(pattern, str) or not pattern:
            raise ValueError(f"{source}: pattern {index} must be a nonempty regex string")
        try:
            regex = re.compile(pattern)
        except re.error as error:
            raise ValueError(f"{source}: invalid regex in pattern {index}: {error}") from error
        if not {"sheet_number", "revision"}.issubset(regex.groupindex):
            raise ValueError(f"{source}: pattern {index} needs sheet_number and revision groups")
        compiled.append(regex)
    return compiled


def parse_filename(filename: str, patterns: list[re.Pattern]) -> Optional[Drawing]:
    for pattern in patterns:
        match = pattern.fullmatch(filename)
        if match:
            sheet_number = (match["sheet_number"] or "").strip()
            revision = (match["revision"] or "").strip()
            if sheet_number and revision:
                return Drawing(filename, sheet_number, revision)
    return None


def check_handoff(
    project: str, sheets: list[Sheet], folder: Path, patterns: list[re.Pattern]
) -> dict:
    sheet_groups = defaultdict(list)
    for sheet in sheets:
        sheet_groups[sheet.sheet_number.casefold()].append(asdict(sheet))

    file_groups = defaultdict(list)
    findings = {key: [] for key in FINDING_LABELS}
    file_count = 0
    for path in sorted(folder.iterdir(), key=lambda entry: (entry.name.casefold(), entry.name)):
        if not path.is_file():
            continue
        file_count += 1
        drawing = parse_filename(path.name, patterns)
        if drawing is None:
            findings["unmatched_extra_files"].append(
                {"filename": path.name, "reason": "filename_did_not_match_rules"}
            )
            continue
        key = drawing.sheet_number.casefold()
        file_groups[key].append(asdict(drawing))
        if key not in sheet_groups:
            findings["unmatched_extra_files"].append(
                {**asdict(drawing), "reason": "sheet_not_in_list"}
            )

    for drawings in file_groups.values():
        if len(drawings) > 1:
            findings["duplicate_files"].append(
                {"sheet_number": drawings[0]["sheet_number"], "files": drawings}
            )
    for group in sheet_groups.values():
        if len(group) > 1:
            findings["duplicate_sheets"].append(
                {"sheet_number": group[0]["sheet_number"], "sheets": group}
            )

    packages = {discipline: [] for discipline in DISCIPLINES}
    for sheet in sheets:
        row = asdict(sheet)
        key = sheet.sheet_number.casefold()
        drawings = file_groups.get(key, [])
        issues = []
        if not drawings:
            findings["missing_sheets"].append(row)
            issues.append("missing_sheets")
        if len(drawings) > 1:
            issues.append("duplicate_files")
        if len(sheet_groups[key]) > 1:
            issues.append("duplicate_sheets")
        mismatches = []
        for drawing in drawings:
            if drawing["revision"].casefold() != sheet.required_revision.casefold():
                mismatches.append({"sheet": row, "file": drawing})
        if mismatches:
            findings["revision_mismatches"].extend(mismatches)
            issues.append("revision_mismatches")
        if not sheet.owner:
            findings["unresolved_ownership"].append(row)
            issues.append("unresolved_ownership")
        packages[sheet.discipline].append({**row, "files": drawings, "issues": issues})

    return {
        "project": project,
        "sheet_count": len(sheets),
        "file_count": file_count,
        "findings": findings,
        "disciplines": packages,
    }
