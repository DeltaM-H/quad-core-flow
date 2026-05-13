# Quad-Core Flow (QCF)

基于 Claude 的多智能体协作管道。将任务描述自动经过 Tech-Lead 分析、Coder 实现、Code Review、Security Audit 四个核心阶段，支持多轮迭代修复。

## 流程

```
Task → Tech-Lead (设计) → Coder (实现) → Code Review + Security Audit → 完成
                                  ↑_____________ 修复循环 _____________↓
```

## 快速开始

```bash
# 安装
pip install -e .

# 编写任务
echo "# my feature" > tasks/my-task.md

# 运行全流程
qcf auto tasks/my-task.md

# 连续模式（自动侦察新任务）
qcf auto tasks/my-task.md --continuous
```

## 命令

| 命令              | 说明                              |
| ----------------- | --------------------------------- |
| `qcf init`        | 创建默认配置和目录结构            |
| `qcf run <doc>`   | 在已有设计文档上运行实现→审查循环 |
| `qcf auto <task>` | 全自动流程：分析→实现→审查→审计   |
| `qcf status`      | 查看管道状态                      |
| `qcf watch`       | 监听 tech-lead/ 目录              |
| `qcf stop`        | 停止所有 QCF 进程                 |
