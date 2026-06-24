"""Replace CUSTOM_CSS in app.py with new blue-purple tech theme"""
import re

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the CUSTOM_CSS block boundaries
start_marker = "CUSTOM_CSS = \"\"\""
end_marker = "\"\"\""
start_idx = content.find(start_marker)
if start_idx == -1:
    print("ERROR: CUSTOM_CSS not found")
    exit(1)

# Find the closing triple quote
search_start = start_idx + len(start_marker)
end_idx = content.find(end_marker, search_start)
if end_idx == -1:
    print("ERROR: End of CUSTOM_CSS not found")
    exit(1)
end_idx += 3  # Include the closing """

print(f"Found CUSTOM_CSS: lines {content[:start_idx].count(chr(10))+1} to {content[:end_idx].count(chr(10))+1}")

# New CSS from the user's design
new_css = """CUSTOM_CSS = """
/* ========== 全局变量 ========== */
:root {
    --primary-color: #6366f1;
    --primary-light: #818cf8;
    --primary-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%);
    --secondary-color: #06b6d4;
    --success-color: #10b981;
    --warning-color: #f59e0b;
    --error-color: #ef4444;
    --bg-main: #0f172a;
    --bg-card: #1e293b;
    --bg-card-hover: #334155;
    --bg-input: #0f172a;
    --text-primary: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #334155;
    --border-light: #475569;
}

* { border-color: var(--border-color) !important; }

body {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 30%, #0f172a 70%, #1e1b4b 100%);
    background-attachment: fixed;
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.gradio-container { max-width: 1400px !important; }

/* ========== 顶部标题栏 ========== */
.app-header {
    background: var(--primary-gradient) !important;
    padding: 24px 32px !important;
    border-radius: 20px;
    margin-bottom: 24px;
    box-shadow: 0 20px 60px rgba(99, 102, 241, 0.3);
    position: relative;
    overflow: hidden;
}
.app-header::before {
    content: '';
    position: absolute;
    top: -50%; right: -10%;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
    border-radius: 50%;
}
.app-header h1 { color: white !important; font-weight: 700; font-size: 32px; margin: 0; position: relative; z-index: 1; }
.app-header p { color: rgba(255,255,255,0.85) !important; margin: 6px 0 0 0; font-size: 15px; position: relative; z-index: 1; }

/* ========== 卡片 ========== */
.chat-container, .sidebar-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.15);
}
.chat-container:hover, .sidebar-card:hover {
    border-color: rgba(99,102,241,0.4) !important;
    box-shadow: 0 8px 32px rgba(99,102,241,0.12);
}

/* ========== 聊天气泡 ========== */
.chatbot .message {
    border-radius: 16px !important;
    padding: 14px 18px !important;
    margin-bottom: 12px;
    max-width: 85%;
    line-height: 1.6;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.chatbot .user {
    background: var(--primary-gradient) !important;
    color: white !important;
    margin-left: auto;
    border-bottom-right-radius: 4px !important;
}
.chatbot .bot {
    background: var(--bg-card-hover) !important;
    color: var(--text-primary) !important;
    margin-right: auto;
    border-bottom-left-radius: 4px !important;
    border: 1px solid var(--border-color);
}

/* ========== 按钮 ========== */
button.primary-btn {
    background: var(--primary-gradient) !important;
    border: none !important;
    border-radius: 12px !important;
    color: white !important;
    font-weight: 600;
    padding: 12px 28px !important;
    box-shadow: 0 4px 15px rgba(99,102,241,0.35);
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
}
button.primary-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99,102,241,0.45); }

/* ========== 输入框 ========== */
textarea, input[type="text"], input[type="number"], select {
    background: var(--bg-input) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    font-size: 14px;
    transition: all 0.3s ease;
}
textarea:focus, input:focus, select:focus {
    border-color: var(--primary-color) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
    outline: none !important;
}

/* ========== 滚动条 ========== */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-main); border-radius: 4px; }
::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary-color); }

/* ========== 状态卡片网格 ========== */
.status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.status-item {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px;
    text-align: center;
}
.status-item:hover { border-color: var(--success-color); background: rgba(16,185,129,0.05); }
.status-item .status-icon { font-size: 20px; margin-bottom: 4px; }
.status-item .status-text { font-size: 11px; color: var(--text-secondary); }

/* ========== 滑块 ========== */
input[type="range"] { -webkit-appearance: none; height: 6px; border-radius: 3px; background: var(--bg-card-hover); }
input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%;
    background: var(--primary-gradient); cursor: pointer;
    box-shadow: 0 2px 10px rgba(99,102,241,0.5);
    border: 2px solid white;
}

/* ========== 底部文字 ========== */
.footer-text { color: var(--text-muted); font-size: 12px; text-align: center; margin-top: 24px; }

/* ========== 代码块 ========== */
pre, code { background: #0f172a !important; border-radius: 8px !important; border: 1px solid var(--border-color) !important; }

/* ========== Accordeon 折叠面板 ========== */
.accordion { background: var(--bg-card) !important; border: 1px solid var(--border-color) !important; border-radius: 12px !important; margin-bottom: 12px; overflow: hidden; }
"""

old_block = content[start_idx:end_idx]
new_block = new_css
content = content.replace(old_block, new_block, 1)

# Also update the header HTML class from "jinli-header" to "app-header"
content = content.replace('class="jinli-header"', 'class="app-header"')

with open(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai\app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"CSS replaced successfully!")
