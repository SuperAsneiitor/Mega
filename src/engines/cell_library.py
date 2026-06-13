#!/usr/bin/env python3
"""Standard-cell function lookup table.

Pre-extracts area, pin directions, and logic functions from Liberty files
and caches them as JSON so that subsequent MegaCell runs can look up
stdCell information without re-parsing the .lib files.
"""

from __future__ import annotations

import json
from pathlib import Path

from parsers.liberty_parser import CellInfo, parse_liberty_cells


# JSON serialisation helpers
def _cell_to_dict(cell: CellInfo) -> dict:
    return {
        "area": cell.area,
        "pins": dict(cell.pins),
        "functions": dict(cell.functions),
    }


def _dict_to_cell(d: dict) -> CellInfo:
    return CellInfo(
        area=d.get("area"),
        pins=d.get("pins", {}),
        functions=d.get("functions", {}),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_cell_library(liberty_paths: list[Path]) -> dict[str, CellInfo]:
    """Parse Liberty files and return a dict mapping cell name → CellInfo.

    This is the full-parse path; use :func:`save_cell_library` to cache
    the result and :func:`load_cell_library` for subsequent runs.
    """
    return parse_liberty_cells(liberty_paths)


def save_cell_library(cell_lib: dict[str, CellInfo], path: Path) -> None:
    """Persist a cell library to a JSON file."""
    data = {
        "cells": {name: _cell_to_dict(cell) for name, cell in cell_lib.items()}
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def load_cell_library(path: Path) -> dict[str, CellInfo]:
    """Load a cell library from a JSON file."""
    data = json.loads(path.read_text())
    return {
        name: _dict_to_cell(cell_data)
        for name, cell_data in data.get("cells", {}).items()
    }


def lookup_cell_area(cell_lib: dict[str, CellInfo], cell_name: str) -> float:
    """Return the area of *cell_name* from the library.

    Returns 0.0 if the cell is not found.
    """
    cell = cell_lib.get(cell_name)
    if cell is None or cell.area is None:
        return 0.0
    return cell.area
