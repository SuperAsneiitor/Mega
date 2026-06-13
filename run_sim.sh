#!/usr/bin/env bash
# 仿真路径: 网表 → testbench → iverilog 仿真 → 真值表 → 最小化 → Liberty 模板
# 用法: ./run_sim.sh <netlist> <stdcell_dir> [top] [work_dir]
# 示例: ./run_sim.sh demo/input/megacell_simple.v demo/input/asap7sc7p5t/Verilog MegaCell_simple build/my_test
set -euo pipefail

NETLIST="$1"
STDCELL_DIR="$2"
TOP="${3:-}"
WORK_DIR="${4:-build/sim}"

ARGS=("$NETLIST" --stdcell-dir "$STDCELL_DIR" --work-dir "$WORK_DIR")
[[ -n "$TOP" ]] && ARGS+=(--top "$TOP")

python3 src/megacell_flow.py sim "${ARGS[@]}"
