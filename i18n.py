"""
万象积木 — 国际化支持模块 (i18n)

用法:
    from i18n import _
    print(_("welcome"))  # 输出当前语言的欢迎语
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ============================================================
# 翻译字典
# ============================================================

TRANSLATIONS = {
    "zh": {
        # 通用
        "app_name": "万象积木",
        "tagline": "多模型路由 · Agent编排 · RAG知识库 · 四层记忆 · 安全防护",
        "footer": "多模型路由 · 四层记忆 · Agent编排 · RAG · 安全防护",

        # Tab 名称
        "tab_chat": "💬 对话",
        "tab_knowledge": "📚 知识库",
        "tab_memory": "🧠 记忆",
        "tab_dashboard": "📊 系统",
        "tab_tools": "🛠️ 工具",

        # 对话
        "input_placeholder": "输入你的问题，按回车发送...",
        "btn_send": "🚀 发送",
        "btn_clear": "🗑️ 清空",
        "btn_regenerate": "🔄 重新生成",
        "btn_edit": "✏️ 编辑上条",
        "btn_new_session": "➕ 新会话",
        "btn_delete_session": "🗑️ 删除",
        "btn_export": "📤 导出",
        "session_selector": "会话列表",
        "user_selector": "用户",
        "model_selector": "选择模型",
        "temperature": "温度",
        "system_prompt": "系统提示词",
        "thinking": "⏳ 正在思考...",
        "no_content": "⚠️ 模型未返回内容",

        # 记忆面板
        "memory_panel_title": "🧠 记忆管理面板",
        "memory_panel_desc": "实时查看和管理万象积木 记住的关于你的信息。",
        "memory_search": "搜索关键词",
        "memory_search_placeholder": "输入关键词搜索记忆...",
        "memory_no_data": "📭 暂无长期记忆",
        "memory_stats": "📊 四层记忆统计",
        "memory_summary": "📋 会话摘要",
        "memory_refresh": "🔄 刷新记忆",

        # 系统仪表盘
        "dashboard_title": "📊 系统运行仪表盘",
        "circuit_breaker": "⚡ 熔断器状态",
        "security_stats": "🛡️ 安全体系统计",
        "audit_events": "📋 最近审计事件",
        "agent_dag": "🤖 最近 Agent 执行链路",
        "btn_refresh": "🔄 刷新仪表盘",

        # 知识库
        "kb_title": "📤 上传文档",
        "kb_supported": "支持 PDF / Word / Markdown / HTML / TXT / CSV",
        "kb_upload_btn": "📥 上传并索引",
        "kb_query": "🔍 知识库问答",
        "kb_query_placeholder": "基于知识库内容回答问题...",

        # 错误提示
        "error_prefix": "⚠️ 出错了",
        "error_hint": "💡 可能的原因：\n1. API Key 是否正确？→ 编辑 .env 文件\n2. 网络连接是否正常？→ 检查代理/防火墙\n3. 模型服务是否可用？→ 在「系统」页查看熔断状态",
        "error_retry": "🔧 尝试：点击清空按钮重新开始对话",
    },

    "en": {
        # General
        "app_name": "WanXiang JiMu Assistant",
        "tagline": "Multi-Model Router · Agent Orchestrator · RAG · 4-Layer Memory · Security",
        "footer": "Multi-Model Router · 4-Layer Memory · Agent · RAG · Security",

        # Tabs
        "tab_chat": "💬 Chat",
        "tab_knowledge": "📚 Knowledge",
        "tab_memory": "🧠 Memory",
        "tab_dashboard": "📊 System",
        "tab_tools": "🛠️ Tools",

        # Chat
        "input_placeholder": "Type your message and press Enter...",
        "btn_send": "🚀 Send",
        "btn_clear": "🗑️ Clear",
        "btn_regenerate": "🔄 Regenerate",
        "btn_edit": "✏️ Edit",
        "btn_new_session": "➕ New Session",
        "btn_delete_session": "🗑️ Delete",
        "btn_export": "📤 Export",
        "session_selector": "Sessions",
        "user_selector": "User",
        "model_selector": "Model",
        "temperature": "Temperature",
        "system_prompt": "System Prompt",
        "thinking": "⏳ Thinking...",
        "no_content": "⚠️ Model returned no content",

        # Memory panel
        "memory_panel_title": "🧠 Memory Management",
        "memory_panel_desc": "View and manage what WanXiang JiMu remembers about you.",
        "memory_search": "Search",
        "memory_search_placeholder": "Search memories...",
        "memory_no_data": "📭 No long-term memories yet",
        "memory_stats": "📊 Memory Statistics",
        "memory_summary": "📋 Session Summary",
        "memory_refresh": "🔄 Refresh",

        # Dashboard
        "dashboard_title": "📊 System Dashboard",
        "circuit_breaker": "⚡ Circuit Breaker",
        "security_stats": "🛡️ Security Stats",
        "audit_events": "📋 Recent Events",
        "agent_dag": "🤖 Agent Execution DAG",
        "btn_refresh": "🔄 Refresh",

        # Knowledge base
        "kb_title": "📤 Upload Documents",
        "kb_supported": "Supports PDF / Word / Markdown / HTML / TXT / CSV",
        "kb_upload_btn": "📥 Upload & Index",
        "kb_query": "🔍 Knowledge Query",
        "kb_query_placeholder": "Ask questions based on knowledge base...",

        # Error messages
        "error_prefix": "⚠️ Error",
        "error_hint": "💡 Possible causes:\n1. API Key incorrect? → Edit .env file\n2. Network issue? → Check proxy/firewall\n3. Model unavailable? → Check circuit breaker status",
        "error_retry": "🔧 Try: click Clear to restart the conversation",
    },
}


class I18n:
    """国际化管理器"""

    def __init__(self, lang: str = "zh"):
        self.lang = lang if lang in TRANSLATIONS else "zh"

    def set_lang(self, lang: str):
        if lang in TRANSLATIONS:
            self.lang = lang

    def get(self, key: str, **kwargs) -> str:
        """获取翻译文本"""
        translations = TRANSLATIONS.get(self.lang, TRANSLATIONS["zh"])
        text = translations.get(key, key)
        if kwargs:
            text = text.format(**kwargs)
        return text


# 全局实例
_i18n = I18n()


def set_language(lang: str):
    """设置全局语言"""
    _i18n.set_lang(lang)


def _(key: str, **kwargs) -> str:
    """获取当前语言的翻译"""
    return _i18n.get(key, **kwargs)


def get_available_languages() -> list[str]:
    """获取可用语言列表"""
    return list(TRANSLATIONS.keys())
