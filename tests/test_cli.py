import csv
import json
from pathlib import Path

import pytest

from drawing_handoff_checker.cli import CTA, main

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def sample(tmp_path, capsys):
    output = tmp_path / "output"
    status = main([
        str(EXAMPLES / "sheet-list.csv"),
        str(EXAMPLES / "drawings"),
        "--project", "Sample Bayside Pavilion",
        "--rules", str(EXAMPLES / "filename-rules.json"),
        "--output-dir", str(output),
    ])
    return status, output, json.loads((output / "report.json").read_text()), capsys.readouterr().out


@pytest.mark.parametrize(
    ("finding", "count", "label"),
    [
        ("missing_sheets", 1, "Missing sheets"),
        ("duplicate_files", 1, "Duplicate files"),
        ("duplicate_sheets", 1, "Duplicate sheets"),
        ("revision_mismatches", 1, "Revision mismatches"),
        ("unresolved_ownership", 1, "Unresolved ownership"),
        ("unmatched_extra_files", 2, "Unmatched extra files"),
    ],
)
def test_finding_counts_are_reported(sample, finding, count, label):
    status, _, report, stdout = sample
    assert status == 1
    assert len(report["findings"][finding]) == count
    assert f"{label}: {count}\n" in stdout


def test_finding_details(sample):
    _, _, report, _ = sample
    findings = report["findings"]
    assert findings["missing_sheets"][0]["sheet_number"] == "A-102"
    assert {file["revision"] for file in findings["duplicate_files"][0]["files"]} == {"A", "B"}
    assert [row["csv_line"] for row in findings["duplicate_sheets"][0]["sheets"]] == [4, 5]
    mismatch = findings["revision_mismatches"][0]
    assert mismatch["file"]["revision"] == "A"
    assert mismatch["sheet"]["required_revision"] == "B"
    assert findings["unresolved_ownership"][0]["owner"] == ""
    assert {item["filename"]: item["reason"] for item in findings["unmatched_extra_files"]} == {
        "SV-999_Extra-Survey_RevA.pdf": "sheet_not_in_list",
        "unlisted-notes.txt": "filename_did_not_match_rules",
    }


def read_csv(path):
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def test_consolidated_and_discipline_exports(sample):
    _, output, report, stdout = sample
    assert stdout.splitlines()[-1] == CTA
    assert stdout.count(CTA) == 1
    checklist = (output / "handoff-checklist.md").read_text(encoding="utf-8")
    assert "Design and scope decisions remain with the project professionals." in checklist
    assert "## Unmatched extra files" in checklist
    transmittal = read_csv(output / "transmittal.csv")
    assert len(transmittal) == 6
    missing = next(row for row in transmittal if row["sheet_number"] == "A-102")
    assert (missing["filename"], missing["findings"]) == ("", "missing_sheets")
    assert {
        row["found_revision"]: row["findings"]
        for row in transmittal if row["sheet_number"] == "A-101"
    } == {"A": "duplicate_files, revision_mismatches", "B": "duplicate_files"}

    for discipline, slug in [
        ("Architectural Drawings", "architectural-drawings"),
        ("Existing Conditions", "existing-conditions"),
        ("Survey", "survey"),
    ]:
        folder = output / slug
        rows = read_csv(folder / "transmittal.csv")
        assert rows == [row for row in transmittal if row["discipline"] == discipline]
        checklist = (folder / "handoff-checklist.md").read_text(encoding="utf-8")
        assert f"## {discipline}" in checklist
        assert CTA not in checklist

    assert report["disciplines"]["Survey"][0]["issues"] == []
    assert "- [x] **SV-101**" in (output / "survey/handoff-checklist.md").read_text(encoding="utf-8")


def make_input(tmp_path, sheet_number="a-101", revision="b"):
    sheet_list = tmp_path / "sheets.csv"
    sheet_list.write_text(
        "sheet_number,title,discipline,owner,required_revision\n"
        f"{sheet_number},Plan,architectural,Sample Team,{revision}\n",
        encoding="utf-8",
    )
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    return sheet_list, drawings


def test_default_rules_skip_subdirectories_and_no_cta(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sheet_list, drawings = make_input(tmp_path)
    (drawings / "A-101_Floor_Plan_RevB.PDF").write_bytes(b"\xff\x00")
    nested = drawings / "nested"
    nested.mkdir()
    (nested / "extra.pdf").touch()

    original_open = Path.open

    def guard_open(path, *args, **kwargs):
        assert not path.is_relative_to(drawings), f"opened a drawing: {path}"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guard_open)
    assert main([str(sheet_list), str(drawings), "--no-cta"]) == 0
    stdout = capsys.readouterr().out
    assert CTA not in stdout
    assert "Files scanned: 1" in stdout
    assert stdout.splitlines()[-1] == "Design and scope decisions remain with the project professionals."
    assert (tmp_path / "handoff-output/report.json").is_file()


def test_custom_rules_in_order(tmp_path, capsys):
    sheet_list, drawings = make_input(tmp_path, "PLAN_7", "01")
    (drawings / "01--PLAN_7.dwg").touch()
    rules = tmp_path / "rules.json"
    rules.write_text(json.dumps({"patterns": [
        r"(?P<revision>[0-9]{2})--(?P<sheet_number>PLAN_[0-9]+)\.dwg",
        r"(?P<sheet_number>[0-9]{2})--(?P<revision>PLAN_[0-9]+)\.dwg",
    ]}), encoding="utf-8")
    assert main([
        str(sheet_list), str(drawings), "--rules", str(rules),
        "--output-dir", str(tmp_path / "out"),
    ]) == 0
    assert "Unmatched extra files: 0" in capsys.readouterr().out


def test_invalid_rules_exit_without_exports(tmp_path, capsys):
    sheet_list, drawings = make_input(tmp_path)
    rules = tmp_path / "rules.json"
    rules.write_text('{"patterns": ["(?P<sheet_number>.*)"]}', encoding="utf-8")
    output = tmp_path / "out"
    with pytest.raises(SystemExit) as error:
        main([str(sheet_list), str(drawings), "--rules", str(rules), "--output-dir", str(output)])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "revision groups" in captured.err
    assert captured.out == ""
    assert not output.exists()


def test_output_cannot_replace_a_drawing(tmp_path, capsys):
    sheet_list, drawings = make_input(tmp_path)
    original = drawings / "report.json"
    original.write_text("original", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main([str(sheet_list), str(drawings), "--output-dir", str(drawings)])
    assert error.value.code == 2
    assert "export would write into the scanned folder" in capsys.readouterr().err
    assert original.read_text(encoding="utf-8") == "original"
