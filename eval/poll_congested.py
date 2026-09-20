"""Retry the reference-conflict fixture on models that were 503 during the
first measurement, until they answer or the budget runs out.

Writes eval/tier_results.json. Bounded: it will not poll forever.
"""
import json, sys, time, warnings, datetime
warnings.filterwarnings("ignore")
sys.path.insert(0, "src")

from pathlib import Path
from recall.evaluate import load_fixtures
from recall.grader import GeminiGrader, build_prompt
from recall.store import QuestionBank

TARGETS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"]
OUT = Path("eval/tier_results.json")
MAX_ROUNDS, GAP = 12, 180          # 12 rounds x 3 min = ~36 min ceiling

fx = [f for f in load_fixtures() if f.id == "kl-reference-and-rubric-wrong"][0]
q = QuestionBank(Path("questions")).questions[fx.question_id].model_copy(
    update={"answer": fx.reference_override, "rubric": fx.rubric_override})
assert not q.provenance.trusted, "must measure under the UNVERIFIED prompt"
prompt = build_prompt(q, fx.answer)

done = json.loads(OUT.read_text()) if OUT.exists() else {}
for rnd in range(MAX_ROUNDS):
    pending = [m for m in TARGETS if m not in done]
    if not pending:
        break
    for m in pending:
        try:
            g = GeminiGrader(model=m, fallbacks=[])     # no fallback: test THIS model
            grade = g._call(m, prompt)                  # bypass gate, keep prompt
            conflict = any("REFERENCE CONFLICT" in e.upper() for e in grade.errors)
            done[m] = {
                "verdict": grade.verdict,
                "conflict_flagged": conflict,
                "safe_for_unverified": grade.verdict == "correct" and conflict,
                "errors": grade.errors,
                "at": datetime.datetime.now().isoformat(timespec="seconds"),
                "round": rnd + 1,
            }
            print(f"[round {rnd+1}] {m}: verdict={grade.verdict} "
                  f"conflict={conflict} SAFE={done[m]['safe_for_unverified']}", flush=True)
            OUT.write_text(json.dumps(done, indent=2))
        except Exception as exc:
            print(f"[round {rnd+1}] {m}: {str(exc)[:60]}", flush=True)
        time.sleep(5)
    if [m for m in TARGETS if m not in done]:
        time.sleep(GAP)

still = [m for m in TARGETS if m not in done]
print(f"\nDONE. resolved={sorted(done)} unresolved={still}", flush=True)
