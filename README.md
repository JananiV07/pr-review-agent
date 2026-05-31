<div align="center">

# 🔍 pr-review-agent

**An AI pull-request reviewer for your terminal — point it at a GitHub PR, get a structured, opinionated code review powered by Google Gemini.**

[![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Gemini](https://img.shields.io/badge/LLM-Gemini%202.5-8E75B2?logo=googlegemini&logoColor=white)](https://ai.google.dev/)
[![Rich](https://img.shields.io/badge/UI-rich-009688)](https://github.com/Textualize/rich)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#-contributing)

</div>

---

`pr-review-agent` is a single-purpose command-line tool: give it a GitHub pull-request URL and it fetches the title, description, and full diff, asks **Google Gemini** to review the changes, and prints a clean, color-coded report right in your terminal — **Summary**, **Issues Found** (with line references), **Suggestions**, and a final **Verdict**.

It's small, dependency-light, and the LLM contract is enforced with a **JSON response schema**, so the output is always structured — never a wall of prose to parse.

---

## ✨ Features

- **🎯 One command, full review** — `python agent.py <pr-url>` and you're done.
- **🧱 Structured output, guaranteed** — Gemini responds against a Pydantic JSON schema, so you always get the same four sections. No fragile text parsing.
- **🐞 Severity-tagged issues** — each problem is classified (`security` · `bug` · `logic_error` · `other`) and rendered in a color-coded table with file:line references.
- **⚖️ Actionable verdict** — `Approve` / `Request Changes` / `Needs Discussion`, with a one-line justification.
- **🎨 Beautiful terminal UI** — panels, tables, and spinners via [`rich`](https://github.com/Textualize/rich).
- **🪟 Cross-platform** — handles Windows legacy-console encoding (UTF-8) and escapes untrusted text so a `[bold]` in a diff can't break the render.
- **🔒 Secrets stay local** — API keys live in a git-ignored `.env`; nothing sensitive is ever committed.
- **🧩 Tunable** — model, token budget, and the review prompt live in one tidy `config.py`.

---

## 🎬 Example

```console
$ python agent.py https://github.com/psf/requests/pull/7489
```

```text
──────────────────── PR Review — psf/requests#7489 ────────────────────
FIX: Add RFC 7230 header validation to reject pseudo-headers (fix #6167)

┌──────────────────────────── 📋 Summary ─────────────────────────────┐
│ Introduces requests/validators.py with helpers for validating HTTP   │
│ header names against RFC 7230 (pseudo-headers, control characters).  │
└──────────────────────────────────────────────────────────────────────┘
                          🐞 Issues Found (1)
  Severity      Location   Description
 ──────────────────────────────────────────────────────────────────────
  logic error   N/A:N/A    The PR adds the validators but never wires
                           them into the request flow, so the stated
                           fix for #6167 is incomplete.
┌──────────────────────────── 💡 Suggestions ─────────────────────────┐
│ • Raise a custom requests.exceptions.InvalidHeaderName instead of    │
│   a bare ValueError.                                                  │
│ • Remove the leftover `if __name__ == "__main__":` test block.       │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────  ⚖️  Verdict ─────────────────────────┐
│ ❌ Request Changes                                                    │
│                                                                       │
│ Validation logic is solid, but it isn't integrated, so the fix is    │
│ incomplete.                                                           │
└──────────────────────────────────────────────────────────────────────┘
```

> *(Real output, lightly trimmed. Colors not shown here — your terminal gets the full color-coded version.)*

---

## 🏗️ How It Works

```
        GitHub PR URL
              │
              ▼
   ┌─────────────────────┐    PyGithub      ┌──────────────────────────┐
   │  parse_pr_url()     │ ───────────────▶ │  title · body · diff      │
   └─────────────────────┘                  └──────────────────────────┘
                                                        │
                                            JSON schema  ▼  (response_schema=Review)
                                            ┌──────────────────────────┐
                                            │   Google Gemini 2.5       │
                                            └──────────────────────────┘
                                                        │  structured Review
                                                        ▼
                                            ┌──────────────────────────┐
                                            │   rich terminal render    │
                                            └──────────────────────────┘
```

1. **Parse** the PR URL into `owner / repo / number`.
2. **Fetch** the PR's title, body, and per-file diffs with **PyGithub**.
3. **Review** — the assembled diff is sent to **Gemini**, constrained by a JSON response schema (the `Review` Pydantic model).
4. **Render** the validated result with **rich**.

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+**
- A **Google Gemini API key** — free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- *(Optional)* a **GitHub token** — needed for private repos, recommended for everyone to avoid anonymous rate limits

### Installation

```bash
# Clone
git clone https://github.com/JananiV07/pr-review-agent.git
cd pr-review-agent

# (recommended) create a virtual environment
python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

Copy the example env file and add your keys:

```bash
cp .env.example .env
```

| Variable         | Required | Description                                                                                          |
| ---------------- | :------: | ---------------------------------------------------------------------------------------------------- |
| `GEMINI_API_KEY` |    ✅     | Your Google Gemini API key. Get one at [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| `GITHUB_TOKEN`   |    ⬜     | GitHub PAT. Required for private repos; strongly recommended otherwise. [Create one](https://github.com/settings/tokens). |

> `.env` is git-ignored — your keys never leave your machine.

### Usage

```bash
python agent.py https://github.com/<owner>/<repo>/pull/<number>
```

```bash
# Try it on a real public PR
python agent.py https://github.com/psf/requests/pull/7489
```

---

## 🧩 The Review, Explained

| Section            | What it contains                                                                 |
| ------------------ | -------------------------------------------------------------------------------- |
| **📋 Summary**      | A neutral, plain-English description of what the PR actually does.                |
| **🐞 Issues Found** | Genuine bugs, logic errors, and security concerns — each with a severity and a `file:line` reference. |
| **💡 Suggestions**  | Non-blocking improvements: readability, tests, naming, edge cases.               |
| **⚖️ Verdict**      | `Approve`, `Request Changes`, or `Needs Discussion`, plus a one-line rationale.  |

**Severity levels:** `security` · `bug` · `logic_error` · `other`.

---

## ⚙️ Configuration

All tunables live in [`config.py`](config.py):

| Setting          | Default              | Description                                                              |
| ---------------- | -------------------- | ----------------------------------------------------------------------- |
| `MODEL`          | `gemini-2.5-flash`   | Gemini model. Swap to `gemini-2.5-pro` for deeper reviews of tricky diffs. |
| `MAX_TOKENS`     | `8192`               | Output-token budget (room for Gemini's reasoning **and** the JSON).     |
| `MAX_DIFF_CHARS` | `200_000`            | Soft ceiling on diff size — larger diffs trigger a warning, not a silent truncation. |
| `SYSTEM_PROMPT`  | *(see file)*         | The reviewer persona and field-by-field instructions.                   |

---

## 📁 Project Structure

```
pr-review-agent/
├── agent.py          # CLI entry point + all orchestration logic
├── config.py         # Model, token budget, thresholds, system prompt
├── requirements.txt  # Runtime dependencies
├── .env.example      # Template for your secrets (copy to .env)
├── .gitignore        # Keeps .env and caches out of git
├── LICENSE           # MIT
└── README.md
```

---

## 🧠 Design Notes

- **Why a JSON response schema?** Forcing Gemini to fill a Pydantic schema makes the output deterministic in *shape* — every run yields the same four sections, validated before rendering. No regex, no "sometimes it adds a preamble."
- **Diff-only review.** The agent reviews exactly what the diff shows; it does not clone the repo or read surrounding files. That keeps it fast and cheap, at the cost of whole-codebase context.
- **Robust rendering.** All model- and PR-derived text is escaped before entering `rich` markup, and stdout is reconfigured to UTF-8 — so a diff containing `[/]` or an emoji won't crash the report on any platform.

---

## ⚠️ Limitations

- Reviews **only the diff** — it can't catch issues that depend on code outside the changed lines.
- **Large PRs** are reviewed in full but cost more and may be slower; a warning is shown past `MAX_DIFF_CHARS`.
- Like any LLM, it can be **confidently wrong** — treat the output as a fast first pass, not a substitute for human review.

---

## 🔐 Security

- API keys are read from a **git-ignored `.env`** — never hard-code them or paste them into chats/issues.
- **Private-repo diffs are sent to Google's Gemini API** for review. Don't run it on code you can't share with a third-party LLM provider.
- Rotate a key immediately if it's ever exposed: [Gemini keys](https://aistudio.google.com/apikey) · [GitHub tokens](https://github.com/settings/tokens).

---

## 🛠️ Tech Stack

| Tool                                                          | Role                              |
| ------------------------------------------------------------- | --------------------------------- |
| [google-genai](https://pypi.org/project/google-genai/)        | Gemini API client + structured output |
| [PyGithub](https://pygithub.readthedocs.io/)                  | GitHub REST API client            |
| [rich](https://github.com/Textualize/rich)                    | Terminal formatting               |
| [pydantic](https://docs.pydantic.dev/)                        | Schema definition & validation    |
| [python-dotenv](https://pypi.org/project/python-dotenv/)      | `.env` loading                    |

---

## 🤝 Contributing

Issues and pull requests are welcome! If you're opening a PR, keep changes focused and run the agent on it first 😉.

---

## 📄 License

Released under the [MIT License](LICENSE).

<div align="center">
<sub>Built with PyGithub, Google Gemini, and rich.</sub>
</div>
