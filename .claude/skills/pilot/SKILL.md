---
name: pilot
description: "Pilot launch entry. Evaluate project state, write a task, start pipeline. Usage: /pilot <instruction>"
allowed-tools: Write, Read, Bash, Agent
---

# QCF Pilot — Entry Point

Evaluates current project state, writes a new task file, and launches the continuous pipeline.

## Flow

1. **Assess** — read project state, config, logs, and the user instruction
2. **Plan** — decide what task to generate next
3. **Write task** — create `tasks/pilot-<N>.md` with 5-section structure
4. **Launch** — `qcf auto tasks/pilot-<N>.md --continuous`

## Usage

```
/pilot 优化数据库查询性能          — Pilot writes a task and launches continuous pipeline
/pilot 先跑测试，再看下一步         — Pilot assesses and decides next task
```

## Notes

- Task files are written to `tasks/` with auto-incremented name
- Pipeline runs in continuous mode (`--continuous`) so Pilot loops on completion
- Check pipeline status with `/qcf-status`
