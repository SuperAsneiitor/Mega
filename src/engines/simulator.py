#!/usr/bin/env python3
"""Simulation backends for gate-level MegaCell verification.

Supported backends:

- ``iverilog`` — Icarus Verilog (default)
- ``vcs`` — Synopsys VCS
- ``custom`` — user-supplied command templates
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

from parsers.verilog_parser import ModuleInfo
from generators.testbench_generator import generate_testbench


# ---------------------------------------------------------------------------
# stdCell Verilog resolution
# ---------------------------------------------------------------------------


def verilog_files_for_cells(
    verilog_dir: Path, verilog_glob: str, cell_names: set[str]
) -> list[Path]:
    """Scan *verilog_dir* with *verilog_glob* and return paths that contain
    module definitions for any of *cell_names*.

    Stops early once all requested cells are found.
    """
    files: list[Path] = []
    missing = set(cell_names)
    for path in sorted(verilog_dir.glob(verilog_glob)):
        text = path.read_text()
        found = {cell for cell in missing if re.search(rf"\bmodule\s+{re.escape(cell)}\b", text)}
        if found:
            files.append(path)
            missing -= found
        if not missing:
            break
    if missing:
        raise ValueError("Cannot find Verilog definitions for cells: " + ", ".join(sorted(missing)))
    return files


def resolve_stdcell_verilog(
    explicit_files: list[Path],
    verilog_dir: Path | None,
    verilog_glob: str,
    cell_names: set[str],
) -> list[Path]:
    """Resolve stdCell Verilog model paths.

    Uses explicit files if provided, otherwise scans *verilog_dir*.
    """
    if explicit_files:
        return explicit_files
    if verilog_dir is None:
        raise ValueError("Pass --stdcell-verilog-dir or at least one --stdcell-verilog-file.")
    return verilog_files_for_cells(verilog_dir, verilog_glob, cell_names)


# ---------------------------------------------------------------------------
# Command-line helpers
# ---------------------------------------------------------------------------


def _shlex_join(args: list[str]) -> str:
    """Join shell arguments safely (compatible with Python <3.8)."""
    return " ".join(shlex.quote(a) for a in args)


@dataclass
class _TemplateValues:
    """Pre-computed placeholder values for command templates."""

    stdcell_sources: str
    sources: str
    netlist: str
    tb: str
    simv: str
    work_dir: str


def _make_template_values(
    netlist: Path,
    tb_path: Path,
    sim_path: Path,
    work_dir: Path,
    stdcell_verilog: list[Path],
) -> _TemplateValues:
    stdcell_sources = _shlex_join([str(p) for p in stdcell_verilog])
    sources = " ".join(
        [stdcell_sources, shlex.quote(str(netlist)), shlex.quote(str(tb_path))]
    ).strip()
    return _TemplateValues(
        stdcell_sources=stdcell_sources,
        sources=sources,
        netlist=shlex.quote(str(netlist)),
        tb=shlex.quote(str(tb_path)),
        simv=shlex.quote(str(sim_path)),
        work_dir=shlex.quote(str(work_dir)),
    )


def run_shell_template(template: str, values: _TemplateValues) -> subprocess.CompletedProcess[str]:
    """Expand a command template and execute it via shell."""
    command = template.format(
        stdcell_sources=values.stdcell_sources,
        sources=values.sources,
        netlist=values.netlist,
        tb=values.tb,
        simv=values.simv,
        work_dir=values.work_dir,
    )
    return subprocess.run(command, check=True, text=True, capture_output=True, shell=True)


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _run_iverilog(
    netlist: Path,
    tb_path: Path,
    sim_path: Path,
    work_dir: Path,
    stdcell_verilog: list[Path],
    iverilog_bin: str,
    vvp_bin: str,
) -> str:
    compile_cmd = [
        iverilog_bin,
        *[str(p) for p in stdcell_verilog],
        str(netlist),
        str(tb_path),
        "-o",
        str(sim_path),
    ]
    subprocess.run(compile_cmd, check=True, text=True, capture_output=True)
    result = subprocess.run([vvp_bin, str(sim_path)], check=True, text=True, capture_output=True)
    return result.stdout


def _run_vcs(
    netlist: Path,
    tb_path: Path,
    sim_path: Path,
    work_dir: Path,
    stdcell_verilog: list[Path],
    vcs_bin: str,
) -> str:
    sources = [str(p) for p in stdcell_verilog] + [str(netlist), str(tb_path)]
    compile_cmd = [vcs_bin, "-full64", "-sverilog", *sources, "-o", str(sim_path)]
    subprocess.run(compile_cmd, check=True, text=True, capture_output=True)
    result = subprocess.run([str(sim_path)], check=True, text=True, capture_output=True)
    return result.stdout


def _run_custom(
    netlist: Path,
    tb_path: Path,
    sim_path: Path,
    work_dir: Path,
    stdcell_verilog: list[Path],
    compile_cmd_template: str | None,
    run_cmd_template: str,
) -> str:
    values = _make_template_values(netlist, tb_path, sim_path, work_dir, stdcell_verilog)
    if compile_cmd_template:
        run_shell_template(compile_cmd_template, values)
    result = run_shell_template(run_cmd_template, values)
    return result.stdout


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_simulation(
    module: ModuleInfo,
    netlist: Path,
    stdcell_verilog: list[Path],
    work_dir: Path,
    *,
    delay: int = 1,
    max_vectors: int = 1_000_000,
    simulator: str = "iverilog",
    iverilog_bin: str = "iverilog",
    vvp_bin: str = "vvp",
    vcs_bin: str = "vcs",
    compile_cmd_template: str | None = None,
    run_cmd_template: str | None = None,
) -> str:
    """Compile and run gate-level simulation for *module*.

    Returns
    -------
    str
        The simulation stdout (used to parse the truth table).
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    tb_path = work_dir / f"tb_{module.name}.v"
    sim_path = work_dir / f"{module.name}.simv"
    tb_path.write_text(generate_testbench(module, delay=delay, max_vectors=max_vectors))

    if simulator == "iverilog":
        return _run_iverilog(netlist, tb_path, sim_path, work_dir, stdcell_verilog,
                             iverilog_bin, vvp_bin)

    if simulator == "vcs":
        return _run_vcs(netlist, tb_path, sim_path, work_dir, stdcell_verilog, vcs_bin)

    if simulator == "custom":
        if not run_cmd_template:
            raise ValueError("--run-cmd-template is required when --simulator custom is used.")
        return _run_custom(netlist, tb_path, sim_path, work_dir, stdcell_verilog,
                           compile_cmd_template, run_cmd_template)

    raise ValueError(f"Unsupported simulator '{simulator}'. Use 'iverilog', 'vcs', or 'custom'.")
