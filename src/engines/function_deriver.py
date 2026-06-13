#!/usr/bin/env python3
"""组合推导引擎 — 由 stdCell 的 function 逐级代入，合成 MegaCell 的整体布尔函数。

算法:
  1. 解析网表中所有实例的引脚连接关系
  2. 构建信号依赖图（DAG），拓扑排序
  3. 从原始输入开始，逐级将 stdCell 的函数代入，推导每个内部线网表达式
  4. 对推导出的输出表达式，在全部输入组合上求值得到真值表
  5. 调用 Quine-McCluskey 最小化，得到最简 SOP 形式

与仿真路径的区别: 此方法不需要运行门级仿真器，纯符号推导。
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from parsers.verilog_parser import ModuleInfo, Port, parse_instances, parse_modules, select_module, strip_comments
from engines.truth_table import TruthTable


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class InstanceConn:
    """一个实例的完整连接信息."""
    inst_name: str                        # 实例名, e.g. "u_and_ab"
    cell_name: str                        # 单元名, e.g. "AND2x2_ASAP7_75t_R"
    connections: dict[str, str] = field(default_factory=dict)  # cell_pin → net_name


# ---------------------------------------------------------------------------
# 实例连接解析
# ---------------------------------------------------------------------------

def parse_instance_connections(netlist_text: str, top_module: str) -> list[InstanceConn]:
    """解析顶层模块中所有实例的引脚连接.

    处理格式::

        CELL_NAME INST_NAME (
            .PIN1(NET1),
            .PIN2(NET2)
        );
    """
    modules = parse_modules(netlist_text)
    module = select_module(modules, top_module)
    text = strip_comments(netlist_text)

    # 定位顶层模块体
    body_match = re.search(
        rf"\bmodule\s+{re.escape(module.name)}\s*\(.*?\)\s*;(.*?)\bendmodule\b",
        text, flags=re.S,
    )
    if not body_match:
        raise ValueError(f"找不到顶层模块 {module.name} 的模块体")
    body = body_match.group(1)

    # 匹配实例:  CELL_NAME INST_NAME ( ... );
    instance_re = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_$]*)\s+"     # cell_name
        r"(?:#\s*\(.*?\)\s*)?"                  # 可选参数
        r"([A-Za-z_][A-Za-z0-9_$]*)\s*"        # inst_name
        r"\((.*?)\)\s*;",                       # 引脚连接
        flags=re.S,
    )

    skip = {"input", "output", "wire", "reg", "logic", "assign", "specify", "module", "endmodule"}
    instances: list[InstanceConn] = []

    for match in instance_re.finditer(body):
        cell_name = match.group(1)
        inst_name = match.group(2)
        pin_text = match.group(3)

        if cell_name in skip:
            continue

        inst = InstanceConn(inst_name=inst_name, cell_name=cell_name)

        # 解析 .PIN(NET) 对
        pin_re = re.compile(r"\.([A-Za-z_][A-Za-z0-9_$]*)\s*\(\s*([A-Za-z_][A-Za-z0-9_$]*)\s*\)")
        for pm in pin_re.finditer(pin_text):
            pin = pm.group(1)
            net = pm.group(2)
            inst.connections[pin] = net

        if inst.connections:
            instances.append(inst)

    return instances


# ---------------------------------------------------------------------------
# Liberty 表达式求值器（递归下降）
# ---------------------------------------------------------------------------

def _tokenize(expr: str) -> list[str]:
    """将 Liberty 布尔表达式拆分为 token 列表."""
    tokens: list[str] = []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c in '!*+()':
            tokens.append(c)
            i += 1
        elif c.isspace():
            i += 1
        else:
            # 变量名
            j = i
            while j < len(expr) and (expr[j].isalnum() or expr[j] == '_' or expr[j] == '$'):
                j += 1
            tokens.append(expr[i:j])
            i = j
    return tokens


def _parse_or(tokens: list[str], pos: int, values: dict[str, int]) -> tuple[int, int]:
    """解析 OR 表达式: term ('+' term)*"""
    left, pos = _parse_and(tokens, pos, values)
    while pos < len(tokens) and tokens[pos] == '+':
        right, pos = _parse_and(tokens, pos + 1, values)
        left = left | right
    return left, pos


def _parse_and(tokens: list[str], pos: int, values: dict[str, int]) -> tuple[int, int]:
    """解析 AND 表达式: factor ('*' factor)*"""
    left, pos = _parse_factor(tokens, pos, values)
    while pos < len(tokens) and tokens[pos] == '*':
        right, pos = _parse_factor(tokens, pos + 1, values)
        left = left & right
    return left, pos


def _parse_factor(tokens: list[str], pos: int, values: dict[str, int]) -> tuple[int, int]:
    """解析因子: '!' factor | '(' expr ')' | VAR"""
    if pos >= len(tokens):
        raise ValueError("表达式意外结束")
    token = tokens[pos]
    if token == '!':
        result, pos = _parse_factor(tokens, pos + 1, values)
        return 1 - result, pos  # NOT
    elif token == '(':
        result, pos = _parse_or(tokens, pos + 1, values)
        if pos >= len(tokens) or tokens[pos] != ')':
            raise ValueError(f"期望 ')' 但得到 {tokens[pos] if pos < len(tokens) else 'EOF'}")
        return result, pos + 1
    else:
        # 变量名
        if token not in values:
            raise ValueError(f"变量 {token} 未在输入值中定义")
        return values[token], pos + 1


def evaluate_expression(expr: str, values: dict[str, int]) -> int:
    """对给定的输入值 (0/1) 求布尔表达式的值.

    Args:
        expr: Liberty 格式的布尔表达式 (e.g. ``"(!A * B) + (A * !B)"``)
        values: 变量名 → 0 或 1 的映射

    Returns:
        0 或 1
    """
    tokens = _tokenize(expr)
    if not tokens:
        return 0
    result, pos = _parse_or(tokens, 0, values)
    return result


# ---------------------------------------------------------------------------
# 符号代入
# ---------------------------------------------------------------------------

def _substitute_expr(expr: str, mapping: dict[str, str]) -> str:
    """将表达式中的变量名替换为对应的子表达式.

    使用占位符两步替换，避免已代入表达式内的变量名被二次替换。
    替换时自动加括号保护优先级.
    """
    result = expr
    # 第一步: 变量 → 唯一占位符
    placeholders: dict[str, str] = {}
    for i, var in enumerate(sorted(mapping, key=len, reverse=True)):
        ph = f'__PH{i}__'
        placeholders[ph] = f'({mapping[var]})'
        result = re.sub(rf'\b{re.escape(var)}\b', ph, result)
    # 第二步: 占位符 → 实际表达式
    for ph, replacement in placeholders.items():
        result = result.replace(ph, replacement)
    return result


# ---------------------------------------------------------------------------
# 主推导算法
# ---------------------------------------------------------------------------

def derive_functions(
    netlist_text: str,
    top_module: str,
    inputs: list[Port],
    outputs: list[Port],
    cell_lib: dict,
) -> dict[str, str]:
    """由 stdCell 函数组合推导 MegaCell 各输出的布尔函数.

    Args:
        netlist_text: MegaCell 门级网表文本
        top_module: 顶层模块名
        inputs: 原始输入端口列表
        outputs: 原始输出端口列表
        cell_lib: stdCell 查找表 (dict[cell_name, CellInfo])

    Returns:
        dict[output_name, minimized_liberty_expression]
    """
    # ---- 1. 解析实例连接 ----
    instances = parse_instance_connections(netlist_text, top_module)

    # ---- 2. 构建数据流图 ----
    # net_exprs: 每个线网的当前表达式（字符串）
    net_exprs: dict[str, str] = {}
    for port in inputs:
        net_exprs[port.name] = port.name  # 原始输入 → 自身

    # 每个实例的: 输入引脚→线网, 输出引脚→线网
    inst_inputs: dict[str, dict[str, str]] = {}   # inst_name → {cell_pin: net}
    inst_outputs: dict[str, dict[str, str]] = {}  # inst_name → {cell_pin: net}

    for inst in instances:
        cell = cell_lib.get(inst.cell_name)
        if cell is None:
            raise ValueError(
                f"查找表中找不到单元 '{inst.cell_name}'（实例 {inst.inst_name}）。"
                f" 请先用 --build-cell-lib 构建包含此单元的查找表。"
            )

        inp = {}
        outp = {}
        for pin, net in inst.connections.items():
            direction = cell.pins.get(pin, "unknown")
            if direction == "input":
                inp[pin] = net
            elif direction == "output":
                outp[pin] = net
            else:
                # 方向未知时，如果在 function 的 key 中则为 output，否则为 input
                if pin in cell.functions:
                    outp[pin] = net
                else:
                    inp[pin] = net

        inst_inputs[inst.inst_name] = inp
        inst_outputs[inst.inst_name] = outp

    # ---- 3. 迭代推导（数据流传播）----
    # 重复遍历实例列表，直到所有能推导的都推导完毕
    remaining = list(instances)
    progress = True

    while remaining and progress:
        progress = False
        next_remaining: list[InstanceConn] = []

        for inst in remaining:
            inp = inst_inputs[inst.inst_name]
            outp = inst_outputs[inst.inst_name]
            cell = cell_lib[inst.cell_name]

            # 检查所有输入线网是否已有表达式
            ready = all(net in net_exprs for net in inp.values())
            if not ready:
                next_remaining.append(inst)
                continue

            progress = True

            # 构建代入映射: cell_pin → net_expression
            mapping = {pin: net_exprs[net] for pin, net in inp.items()}

            # 对每个输出引脚，代入得到线网表达式
            for pin, net in outp.items():
                if net in net_exprs:
                    continue  # 已推导过（可能被其他实例驱动）

                func = cell.functions.get(pin)
                if func is None:
                    raise ValueError(
                        f"单元 '{inst.cell_name}' 的输出引脚 '{pin}' "
                        f"在查找表中没有 function 定义"
                    )

                derived = _substitute_expr(func, mapping)
                net_exprs[net] = derived

        remaining = next_remaining

    if remaining:
        unresolved = [inst.inst_name for inst in remaining]
        raise ValueError(
            f"存在循环依赖或缺失驱动: {', '.join(unresolved)}"
        )

    # ---- 4. 对推导出的表达式求值 → 真值表 → 最小化 ----
    from engines.logic_minimizer import minimize_minterms, cubes_to_liberty

    input_names = [port.name for port in inputs]
    n_inputs = len(input_names)
    functions: dict[str, str] = {}

    for output in outputs:
        out_net = output.name
        if out_net not in net_exprs:
            raise ValueError(f"输出端口 '{out_net}' 未被任何实例驱动")

        expr = net_exprs[out_net]
        minterms: list[int] = []

        for idx in range(1 << n_inputs):
            # 构造输入值: 将 idx 的各位分配给各输入
            values = {}
            for i, name in enumerate(input_names):
                values[name] = (idx >> (n_inputs - 1 - i)) & 1
            if evaluate_expression(expr, values):
                minterms.append(idx)

        cubes = minimize_minterms(minterms, n_inputs)
        functions[out_net] = cubes_to_liberty(cubes, input_names)

    return functions


# ---------------------------------------------------------------------------
# 便捷入口: 直接返回 TruthTable（便于与仿真结果对比）
# ---------------------------------------------------------------------------

def derive_truth_table(
    netlist_text: str,
    top_module: str,
    inputs: list[Port],
    outputs: list[Port],
    cell_lib: dict,
) -> TruthTable:
    """推导并返回完整的真值表（可用于与仿真结果 diff 对比）."""
    input_names = [p.name for p in inputs]
    output_names = [p.name for p in outputs]
    n_inputs = len(input_names)

    # 推导表达式
    functions = derive_functions(netlist_text, top_module, inputs, outputs, cell_lib)

    # 在所有输入组合上求值
    rows: list[tuple[dict[str, str], dict[str, str]]] = []
    for idx in range(1 << n_inputs):
        values = {}
        for i, name in enumerate(input_names):
            values[name] = (idx >> (n_inputs - 1 - i)) & 1

        in_dict = {name: str(values[name]) for name in input_names}
        out_dict = {}
        for out_name, expr in functions.items():
            out_dict[out_name] = str(evaluate_expression(expr, values))

        rows.append((in_dict, out_dict))

    return TruthTable(inputs=list(inputs), outputs=list(outputs), rows=rows)
