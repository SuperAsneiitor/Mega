# MegaCell Flow

为组合逻辑 MegaCell 自动生成 Liberty (.lib) 模板。

## 两条路径

### A. 仿真路径

```
网表 → testbench → iverilog 仿真 → 真值表 → Quine-McCluskey 最小化 → .lib
```

```bash
./run_sim.sh <netlist> <stdcell_verilog_dir> [top] [work_dir]

# 示例
./run_sim.sh demo/input/megacell_simple.v demo/input/asap7sc7p5t/Verilog MegaCell_simple
```

### B. 推导路径（无需仿真器）

```
前序: Liberty 文件 → stdCell 查找表 (JSON)
推导: 网表 + 查找表 → 符号代入 → 求值 → Quine-McCluskey 最小化 → .lib
```

```bash
# 前序准备（仅需一次）
./run_build_lib.sh <lib_dir> <output.json> [glob]

# 推导
./run_derive.sh <netlist> <cell_lib.json> [func_override.json] [top] [work_dir]

# 完整示例
./run_build_lib.sh demo/input/asap7sc7p5t/LIB/NLDM_d demo/cell_lib/asap7_rvt_tt.json '*RVT_TT*.lib'
./run_derive.sh demo/input/megacell_simple.v demo/cell_lib/asap7_rvt_tt.json demo/cell_lib/stdcell_funcs.json MegaCell_simple
```

## 项目结构

```
run_sim.sh                # 仿真入口
run_derive.sh             # 推导入口
run_build_lib.sh          # 构建查找表入口
src/
├── megacell_flow.py      # Python 主入口 (sim/derive/build-lib 子命令)
├── parsers/              # 解析层
│   ├── verilog_parser.py
│   └── liberty_parser.py
├── engines/              # 引擎层
│   ├── simulator.py      #   仿真引擎 (iverilog)
│   ├── function_deriver.py # 组合推导引擎
│   ├── logic_minimizer.py  # Quine-McCluskey
│   ├── truth_table.py      # 真值表
│   └── cell_library.py     # 查找表缓存
└── generators/           # 生成层
    ├── testbench_generator.py
    └── liberty_writer.py
demo/
├── cell_lib/             # 预构建查找表
├── config/               # 工艺配置
└── input/                # 示例网表
```

## 生成产物

- `tb_<cell>.v` — 穷举测试平台
- `<cell>.truth.csv` — 真值表
- `<cell>.template.lib` — Liberty 模板
- `<cell>.sim.log` — 仿真日志（仅仿真路径）

## 限制

- 仅组合逻辑 MegaCell
- 仅标量 I/O（不支持总线端口）
- 穷举仿真上限 20 输入位
- 时序和功耗表为占位符
