#!/usr/bin/env csh
#===============================================================================
# 前序准备: 从 Liberty 文件提取 stdCell 的 function/area/pin 方向，保存为 JSON 查找表
#
# 用法:
#   ./run_build_cell_lib.csh <lib_dir> <lib_glob> <output_json>
#
# 示例:
#   ./run_build_cell_lib.csh \
#       demo/input/asap7sc7p5t/LIB/NLDM_d \
#       '*RVT_TT*.lib' \
#       demo/cell_lib/asap7_rvt_tt.json
#
# 生成产物:
#   demo/cell_lib/asap7_rvt_tt.json  — stdCell 查找表（含 area, function, pin 方向）
#===============================================================================

set LIB_DIR="$1"
set LIB_GLOB="$2"
set OUTPUT_JSON="$3"

echo "== 构建 stdCell 查找表 =="
echo "Liberty 目录 : $LIB_DIR"
echo "匹配模式     : $LIB_GLOB"
echo "输出路径     : $OUTPUT_JSON"
echo ""

python3 src/megacell_flow.py --build-cell-lib \
    --stdcell-lib-dir "$LIB_DIR" \
    --lib-glob "$LIB_GLOB" \
    --cell-lib-path "$OUTPUT_JSON"
