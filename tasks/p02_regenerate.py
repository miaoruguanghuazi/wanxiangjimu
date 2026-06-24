"""P0.2: Complete regenerate/edit functionality"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add regenerate/edit buttons after clear_btn
old_ui = """                    clear_btn = gr.Button("\\U0001f5d1\\ufe0f 清空", variant="secondary", scale=1)"""

# Try with the escaped emoji that might be in the file
old_ui_alt = '                    clear_btn = gr.Button("\U0001f5d1\ufe0f 清空", variant="secondary", scale=1)'
new_ui = '                    clear_btn = gr.Button("\U0001f5d1\ufe0f 清空", variant="secondary", scale=1)\n                with gr.Row():\n                    regenerate_btn = gr.Button("\U0001f504 重新生成", size="sm", visible=False)\n                    edit_btn = gr.Button("\u270f\ufe0f 编辑上条", size="sm", visible=False)'

if old_ui_alt in content:
    content = content.replace(old_ui_alt, new_ui, 1)
    print("1. Added regenerate/edit buttons")
else:
    print("1. Could not find clear_btn")

# 2. Add regenerate and edit event handlers after the show/hide buttons
old_events = """        # 发送后显示重新生成/编辑按钮
        def show_action_btns():
            return gr.update(visible=True), gr.update(visible=True)
        def hide_action_btns():
            return gr.update(visible=False), gr.update(visible=False)

        send_btn.click(fn=show_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])
        clear_btn.click(fn=hide_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])"""

new_events = """        # ===== 重新生成 / 编辑 =====
        def show_action_btns():
            return gr.update(visible=True), gr.update(visible=True)
        def hide_action_btns():
            return gr.update(visible=False), gr.update(visible=False)

        send_btn.click(fn=show_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])
        clear_btn.click(fn=hide_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])

        def do_regenerate(sid):
            """重新生成：找到最后一条用户消息，放回输入框"""
            ms = _get_ms()
            if ms:
                msgs = ms.l1.get_messages(sid)
                for m in reversed(msgs):
                    if m.get("role") == "user":
                        return m.get("content", "")
            return ""
        regenerate_btn.click(fn=do_regenerate, inputs=[session_id], outputs=[msg_input])

        def do_edit(sid):
            """编辑上条：把最后一条用户消息放回输入框"""
            return do_regenerate(sid)
        edit_btn.click(fn=do_edit, inputs=[session_id], outputs=[msg_input])"""

if old_events in content:
    content = content.replace(old_events, new_events, 1)
    print("2. Added regenerate/edit event handlers")
else:
    print("2. Could not find events section")

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"\nP0.2 done ({'full' if old_ui_alt in content and old_events in content else 'partial'})")
