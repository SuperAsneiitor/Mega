#!/usr/bin/env csh
#===============================================================================
# MegaCell 流程: 给定网表 + stdCell 查找表 → 生成仿真激励 → 调用仿真器 → 输出 Liberty 模板
#
# 用法:
#   ./run_megacell_flow.csh <netlist> <cell_lib_json> <stdcell_verilog_dir> \
#       [verilog_glob] [top_module] [work_dir]
#
# 场景示例:
#
#   # 场景1: Icarus Verilog（默认）
#   ./run_megacell_flow.csh \
#       demo/input/megacell_simple.v \
#       demo/cell_lib/asap7_rvt_tt.json \
#       demo/input/asap7sc7p5t/Verilog
#
#   # 场景2: Synopsys VCS
#   setenv SIMULATOR vcs
#   ./run_megacell_flow.csh \
#       demo/input/megacell_simple.v \
#       demo/cell_lib/asap7_rvt_tt.json \
#       demo/input/asap7sc7p5t/Verilog \
#       '*RVT_TT*.v' \
#       MegaCell_simple \
#       demo/build/vcs_test
#
#   # 场景3: 自定义仿真器
#   setenv SIMULATOR custom
#   setenv COMPILE_CMD_TEMPLATE "vcs -full64 -sverilog {sources} -o {simv}"
#   setenv RUN_CMD_TEMPLATE "{simv}"
#   ./run_megacell_flow.csh ... （参数同上）
#
# 生成产物（在 work_dir 下）:
#   tb_<cell>.v           — 穷举测试平台
#   <cell>.sim.log        — 仿真原始输出
#   <cell>.truth.csv      — 真值表 CSV
#   <cell>.template.lib   — Liberty 模板
#===============================================================================

#-------------------------------------------------------------------------------
# 参数解析
#-------------------------------------------------------------------------------
if ( $#argv < 3 ) then
    echo "用法: $0 <netlist> <cell_lib_json> <stdcell_verilog_dir> [verilog_glob] [top_module] [work_dir]"
    exit 1
endif

set NETLIST="$1"
set CELL_LIB="$2"
set VERILOG_DIR="$3"

# 可选参数及其默认值
if ( $#argv >= 4 ) then
    set VERILOG_GLOB="$4"
else
    set VERILOG_GLOB="*.v"
endif

if ( $#argv >= 5 ) then
    set TOP_MODULE="$5"
else
    set TOP_MODULE=""
endif

if ( $#argv >= 6 ) then
    set WORK_DIR="$6"
else
    set TOP_NAME=`basename "$NETLIST" .v`
    set WORK_DIR="demo/build/${TOP_NAME}"
endif

# 仿真器选择（环境变量，默认 iverilog）
if ( ! $?SIMULATOR ) set SIMULATOR="iverilog"

#-------------------------------------------------------------------------------
# 定位项目根目录并组装 Python 调用
#-------------------------------------------------------------------------------
set FLOW_ROOT=`cd "$(dirname "$0")/.." && pwd`
cd "$FLOW_ROOT"

set CMD="python3 src/megacell_flow.py $NETLIST"
set CMD="$CMD --cell-lib $CELL_LIB"
set CMD="$CMD --stdcell-verilog-dir $VERILOG_DIR"
set CMD="$CMD --stdcell-verilog-glob $VERILOG_GLOB"
set CMD="$CMD --simulator $SIMULATOR"
set CMD="$CMD --work-dir $WORK_DIR"

if ( "$TOP_MODULE" != "" ) then
    set CMD="$CMD --top $TOP_MODULE"
endif

# 按仿真器场景追加对应参数
if ( "$SIMULATOR" == "iverilog" ) then
    if ( $?IVERILOG_BIN ) then
        set CMD="$CMD --iverilog-bin $IVERILOG_BIN"
    endif
else if ( "$SIMULATOR" == "vcs" ) then
    if ( $?VCS_BIN ) then
        set CMD="$CMD --vcs-bin $VCS_BIN"
    endif
else if ( "$SIMULATOR" == "custom" ) then
    if ( $?COMPILE_CMD_TEMPLATE ) then
        set CMD="$CMD --compile-cmd-template '$COMPILE_CMD_TEMPLATE'"
    endif
    if ( $?RUN_CMD_TEMPLATE ) then
        set CMD="$CMD --run-cmd-template '$RUN_CMD_TEMPLATE'"
    endif
endif

#-------------------------------------------------------------------------------
# 执行
#-------------------------------------------------------------------------------
echo "== MegaCell 流程 =="
echo "网表       : $NETLIST"
echo "查找表     : $CELL_LIB"
echo "Verilog目录: $VERILOG_DIR"
echo "顶层模块   : $TOP_MODULE"
echo "工作目录   : $WORK_DIR"
echo "仿真器     : $SIMULATOR"
echo ""

eval $CMD
