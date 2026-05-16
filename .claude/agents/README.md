# QCF Agents Index

Pipeline order: `tech-lead` → `task-validator` → `implement` → `review` → `security-reviewer` → `test-agent` → `pilot` → `evolver` / `meta-auditor`

| Agent                                             | Stage   | Model  | Tools                   | Description                                                                      |
| ------------------------------------------------- | ------- | ------ | ----------------------- | -------------------------------------------------------------------------------- |
| [tech-lead](tech-lead.md)                         | Core 1  | sonnet | Read, Bash              | Transform requirements into design documents with architecture analysis          |
| [task-validator](task-validator.md)               | Pre     | sonnet | Bash, Read, Write       | Validate and rewrite task files with 5-section structure and atomicity           |
| [implement](implement.md)                         | Core 2  | sonnet | Write, Read, Edit, Bash | Write production code from design docs, produce scope.json + summary.md          |
| [arch-reviewer](arch-reviewer.md)                 | Design  | opus   | Read, Write             | Review design doc for module boundaries, dependency direction, conventions       |
| [api-reviewer](api-reviewer.md)                   | Core 3a | opus   | Read                    | Inspect interface signatures, backward compatibility, naming conventions         |
| [code-quality-reviewer](code-quality-reviewer.md) | Core 3b | sonnet | Read                    | Check naming, DRY, complexity, test coverage, error handling                     |
| [security-reviewer](security-reviewer.md)         | Core 4  | opus   | Read                    | Audit for SQL injection, XSS, CSRF, auth bypass, info leaks                      |
| [test-agent](test-agent.md)                       | Core 4b | sonnet | Read, Bash, Write       | Run tests and report results, detect test framework, execute tests               |
| [pilot](pilot.md)                                 | Core 5  | sonnet | Bash, Read, Write       | Assess project state, verify code changes, decide steady-state or new group      |
| [evolver](evolver.md)                             | REPLAN  | sonnet | Write, Read, Edit, Bash | Analyze pipeline failures and modify QCF's own code to fix systemic issues       |
| [meta-auditor](meta-auditor.md)                   | REPLAN  | opus   | Read                    | Verify evolver changes don't introduce regressions across all quality dimensions |
