# 🏛️ Architecture

A visual guide to how **pr-review-agent** turns a GitHub pull-request URL into a structured terminal review. All diagrams are [Mermaid](https://mermaid.js.org/) and render natively on GitHub.

- [Pipeline](#pipeline)
- [Runtime Sequence](#runtime-sequence)
- [Control Flow & Exit Codes](#control-flow--exit-codes)
- [Data Model](#data-model)
- [Module Map](#module-map)

---

## Pipeline

The happy path, end to end:

```mermaid
flowchart LR
    A([GitHub PR URL]) --> B["parse_pr_url()"]
    B --> C["fetch_pull_request()<br/>PyGithub"]
    C --> D[/"title · body · diff"/]
    D --> E["request_review()<br/>Gemini · JSON schema"]
    E --> F["Review<br/>Pydantic-validated"]
    F --> G["render_review()<br/>rich"]
    G --> H([Terminal report])
```

---

## Runtime Sequence

Who talks to whom during a single review run:

```mermaid
sequenceDiagram
    actor User
    participant CLI as agent.py
    participant GH as GitHub · PyGithub
    participant GM as Gemini API
    participant Term as Terminal · rich

    User->>CLI: python agent.py PR_URL
    CLI->>CLI: parse_pr_url()
    CLI->>GH: get_repo · get_pull · get_files()
    GH-->>CLI: title, body, diff
    CLI->>GM: generate_content(diff, schema=Review)
    GM-->>CLI: structured JSON review
    CLI->>CLI: validate -> Review
    CLI->>Term: render_review()
    Term-->>User: Summary · Issues · Suggestions · Verdict
```

---

## Control Flow & Exit Codes

Every branch the CLI can take, including error paths and the resulting exit code:

```mermaid
flowchart TD
    S([python agent.py PR_URL]) --> K{GEMINI_API_KEY set?}
    K -- no --> E1[/print error/] --> X1([exit 1])
    K -- yes --> U{valid PR URL?}
    U -- no --> E2[/print error/] --> X1
    U -- yes --> FETCH[fetch PR via GitHub]
    FETCH -- GithubException --> E3[/print GitHub error + hint/] --> X1
    FETCH --> HASF{file changes?}
    HASF -- no --> NOOP[/print 'nothing to review'/] --> X0([exit 0])
    HASF -- yes --> BIG{diff &gt; MAX_DIFF_CHARS?}
    BIG -- yes --> WARN[/warn: large diff/] --> REV
    BIG -- no --> REV[review with Gemini]
    REV -- APIError / parse error --> E4[/print error/] --> X1
    REV --> RENDER[render review with rich] --> X0
```

| Exit code | When |
| :-------: | ---- |
| `0` | Review printed, **or** the PR had no file changes to review. |
| `1` | Missing API key, invalid URL, GitHub error, Gemini error, or unparseable response. |

---

## Data Model

The review contract is a set of Pydantic models. `Review` doubles as the JSON
response schema sent to Gemini **and** the validated object used for rendering —
one source of truth for the output shape.

```mermaid
classDiagram
    class PullRequest {
        +str owner
        +str repo
        +int number
        +str title
        +str body
        +str diff
        +int num_files
        +reference() str
    }
    class Review {
        +str summary
        +Issue[] issues
        +str[] suggestions
        +Verdict verdict
        +str verdict_reasoning
    }
    class Issue {
        +str file
        +str line
        +Severity severity
        +str description
    }
    class Severity {
        <<enumeration>>
        security
        bug
        logic_error
        other
    }
    class Verdict {
        <<enumeration>>
        Approve
        RequestChanges
        NeedsDiscussion
    }
    Review "1" o-- "0..*" Issue : contains
    Issue --> Severity
    Review --> Verdict
```

> **Verdict** values are the literal strings `"Approve"`, `"Request Changes"`, and `"Needs Discussion"` (shown without spaces above for diagram compatibility).

---

## Module Map

How the code is organized and what each piece owns:

```mermaid
flowchart TD
    subgraph cfg["config.py"]
        M[MODEL · MAX_TOKENS<br/>MAX_DIFF_CHARS · SYSTEM_PROMPT]
    end
    subgraph ag["agent.py"]
        direction TB
        P["parse_pr_url()"]
        FT["fetch_pull_request()<br/>+ _build_diff()"]
        RR["request_review()<br/>+ _build_user_content()<br/>+ _parse_review()"]
        RV["render_review()"]
        MN["main() — CLI entry"]
    end
    ENV[".env<br/>GEMINI_API_KEY · GITHUB_TOKEN"] -.loaded by.-> MN
    MN --> P --> FT --> RR --> RV
    M -.configures.-> RR
    M -.configures.-> MN
```

---

_Back to the [README](../README.md)._
