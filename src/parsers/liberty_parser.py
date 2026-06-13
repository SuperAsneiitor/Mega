#!/usr/bin/env python3
"""Liberty (.lib) file parsing for standard cell characterisation data.

Extracts per-cell area, pin directions, and combinational function expressions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CellInfo:
    """Information about one standard cell parsed from a Liberty file."""

    area: float | None = None
    pins: dict[str, str] = field(default_factory=dict)  # name → "input" | "output"
    functions: dict[str, str] = field(default_factory=dict)  # output_pin → expression


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------


def resolve_liberty_files(
    explicit_files: list[Path],
    lib_dir: Path | None,
    lib_glob: str,
) -> list[Path]:
    """Resolve Liberty file paths from explicit list or dir + glob."""
    if explicit_files:
        return explicit_files
    if lib_dir is None:
        raise ValueError("Pass --stdcell-lib-dir or at least one --stdcell-lib-file.")
    return sorted(lib_dir.glob(lib_glob))


# ---------------------------------------------------------------------------
# Liberty parsing
# ---------------------------------------------------------------------------


def _parse_liberty_value(val_str: str) -> str:
    """Strip quotes and whitespace from a Liberty attribute value."""
    val = val_str.strip()
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        val = val[1:-1]
    return val


def parse_liberty_cells(lib_paths: list[Path]) -> dict[str, CellInfo]:
    """Parse Liberty files and return a dict mapping cell name → CellInfo.

    Extracts for each cell:
    - ``area``
    - ``direction`` of every pin (input / output)
    - ``function`` of every output pin
    """
    cells: dict[str, CellInfo] = {}

    cell_re = re.compile(r"^\s*cell\s*\(\s*([^\s)]+)\s*\)\s*\{")
    pin_re = re.compile(r"^\s*pin\s*\(\s*([^\s)]+)\s*\)\s*\{")
    area_re = re.compile(r"^\s*area\s*:\s*([-+0-9.eE]+)\s*;")
    direction_re = re.compile(r"^\s*direction\s*:\s*(\S+)\s*;")
    function_re = re.compile(r"^\s*function\s*:\s*(\S.*?)\s*;")

    for path in lib_paths:
        text = path.read_text()

        current_cell: str | None = None
        current_pin: str | None = None
        depth = 0  # unified nesting depth from current cell's opening brace

        for raw_line in text.splitlines():
            line = raw_line.strip()
            delta = line.count("{") - line.count("}")

            if current_cell is not None:
                depth += delta

            # ---- Inside a pin block ---------------------------------------
            if current_pin is not None:
                dm = direction_re.match(line)
                if dm:
                    direction = dm.group(1).strip().strip('"')
                    cells[current_cell].pins[current_pin] = direction

                fm = function_re.match(line)
                if fm:
                    func_expr = _parse_liberty_value(fm.group(1))
                    cells[current_cell].functions[current_pin] = func_expr

                if depth <= 1:
                    # depth=1 means we're at the pin's closing brace
                    # (cell's own brace + pin's brace → 2, minus pin close → 1)
                    current_pin = None
                continue

            # ---- Inside a cell, not in a pin -------------------------------
            if current_cell is not None:
                am = area_re.match(line)
                if am and cells[current_cell].area is None:
                    cells[current_cell].area = float(am.group(1))

                pm = pin_re.match(line)
                if pm:
                    current_pin = pm.group(1).strip()
                    continue

                if depth <= 0:
                    current_cell = None
                continue

            # ---- Outside any cell ------------------------------------------
            cm = cell_re.match(line)
            if cm:
                current_cell = cm.group(1).strip()
                depth = delta  # typically 1 for the cell's opening brace
                cells.setdefault(current_cell, CellInfo())

    return cells
