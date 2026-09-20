"""FSRS scheduling plus the grade -> rating mapping and question selection."""

from __future__ import annotations

import random
from datetime import datetime, timezone

from fsrs import Card, Rating, Scheduler

from .schema import Grade, Question, TrustStatus
from .store import QuestionBank, ReviewStore


def grade_to_rating(grade: Grade) -> Rating:
    """Map a structured grade onto an FSRS rating.

    Any outright error drops straight to `Again`, even when most rubric
    points were hit. Stating something false is a worse failure mode than
    leaving something out - it means the wrong thing is what got encoded,
    and it should come back soon.
    """
    if grade.errors or grade.verdict == "incorrect":
        return Rating.Again
    if grade.verdict == "partial" or grade.score < 1.0:
        return Rating.Hard
    return Rating.Good


class ReviewSession:
    """Picks what to ask next and applies scheduling after each answer."""

    def __init__(
        self,
        bank: QuestionBank,
        store: ReviewStore,
        *,
        topic: str | None = None,
        include_unverified: bool = True,
        rng: random.Random | None = None,
    ):
        self.bank = bank
        self.store = store
        self.topic = topic
        self.include_unverified = include_unverified
        self.scheduler = Scheduler()
        self.rng = rng or random.Random()

    def _eligible(self) -> list[Question]:
        qs = self.bank.servable()
        if self.topic:
            qs = [q for q in qs if q.topic == self.topic]
        if not self.include_unverified:
            qs = [q for q in qs if q.provenance.trusted]
        return qs

    def queue(self, now: datetime | None = None, limit: int | None = None) -> list[Question]:
        """Due questions first (most overdue first), then unseen ones.

        Verified questions sort ahead of unverified at equal urgency, so a
        session leads with the material you can actually trust.
        """
        now = now or datetime.now(timezone.utc)
        seen = self.store.seen_ids()
        due, fresh = [], []
        for q in self._eligible():
            if q.id in seen:
                card = self.store.get_card(q.id)
                if card.due <= now:
                    due.append((card.due, not q.provenance.trusted, q))
            else:
                fresh.append((not q.provenance.trusted, q))
        due.sort(key=lambda t: (t[0], t[1]))
        fresh.sort(key=lambda t: t[0])
        ordered = [q for *_, q in due] + [q for _, q in fresh]
        return ordered[:limit] if limit else ordered

    def apply(self, question: Question, answer: str, grade: Grade) -> Card:
        rating = grade_to_rating(grade)
        card = self.store.get_card(question.id)
        card, _log = self.scheduler.review_card(card, rating)
        self.store.save_card(question.id, card)
        self.store.record(question.id, answer, grade, int(rating))
        return card


def bank_summary(bank: QuestionBank) -> str:
    v = len(bank.by_status(TrustStatus.VERIFIED))
    u = len(bank.by_status(TrustStatus.UNVERIFIED))
    d = len(bank.by_status(TrustStatus.DISPUTED))
    return f"{len(bank)} questions - {v} verified, {u} unverified, {d} disputed"
