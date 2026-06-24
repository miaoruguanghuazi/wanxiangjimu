# 贡献指南

感谢你对万象积木 的兴趣！任何形式的贡献都欢迎。

## 如何贡献

### 报告 Bug

提交 Issue 时请包含：
- 运行环境（OS、Python 版本）
- 复现步骤
- 期望行为 vs 实际行为
- 相关日志

### 提交功能建议

描述清楚：
- 你想要的功能解决了什么问题
- 可选的实现思路
- 是否愿意参与实现

### 提交代码

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/my-feature`
3. 提交改动：`git commit -m 'feat: add my feature'`
4. 推送：`git push origin feature/my-feature`
5. 创建 Pull Request

## 开发环境

```bash
git clone https://github.com/your-username/wanxiang-ai.git
cd wanxiang-ai
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入 API Key
```

## 代码规范

- Python 3.12+
- 使用类型注解
- async/await 异步风格
- 保持单测覆盖率 > 80%
- 遵循 Google Python 代码风格

## 提交规范

使用 Conventional Commits：

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档
- `refactor:` 重构
- `test:` 测试
- `chore:` 构建/工具
