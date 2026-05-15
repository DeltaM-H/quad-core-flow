---
name: qcf-run
description: "Run QCF inner loop on a design doc. Usage: /qcf-run <design-doc>"
allowed-tools: Bash, Read
---

# QCF Run — Execute Inner Loop Only

Runs the QCF inner loop (implement → review → audit) on an **existing** design document
from `tech-lead/`.

## Usage

```
/qcf-run <design-doc>              — Run inner loop
/qcf-run <design-doc> --detach     — Run in background
/qcf-run <design-doc> --no-commit  — Disable auto-commit (debugging)
```

## Execution

1. **Validate** — check the design doc exists
2. **Run** — `qcf run <design-doc> [--detach] [--no-commit]`

## Notes

- Prefer `/qcf-start` for full pipeline (includes Tech-Lead → inner loop → Pilot)
- `/qcf-run` is for testing or running the inner loop on an already-written design doc
- Fail recovery is handled by Pilot in continuous mode; standalone run returns FAIL directly
