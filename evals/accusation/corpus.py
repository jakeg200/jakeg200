"""The false-accusation corpus. SPEC.md §10, and M2's acceptance gate.

60+ correct derivations, including unusual orders and non-standard notation. Assert we never claim
a break in a correct chain. Target < 1%, fail the build above 2%.

The corpus is deliberately weighted toward the things that make a verifier wrong for the *right*
reasons — a learner who skips two steps at once, writes 3·x, puts the unknown on the right, divides
before transposing, or uses a fraction bar where the textbook used a division sign. Every one of
those is correct work, and every one of them is a plausible way for a naive checker to accuse
someone.

A derivation that tier 1 cannot parse is not a failure here. `unverifiable` is a pass: the
requirement is that we never claim a break, not that we always find one.
"""

from __future__ import annotations

from atrium.seed.linear_equations import PROBLEMS

#: Correct derivations, unusual routes, and non-standard notation.
EXTRA_CHAINS: list[tuple[str, list[str]]] = [
    # --- unusual order: divide before transposing -------------------------------------------
    ("divide-first-1", ["2x + 6 = 14", "x + 3 = 7", "x = 4"]),
    ("divide-first-2", ["3x + 9 = 21", "x + 3 = 7", "x = 4"]),
    ("divide-first-3", ["4x - 8 = 12", "x - 2 = 3", "x = 5"]),
    ("divide-first-4", ["5(x + 2) = 35", "x + 2 = 7", "x = 5"]),
    # --- two steps collapsed into one -------------------------------------------------------
    ("collapsed-1", ["3x + 8 = 23", "x = 5"]),
    ("collapsed-2", ["4x - 4 = 2x + 6", "x = 5"]),
    ("collapsed-3", ["2(x + 3) = 14", "x = 4"]),
    ("collapsed-4", ["7 - 2x = 1", "x = 3"]),
    # --- unknown on the right ---------------------------------------------------------------
    ("right-side-1", ["12 = 3x", "4 = x"]),
    ("right-side-2", ["23 = 3x + 8", "15 = 3x", "5 = x"]),
    ("right-side-3", ["3x + 8 = 23", "23 = 3x + 8", "15 = 3x", "x = 5"]),
    ("right-side-4", ["20 = 4(x - 1)", "5 = x - 1", "6 = x"]),
    # --- non-standard notation --------------------------------------------------------------
    ("notation-cdot", [r"3 \cdot x = 15", "x = 5"]),
    ("notation-times", [r"3 \times x = 15", "x = 5"]),
    ("notation-frac", [r"\frac{3x}{3} = \frac{15}{3}", "x = 5"]),
    ("notation-frac-2", [r"\frac{x}{4} = 3", "x = 12"]),
    ("notation-frac-3", [r"\frac{2x + 1}{3} = 5", "2x + 1 = 15", "x = 7"]),
    ("notation-div", [r"15 \div 3 = x", "5 = x"]),
    ("notation-braces", ["2{x + 3} = 14", "2x + 6 = 14", "x = 4"]),
    ("notation-spacing", ["3 x + 8 = 23", "3 x = 15", "x = 5"]),
    ("notation-parens", ["((3x)) + 8 = 23", "3x = 15", "x = 5"]),
    ("notation-caret", ["x^1 + 4 = 9", "x = 5"]),
    ("notation-implicit", ["2(x)(1) = 10", "2x = 10", "x = 5"]),
    # --- signs, the classic false-accusation trap -------------------------------------------
    ("signs-1", ["5 - 2x = 1", "-2x = -4", "x = 2"]),
    ("signs-2", ["5 - 2x = 1", "5 = 1 + 2x", "4 = 2x", "x = 2"]),
    ("signs-3", ["-x = -2", "x = 2"]),
    ("signs-4", ["-3x + 6 = 0", "6 = 3x", "x = 2"]),
    ("signs-5", ["7 - (x + 2) = 3", "5 - x = 3", "x = 2"]),
    ("signs-6", ["-(x - 4) = 1", "4 - x = 1", "x = 3"]),
    # --- fractions and non-integer answers --------------------------------------------------
    ("fraction-answer-1", ["3x = 7", "x = 7/3"]),
    ("fraction-answer-2", ["2x + 1 = 4", "2x = 3", "x = 3/2"]),
    ("fraction-answer-3", [r"3x = 7", r"x = \frac{7}{3}"]),
    ("fraction-answer-4", ["4x = 2", "x = 1/2", "x = 0.5"]),
    # --- expression rearrangement (not equations) -------------------------------------------
    ("expr-1", ["2(x + 3)", "2x + 6"]),
    ("expr-2", ["x^2 - 1", "(x - 1)(x + 1)"]),
    ("expr-3", ["3x + 2x", "5x"]),
    ("expr-4", [r"\frac{x}{2} + \frac{x}{3}", r"\frac{5x}{6}"]),
    ("expr-5", ["(x + 1)^2", "x^2 + 2x + 1"]),
    ("expr-6", ["4(x - 2) + 8", "4x"]),
    # --- redundant and no-op steps a learner really writes ----------------------------------
    ("noop-1", ["3x = 15", "3x = 15", "x = 5"]),
    ("noop-2", ["x = 5", "x = 5"]),
    ("noop-3", ["2x = 10", "10 = 2x", "x = 5"]),
    ("restate-1", ["x + 7 = 12", "7 + x = 12", "x = 5"]),
    ("restate-2", ["4x - 4 = 2x + 6", "2x + 6 = 4x - 4", "x = 5"]),
    # --- longer correct chains ---------------------------------------------------------------
    ("long-1", ["2(3x - 1) = 4(x + 2)", "6x - 2 = 4x + 8", "2x - 2 = 8", "2x = 10", "x = 5"]),
    ("long-2", ["3(x - 2) = x + 4", "3x - 6 = x + 4", "2x = 10", "x = 5"]),
    ("long-3", ["x/2 + x/3 = 5", "5x/6 = 5", "5x = 30", "x = 6"]),
    ("long-4", ["(2x + 1)/3 = 5", "2x + 1 = 15", "2x = 14", "x = 7"]),
    ("long-5", ["5(q + 1) = 2q + 17", "5q + 5 = 2q + 17", "3q = 12", "q = 4"]),
    # --- identities and degenerate but correct cases -----------------------------------------
    ("identity-1", ["2x + 2 = 2(x + 1)", "0 = 0"]),
    ("identity-2", ["x + 0 = 5", "x = 5"]),
    ("identity-3", ["1x = 5", "x = 5"]),
    # --- decimals ---------------------------------------------------------------------------
    ("decimal-1", ["0.5x = 2", "x = 4"]),
    ("decimal-2", ["x + 1.5 = 4", "x = 2.5"]),
    ("decimal-3", ["2.5x = 10", "x = 4"]),
    # --- other variable names ----------------------------------------------------------------
    ("var-t", ["5t - 4 = 26", "5t = 30", "t = 6"]),
    ("var-theta", ["3n + 1 = 10", "3n = 9", "n = 3"]),
    ("var-p", ["7p + 2 = 3p + 18", "4p = 16", "p = 4"]),
]


def build() -> list[tuple[str, list[str]]]:
    """Every chain in the corpus. Each is correct; none may be reported as broken."""
    chains: list[tuple[str, list[str]]] = []
    for problem in PROBLEMS:
        chains.append(
            (f"{problem['id']}-canonical", [problem["statement"], *problem["solution_steps"]])
        )
        analogue = problem["analogue"]
        chains.append((f"{problem['id']}-analogue", [analogue["statement"], *analogue["steps"]]))
    chains.extend(EXTRA_CHAINS)
    return chains
