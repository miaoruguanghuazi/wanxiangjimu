# 万象积木 开发者指南

## 项目架构

```
app.py                   主入口（Gradio UI）
├── model_router/        多模型路由系统
├── memory_system/       四层记忆系统
├── agent_orchestrator/  Agent 编排层
├── rag_pipeline/        RAG 知识库
├── security/            安全体系
├── tools/               工具框架
├── skill_market/        插件市场
├── cli/                 CLI 工具
├── telemetry.py         可观测性
├── conf/models.yaml     模型配置
└── api_server.py        OpenAI 兼容 API
```

## 如何编写一个 Skill

Skill 是万象积木 的插件机制，允许你扩展 AI 的能力。

### Step 1: 创建 Skill 项目

```bash
python -m cli skill create my-weather
```

这会生成以下文件结构：

```
my-weather/
├── __init__.py
├── manifest.json    # Skill 配置
└── handler.py       # 逻辑实现
```

### Step 2: 配置 manifest.json

```json
{
  "name": "天气查询",
  "version": "0.1.0",
  "description": "查询城市天气信息",
  "author": "your-name",
  "keywords": ["天气", "温度", "下雨"],
  "triggers": ["天气", "温度", "下雨"],
  "system_prompt": "你可以查询天气信息。"
}
```

- `triggers`: 触发关键词，当用户输入包含这些词时，Skill 会被激活
- `system_prompt`: 注入到系统提示词中的指令

### Step 3: 实现 handler.py

```python
async def execute(params: dict) -> dict:
    """
    执行 Skill
    
    params 包含:
    - input: 用户输入的文本
    - context: 当前对话上下文
    
    返回:
    - content: 要输出的内容
    - success: 是否成功
    """
    user_input = params.get("input", "")
    
    # 在这里实现你的逻辑
    result = f"处理完毕：{user_input}"
    
    return {
        "content": result,
        "success": True,
    }
```

### Step 4: 安装 Skill

```bash
python -m cli skill install ./my-weather
```

### Step 5: 验证

```bash
python -m cli skill list
python -m cli skill show my-weather
```

---

## 如何添加新模型

编辑 `conf/models.yaml`，在 `models` 列表中添加新条目：

```yaml
- model_id: my-model
  litellm_model: provider/my-model
  provider: my-provider
  api_key_env: MY_API_KEY
  context_window: 32000
  max_output: 4096
  pricing:
    input: 0.50
    output: 1.50
  capabilities: [text, code]
  speed_tier: 2
  quality_scores:
    general_qa: 7
    coding: 7
    reasoning: 7
    creative_writing: 7
```

然后在 `.env` 中添加 `MY_API_KEY=your-key-here`。

---

## 运行测试

```bash
# 运行所有测试
pytest

# 运行指定模块测试
pytest test_model_router.py -v
pytest test_memory_system.py -v

# 带覆盖率
pytest --cov=model_router --cov=memory_system
```

---

## 代码规范

- Python 3.12+，类型注解
- async/await 异步编程
- Google 风格的文档字符串
- 单测覆盖率 > 80%
