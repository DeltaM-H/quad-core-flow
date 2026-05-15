---
name: qcf-status
description: "Show QCF pipeline status. Usage: /qcf-status [--watch]"
allowed-tools: Bash
---

# QCF Status — Pipeline Dashboard

Shows the current state of the running QCF pipeline: active stage, round, and completion history.

## Usage

```
/qcf-status              — One-shot status display
/qcf-status --watch      — Live monitoring (Ctrl+C to stop)
/qcf-status -w           — Same, short flag
```

## Execution

1. Run `qcf status [--watch]`
2. Display the formatted dashboard output
