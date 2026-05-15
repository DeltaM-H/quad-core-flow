---
name: pilot
description: "Set direction for QCF Pilot agent. Usage: /pilot <instruction>. Example: /pilot 优先处理测试任务"
allowed-tools: Write, Read, Bash
---

# QCF Pilot Direction

Sets a one-shot instruction for the QCF Pilot agent. The instruction is written to
`/tmp/qcf-pilot-direction.txt` and consumed on the next Pilot run.

## Execution

1. Extract user instruction from skill `args`
2. Write it to `/tmp/qcf-pilot-direction.txt`
3. Confirm to user

## Output

Confirm with:

```
✅ Pilot direction set: <instruction>
```
