---
name: qcf-run
description: "Run QCF inner loop on a design doc. Usage: /qcf-run <design-doc> [--detach]"
allowed-tools: Bash, Read
---

# QCF Run — Inner Loop on Design Doc

Runs the inner loop (implement → review → audit) on an **existing** design doc
from tech-lead output.

## Usage

```
/qcf-run <design-doc>              — Inner loop
/qcf-run <design-doc> -d           — In background
/qcf-run <design-doc> --no-commit   — Skip auto-commit
```

## Execution

1. **Validate** — check the design doc exists
2. **Run** — `qcf run <design-doc> [--detach] [--no-commit]`
