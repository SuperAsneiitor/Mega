#!/usr/bin/env bash
#===============================================================================
# MegaCell Flow — 组合逻辑 MegaCell Liberty 模板自动生成流程（Bash 入口）
#
# 用法:
#   ./run_megacell_flow.sh <config.env> <netlist.v> [top_module] [work_dir]
#
# 示例:
#   ./run_megacell_flow.sh ../demo/config/asap7_rvt_tt.env ../demo/input/megacell_simple.v MegaCell_simple
#
# 配置文件（.env）中可覆盖的环境变量见 usage() 函数。
#===============================================================================

set -euo pipefail

#-------------------------------------------------------------------------------
# 函数: usage — 打印帮助信息
#-------------------------------------------------------------------------------
usage() {
    cat <<'EOF'
用法:
  run_megacell_flow.sh <config.env> <netlist.v> [top_module] [work_dir]

示例:
  # 使用 Icarus Verilog 仿真
  ./run_megacell_flow.sh ../demo/config/asap7_rvt_tt.env \
    ../demo/input/megacell_simple.v MegaCell_simple

  # 使用 VCS 仿真（配置文件中设 SIMULATOR=vcs）
  SIMULATOR=vcs ./run_megacell_flow.sh ../demo/config/asap7_rvt_tt.env \
    ../demo/input/megacell_simple.v MegaCell_simple

配置文件 (.env) 中可设置的环境变量:
  TECH_NAME               工艺名称（用于默认输出路径，默认 generic）
  CORNER_NAME             工艺角名称（用于默认输出路径，默认 default）
  STDCELL_VERILOG_DIR     标准单元 Verilog 模型目录
  STDCELL_VERILOG_GLOB    标准单元 Verilog 模型匹配模式（默认 *.v）
  STDCELL_VERILOG_FILES   显式列出标准单元 Verilog 文件（空格分隔）
  STDCELL_LIB_DIR         标准单元 Liberty 文件目录
  STDCELL_LIB_GLOB        标准单元 Liberty 文件匹配模式（默认 *.lib）
  STDCELL_LIB_FILES       显式列出标准单元 Liberty 文件（空格分隔）
  SIMULATOR               仿真器: iverilog | vcs | custom（默认 iverilog）
  IVERILOG_BIN            iverilog 可执行文件路径（默认 iverilog）
  VVP_BIN                 vvp 可执行文件路径（默认 vvp）
  VCS_BIN                 vcs 可执行文件路径（默认 vcs）
  CELL_LIB                预构建的 stdCell 查找表 JSON 路径（可选）
  COMPILE_CMD_TEMPLATE    自定义编译命令模板（SIMULATOR=custom 时使用）
  RUN_CMD_TEMPLATE        自定义运行命令模板（SIMULATOR=custom 时必需）
  MAX_VECTORS             穷举向量安全上限（默认 1000000）
  SIM_DELAY               测试平台稳定延时（默认 1）
EOF
}

#-------------------------------------------------------------------------------
# 第一阶段: 解析命令行参数
#-------------------------------------------------------------------------------
if [[ $# -lt 2 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

# 定位项目根目录（脚本所在目录的上一级，即 src/ 的父目录）
FLOW_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${FLOW_ROOT}"

CONFIG_FILE="$1"      # 配置文件路径（.env）
NETLIST="$2"          # MegaCell 门级网表路径
TOP_MODULE="${3:-${MEGACELL_TOP:-}}"   # 顶层模块名（可选）
WORK_DIR="${4:-}"     # 工作目录（可选，默认自动生成）

# 检查配置文件是否存在
if [[ ! -f "${CONFIG_FILE}" ]]; then
    echo "错误: 配置文件不存在: ${CONFIG_FILE}" >&2
    exit 1
fi

#-------------------------------------------------------------------------------
# 第二阶段: 加载配置文件并设置默认值
#-------------------------------------------------------------------------------
# shellcheck source=/dev/null
source "${CONFIG_FILE}"

# 所有可配置变量及其默认值
TECH_NAME="${TECH_NAME:-generic}"
CORNER_NAME="${CORNER_NAME:-default}"
STDCELL_VERILOG_GLOB="${STDCELL_VERILOG_GLOB:-*.v}"
STDCELL_LIB_GLOB="${STDCELL_LIB_GLOB:-*.lib}"
SIMULATOR="${SIMULATOR:-iverilog}"
IVERILOG_BIN="${IVERILOG_BIN:-iverilog}"
VVP_BIN="${VVP_BIN:-vvp}"
VCS_BIN="${VCS_BIN:-vcs}"
MAX_VECTORS="${MAX_VECTORS:-1000000}"
SIM_DELAY="${SIM_DELAY:-1}"

# 自动生成工作目录（如果未显式指定）
if [[ -z "${WORK_DIR}" ]]; then
    CELL_NAME="${TOP_MODULE:-$(basename "${NETLIST}" .v)}"
    WORK_DIR="demo/build/${TECH_NAME}_${CORNER_NAME}/${CELL_NAME}"
fi

#-------------------------------------------------------------------------------
# 第三阶段: 组装 Python 命令行参数
#-------------------------------------------------------------------------------
# 基础参数
args=(
    "${FLOW_ROOT}/src/megacell_flow.py"
    "${NETLIST}"
    "--work-dir" "${WORK_DIR}"
    "--simulator" "${SIMULATOR}"
    "--max-vectors" "${MAX_VECTORS}"
    "--delay" "${SIM_DELAY}"
)

# 顶层模块
if [[ -n "${TOP_MODULE}" ]]; then
    args+=("--top" "${TOP_MODULE}")
fi

# 标准单元 Verilog 模型（目录 + glob）
if [[ -n "${STDCELL_VERILOG_DIR:-}" ]]; then
    args+=("--stdcell-verilog-dir" "${STDCELL_VERILOG_DIR}")
    args+=("--stdcell-verilog-glob" "${STDCELL_VERILOG_GLOB}")
fi

# 标准单元 Verilog 模型（显式文件列表）
if [[ -n "${STDCELL_VERILOG_FILES:-}" ]]; then
    for file in ${STDCELL_VERILOG_FILES}; do
        args+=("--stdcell-verilog-file" "${file}")
    done
fi

# 标准单元 Liberty 文件（目录 + glob）
if [[ -n "${STDCELL_LIB_DIR:-}" ]]; then
    args+=("--stdcell-lib-dir" "${STDCELL_LIB_DIR}")
    args+=("--lib-glob" "${STDCELL_LIB_GLOB}")
fi

# 标准单元 Liberty 文件（显式文件列表）
if [[ -n "${STDCELL_LIB_FILES:-}" ]]; then
    for file in ${STDCELL_LIB_FILES}; do
        args+=("--stdcell-lib-file" "${file}")
    done
fi

# 仿真器相关参数（按后端分别处理）
if [[ "${SIMULATOR}" == "iverilog" ]]; then
    args+=("--iverilog-bin" "${IVERILOG_BIN}")
    args+=("--vvp-bin" "${VVP_BIN}")
elif [[ "${SIMULATOR}" == "vcs" ]]; then
    args+=("--vcs-bin" "${VCS_BIN}")
else
    # 自定义仿真器
    if [[ -n "${COMPILE_CMD_TEMPLATE:-}" ]]; then
        args+=("--compile-cmd-template" "${COMPILE_CMD_TEMPLATE}")
    fi
    if [[ -n "${RUN_CMD_TEMPLATE:-}" ]]; then
        args+=("--run-cmd-template" "${RUN_CMD_TEMPLATE}")
    fi
fi

# 预构建查找表（可选）
if [[ -n "${CELL_LIB:-}" ]]; then
    args+=("--cell-lib" "${CELL_LIB}")
fi

#-------------------------------------------------------------------------------
# 第四阶段: 打印运行信息并执行
#-------------------------------------------------------------------------------
echo "== MegaCell 流程 =="
echo "配置文件 : ${CONFIG_FILE}"
echo "网表     : ${NETLIST}"
echo "顶层模块 : ${TOP_MODULE:-自动检测}"
echo "工作目录 : ${WORK_DIR}"
echo "仿真器   : ${SIMULATOR}"
echo ""

python3 "${args[@]}"
