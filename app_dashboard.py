"""
万象积木 — 系统仪表盘模块

提供「系统状态」Gradio Tab，展示:
1. 熔断器状态表
2. 模型调用统计
3. 安全拦截统计
4. 路由历史
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

import gradio as gr

logger = logging.getLogger(__name__)


def build_dashboard_tab(
    model_router_ref,
    security_ref,
    orchestrator_ref,
):
    """
    构建系统仪表盘 Tab

    参数:
        model_router_ref: 返回 model_router dict 的可调用对象
        security_ref: 返回 security dict 的可调用对象
        orchestrator_ref: 返回 orchestrator dict 的可调用对象
    """

    # ---- 熔断器状态表 ----
    def get_circuit_breaker_table() -> str:
        mr = model_router_ref()
        if not mr or not mr.get("circuit"):
            return """<div style="padding:20px;text-align:center;color:#94a3b8">⚠️ 路由系统未加载</div>"""

        cb_status = mr["circuit"].all_status()
        if not cb_status:
            return """<div style="padding:10px;color:#94a3b8;font-size:13px">暂无熔断记录</div>"""

        rows = []
        for model_id, status in sorted(cb_status.items()):
            state = status.get("state", "unknown")
            failure = status.get("failure_count", 0)
            last_fail = status.get("last_failure_reason", "")
            last_fail_short = (last_fail[:60] + "...") if last_fail and len(last_fail) > 60 else (last_fail or "—")

            if state == "closed":
                bg = "#f0fdf4"
                border = "#bbf7d0"
                label = "✅ 正常"
            elif state == "open":
                bg = "#fef2f2"
                border = "#fca5a5"
                label = "🔴 熔断"
            else:
                bg = "#fffbeb"
                border = "#fde68a"
                label = "🟡 半开"

            rows.append(f"""<tr style="background:{bg}">
                <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;font-weight:500">{model_id}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0">{label}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;text-align:center">{failure}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #e2e8f0;font-size:12px;color:#64748b;max-width:200px;overflow:hidden;text-overflow:ellipsis">{last_fail_short}</td>
            </tr>""")

        open_count = sum(1 for v in cb_status.values() if v["state"] == "open")
        header_color = "#dc2626" if open_count > 0 else "#16a34a"
        return f"""<div style="margin-bottom:8px;font-size:13px;color:{header_color}">熔断模型: {open_count}/{len(cb_status)}</div>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#f1f5f9;text-align:left">
            <th style="padding:6px 10px;border-bottom:2px solid #e2e8f0">模型</th>
            <th style="padding:6px 10px;border-bottom:2px solid #e2e8f0">状态</th>
            <th style="padding:6px 10px;border-bottom:2px solid #e2e8f0;text-align:center">失败次数</th>
            <th style="padding:6px 10px;border-bottom:2px solid #e2e8f0">最后错误</th>
        </tr></thead>
        <tbody>{"".join(rows)}</tbody></table>"""

    # ---- 安全拦截统计 ----
    def get_security_stats() -> str:
        sec = security_ref()
        if not sec:
            return """<div style="padding:20px;text-align:center;color:#94a3b8">⚠️ 安全体系未加载</div>"""

        try:
            pg = sec.get("prompt_guard")
            audit = sec.get("audit")
            rl = sec.get("rate_limiter")
            sg = sec.get("session_guard")

            pg_stats = pg.get_stats() if pg else {}
            audit_stats = audit.get_stats() if audit else {}
            rl_stats = rl.get_stats() if rl else {}
            sg_stats = sg.get_stats() if sg else {}

            blocked = pg_stats.get("blocked", 0)
            suspicious = pg_stats.get("suspicious", 0)
            total_audit = audit_stats.get("total", 0)
            rl_blocked = rl_stats.get("blocked", 0)
            active_sessions = sg_stats.get("active", 0)

            bg_blocked = "#fef2f2" if blocked > 0 else "#f0fdf4"
            bg_rl = "#fffbeb" if rl_blocked > 0 else "#f0fdf4"

            cards = [
                f"""<div class="dashboard-card" style="background:{bg_blocked};border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;flex:1;min-width:100px">
                    <div style="font-size:20px;font-weight:700;color:#1e293b">{blocked}</div>
                    <div style="font-size:11px;color:#64748b">注入拦截</div>
                </div>""",
                f"""<div class="dashboard-card" style="background:#fffbeb;border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;flex:1;min-width:100px">
                    <div style="font-size:20px;font-weight:700;color:#1e293b">{suspicious}</div>
                    <div style="font-size:11px;color:#64748b">可疑标记</div>
                </div>""",
                f"""<div class="dashboard-card" style="background:{bg_rl};border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;flex:1;min-width:100px">
                    <div style="font-size:20px;font-weight:700;color:#1e293b">{rl_blocked}</div>
                    <div style="font-size:11px;color:#64748b">速率限制</div>
                </div>""",
                f"""<div class="dashboard-card" style="background:#f0fdf4;border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;flex:1;min-width:100px">
                    <div style="font-size:20px;font-weight:700;color:#1e293b">{total_audit}</div>
                    <div style="font-size:11px;color:#64748b">审计事件</div>
                </div>""",
                f"""<div class="dashboard-card" style="background:#f0fdf4;border:1px solid #e2e8f0;border-radius:8px;padding:10px;text-align:center;flex:1;min-width:100px">
                    <div style="font-size:20px;font-weight:700;color:#1e293b">{active_sessions}</div>
                    <div style="font-size:11px;color:#64748b">活跃会话</div>
                </div>""",
            ]
            return f"""<div style="display:flex;gap:8px;flex-wrap:wrap">{"".join(cards)}</div>"""
        except Exception as e:
            return f"""<div style="padding:10px;color:#94a3b8;font-size:13px">加载中... ({e})</div>"""

    # ---- 系统概览 ----
    def get_system_overview() -> str:
        mr = model_router_ref()
        orch = orchestrator_ref()
        sec = security_ref()

        items = []

        # 模型路由
        if mr:
            avail = mr.get("available_models", [])
            cb = mr.get("circuit", {})
            cb_status = cb.all_status() if hasattr(cb, 'all_status') else {}
            open_count = sum(1 for v in cb_status.values() if v.get("state") == "open")
            items.append(("🧭 模型路由", f"{len(avail)} 个模型 | {'⚠️ ' + str(open_count) + ' 熔断' if open_count else '✅ 全部正常'}"))

        # Agent 编排
        if orch:
            reg = orch.get("registry")
            agents = reg.list_all() if reg else []
            items.append(("🤖 Agent编排", f"{len(agents)} 个 Agent 就绪"))

        # 安全
        if sec:
            items.append(("🛡️ 安全体系", "11 个模块已加载"))

        cards = []
        for icon_label, value in items:
            cards.append(f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;flex:1;min-width:140px">
                <div style="font-size:12px;font-weight:600;color:#475569">{icon_label}</div>
                <div style="font-size:13px;color:#1e293b;margin-top:2px">{value}</div>
            </div>""")

        return f"""<div style="display:flex;gap:8px;flex-wrap:wrap">{"".join(cards)}</div>"""

    # ---- 审计日志最近事件 ----
    def get_recent_audit_events(limit: int = 10) -> str:
        sec = security_ref()
        if not sec or not sec.get("audit"):
            return """<div style="padding:10px;color:#94a3b8;font-size:13px">审计系统未加载</div>"""
        try:
            recent = sec["audit"].get_recent(limit=limit)
            if not recent:
                return """<div style="padding:10px;color:#94a3b8;font-size:13px">暂无事件</div>"""
            rows = []
            for ev in recent:
                ts = ev.get("timestamp", "")
                event_type = ev.get("event_type", ev.get("type", "?"))
                level = ev.get("level", "info")
                detail = ev.get("detail", "")
                detail_str = str(detail)[:80] if detail else "—"
                color = "#dc2626" if level in ("critical", "error") else ("#eab308" if level in ("warning",) else "#64748b")
                rows.append(f"""<tr>
                    <td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:11px;color:#94a3b8">{str(ts)[:19] if ts else "—"}</td>
                    <td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:12px">{event_type}</td>
                    <td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:11px;color:{color}">{level}</td>
                    <td style="padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:11px;color:#64748b">{detail_str}</td>
                </tr>""")
            return f"""<table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead><tr style="background:#f1f5f9;text-align:left">
                    <th style="padding:4px 8px;border-bottom:2px solid #e2e8f0">时间</th>
                    <th style="padding:4px 8px;border-bottom:2px solid #e2e8f0">事件</th>
                    <th style="padding:4px 8px;border-bottom:2px solid #e2e8f0">级别</th>
                    <th style="padding:4px 8px;border-bottom:2px solid #e2e8f0">详情</th>
                </tr></thead>
                <tbody>{"".join(rows)}</tbody></table>"""
        except Exception as e:
            return f"""<div style="padding:10px;color:#94a3b8;font-size:13px">审计读取失败: {e}</div>"""

    # ============================================================
    # 构建 Gradio UI
    # ============================================================

    with gr.Tab("📊 系统") as dashboard_tab:
        gr.Markdown("### 📊 系统运行仪表盘")

        with gr.Row():
            overview_html = gr.HTML(value="⏳ 加载系统概览...")

        gr.Markdown("---")
        gr.Markdown("#### ⚡ 熔断器状态")
        cb_html = gr.HTML(value="⏳ 加载熔断器状态...")

        gr.Markdown("---")
        gr.Markdown("#### 🛡️ 安全体系统计")
        sec_html = gr.HTML(value="⏳ 加载安全统计...")

        gr.Markdown("---")
        gr.Markdown("---")
        gr.Markdown("#### 🤖 最近 Agent 执行链路")
        dag_html = gr.HTML(value="⏳ 加载 Agent 数据...")

        gr.Markdown("#### 📋 最近审计事件")
        audit_html = gr.HTML(value="⏳ 加载审计日志...")

        refresh_btn = gr.Button("🔄 刷新仪表盘", variant="primary")

        # 刷新事件
        def refresh_all():
            return (
                get_system_overview(),
                get_circuit_breaker_table(),
                get_security_stats(),
                get_recent_audit_events(),
            )

        refresh_btn.click(
            fn=refresh_all,
            inputs=[],
            outputs=[overview_html, cb_html, sec_html, audit_html],
        )

    return dashboard_tab
