"""P0.3: Add chat export button to app.py"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add export button next to clear_btn
old = '                    clear_btn = gr.Button("\\U0001f5d1\\ufe0f 清空", variant="secondary", scale=1)'
new = '                    clear_btn = gr.Button("\\U0001f5d1\\ufe0f 清空", variant="secondary", scale=1)\n                    export_btn = gr.Button("\\U0001f4e4 导出", size="sm", scale=1)'

if old in content:
    content = content.replace(old, new, 1)
    print("1. Export button added")
else:
    print("1. Could not find clear_btn")

# Add export handler
old_events = """        clear_btn.click(
            clear_chat,
            inputs=[session_id],
            outputs=[chatbot, memory_display],
        )"""
new_events = """        clear_btn.click(
            clear_chat,
            inputs=[session_id],
            outputs=[chatbot, memory_display],
        )

        def export_chat(sid):
            import json, datetime
            ms = _get_ms()
            if not ms:
                return "No chat data", None
            msgs = ms.l1.get_messages(sid)
            if not msgs:
                return "No messages", None
            export = {
                "session_id": sid,
                "exported_at": datetime.datetime.now().isoformat(),
                "messages": [{"role": m.get("role"), "content": m.get("content")} for m in msgs]
            }
            json_str = json.dumps(export, ensure_ascii=False, indent=2)
            # Also create a markdown version
            md = f"# Chat Export: {sid}\\n\\n"
            for m in msgs:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                md += f"## {role}\\n{content}\\n\\n"
            return md, json_str

        export_btn.click(
            fn=export_chat,
            inputs=[session_id],
            outputs=[memory_display, msg_input],
        )"""

if old_events in content:
    content = content.replace(old_events, new_events, 1)
    print("2. Export handler added")
else:
    print("2. Could not find clear events")

if 'old' in dir() or 'export' in content:
    with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("P0.3 done")
