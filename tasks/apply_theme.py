"""Apply new CSS theme to app.py - read CSS from external file"""
import re

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\tasks\new_theme.css', 'r', encoding='utf-8') as f:
    new_css_body = f.read()

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the CUSTOM_CSS block
start_marker = 'CUSTOM_CSS = """'
end_marker = '"""'
start_idx = content.find(start_marker)
if start_idx == -1:
    print("ERROR: CUSTOM_CSS not found")
    exit(1)

search_start = start_idx + len(start_marker)
end_idx = content.find(end_marker, search_start)
if end_idx == -1:
    print("ERROR: End of CUSTOM_CSS not found")
    exit(1)
end_idx += 3  # Include closing """

# Replace
old_block = content[start_idx:end_idx]
new_block = 'CUSTOM_CSS = """\n' + new_css_body + '\n"""'
content = content.replace(old_block, new_block, 1)

# Update header class
content = content.replace('class="jinli-header"', 'class="app-header"')

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("New theme CSS applied successfully!")
