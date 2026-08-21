from __future__ import annotations

import re
from typing import Any

ELEMENTS = {
    "Al", "Ag", "Au", "Cd", "Co", "Cr", "Cu", "Fe", "Ga", "Ge", "Hg",
    "In", "Ir", "Mn", "Mo", "Ni", "Os", "Pb", "Pd", "Pt", "Re", "Rh",
    "Ru", "Sc", "Sn", "Ta", "Ti", "V", "W", "Zn", "Zr",
}

REACTION_ALIASES = {
    "co2rr": "CO2RR",
    "co2 reduction": "CO2RR",
    "carbon dioxide reduction": "CO2RR",
    "her": "HER",
    "hydrogen evolution": "HER",
    "oer": "OER",
    "oxygen evolution": "OER",
}


def normalize_reaction(value: str) -> str | None:
    lower = value.strip().lower()
    for alias, label in REACTION_ALIASES.items():
        if alias in lower:
            return label
    return value.strip() or None


def normalize_elements(values: list[Any]) -> list[str]:
    found: list[str] = []
    for value in values:
        symbol = str(value).strip().capitalize()
        if symbol in ELEMENTS and symbol not in found:
            found.append(symbol)
    return found


def normalize_intermediate(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip())
    if cleaned and cleaned not in {"CO", "HCOOH", "CH3OH"} and not cleaned.endswith("*"):
        cleaned += "*"
    return cleaned


def contains_evidence(quote: str, title: str, abstract: str) -> bool:
    normalized_quote = " ".join(quote.split()).lower()
    source = " ".join(f"{title} {abstract}".split()).lower()
    return bool(normalized_quote) and normalized_quote in source
