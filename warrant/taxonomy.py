"""A small, named taxonomy of misconceptions.

Named, because "you made a mistake" is not a diagnosis. Small, because a taxonomy is
only worth having if each entry has a distinct probe attached to it, and a probe is only
worth having if it makes the learner do the thinking. Grow this list only when a real
error in the eval set cannot be described by anything already here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Misconception:
    id: str
    name: str
    description: str
    probe: str
    """A Socratic question. It must point at the step, never at the answer."""


MISCONCEPTIONS: dict[str, Misconception] = {
    m.id: m
    for m in [
        Misconception(
            id="sign_error_across_equals",
            name="Sign lost moving a term",
            description=(
                "A term was moved to the other side of the equals sign without changing "
                "its sign, or was subtracted from one side only."
            ),
            probe=(
                "You moved a term across the equals sign here. What has to happen to that "
                "term's sign when it crosses, and why?"
            ),
        ),
        Misconception(
            id="operation_applied_to_one_side",
            name="Operation applied to one side only",
            description=(
                "An operation was carried out on one side of the equation but not the other, "
                "so the two sides no longer balance."
            ),
            probe=(
                "If you put the same number in for the unknown in the line above and the "
                "line below, would they still agree, and what does that tell you about "
                "what was done to each side?"
            ),
        ),
        Misconception(
            id="divide_only_one_term",
            name="Divided part of a side",
            description=(
                "When dividing through, only one term on a side was divided, leaving the "
                "rest of that side untouched."
            ),
            probe=(
                "When you divide a side that has more than one piece to it, which of "
                "those pieces does the division reach?"
            ),
        ),
        Misconception(
            id="inverse_operation_error",
            name="Same operation instead of the inverse",
            description=(
                "The operation used to undo something was the operation itself rather than "
                "its inverse — multiplying where dividing was needed, or adding where "
                "subtracting was needed."
            ),
            probe=(
                "What is currently being done to the unknown on that line, and what single "
                "operation undoes it?"
            ),
        ),
        Misconception(
            id="combine_unlike_terms",
            name="Unlike terms combined",
            description=(
                "A term in the unknown was added to or merged with a constant, as though "
                "they were the same kind of thing."
            ),
            probe=(
                "Are the two things you combined on that line the same kind of quantity, "
                "and what happens to each of them when the unknown changes?"
            ),
        ),
        Misconception(
            id="distribution_incomplete",
            name="Bracket expanded incompletely",
            description=(
                "A factor outside a bracket was applied to the first term inside it but not "
                "to the rest."
            ),
            probe=("How many of the things inside the bracket does the factor outside it reach?"),
        ),
        Misconception(
            id="cancel_across_sum",
            name="Cancelled across a sum",
            description=(
                "Something was cancelled from a sum rather than from a product, which is not "
                "a legal cancellation."
            ),
            probe=(
                "Does that cancellation still hold if you try it with a specific number "
                "in place of the unknown?"
            ),
        ),
        Misconception(
            id="lost_solution",
            name="Solution lost or gained",
            description=(
                "Dividing by an expression that can be zero, or squaring both sides, changed "
                "which values actually satisfy the equation."
            ),
            probe=(
                "Every value that solved the line above should still solve the line "
                "below, so which one went missing, and which step lost it?"
            ),
        ),
        Misconception(
            id="arithmetic_slip",
            name="Arithmetic slip",
            description=(
                "The method is sound and the structure of the step is right, but a number "
                "was computed incorrectly."
            ),
            probe=(
                "The shape of that step is right, so what do you get if you work the "
                "arithmetic on that line out again on its own?"
            ),
        ),
        Misconception(
            id="unjustified_leap",
            name="Unjustified leap",
            description=(
                "The conclusion may well be true, but nothing on the preceding line supports "
                "getting to it in one move."
            ),
            probe=(
                "What is the intermediate line between these two, and what did you do in "
                "your head to get across it?"
            ),
        ),
        Misconception(
            id="no_derivation",
            name="Answer asserted, not derived",
            description=(
                "An answer was stated and possibly checked, but no working shows where it "
                "came from. Checking an answer confirms it; it does not derive it."
            ),
            probe=(
                "Substituting confirms that value works, but if you had not already known "
                "it, what would the first line of getting there be?"
            ),
        ),
        Misconception(
            id="none",
            name="No break found",
            description="Every step that could be checked followed from the one before it.",
            probe="",
        ),
    ]
}

GENERIC_PROBE = (
    "I cannot follow how you got from the line above to this one. Can you say what you "
    "did in that step, and why it is allowed?"
)


def get(misconception_id: str | None) -> Misconception:
    if misconception_id and misconception_id in MISCONCEPTIONS:
        return MISCONCEPTIONS[misconception_id]
    return MISCONCEPTIONS["unjustified_leap"]
