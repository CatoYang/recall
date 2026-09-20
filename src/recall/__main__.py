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

    args = parser.parse_args(argv)
    if args.cmd is None:
        args.func, args.topic = cmd_review, None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
