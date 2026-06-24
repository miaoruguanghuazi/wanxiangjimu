# 万象积木 安装与部署指南

## 环境要求

- Python 3.12+
- 4GB+ RAM（推荐 8GB）
- 操作系统：Windows / macOS / Linux

## 方式一：本地运行（推荐开发）

### 1. 克隆项目

```bash
git clone https://github.com/your-username/wanxiang-ai.git
cd wanxiang-ai
```

### 2. 创建虚拟环境

```bash
python -m venv venv

# Windows
.\venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入你的 API Key：

```env
DEEPSEEK_API_KEY=sk-your-key-here
# 可选：
OPENAI_API_KEY=sk-your-key-here
DASHSCOPE_API_KEY=sk-your-key-here
```

API Key 申请地址：
- [DeepSeek](https://platform.deepseek.com/)
- [OpenAI](https://platform.openai.com/)
- [通义千问](https://dashscope.aliyun.com/)

### 5. 启动

```bash
python app.py
```

访问 http://localhost:7860

---

## 方式二：Docker 部署（推荐生产）

### 1. 配置

```bash
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 2. 启动

```bash
# 标准启动
docker compose up -d

# 带 API 服务
docker compose --profile with-api up -d
```

### 3. 查看日志

```bash
docker compose logs -f
```

### 4. 停止

```bash
docker compose down
```

### 5. 重建（修改代码后）

```bash
docker compose up -d --build
```

---

## 方式三：K3s 集群部署

详见 `deploy/` 目录的 Helm Chart：

```bash
helm install wanxiang-ai ./deploy
```

---

## 环境变量参考

| 变量 | 说明 | 必填 | 默认值 |
|------|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key | ✅ | — |
| `OPENAI_API_KEY` | OpenAI API Key | ❌ | — |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | ❌ | — |
| `DOUBAO_ENDPOINT` | 豆包 Endpoint | ❌ | — |
| `VOLC_API_KEY` | 火山引擎 API Key | ❌ | — |
| `DEFAULT_MODEL` | 默认模型 | ❌ | `deepseek/deepseek-chat` |
| `WANXIANG_API_KEY` | API 服务的鉴权 Key | ❌ | — |
| `API_PORT` | API 服务端口 | ❌ | 8000 |
| `HF_ENDPOINT` | HuggingFace 镜像地址 | ❌ | `https://hf-mirror.com` |

---

## 常见问题

### Q: 启动后看到"未检测到有效的 API Key"

编辑 `.env` 文件，填入你的 DeepSeek API Key。

### Q: sentence-transformers 模型下载慢

项目默认使用 HuggingFace 镜像 `hf-mirror.com`，可通过 `HF_ENDPOINT` 环境变量切换。

### Q: 如何切换模型？

在对话界面右侧的"选择模型"下拉框中切换，或在 `conf/models.yaml` 中配置。

### Q: 数据存在哪里？

- 对话历史：内存中（L1）
- 会话摘要：`./data/memory/short_term/`
- 长期记忆：`./data/chroma/`（ChromaDB）
- 上传文件：`./data/uploads/`
- 审计日志：`./data/audit/`
