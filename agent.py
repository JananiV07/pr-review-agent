"""PR Review Agent — fetch a GitHub pull request and review it with Gemini.

Usage::

    python agent.py https://github.com/<owner>/<repo>/pull/<number>

The agent fetches the pull request's title, description, and per-file diffs via
PyGithub, sends them to Google's Gemini API for a structured review, and prints
the result to the terminal using ``rich``.

Required environment variables (typically supplied through a local ``.env``):
    GEMINI_API_KEY  Your Google Gemini API key (from https://aistudio.google.com/apikey).
    GITHUB_TOKEN    A GitHub token. Optional for public repositories, but
                    strongly recommended — it lifts the very low anonymous rate
                    limit and grants access to private repos.

The review is produced with a *JSON response schema*, so Gemini always returns
the four required sections (summary, issues, suggestions, verdict) as structured
data, which is then rendered with ``rich``.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import List, Literal, Optional, Tuple

from dotenv import load_dotenv
from github import Auth, Github, GithubException
from google import genai
from google.genai import errors as genai_errors
from pydantic import BaseModel, Field, ValidationError
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

import config


# ---------------------------------------------------------------------------
# Data models for the structured review
# ---------------------------------------------------------------------------

# Severity labels an issue may carry.
Severity = Literal["security", "bug", "logic_error", "other"]

# The three possible review outcomes.
Verdict = Literal["Approve", "Request Changes", "Needs Discussion"]


class Issue(BaseModel):
    """A single concrete problem found in the diff."""

    file: str = Field(description="Path of the file where the issue occurs.")
    line: str = Field(description="Line reference, e.g. '42', '40-55', or 'N/A'.")
    severity: Severity = Field(description="What kind of problem this is.")
    description: str = Field(description="What is wrong and why it matters.")


class Review(BaseModel):
    """The full structured review returned by Gemini.

    This model doubles as the JSON response schema sent to the Gemini API and as
    the validated object used for rendering, so its shape is the single source
    of truth for the review contract.
    """

    summary: str = Field(description="What this PR does, in a few sentences.")
    issues: List[Issue] = Field(
        default_factory=list,
        description="Bugs, logic errors, and security concerns found in the diff.",
    )
    suggestions: List[str] = Field(
        default_factory=list,
        description="Non-blocking improvement ideas.",
    )
    verdict: Verdict = Field(description="Overall recommendation.")
    verdict_reasoning: str = Field(description="Brief justification for the verdict.")


class PullRequest(BaseModel):
    """The slice of a GitHub PR that the agent needs in order to review it."""

    owner: str
    repo: str
    number: int
    title: str
    body: str
    diff: str
    num_files: int

    @property
    def reference(self) -> str:
        """Return a compact human-readable reference like ``owner/repo#123``."""
        return f"{self.owner}/{self.repo}#{self.number}"


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

# Matches a GitHub PR URL and captures the owner, repository, and PR number.
_PR_URL_RE = re.compile(
    r"github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)


def parse_pr_url(url: str) -> Tuple[str, str, int]:
    """Parse a GitHub PR URL into ``(owner, repo, number)``.

    Args:
        url: A URL of the form
            ``https://github.com/<owner>/<repo>/pull/<number>``.

    Returns:
        A ``(owner, repo, number)`` tuple.

    Raises:
        ValueError: If ``url`` is not a recognizable GitHub PR URL.
    """
    match = _PR_URL_RE.search(url.strip())
    if not match:
        raise ValueError(
            f"Not a valid GitHub PR URL: {url!r}\n"
            "Expected something like "
            "https://github.com/<owner>/<repo>/pull/<number>"
        )
    return match.group("owner"), match.group("repo"), int(match.group("number"))


def _build_diff(files) -> str:
    """Assemble a single readable diff string from PyGithub file objects.

    Each changed file contributes a short header followed by its unified-diff
    patch. Files without a textual patch (binary blobs, or diffs GitHub deems
    too large) are noted explicitly rather than dropped silently.

    Args:
        files: An iterable of PyGithub ``File`` objects from ``pr.get_files()``.

    Returns:
        The combined, human-readable diff.
    """
    parts: List[str] = []
    for f in files:
        header = (
            f"### File: {f.filename}  "
            f"({f.status}, +{f.additions} -{f.deletions})"
        )
        if f.patch:
            parts.append(f"{header}\n{f.patch}")
        else:
            parts.append(
                f"{header}\n(No textual diff available — binary file or "
                "diff too large to display.)"
            )
    return "\n\n".join(parts)


def fetch_pull_request(
    owner: str, repo: str, number: int, token: Optional[str]
) -> PullRequest:
    """Fetch a pull request's metadata and diff from GitHub.

    Args:
        owner: Repository owner (user or organization).
        repo: Repository name.
        number: Pull request number.
        token: A GitHub token, or ``None`` for anonymous access.

    Returns:
        A populated :class:`PullRequest`.

    Raises:
        GithubException: If the repository or pull request cannot be accessed
            (not found, private without a token, rate limited, etc.).
    """
    auth = Auth.Token(token) if token else None
    github = Github(auth=auth) if auth else Github()
    try:
        repository = github.get_repo(f"{owner}/{repo}")
        pull = repository.get_pull(number)
        files = list(pull.get_files())
        return PullRequest(
            owner=owner,
            repo=repo,
            number=number,
            title=pull.title or "",
            body=pull.body or "",
            diff=_build_diff(files),
            num_files=len(files),
        )
    finally:
        # Always release the underlying HTTP connection pool.
        github.close()


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _build_user_content(pr: PullRequest) -> str:
    """Format the per-PR content sent to Gemini.

    The stable instructions live in the system prompt; everything that varies
    per PR (title, body, diff) goes here.
    """
    body = pr.body.strip() or "(no description provided)"
    return (
        "# Pull Request\n\n"
        f"**Title:** {pr.title}\n\n"
        f"**Description:**\n{body}\n\n"
        "# Unified Diff\n\n"
        f"{pr.diff if pr.diff.strip() else '(no file changes detected)'}"
    )


def _finish_reason(response) -> str:
    """Best-effort extraction of Gemini's finish reason, for error messages."""
    try:
        return str(response.candidates[0].finish_reason)
    except (AttributeError, IndexError, TypeError):
        return ""


def _parse_review(response) -> Review:
    """Turn a Gemini response into a validated :class:`Review`.

    Prefers the SDK's pre-parsed object, then falls back to validating the raw
    JSON text, so the function is resilient across SDK versions.

    Raises:
        RuntimeError: If no parseable review can be extracted.
        ValidationError: If the returned data does not match the schema.
    """
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, Review):
        return parsed
    if isinstance(parsed, dict):
        return Review.model_validate(parsed)

    try:
        text = response.text
    except Exception:  # noqa: BLE001 - SDK may raise when there is no content
        text = None
    if text:
        return Review.model_validate_json(text)

    reason = _finish_reason(response)
    raise RuntimeError(
        "Gemini did not return a parseable review"
        + (f" (finish reason: {reason})." if reason else ".")
        + " The diff may be too large — try again or raise MAX_TOKENS in config."
    )


def request_review(pr: PullRequest, api_key: str) -> Review:
    """Send the pull request to Gemini and return the parsed review.

    A JSON response schema (the :class:`Review` model) guarantees the response
    comes back as structured data rather than free-form text.

    Args:
        pr: The pull request to review.
        api_key: The Gemini API key.

    Returns:
        The parsed :class:`Review`.

    Raises:
        google.genai.errors.APIError: If the Gemini API call fails.
        RuntimeError: If Gemini returns no usable review.
        ValidationError: If the response does not match the schema.
    """
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=config.MODEL,
        contents=_build_user_content(pr),
        config={
            "system_instruction": config.SYSTEM_PROMPT,
            "max_output_tokens": config.MAX_TOKENS,
            "response_mime_type": "application/json",
            "response_schema": Review,
        },
    )
    return _parse_review(response)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Maps each verdict to a display color and emoji.
_VERDICT_STYLE = {
    "Approve": ("green", "✅"),
    "Request Changes": ("red", "❌"),
    "Needs Discussion": ("yellow", "💬"),
}

# Maps each issue severity to a display color.
_SEVERITY_COLOR = {
    "security": "bold red",
    "bug": "red",
    "logic_error": "yellow",
    "other": "cyan",
}


def render_review(review: Review, pr: PullRequest, console: Console) -> None:
    """Render a :class:`Review` to the terminal using ``rich``.

    Model- and PR-derived text is escaped before being placed into any ``rich``
    markup context (table cells, the verdict panel, the title line) so that
    literal ``[...]`` sequences cannot break rendering or inject styling.

    Args:
        review: The parsed review to display.
        pr: The reviewed pull request (used for the heading).
        console: The ``rich`` console to print to.
    """
    console.rule(f"[bold]PR Review — {pr.reference}")
    console.print(f"[dim]{escape(pr.title)}[/dim]\n")

    # --- Summary ---------------------------------------------------------
    console.print(
        Panel(
            Markdown(review.summary),
            title="📋 Summary",
            border_style="blue",
            box=box.ROUNDED,
        )
    )

    # --- Issues Found ----------------------------------------------------
    if review.issues:
        table = Table(
            title=f"🐞 Issues Found ({len(review.issues)})",
            box=box.SIMPLE_HEAVY,
            show_lines=True,
            expand=True,
        )
        table.add_column("Severity", no_wrap=True)
        table.add_column("Location", no_wrap=True, style="dim")
        table.add_column("Description", ratio=1)
        for issue in review.issues:
            color = _SEVERITY_COLOR.get(issue.severity, "white")
            severity = issue.severity.replace("_", " ")
            table.add_row(
                f"[{color}]{severity}[/{color}]",
                escape(f"{issue.file}:{issue.line}"),
                escape(issue.description),
            )
        console.print(table)
    else:
        console.print(
            Panel(
                "No bugs, logic errors, or security concerns found.",
                title="🐞 Issues Found",
                border_style="green",
                box=box.ROUNDED,
            )
        )

    # --- Suggestions -----------------------------------------------------
    if review.suggestions:
        bullets = "\n".join(f"- {s}" for s in review.suggestions)
        console.print(
            Panel(
                Markdown(bullets),
                title="💡 Suggestions",
                border_style="magenta",
                box=box.ROUNDED,
            )
        )
    else:
        console.print(
            Panel(
                "No additional suggestions.",
                title="💡 Suggestions",
                border_style="magenta",
                box=box.ROUNDED,
            )
        )

    # --- Verdict ---------------------------------------------------------
    color, emoji = _VERDICT_STYLE.get(review.verdict, ("white", ""))
    console.print(
        Panel(
            f"[bold {color}]{emoji} {review.verdict}[/bold {color}]\n\n"
            f"{escape(review.verdict_reasoning)}",
            title="⚖️  Verdict",
            border_style=color,
            box=box.HEAVY,
        )
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Run the PR review agent as a command-line tool.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``). Exposed
            mainly to make the entry point testable.

    Returns:
        A process exit code: ``0`` on success, non-zero on failure.
    """
    parser = argparse.ArgumentParser(
        prog="pr-review-agent",
        description="Review a GitHub pull request with Gemini.",
    )
    parser.add_argument(
        "pr_url",
        help="GitHub pull request URL, e.g. "
        "https://github.com/owner/repo/pull/123",
    )
    args = parser.parse_args(argv)

    # Ensure the terminal can encode the rich output (box-drawing characters,
    # emoji, spinners). On a legacy Windows console (cp1252) these would
    # otherwise raise UnicodeEncodeError; UTF-8 keeps output portable.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    load_dotenv()
    console = Console()

    api_key = os.environ.get("GEMINI_API_KEY")
    github_token = os.environ.get("GITHUB_TOKEN")

    if not api_key:
        console.print(
            "[bold red]Error:[/bold red] GEMINI_API_KEY is not set. "
            "Add it to your environment or a local .env file "
            "(get one at https://aistudio.google.com/apikey)."
        )
        return 1
    if not github_token:
        console.print(
            "[yellow]Warning:[/yellow] GITHUB_TOKEN is not set — using "
            "anonymous GitHub access, which is heavily rate limited and "
            "cannot read private repositories.\n"
        )

    # 1. Parse the URL.
    try:
        owner, repo, number = parse_pr_url(args.pr_url)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1

    # 2. Fetch the PR from GitHub.
    try:
        with console.status(
            f"Fetching PR #{number} from {owner}/{repo}…", spinner="dots"
        ):
            pr = fetch_pull_request(owner, repo, number, github_token)
    except GithubException as exc:
        console.print(
            f"[bold red]GitHub error:[/bold red] could not fetch "
            f"{owner}/{repo}#{number} (status {exc.status}). "
            f"{_github_error_hint(exc)}"
        )
        return 1

    if pr.num_files == 0 or not pr.diff.strip():
        console.print(
            "[yellow]This pull request has no file changes to review.[/yellow]"
        )
        return 0

    if len(pr.diff) > config.MAX_DIFF_CHARS:
        console.print(
            f"[yellow]Note:[/yellow] this diff is large "
            f"({len(pr.diff):,} characters across {pr.num_files} files). "
            "Reviewing the whole thing — this may be slower and pricier than "
            "usual.\n"
        )

    # 3. Ask Gemini for the review.
    try:
        with console.status("Reviewing with Gemini…", spinner="dots"):
            review = request_review(pr, api_key)
    except genai_errors.APIError as exc:
        console.print(f"[bold red]Gemini API error:[/bold red] {exc}")
        return 1
    except (RuntimeError, ValidationError) as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 1

    # 4. Render it.
    console.print()
    render_review(review, pr, console)
    return 0


def _github_error_hint(exc: GithubException) -> str:
    """Return a short, actionable hint for a GitHub error status."""
    hints = {
        401: "Check that GITHUB_TOKEN is valid.",
        403: "You may be rate limited or lack access — set/upgrade GITHUB_TOKEN.",
        404: "The repo or PR was not found, or it is private and your token "
        "lacks access.",
    }
    return hints.get(exc.status, "")


if __name__ == "__main__":
    sys.exit(main())
