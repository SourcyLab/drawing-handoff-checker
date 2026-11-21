# drawing-handoff-checker

A local Python CLI for checking a drawing handoff against a CSV sheet register. It
compares sheet numbers and revisions parsed from filenames and flags missing
sheets, duplicate files, duplicate register rows, revision mismatches, blank
owners, and unmatched extra files. It supports Architectural Drawings, Existing
Conditions, and Survey.

## Install

Python 3.9 or later is required. Run the install command from the repository
root in a virtual environment.

```sh
python -m pip install .
```

Install the test extra to develop and run the tests.

```sh
python -m pip install -e '.[test]'
pytest
```

## Usage

Save your sheet register as a UTF-8 CSV using the headers below.

```csv
sheet_number,title,discipline,owner,required_revision
A-101,Floor Plan,Architectural Drawings,Sample Architecture Team,B
```

Use the revision value itself, such as `B` for `RevB`. Sheet numbers, disciplines,
and revisions compare case-insensitively. Surrounding whitespace is trimmed and
a blank owner is flagged. The CLI scans the selected folder's top-level files.
Each sheet number is expected to be unique across the register. When more than
one filename identifies the same sheet, the CLI reports all candidates and
compares each revision with each corresponding register row.

```sh
drawing-handoff-check sheet-list.csv drawings/ \
  --project "Sample Bayside Pavilion" --output-dir handoff-output --no-cta
```

The output folder defaults to `handoff-output`. It contains a complete
`report.json`, `transmittal.csv`, and `handoff-checklist.md`. The
`architectural-drawings/`, `existing-conditions/`, and `survey/` subfolders
each contain the same CSV and checklist formats for their discipline. The CSV
keeps one row per register row and matching file, with empty file fields when a
sheet is missing. The consolidated checklist and JSON include unmatched files.
A checked box means the filename and register checks found no issues for that
row.

The CLI returns `0` for a clean handoff, `1` when exports were written with
findings, and `2` for input or export errors. Use `--no-cta` to hide the optional
closing line.

## Fork filename rules

The bundled rules recognize names such as `A-101_Floor-Plan_RevB.pdf`. Copy
[`examples/filename-rules.json`](examples/filename-rules.json), then edit its
`patterns` list with your firm's Python regular expressions. Each pattern must
define named groups `sheet_number` and `revision`. Patterns match the full
basename including its extension. The first full match with both groups
populated wins. Escape backslashes for JSON, such as `\\.pdf` for a literal dot.

```sh
drawing-handoff-check sheet-list.csv drawings/ --rules firm-rules.json --no-cta
```

## Privacy

The CLI runs locally using only the Python standard library. It reads the
contents of the sheet-list CSV and the filename rules JSON. It inspects drawing
filenames and never opens drawing files. It makes no network requests, sends no
telemetry, and requires no email address. The optional link is printed as text.

## Sample result

The files in `examples/drawings/` are empty placeholders for the synthetic
Sample Bayside Pavilion project. Run `./examples/run.sh --no-cta` to reproduce
this result and write the exports to `examples/output/`.

```text
Drawing handoff check — Sample Bayside Pavilion
Sheet list rows: 5 | Files scanned: 6
Missing sheets: 1
  - A-102 (CSV line 3)
Duplicate files: 1
  - A-101 — A-101_Floor-Plan-Alternate_RevA.pdf, A-101_Floor-Plan_RevB.pdf
Duplicate sheets: 1
  - EC-101 (CSV lines 4, 5)
Revision mismatches: 1
  - A-101 (CSV line 2) — A-101_Floor-Plan-Alternate_RevA.pdf, found A, required B
Unresolved ownership: 1
  - EC-101 (CSV line 4)
Unmatched extra files: 2
  - SV-999_Extra-Survey_RevA.pdf (sheet not in list)
  - unlisted-notes.txt (filename did not match rules)
Exports: examples/output
Design and scope decisions remain with the project professionals.
```

## Disclaimer

Design and scope decisions remain with the project professionals.

Florida firm license (Certificate of Authorization) No. 39202 — Designda Inc DBA Pineland Engineering.

## License

[Apache License 2.0](LICENSE).
