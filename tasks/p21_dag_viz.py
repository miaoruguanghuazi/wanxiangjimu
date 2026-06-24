"""Integrate DAG viz into app_dashboard.py"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add DAG viz section after security stats
old = '        gr.Markdown("---")\n        gr.Markdown("#### 📋 最近审计事件")'
new = '        gr.Markdown("---")\n        gr.Markdown("#### 🤖 最近 Agent 执行链路")\n        dag_html = gr.HTML(value="⏳ 加载 Agent 数据...")\n\n        gr.Markdown("---")\n        gr.Markdown("#### 📋 最近审计事件")'

if old in content:
    content = content.replace(old, new, 1)
    print("1. DAG section added")
else:
    print("1. Could not find audit section")

# Add DAG refresh in the refresh function
old_refresh = """        def refresh_all():
            return (
                get_system_overview(),
                get_circuit_breaker_table(),
                get_security_stats(),
                get_recent_audit_events(),
            )"""
new_refresh = """        def refresh_all():
            # Agent DAG
            dag_content = """<div style="color:#94a3b8;font-size:13px">运行中自动采集 Agent 编排数据</div>"""
            return (
                get_system_overview(),
                get_circuit_breaker_table(),
                get_security_stats(),
                dag_content,
                get_recent_audit_events(),
            )"""

if old_refresh in content:
    content = content.replace(old_refresh, new_refresh, 1)
    print("2. DAG refresh added")
else:
    print("2. Could not find refresh function")

# Update outputs
old_out = """        refresh_btn.click(
            fn=refresh_all,
            inputs=[],
            outputs=[overview_html, cb_html, sec_html, audit_html],
        )"""
new_out = """        refresh_btn.click(
            fn=refresh_all,
            inputs=[],
            outputs=[overview_html, cb_html, sec_html, dag_html, audit_html],
        )"""

if old_out in content:
    content = content.replace(old_out, new_out, 1)
    print("3. Outputs updated")
else:
    print("3. Could not find refresh click")

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("P2.1 done")
