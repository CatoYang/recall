"""Interactive verification: promote a question to `verified` once a human has
checked it against its cited source.

Status is edited surgically in the YAML text rather than via a load/dump
round-trip, because dumping would strip the comments and block scalars that
make the question files readable.

Nothing here can mark a question verified on its own say-so. `verified` means
a person read the source - that is the entire value of the flag, and an
automated path to setting it would make the whole provenance system
decorative.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from .schema import Question, TrustStatus
from .store import QuestionBank


class QuestionNotFound(LookupError):
    pass


def _block_bounds(text: str, question_id: str) -> tuple[int, int]:
    """Character span of one `- id: <question_id>` entry in a YAML file."""
    start = None
    for m in re.finditer(r"^- id:[ \t]*(\S+)[ \t]*$", text, flags=re.M):
        if m.group(1) == question_id:
            start = m.start()
            break
    if start is None:
        raise QuestionNotFound(question_id)
    nxt = re.search(r"^- id:", text[start + 1:], flags=re.M)
    end = start + 1 + nxt.start() if nxt else len(text)
    return start, end


def set_status(
    path: Path,
    question_id: str,
    status: TrustStatus,
    *,
    checked: datetime.date | None = None,
    source: str | None = None,
) -> None:
    """Rewrite one question's provenance in place, preserving the file."""
    text = path.read_text(encoding="utf-8")
    start, end = _block_bounds(text, question_id)
    block = text[start:end]

    if "provenance:" not in block:
        raise ValueError(f"{question_id} has no provenance block")

    new, n = re.subn(r"^(\s*)status:[ \t]*\S+[ \t]*$",
                     lambda m: f"{m.group(1)}status: {status.value}",
                     block, count=1, flags=re.M)
    if n != 1:
        raise ValueError(f"{question_id}: could not locate a single status line")

    if source:
        new, ns = re.subn(r"^(\s*)source:.*$",
                          lambda m: f'{m.group(1)}source: "{source}"',
                          new, count=1, flags=re.M)
        if ns != 1:
            raise ValueError(f"{question_id}: could not update source")

    # `checked` is the audit trail: when a human last looked.
    stamp = (checked or datetime.date.today()).isoformat()
    if re.search(r"^\s*checked:", new, flags=re.M):
        new = re.sub(r"^(\s*)checked:.*$", lambda m: f"{m.group(1)}checked: {stamp}",
                     new, count=1, flags=re.M)
    elif status is TrustStatus.VERIFIED:
        new = re.sub(r"^(\s*)status:[ \t]*\S+[ \t]*$",
                     lambda m: f"{m.group(0)}\n{m.group(1)}checked: {stamp}",
                     new, count=1, flags=re.M)

    path.write_text(text[:start] + new + text[end:], encoding="utf-8")


def find_file(root: Path, question_id: str) -> Path:
    for path in sorted(root.rglob("*.yaml")):
        try:
            _block_bounds(path.read_text(encoding="utf-8"), question_id)
            return path
        except QuestionNotFound:
            continue
    raise QuestionNotFound(question_id)


def render(q: Question, width: int = 78) -> str:
    """What a person needs on screen to check a question against a source."""
    bar = "=" * width
    lines = [bar, f"{q.id}   [{q.topic}, difficulty {q.difficulty}/5]", bar,
             "", "SOURCE TO CHECK AGAINST:", f"  {q.provenance.source or '(none given)'}"]
    if q.provenance.vault_ref:
        lines += [f"  vault (NOT evidence): {q.provenance.vault_ref}"]
    lines += ["", "QUESTION:", *[f"  {l}" for l in q.prompt.strip().splitlines()],
              "", "REFERENCE ANSWER (this is what gets trusted once verified):",
              *[f"  {l}" for l in q.answer.strip().splitlines()],
              "", "RUBRIC (this is what the grader actually scores):"]
    lines += [f"  {i}. {r}" for i, r in enumerate(q.rubric, 1)]
    return "\n".join(lines)


def pending(bank: QuestionBank, topic: str | None = None) -> list[Question]:
    qs = [q for q in bank.questions.values()
          if q.provenance.status is TrustStatus.UNVERIFIED]
    if topic:
        qs = [q for q in qs if q.topic == topic]
    return sorted(qs, key=lambda q: q.id)
