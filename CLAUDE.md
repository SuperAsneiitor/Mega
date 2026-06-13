# CLAUDE.md

本文件为 Claude Code 在此仓库中工作时提供指导。

## 概述

为组合逻辑 MegaCell 自动生成 Liberty (.lib) 模板。两条路径：

| 路径 | 原理 | 依赖 |
|------|------|------|
| **A. 仿真** | 穷举门级仿真 → 真值表 → Quine-McCluskey 最小化 | iverilog |
| **B. 推导** | 网表 + stdCell 查找表 → 符号代入 → 求值 → 最小化 | 无需仿真器 |

## 常用命令

```bash
# 前序准备: 构建 stdCell 查找表（仅需一次）
./run_build_lib.sh demo/input/asap7sc7p5t/LIB/NLDM_d demo/cell_lib/asap7_rvt_tt.json '*RVT_TT*.lib'

# 路径 A: 仿真
./run_sim.sh demo/input/megacell_simple.v demo/input/asap7sc7p5t/Verilog MegaCell_simple build/sim_test

# 路径 B: 推导
./run_derive.sh demo/input/megacell_simple.v demo/cell_lib/asap7_rvt_tt.json demo/cell_lib/stdcell_funcs.json MegaCell_simple build/derive_test

# 或直接调 Python:
python3 src/megacell_flow.py sim <netlist> --stdcell-dir <dir>
python3 src/megacell_flow.py derive <netlist> --cell-lib <json>
python3 src/megacell_flow.py build-lib <lib_dir> -o <output.json>
```

## 代码层次

```
run_sim.sh               # 仿真入口（项目根）
run_derive.sh            # 推导入口（项目根）
run_build_lib.sh         # 构建查找表入口（项目根）
src/
├── megacell_flow.py     # Python 主入口 (sim / derive / build-lib 子命令)
├── parsers/             # 解析层：Verilog 网表、Liberty 文件
├── engines/             # 引擎层：仿真器、推导器、最小化、查找表
└── generators/          # 生成层：测试平台、Liberty 模板
demo/                    # 示例数据
```

依赖方向: `parsers → engines → generators → megacell_flow`

## 硬限制

- 仅组合逻辑，标量 I/O，≤20 输入位
- 生成的 Liberty 时序/功耗表为占位符
