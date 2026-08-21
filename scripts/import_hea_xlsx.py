"""Import the local HEA workbook into the searchable literature database."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.literature.repository import LiteratureRepository
from tools.literature.schemas import PaperRecord


def clean(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def split_labels(value: Any) -> list[str]:
    return [item.strip() for item in re.split(r"[;,；，|]+", clean(value)) if item.strip()]


def year_from_text(*values: str) -> int | None:
    for value in values:
        match = re.search(r"\b(19|20)\d{2}\b", value)
        if match:
            return int(match.group(0))
    return None


def paper_id(url: str, title: str, row: int) -> str:
    identity = url.lower().strip() or title.lower().strip() or f"row:{row}"
    return "hea-xlsx-" + hashlib.sha1(identity.encode("utf-8")).hexdigest()[:16]


def import_workbook(path: Path, repository: LiteratureRepository) -> dict[str, int]:
    imported = 0
    skipped = 0
    for sheet in pd.ExcelFile(path).sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet)
        if sheet != "Sheet1":
            continue
        for offset, row in frame.iterrows():
            source_row = int(offset) + 2
            title = clean(row.get("Article Title"))
            abstract = clean(row.get("Article Abstract"))
            url = clean(row.get("URL"))
            composition = clean(row.get("Filtered Alloy Composition"))
            if not (title or abstract or url or composition):
                skipped += 1
                continue
            reaction = split_labels(row.get(" Electrocatalytic Reaction"))
            original_reaction = split_labels(row.get("Original Electrocatalytic Reaction"))
            keywords = split_labels(row.get(" Keywords")) + split_labels(row.get("Original Keywords"))
            snippet = clean(row.get(" Evidence Snippet")) or clean(row.get("Original Evidence Snippet"))
            doi = re.sub(r"^https?://doi.org/", "", url, flags=re.I).strip()
            record = PaperRecord(
                paper_id=paper_id(url, title, source_row),
                title=title,
                abstract=abstract,
                year=year_from_text(title, abstract),
                url=url,
                doi=doi,
                source="high_entropy_alloy_xlsx",
                source_file=str(path),
                source_sheet=sheet,
                source_row=source_row,
                composition_raw=composition,
                reaction_labels=list(dict.fromkeys(reaction + original_reaction)),
                keywords=list(dict.fromkeys(keywords)),
                evidence_snippet=snippet,
                context_misread_flag=clean(row.get("Context Misread Flag")).lower() == "true",
                provenance={
                    "metadata": "xlsx_structured_fields",
                    "composition": "Filtered Alloy Composition",
                    "reaction": "Electrocatalytic Reaction",
                    "claim": "Evidence Snippet, Article Abstract, or Article Title",
                    "prompt_fields_are_primary_evidence": False,
                },
            )
            repository.upsert(record)
            imported += 1
    return {"imported": imported, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--database", default="database/literature/literature.db")
    args = parser.parse_args()
    result = import_workbook(args.workbook.resolve(), LiteratureRepository(args.database))
    print(f"hea_xlsx_imported={result['imported']}")
    print(f"hea_xlsx_skipped={result['skipped']}")


if __name__ == "__main__":
    main()
