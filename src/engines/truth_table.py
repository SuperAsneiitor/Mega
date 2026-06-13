#!/usr/bin/env python3
"""Truth table representation and parsing from simulation output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from parsers.verilog_parser import Port


@dataclass(frozen=True)
class TruthTable:
    """Exhaustive truth table for a combinational module.

    Each row maps input port values to output port values (as ``"0"`` /
    ``"1"`` strings).  The row order matches the simulation output.
    """

    inputs: list[Port]
    outputs: list[Port]
    rows: list[tuple[dict[str, str], dict[str, str]]]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def parse_truth_table(sim_output: str, inputs: list[Port], outputs: list[Port]) -> TruthTable:
    """Parse a truth table from the stdout of the generated testbench.

    The testbench prints a header line::

        A B C | Y Z

    followed by rows::

        0 0 0 | 1 0
        0 0 1 | 0 1
        ...

    Returns a TruthTable with one entry per row.
    """
    input_names = [port.name for port in inputs]
    output_names = [port.name for port in outputs]
    expected_header = f"{' '.join(input_names)} | {' '.join(output_names)}"

    rows: list[tuple[dict[str, str], dict[str, str]]] = []
    in_table = False
    for raw_line in sim_output.splitlines():
        line = raw_line.strip()
        if line == expected_header:
            in_table = True
            continue
        if not in_table or "|" not in line:
            continue
        left, right = [part.strip() for part in line.split("|", 1)]
        in_values = left.split()
        out_values = right.split()
        if len(in_values) != len(inputs) or len(out_values) != len(outputs):
            continue
        rows.append((dict(zip(input_names, in_values)), dict(zip(output_names, out_values))))

    if not rows:
        raise ValueError("No truth-table rows found in simulation output.")
    return TruthTable(inputs=inputs, outputs=outputs, rows=rows)


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------


def write_truth_table_csv(table: TruthTable, path: Path) -> None:
    """Write a TruthTable to CSV with a header row."""
    header = [port.name for port in table.inputs] + [port.name for port in table.outputs]
    rows = [
        [row_inputs[port.name] for port in table.inputs]
        + [row_outputs[port.name] for port in table.outputs]
        for row_inputs, row_outputs in table.rows
    ]
    path.write_text(
        ",".join(header) + "\n" + "\n".join(",".join(row) for row in rows) + "\n"
    )
