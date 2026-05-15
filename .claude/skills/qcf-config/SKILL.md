---
name: qcf-config
description: "View or set QCF configuration. Usage: /qcf-config get/set <key> [<value>]"
allowed-tools: Bash, Read
---

# QCF Config — View and Set Configuration

Read or modify `qcf.toml` values without editing the file directly.

## Usage

```
/qcf-config get                     — Show full config
/qcf-config get models              — Show [models] section
/qcf-config get stages.max_rounds   — Show a single value
/qcf-config set stages.max_rounds 5 — Set a value
```

## Execution

1. Run `qcf config get <key>` or `qcf config set <key> <value>`
2. Display the result
