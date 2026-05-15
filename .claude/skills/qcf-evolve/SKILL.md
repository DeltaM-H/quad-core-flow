---
name: qcf-evolve
description: "Trigger evolution workflow. Usage: /qcf-evolve [<task-description>]"
allowed-tools: Bash, Read
---

# QCF Evolve — Evolution Workflow

Manually trigger QCF's self-improvement (evolution) workflow. Useful when the pipeline
hits a dead end and needs design-level changes to proceed.

## Usage

```
/qcf-evolve                          — Default evolution
/qcf-evolve improve error handling   — With specific direction
```

## Execution

1. Run `qcf evolve [<task>]`
2. Monitor the evolution sandbox output
