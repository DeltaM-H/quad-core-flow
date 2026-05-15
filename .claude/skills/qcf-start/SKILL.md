---
name: qcf-start
description: "Start QCF continuous mode. Usage: /qcf-start <task-file> [--detach]"
allowed-tools: Bash, Read, Agent
---

# QCF Start — Launch Continuous Pipeline

Starts the full Pipeline: validate task → tech-lead → implement → review → audit → pilot → repeat until STEADY_STATE.

## Usage

```
/qcf-start <task-file>             — Start continuous mode
/qcf-start <task-file> --detach    — Run in background
/qcf-start <task-file> -d          — Same, short flag
```

## Execution

1. **Validate** — invoke task-validator agent to check and rewrite task file(s) with 5-section structure
2. **Run** — `qcf auto <task-file> --continuous [--detach]`
3. **Report** — confirm started, show log location if detached

## Behavior

- Before pipeline starts, all task files are validated for 5 required sections and atomicity
- Non-conforming files are automatically rewritten with proper structure
- If validation finds no valid task content, the pipeline is aborted
- Inner loop failures within max_rounds → normal fix rounds
- Max rounds exhausted → code reverted, fail context passed to Pilot for recovery assessment
