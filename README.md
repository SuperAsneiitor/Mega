# MegaCell K Library Template Flow

This directory contains a small flow for generating a Liberty/K-library
template for combinational MegaCells built from stdCells.

## Project Structure

```
src/                              # Core code (technology-neutral) — hierarchical
  run_megacell_flow.sh            # Entry: Bash script
  run_megacell_flow.csh           # Entry: C-shell script
  megacell_flow.py                # Entry: Python main orchestrator
  parsers/                        # Layer 1 — File → Data structures
    verilog_parser.py             #   Verilog netlist parsing
    liberty_parser.py             #   Liberty file parsing
  engines/                        # Layer 2 — Core computation
    simulator.py                  #   Simulator abstraction (iverilog/vcs/custom)
    logic_minimizer.py            #   Quine-McCluskey + timing_sense
    truth_table.py                #   Truth table parsing & CSV output
    cell_library.py               #   stdCell lookup table cache
  generators/                     # Layer 3 — Data structures → Output files
    testbench_generator.py        #   Verilog testbench generation (standalone CLI)
    liberty_writer.py             #   Liberty template generation
demo/                             # Example / demo data
  cell_lib/                   # Pre-built lookup table cache (JSON)
  config/                     # Per-process/corner .env configs
  input/                      # MegaCell netlists, stdCell .v + .lib (ASAP7 PDK)
  build/                      # Generated outputs per cell
```

## Inputs

- MegaCell gate-level Verilog netlist, for example `demo/input/megacell_simple.v`
- stdCell Verilog simulation models
- stdCell Liberty files for area and function lookup
- A shell config file, for example `demo/config/asap7_rvt_tt.env`

## Quick Start

### 1. Build stdCell lookup table (one-time)

```bash
python3 src/megacell_flow.py --build-cell-lib \
  --stdcell-lib-dir demo/input/asap7sc7p5t/LIB/NLDM_d \
  --lib-glob '*RVT_TT*.lib' \
  --cell-lib-path demo/cell_lib/asap7_rvt_tt.json
```

### 2. Run the flow

```bash
# Using cell library (fast — skips Liberty parsing):
python3 src/megacell_flow.py demo/input/megacell_simple.v --top MegaCell_simple \
  --cell-lib demo/cell_lib/asap7_rvt_tt.json \
  --stdcell-verilog-dir demo/input/asap7sc7p5t/Verilog \
  --stdcell-verilog-glob '*RVT_TT*.v' \
  --work-dir demo/build/MegaCell_simple

# Or via shell wrapper:
./src/run_megacell_flow.sh demo/config/asap7_rvt_tt.env demo/input/megacell_simple.v MegaCell_simple
```

Generated files:

- `demo/build/<path>/tb_<cell>.v`: exhaustive testbench
- `demo/build/<path>/<cell>.sim.log`: raw simulation output
- `demo/build/<path>/<cell>.truth.csv`: parsed truth table
- `demo/build/<path>/<cell>.template.lib`: Liberty template

## Simulator Selection

| Value | Simulator | Notes |
|-------|-----------|-------|
| `iverilog` | Icarus Verilog | Default. Requires `iverilog` + `vvp`. |
| `vcs` | Synopsys VCS | Requires `vcs`. Set `VCS_BIN` if needed. |
| `custom` | User-defined | Uses `COMPILE_CMD_TEMPLATE` / `RUN_CMD_TEMPLATE`. |

Example VCS usage:
```bash
SIMULATOR=vcs ./src/run_megacell_flow.sh demo/config/asap7_rvt_tt.env demo/input/megacell_simple.v MegaCell_simple
```

## Config File Variables

Each process/corner/simulator should have its own config file under `demo/config/`.

| Variable | Description |
|----------|-------------|
| `TECH_NAME` | Process name used in the default output path |
| `CORNER_NAME` | Corner name used in the default output path |
| `STDCELL_VERILOG_DIR` | Directory containing stdCell simulation models |
| `STDCELL_VERILOG_GLOB` | Glob used to scan stdCell simulation models |
| `STDCELL_VERILOG_FILES` | Optional explicit whitespace-separated Verilog files |
| `STDCELL_LIB_DIR` | Directory containing stdCell Liberty files |
| `STDCELL_LIB_GLOB` | Glob used to scan Liberty files |
| `STDCELL_LIB_FILES` | Optional explicit whitespace-separated Liberty files |
| `SIMULATOR` | `iverilog`, `vcs`, or `custom` |
| `IVERILOG_BIN` / `VVP_BIN` | Executables for `SIMULATOR=iverilog` |
| `VCS_BIN` | Executable for `SIMULATOR=vcs` |
| `CELL_LIB` | Path to pre-built cell library JSON |
| `COMPILE_CMD_TEMPLATE` / `RUN_CMD_TEMPLATE` | Commands for `SIMULATOR=custom` |
| `MAX_VECTORS` | Exhaustive vector safety limit (default 1M) |
| `SIM_DELAY` | Testbench settle delay (default 1) |

Custom simulator command templates use these placeholders:
`{sources}`, `{stdcell_sources}`, `{netlist}`, `{tb}`, `{simv}`, `{work_dir}`.

## What The Flow Fills

For each scalar output pin:
- `function`
- `power_down_function`
- `timing_sense` for input-output arcs that affect the output

For the cell:
- `area`, by summing instantiated stdCell areas from Liberty

Timing and power table values are left as characterization placeholders.

## Limits

- Only combinational MegaCells are supported.
- Input/output buses are rejected.
- Exhaustive simulation is capped at 20 input bits by default.
- The generated `function` uses Liberty Boolean syntax:
  `!` for NOT, `*` for AND, `+` for OR.
