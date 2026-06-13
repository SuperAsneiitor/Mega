# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此仓库中工作时提供指导。

## 概述

这是一个 EDA 流程，用于为由标准单元构建的组合逻辑 MegaCell 生成 Liberty (.lib) 模板。它运行穷举门级仿真，提取真值表，通过 Quine-McCluskey 算法最小化布尔函数，并生成包含函数、timing_sense 弧和面积的 Liberty 模板。

支持仿真器：Icarus Verilog、Synopsys VCS、用户自定义命令模板。

## 常用命令

```bash
# 构建 stdCell 查找表（一次性，后续可复用）：
python3 src/megacell_flow.py --build-cell-lib \
  --stdcell-lib-dir demo/input/asap7sc7p5t/LIB/NLDM_d \
  --lib-glob '*RVT_TT*.lib' \
  --cell-lib-path demo/cell_lib/asap7_rvt_tt.json

# 用查找表运行流程（快路径，跳过 Liberty 解析）：
python3 src/megacell_flow.py demo/input/megacell_simple.v --top MegaCell_simple \
  --cell-lib demo/cell_lib/asap7_rvt_tt.json \
  --stdcell-verilog-dir demo/input/asap7sc7p5t/Verilog \
  --stdcell-verilog-glob '*RVT_TT*.v' \
  --work-dir demo/build/MegaCell_simple

# 直接解析 Liberty 运行流程（慢路径，无需预构建查找表）：
python3 src/megacell_flow.py demo/input/megacell_simple.v --top MegaCell_simple \
  --stdcell-verilog-dir demo/input/asap7sc7p5t/Verilog \
  --stdcell-verilog-glob '*RVT_TT*.v' \
  --stdcell-lib-dir demo/input/asap7sc7p5t/LIB/NLDM_d \
  --lib-glob '*RVT_TT*.lib' \
  --work-dir demo/build/MegaCell_simple

# Bash 入口（加载配置文件运行）：
./src/run_megacell_flow.sh demo/config/asap7_rvt_tt.env demo/input/megacell_simple.v MegaCell_simple

# C Shell 入口（前序准备：构建查找表）：
./src/run_build_cell_lib.csh \
  demo/input/asap7sc7p5t/LIB/NLDM_d \
  '*RVT_TT*.lib' \
  demo/cell_lib/asap7_rvt_tt.json

# C Shell 入口（主流：网表 + 查找表 → 仿真 → Liberty 模板）：
./src/run_megacell_flow.csh \
  demo/input/megacell_simple.v \
  demo/cell_lib/asap7_rvt_tt.json \
  demo/input/asap7sc7p5t/Verilog

# C Shell + VCS：
setenv SIMULATOR vcs
./src/run_megacell_flow.csh \
  demo/input/megacell_simple.v \
  demo/cell_lib/asap7_rvt_tt.json \
  demo/input/asap7sc7p5t/Verilog \
  '*RVT_TT*.v' \
  MegaCell_simple \
  demo/build/vcs_test

# 使用 VCS 仿真器（Bash）：
SIMULATOR=vcs ./src/run_megacell_flow.sh demo/config/asap7_rvt_tt.env demo/input/megacell_simple.v MegaCell_simple

# 仅生成测试平台（不运行仿真）：
PYTHONPATH=src python3 src/generators/testbench_generator.py \
  demo/input/megacell_simple.v --top MegaCell_simple -o tb_MegaCell_simple.v
```

## 架构

### 目录层次

入口文件在最上层，支撑模块按功能分为三层：

```
src/
├── run_megacell_flow.sh          # 入口：Bash 脚本（加载 .env 配置）
├── run_build_cell_lib.csh        # 入口：Csh 脚本 — 前序准备（构建查找表）
├── run_megacell_flow.csh         # 入口：Csh 脚本 — 主流（网表 + 查找表 → 仿真 → .lib）
├── megacell_flow.py              # 入口：Python 主流程编排
│
├── parsers/                      # 解析层 — 文件 → 数据结构
│   ├── verilog_parser.py         # Verilog 网表解析
│   └── liberty_parser.py         # Liberty 文件解析
│
├── engines/                      # 引擎层 — 核心计算逻辑
│   ├── simulator.py              # 仿真引擎（iverilog/vcs/custom）
│   ├── logic_minimizer.py        # Quine-McCluskey 最小化 + timing_sense
│   ├── truth_table.py            # 真值表解析与 CSV 输出
│   └── cell_library.py           # stdCell 查找表缓存
│
└── generators/                   # 生成层 — 数据结构 → 输出文件
    ├── testbench_generator.py    # Verilog 测试平台生成（含独立 CLI）
    └── liberty_writer.py         # Liberty 模板生成
```

### 层次依赖关系（无环 DAG）

```
parsers/          ← 无内部依赖
  ↓
engines/          ← 依赖 parsers/
  ↓
generators/       ← 依赖 parsers/ + engines/
  ↓
megacell_flow.py  ← 入口层，依赖全部三层
```

### 核心数据流

```
netlist.v + stdCell .v/.lib + config.env
    → 解析端口和实例 (parsers/verilog_parser)
    → [可选] 加载查找表获取面积 (engines/cell_library)
    → 生成穷举测试平台 (generators/testbench_generator)
    → 编译并仿真 (engines/simulator: iverilog / vcs / custom)
    → 解析真值表 (engines/truth_table)
    → Quine-McCluskey 最小化 (engines/logic_minimizer)
    → 生成 Liberty 模板 (generators/liberty_writer)
```

### 查找表（Cell Library）

预提取机制避免每次重复解析 Liberty 文件：
- `--build-cell-lib`：从 Liberty 构建查找表并保存为 JSON
- `--cell-lib <path>`：从 JSON 加载查找表，跳过 Liberty 解析

### 仿真器选择

| SIMULATOR | 说明 |
|-----------|------|
| `iverilog` | Icarus Verilog（默认），需安装 iverilog + vvp |
| `vcs` | Synopsys VCS，需 `VCS_BIN` 环境变量 |
| `custom` | 用户自定义，通过 `COMPILE_CMD_TEMPLATE` / `RUN_CMD_TEMPLATE` 指定 |

### 代码中的硬限制

- 仅支持组合逻辑 MegaCell，不支持时序元件。
- 不支持总线端口（仅标量 I/O），在 `scalar_ports()` 中检查。
- 穷举仿真拒绝超过 20 个输入位。
- `MAX_VECTORS`（默认 100 万）是辅助安全上限。
- 生成的 Liberty 中的时序和功耗表为占位符。
