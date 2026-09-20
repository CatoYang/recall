from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fsrs import Rating
from pydantic import ValidationError

from recall.grader import build_prompt
from recall.scheduler import ReviewSession, grade_to_rating
from recall.schema import Grade, Provenance, Question, RubricPoint, TrustStatus
from recall.store import QuestionBank, ReviewStore

QUESTIONS_DIR = Path(__file__).resolve().parents[1] / "questions"


def make_question(qid="q1", status=TrustStatus.UNVERIFIED, source=None, topic="t"):
    return Question(
        id=qid,
        topic=topic,
        prompt="p",
        answer="a",
        rubric=["r1", "r2"],
        provenance=Provenance(status=status, source=source),
    )


def make_grade(verdict="correct", hits=(True, True), errors=()):
    return Grade(
        rubric_points=[RubricPoint(point=f"r{i}", hit=h, comment="")
                       for i, h in enumerate(hits)],
        errors=list(errors),
        verdict=verdict,
        followup="f",
    )


# ------------------------------------------------------------------ schema

def test_verified_question_requires_a_source():
    with pytest.raises(ValidationError):
        Provenance(status=TrustStatus.VERIFIED)
    Provenance(status=TrustStatus.VERIFIED, source="Murphy PML SS6.2")


def test_disputed_questions_are_not_servable():
    assert not make_question(status=TrustStatus.DISPUTED).servable
    assert make_question(status=TrustStatus.UNVERIFIED).servable


def test_score_is_fraction_of_rubric_hit():
    assert make_grade(hits=(True, True)).score == 1.0
    assert make_grade(hits=(True, False)).score == 0.5
    assert make_grade(hits=(False, False)).score == 0.0


# --------------------------------------------------------------- scheduling

def test_any_error_forces_again_even_with_full_rubric():
    """A confident wrong claim must not be scheduled as if it went well."""
    g = make_grade(verdict="correct", hits=(True, True), errors=["said forward KL is zero-forcing"])
    assert grade_to_rating(g) is Rating.Again


def test_rating_mapping():
    assert grade_to_rating(make_grade("correct", (True, True))) is Rating.Good
    assert grade_to_rating(make_grade("partial", (True, False))) is Rating.Hard
    assert grade_to_rating(make_grade("incorrect", (False, False))) is Rating.Again


def test_partial_rubric_never_rates_good():
    g = make_grade(verdict="correct", hits=(True, False))
    assert grade_to_rating(g) is Rating.Hard


# -------------------------------------------------------------------- store

def test_review_roundtrip_and_scheduling(tmp_path):
    store = ReviewStore(tmp_path / "r.db")
    bank = QuestionBank.__new__(QuestionBank)
    q = make_question()
    bank.questions = {q.id: q}
    bank.root = tmp_path

    session = ReviewSession(bank, store)
    assert [x.id for x in session.queue()] == ["q1"]  # unseen -> due

    card = session.apply(q, "my answer", make_grade())
    assert card.due > datetime.now(timezone.utc)
    assert "q1" not in store.due_ids()  # scheduled into the future

    rows = store.history("q1")
    assert len(rows) == 1
    assert rows[0]["answer"] == "my answer"  # answers kept verbatim for audit
    assert store.stats()["reviews"] == 1
    store.close()


def test_verified_questions_sort_ahead_of_unverified(tmp_path):
    store = ReviewStore(tmp_path / "r.db")
    bank = QuestionBank.__new__(QuestionBank)
    unver = make_question("u1")
    ver = make_question("v1", TrustStatus.VERIFIED, "Murphy SS6.2")
    bank.questions = {"u1": unver, "v1": ver}
    bank.root = tmp_path

    session = ReviewSession(bank, store)
    assert [q.id for q in session.queue()] == ["v1", "u1"]
    store.close()


def test_include_unverified_false_filters_them(tmp_path):
    store = ReviewStore(tmp_path / "r.db")
    bank = QuestionBank.__new__(QuestionBank)
    bank.questions = {
        "u1": make_question("u1"),
        "v1": make_question("v1", TrustStatus.VERIFIED, "src"),
    }
    bank.root = tmp_path
    session = ReviewSession(bank, store, include_unverified=False)
    assert [q.id for q in session.queue()] == ["v1"]
    store.close()


# ------------------------------------------------------------------ grader

def test_prompt_warns_when_reference_is_unverified():
    p = build_prompt(make_question(), "my answer")
    assert "has NOT been verified" in p
    assert "REFERENCE CONFLICT" in p


def test_prompt_marks_verified_reference_authoritative():
    q = make_question(status=TrustStatus.VERIFIED, source="Murphy PML SS6.2")
    p = build_prompt(q, "my answer")
    assert "Murphy PML SS6.2" in p
    assert "authoritative" in p


# ------------------------------------------------------- the shipped bank

def test_shipped_question_bank_is_valid():
    bank = QuestionBank(QUESTIONS_DIR)
    assert len(bank) >= 10
    for q in bank.questions.values():
        assert q.rubric, f"{q.id} has no rubric"
        assert q.provenance.source, f"{q.id} should name where to verify it"


def test_shipped_bank_claims_no_unearned_verification():
    """Nothing ships as `verified` - no human has checked these yet."""
    bank = QuestionBank(QUESTIONS_DIR)
    assert not bank.by_status(TrustStatus.VERIFIED)


# ------------------------------------------------------------ backend wiring

def test_unknown_backend_rejected():
    from recall.grader import make_grader
    with pytest.raises(ValueError, match="unknown backend"):
        make_grader(backend="mistral")


def test_missing_credential_is_actionable(monkeypatch):
    """A missing key must say where to get one, not fail deep in an SDK."""
    from recall.grader import MissingCredential, make_grader
    import recall.config as cfg

    monkeypatch.setattr(cfg, "_loaded", True)          # skip .env
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(MissingCredential, match="aistudio.google.com"):
        make_grader(backend="gemini")


def test_both_backends_share_one_prompt():
    """Backends must not drift apart - the prompt is the graded contract.

    Checks the whole class, not one method: where in the class the prompt is
    assembled is an implementation detail, that it is the shared one is not.
    """
    from recall.grader import AnthropicGrader, GeminiGrader
    import inspect
    for cls in (AnthropicGrader, GeminiGrader):
        src = inspect.getsource(cls)
        assert "build_prompt(" in src, f"{cls.__name__} builds its own prompt"
        assert "SYSTEM" in src, f"{cls.__name__} uses its own system prompt"


# ---------------------------------------------------------- gemini fallback

class _FakeGemini:
    """Fails the first N models with a 503, then succeeds."""

    def __init__(self, fail_models):
        self.fail_models = set(fail_models)
        self.tried = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.tried.append(model)
        if model in self.fail_models:
            raise RuntimeError("503 UNAVAILABLE. model is overloaded")
        return type("R", (), {"parsed": make_grade("incorrect", (False, False))})()


def _verified_q(qid="q1"):
    return make_question(qid, TrustStatus.VERIFIED, "Murphy PML SS6.2")


def test_gemini_falls_back_past_congested_models():
    """Pure fallback mechanics, on a verified question (no capability gate)."""
    from recall.grader import GeminiGrader

    fake = _FakeGemini({"gemini-3.8-flash", "gemini-3.5-flash"})
    g = GeminiGrader(model="gemini-3.8-flash", client=fake,
                     fallbacks=["gemini-3.5-flash", "gemini-3.5-flash-lite"])
    grade = g.grade(_verified_q(), "an answer")
    assert grade.verdict == "incorrect"
    assert g.used_model == "gemini-3.5-flash-lite"   # what actually answered
    assert fake.tried.count("gemini-3.8-flash") == 2  # retried once before moving on


def test_gemini_does_not_retry_non_transient_errors():
    """A bad key or malformed request must fail fast, not burn the chain."""
    from recall.grader import GeminiGrader

    class Boom:
        models = None
        def generate_content(self, **kw):
            raise RuntimeError("400 INVALID_ARGUMENT: bad schema")
    boom = Boom(); boom.models = boom

    g = GeminiGrader(model="gemini-3.8-flash", client=boom, fallbacks=[])
    with pytest.raises(RuntimeError, match="INVALID_ARGUMENT"):
        g.grade(_verified_q(), "a")


def test_all_models_exhausted_gives_actionable_error():
    from recall.grader import GeminiGrader

    fake = _FakeGemini({"gemini-3.8-flash", "gemini-3.5-flash"})
    g = GeminiGrader(model="gemini-3.8-flash", client=fake,
                     fallbacks=["gemini-3.5-flash"])
    with pytest.raises(RuntimeError, match="congested"):
        g.grade(_verified_q(), "a")


# ------------------------------------------- unverified needs a capable model

def test_unverified_question_refuses_a_non_conflict_capable_model():
    """Measured: flash-lite marks a CORRECT answer wrong when the reference is
    wrong, and never reports the conflict. Grading an unverified question with
    it would train the misconception in, so it must refuse rather than degrade.
    See eval/fixtures.yaml::kl-reference-and-rubric-wrong."""
    from recall.grader import GeminiGrader, NoCapableModel

    fake = _FakeGemini(set())
    g = GeminiGrader(model="gemini-3.5-flash-lite", client=fake, fallbacks=[])
    with pytest.raises(NoCapableModel, match="unverified"):
        g.grade(make_question(), "a")           # unverified by default
    assert fake.tried == []                      # refused before spending a call


def test_unverified_question_never_degrades_below_capable_tier():
    from recall.grader import GeminiGrader

    fake = _FakeGemini({"gemini-3.8-flash"})     # capable one is congested
    g = GeminiGrader(model="gemini-3.8-flash", client=fake,
                     fallbacks=["gemini-3.5-flash-lite"])
    with pytest.raises(RuntimeError, match="unverified"):
        g.grade(make_question(), "a")
    assert "gemini-3.5-flash-lite" not in fake.tried   # the whole point


def test_verified_question_may_use_the_cheap_tier():
    from recall.grader import GeminiGrader

    fake = _FakeGemini(set())
    g = GeminiGrader(model="gemini-3.5-flash-lite", client=fake, fallbacks=[])
    assert g.grade(_verified_q(), "a").verdict == "incorrect"
    assert fake.tried == ["gemini-3.5-flash-lite"]


# ------------------------------------------------------------- verification

VERIFY_YAML = '''# a comment that must survive
- id: alpha
  topic: t
  prompt: |
    multi
    line
  answer: |
    a
  rubric:
    - r1
  provenance:
    status: unverified
    source: "Murphy SS6.2"
  tags: [x]

- id: beta
  topic: t
  prompt: |
    p
  answer: |
    a
  rubric:
    - r1
  provenance:
    status: unverified
    source: "Cover SS2.3"
'''


def test_set_status_promotes_only_the_named_question(tmp_path):
    from recall.verify import set_status
    from recall.schema import TrustStatus
    import datetime, yaml as y

    f = tmp_path / "q.yaml"; f.write_text(VERIFY_YAML)
    set_status(f, "alpha", TrustStatus.VERIFIED, checked=datetime.date(2026, 9, 20))
    out = f.read_text()

    assert "# a comment that must survive" in out      # formatting preserved
    assert "multi\n    line" in out                     # block scalars intact
    data = {d["id"]: d for d in y.safe_load(out)}
    assert data["alpha"]["provenance"]["status"] == "verified"
    assert str(data["alpha"]["provenance"]["checked"]) == "2026-09-20"
    assert data["beta"]["provenance"]["status"] == "unverified"   # untouched
    assert "checked" not in data["beta"]["provenance"]


def test_set_status_round_trips_through_the_loader(tmp_path):
    from recall.verify import set_status
    from recall.schema import TrustStatus
    from recall.store import QuestionBank

    f = tmp_path / "q.yaml"; f.write_text(VERIFY_YAML)
    set_status(f, "beta", TrustStatus.DISPUTED)
    bank = QuestionBank(tmp_path)
    assert bank.questions["beta"].provenance.status is TrustStatus.DISPUTED
    assert not bank.questions["beta"].servable
    assert bank.questions["alpha"].servable


def test_set_status_rejects_unknown_id(tmp_path):
    from recall.verify import QuestionNotFound, set_status
    from recall.schema import TrustStatus

    f = tmp_path / "q.yaml"; f.write_text(VERIFY_YAML)
    with pytest.raises(QuestionNotFound):
        set_status(f, "gamma", TrustStatus.VERIFIED)
