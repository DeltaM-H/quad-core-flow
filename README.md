# Quad-Core Flow (QCF)

**QCF** is a multi-agent AI pipeline that automates software development. Given a task description, it orchestrates six Claude agents in sequence — Tech-Lead → Implement/Fix → Review → Audit → Pilot + Evolver — each playing a specialized role to go from requirements to production-ready code.

## Pipeline

```
                          ┌─────────────────────────────────────────┐
  Task ──► Tech-Lead ────► Coder ──► Review ──► Audit ──► Done     │
                 ▲        (Impl/        │          │                │
                 │          Fix)        │          │                │
                 │           ▲          ▼          ▼               │
                 │           │    Review         Audit              │
                 │           │    PASS?         PASS?               │
                 │           └───────┴─────┬──────┘                 │
                 │                        │                        │
                 │                   Both PASS                     │
                 │               → Commit & Done                   │
                 │                        │                        │
                 │                  (or FAIL → fix loop)            │
                 └────────────────────────┘────────────────────────┘
                                      │
                                    Pilot
                                      │
                              ┌───────┴───────┐
                              │               │
                         Steady State    New Task
                                        ─► next iteration
```

### Cores

| Core   | Agent             | Role                                                                       |
| ------ | ----------------- | -------------------------------------------------------------------------- |
| **1**  | Tech-Lead         | Analyze requirements, explore project structure, produce a design document |
| **2**  | Coder (Implement) | Read the design doc and implement the code                                 |
| **2b** | Fix               | Read issues from Review/Audit and repair the code                          |
| **3**  | Reviewer          | Check correctness, architecture, edge cases, naming, completeness          |
| **4**  | Auditor           | Security audit: SQLi, XSS, CSRF, auth, info leaks, input validation        |
| **5**  | Pilot             | Assess project state, decide if another iteration is needed                |
| **6**  | Evolver           | Analyze pipeline failures and self-modify QCF code (with Meta-Audit gate)  |

Review and Audit run **in parallel** each round. If either fails, issues are fed to the Fix agent for the next round (up to `max_rounds`).

When the pipeline itself fails, the **Evolver** + **Meta-Audit** loop can be triggered to analyze root causes and self-modify QCF's code in an isolated git worktree sandbox.

## Features

- **Auto mode**: one command from task to done — Tech-Lead → inner loop → commit
- **Continuous mode**: after completion, Pilot re-evaluates the project and spawns new tasks automatically
- **Self-evolution**: Evolver agent analyzes pipeline failures and fixes QCF code, gated by Meta-Audit validation
- **Watch mode**: monitor the `tech-lead/` directory for new design documents
- **Detached mode**: run the pipeline in the background, poll status via JSON
- **Configurable**: timeouts, models (per stage), Claude parameters, commit messages, hooks
- **Hook system**: shell scripts or inline commands at every lifecycle event (post-start, on-passed, on-failed, etc.)
- **Auto-commit**: on passing all checks, results are committed to git
- **Status monitoring**: real-time status via `qcf status --watch`

## Quick Start

```bash
# Install
pip install -e .

# Initialize config and directory structure
qcf init

# Write a task
echo "# my feature" > tasks/my-task.md

# Run the full pipeline (auto mode)
qcf auto tasks/my-task.md

# Continuous mode — automatically discovers new tasks
qcf auto tasks/my-task.md --continuous
```

## Commands

| Command                        | Description                                            |
| ------------------------------ | ------------------------------------------------------ |
| `qcf init`                     | Create default `qcf.toml` and directory scaffold       |
| `qcf auto <task>`              | Full pipeline: Tech-Lead → Implement → Review → Audit  |
| `qcf auto <task> --continuous` | Auto mode + Pilot loop until steady state              |
| `qcf run <doc>`                | Run inner loop on an existing design document          |
| `qcf run <doc> --detach`       | Run in background, poll `/tmp/qcf-status.json`         |
| `qcf evolve`                   | Trigger self-evolution: analyze failures, fix QCF code |
| `qcf worktree list`            | List active git worktrees                              |
| `qcf status`                   | Show pipeline status                                   |
| `qcf status --watch`           | Live-updating status dashboard                         |
| `qcf watch`                    | Watch tech-lead/ directory for new design docs         |
| `qcf config get/set`           | Read or write configuration values                     |
| `qcf version`                  | Print version                                          |
| `qcf stop`                     | Kill all running QCF processes                         |

## Configuration

QCF is configured via `qcf.toml` (generated by `qcf init`). Key sections:

```toml
[workspace]
docs_dir = "output/docs"
status_file = "/tmp/qcf-status.json"

[stages]
max_rounds = 3
implement_timeout = 600
review_timeout = 450
audit_timeout = 300

[models]
review = "sonnet"
audit = ""

[hooks]
on-passed = ["notify-send 'Pipeline passed'"]
```

## Package Structure

```
qcf/                    # Python package (pip install -e .)
├── cli.py             # CLI entry point & argument parsing
├── config.py          # Configuration (qcf.toml) loader
├── engine.py          # Pipeline state machine & stage runners
├── evolver.py         # Self-evolution: Evolver + Meta-Audit orchestration
├── progress.py        # AGENT_PROGRESS.json pipeline dashboard
├── worktree.py        # Git worktree sandbox utilities
├── runner.py          # Claude CLI subprocess launcher
├── models.py          # Data models (Issue, ReviewOutput, AuditOutput, etc.)
├── hooks.py           # Event hook system (script + inline + callback)
├── watch.py           # Watch mode (inotify/poll)
├── default_config.toml
└── prompts/           # Jinja2 prompt templates
    ├── tech-lead.j2
    ├── implement.j2
    ├── fix.j2
    ├── review.j2
    ├── audit.j2
    ├── pilot.j2
    ├── evolver.j2
    └── meta_audit.j2
```

After running `qcf init`, the following are created:

```
tasks/                  # Place task descriptions here (input for auto mode)
output/docs/            # Pipeline output artifacts
├── tech-lead/         # Design documents
├── code-reviewer/     # Review reports
└── security-reviewer/ # Audit reports
```

## Requirements

- Python ≥ 3.10
- [Claude Code](https://claude.ai/code) CLI (`claude` on PATH)
- Linux (inotify-based watch mode) or any OS with file polling fallback

## Performance

- Each stage runs as a separate Claude Code subprocess with configurable timeout
- Review and Audit run in parallel using `asyncio.gather`
- Token usage is tracked per round and displayed in the summary

## License

MIT
