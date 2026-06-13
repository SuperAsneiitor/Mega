#!/usr/bin/env python3
"""MegaCell Flow — 两条路径从网表到 Liberty 模板.

路径 A（仿真）:  网表 → testbench → iverilog 仿真 → 真值表 → 最小化 → .lib
路径 B（推导）:  网表 + stdCell 查找表 → 符号代入 → 求值 → 最小化 → .lib

子命令:
    sim        仿真路径
    derive     推导路径（需先 build-lib）
    build-lib  构建 stdCell 查找表（前序准备）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parsers.verilog_parser import (
    ModuleInfo, Port,
    ordered_ports, parse_instances, parse_modules,
    scalar_ports, select_module, vector_width,
)
from engines.simulator import run_simulation
from engines.truth_table import parse_truth_table, write_truth_table_csv, TruthTable
from engines.logic_minimizer import functions_from_truth_table, timing_sense
from engines.cell_library import (
    build_cell_library, load_cell_library,
    lookup_cell_area, save_cell_library,
)
from engines.function_deriver import derive_functions, derive_truth_table
from parsers.liberty_parser import resolve_liberty_files
from generators.liberty_writer import generate_lib_template


# ====================================================================
# 共享辅助
# ====================================================================

def _parse_top(netlist: Path, top: str | None) -> tuple[ModuleInfo, list[Port], list[Port], list[str]]:
    """解析网表，返回 module / inputs / outputs / cell_names."""
    text = netlist.read_text()
    module = select_module(parse_modules(text), top)
    ports = ordered_ports(module)
    inputs = scalar_ports([p for p in ports if p.direction == "input"], "Input")
    outputs = scalar_ports([p for p in ports if p.direction == "output"], "Output")
    cell_names = parse_instances(text, module.name)
    if vector_width(inputs) > 20:
        raise ValueError("输入位宽超过 20，拒绝穷举。")
    return module, inputs, outputs, cell_names


def _write_outputs(work_dir: Path, cell_name: str, inputs: list[str],
                   outputs: list[str], functions: dict[str, str],
                   table: TruthTable | None, cell_area: float) -> Path:
    """写入 .truth.csv 和 .template.lib，返回 lib 路径."""
    work_dir.mkdir(parents=True, exist_ok=True)
    if table is not None:
        write_truth_table_csv(table, work_dir / f"{cell_name}.truth.csv")

    # 构建 timing_arcs: output → {input → sense}
    timing_arcs: dict[str, dict[str, str]] = {}
    if table is not None:
        for out_name in outputs:
            timing_arcs[out_name] = {}
            for in_name in inputs:
                sense = timing_sense(table, out_name, in_name)
                if sense is not None:
                    timing_arcs[out_name][in_name] = sense

    out = work_dir / f"{cell_name}.template.lib"
    out.write_text(generate_lib_template(
        cell_name=cell_name,
        inputs=inputs,
        outputs=outputs,
        functions=functions,
        timing_arcs=timing_arcs,
        cell_area=cell_area,
    ))
    return out


# ====================================================================
# 子命令: build-lib
# ====================================================================

def cmd_build_lib(args: argparse.Namespace) -> None:
    lib_paths = resolve_liberty_files([], args.lib_dir, args.glob)
    if not lib_paths:
        raise SystemExit("错误: 未匹配到 Liberty 文件。")
    cell_lib = build_cell_library(lib_paths)
    save_cell_library(cell_lib, args.output)
    print(f"查找表已保存: {args.output} ({len(cell_lib)} 个 cell)")


# ====================================================================
# 子命令: sim
# ====================================================================

def cmd_sim(args: argparse.Namespace) -> None:
    module, inputs, outputs, cell_names = _parse_top(args.netlist, args.top)

    # 1. 标准单元 Verilog（手工指定）
    verilog_files = args.stdcell_list

    # 2. 仿真
    sim_out = run_simulation(
        module=module, netlist=args.netlist, stdcell_verilog=verilog_files,
        work_dir=args.work_dir, simulator="iverilog",
    )

    # 3. 真值表 → 最小化
    table = parse_truth_table(sim_out, inputs, outputs)
    functions = functions_from_truth_table(table)

    # 4. 面积（从 Liberty 快读，可选）
    lib_paths = sorted(args.lib_dir.glob(args.lib_glob)) if args.lib_dir else []
    cell_area = 0.0
    if lib_paths:
        lib = build_cell_library(lib_paths)
        cell_area = sum(lookup_cell_area(lib, c) for c in cell_names)

    (args.work_dir / f"{module.name}.sim.log").write_text(sim_out)

    in_names = [p.name for p in inputs]
    out_names = [p.name for p in outputs]
    out = _write_outputs(args.work_dir, module.name, in_names, out_names,
                         functions, table, cell_area)

    print(f"Top        : {module.name}")
    print(f"输入位宽   : {vector_width(inputs)}")
    print(f"真值表     : {args.work_dir / f'{module.name}.truth.csv'}")
    print(f"Liberty    : {out}")
    for name, func in functions.items():
        print(f"  {name} = {func}")


# ====================================================================
# 子命令: derive
# ====================================================================

def cmd_derive(args: argparse.Namespace) -> None:
    module, inputs, outputs, cell_names = _parse_top(args.netlist, args.top)

    # 1. 加载查找表
    cell_lib = load_cell_library(args.cell_lib)

    # 2. 可选函数覆写
    if args.func_override:
        override = json.loads(args.func_override.read_text())
        for name, funcs in override.get("cells", {}).items():
            if name in cell_lib:
                cell_lib[name].functions.update(funcs)

    # 3. 推导
    functions = derive_functions(
        netlist_text=args.netlist.read_text(),
        top_module=module.name,
        inputs=inputs, outputs=outputs, cell_lib=cell_lib,
    )
    table = derive_truth_table(
        netlist_text=args.netlist.read_text(),
        top_module=module.name,
        inputs=inputs, outputs=outputs, cell_lib=cell_lib,
    )

    # 4. 面积
    cell_area = sum(lookup_cell_area(cell_lib, c) for c in cell_names)

    in_names = [p.name for p in inputs]
    out_names = [p.name for p in outputs]
    out = _write_outputs(args.work_dir, module.name, in_names, out_names,
                         functions, table, cell_area)

    print(f"Top        : {module.name}")
    print(f"输入位宽   : {vector_width(inputs)}")
    print(f"查找表     : {args.cell_lib}")
    print(f"真值表     : {args.work_dir / f'{module.name}.truth.csv'}")
    print(f"Liberty    : {out}")
    for name, func in functions.items():
        print(f"  {name} = {func}")


# ====================================================================
# 主入口
# ====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    # ---- sim ----------------------------------------------------------
    p_sim = sub.add_parser("sim", help="仿真路径: 网表 → iverilog → 真值表 → .lib")
    p_sim.add_argument("netlist", type=Path, help="MegaCell 门级网表 (.v)")
    p_sim.add_argument("--stdcell-list", type=Path, nargs="+", required=True,
                       help="标准单元 Verilog 文件列表")
    p_sim.add_argument("--lib-dir", type=Path, default=None,
                       help="标准单元 Liberty 目录（可选，用于计算面积）")
    p_sim.add_argument("--lib-glob", default="*.lib", help="Liberty 匹配模式")
    p_sim.add_argument("--top", help="顶层模块名（自动检测）")
    p_sim.add_argument("--work-dir", type=Path, default=Path("build/sim"),
                       help="输出目录（默认 build/sim）")

    # ---- derive -------------------------------------------------------
    p_derive = sub.add_parser("derive", help="推导路径: 查找表 + 网表 → 符号代入 → .lib")
    p_derive.add_argument("netlist", type=Path, help="MegaCell 门级网表 (.v)")
    p_derive.add_argument("--cell-lib", type=Path, required=True,
                          help="stdCell 查找表 JSON（由 build-lib 生成）")
    p_derive.add_argument("--func-override", type=Path,
                          help="标准单元函数覆写 JSON（可选）")
    p_derive.add_argument("--top", help="顶层模块名（自动检测）")
    p_derive.add_argument("--work-dir", type=Path, default=Path("build/derive"),
                          help="输出目录（默认 build/derive）")

    # ---- build-lib ----------------------------------------------------
    p_build = sub.add_parser("build-lib", help="构建 stdCell 查找表（前序准备）")
    p_build.add_argument("lib_dir", type=Path, help="标准单元 Liberty 目录")
    p_build.add_argument("-o", "--output", type=Path, required=True,
                         help="输出 JSON 路径")
    p_build.add_argument("--glob", default="*.lib", help="Liberty 匹配模式")

    args = parser.parse_args()

    if args.command == "sim":
        cmd_sim(args)
    elif args.command == "derive":
        cmd_derive(args)
    elif args.command == "build-lib":
        cmd_build_lib(args)


if __name__ == "__main__":
    main()
