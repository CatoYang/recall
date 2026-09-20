"""Measure how well a candidate grader model actually grades.

The headline metric is the **false-correct rate**: how often the grader passes
an answer containing a planted error. That is the failure that hurts, because
FSRS then schedules the card months out and the misconception is reinforced
invisibly. A grader that is too harsh is merely irritating - you notice, you
check the source, you correct it.

Runs are cached per (fixture, model) in results.json, so hitting a rate limit
costs you nothing: rerun and it resumes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .grader import make_grader
from .schema import Grade
from .store import QuestionBank

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
FIXTURES = EVAL_DIR / "fixtures.yaml"
RESULTS = EVAL_DIR / "results.json"


@dataclass
class Fixture:
    id: str
    question_id: str
    answer: str
    expect: str                       # correct | partial | incorrect
    subtlety: str = "none"
    planted_errors: list[str] = field(default_factory=list)
    #: Replace the stored reference answer with a deliberately WRONG one.
    #: Tests whether the grader defers to a bad reference or flags the
    #: conflict - the behaviour the `unverified` provenance path depends on.
    reference_override: str | None = None
    #: Also corrupt the rubric. Without this the rubric still carries the
    #: truth and the grader can score correctly without ever consulting its
    #: own knowledge - which makes a reference-conflict test vacuous.
    rubric_override: list[str] | None = None
    expect_conflict: bool = False

    @property
    def should_flag(self) -> bool:
        return bool(self.planted_errors)


def load_fixtures(path: Path = FIXTURES) -> list[Fixture]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Fixture(**entry) for entry in raw]


def _load_results() -> dict:
    if RESULTS.exists():
        return json.loads(RESULTS.read_text(encoding="utf-8"))
    return {}


def _save_results(data: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run(
    models: list[str],
    *,
    backend: str | None = None,
    bank: QuestionBank | None = None,
    fixtures: list[Fixture] | None = None,
    delay: float = 4.0,
    force: bool = False,
    log=print,
) -> dict:
    """Grade every fixture with every model, caching as it goes.

    `delay` paces requests to stay under per-minute rate limits; at the
    default 4s that is 15 requests/minute.
    """
    bank = bank or QuestionBank(Path(EVAL_DIR).parent / "questions")
    fixtures = fixtures or load_fixtures()
    results = {} if force else _load_results()

    for model in models:
        grader = make_grader(backend=backend, model=model)
        for fx in fixtures:
            key = f"{model}::{fx.id}"
            if key in results:
                continue
            question = bank.questions[fx.question_id]
            if fx.reference_override or fx.rubric_override:
                upd = {}
                if fx.reference_override:
                    upd["answer"] = fx.reference_override
                if fx.rubric_override:
                    upd["rubric"] = fx.rubric_override
                question = question.model_copy(update=upd)
            try:
                grade = grader.grade(question, fx.answer)
            except Exception as exc:
                log(f"  {fx.id:26s} FAILED  {type(exc).__name__}: {str(exc)[:70]}")
                results[key] = {"error": f"{type(exc).__name__}: {exc}"}
                _save_results(results)
                continue
            used = getattr(grader, "used_model", model)
            results[key] = {
                "model_requested": model,
                "model_used": used,
                "verdict": grade.verdict,
                "score": grade.score,
                "n_errors": len(grade.errors),
                "errors": grade.errors,
            }
            _save_results(results)          # checkpoint every call
            drift = "" if used == model else f"  (answered by {used})"
            log(f"  {fx.id:26s} {grade.verdict:9s} errs={len(grade.errors)}{drift}")
            time.sleep(delay)
    return results


def score(results: dict, model: str, fixtures: list[Fixture]) -> dict:
    """Summarise one model's behaviour on the fixture set."""
    by_id = {f.id: f for f in fixtures}
    false_correct, false_incorrect, caught, missed, errored = [], [], 0, 0, 0
    off_model = 0

    for fx in fixtures:
        r = results.get(f"{model}::{fx.id}")
        if r is None:
            continue
        if "error" in r:
            errored += 1
            continue
        if r.get("model_used") != model:
            off_model += 1           # answered by a fallback; excluded below
            continue

        passed = r["verdict"] == "correct"
        if fx.should_flag:
            # the metric that matters: did a planted error slip through?
            if passed or r["n_errors"] == 0:
                false_correct.append(fx.id)
                missed += 1
            else:
                caught += 1
        elif fx.expect == "correct" and not passed:
            false_incorrect.append(fx.id)

    flagged = [f for f in fixtures if f.should_flag]
    return {
        "model": model,
        "graded": sum(1 for f in fixtures
                      if (r := results.get(f"{model}::{f.id}")) and "error" not in r
                      and r.get("model_used") == model),
        "api_errors": errored,
        "answered_by_fallback": off_model,
        "planted_total": len(flagged),
        "planted_caught": caught,
        "false_correct": false_correct,
        "false_correct_rate": len(false_correct) / len(flagged) if flagged else 0.0,
        "false_incorrect": false_incorrect,
    }


def report(results: dict, models: list[str], fixtures: list[Fixture], log=print) -> None:
    log("")
    log(f"{'model':26s} {'caught':>8s} {'FALSE-CORRECT':>14s} {'false-incorr':>13s}")
    log("-" * 66)
    rows = [score(results, m, fixtures) for m in models]
    for s in sorted(rows, key=lambda s: s["false_correct_rate"]):
        caught = f"{s['planted_caught']}/{s['planted_total']}"
        fc = f"{len(s['false_correct'])} ({s['false_correct_rate']:.0%})"
        log(f"{s['model']:26s} {caught:>8s} {fc:>14s} {len(s['false_incorrect']):>13d}")

    log("")
    log("false-correct = a planted error slipped through. This is the failure")
    log("that matters: the card gets scheduled out and the error is reinforced.")
    for s in rows:
        if s["false_correct"]:
            log(f"\n  {s['model']} missed:")
            by_id = {f.id: f for f in fixtures}
            for fid in s["false_correct"]:
                log(f"    - {fid} [{by_id[fid].subtlety}]")
        if s["answered_by_fallback"]:
            log(f"  {s['model']}: {s['answered_by_fallback']} fixture(s) answered by a "
                f"fallback model, excluded from its score")
