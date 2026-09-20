# recall

Spaced-repetition drilling for ML, statistics and CS. You write a free-text
answer, Claude grades it against a stored rubric, and FSRS decides when the
question comes back.

## The design in one idea

A question bank used as an answer key needs a higher standard of trust than a
set of reference notes. Notes you read skeptically; an answer key trains you.
If a wrong answer sits in the bank, the grader will mark your matching wrong
answer *correct*, and you will be actively trained into the error.

So every question carries **provenance**:

| status | meaning | how it is served |
|---|---|---|
| `verified` | a human checked the answer against the named source | graded normally, reference treated as authoritative |
| `unverified` | LLM-generated, unchecked | still asked, but the grader is told the reference may be wrong and asked to flag conflicts; the UI warns you after you answer |
| `disputed` | known or suspected wrong | never served |

This turns "reverify everything before I can start" into incremental work:
verify the small slice you actually drill, at the moment you drill it.

**Everything currently in `questions/` is `unverified`.** It was LLM-generated.
The `source` field names where to check each one - it is a pointer, not a
claim that anyone has looked.

## Usage

```bash
pip install -e .
export ANTHROPIC_API_KEY=...      # or run `ant auth login`

recall                  # start a review session
recall --topic inference
recall check            # validate the bank, list what is unverified
recall stats            # review history summary
```

Keys: `Ctrl+S` grade, `Ctrl+N` next, `Ctrl+R` reveal reference, `Ctrl+Q` quit.

## Verifying a question

1. Open the cited source and read the passage.
2. Correct the `answer` and `rubric` if they are wrong.
3. Set `status: verified` and `checked: YYYY-MM-DD`.

`recall check` fails if a question is marked `verified` without a `source`.

## Question format

```yaml
- id: kl-direction-zero-forcing        # slug, unique across the bank
  topic: information-theory
  difficulty: 4                        # 1-5
  prompt: |
    Which direction of the KL divergence is "zero-forcing"...
  answer: |
    Reverse KL, D(Q||P), is zero-forcing...
  rubric:                              # what the grader scores against
    - States reverse KL is zero-forcing and forward KL is mass-covering
    - Derives the asymmetry from which distribution the expectation is under
  provenance:
    status: unverified
    source: "Murphy, PML: An Introduction, ch. 6"
    vault_ref: "01_Foundations.../Entropy_and_KL_Divergence.md"
  tags: [kl-divergence, variational-inference]
```

Grading scores the **rubric**, not prose similarity to `answer`. That is what
stops a fluent answer that names the right concepts without the mechanics from
passing.

## Grading and scheduling

The grader separates *missing* from *wrong*. Any outright error drops the card
straight to FSRS `Again` even when every rubric point was hit - stating
something false means the wrong thing got encoded, and it should come back
soon.

Every answer you write is stored verbatim alongside the full grade, so you can
audit whether the grader has been drifting lenient over time.

## Layout

```
questions/     YAML question bank - in git, diffable, reviewable
prompts/       the standalone LLM study prompts this grew out of
state/         SQLite review history - gitignored, high churn
src/recall/    schema -> store -> scheduler -> grader -> app
```

The vault at `~/AI-Knowledge-Repository` is a **topic map and question
source**, never an answer key. `vault_ref` links back to it for context; it
never counts as verification.
