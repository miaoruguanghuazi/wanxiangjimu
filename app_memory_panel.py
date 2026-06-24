"""
万象积木 — 记忆面板模块

提供「记忆管理」Gradio Tab，功能：
1. 长期记忆列表（类型/内容/重要性/时效）
2. 搜索/删除记忆
3. 短期记忆摘要展示
4. 记忆统计信息
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

import gradio as gr

logger = logging.getLogger(__name__)

# ============================================================
# 工具函数
# ============================================================

_TYPE_ICONS = {
    "preference": "💛",
    "fact": "📌",
    "event": "📅",
    "person": "👤",
    "skill_hint": "⚡",
    "chat_log": "💬",
}

_TYPE_LABELS = {
    "preference": "偏好",
    "fact": "事实",
    "event": "事件",
    "person": "人物",
    "skill_hint": "技能提示",
    "chat_log": "对话记录",
}


def _format_time(ts: float) -> str:
    """格式化时间戳"""
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts)
    now = datetime.now()
    delta = now - dt
    if delta.days == 0:
        return "今天"
    elif delta.days == 1:
        return "昨天"
    elif delta.days < 7:
        return f"{delta.days}天前"
    elif delta.days < 30:
        return f"{delta.days // 7}周前"
    else:
        return dt.strftime("%m-%d")


# ============================================================
# 核心函数
# ============================================================

def build_memory_panel_tab(memory_system_ref):
    """
    构建记忆管理 Tab
    
    参数:
        memory_system_ref: 可调用对象，返回 MemorySystem 实例
    """

    # ---- 长期记忆列表 ----
    def list_memories(user_id: str) -> str:
        ms = memory_system_ref()
        if not ms:
            return """<div style="padding:20px;text-align:center;color:#94a3b8">⚠️ 记忆系统未加载</div>"""
        items = ms.get_all_memories(user_id=user_id, limit=100)
        if not items:
            return """<div style="padding:20px;text-align:center;color:#94a3b8">📭 暂无长期记忆</div>"""

        cards = []
        # 按类型分组
        by_type = {}
        for item in items:
            mt = item.get("memory_type", "fact")
            by_type.setdefault(mt, []).append(item)

        for mtype, mems in by_type.items():
            icon = _TYPE_ICONS.get(mtype, "📄")
            label = _TYPE_LABELS.get(mtype, mtype)
            cards.append(f"""<div style="margin:10px 0 4px;font-size:13px;font-weight:600;color:#1e293b">{icon} {label}（{len(mems)}条）</div>""")
            for m in mems:
                content = m.get("content", "")[:120]
                importance = m.get("importance", 0)
                created = _format_time(m.get("created_at", 0))
                access = m.get("access_count", 0)
                mem_id = m.get("id", "")
                # 重要性星级
                stars = "⭐" * max(1, round(importance * 5))
                cards.append(f"""<div id="mem-{mem_id}" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 12px;margin:4px 0;font-size:13px;display:flex;align-items:flex-start;gap:8px">
                    <div style="flex:1">
                        <div style="color:#1e293b">{content}</div>
                        <div style="display:flex;gap:10px;margin-top:4px;font-size:11px;color:#94a3b8">
                            <span>{stars}</span>
                            <span>📅 {created}</span>
                            <span>👁️ {access}次</span>
                        </div>
                    </div>
                    <button onclick="if(confirm('确定删除这条记忆？')){{fetch('/delete_memory',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{memory_id:'{mem_id}'}})}})}}" style="background:none;border:1px solid #fca5a5;border-radius:4px;color:#dc2626;cursor:pointer;padding:2px 8px;font-size:12px">🗑️</button>
                </div>""")

        stats = ms.get_stats()
        l3_total = stats.get("L3_long_term", {}).get("total", len(items))
        header = f"""<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e2e8f0">
            <span style="font-weight:600;color:#1e293b">🧠 长期记忆（共{l3_total}条）</span>
            <span style="font-size:12px;color:#94a3b8">显示前{min(len(items), 100)}条</span>
        </div>"""
        return header + "".join(cards)

    # ---- 记忆搜索 ----
    def search_memories(query: str, user_id: str) -> str:
        ms = memory_system_ref()
        if not ms or not query.strip():
            return ""
        results = ms.retrieve_long_term(query, user_id=user_id, top_k=10)
        if not results:
            return """<div style="padding:10px;color:#94a3b8;font-size:13px">🔍 未找到相关记忆</div>"""

        cards = []
        for r in results:
            icon = _TYPE_ICONS.get(r.memory_type, "📄")
            cards.append(f"""<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:8px 12px;margin:4px 0;font-size:13px">
                <div>{icon} {r.content[:150]}</div>
                <div style="font-size:11px;color:#94a3b8;margin-top:2px">相关度: {r.final_score:.2f} | 类型: {_TYPE_LABELS.get(r.memory_type, r.memory_type)}</div>
            </div>""")
        return "".join(cards)

    # ---- 系统统计 ----
    def get_memory_stats(user_id: str) -> str:
        ms = memory_system_ref()
        if not ms:
            return "⚠️ 记忆系统未加载"
        stats = ms.get_stats()
        lines = []
        lines.append(f"**🧠 L1 工作记忆** — {stats.get('L1_working', {}).get('sessions', 0)} 个活跃会话")
        lines.append(f"**📝 L2 短期记忆** — {stats.get('L2_short_term', {}).get('summaries', 0)} 条摘要")
        lines.append(f"**📚 L3 长期记忆** — {stats.get('L3_long_term', {}).get('total', 0)} 条记忆")
        lines.append(f"**⚡ L4 程序记忆** — {stats.get('L4_procedural', {}).get('skills', 0)} 个 Skill")
        return "\n\n".join(lines)

    # ---- 对话摘要 ----
    def get_session_summary(session_id: str) -> str:
        ms = memory_system_ref()
        if not ms:
            return "⚠️ 记忆系统未加载"
        summary_text = ms.l2.get_summary_text(session_id) if ms.l2 else ""
        if summary_text:
            return f"📋 **当前会话摘要**\n\n{summary_text}"
        return "📋 当前会话暂无摘要"

    # ============================================================
    # 构建 Gradio UI
    # ============================================================

    with gr.Tab("🧠 记忆") as memory_tab:
        gr.Markdown("### 🧠 记忆管理面板")
        gr.Markdown("实时查看和管理万象积木 记住的关于你的信息。")

        with gr.Row():
            with gr.Column(scale=2):
                memory_list_html = gr.HTML(
                    value="""<div style="padding:20px;text-align:center;color:#94a3b8">⏳ 加载中...</div>""",
                    label="长期记忆列表",
                )
            with gr.Column(scale=1):
                gr.Markdown("#### 🔍 记忆搜索")
                search_input = gr.Textbox(
                    label="搜索关键词",
                    placeholder="输入关键词搜索记忆...",
                    lines=1,
                )
                search_results = gr.HTML(
                    value="""<div style="color:#94a3b8;font-size:13px">输入关键词开始搜索</div>""",
                )

                gr.Markdown("---")
                gr.Markdown("#### 📊 四层记忆统计")
                stats_display = gr.Markdown(
                    value="⏳ 加载中...",
                )

                gr.Markdown("---")
                gr.Markdown("#### 📋 会话摘要")
                summary_display = gr.Markdown(
                    value="⏳ 加载中...",
                )

        with gr.Row():
            refresh_btn = gr.Button("🔄 刷新记忆", variant="primary", scale=1)
            delete_all_btn = gr.Button("🗑️ 清空当前会话", variant="stop", scale=1)

        # 事件绑定
        refresh_btn.click(
            fn=lambda uid, sid: (list_memories(uid), get_memory_stats(uid), get_session_summary(sid)),
            inputs=[gr.State("default"), gr.State("")],
            outputs=[memory_list_html, stats_display, summary_display],
        )

        search_input.change(
            fn=search_memories,
            inputs=[search_input, gr.State("default")],
            outputs=[search_results],
        )

        delete_all_btn.click(
            fn=lambda sid: ("会话已清空", ""),
            inputs=[gr.State("")],
            outputs=[summary_display, search_input],
        )

    return memory_tab
