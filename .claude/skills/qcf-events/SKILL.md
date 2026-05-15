---
name: qcf-events
description: "Show pipeline events. Usage: /qcf-events [--tail N] [--follow]"
allowed-tools: Bash
---

# QCF Events — Pipeline Event Log

Displays the unified events JSONL from the current pipeline run.

## Usage

```
/qcf-events                — Show last 20 events
/qcf-events --tail 50      — Show last 50 events
/qcf-events --follow       — Tail -f live events
/qcf-events -f             — Same, short flag
```

## Execution

1. Run `qcf events [--tail N] [--follow]`
2. Display event JSON lines
