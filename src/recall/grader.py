"""LLM grading of a free-text answer against a stored rubric.

Two deliberate choices, independent of which model does the grading:

1. The model grades against the *rubric points*, not against prose similarity
   to the reference answer. Similarity grading rewards an answer that uses the
   right vocabulary without the right mechanics - exactly the failure this
   tool exists to catch.

2. The reference answer is labelled with its trust status in the prompt. For
   an unverified question the model is told the reference may itself be wrong
   and is asked to flag a conflict rather than defer to it.

Backends are pluggable because the capability a grader needs depends on the
job: grading against a *verified* reference is comparison (mid-tier models are
fine), while grading against an *unverified* one requires the grader to supply
its own domain knowledge (frontier only).
"""

from __future__ import annotations

from typing import Protocol

from .config import backend_name, get_key, model_override
from .schema import Grade, Question, TrustStatus

ANTHROPIC_MODEL = "claude-opus-5"
GEMINI_MODEL = "gemini-flash-latest"

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


class MissingCredential(RuntimeError):
    pass


class GraderBackend(Protocol):
    name: str
    model: str

    def grade(self, question: Question, answer: str) -> Grade: ...


class AnthropicGrader:
    name = "anthropic"

    def __init__(self, model: str | None = None, client=None):
        import anthropic

        self.model = model or ANTHROPIC_MODEL
        if client is None:
            key = get_key("ANTHROPIC_API_KEY")
            if not key:
                raise MissingCredential(
                    "ANTHROPIC_API_KEY is not set. Put it in .env or export it."
                )
            client = anthropic.Anthropic(api_key=key)
        self.client = client

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


class GeminiGrader:
    name = "gemini"

    def __init__(self, model: str | None = None, client=None):
        from google import genai

        self.model = model or GEMINI_MODEL
        if client is None:
            key = get_key("GEMINI_API_KEY") or get_key("GOOGLE_API_KEY")
            if not key:
                raise MissingCredential(
                    "GEMINI_API_KEY is not set. Get one at "
                    "https://aistudio.google.com/apikey, then put it in .env."
                )
            client = genai.Client(api_key=key)
        self.client = client

    def grade(self, question: Question, answer: str) -> Grade:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=build_prompt(question, answer),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=Grade,
            ),
        )
        parsed = response.parsed
        # The SDK returns the pydantic instance when response_schema is a model,
        # but falls back to a dict on some paths - normalise either way.
        return parsed if isinstance(parsed, Grade) else Grade.model_validate(parsed)


BACKENDS = {"anthropic": AnthropicGrader, "gemini": GeminiGrader}


def make_grader(backend: str | None = None, model: str | None = None) -> GraderBackend:
    name = (backend or backend_name()).lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; choose from {sorted(BACKENDS)}")
    return BACKENDS[name](model=model or model_override())


#: Backwards-compatible alias - `Grader()` still resolves via config.
def Grader(*args, **kwargs) -> GraderBackend:  # noqa: N802
    return make_grader(*args, **kwargs)
