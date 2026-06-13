#!/usr/bin/env python3
"""Combinational logic minimization using Quine-McCluskey.

Also provides Liberty-format expression generation and timing-sense detection.
"""

from __future__ import annotations

import itertools

from engines.truth_table import TruthTable


# ---------------------------------------------------------------------------
# Quine-McCluskey core
# ---------------------------------------------------------------------------


def combine_cubes(a: str, b: str) -> str | None:
    """Try to combine two cube strings (e.g. ``"01-0"`` + ``"01-1"`` → ``"01--"``).

    Returns the combined cube if they differ in exactly one position, or
    ``None``.
    """
    diff = 0
    chars: list[str] = []
    for ca, cb in zip(a, b):
        if ca == cb:
            chars.append(ca)
        elif ca != "-" and cb != "-":
            diff += 1
            chars.append("-")
        else:
            return None
    return "".join(chars) if diff == 1 else None


def cube_covers(cube: str, minterm: int, width: int) -> bool:
    """Check whether *cube* covers a given *minterm*."""
    bits = f"{minterm:0{width}b}"
    return all(c == "-" or c == bit for c, bit in zip(cube, bits))


def minimize_minterms(minterms: list[int], width: int) -> list[str]:
    """Minimize a list of minterm indices using Quine-McCluskey.

    Returns a sorted list of prime implicant cube strings.
    """
    if not minterms:
        return []
    all_count = 1 << width
    if len(minterms) == all_count:
        return ["-" * width]

    current = {f"{minterm:0{width}b}" for minterm in minterms}
    primes: set[str] = set()

    # Phase 1 — find all prime implicants
    while current:
        used: set[str] = set()
        next_round: set[str] = set()
        for a, b in itertools.combinations(sorted(current), 2):
            combined = combine_cubes(a, b)
            if combined is not None:
                used.add(a)
                used.add(b)
                next_round.add(combined)
        primes.update(current - used)
        current = next_round

    # Phase 2 — essential prime implicant selection + minimal cover
    coverage = {prime: {m for m in minterms if cube_covers(prime, m, width)} for prime in primes}
    uncovered = set(minterms)
    selected: set[str] = set()

    # Select essential primes
    while uncovered:
        essential = None
        for minterm in sorted(uncovered):
            covering = [prime for prime, covered in coverage.items() if minterm in covered]
            if len(covering) == 1:
                essential = covering[0]
                break
        if essential is None:
            break
        selected.add(essential)
        uncovered -= coverage[essential]

    # Cover remaining minterms with minimal-cost subset
    if uncovered:
        candidates = [
            prime for prime in primes if coverage[prime] & uncovered and prime not in selected
        ]
        best: tuple[int, int, tuple[str, ...]] | None = None
        for size in range(1, len(candidates) + 1):
            for combo in itertools.combinations(candidates, size):
                covered: set[int] = set()
                literals = 0
                for cube in combo:
                    covered |= coverage[cube]
                    literals += sum(ch != "-" for ch in cube)
                if uncovered <= covered:
                    score = (size, literals, tuple(sorted(combo)))
                    if best is None or score < best:
                        best = score
            if best is not None:
                selected.update(best[2])
                break

    return sorted(selected)


# ---------------------------------------------------------------------------
# Liberty expression generation
# ---------------------------------------------------------------------------


def cubes_to_liberty(cubes: list[str], input_names: list[str]) -> str:
    """Convert a set of prime-implicant cubes to a Liberty Boolean expression.

    Uses ``!`` for NOT, ``*`` for AND, ``+`` for OR.  Returns ``"0"`` or
    ``"1"`` for constant functions.
    """
    if not cubes:
        return "0"
    if cubes == ["-" * len(input_names)]:
        return "1"

    terms: list[str] = []
    for cube in cubes:
        literals = [
            name if bit == "1" else f"!{name}"
            for name, bit in zip(input_names, cube)
            if bit != "-"
        ]
        if len(literals) == 1:
            terms.append(literals[0])
        else:
            terms.append("(" + " * ".join(literals) + ")")
    return " + ".join(terms)


# ---------------------------------------------------------------------------
# Timing sense
# ---------------------------------------------------------------------------


def timing_sense(table: TruthTable, output_name: str, input_name: str) -> str | None:
    """Determine the timing sense (unateness) of an input→output arc.

    Returns one of ``"positive_unate"``, ``"negative_unate"``,
    ``"non_unate"``, or ``None`` if the output does not depend on the input.
    """
    by_inputs = {
        tuple(row_inputs[port.name] for port in table.inputs): row_outputs[output_name]
        for row_inputs, row_outputs in table.rows
    }
    input_idx = [port.name for port in table.inputs].index(input_name)
    rises = False
    falls = False
    depends = False

    for bits, out0 in by_inputs.items():
        if bits[input_idx] != "0":
            continue
        pair = list(bits)
        pair[input_idx] = "1"
        out1 = by_inputs.get(tuple(pair))
        if out1 is None or out0 == out1:
            continue
        depends = True
        rises |= out0 == "0" and out1 == "1"
        falls |= out0 == "1" and out1 == "0"

    if not depends:
        return None
    if rises and not falls:
        return "positive_unate"
    if falls and not rises:
        return "negative_unate"
    return "non_unate"


def functions_from_truth_table(table: TruthTable) -> dict[str, str]:
    """Derive a minimized Liberty function string for each output in *table*."""
    input_names = [port.name for port in table.inputs]
    functions: dict[str, str] = {}
    for output in table.outputs:
        minterms = [
            index
            for index, (_, row_outputs) in enumerate(table.rows)
            if row_outputs[output.name] == "1"
        ]
        cubes = minimize_minterms(minterms, len(input_names))
        functions[output.name] = cubes_to_liberty(cubes, input_names)
    return functions
