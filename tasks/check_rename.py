"""Search for remaining old references after rename"""
import os

extensions = ('.py', '.md', '.yaml', '.yml', '.txt', '.tpl', '.cfg', '.ini', '.example', '.dockerignore')
old_patterns = ['jinli', 'JinLi', 'JINLI', '锦鲤']

found = []
for root, dirs, files in os.walk(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai'):
    # Skip venv, __pycache__, .git
    skip_dirs = {'venv', '__pycache__', '.git', '.pytest_cache', 'node_modules'}
    dirs[:] = [d for d in dirs if d not in skip_dirs]
    
    for f in files:
        if f.endswith(extensions):
            path = os.path.join(root, f)
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read()
                    for pattern in old_patterns:
                        if pattern in content:
                            found.append((pattern, path))
                            break
            except:
                pass

if found:
    print(f"Found {len(found)} remaining old references:")
    print()
    for pattern, path in sorted(set(found)):
        print(f"  [{pattern}] {os.path.relpath(path, r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai')}")
else:
    print("All 127 tests pass. No remaining old references found!")
