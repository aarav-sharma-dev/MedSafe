"""Validate and import DDInter 2.0 CSV files into MedSafe's SQLite database.

DDInter 2.0 download files (https://ddinter2.scbdd.com) are grouped by ATC
anatomical class (e.g. `ddinter_downloads_code_A.csv`) and use columns:
    DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level

Safety & provenance rules enforced by this importer:
* Does NOT overwrite `data/interactions_seed.csv`.
* Preserves the raw `Level` field (`Major`, `Moderate`, `Minor`, `Unknown`).
  `Unknown` is mapped to `unspecified` — never downgraded to `minor`.
* Preserves `DDInterID_A` and `DDInterID_B` as the source record identifier.
* Does NOT fabricate mechanism or management text (DDInter download CSVs do
  not include mechanism prose; those fields remain None).
* Validates all files before writing in a single SQLite transaction so a
  failed import never corrupts or deletes existing data.
* Records DDInter 2.0 attribution and its Creative Commons
  Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0) license terms.

Usage:
    py tools/convert_ddinter.py path/to/ddinter_folder [--version 2.0]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
import dataset_import
import db

DDINTER_META_TEMPLATE = {
    "dataset_id": "ddinter-2.0",
    "name": "DDInter 2.0 Drug-Drug Interaction Database",
    "version": "2.0",
    "source_url": "https://ddinter2.scbdd.com/",
    "license": (
        "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International "
        "(CC BY-NC-SA 4.0). Commercial redistribution is not permitted without "
        "separate authorization from the DDInter authors."
    ),
    "attribution": (
        "Xiong G. et al., DDInter: an online drug-drug interaction database "
        "towards improving clinical decision-making and patient safety, "
        "Nucleic Acids Research (https://ddinter2.scbdd.com/)."
    ),
    "notes": (
        "Imported from DDInter 2.0 CSV download files. DDInter CSV downloads "
        "provide pair identifiers and severity levels (Major, Moderate, Minor, "
        "Unknown) without mechanism prose; 'Unknown' is mapped to 'unspecified'."
    ),
    "is_demo": 0,
}


def import_ddinter_folder(
    folder_or_file: Path | str,
    *,
    db_paths: list[Path] | None = None,
    version: str = "2.0",
) -> dataset_import.ImportReport:
    target = Path(folder_or_file)
    if target.is_dir():
        csv_files = sorted(target.glob("*.csv"))
    elif target.is_file():
        csv_files = [target]
    else:
        rep = dataset_import.ImportReport(dataset_id="ddinter-2.0")
        rep.errors.append(f"Path not found: {target}")
        return rep

    meta = {**DDINTER_META_TEMPLATE, "version": version}
    targets = db_paths or [config.personal_db_path(), config.demo_db_path()]
    last_report: dataset_import.ImportReport | None = None
    for db_path in targets:
        db.init_db(db_path)
        last_report = dataset_import.import_interactions(
            db_path, csv_files, meta, fmt="ddinter"
        )
        if not last_report.ok:
            return last_report
    assert last_report is not None
    return last_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and import DDInter 2.0 CSV files into MedSafe."
    )
    parser.add_argument(
        "path",
        help="Folder containing DDInter 2.0 CSV files (or a single DDInter CSV file).",
    )
    parser.add_argument(
        "--version",
        default="2.0",
        help="Dataset version/release label to record (default: 2.0).",
    )
    args = parser.parse_args(argv)
    report = import_ddinter_folder(args.path, version=args.version)
    print(report.summary())
    if report.rejected:
        print("\nSample rejected rows (up to 10):")
        for fname, row_no, reason in report.rejected[:10]:
            print(f"  {fname} line {row_no}: {reason}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
