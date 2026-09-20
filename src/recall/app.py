"""Textual TUI for review sessions."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, Markdown, Static, TextArea

from .grader import Grader
from .schema import Grade, Question
from .scheduler import ReviewSession, bank_summary, grade_to_rating
from .store import QuestionBank, ReviewStore

_VERDICT_STYLE = {"correct": "green", "partial": "yellow", "incorrect": "red"}


class RecallApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "recall"

    BINDINGS = [
        Binding("ctrl+s", "submit", "Submit answer"),
        Binding("ctrl+n", "next", "Next question"),
        Binding("ctrl+r", "reveal", "Reveal reference"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, questions_dir: Path, db_path: Path, topic: str | None = None):
        super().__init__()
        self.bank = QuestionBank(questions_dir)
        self.store = ReviewStore(db_path)
        self.session = ReviewSession(self.bank, self.store, topic=topic)
        self.queue: list[Question] = []
        self.current: Question | None = None
        self.grading = False

    # ---------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with VerticalScroll(id="left"):
                yield Label("", id="meta")
                yield Markdown("", id="prompt")
                yield TextArea(id="answer", language="markdown")
            with VerticalScroll(id="right"):
                yield Static("Answer, then Ctrl+S to grade.", id="feedback")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = bank_summary(self.bank)
        self.queue = self.session.queue()
        self.advance()
        self.query_one("#answer", TextArea).focus()

    # ------------------------------------------------------------ navigation

    def advance(self) -> None:
        if not self.queue:
            self.current = None
            self.query_one("#prompt", Markdown).update("## Nothing due\n\nQueue is empty.")
            self.query_one("#meta", Label).update("")
            self.query_one("#feedback", Static).update(
                f"Session complete. {self.store.stats()['reviews']} reviews on record."
            )
            return
        self.current = self.queue.pop(0)
        q = self.current
        flag = "" if q.provenance.trusted else "  (UNVERIFIED)"
        self.query_one("#meta", Label).update(
            f"{q.topic} - difficulty {q.difficulty}/5{flag}   ({len(self.queue)} left)"
        )
        self.query_one("#prompt", Markdown).update(f"## Question\n\n{q.prompt}")
        area = self.query_one("#answer", TextArea)
        area.text = ""
        area.focus()
        self.query_one("#feedback", Static).update("Answer, then Ctrl+S to grade.")

    # -------------------------------------------------------------- actions

    def action_next(self) -> None:
        if not self.grading:
            self.advance()

    def action_reveal(self) -> None:
        if self.current:
            self.query_one("#feedback", Static).update(
                f"REFERENCE ANSWER\n\n{self.current.answer}\n\n"
                f"Provenance: {self.current.provenance.status.value}"
                + (f" ({self.current.provenance.source})" if self.current.provenance.source else "")
            )

    def action_submit(self) -> None:
        if self.grading or self.current is None:
            return
        answer = self.query_one("#answer", TextArea).text.strip()
        if not answer:
            self.notify("Write an answer first.", severity="warning")
            return
        self.grading = True
        self.query_one("#feedback", Static).update("Grading...")
        self.grade_answer(self.current, answer)

    @work(thread=True, exclusive=True)
    def grade_answer(self, question: Question, answer: str) -> None:
        try:
            grade = Grader().grade(question, answer)
        except Exception as exc:  # surfaced in the panel, session continues
            self.call_from_thread(self.on_grade_failed, exc)
            return
        self.call_from_thread(self.on_graded, question, answer, grade)

    # -------------------------------------------------------------- results

    def on_graded(self, question: Question, answer: str, grade: Grade) -> None:
        self.grading = False
        card = self.session.apply(question, answer, grade)
        rating = grade_to_rating(grade)

        lines = [f"[{_VERDICT_STYLE[grade.verdict]}]{grade.verdict.upper()}[/]"
                 f"  {grade.score:.0%} of rubric", ""]
        for p in grade.rubric_points:
            mark = "[green]HIT [/]" if p.hit else "[red]MISS[/]"
            lines.append(f"{mark} {p.point}")
            if p.comment:
                lines.append(f"       {p.comment}")
        if grade.errors:
            lines += ["", "[red]ERRORS[/]"]
            lines += [f"  - {e}" for e in grade.errors]
        if not question.provenance.trusted:
            lines += ["", "[yellow]Reference is UNVERIFIED - check this grade "
                          "against a real source before trusting it.[/]"]
        lines += ["", "[bold]Follow-up[/]", grade.followup, "",
                  f"Rated {rating.name}; next due {card.due:%Y-%m-%d}.",
                  "Ctrl+N for the next question."]
        self.query_one("#feedback", Static).update("\n".join(lines))

    def on_grade_failed(self, exc: Exception) -> None:
        self.grading = False
        self.query_one("#feedback", Static).update(
            f"[red]Grading failed[/]\n\n{type(exc).__name__}: {exc}\n\n"
            "Ctrl+S retries. Is ANTHROPIC_API_KEY set?"
        )

    def on_unmount(self) -> None:
        self.store.close()
