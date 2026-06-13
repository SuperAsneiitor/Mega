#!/usr/bin/env python3
"""Generate an exhaustive combinational Verilog testbench from a netlist.

The generated testbench drives every input-bit combination and prints one
truth-table row per vector.  Intended for small combinational MegaCells.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from parsers.verilog_parser import ModuleInfo, Port, parse_modules, select_module, vector_width


def decl_line(kind: str, port: Port) -> str:
    """Generate a ``reg`` or ``wire`` declaration line for a port."""
    width = f" {port.width_expr}" if port.width_expr else ""
    return f"    {kind}{width} {port.name};"


def format_concat(ports: list[Port]) -> str:
    """Return comma-separated port names for concatenation."""
    return ", ".join(port.name for port in ports)


def display_format(ports: list[Port]) -> str:
    """Return a ``%b %b ...`` format string for $display."""
    return " ".join("%b" for _ in ports)


def display_args(ports: list[Port]) -> str:
    """Return comma-separated port names for $display arguments."""
    return ", ".join(port.name for port in ports)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------


def generate_testbench(module: ModuleInfo, delay: int = 1, max_vectors: int = 1_000_000) -> str:
    """Generate a self-checking exhaustive testbench for *module*.

    Parameters
    ----------
    module : ModuleInfo
        The parsed top module.
    delay : int
        Simulation time units to wait after each input vector.
    max_vectors : int
        Safety limit on the number of generated vectors.

    Returns
    -------
    str
        Complete Verilog testbench source.
    """
    ordered_ports = [module.ports[name] for name in module.port_order if name in module.ports]
    inputs = [port for port in ordered_ports if port.direction == "input"]
    outputs = [port for port in ordered_ports if port.direction == "output"]

    if not inputs:
        raise ValueError(f"Module '{module.name}' has no input ports.")
    if not outputs:
        raise ValueError(f"Module '{module.name}' has no output ports.")

    total_input_bits = vector_width(inputs)
    vector_count = 1 << total_input_bits
    if vector_count > max_vectors:
        raise ValueError(
            f"{module.name} has {total_input_bits} input bits, requiring {vector_count} "
            f"vectors. Increase --max-vectors if this is expected."
        )

    input_concat = format_concat(inputs)
    dut_ports = "\n".join(f"        .{port.name}({port.name})," for port in ordered_ports)
    dut_ports = dut_ports.rstrip(",")
    input_names = " ".join(port.name for port in inputs)
    output_names = " ".join(port.name for port in outputs)
    row_fmt = f"{display_format(inputs)} | {display_format(outputs)}"
    row_display_args = ", ".join(
        arg for arg in [display_args(inputs), display_args(outputs)] if arg
    )

    lines: list[str] = [
        "`timescale 1ns/10ps",
        "",
        f"module tb_{module.name};",
    ]
    lines.extend(decl_line("reg", port) for port in inputs)
    lines.extend(decl_line("wire", port) for port in outputs)
    lines.extend(
        [
            "",
            f"    reg [{total_input_bits}:0] vector;",
            "",
            f"    {module.name} dut (",
            dut_ports,
            "    );",
            "",
            "    initial begin",
            f'        $dumpfile("{module.name}.vcd");',
            f"        $dumpvars(0, tb_{module.name});",
            f'        $display("{input_names} | {output_names}");',
            f"        for (vector = 0; vector < {vector_count}; vector = vector + 1) begin",
            f"            {{{input_concat}}} = vector[{total_input_bits - 1}:0];",
            f"            #{delay};",
            f'            $display("{row_fmt}", {row_display_args});',
            "        end",
            "        $finish;",
            "    end",
            "endmodule",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate exhaustive Verilog stimulus for a combinational MegaCell netlist."
    )
    parser.add_argument("netlist", type=Path, help="Path to the MegaCell Verilog netlist.")
    parser.add_argument("--top", help="Top module name. Required if the file has multiple modules.")
    parser.add_argument(
        "-o", "--out", type=Path,
        help="Output testbench path. Defaults to <netlist_dir>/tb_<top>.v.",
    )
    parser.add_argument("--delay", type=int, default=1, help="Delay after each input vector.")
    parser.add_argument(
        "--max-vectors", type=int, default=1_000_000,
        help="Safety limit for generated exhaustive vectors.",
    )
    args = parser.parse_args()

    module = select_module(parse_modules(args.netlist.read_text()), args.top)
    out_path = args.out or args.netlist.with_name(f"tb_{module.name}.v")
    out_path.write_text(generate_testbench(module, args.delay, args.max_vectors))
    print(f"Generated {out_path} for top module {module.name}")


if __name__ == "__main__":
    main()
