#!/usr/bin/env bash
# 推导路径: stdCell 查找表 + 网表 → 符号代入 → 真值表 → 最小化 → Liberty 模板
# 用法: ./run_derive.sh <netlist> <cell_lib.json> [func_override.json] [top] [work_dir]
# 示例: ./run_derive.sh demo/input/megacell_simple.v demo/cell_lib/asap7_rvt_tt.json demo/cell_lib/stdcell_funcs.json MegaCell_simple build/my_test
set -euo pipefail

NETLIST="$1"
CELL_LIB="$2"
FUNC_OVERRIDE="${3:-}"
TOP="${4:-}"
WORK_DIR="${5:-build/derive}"

ARGS=("$NETLIST" --cell-lib "$CELL_LIB" --work-dir "$WORK_DIR")
[[ -n "$FUNC_OVERRIDE" ]] && ARGS+=(--func-override "$FUNC_OVERRIDE")
[[ -n "$TOP" ]] && ARGS+=(--top "$TOP")

python3 src/megacell_flow.py derive "${ARGS[@]}"
