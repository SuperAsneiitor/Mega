#!/usr/bin/env python3
"""生成 Liberty (.lib) 模板。

模板填入 function、timing_sense、area。时序和功耗表留为特征化占位符。

修改格式只需改 `generate_lib_template()` 一个函数。
"""

from __future__ import annotations


def generate_lib_template(
    cell_name: str,
    inputs: list[str],
    outputs: list[str],
    functions: dict[str, str],
    timing_arcs: dict[str, dict[str, str]],
    cell_area: float,
    library_name: str = "megacell_template",
) -> str:
    """生成 Liberty 模板字符串。

    Parameters
    ----------
    cell_name : str
        MegaCell 名称。
    inputs : list[str]
        输入引脚名列表。
    outputs : list[str]
        输出引脚名列表。
    functions : dict[str, str]
        输出引脚名 → Liberty 布尔表达式 (e.g. ``"(A * B) + !C"``)。
    timing_arcs : dict[str, dict[str, str]]
        输出引脚 → {输入引脚 → sense}。
        sense 取值: ``"positive_unate"`` / ``"negative_unate"`` / ``"non_unate"``。
    cell_area : float
        cell 总面积。
    library_name : str
        Liberty 库名（默认 ``"megacell_template"``）。

    Returns
    -------
    str
        完整的 Liberty 模板文本。
    """
    lines = [
        f"library ({library_name}) {{",
        "  delay_model : table_lookup;",
        "",
        f"  cell ({cell_name}) {{",
        f"    area : {cell_area:.6g};",
    ]

    # ---- 输入引脚 ----
    for pin in inputs:
        lines.extend([
            f"    pin ({pin}) {{",
            "      direction : input;",
            "    }",
        ])

    # ---- 输出引脚 ----
    for pin in outputs:
        lines.extend([
            f"    pin ({pin}) {{",
            "      direction : output;",
            f'      function : "{functions[pin]}";',
            '      power_down_function : "(!VDD) + (VSS)";',
        ])

        # 每个有影响的输入 → 输出弧
        for related_pin, sense in timing_arcs.get(pin, {}).items():
            lines.extend([
                "      timing () {",
                f'        related_pin : "{related_pin}";',
                f"        timing_sense : {sense};",
                "        timing_type : combinational;",
                "        /* 时序表占位 — 由特征化工具填充: cell_rise / cell_fall / rise_transition / fall_transition */",
                "      }",
            ])
        lines.append("    }")

    lines.extend(["  }", "}"])
    return "\n".join(lines) + "\n"
