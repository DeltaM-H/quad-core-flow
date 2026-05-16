# Quad-Core Flow (QCF)

**QCF** is a multi-agent AI pipeline that automates software development. Given a task description, it orchestrates Claude agents through a structured loop — Tech-Lead → Architecture Review → Implement/Fix → API + Quality Review + Security Audit + Test → Pilot — producing production-ready code from requirements.

## Pipeline

```
                           ┌───────────────────────────────────────────────┐
 Task ──► Tech-Lead ─────► Arch-Review ──► Coder ──► Review ────────► Test
                 ▲              │          (Impl/       │    │         │
                 │              │            Fix)       │    │         │
                 │              │          [API+Quality]│    │         │
                 │              │               ▲       │    │         │
                 │              ▼               │   PASS/FAIL  │   PASS/FAIL
                 │          PASS/FAIL            └───┬──┬──────┘     │
                 │                                   │  │            │
                 └────────────────────────────────────┘  │            │
                                                   │     │           │
                                              ── ALL PASS ──────────┘
                                                  │
                                              Commit
                                                  │
                                            (or FAIL → fix loop)
```

After the inner loop passes, **Pilot** assesses the project and either declares steady state or produces a new task for the next iteration.

## Quick Start

```bash
pip install -e .
qcf init
echo "# my feature" > tasks/my-task.md
qcf auto tasks/my-task.md            # full pipeline
qcf auto tasks/my-task.md -c         # continuous (Pilot loop)
```

## Agents

| Agent             | Stage     | Role                                                  |
| ----------------- | --------- | ----------------------------------------------------- |
| Tech-Lead         | Pre-loop  | Analyze requirements, produce a design document       |
| Arch-Reviewer     | Pre-loop  | Review design doc for module boundaries, architecture |
| Coder (Implement) | Loop      | Implement code from the design doc                    |
| Fix               | Loop      | Repair code from Review/Audit/Test issues             |
| API Reviewer      | Loop      | Check interface signatures, backward compatibility    |
| Quality Reviewer  | Loop      | Check naming, DRY, complexity, error handling         |
| Auditor           | Loop      | Security audit: OWASP Top 10                          |
| Test Agent        | Loop      | Run tests and report PASS/FAIL results                |
| Pilot             | Post-loop | Assess project state, decide next action              |
| Evolver           | Escalate  | Analyze pipeline failures and self-modify QCF code    |
| Meta-Auditor      | Escalate  | Validate Evolver's self-modifications                 |

The inner loop (Implement → Review → Audit → Test) runs up to `max_rounds`. Review, Audit, and Test run in parallel. If all checks pass, results are committed and Pilot takes over. On exhaustion, code is reverted to the last commit and Pilot receives a fail report to plan recovery.

## Commands

| Command                          | Description                           |
| -------------------------------- | ------------------------------------- |
| `qcf init`                       | Create default config and directories |
| `qcf auto <task>`                | Full pipeline: Tech-Lead → inner loop |
| `qcf auto <task> --continuous`   | Auto mode + Pilot loop                |
| `qcf run <doc>`                  | Inner loop on an existing design doc  |
| `qcf run <doc> --detach`         | Run in background                     |
| `qcf status [--watch]`           | Show pipeline status                  |
| `qcf config get/set <key> [val]` | Read or write configuration           |
| `qcf events [--tail N,--follow]` | Show pipeline events                  |
| `qcf evolve`                     | Trigger self-evolution                |
| `qcf worktree list\|remove`      | Manage git worktrees                  |
| `qcf stop`                       | Kill all running QCF processes        |
| `qcf version`                    | Print version                         |

### In-Session Skills

| Command       | Description                          |
| ------------- | ------------------------------------ |
| `/qcf-start`  | Start continuous pipeline            |
| `/qcf-run`    | Run pipeline on a design document    |
| `/qcf-status` | Show pipeline status                 |
| `/qcf-stop`   | Stop all processes                   |
| `/qcf-evolve` | Trigger evolution                    |
| `/qcf-config` | Get/set config values                |
| `/qcf-events` | Show pipeline events                 |
| `/pilot`      | Inject user direction into the Pilot |

## Configuration

`qcf.toml` is generated by `qcf init`:

```toml
[workspace]
docs_dir = "output/docs"

[stages]
max_rounds = 3
implement_timeout = 600
review_timeout = 450
audit_timeout = 300
test_timeout = 300

[models]
"api-reviewer" = "sonnet"
"code-quality-reviewer" = "sonnet"
"arch-reviewer" = "opus"
"test-agent" = "sonnet"

[hooks]
on-passed = ["notify-send 'Pipeline passed'"]
```

## Project Structure

```
qcf/                      # Python package
├── cli.py               # CLI entry point
├── config.py            # Config loader (qcf.toml)
├── engine.py            # Pipeline state machine
├── evolver.py           # Self-evolution workflow
├── events.py            # JSONL event logger
├── runner.py            # Claude CLI subprocess launcher
├── models.py            # Data models
├── hooks.py             # Event hook system
├── progress.py          # Pipeline dashboard
├── worktree.py          # Git worktree utilities
├── prompts/             # Prompt template helpers
├── default_config.toml  # Default config values
└── __init__.py

.claude/
├── agents/              # Agent prompt templates (one per role)
├── skills/              # Slash command skills (6 qcf-* + pilot)
└── worktrees/           # Isolated worktrees for evolution

tasks/                   # Task descriptions (input for qcf auto)
output/docs/             # Pipeline output artifacts
├── tech-lead/           # Design documents
├── coder/               # Implementation workspace
├── code-reviewer/       # Review reports
└── security-reviewer/   # Audit reports
```

## Requirements

- Python >= 3.10
- [Claude Code](https://claude.ai/code) CLI (`claude` on PATH)
- Linux or macOS

## License

MIT
