---
name: qcf-run
description: "Run QCF inner loop on a design doc. Usage: /qcf-run <design-doc> [--from <stage>]"
allowed-tools: Bash, Read
---

# QCF Run — Execute Inner Loop Only

Runs the QCF inner loop (implement → review → audit) on an **existing** design document.

## Usage

```
/qcf-run <design-doc>              — Auto-detect start stage from path
/qcf-run <design-doc> --from fix   — Force start from fix stage
/qcf-run <design-doc> --detach     — Run in background
/qcf-run <design-doc> --no-commit  — Disable auto-commit (debugging)
```

## Execution

1. **Validate** — check the design doc exists
2. **Detect stage** — if `--from` given use it; otherwise infer from path (`tech-lead/` → implement, `code-reviewer/` → fix)
3. **Run** — `qcf run <design-doc> [--start-stage <stage>] [--detach] [--no-commit]`

## Notes

- Prefer `/qcf-start` for full pipeline (includes Tech-Lead design phase)
- `/qcf-run` is for resuming or testing the inner loop on an already-written design doc
