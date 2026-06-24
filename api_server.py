"""
万象积木 — OpenAI 兼容 API 服务

提供 /v1/chat/completions 接口，兼容 OpenAI API 格式。
支持万象积木 特有参数：
  - preference: balanced/cheap/best/fast
  - enable_memory: true/false
  - enable_rag: true/false

启动: python -m uvicorn api_server:app --port 8000
"""

from __future__ import annotations

import os
import time
import logging
import uuid
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import StreamingResponse, JSONResponse
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("需要安装 fastapi 和 uvicorn: pip install fastapi uvicorn")

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("wanxiang-api")

# ============================================================
# 数据模型
# ============================================================

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = ""
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True
    # 万象积木 特有参数
    preference: Optional[str] = None
    enable_memory: bool = True
    enable_rag: bool = True

class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "wanxiang-jimu"

class ModelList(BaseModel):
    object: str = "list"
    data: list[ModelInfo]

# ============================================================
# API Key 验证
# ============================================================

API_KEY = os.getenv("WANXIANG_API_KEY", "")
SESSION_MAP: dict[str, dict] = {}  # session_id -> state

def verify_api_key(request: Request):
    if API_KEY:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            if token != API_KEY:
                raise HTTPException(status_code=401, detail="Invalid API key")
        else:
            raise HTTPException(status_code=401, detail="Missing Authorization header")

# ============================================================
# App 初始化（懒加载）
# ============================================================

_router_engine = None
_router_adapter = None
_registry = None
_memory = None
_app_instance = None

def ensure_system():
    global _router_engine, _router_adapter, _registry, _memory
    if _router_engine is not None:
        return
    from model_router import (
        ModelRegistry, default_registry,
        CircuitBreakerManager, RouterEngine, ModelAdapter,
    )
    from memory_system import MemorySystem
    import chromadb

    _registry = default_registry()
    circuit = CircuitBreakerManager()
    _router_engine = RouterEngine(_registry, circuit)
    _router_adapter = ModelAdapter(_registry, circuit)

    try:
        chroma_client = chromadb.PersistentClient(path="./data/chroma")
        _memory = MemorySystem(chroma_client=chroma_client, data_path="./data/memory")
    except Exception as e:
        logger.warning(f"Memory system init failed: {e}")

# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="万象积木 API",
    description="OpenAI 兼容接口 · 多模型路由 · 四层记忆 · 安全防护",
    version="1.5.0",
)


@app.get("/v1/models")
async def list_models(request: Request):
    verify_api_key(request)
    ensure_system()
    models = []
    if _registry:
        for m in _registry.all_enabled():
            models.append(ModelInfo(id=m.model_id, created=int(m.context_window)))
    return ModelList(data=models)


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatRequest, request: Request):
    verify_api_key(request)
    ensure_system()

    if not _router_engine:
        raise HTTPException(status_code=503, detail="Model router not available")

    # 提取最后一条用户消息
    user_message = ""
    for m in reversed(req.messages):
        if m.role == "user":
            user_message = m.content
            break

    if not user_message:
        raise HTTPException(status_code=400, detail="No user message found")

    # 构建 messages（用记忆系统增强）
    messages_dicts = [{"role": m.role, "content": m.content} for m in req.messages]
    session_id = f"api_{uuid.uuid4().hex[:12]}"

    if req.enable_memory and _memory:
        try:
            from memory_system.models import MemoryEntry
            enhanced = _memory.build_prompt(
                session_id, user_message,
                "You are WanXiang JiMu Assistant, a helpful AI with multi-model routing.",
                enable_long_term=True,
            )
        except Exception:
            enhanced = messages_dicts
    else:
        enhanced = messages_dicts

    # 路由
    route = _router_engine.route(
        user_message,
        preference=req.preference or "balanced",
    )

    if req.stream:
        return _stream_response(route, enhanced, req, session_id)
    else:
        return await _nonstream_response(route, enhanced, req, session_id)


async def _stream_response(route, messages, req: ChatRequest, session_id: str):
    async def generate():
        response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created = int(time.time())

        # 首块 — 角色
        yield f'data: {{"id":"{response_id}","object":"chat.completion.chunk","created":{created},"model":"{route.primary_model}","choices":[{{"index":0,"delta":{{"role":"assistant"}},"finish_reason":null}}]}}\n\n'

        full_content = ""
        try:
            async for chunk in _router_adapter.stream_call_with_route(
                route, messages, req.temperature, req.max_tokens
            ):
                full_content += chunk
                content_json = chunk.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
                yield f'data: {{"id":"{response_id}","object":"chat.completion.chunk","created":{created},"model":"{route.primary_model}","choices":[{{"index":0,"delta":{{"content":"{content_json}"}},"finish_reason":null}}]}}\n\n'
        except Exception as e:
            error_msg = f"\n\nError: {e}"
            yield f'data: {{"id":"{response_id}","object":"chat.completion.chunk","created":{created},"model":"{route.primary_model}","choices":[{{"index":0,"delta":{{"content":"{error_msg}"}},"finish_reason":"stop"}}]}}\n\n'

        # 尾块
        yield f'data: {{"id":"{response_id}","object":"chat.completion.chunk","created":{created},"model":"{route.primary_model}","choices":[{{"index":0,"delta":{{}},"finish_reason":"stop"}}]}}\n\n'
        yield "data: [DONE]\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


async def _nonstream_response(route, messages, req: ChatRequest, session_id: str):
    try:
        response = await _router_adapter.call_with_route(
            route, messages, req.temperature, req.max_tokens
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    response_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    return {
        "id": response_id,
        "object": "chat.completion",
        "created": created,
        "model": route.primary_model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response.content},
            "finish_reason": response.finish_reason,
        }],
        "usage": response.token_usage,
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
