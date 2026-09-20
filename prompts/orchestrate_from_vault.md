# Unattended generation from the vault (Antigravity / Gemini)

For a long unsupervised run: point Antigravity at the vault, let it walk
topics on its own, and give it a real validation loop so mistakes get caught
*during* the run instead of discovered after.

This is a looser pattern than `generate_questions.md` (which works from one
excerpt you hand-pick). Here the model is choosing its own excerpts by
reading whole notes autonomously - that's more coverage per hour but weaker
grounding, so the prompt below adds a rule the excerpt-based one doesn't
need: permission to distrust the source.

## Setup - point it at the live files, no git round-trip

WSL2 exposes its filesystem to Windows directly. Give Antigravity these two
paths as its workspace:

```
\\wsl.localhost\Ubuntu\home\cato\recall                    <- write questions here
\\wsl.localhost\Ubuntu\home\cato\AI-Knowledge-Repository   <- read source notes from here
```

(If `\\wsl.localhost\...` doesn't resolve, try `\\wsl$\...` instead - same
target, older alias.)

Give it the validation command too - this is what turns a 2-hour blind run
into one with real per-file feedback. If Antigravity has a terminal, it can
run:

```
wsl.exe -d Ubuntu -- bash -lc "cd ~/recall && .venv/bin/python -m recall check"
```

That's the actual pydantic schema the tool uses, not a guess at the format -
same check I run by hand. Confirmed working from the WSL side before this
run started.

## What to tell it about the vault it's about to read

**The vault is LLM-generated and known to contain errors** - it says so in
its own `CLAUDE.md`, and there's at least one confirmed live example: the
note at `01_Foundations_Probability_and_Information_Theory/Information_Theory/Entropy_and_KL_Divergence.md`,
line 39, labels forward KL divergence "zero-forcing" - backwards, it's
mass-covering; reverse KL is the zero-forcing one. A model told to extract
*only* what the source says would transcribe that straight into a new
question. Give it permission to do the opposite: check each claim against
its own knowledge, and if a vault note conflicts with what it's confident is
correct, either correct it in the generated answer (noting the correction in
`source`, e.g. `"vault note states X; corrected to Y - see [reason]"`) or
skip that specific question rather than propagate it.

This is a different instruction from the excerpt-based prompt on purpose:
there, the excerpt IS the ground truth because you chose it. Here, the vault
is a topic map that happens to also contain draft prose, and prose from an
unverified vault is not automatically ground truth just because it's the
source text being read.

## Scope and budget, so it self-limits

285 files is too much for one unattended run to turn into reviewable
output - don't let it try to cover the whole vault. Give it a priority order
and a stopping condition instead of open-ended "do the whole thing":

1. Priority: the numbered DAG (`01_` through `08_`) over the legacy trees
   (`AI-Knowledge-Repository/` nested copy, `Programing Knowledge/`, etc.) -
   the DAG is the consolidated, current version of the same material.
2. Within the DAG, prefer notes with a clear `## Prerequisites` header and a
   single well-scoped topic over sprawling ones - easier to extract a tight
   rubric from.
3. One YAML file per note, saved as
   `questions/<domain>/<topic-matching-note-filename>.yaml`.
4. Stop after roughly 90 minutes of work OR 20 files, whichever comes
   first - leaving a clear log of what was covered so the next run (or you,
   by hand) knows where to pick up.
5. Difficulty: default to 1-2 (single definition / one mechanism - see the
   ladder in `generate_questions.md`) unless a note is itself introductory
   in tone, then 2-3. Nothing above 3 without being asked - the existing
   bank already covers 3-4 on the topics it touches.

## The orchestration prompt

```
Role: Technical flashcard author for an advanced spaced-repetition drilling
tool, running unattended for up to 90 minutes. You will read notes from a
vault and generate question files from them, validating each one before
moving to the next.

Workspace:
- Read source notes from: \\wsl.localhost\Ubuntu\home\cato\AI-Knowledge-Repository
- Write question files to: \\wsl.localhost\Ubuntu\home\cato\recall\questions\<domain>\<topic>.yaml
- After writing each file, validate it by running in a terminal:
  wsl.exe -d Ubuntu -- bash -lc "cd ~/recall && .venv/bin/python -m recall check"
  If it reports an error, fix the specific file responsible before moving on.
  Do not proceed to the next note with a known-broken file left behind.

Priority order:
1. Walk the numbered directories 01_ through 08_ first. Only touch
   AI-Knowledge-Repository/, Programing Knowledge/, or other legacy trees if
   you run out of DAG notes to cover.
2. Prefer notes with a clear single topic and a `## Prerequisites` header
   over long sprawling ones.
3. Skip notes you've effectively already covered from a different section -
   check the ids already present in questions/ before writing new ones with
   overlapping content.

Stop condition: stop after roughly 90 minutes OR 20 files written, whichever
comes first. When you stop, write a short summary to
questions/_generation_log.md listing: which notes you covered, which you
skipped and why, and any vault content you flagged as wrong (see below).
Append to that file rather than overwriting it if it already exists.

Per note, do this:
1. Read the note in full.
2. IMPORTANT: the vault is LLM-generated and known to contain errors - do
   not transcribe a claim you have reason to doubt. If something in the note
   conflicts with what you're confident is correct, either write the
   corrected version and say so in `source`, or skip that specific question.
   Known example: 01_Foundations_Probability_and_Information_Theory/
   Information_Theory/Entropy_and_KL_Divergence.md line 39 calls forward KL
   "zero-forcing" - it is backwards, forward KL is mass-covering.
3. Pick difficulty 1-2 by default (single definition / one mechanism), 2-3
   if the note itself is introductory. Nothing above 3.
4. Generate 3-6 questions from the note - fewer if the note doesn't support
   that many genuinely distinct, checkable claims. Do not pad.
5. Write them as a YAML list matching this schema exactly (no extra fields,
   no commentary outside the YAML):

- id: <kebab-case-slug, unique across the ENTIRE questions/ tree - check
    existing files first, prefix with the topic if there's any collision risk>
  topic: <short kebab-case topic name>
  difficulty: <1-3>
  prompt: |
    <the question>
  answer: |
    <the full correct answer, self-contained and actually correct - this is
    what a grader will compare a student's response against>
  rubric:
    - <one specific, checkable point the answer demonstrates>
    - <a second point, same standard - usually 2-4 total>
  provenance:
    status: unverified
    source: "vault note: <relative path to the note>. <If you corrected
      something the note got wrong, say what and why here.>"
    vault_ref: "<same relative path>"
  tags: [<2-4 short lowercase tags>]

6. Save as questions/<domain>/<topic>.yaml, run the validation command,
   fix any reported error, then move to the next note.

Never set status to anything other than unverified. You are not authorized
to mark your own output verified.
```

## When you're back

```bash
cd ~/recall
.venv/bin/recall check                      # final tally: how many, what topics
cat questions/_generation_log.md             # what it covered, what it flagged as wrong in the vault
git status                                   # review before committing
git diff --stat
```

Skim `_generation_log.md` first, especially anything it flagged as a vault
correction - those are worth a second look since they're the model
overruling its own source rather than just reporting it.
