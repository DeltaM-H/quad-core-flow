{% if issues_content is defined and issues_content %}
请根据以下问题列表修复代码。

问题列表:
{{ issues_content }}

## 范围限定

在修复之前，使用 Read 工具读取：

1. **范围文件** {{ scope_file_path }} — 了解当前实现的范围边界
2. **详细摘要** {{ summary_file_path }} — 了解当前的实现概要

只修改问题列表中涉及的文件和模块，不要修改不相关的代码。

{% else %}
请读取设计文档 {{ design_doc_path }}，根据设计实现对应的代码。

## 范围限定

1. 先仔细阅读设计文档，理解完整需求
2. 在项目对应位置实现代码
3. 不要修改本次需求不相关的任何文件
   {% endif %}

## Input Contract

- 设计文档 ({{ design_doc_path }}) — 包含 Objective / Design / Files to Change / Implementation Plan
  {% if issues_content is defined and issues_content %}
- 问题列表 (修复模式) — 上一轮 review + audit 发现的具体 issue
- 范围文件 ({{ scope_file_path }}) — 当前实现范围边界
- 摘要文件 ({{ summary_file_path }}) — 实现概要（含接口签名、安全路径、设计决策）
  {% endif %}

## Execution Phases

1. **Read** — 读取设计文档/问题列表，理解需求
2. **Implement/Fix** — 在项目对应位置编写或修改代码
3. **Write artifacts** — 产出 scope.json（范围文件）、summary.md（详细摘要）、brief summary（简略摘要）
4. **Verify** — 确认所有产出文件已正确写入

## Failure Strategy

- 不需要重试（单次实现/修复）
- 超时处理：如果被超时中断，产出文件可能不完整，由 Pipeline 负责标记
- 如果设计文档中有不明确的地方，基于合理假设实现并在摘要中说明

## Self-Check List

- [ ] 所有新增/修改的代码文件已在 `changed_files` 中列出
- [ ] scope.json 包含 `changed_files`、`dependencies`、`out_of_scope`（均为列表）
- [ ] summary.md 包含 **接口签名**、**安全敏感代码路径**、**设计决策摘要** 三个段落
- [ ] 每个段落有实质性内容（>50 非空字符）
- [ ] 简略摘要已写入指定路径

## 产出要求

实现完成后，你必须产出以下文件：

### 1. 范围文件 scope.json → {{ scope_file_path }}

记录本次{% if issues_content is defined and issues_content %}修复{% else %}实现{% endif %}的范围边界：

```json
{
  "changed_files": ["path/to/file1.py", "path/to/file2.py"],
  "dependencies": ["dependent-module-A", "dependent-module-B"],
  "out_of_scope": ["path/to/related-but-not-modified.py"]
}
```

- `changed_files`: 所有新增或修改的文件（相对于项目根目录）
- `dependencies`: 本次实现依赖的外部模块或接口（仅列本次新增的依赖关系）
- `out_of_scope`: 与本次需求相关但明确未修改的文件

### 2. 详细摘要 summary.md → {{ summary_file_path }}

{% if issues_content is defined and issues_content %}
在已有摘要内容末尾追加本次修复的关键信息：

- 修复了哪些问题
- 修改了哪些接口签名（如果有变化）
- 关键修复决策理由

{% else %}
分三个段落撰写：

**### 1. 接口签名（~1K）**
列出修改/新增的函数签名、类签名、参数和返回值。用于 Code Reviewer 审查。
不要粘贴完整的代码实现，只列出签名。

**### 2. 安全敏感代码路径（~1K）**
列出涉及权限、SQL、输入验证的代码路径和文件行号，用于安全审计员审查。
包括：SQL 查询位置、权限校验点、用户输入处理处、敏感数据读写处。
如果本次实现不涉及安全敏感代码，明确写明"本次无安全敏感代码路径"并提供理由。

**### 3. 设计决策摘要（~1K）**
方案选择理由、替代方案评估，用于 Code Reviewer 审查。
为什么选择这个方案而不是其他方案，关键数据流如何设计。
{% endif %}

### 3. 简略摘要 → {{ brief_summary_path }}

{% if issues_content is defined and issues_content %}
追加 1-2 行简要说明本次修复的内容。
{% else %}
用于永久记录，只需 3-5 行简要说明本次修改了什么、为什么、涉及哪些文件。
{% endif %}

## Return Protocol

- **SUCCESS**: 所有产出文件（scope.json / summary.md / brief summary）已写入指定路径
- **BLOCKED**: 设计文档或问题列表不可读，无法开始工作
- **NEEDS_DECISION**: 需求存在多义性，需要 Tech-Lead 澄清

请开始{% if issues_content is defined and issues_content %}修复{% else %}实现{% endif %}。
