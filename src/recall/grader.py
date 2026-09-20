"""LLM grading of a free-text answer against a stored rubric.

Two deliberate choices, independent of which model does the grading:

1. The model grades against the *rubric points*, not against prose similarity
   to the reference answer. Similarity grading rewards an answer that uses the
   right vocabulary without the right mechanics - exactly the failure this
   tool exists to catch.

2. The reference answer is labelled with its trust status in the prompt, at
   three levels rather than two. Human-signed references are authoritative;
   *model*-checked ones are presented as probably-right but still challengeable;
   unverified ones are presented as suspect. Collapsing the middle level into
   the first would make `checked_by` decorative - the grader would defer
   absolutely to a reference no person has ever read.

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
    "This reference answer has been verified by a person against {source}. "
    "Treat it as authoritative."
)
_MODEL_CHECKED_NOTE = (
    "This reference answer was checked against external sources by a model "
    "({checked_by}), not by a person. Source: {source}. It is likely correct, "
    "so grade the candidate against the rubric in the normal way - but it has "
    "had no human signoff. If it states something you are confident is wrong, "
    "record that in `errors` as a REFERENCE CONFLICT instead of marking the "
    "candidate wrong for disagreeing with it."
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
    if p.status is not TrustStatus.VERIFIED:
        note = _UNTRUSTED_NOTE
    elif p.human_checked:
        note = _TRUSTED_NOTE.format(source=p.source)
    else:
        note = _MODEL_CHECKED_NOTE.format(source=p.source, checked_by=p.checked_by)
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
        self.used_model = self.model
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


#: Tried in order when the primary model returns 503/429, most to least
#: capable. Free-tier Flash is frequently congested and Pro is excluded
#: outright (limit: 0), so flash-lite is the availability floor.
GEMINI_FALLBACKS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.7-flash",       # last: 503 on every attempt during measurement
]

#: Models able to override a wrong reference and report a REFERENCE CONFLICT.
#: Grading an *unverified* question requires this: the stored answer may be
#: wrong, so the grader must supply its own knowledge rather than defer.
#:
#: Measured on eval/fixtures.yaml::kl-reference-and-rubric-wrong - reference
#: AND rubric both carry the error, candidate answer is correct:
#:
#:   gemini-3.8-flash       verdict=correct,   conflict flagged   CONFIRMED
#:   gemini-3.6-flash       verdict=correct,   conflict flagged   CONFIRMED
#:   gemini-3.5-flash       verdict=correct,   conflict flagged   CONFIRMED
#:   gemini-3.5-flash-lite  verdict=INCORRECT, no conflict        unsafe
#:   gemini-3.1-flash-lite  verdict=INCORRECT, conflict flagged   unsafe
#:                          (noticed the problem and failed you anyway)
#:
#: flash-lite marks a CORRECT answer wrong when the reference is wrong, which
#: would train the misconception in - strictly worse than refusing to grade.
#:
#: The whole flash tier that could be reached is confirmed. gemini-3.7-flash
#: returned 503 on every one of 12 attempts over ~36 minutes (see
#: eval/poll_congested.py, eval/tier_results.json) and stays inferred; the Pro
#: tier is unreachable on the free plan (limit: 0).
CONFLICT_CAPABLE = frozenset({
    "gemini-3.8-flash",       # CONFIRMED
    "gemini-3.7-flash",       # inferred - 503 across 12 attempts / 36 min
    "gemini-3.6-flash",       # CONFIRMED
    "gemini-3.5-flash",       # CONFIRMED
    "gemini-flash-latest",    # inferred (alias)
    "gemini-3.1-pro-preview", # inferred (free tier: limit 0)
    "gemini-pro-latest",      # inferred
})


class NoCapableModel(RuntimeError):
    """No model able to grade an unverified question was reachable."""

_TRANSIENT = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")


def _is_transient(exc: Exception) -> bool:
    return any(t in str(exc) for t in _TRANSIENT)


class GeminiGrader:
    name = "gemini"

    def __init__(self, model: str | None = None, client=None, fallbacks=None):
        from google import genai

        self.model = model or GEMINI_MODEL
        self.used_model = self.model
        # `is None` not falsy: fallbacks=[] means *no* fallbacks, which is not
        # the same as 'unspecified, use defaults'.
        chain = GEMINI_FALLBACKS if fallbacks is None else fallbacks
        self.fallbacks = [m for m in chain if m != self.model]
        if client is None:
            key = get_key("GEMINI_API_KEY") or get_key("GOOGLE_API_KEY")
            if not key:
                raise MissingCredential(
                    "GEMINI_API_KEY is not set. Get one at "
                    "https://aistudio.google.com/apikey, then put it in .env."
                )
            client = genai.Client(api_key=key)
        self.client = client

    def _call(self, model: str, prompt: str) -> Grade:
        from google.genai import types

        response = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=Grade,
                # we never want tool calls here; also silences the AFC warning
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            ),
        )
        parsed = response.parsed
        # The SDK returns the pydantic instance when response_schema is a model,
        # but falls back to a dict on some paths - normalise either way.
        return parsed if isinstance(parsed, Grade) else Grade.model_validate(parsed)

    def grade(self, question: Question, answer: str) -> Grade:
        """Grade, degrading to a less contended model rather than failing.

        Free-tier Flash and Pro return 503/429 often enough that a single
        attempt would interrupt a review session regularly. `used_model`
        records what actually answered, so a grade is never silently
        attributed to a model that did not produce it.
        """
        import time

        prompt = build_prompt(question, answer)
        chain = [self.model, *self.fallbacks]

        # An unverified reference may itself be wrong, so the grader has to be
        # able to overrule it. Degrading to a model that cannot do that would
        # silently turn a safe grade into one that marks correct answers wrong
        # - the worst outcome this tool can produce. Refuse instead.
        #
        # Deliberately gated on `trusted`, not on `human_checked`: a
        # model-checked reference is challengeable in the *prompt* but is still
        # probably right, and the measured flash-lite failure was specifically
        # about overruling a reference that is wrong. Gating the middle tier
        # here too would route the entire bank to the congested flash tier to
        # guard against a case whose prior is now low.
        if not question.provenance.trusted:
            chain = [m for m in chain if m in CONFLICT_CAPABLE]
            if not chain:
                raise NoCapableModel(
                    f"{self.model!r} is not rated to grade an unverified "
                    "question: it cannot reliably overrule a wrong reference. "
                    f"Use one of {sorted(CONFLICT_CAPABLE)}, or verify the "
                    "question first."
                )

        last: Exception | None = None
        for model in chain:
            for attempt in range(2):
                try:
                    grade = self._call(model, prompt)
                    self.used_model = model
                    return grade
                except Exception as exc:
                    last = exc
                    if not _is_transient(exc):
                        raise
                    if attempt == 0:
                        time.sleep(1.5)
        tier = "" if question.provenance.trusted else (
            " Only conflict-capable models are eligible here because the "
            "question is unverified."
        )
        raise RuntimeError(
            f"every eligible Gemini model was unavailable (last: {last})."
            f"{tier} Free-tier Flash is often congested - try again shortly."
        ) from last


BACKENDS = {"anthropic": AnthropicGrader, "gemini": GeminiGrader}


def make_grader(backend: str | None = None, model: str | None = None) -> GraderBackend:
    name = (backend or backend_name()).lower()
    if name not in BACKENDS:
        raise ValueError(f"unknown backend {name!r}; choose from {sorted(BACKENDS)}")
    return BACKENDS[name](model=model or model_override())


#: Backwards-compatible alias - `Grader()` still resolves via config.
def Grader(*args, **kwargs) -> GraderBackend:  # noqa: N802
    return make_grader(*args, **kwargs)
