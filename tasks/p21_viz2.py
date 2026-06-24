"""P2.1: Add DAG section to dashboard - direct file modification"""
import re

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find where to insert the DAG section
insert_idx = None
output_idx = None

for i, line in enumerate(lines):
    # Find the line with "最近审计事件"
    if '最近审计事件' in line and '####' in line:
        insert_idx = i
    # Find the output list for refresh button
    if 'outputs=[' in line and 'overview_html' in line and 'audit_html' in line:
        output_idx = i

if insert_idx:
    dag_lines = [
        '        gr.Markdown("---")\n',
        '        gr.Markdown("#### 🤖 最近 Agent 执行链路")\n',
        '        dag_html = gr.HTML(value="⏳ 加载 Agent 数据...")\n',
        '\n',
    ]
    for j, dl in enumerate(reversed(dag_lines)):
        lines.insert(insert_idx, dl)
    print(f"1. DAG section inserted at line {insert_idx}")
else:
    print("1. Could not find audit section")

if output_idx:
    old_line = lines[output_idx]
    new_line = old_line.replace('audit_html', 'dag_html, audit_html')
    lines[output_idx] = new_line
    print(f"2. Outputs updated at line {output_idx}")
else:
    print("2. Could not find outputs")

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("P2.1 done")
