#!/usr/bin/env python3
"""Build a Liberty-style template for a combinational MegaCell.

Flow
----
1. (Optional) Build or load a stdCell lookup table from Liberty files.
2. Parse the MegaCell netlist to discover ports and instantiated stdCells.
3. Generate an exhaustive testbench and run gate-level simulation.
4. Parse the truth table from simulation output.
5. Minimize each scalar output with Quine-McCluskey.
6. Emit a Liberty template containing pins, functions, area, and
   placeholder timing arcs.

This is intended for small combinational MegaCells.  Exhaustive
simulation grows as 2^N input bits.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from parsers.verilog_parser import (
    ordered_ports,
    parse_instances,
    parse_modules,
    scalar_ports,
    select_module,
    vector_width,
)
from engines.simulator import resolve_stdcell_verilog, run_simulation
from engines.truth_table import parse_truth_table, write_truth_table_csv
from engines.logic_minimizer import functions_from_truth_table
from parsers.liberty_parser import resolve_liberty_files
from generators.liberty_writer import generate_lib_template
from engines.cell_library import (
    build_cell_library,
    load_cell_library,
    lookup_cell_area,
    save_cell_library,
)
from engines.function_deriver import derive_functions, derive_truth_table


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)

    # ---- MegaCell input ---------------------------------------------------
    parser.add_argument(
        "netlist", type=Path, nargs="?",
        help="MegaCell gate-level Verilog netlist.",
    )
    parser.add_argument("--top", help="Top MegaCell module name.")

    # ---- stdCell Verilog --------------------------------------------------
    parser.add_argument(
        "--stdcell-verilog-dir", type=Path, default=None,
        help="Directory containing stdCell Verilog models.",
    )
    parser.add_argument(
        "--stdcell-verilog-glob", default="*.v",
        help="Glob used when scanning --stdcell-verilog-dir.",
    )
    parser.add_argument(
        "--stdcell-verilog-file", type=Path, action="append", default=[],
        help="Explicit stdCell Verilog model file. Repeatable.",
    )

    # ---- stdCell Liberty --------------------------------------------------
    parser.add_argument(
        "--stdcell-lib-dir", type=Path, default=None,
        help="Directory containing stdCell Liberty files.",
    )
    parser.add_argument(
        "--stdcell-lib-file", type=Path, action="append", default=[],
        help="Explicit stdCell Liberty file. Repeatable.",
    )
    parser.add_argument("--lib-glob", default="*.lib", help="StdCell Liberty glob.")

    # ---- Cell library (lookup table) --------------------------------------
    parser.add_argument(
        "--cell-lib", type=Path, default=None,
        help="Pre-built stdCell lookup table (JSON). Skips Liberty parsing.",
    )
    parser.add_argument(
        "--build-cell-lib", action="store_true",
        help="Build a stdCell lookup table from Liberty files and exit.",
    )
    parser.add_argument(
        "--cell-lib-path", type=Path, default=None,
        help="Output path for --build-cell-lib (default: demo/cell_lib/).",
    )
    parser.add_argument(
        "--derive", action="store_true",
        help="使用组合推导模式（跳过仿真，由 stdCell function 逐级代入合成）。",
    )
    parser.add_argument(
        "--cell-func-override", type=Path, default=None,
        help="标准单元函数覆写 JSON（用于纠正 NLDM Liberty 中不准确的 function）。",
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="同时运行推导与仿真，对比两者真值表是否一致。",
    )

    # ---- Simulation -------------------------------------------------------
    parser.add_argument(
        "--simulator", choices=["iverilog", "vcs", "custom"], default="iverilog",
        help="Simulation backend.",
    )
    parser.add_argument("--iverilog-bin", default="iverilog")
    parser.add_argument("--vvp-bin", default="vvp")
    parser.add_argument("--vcs-bin", default="vcs")
    parser.add_argument(
        "--compile-cmd-template",
        help="Custom compile command. Placeholders: {sources}, {simv}, {work_dir}, ...",
    )
    parser.add_argument(
        "--run-cmd-template",
        help="Custom run command. Placeholders: {sources}, {simv}, {work_dir}, ...",
    )

    # ---- Output -----------------------------------------------------------
    parser.add_argument("--work-dir", type=Path, default=Path("build/megacell_flow"))
    parser.add_argument("--out", type=Path, help="Output Liberty template path.")
    parser.add_argument("--delay", type=int, default=1)
    parser.add_argument("--max-vectors", type=int, default=1_000_000)

    args = parser.parse_args()

    # ---- Build-cell-lib mode: parse Liberty, save JSON, exit ---------------
    if args.build_cell_lib:
        lib_paths = resolve_liberty_files(
            args.stdcell_lib_file, args.stdcell_lib_dir, args.lib_glob
        )
        if not lib_paths:
            raise ValueError("No stdCell Liberty files matched the input configuration.")
        cell_lib = build_cell_library(lib_paths)
        out_path = args.cell_lib_path or Path("demo/cell_lib/default.json")
        save_cell_library(cell_lib, out_path)
        print(f"Cell library saved to {out_path} ({len(cell_lib)} cells)")
        return

    # ---- Normal flow: require netlist -------------------------------------
    if args.netlist is None:
        parser.error("netlist is required (or use --build-cell-lib to build the lookup table).")

    netlist_text = args.netlist.read_text()
    module = select_module(parse_modules(netlist_text), args.top)
    ports = ordered_ports(module)
    inputs = scalar_ports([p for p in ports if p.direction == "input"], "Input")
    outputs = scalar_ports([p for p in ports if p.direction == "output"], "Output")

    if vector_width(inputs) > 20:
        raise ValueError("Refusing exhaustive simulation above 20 input bits.")

    cell_names = parse_instances(netlist_text, module.name)

    # ---- Resolve stdCell Verilog -------------------------------------------
    stdcell_verilog = resolve_stdcell_verilog(
        args.stdcell_verilog_file,
        args.stdcell_verilog_dir,
        args.stdcell_verilog_glob,
        set(cell_names),
    )

    # ---- Resolve cell area (from lookup table or Liberty) ------------------
    if args.cell_lib:
        # Fast path: use pre-built lookup table
        cell_lib = load_cell_library(args.cell_lib)
        cell_area = sum(lookup_cell_area(cell_lib, cell) for cell in cell_names)
    else:
        # Slow path: parse Liberty files
        lib_paths = resolve_liberty_files(
            args.stdcell_lib_file, args.stdcell_lib_dir, args.lib_glob
        )
        if not lib_paths:
            raise ValueError("No stdCell Liberty files matched the input configuration.")
        cell_lib = build_cell_library(lib_paths)
        cell_area = sum(lookup_cell_area(cell_lib, cell) for cell in cell_names)

    # ---- 应用函数覆写（如果有） --------------------------------------------
    if args.cell_func_override:
        import json
        override_data = json.loads(args.cell_func_override.read_text())
        for cell_name, funcs in override_data.get("cells", {}).items():
            if cell_name in cell_lib:
                cell_lib[cell_name].functions.update(funcs)

    # ---- 运行推导 或 仿真 --------------------------------------------------
    if args.derive:
        # 组合推导模式：跳过仿真，纯符号推导
        print("模式: 组合推导（无仿真）")
        functions = derive_functions(
            netlist_text=netlist_text,
            top_module=module.name,
            inputs=inputs,
            outputs=outputs,
            cell_lib=cell_lib,
        )
        # 推导模式下仍生成真值表（由表达式求值得到）
        table = derive_truth_table(
            netlist_text=netlist_text,
            top_module=module.name,
            inputs=inputs,
            outputs=outputs,
            cell_lib=cell_lib,
        )
    else:
        # 仿真模式：编译运行仿真器，从 stdout 提取真值表
        sim_output = run_simulation(
            module=module,
            netlist=args.netlist,
            stdcell_verilog=stdcell_verilog,
            work_dir=args.work_dir,
            delay=args.delay,
            max_vectors=args.max_vectors,
            simulator=args.simulator,
            iverilog_bin=args.iverilog_bin,
            vvp_bin=args.vvp_bin,
            vcs_bin=args.vcs_bin,
            compile_cmd_template=args.compile_cmd_template,
            run_cmd_template=args.run_cmd_template,
        )
        table = parse_truth_table(sim_output, inputs, outputs)
        functions = functions_from_truth_table(table)

    # ---- 对比模式（同时运行推导和仿真，diff 真值表） ------------------------
    if args.compare:
        print("模式: 对比验证（推导 vs 仿真）")
        # 仿真
        sim_output = run_simulation(
            module=module,
            netlist=args.netlist,
            stdcell_verilog=stdcell_verilog,
            work_dir=args.work_dir,
            delay=args.delay,
            max_vectors=args.max_vectors,
            simulator=args.simulator,
            iverilog_bin=args.iverilog_bin,
            vvp_bin=args.vvp_bin,
            vcs_bin=args.vcs_bin,
            compile_cmd_template=args.compile_cmd_template,
            run_cmd_template=args.run_cmd_template,
        )
        sim_table = parse_truth_table(sim_output, inputs, outputs)
        sim_funcs = functions_from_truth_table(sim_table)

        # 推导
        derive_table = derive_truth_table(
            netlist_text=netlist_text,
            top_module=module.name,
            inputs=inputs,
            outputs=outputs,
            cell_lib=cell_lib,
        )
        derive_funcs = derive_functions(
            netlist_text=netlist_text,
            top_module=module.name,
            inputs=inputs,
            outputs=outputs,
            cell_lib=cell_lib,
        )

        # 对比真值表
        sim_rows = {(tuple(r[0].values()), tuple(r[1].values())) for r in sim_table.rows}
        derive_rows = {(tuple(r[0].values()), tuple(r[1].values())) for r in derive_table.rows}
        if sim_rows == derive_rows:
            print("✓ 真值表一致：推导结果与仿真完全匹配")
        else:
            print("✗ 真值表不一致！")
            print(f"  仿真独有: {sim_rows - derive_rows}")
            print(f"  推导独有: {derive_rows - sim_rows}")

        # 对比函数
        print("仿真函数:")
        for name, func in sim_funcs.items():
            print(f"  {name} = {func}")
        print("推导函数:")
        for name, func in derive_funcs.items():
            print(f"  {name} = {func}")

        # 以仿真结果为准输出
        table = sim_table
        functions = sim_funcs

    # ---- Write outputs -----------------------------------------------------
    args.work_dir.mkdir(parents=True, exist_ok=True)
    if not args.derive or args.compare:
        (args.work_dir / f"{module.name}.sim.log").write_text(
            sim_output if not args.derive else ""
        )
    write_truth_table_csv(table, args.work_dir / f"{module.name}.truth.csv")

    out_path = args.out or args.work_dir / f"{module.name}.template.lib"
    out_path.write_text(generate_lib_template(module, table, functions, cell_area))

    print(f"Top: {module.name}")
    print("StdCell Verilog:")
    for path in stdcell_verilog:
        print(f"  {path}")
    if args.cell_lib:
        print(f"Cell library: {args.cell_lib}")
    print("Functions:")
    for name, function in functions.items():
        print(f"  {name} = {function}")
    print(f"Truth table: {args.work_dir / f'{module.name}.truth.csv'}")
    print(f"Liberty template: {out_path}")


if __name__ == "__main__":
    main()
