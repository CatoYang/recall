"""Question loading (YAML, in git) and review state (SQLite, not in git).

The split is deliberate: questions are content you want to diff, review, and
roll back, so they live in version control. Review state is a high-churn
append log that would make every commit noise, so it lives in a local db.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
from fsrs import Card

from .schema import Grade, Question, TrustStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    question_id TEXT PRIMARY KEY,
    fsrs_card   TEXT NOT NULL          -- Card.to_dict() as JSON
);
CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    answer      TEXT NOT NULL,         -- what you actually wrote, verbatim
    verdict     TEXT NOT NULL,
    score       REAL NOT NULL,
    grade_json  TEXT NOT NULL,         -- full Grade, for auditing grader drift
    rating      INTEGER NOT NULL       -- FSRS rating actually applied
);
CREATE INDEX IF NOT EXISTS reviews_by_question ON reviews(question_id);
"""


class QuestionBank:
    """Loads every *.yaml under a questions/ directory."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.questions: dict[str, Question] = {}
        self.load()

    def load(self) -> None:
        self.questions.clear()
        for path in sorted(self.root.rglob("*.yaml")):
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            if not isinstance(raw, list):
                raise ValueError(f"{path}: expected a list of questions")
            for entry in raw:
                q = Question.model_validate(entry)
                if q.id in self.questions:
                    raise ValueError(f"duplicate question id {q.id!r} in {path}")
                self.questions[q.id] = q

    def __len__(self) -> int:
        return len(self.questions)

    def servable(self) -> list[Question]:
        return [q for q in self.questions.values() if q.servable]

    def by_status(self, status: TrustStatus) -> list[Question]:
        return [q for q in self.questions.values() if q.provenance.status is status]


class ReviewStore:
    """FSRS card state plus a full, auditable history of your own answers."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_card(self, question_id: str) -> Card:
        row = self.conn.execute(
            "SELECT fsrs_card FROM cards WHERE question_id = ?", (question_id,)
        ).fetchone()
        if row is None:
            return Card()
        return Card.from_dict(json.loads(row["fsrs_card"]))

    def save_card(self, question_id: str, card: Card) -> None:
        self.conn.execute(
            "INSERT INTO cards (question_id, fsrs_card) VALUES (?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET fsrs_card = excluded.fsrs_card",
            (question_id, json.dumps(card.to_dict())),
        )
        self.conn.commit()

    def record(
        self, question_id: str, answer: str, grade: Grade, rating: int
    ) -> None:
        self.conn.execute(
            "INSERT INTO reviews (question_id, reviewed_at, answer, verdict, "
            "score, grade_json, rating) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                question_id,
                datetime.now(timezone.utc).isoformat(),
                answer,
                grade.verdict,
                grade.score,
                grade.model_dump_json(),
                rating,
            ),
        )
        self.conn.commit()

    def due_ids(self, now: datetime | None = None) -> set[str]:
        """Question ids whose card is due. Unseen questions are always due."""
        now = now or datetime.now(timezone.utc)
        due = set()
        for row in self.conn.execute("SELECT question_id, fsrs_card FROM cards"):
            card = Card.from_dict(json.loads(row["fsrs_card"]))
            if card.due <= now:
                due.add(row["question_id"])
        return due

    def seen_ids(self) -> set[str]:
        return {r["question_id"] for r in self.conn.execute("SELECT question_id FROM cards")}

    def history(self, question_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM reviews WHERE question_id = ? ORDER BY reviewed_at",
                (question_id,),
            )
        )

    def stats(self) -> dict[str, float | int]:
        row = self.conn.execute(
            "SELECT COUNT(*) n, AVG(score) avg FROM reviews"
        ).fetchone()
        return {"reviews": row["n"] or 0, "mean_score": row["avg"] or 0.0}
