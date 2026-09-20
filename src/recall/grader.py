"""LLM grading of a free-text answer against a stored rubric.

Two deliberate choices here:

1. The model grades against the *rubric points*, not against prose similarity
   to the reference answer. Similarity grading rewards an answer that uses the
   right vocabulary without the right mechanics - exactly the failure this
   tool exists to catch.

2. The reference answer is labelled with its trust status in the prompt. For
   an unverified question the model is told the reference may itself be wrong
   and is asked to flag a conflict rather than defer to it.
"""

from __future__ import annotations

import anthropic

from .schema import Grade, Question, TrustStatus

MODEL = "claude-opus-5"

SYSTEM = """You are a rigorous examiner for an advanced ML/statistics assessment.

Grade the candidate's answer against the supplied rubric points. For each point, \
decide whether the answer actually demonstrates it - not whether it mentions the \
right words. An answer that names a concept without its mechanism has NOT hit the \
point.

Rules:
- Judge only what the candidate wrote. Do not credit knowledge they did not show.
- Separate MISSING from WRONG. A rubric point not covered is a miss. A positive \
claim that is false is an error, and errors are what matter most - record each one \
in `errors` with the incorrect claim quoted.
- Be strict about terminology precision, direction of implication, and boundary \
conditions. Flag conflated terms.
- Do not re-teach the topic. Do not pad with encouragement.
- End with one discriminative follow-up question probing an adjacent edge case. \
Do not answer it.

Verdicts: `correct` = every rubric point hit and no errors. `partial` = some points \
hit, no serious errors. `incorrect` = most points missed, or any fundamental error."""

_TRUSTED_NOTE = (
    "This reference answer has been verified against {source}. Treat it as "
    "authoritative."
)
_UNTRUSTED_NOTE = (
    "WARNING: this reference answer is LLM-generated and has NOT been verified "
    "by a human. It may contain errors. Grade against the rubric using your own "
    "knowledge. If the reference or a rubric point contradicts what you know to "
    "be correct, say so explicitly in `errors` as a REFERENCE CONFLICT rather "
    "than marking the candidate wrong."
)


def build_prompt(question: Question, answer: str) -> str:
    p = question.provenance
    note = (
        _TRUSTED_NOTE.format(source=p.source)
        if p.status is TrustStatus.VERIFIED
        else _UNTRUSTED_NOTE
    )
    points = "\n".join(f"{i}. {r}" for i, r in enumerate(question.rubric, 1))
    return f"""<question>
{question.prompt}
</question>

<rubric>
{points}
</rubric>

<reference_answer>
{question.answer}
</reference_answer>

<reference_trust>
{note}
</reference_trust>

<candidate_answer>
{answer}
</candidate_answer>"""


class Grader:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model

    def grade(self, question: Question, answer: str) -> Grade:
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": build_prompt(question, answer)}],
            output_format=Grade,
        )
        return response.parsed_output
