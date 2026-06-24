"""Handle real remaining rename issues (not path references)"""
import os, re

root = r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai'

fixes = {
    # JINLI_API_KEY -> WANXIANG_API_KEY
    '.env.example': [('JINLI_API_KEY', 'WANXIANG_API_KEY')],
    'api_server.py': [('JINLI_API_KEY', 'WANXIANG_API_KEY')],
    'docker-compose.yml': [('JINLI_API_KEY', 'WANXIANG_API_KEY')],
    'docs/API.md': [('JINLI_API_KEY', 'WANXIANG_API_KEY')],
    'docs/INSTALL.md': [('JINLI_API_KEY', 'WANXIANG_API_KEY')],
    
    # Collection names
    'memory_system/l3_long_term.py': [('jinli_long_term_memory', 'wanxiang_long_term_memory')],
    'rag_pipeline/indexer.py': [('jinli_rag', 'wanxiang_rag')],
    'rag_pipeline/retriever.py': [('jinli_rag', 'wanxiang_rag')],
    
    # Skill market collection
    'skill_market/__init__.py': [('jinli_skill', 'wanxiang_skill')],
    'skill_market/marketplace.py': [('jinli', 'wanxiang')],
    'skill_market/runtime.py': [('jinli', 'wanxiang')],
    'skill_market/store.py': [('jinli', 'wanxiang')],
    
    # Security
    'security/config_validator.py': [('jinli', 'wanxiang')],
    'security/path_guard.py': [('jinli', 'wanxiang')],
    
    # GitHub CI
    '.github/workflows/ci.yml': [('jinli-ai', 'wanxiang-jimu')],
    
    # App.py skill_market URL
    'app.py': [('registry.jinli.ai', 'registry.wanxiang-jimu.ai')],
}

count = 0
for rel_path, replacements in fixes.items():
    full_path = os.path.join(root, rel_path)
    if not os.path.exists(full_path):
        print(f"SKIP: {rel_path} not found")
        continue
    with open(full_path, 'r', encoding='utf-8') as f:
        content = f.read()
    for old, new in replacements:
        if old in content:
            # Use word boundary for safety
            content = content.replace(old, new)
            count += 1
            print(f"  {old} -> {new}  ({rel_path})")
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)

print(f"\nFixed {count} remaining references across {len(fixes)} files")
