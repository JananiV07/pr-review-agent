"""Configuration for the PR Review Agent.

This module centralizes the few settings that are likely to be tuned — the
Gemini model, the output token budget, and a couple of behavioral knobs —
along with the system prompt that defines *how* the model reviews a pull
request. Keeping these here means :mod:`agent` can stay focused on
orchestration logic.
"""

# ---------------------------------------------------------------------------
# Model settings
# ---------------------------------------------------------------------------

# The Gemini model used to perform the review. ``gemini-2.5-flash`` is fast,
# cost-effective, and capable enough for code review. For deeper reviews of
# tricky changes you can switch to ``gemini-2.5-pro``.
MODEL: str = "gemini-2.5-flash"

# Maximum number of tokens the model may generate for a single review. Gemini
# 2.5 models also spend "thinking" tokens against this budget, so this is kept
# generous enough to leave room for both the reasoning and the JSON output.
MAX_TOKENS: int = 8192

# ---------------------------------------------------------------------------
# Behavioral knobs
# ---------------------------------------------------------------------------

# Soft ceiling (in characters) on the combined diff sent to the model. Gemini
# has a large context window, but extremely large diffs cost more and rarely
# review well in a single pass. When this is exceeded, the agent warns the user
# instead of silently truncating.
MAX_DIFF_CHARS: int = 200_000

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

# The system prompt is the stable instruction set sent ahead of every PR. The
# response *shape* is enforced separately via a JSON response schema (see
# agent.py), so this prompt focuses on review quality and what each field means.
SYSTEM_PROMPT: str = """\
You are an experienced senior software engineer performing a thorough but \
pragmatic code review of a GitHub pull request.

You will be given the PR title, description, and the unified diff of all changed \
files. Review only what the diff shows — do not assume the existence or behavior \
of code you cannot see.

Return your review as JSON matching the provided schema, where each field means:

- summary: A concise, neutral description of what the PR actually does.
- issues: Concrete problems only — genuine bugs, logic errors, or security \
concerns. For each, reference the file and the most relevant line (use the \
new-file line number from the diff's hunk header when visible, otherwise your \
best estimate or "N/A"), and classify its severity. Do NOT list stylistic \
preferences here.
- suggestions: Non-blocking improvements (readability, tests, naming, edge \
cases). These must never duplicate anything reported under issues.
- verdict: One of "Approve", "Request Changes", or "Needs Discussion". Use \
"Request Changes" only when there is at least one real bug or security issue; \
use "Needs Discussion" when the intent or design is genuinely unclear; \
otherwise "Approve".
- verdict_reasoning: One or two sentences justifying the verdict.

Always populate every field. Be specific and cite concrete lines. Prefer a \
short, high-signal review over an exhaustive one."""
