# MegaCell Flow

为组合逻辑 MegaCell 自动生成 Liberty (.lib) 模板。

## 两条路径

### A. 仿真路径

```
网表 → testbench → iverilog 仿真 → 真值表 → Quine-McCluskey 最小化 → .lib
```

```bash
./run_sim.sh <netlist> "<stdcell1.v stdcell2.v ...>" [top] [work_dir]

# 示例
./run_sim.sh demo/input/megacell_simple.v \
  "demo/input/asap7sc7p5t/Verilog/asap7sc7p5t_SIMPLE_RVT_TT_201020.v demo/input/asap7sc7p5t/Verilog/asap7sc7p5t_INVBUF_RVT_TT_201020.v" \
  MegaCell_simple
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
│   ├── verilog_parser.py   # Verilog 网表解析（模块/端口/实例）
│   └── liberty_parser.py   # Liberty 文件解析（cell/pin/function）
├── engines/              # 引擎层
│   ├── simulator.py        # 仿真引擎（iverilog / VCS / custom）
│   ├── function_deriver.py # 组合推导引擎（符号代入）
│   ├── logic_minimizer.py  # Quine-McCluskey 两级逻辑最小化
│   ├── truth_table.py      # 真值表表示与解析
│   └── cell_library.py     # stdCell 查找表缓存（JSON）
└── generators/           # 生成层
    ├── testbench_generator.py  # 穷举测试平台生成
    └── liberty_writer.py       # Liberty 模板生成
demo/
├── cell_lib/             # 预构建查找表
├── config/               # 工艺配置
└── input/                # 示例网表
```

依赖方向: `parsers → engines → generators → megacell_flow`

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

---

# 开发手册

## 架构总览

```
                 ┌─────────────────────────┐
                 │     megacell_flow.py     │  主入口，编排流程
                 └───────────┬─────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
   ┌──────────┐      ┌──────────────┐      ┌─────────────┐
   │ parsers/ │      │   engines/   │      │ generators/ │
   │          │ ───► │              │ ───► │             │
   │ .v 解析  │      │ 仿真/推导     │      │ .lib 写入   │
   │ .lib解析 │      │ 最小化       │      │ testbench   │
   └──────────┘      └──────────────┘      └─────────────┘
```

数据流向（仿真路径）:
```
megacell.v + stdcell.v
  → verilog_parser.py (parse_modules, parse_instances)
    → testbench_generator.py (generate_testbench)
      → simulator.py (run_simulation → iverilog)
        → truth_table.py (parse_truth_table)
          → logic_minimizer.py (minimize_minterms, cubes_to_liberty)
            → liberty_writer.py (generate_lib_template)
              → .template.lib + .truth.csv
```

数据流向（推导路径）:
```
megacell.v + cell_lib.json
  → verilog_parser.py (parse_modules)
    → function_deriver.py (derive_functions)
      ├── parse_instance_connections (实例引脚连接)
      ├── 拓扑排序 + 符号代入 (_substitute_expr)
      ├── evaluate_expression (递归下降求值器)
      └── logic_minimizer.py (minimize_minterms)
        → liberty_writer.py (generate_lib_template)
          → .template.lib + .truth.csv
```

---

## 修改仿真工具

仿真链路涉及两个文件：testbench 生成器 (`src/generators/testbench_generator.py`) 和仿真后端 (`src/engines/simulator.py`)。

### 1. 更换仿真器（iverilog → VCS → 自定义）

仿真器选择在 `src/engines/simulator.py:187` 的 `run_simulation()` 函数中，通过 `simulator` 参数控制。

**内置后端**:
| simulator 值 | 后端函数 | 覆盖参数 |
|--------------|---------|---------|
| `"iverilog"` | `_run_iverilog()` | `--iverilog-bin`, `--vvp-bin` |
| `"vcs"`      | `_run_vcs()`      | `--vcs-bin` |
| `"custom"`   | `_run_custom()`   | `--compile-cmd-template`, `--run-cmd-template` |

**添加新仿真器**（以 Xcelium 为例）:

步骤 1：在 `src/engines/simulator.py` 添加后端函数:

```python
def _run_xcelium(
    netlist: Path,
    tb_path: Path,
    sim_path: Path,
    work_dir: Path,
    stdcell_verilog: list[Path],
    xrun_bin: str = "xrun",
) -> str:
    """使用 Cadence Xcelium 运行仿真."""
    cmd = [
        xrun_bin,
        *[str(p) for p in stdcell_verilog],
        str(netlist),
        str(tb_path),
        "-o", str(sim_path),
        "-q",
    ]
    subprocess.run(cmd, check=True, text=True, capture_output=True)
    result = subprocess.run([str(sim_path)], check=True, text=True, capture_output=True)
    return result.stdout
```

步骤 2：在 `run_simulation()` 分发逻辑中添加分支（`src/engines/simulator.py:214` 附近）:

```python
if simulator == "xcelium":
    return _run_xcelium(netlist, tb_path, sim_path, work_dir, stdcell_verilog, xrun_bin)
```

步骤 3：在 `src/megacell_flow.py` 的 `cmd_sim()` 中暴露新参数:

```python
p_sim.add_argument("--xrun-bin", default="xrun", help="Xcelium binary")
```

步骤 4：传递给 `run_simulation()` 调用:

```python
sim_out = run_simulation(
    module=module, netlist=args.netlist, stdcell_verilog=verilog_files,
    work_dir=args.work_dir, simulator="xcelium",
    xrun_bin=args.xrun_bin,
)
```

### 2. 修改测试平台生成逻辑

测试平台由 `src/generators/testbench_generator.py:42` 的 `generate_testbench()` 函数生成。

**关键参数**:
| 参数 | 默认值 | 含义 |
|------|--------|------|
| `delay` | `1` | 每个输入向量后的等待时间（仿真时间单位） |
| `max_vectors` | `1_000_000` | 安全上限（约 2^20） |

**修改方向**:

- **改变激励格式**: 编辑 `display_format()` / `display_args()` 函数（第 27-34 行）。注意 `parse_truth_table()` 依赖 `"%b %b | %b %b"` 的输出格式。
- **添加延时模型**: 在 `generate_testbench()` 中修改 `#{delay}` 行（第 108 行），可改为 `#(delay/2)` + `#(delay/2)` 分两段测量。
- **支持非穷举仿真**: 替换 `for (vector = 0; ...)` 循环（第 106 行）为读取文件或随机向量。

**示例 — 改为随机采样仿真**:

```python
# 在 generate_testbench() 中替换循环体
lines.extend([
    "        repeat (10000) begin",
    f"            {{{input_concat}}} = $random;",
    f"            #{delay};",
    f'            $display("{row_fmt}", {row_display_args});',
    "        end",
])
```

> **重要**: 如果修改了 `$display` 输出格式，必须同步修改 `src/engines/truth_table.py:30` 的 `parse_truth_table()` 函数，使其能正确解析新格式。

### 3. 真值表解析

`src/engines/truth_table.py` 负责从仿真 stdout 解析真值表。

`parse_truth_table()` 第 30 行扫描仿真输出中的 header 行（如 `"A B C | Y Z"`），然后逐行解析为 `{input_name: "0"/"1"}` 的映射。

如果要修改解析逻辑：
- 修改 `expected_header` 的生成方式（第 47 行）
- 修改行解析的分隔符和格式（第 56-62 行）

---

## 修改 Liberty 模板生成

Liberty 模板由 `src/generators/liberty_writer.py` 的 `generate_lib_template()` 函数生成。

### 函数签名

```python
def generate_lib_template(
    cell_name: str,          # MegaCell 名称
    inputs: list[str],       # 输入引脚名列表
    outputs: list[str],      # 输出引脚名列表
    functions: dict[str, str],        # 输出引脚 → Liberty 布尔表达式
    timing_arcs: dict[str, dict[str, str]],  # 输出引脚 → {输入引脚 → sense}
    cell_area: float,        # 总面积
    library_name: str = "megacell_template",
) -> str
```

### 修改模板格式

所有 Liberty 语法字符串都在 `generate_lib_template()` 中硬编码，逐行拼接。修改某一部分只需找到对应的 `lines.extend/append` 调用。

**常用修改点**:

| 需求 | 位置 | 操作 |
|------|------|------|
| 修改库名 | 第 47 行 | 改 `library ({library_name})` |
| 修改 delay_model | 第 48 行 | 改 `delay_model : ...` |
| 修改 area 格式 | 第 51 行 | 改 `{cell_area:.6g}` |
| 添加 pin 属性（如 capacitance） | 第 56-59 行（输入 pin）或第 64-69 行（输出 pin） | 插入 `capacitance : ...;` |
| 修改 function 格式 | 第 67 行 | 引号或括号风格 |
| 添加/删除 timing 弧 | 第 72-80 行 | 修改 `timing ()` 块 |
| 添加时序表模板 | 第 78 行注释处 | 替换占位注释为实际表 |
| 修改 power_down_function | 第 68 行 | 改表达式 |

**示例 1 — 为输入 pin 添加电容**:

```python
# 第 56-60 行附近，改为:
for pin in inputs:
    lines.extend([
        f"    pin ({pin}) {{",
        "      direction : input;",
        '      capacitance : 0.001;',          # 新增
        "    }",
    ])
```

**示例 2 — 填入实际 NLDM 时序表**:

```python
# 第 72-80 行附近，替换占位注释:
lines.extend([
    "      timing () {",
    f'        related_pin : "{related_pin}";',
    f"        timing_sense : {sense};",
    "        timing_type : combinational;",
    '        cell_rise (delay_template_7x7) {',
    '          index_1 ("0.01, 0.02, ...");',
    '          index_2 ("0.01, 0.02, ...");',
    '          values ("0.1, 0.2, ...");',
    '        }',
    '        rise_transition (delay_template_7x7) { ... }',
    '        cell_fall (delay_template_7x7) { ... }',
    '        fall_transition (delay_template_7x7) { ... }',
    "      }",
])
```

**示例 3 — 修改布尔表达式语法风格**（如用 `&` 替代 `*`）:

编辑 `src/engines/logic_minimizer.py:118` 的 `cubes_to_liberty()` 函数:

```python
# 第 139 行，将 "* " 改为 "& "
terms.append("(" + " & ".join(literals) + ")")
```

### 调用链

`generate_lib_template()` 在 `src/megacell_flow.py:72` 的 `_write_outputs()` 中被调用。timing_arcs 由 `src/engines/logic_minimizer.py:148` 的 `timing_sense()` 生成，functions 由 `src/engines/logic_minimizer.py:184` 的 `functions_from_truth_table()` 生成。

---

## 修改最小化引擎

Quine-McCluskey 实现在 `src/engines/logic_minimizer.py`。

### 核心函数

| 函数 | 行号 | 用途 |
|------|------|------|
| `combine_cubes()` | 19 | 合并两个立方体（如 `01-0` + `01-1` → `01--`） |
| `minimize_minterms()` | 44 | 主算法：找质蕴含 + 覆盖选择 |
| `cubes_to_liberty()` | 118 | 立方体集合 → Liberty 表达式 |
| `timing_sense()` | 148 | 检测输入→输出的 unateness |
| `functions_from_truth_table()` | 184 | 真值表 → 最小化表达式集合 |

### 替换最小化算法

如果要换成 Espresso 或其他算法，修改 `minimize_minterms()`（第 44 行）即可，它的签名是:

```python
def minimize_minterms(minterms: list[int], width: int) -> list[str]:
```

输入是 minterm 索引列表和输入位宽，返回立方体字符串列表。只需保持此接口不变，下游代码无需改动。

---

## 修改网表解析

`src/parsers/verilog_parser.py` 处理结构级 Verilog。

### 关键函数

| 函数 | 行号 | 用途 |
|------|------|------|
| `parse_modules()` | 124 | 解析 `module...endmodule`，提取端口声明 |
| `parse_instances()` | 195 | 解析实例化语句 `CELL inst (.pin(net))` |
| `strip_comments()` | 45 | 去除注释 |

### 支持的语法子集

- `module NAME (ports); ... endmodule`
- `input/output wire/net` 端口声明
- `CELL_NAME inst_name (.PIN(NET), ...)` 实例化
- 标量和简单向量端口（如 `[3:0]`）

### 扩展支持

- **参数化模块**: 修改 `parse_instances()` 的正则（第 214 行）已支持 `#(...)` 参数
- **generate 块**: 需大幅扩展，目前不支持
- **总线端口**: 修改 `scalar_ports()` 验证（第 243 行），解除总线限制

---

## 修改推导引擎

`src/engines/function_deriver.py` 实现符号代入推导。

### 算法流程

1. `parse_instance_connections()` — 解析所有实例的 `.PIN(NET)` 连接
2. 构建映射图 `net_exprs` — 线网名 → 符号表达式字符串
3. 迭代推导 — 当实例的输入线网全部就绪时，代入得到输出线网表达式
4. `evaluate_expression()` — 递归下降求值器，在所有输入组合上求值
5. 调用 `minimize_minterms()` → Liberty 表达式

### 修改点

- **表达式求值器**: `_tokenize()` + `_parse_or/and/factor()` 实现递归下降。支持 `!` / `*` / `+` / `()` 语法，与 Liberty 格式一致。要增加运算符（如 `^` XOR），修改 `_parse_or()` 或添加新层级。
- **代入策略**: `_substitute_expr()` 用占位符两步替换，避免变量名冲突。如果要优化表达式膨胀，可以在此函数中插入简化步骤。
- **循环检测**: 第 306 行，如果迭代后仍有未推导实例，抛出异常。可改为更细粒度的诊断。

---

## 测试

```bash
# 1. 推导路径（最常用）
./run_derive.sh demo/input/megacell_simple.v \
    demo/cell_lib/asap7_rvt_tt.json \
    demo/cell_lib/stdcell_funcs.json \
    MegaCell_simple build/test_derive

# 2. 仿真路径（需要 stdCell Verilog 文件）
./run_sim.sh demo/input/megacell_simple.v \
    "demo/input/asap7sc7p5t/Verilog/asap7sc7p5t_SIMPLE_RVT_TT_201020.v demo/input/asap7sc7p5t/Verilog/asap7sc7p5t_INVBUF_RVT_TT_201020.v" \
    MegaCell_simple build/test_sim

# 3. 验证两条路径一致性
diff build/test_derive/MegaCell_simple.truth.csv build/test_sim/MegaCell_simple.truth.csv

# 4. 直接调 Python
python3 src/megacell_flow.py derive demo/input/megacell_simple.v \
    --cell-lib demo/cell_lib/asap7_rvt_tt.json \
    --func-override demo/cell_lib/stdcell_funcs.json \
    --work-dir build/my_test
```

### 测试要点

- 推导和仿真路径的真值表必须完全一致（穷举验证）
- 最小化表达式在所有 2^N 输入组合上求值，必须与真值表一致
- timing_sense 的 unateness 标注必须正确（可对照真值表手动验证关键 pin）

---

## 配置参考

| 文件 | 用途 |
|------|------|
| `demo/cell_lib/asap7_rvt_tt.json` | 预构建的 stdCell 查找表（area + function + pin direction） |
| `demo/cell_lib/stdcell_funcs.json` | 手动覆写 stdCell function（弥补 NLDM Liberty 的 function 字段不准确） |
| `demo/config/asap7_rvt_tt.env` | 工艺 corner 环境变量 |
| `demo/input/megacell_simple.v` | 示例 MegaCell 网表（4 输入 2 输出，6 个 stdCell 实例） |
