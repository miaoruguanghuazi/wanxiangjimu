"""P2.2: Add multi-user isolation - user_id state + dropdown"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the state section and add user_id state
insert_idx = None
for i, line in enumerate(lines):
    if 'last_user_msg = gr.State' in line:
        insert_idx = i + 1
        break

if insert_idx:
        lines.insert(insert_idx, '        user_id = gr.State("default")  # 当前用户\n')
        print(f"1. user_id state added at line {insert_idx}")
else:
    print("1. Could not find state section")

# Add user dropdown after the session selector
for i, line in enumerate(lines):
    if 'session_selector' in line and 'gr.Dropdown' in line:
        # Add user dropdown after the session row
        for j in range(i, min(i+10, len(lines))):
            if 'del_session_btn' in lines[j]:
                lines.insert(j+1, '                    user_selector = gr.Dropdown(\n')
                lines.insert(j+2, '                        choices=["default", "user1", "user2"],\n')
                lines.insert(j+3, '                        value="default",\n')
                lines.insert(j+4, '                        label="用户",\n')
                lines.insert(j+5, '                        interactive=True,\n')
                lines.insert(j+6, '                        scale=1,\n')
                lines.insert(j+7, '                        min_width=80,\n')
                lines.insert(j+8, '                    )\n')
                print("2. User dropdown added")
                break
        break

# Update auto_extract_and_store call to use user_id
for i, line in enumerate(lines):
    if 'auto_extract_and_store' in line and 'user_id="default"' in line:
        lines[i] = line.replace('user_id="default"', 'user_id=user_id')
        print(f"3. user_id wired to auto_extract at line {i+1}")
        break

# Update build_prompt calls
for i, line in enumerate(lines):
    if 'ms.build_prompt(' in line and 'user_id' not in line:
        lines[i] = line.replace(')', ', user_id=user_id)')
        print(f"4. user_id wired to build_prompt at line {i+1}")
        break

# Wire user_selector to user_id state
for i, line in enumerate(lines):
    if 'session_selector.change' in line and i > 100:
        lines.insert(i, '        user_selector.change(fn=lambda u: u, inputs=[user_selector], outputs=[user_id])\n')
        print(f"5. user_selector event added at line {i+1}")
        break

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("P2.2 done")
