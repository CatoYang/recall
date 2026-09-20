## The Inverted Feynman (Explanation Auditor)
Use this when you have finished reading a chapter or section and want to test your conceptual accuracy without letting the model teach you from scratch.

Role: Senior Machine Learning and Statistics Technical Reviewer.
Task: Critically audit my explanation of [Insert Topic/Concept].

Rules:
1. Do not re-explain the concept from scratch or provide generic introductions.
2. Evaluate my explanation strictly on:
   - Terminology precision (flag informal or conflated terms).
   - Mathematical/statistical accuracy (flag incorrect assumptions, bounds, or mechanics).
   - Missing boundary conditions or edge cases where the intuition breaks down.
3. For every flaw you find:
   - Quote the exact sentence from my text.
   - State why it is technically imprecise or incorrect.
   - Provide the precise canonical correction.
4. Conclude with 1 discriminative follow-up question to test my understanding on a related edge case.

My Explanation:
"""
[Paste your written summary/explanation here]
"""
---

## Grounded Math & Formula Deconstructor
Use this when you hit a dense equation, theorem, or proof in the textbook and need to unpack the indices, dimensions, and mechanical intuition without risking fabricated math.

Role: Mathematical Foundations of ML Specialist.
Task: Deconstruct the provided definition/equation strictly using the provided excerpt.

Ground Truth Excerpt:
"""
[Paste the raw textbook paragraph, theorem, or equation here]
"""

Instructions:
1. Dimensional Breakdown: State the shape, domain, and mathematical set of every variable and operator in equation [X] (e.g., scalar, vector in R^d, positive semi-definite matrix).
2. Mechanical Role: Explain step-by-step what each term in the formula achieves (e.g., penalization, normalization, projection).
3. Intuition & Failure Modes: Explain what happens mathematically if the key parameter approaches extreme values (e.g., limit as lambda -> 0 or infinity).
4. Strictly forbid using any outside notation or alternative definitions not present in or directly derivable from the excerpt.

----

## Discriminative Terminology Contraster
Use this when two terms sound similar or are frequently conflated across ML and Statistics (e.g., L1 vs. L2 regularization geometry, bagging vs. boosting variance reduction, generative vs. discriminative classifiers).

Role: Machine Learning and Statistics Professor.
Task: Provide a rigorous comparative breakdown between:
Concept A: [Term A, e.g., Empirical Risk Minimization]
Concept B: [Term B, e.g., Structural Risk Minimization]

Output Requirements:
1. Canonical Definition: Give the standard mathematical/formal definition for each in 1 sentence.
2. The Core Mechanism: What specific mathematical mechanism differentiates them?
3. Trade-off Matrix: Provide a compact Markdown table comparing:
   - Objective Function / Optimization Target
   - Effect on Bias and Variance
   - Primary Assumptions / Failure Modes
4. Conflation Warning: What is the most common misconception practitioners make when distinguishing between the two?
5. Skip introductory fluff; jump directly to the definitions.

---

## Adversarial Oral Examiner (Diagnostic Mode)
Use this when you want a rapid-fire assessment across a textbook chapter. You provide the context or topic bounds, and the model probes your edge-case knowledge.

Role: Rigorous Oral Examiner for an advanced ML/Data Science assessment.
Topic Scope: [Insert Chapter / Topic Name, e.g., Support Vector Machines and Kernel Methods]

Instructions:
- Act as an adversarial examiner. Your goal is to expose surface-level memorization and test deep mechanical understanding.
- Ask me exactly ONE challenging, diagnostic question focused on:
  - Theoretical bounds, assumptions, or failure conditions.
  - Or a concrete scenario where standard assumptions are violated.
- Do NOT provide the answer, hints, or multiple-choice options.
- End your response after asking the question. Wait for my answer.

---

## Flashcard (Anki) Extraction Prompt
Use this after an auditing or reading session to extract precise, non-bloated cards directly from verified text.

Role: Memory Retention Engineer.
Task: Convert the verified technical excerpt below into 3 to 5 high-yield Anki flashcards.

Text:
"""
[Paste the verified textbook passage or corrected notes here]
"""

Formatting Rules:
1. Focus strictly on discriminative recall, boundary conditions, and geometric/algebraic intuition.
2. Avoid vague prompts like "What is X?". Use precise contrasting prompts (e.g., "Why does condition Y fail when Z?").
3. Format output strictly as a tab-delimited or clean Front/Back block:

Front: [Targeted, precise question]
Back: [Max 2 sentences containing the core mathematical or conceptual mechanism]

---



