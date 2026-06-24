"""
Agent 执行过程 DAG 可视化

将 OrchestrationPlan 渲染为 HTML 有向无环图，
展示 Agent 编排的完整链路。
"""

from __future__ import annotations


def render_plan_dag(plan) -> str:
    """
    将编排计划渲染为 HTML DAG 图

    参数:
        plan: OrchestrationPlan 实例 (或具有 nodes/plan_id/mode 属性的对象)

    返回:
        HTML 字符串
    """
    if not plan or not plan.nodes:
        return '<div style="color:#94a3b8;font-size:13px">暂无编排数据</div>'

    mode_labels = {
        "single": "单任务",
        "sequential": "串行链",
        "fanout": "并行扇出",
        "human_approval": "人工审批",
        "conditional": "条件分支",
    }
    mode_name = mode_labels.get(
        plan.mode.value if hasattr(plan.mode, 'value') else str(plan.mode),
        str(getattr(plan, 'mode', '?'))
    )

    # Build node HTML
    nodes_html = ""
    edges = []

    for node in plan.nodes:
        node_id = node.node_id
        agent = node.agent_id
        action = node.action[:30]
        status = node.status.value if hasattr(node.status, 'value') else str(getattr(node.status, 'pending'))
        duration = ""
        if hasattr(node, 'duration_seconds') and node.duration_seconds is not None:
            duration = f"{node.duration_seconds:.1f}s"

        # Color by status
        colors = {
            "success": "#16a34a",
            "failed": "#dc2626",
            "running": "#2563eb",
            "pending": "#94a3b8",
            "waiting": "#d97706",
            "cancelled": "#6b7280",
            "timeout": "#dc2626",
        }
        bg_colors = {
            "success": "#f0fdf4",
            "failed": "#fef2f2",
            "running": "#eff6ff",
            "pending": "#f8fafc",
            "waiting": "#fffbeb",
            "cancelled": "#f9fafb",
            "timeout": "#fef2f2",
        }
        color = colors.get(status, "#94a3b8")
        bg = bg_colors.get(status, "#f8fafc")

        nodes_html += f"""<div id="node-{node_id}" style="background:{bg};border:1px solid {color};border-radius:8px;padding:8px 12px;margin:4px 0;font-size:12px;display:flex;align-items:center;gap:8px">
            <div style="width:10px;height:10px;border-radius:50%;background:{color};flex-shrink:0"></div>
            <div style="flex:1">
                <div style="font-weight:600;color:#1e293b">{agent}</div>
                <div style="color:#64748b;font-size:11px">{action}</div>
            </div>
            <div style="text-align:right">
                <div style="font-size:11px;color:{color};font-weight:500">{status}</div>
                <div style="font-size:10px;color:#94a3b8">{duration}</div>
            </div>
        </div>"""

        if hasattr(node, 'depends_on') and node.depends_on:
            for dep in node.depends_on:
                edges.append((dep, node_id))

    # Build edge arrows (simple version)
    edges_html = ""
    if edges:
        edges_html = '<div style="margin:4px 0;padding-left:16px;border-left:2px solid #e2e8f0">'
        for src, dst in edges:
            edges_html += f'<div style="font-size:11px;color:#94a3b8;padding:2px 0">{src} → {dst}</div>'
        edges_html += '</div>'

    # Agent colors
    agent_colors = {
        "code_agent": "#3b82f6",
        "data_agent": "#8b5cf6",
        "research_agent": "#10b981",
        "general_agent": "#f59e0b",
        "ops_agent": "#ef4444",
        "design_agent": "#ec4899",
    }

    plan_id = getattr(plan, 'plan_id', '?')[:8]

    html = f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:12px;font-size:13px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #e2e8f0">
            <span style="font-weight:600;color:#1e293b">🤖 Agent 编排 DAG</span>
            <span style="color:#94a3b8;font-size:11px">{mode_name} · {len(plan.nodes)} 节点 · {plan_id}</span>
        </div>
        {nodes_html}
        {edges_html}
    </div>"""

    return html


def render_execution_history(history: list) -> str:
    """渲染执行历史列表"""
    if not history:
        return '<div style="color:#94a3b8;font-size:13px">暂无执行记录</div>'

    items = ""
    for h in history[-10:]:  # 最近10条
        plan_id = h.get("plan_id", "?")[:8]
        mode = h.get("mode", "?")
        nodes = h.get("node_count", 0)
        status = h.get("status", "?")
        color = "#16a34a" if status == "success" else "#dc2626" if status == "failed" else "#94a3b8"

        items += f"""<div style="display:flex;align-items:center;gap:6px;padding:4px 8px;border-bottom:1px solid #f1f5f9;font-size:12px">
            <span style="color:{color};font-weight:500">{status}</span>
            <span style="color:#64748b;flex:1">{mode} · {nodes} 节点</span>
            <span style="color:#94a3b8;font-size:11px">{plan_id}</span>
        </div>"""

    return f"""<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px;font-size:13px">
        <div style="font-weight:600;color:#1e293b;margin-bottom:4px">📋 执行历史</div>
        {items}
    </div>"""
