# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
.venv/bin/pytest tests/ -q                      # full suite (fast, no network)
.venv/bin/pytest tests/ -q -k rating            # single test by name
.venv/bin/recall check                          # validate the question bank
.venv/bin/recall                                # launch the TUI
```

The venv is at `.venv/`; the package is installed editable. No API key is
needed for tests or `recall check` - only for live grading.

## The invariant this project exists to protect

A question's `answer` is only an authoritative grading reference when
`provenance.status is VERIFIED`, which requires a human to have checked it
against `provenance.source`. Everything else follows from this:

- **Never mark a question `verified` that you generated.** LLM-authored
  questions ship as `unverified`. `source` means "where to check this", not
  "this was checked". `tests/test_recall.py::test_shipped_bank_claims_no_unearned_verification`
  enforces this and should not be relaxed.
- `vault_ref` points into `~/AI-Knowledge-Repository`, which is an
  LLM-generated note vault. It is a topic map, never evidence of correctness.
- `grader.py` sends a different trust preamble depending on status. For
  unverified questions it tells the model the reference may be wrong and to
  report a `REFERENCE CONFLICT` rather than mark the candidate wrong. Keep
  that branch intact when editing the prompt.

## Architecture

Strictly layered, each module depending only on the ones above it:

`schema.py` (pydantic models, no I/O) -> `store.py` (YAML bank + SQLite state)
-> `scheduler.py` (FSRS + selection) -> `grader.py` (Claude) -> `app.py` (TUI).

- **`schema.py`** - `Question`, `Provenance`, `Grade`. `Grade` is used directly
  as the structured-output format for the API call, so changing its shape
  changes the grading contract.
- **`store.py`** - questions are YAML in git (diffable content); review state
  is SQLite in `state/` (gitignored, high churn). Don't merge these.
- **`scheduler.py`** - `grade_to_rating` is the pedagogical core: **any entry
  in `grade.errors` forces `Rating.Again`**, even at a full rubric score. A
  confident false claim is a worse outcome than a gap, and the schedule must
  reflect that. Don't "fix" this to average the signals.
- **`grader.py`** - `client.messages.parse(output_format=Grade)` with
  `claude-opus-5` and adaptive thinking. Grades the rubric, not prose
  similarity to the reference answer.
- **`app.py`** - Textual. The API call runs in `@work(thread=True)`; results
  reach the UI via `call_from_thread`. Don't call the grader on the event loop.

## Conventions

- Reference answers use LaTeX in `$...$`; rubric points are plain prose (they
  are read back to you in the terminal).
- Question ids are kebab-case slugs, unique bank-wide - `store.py` raises on
  duplicates across files.
- Rich markup in `Static.update()` must use standard colour tags
  (`[green]`, `[red]`, `[yellow]`, `[bold]`). Custom tags like `[ok]` do not
  resolve. Watch for literal square brackets in interpolated text - they parse
  as markup.

## Testing

Tests never hit the network. `build_prompt` is tested directly for the two
trust branches; the live `Grader.grade` call is the one untested path. When
adding a question file, `test_shipped_question_bank_is_valid` will validate it
automatically.
