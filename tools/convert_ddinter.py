"""Convert the DDInter 2.0 dataset into MedSafe's interaction CSV format.

Steps:
1. Download the drug-drug interaction CSVs from DDInter 2.0
   (search 'DDInter 2.0 download' - files are grouped by drug class,
   e.g. ddinter_downloads_code_A.csv).
2. Put them all in one folder.
3. Run:  python tools/convert_ddinter.py path/to/ddinter_folder
4. Reload the database:  python interactions.py

DDInter columns are typically: DDInterID_A, Drug_A, DDInterID_B, Drug_B, Level.
DDInter has no mechanism text, so we write a generic note - the FDA label
text (openFDA) and the AI explanation fill in the details at runtime.
"""

import csv
import sys
from pathlib import Path

OUT = Path(__file__).parent.parent / "data" / "interactions_seed.csv"

LEVEL_MAP = {"major": "major", "moderate": "moderate", "minor": "minor", "unknown": "minor"}


def convert(folder: str) -> int:
    seen = set()
    rows = []
    for csv_file in sorted(Path(folder).glob("*.csv")):
        with open(csv_file, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                a = row.get("Drug_A", "").strip().lower()
                b = row.get("Drug_B", "").strip().lower()
                level = LEVEL_MAP.get(row.get("Level", "").strip().lower())
                if not a or not b or not level:
                    continue
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    (key[0], key[1], level,
                     f"DDInter 2.0 reports a {level} interaction between "
                     f"{key[0]} and {key[1]}. Ask your pharmacist for details.")
                )
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["drug_a", "drug_b", "severity", "mechanism"])
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python tools/convert_ddinter.py path/to/ddinter_folder")
    n = convert(sys.argv[1])
    print(f"Wrote {n} interaction pairs to {OUT}")
    print("Now run:  python interactions.py   (loads them into the database)")
