"""Question, provenance and grading models.

The provenance field is the point of this whole design: a question is only
trusted as an answer key once a human has checked it against a real source.
Everything else in the system keys off `Provenance.status`.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class TrustStatus(str, Enum):
    """How much the stored answer can be trusted as a grading reference."""

    #: Checked by a human against a named source. Safe to grade against.
    VERIFIED = "verified"
    #: LLM-generated, nobody has checked it. Still asked, but flagged after
    #: you answer so you audit the grader instead of deferring to it.
    UNVERIFIED = "unverified"
    #: Known or suspected wrong. Never served until fixed.
    DISPUTED = "disputed"


class Provenance(BaseModel):
    status: TrustStatus = TrustStatus.UNVERIFIED
    #: Free text, but be specific: "Murphy, PML Vol 1, SS6.2" beats "textbook".
    source: str | None = None
    #: When this answer was last checked against `source`.
    checked: date | None = None
    #: WHO checked it. Kept distinct from `checked` on purpose: a claim
    #: confirmed by a model against fetched sources is better than an
    #: unchecked one but is not the same as a person reading the cited
    #: textbook, and collapsing the two would quietly recreate the problem
    #: this whole system exists to prevent.
    checked_by: str | None = None
    #: Where in the vault this came from. Never treated as verification -
    #: the vault is LLM-generated and is a topic map, not an answer key.
    vault_ref: str | None = None

    # model_validator, not field_validator: a field validator on `source`
    # never fires when `source` is left at its default, which is exactly the
    # case this rule exists to catch.
    @model_validator(mode="after")
    def _source_required_when_verified(self) -> "Provenance":
        if self.status is TrustStatus.VERIFIED:
            if not self.source:
                raise ValueError("a verified question must name its source")
            if not self.checked_by:
                raise ValueError("a verified question must record checked_by")
        return self

    @property
    def trusted(self) -> bool:
        return self.status is TrustStatus.VERIFIED

    @property
    def human_checked(self) -> bool:
        """True only when a person signed off, not a model."""
        return self.trusted and not (self.checked_by or "").startswith("claude")


class Question(BaseModel):
    id: str
    topic: str
    prompt: str
    #: The reference answer. Only authoritative when provenance is verified.
    answer: str
    #: The specific points an answer must hit. The grader scores against
    #: these, not against prose similarity to `answer` - that is what keeps
    #: a fluent-but-wrong answer from passing.
    rubric: list[str] = Field(min_length=1)
    provenance: Provenance = Field(default_factory=Provenance)
    difficulty: int = Field(default=3, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not v or " " in v:
            raise ValueError(f"id must be a non-empty slug without spaces: {v!r}")
        return v

    @property
    def servable(self) -> bool:
        return self.provenance.status is not TrustStatus.DISPUTED


class RubricPoint(BaseModel):
    """The grader's verdict on one rubric line."""

    point: str
    hit: bool
    comment: str


class Grade(BaseModel):
    """Structured grading result. Returned by the model via structured outputs."""

    rubric_points: list[RubricPoint]
    #: Anything stated that is actually wrong, as opposed to merely missing.
    #: Tracked separately because a confident error is worse than a gap.
    errors: list[str] = Field(default_factory=list)
    verdict: Literal["correct", "partial", "incorrect"]
    #: One discriminative follow-up, per the Inverted Feynman prompt.
    followup: str

    @property
    def score(self) -> float:
        if not self.rubric_points:
            return 0.0
        return sum(p.hit for p in self.rubric_points) / len(self.rubric_points)
