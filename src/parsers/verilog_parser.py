#!/usr/bin/env python3
"""Verilog netlist parsing — module ports and instantiated cells.

This module is technology-neutral and handles a subset of structural Verilog:
- Module headers with port declarations
- Instance statements (cell_name inst_name ( .pin(net), ... ))
- Scalar and vector ports with constant widths

It does NOT handle:
- Parameterized modules
- Generate blocks
- Inline gate primitives
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Port:
    """A single module port."""

    name: str
    direction: str  # "input" or "output"
    width_expr: str  # e.g. "[3:0]" or "" for scalar
    width: int  # resolved bit width (>=1)


@dataclass(frozen=True)
class ModuleInfo:
    """Parsed information about one Verilog module."""

    name: str
    port_order: list[str]  # port names in declaration order
    ports: dict[str, Port]  # port name → Port


# ---------------------------------------------------------------------------
# Low-level text helpers
# ---------------------------------------------------------------------------


def strip_comments(text: str) -> str:
    """Remove block (/* */) and line (//) comments from Verilog source."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def split_csv(text: str) -> list[str]:
    """Split comma-separated text, stripping whitespace from each item."""
    return [item.strip() for item in text.split(",") if item.strip()]


def parse_width(width_expr: str) -> int:
    """Resolve a Verilog bus width expression like ``[3:0]`` to an integer width.

    Returns 1 for an empty expression (scalar port).
    """
    if not width_expr:
        return 1

    match = re.fullmatch(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", width_expr)
    if not match:
        raise ValueError(f"Only constant bus widths are supported, got: {width_expr}")

    msb = int(match.group(1))
    lsb = int(match.group(2))
    return abs(msb - lsb) + 1


def clean_decl_name(name: str) -> str:
    """Extract a bare port name from a declaration fragment.

    Handles trailing assignments, bus ranges, and whitespace.
    """
    name = name.strip()
    name = re.sub(r"\s*=.*$", "", name)
    name = re.sub(r"\s*\[.*?\]\s*$", "", name)
    match = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)$", name)
    if not match:
        raise ValueError(f"Cannot parse port name from declaration item: {name}")
    return match.group(1)


# ---------------------------------------------------------------------------
# Port / module parsing
# ---------------------------------------------------------------------------


def parse_declaration(stmt: str) -> list[Port]:
    """Parse a single ``input ...;`` or ``output ...;`` declaration.

    Returns a list of Port objects (one per comma-separated signal).
    """
    stmt = " ".join(stmt.strip().rstrip(";").split())
    match = re.match(r"^(input|output)\b\s*(.*)$", stmt)
    if not match:
        return []

    direction = match.group(1)
    rest = match.group(2)
    # Strip type qualifiers
    rest = re.sub(r"\b(wire|reg|logic|signed|unsigned)\b", "", rest)
    rest = " ".join(rest.split())

    width_match = re.match(r"(\[[^\]]+\])\s*(.*)$", rest)
    if width_match:
        width_expr = width_match.group(1)
        names_text = width_match.group(2)
    else:
        width_expr = ""
        names_text = rest

    width = parse_width(width_expr)
    return [
        Port(clean_decl_name(name), direction, width_expr, width)
        for name in split_csv(names_text)
    ]


def parse_modules(verilog_text: str) -> list[ModuleInfo]:
    """Parse all modules from a Verilog source text.

    Returns a list of ModuleInfo objects, one per ``module ... endmodule`` block.
    """
    text = strip_comments(verilog_text)
    module_re = re.compile(
        r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\s*\((.*?)\)\s*;(.*?)\bendmodule\b",
        re.S,
    )

    modules: list[ModuleInfo] = []
    for match in module_re.finditer(text):
        name = match.group(1)
        header = match.group(2)
        body = match.group(3)
        ports: dict[str, Port] = {}
        port_order: list[str] = []

        # Ports declared in the module header
        for item in split_csv(header):
            decl_ports = parse_declaration(item)
            if decl_ports:
                for port in decl_ports:
                    ports[port.name] = port
                    port_order.append(port.name)
            else:
                port_name = clean_decl_name(item)
                port_order.append(port_name)

        # Ports declared as separate statements in the body
        for stmt in body.split(";"):
            stripped = stmt.strip()
            if not re.match(r"^(input|output)\b", stripped):
                continue
            for port in parse_declaration(stripped + ";"):
                ports[port.name] = port

        modules.append(ModuleInfo(name, port_order, ports))

    return modules


def select_module(modules: list[ModuleInfo], top: str | None) -> ModuleInfo:
    """Select a module by name from a parsed module list.

    If *top* is None and exactly one module exists, returns it.
    Otherwise raises ValueError.
    """
    if not modules:
        raise ValueError("No Verilog module found in the netlist.")

    if top:
        for module in modules:
            if module.name == top:
                return module
        names = ", ".join(module.name for module in modules)
        raise ValueError(f"Top module '{top}' not found. Available modules: {names}")

    if len(modules) == 1:
        return modules[0]

    names = ", ".join(module.name for module in modules)
    raise ValueError(f"Multiple modules found, please pass --top. Available modules: {names}")


# ---------------------------------------------------------------------------
# Instance parsing
# ---------------------------------------------------------------------------


def parse_instances(netlist_text: str, top_module: str) -> list[str]:
    """Return instantiated cell/module names inside the selected top module.

    Filters out keywords (input, output, wire, reg, etc.) so only
    user-defined instance types remain.
    """
    modules = parse_modules(netlist_text)
    module = select_module(modules, top_module)
    text = strip_comments(netlist_text)

    body_match = re.search(
        rf"\bmodule\s+{re.escape(module.name)}\s*\(.*?\)\s*;(.*?)\bendmodule\b",
        text,
        flags=re.S,
    )
    if not body_match:
        raise ValueError(f"Cannot find body for top module {module.name}")

    body = body_match.group(1)
    instance_re = re.compile(
        r"\b([A-Za-z_][A-Za-z0-9_$]*)\s+"
        r"(?:#\s*\(.*?\)\s*)?"
        r"[A-Za-z_][A-Za-z0-9_$]*\s*\(",
        flags=re.S,
    )
    skip = {"input", "output", "wire", "reg", "logic", "assign", "specify"}
    return [
        match.group(1)
        for match in instance_re.finditer(body)
        if match.group(1) not in skip
    ]


# ---------------------------------------------------------------------------
# Port helpers
# ---------------------------------------------------------------------------


def vector_width(ports: list[Port]) -> int:
    """Return the total bit width of a list of ports."""
    return sum(port.width for port in ports)


def ordered_ports(module: ModuleInfo) -> list[Port]:
    """Return the module's ports in declaration order."""
    return [module.ports[name] for name in module.port_order if name in module.ports]


def scalar_ports(ports: list[Port], kind: str) -> list[Port]:
    """Validate that all ports are scalar and return them.

    Raises ValueError if any port has width > 1.
    """
    wide = [port.name for port in ports if port.width != 1]
    if wide:
        raise ValueError(
            f"{kind} bus ports are not supported yet: " + ", ".join(wide)
        )
    return ports
