<div align="center">

# 🧩 万象积木

**多模型 · Agent编排 · RAG知识库 · 四层记忆 · 安全防护**

[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-127%20passing-brightgreen)]()

</div>

---

## ✨ 核心特性

| 模块 | 说明 |
|------|------|
| 🧭 **多模型路由** | DeepSeek / GPT-4o / 豆包 / 通义千问 自动路由 + 熔断降级 |
| 🧠 **四层记忆** | L1工作记忆 → L2短期 → L3长期(ChromaDB) → L4程序(Skill) |
| 🤖 **Agent编排** | 6个专长Agent，4种执行模式（单任务/串行/并行/审批） |
| 📚 **RAG知识库** | 本地向量检索 + 关键词混合检索，支持PDF/Word/网页 |
| 🛡️ **安全体系** | 11个安全模块：Prompt注入防护 / 沙箱 / 审计 / 速率限制 |
| 🔧 **工具调用** | 7个内置工具（搜索/代码执行/文件读写/HTTP请求）|
| 🔌 **Skill市场** | 插件SDK + 热插拔运行时 + CLI 脚手架 |
| 📊 **可视化** | 路由决策卡片 / 记忆管理面板 / 系统仪表盘 |
| 🌐 **API兼容** | OpenAI 兼容接口 `/v1/chat/completions` |

## 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/your-username/wanxiang-ai.git
cd wanxiang-ai

# 2. 安装
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置
cp .env.example .env
# 编辑 .env 填入 DeepSeek API Key

# 4. 启动
python app.py
```

访问 **http://localhost:7860**

### Docker 一键启动

```bash
docker compose up -d
```

---

## 📖 文档

| 文档 | 说明 |
|------|------|
| [安装指南](docs/INSTALL.md) | 本地/Docker/K3s 部署 |
| [使用指南](docs/USAGE.md) | 功能使用说明 |
| [开发者指南](docs/DEVELOPER.md) | 如何写 Skill / 添加模型 |
| [API 文档](docs/API.md) | OpenAI 兼容接口 |
| [贡献指南](CONTRIBUTING.md) | 如何参与项目 |
| [路线图](ROADMAP.md) | 版本计划 |

---

## 🧭 路由决策可视化

发送消息后，系统会展示完整的路由链路：

```
🧭 路由决策                    10.5ms
├─ 任务分类 → code
├─ 偏好策略 → balanced
├─ 能力过滤 → 4 个候选
├─ 熔断过滤 → 全部正常
├─ 评分排序 → deepseek-coder(87分) → ...
└─ 降级链 → 主选 → 备选 3 个
```

## 🧠 记忆系统

系统会自动记住你的偏好和事实：

```
你说: "我喜欢Python编程"
下一次: "帮我写个Python函数"
AI会知道: 用户喜欢Python → 给出更贴心的回答
```

在「记忆」Tab 中查看和管理所有记忆。

---

## 🛡️ 安全体系

| 模块 | 防护类型 |
|------|----------|
| PromptGuard | Prompt注入检测（4层模式库）|
| ContentFilter | 内容安全过滤 |
| CodeSandbox | 代码执行沙箱 |
| PathGuard | 文件路径防护 |
| HTTPGuard | SSRF 防护 |
| RateLimiter | 速率限制（令牌桶）|
| SessionGuard | 会话安全 |
| AuditLogger | 审计日志 |
| OutputGuard | 输出内容安全 |

---

## 🧩 Skill 插件开发

```bash
# 创建 Skill
python -m cli skill create my-tool

# 安装
python -m cli skill install ./my-tool

# 查看
python -m cli skill list
```

详细说明见 [开发者指南](docs/DEVELOPER.md)。

---

## 📊 项目结构

```
wanxiang-ai/
├── app.py                  # 主入口（Gradio UI）
├── api_server.py           # OpenAI 兼容 API
├── cli/                    # CLI 工具
├── model_router/           # 多模型路由（7模块）
├── memory_system/          # 四层记忆（8模块）
├── agent_orchestrator/     # Agent编排（7模块）
├── rag_pipeline/           # RAG管线（8模块）
├── security/               # 安全体系（11模块）
├── tools/                  # 工具框架（4模块）
├── skill_market/           # 插件市场（7模块）
├── conf/models.yaml        # 模型配置
├── telemetry.py            # 可观测性
├── deploy/                 # K3s Helm Chart
└── docs/                   # 文档
```

## 🧪 测试

```bash
pytest          # 全部测试
pytest -v       # 详细输出
```

**测试覆盖：** 127 个测试用例 ✅

## 📜 License

[MIT](LICENSE)

---

<div align="center">
  <strong>万象积木 — 你的记忆型 AI 同事</strong>
</div>
