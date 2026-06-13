#!/usr/bin/env python3
"""Generate a Liberty (.lib) template for a MegaCell.

The template fills function, timing_sense, and area.  Timing and power
table values are left as characterization placeholders.
"""

from __future__ import annotations

from parsers.verilog_parser import ModuleInfo
from engines.truth_table import TruthTable
from engines.logic_minimizer import timing_sense


def generate_lib_template(
    module: ModuleInfo,
    table: TruthTable,
    functions: dict[str, str],
    cell_area: float,
) -> str:
    """Generate a complete Liberty template string for *module*.

    Parameters
    ----------
    module : ModuleInfo
        The parsed top module.
    table : TruthTable
        The truth table (used to derive timing senses).
    functions : dict[str, str]
        Pre-computed Liberty function strings keyed by output port name.
    cell_area : float
        Total cell area (sum of instantiated stdCell areas).
    """
    lines = [
        "library (megacell_template) {",
        "  delay_model : table_lookup;",
        "",
        f"  cell ({module.name}) {{",
        f"    area : {cell_area:.6g};",
    ]

    for pin in table.inputs:
        lines.extend(
            [
                f"    pin ({pin.name}) {{",
                "      direction : input;",
                "    }",
            ]
        )

    for pin in table.outputs:
        lines.extend(
            [
                f"    pin ({pin.name}) {{",
                "      direction : output;",
                f'      function : "{functions[pin.name]}";',
                '      power_down_function : "(!VDD) + (VSS)";',
            ]
        )
        for input_pin in table.inputs:
            sense = timing_sense(table, pin.name, input_pin.name)
            if sense is None:
                continue
            lines.extend(
                [
                    "      timing () {",
                    f'        related_pin : "{input_pin.name}";',
                    f"        timing_sense : {sense};",
                    "        timing_type : combinational;",
                    "        /* Fill cell_rise/cell_fall and transition tables by characterization. */",
                    "      }",
                ]
            )
        lines.append("    }")

    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"
