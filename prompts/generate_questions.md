# Generating questions with Gemini

Paste the block below into Gemini (Antigravity, AI Studio, or gemini.google.com
— whichever you have open), fill in the four `{...}` placeholders, and paste
in a real excerpt. Save what comes back as
`questions/{domain}/{topic}.yaml` and run:

```bash
cd ~/recall && .venv/bin/recall check
```

That's local schema validation — no LLM call, no cost. If it reports an
error, paste the error text back into the same Gemini conversation and ask it
to fix the YAML; don't hand-debug YAML indentation yourself unless you want
to.

## Why "paste an excerpt" instead of "write me questions about X"

A model asked to generate questions from its own memory can be confidently
wrong in ways that are hard to catch - that's exactly what happened twice
already in the source vault this tool grew out of (a mislabelled KL-divergence
direction, an "infinite variance" claim about the Cauchy distribution that's
actually *undefined*). A model asked to extract questions from a paragraph
you hand it is anchored to that paragraph - you have something concrete to
re-read and compare against, and the model has much less room to invent.

The questions still ship `unverified` either way (nothing here signs off on
correctness - see `../CLAUDE.md`), but grounding the generation in a real
excerpt is a meaningfully safer starting point than free generation.

## Difficulty ladder

The existing bank (`questions/stats/`) sits at 3-4: multi-step derivations,
graduate-level. Don't force yourself onto that ladder rung immediately - ask
for 1-2 while a topic is new, and let it climb as the topic does.

| difficulty | what it tests | example shape |
|---|---|---|
| 1 | a single definition or fact, stated correctly | "What does X mean?" |
| 2 | one mechanism, no multi-step reasoning | "Why does X happen?" |
| 3 | applying a concept to a new case | "What happens to X if Y changes?" |
| 4 | a derivation or multi-step chain of reasoning | "Derive why X implies Y" |
| 5 | synthesis across multiple concepts | "Contrast X and Y, then show Z" |

`recall` has no difficulty filter yet - the lever you actually have is
`topic`. Give your easy questions their own topic name (e.g. a `-basics`
suffix) and drill just that with `recall review --topic <name>` until you're
ready to fold it back in with the harder set.

---

## The prompt (copy from here down)

```
Role: Technical flashcard author for an advanced spaced-repetition drilling
tool. You will extract questions strictly from the excerpt I provide - do not
add facts, examples, or claims that are not present in or directly derivable
from it. If the excerpt doesn't support a claim, leave it out rather than
filling the gap from general knowledge.

Task: produce {count} questions on {topic} at difficulty {difficulty}/5
(see ladder: 1=single definition, 2=one mechanism, 3=applying a concept to a
new case, 4=a derivation/multi-step chain, 5=synthesis across concepts).

Excerpt (the ONLY source of truth - do not go beyond it):
"""
{paste the excerpt here}
"""

Output format: a single YAML block, valid as a list of entries matching this
schema exactly. Follow it field-for-field, do not add or omit fields, do not
add commentary before or after the YAML block.

- id: <kebab-case-slug, no spaces, unique, descriptive of the specific question>
  topic: {topic}
  difficulty: {difficulty}
  prompt: |
    <the question, as you'd ask a student. Multi-line with | if long.>
  answer: |
    <the full correct answer, self-contained. This is what a grader will
    compare a student's response against, so it needs to actually be
    correct and complete relative to the excerpt - not just gesture at the
    right area.>
  rubric:
    - <one specific, checkable point the answer must hit - not "mentions X"
      but "states the mechanism/direction/condition that makes X true">
    - <a second point, same standard>
    - <as many as the answer actually has distinct claims - usually 2-5>
  provenance:
    status: unverified
    source: "<name the actual book/paper/course this excerpt is from, with
      section/chapter if you know it. If I didn't tell you, write 'excerpt
      provided by user, no citation given' - do not invent a citation.>"
  tags: [<2-4 short lowercase tags>]

Rules:
- Every rubric point must be something the ANSWER actually demonstrates, not
  a restatement of the question.
- Do not write a rubric point for anything not covered in `answer`.
- `provenance.source` must never be fabricated. If you don't know the exact
  section, say so rather than guessing a plausible-sounding one.
- Never set `status` to anything other than `unverified`. You are not
  authorized to mark your own output verified - a human has to do that
  against a real source, later, separately.
- Prefer 2-4 rubric points per question. More than that usually means the
  question is really two questions - split it instead.
```
