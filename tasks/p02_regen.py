"""P0.2: Regenerate/edit functionality"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Find and replace the events section
marker = """        # \u53d1\u9001\u540e\u663e\u793a\u91cd\u65b0\u751f\u6210/\u7f16\u8f91\u6309\u94ae
        def show_action_btns():
            return gr.update(visible=True), gr.update(visible=True)
        def hide_action_btns():
            return gr.update(visible=False), gr.update(visible=False)

        send_btn.click(fn=show_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])
        clear_btn.click(fn=hide_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])"""

replacement = """        # ===== \u91cd\u65b0\u751f\u6210 / \u7f16\u8f91 =====
        def show_action_btns():
            return gr.update(visible=True), gr.update(visible=True)
        def hide_action_btns():
            return gr.update(visible=False), gr.update(visible=False)

        send_btn.click(fn=show_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])
        clear_btn.click(fn=hide_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])

        def do_regenerate(sid):
            ms = _get_ms()
            if ms:
                msgs = ms.l1.get_messages(sid)
                for m in reversed(msgs):
                    if m.get("role") == "user":
                        return m.get("content", "")
            return ""

        regenerate_btn.click(fn=do_regenerate, inputs=[session_id], outputs=[msg_input])
        edit_btn.click(fn=do_regenerate, inputs=[session_id], outputs=[msg_input])"""

if marker in content:
    content = content.replace(marker, replacement, 1)
    print("1. Regenerate/edit events added")
else:
    print("1. ERROR: Could not find events section marker")

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Done")
