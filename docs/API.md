# 万象积木 API 文档

万象积木 提供 OpenAI 兼容的 API 接口，支持流式和非流式调用。

## 启动 API 服务

```bash
# 带 API 服务启动
docker compose --profile with-api up -d

# 或直接运行
pip install uvicorn
uvicorn api_server:app --port 8000
```

## 认证

在 `.env` 中设置 API Key：

```env
WANXIANG_API_KEY=sk-your-api-key
```

请求时在 HTTP Header 中添加：

```http
Authorization: Bearer sk-your-api-key
```

---

## 列出可用模型

```http
GET /v1/models
Authorization: Bearer sk-your-api-key
```

**响应示例：**

```json
{
  "object": "list",
  "data": [
    {"id": "deepseek-chat", "object": "model", "created": 64000, "owned_by": "wanxiang-ai"},
    {"id": "gpt-4o", "object": "model", "created": 128000, "owned_by": "wanxiang-ai"}
  ]
}
```

---

## 聊天补全

```http
POST /v1/chat/completions
Authorization: Bearer sk-your-api-key
Content-Type: application/json
```

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `messages` | array | ✅ | 对话消息列表 |
| `model` | string | ❌ | 模型 ID（留空则自动路由） |
| `temperature` | float | ❌ | 温度 (0-2)，默认 0.7 |
| `max_tokens` | int | ❌ | 最大输出长度，默认 4096 |
| `stream` | bool | ❌ | 是否流式输出，默认 true |
| `preference` | string | ❌ | 路由偏好：balanced/cheap/best/fast |
| `enable_memory` | bool | ❌ | 是否启用长期记忆，默认 true |
| `enable_rag` | bool | ❌ | 是否启用 RAG，默认 true |

### 请求示例（非流式）

```json
{
  "messages": [
    {"role": "system", "content": "你是一个有用的助手。"},
    {"role": "user", "content": "写一个 Python 快速排序"}
  ],
  "temperature": 0.7,
  "stream": false,
  "preference": "balanced"
}
```

### 响应示例

```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1719123456,
  "model": "deepseek-coder",
  "choices": [{
    "index": 0,
    "message": {"role": "assistant", "content": "def quicksort(arr):\n    ..."},
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 42,
    "completion_tokens": 128,
    "total_tokens": 170
  }
}
```

### 请求示例（流式）

```json
{
  "messages": [{"role": "user", "content": "你好"}],
  "stream": true
}
```

流式响应使用 Server-Sent Events (SSE) 格式：

```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"role":"assistant"}}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"你好"}}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```

### curl 示例

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $WANXIANG_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

---

## 偏好策略说明

| 偏好 | 适用场景 | 权重 |
|------|----------|------|
| `balanced` | 日常使用（默认） | 成本33%·质量34%·速度33% |
| `cheap` | 预算敏感 | 成本55%·质量25%·速度20% |
| `best` | 追求质量 | 成本15%·质量60%·速度25% |
| `fast` | 追求速度 | 成本20%·质量25%·速度55% |

---

## 错误码

| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误（缺少 user 消息等）|
| 401 | API Key 无效或缺失 |
| 500 | 服务内部错误（所有模型调用失败等）|
| 503 | 模型路由系统不可用 |
