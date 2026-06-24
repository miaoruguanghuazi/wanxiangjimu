"""P2.1: DAG viz - simplified"""
with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add DAG section
old1 = '        gr.Markdown("#### \\U0001f4cb \\u6700\\u8fd1\\u5ba1\\u8ba1\\u4e8b\\u4ef6")'
new1 = '        gr.Markdown("#### \\U0001f916 \\u6700\\u8fd1 Agent \\u6267\\u884c\\u94fe\\u8def")\n        dag_html = gr.HTML(value="\\u23f3 \\u52a0\\u8f7d Agent \\u6570\\u636e...")\n\n        gr.Markdown("---")\n        gr.Markdown("#### \\U0001f4cb \\u6700\\u8fd1\\u5ba1\\u8ba1\\u4e8b\\u4ef6")"

if old1 in content:
    content = content.replace(old1, new1, 1)
    print("1. DAG section added")
else:
    print("1. Could not find audit section marker")

# 2. Update refresh function
old2 = "outputs=[overview_html, cb_html, sec_html, audit_html],"
new2 = "outputs=[overview_html, cb_html, sec_html, dag_html, audit_html],"

if old2 in content:
    # There might be multiple, replace carefully
    content = content.replace(old2, new2, 1)
    print("2. Outputs updated")
else:
    print("2. Could not find outputs")

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app_dashboard.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("P2.1 done")
