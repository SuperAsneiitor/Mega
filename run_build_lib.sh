#!/usr/bin/env bash
# 前序准备: 从 Liberty 文件抽取 stdCell function，保存为 JSON 查找表
# 用法: ./run_build_lib.sh <lib_dir> <output.json> [glob]
# 示例: ./run_build_lib.sh demo/input/asap7sc7p5t/LIB/NLDM_d demo/cell_lib/asap7_rvt_tt.json '*RVT_TT*.lib'
set -euo pipefail
python3 src/megacell_flow.py build-lib "$1" -o "$2" --glob "${3:-*.lib}"
