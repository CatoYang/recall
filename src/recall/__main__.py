"""CLI entry point: `recall` to review, `recall check` to audit the bank."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .scheduler import bank_summary
from .schema import TrustStatus
from .store import QuestionBank, ReviewStore

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS = ROOT / "questions"
DEFAULT_DB = Path(os.environ.get("RECALL_DB", ROOT / "state" / "reviews.db"))


def cmd_review(args: argparse.Namespace) -> int:
    from .app import RecallApp  # imported late so `check` works without a TTY

    RecallApp(args.questions, args.db, topic=args.topic).run()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Validate every question file and report trust composition."""
    try:
        bank = QuestionBank(args.questions)
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(bank_summary(bank))
    unverified = bank.by_status(TrustStatus.UNVERIFIED)
    if unverified:
        print("\nUnverified (not safe as an answer key until checked):")
        for q in sorted(unverified, key=lambda q: q.id):
            print(f"  {q.topic:24s} {q.id}")
    disputed = bank.by_status(TrustStatus.DISPUTED)
    if disputed:
        print("\nDisputed (never served):")
        for q in disputed:
            print(f"  {q.id}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Walk unverified questions so a human can promote them."""
    from .verify import find_file, pending, render, set_status
    from .schema import TrustStatus

    bank = QuestionBank(args.questions)
    todo = pending(bank, args.topic)
    if args.id:
        todo = [q for q in todo if q.id in args.id]
    if not todo:
        print("nothing pending verification")
        return 0

    print(f"{len(todo)} question(s) pending. For each: read the cited source, "
          f"then answer.\n")
    promoted = 0
    for q in todo:
        print(render(q))
        print()
        try:
            reply = input("  [y] verified  [n] skip  [d] dispute  [q] quit > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nstopped")
            break
        if reply == "q":
            break
        if reply == "y":
            set_status(find_file(args.questions, q.id), q.id, TrustStatus.VERIFIED)
            promoted += 1
            print("  -> verified\n")
        elif reply == "d":
            set_status(find_file(args.questions, q.id), q.id, TrustStatus.DISPUTED)
            print("  -> disputed (will not be served)\n")
        else:
            print("  -> left unverified\n")

    bank = QuestionBank(args.questions)
    print(bank_summary(bank))
    if promoted:
        print(f"{promoted} promoted - these can now be graded by the cheap tier.")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    """Measure candidate grader models against planted-error fixtures."""
    from .evaluate import load_fixtures, report, run

    fixtures = load_fixtures()
    flagged = sum(1 for f in fixtures if f.should_flag)
    calls = len(args.models) * len(fixtures)
    print(f"{len(fixtures)} fixtures ({flagged} with planted errors) "
          f"x {len(args.models)} model(s) = up to {calls} calls, "
          f"~{calls * 1250:,} tokens, ~{calls * args.delay / 60:.0f} min at "
          f"{args.delay}s spacing")
    print("cached per (fixture, model) - safe to interrupt and rerun\n")

    for m in args.models:
        print(f"{m}:")
        results = run([m], backend=args.backend, delay=args.delay, force=args.force)
    report(results, args.models, fixtures)
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Verify credentials and list models the key can actually reach."""
    from .config import backend_name, get_key

    backend = args.backend or backend_name()
    if backend == "gemini":
        key = get_key("GEMINI_API_KEY") or get_key("GOOGLE_API_KEY")
        if not key:
            print("GEMINI_API_KEY not set.\n\n"
                  "  1. Get a key at https://aistudio.google.com/apikey\n"
                  "  2. echo 'GEMINI_API_KEY=...' >> .env\n", file=sys.stderr)
            return 1
        from google import genai

        client = genai.Client(api_key=key)
        print(f"key ok (...{key[-4:]}). Models supporting generateContent:\n")
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions:
                print(f"  {m.name.removeprefix('models/')}")
        return 0

    key = get_key("ANTHROPIC_API_KEY")
    if not key:
        print("ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1
    import anthropic

    print(f"key ok (...{key[-4:]}). Models:\n")
    for m in anthropic.Anthropic(api_key=key).models.list():
        print(f"  {m.id}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = ReviewStore(args.db)
    s = store.stats()
    print(f"{s['reviews']} reviews, mean rubric score {s['mean_score']:.0%}")
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recall")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="cmd")

    p_review = sub.add_parser("review", help="start a review session (default)")
    p_review.add_argument("--topic", default=None)
    p_review.set_defaults(func=cmd_review)

    sub.add_parser("check", help="validate the bank and show trust status").set_defaults(
        func=cmd_check
    )
    sub.add_parser("stats", help="review history summary").set_defaults(func=cmd_stats)

    p_models = sub.add_parser("models", help="verify credentials, list reachable models")
    p_models.add_argument("--backend", choices=["anthropic", "gemini"], default=None)
    p_models.set_defaults(func=cmd_models)

    p_verify = sub.add_parser("verify", help="check questions against their sources")
    p_verify.add_argument("--topic", default=None)
    p_verify.add_argument("--id", nargs="*", default=None)
    p_verify.set_defaults(func=cmd_verify)

    p_eval = sub.add_parser("eval", help="measure grader models on planted errors")
    p_eval.add_argument("models", nargs="+", help="model ids to compare")
    p_eval.add_argument("--backend", choices=["anthropic", "gemini"], default=None)
    p_eval.add_argument("--delay", type=float, default=4.0,
                        help="seconds between calls (rate-limit pacing)")
    p_eval.add_argument("--force", action="store_true", help="ignore cached results")
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args(argv)
    if args.cmd is None:
        args.func, args.topic = cmd_review, None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
