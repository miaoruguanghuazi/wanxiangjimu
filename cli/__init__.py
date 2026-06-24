"""
万象积木 Skill CLI 脚手架

用法:
    python -m cli skill list
    python -m cli skill create my-skill
    python -m cli skill install ./my-skill
    python -m cli skill uninstall my-skill
    python -m cli skill show my-skill
"""

from __future__ import annotations

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime


def cmd_skill(args: list[str]):
    if not args or args[0] in ("help", "--help", "-h"):
        print_skill_help()
        return

    sub = args[0]
    if sub == "list":
        skill_list()
    elif sub == "create":
        if len(args) < 2:
            print("ERROR: python -m cli skill create <skill-name>")
            return
        skill_create(args[1])
    elif sub == "install":
        if len(args) < 2:
            print("ERROR: python -m cli skill install <path>")
            return
        skill_install(args[1])
    elif sub == "uninstall":
        if len(args) < 2:
            print("ERROR: python -m cli skill uninstall <skill-id>")
            return
        skill_uninstall(args[1])
    elif sub == "show":
        if len(args) < 2:
            print("ERROR: python -m cli skill show <skill-id>")
            return
        skill_show(args[1])
    else:
        print(f"ERROR: unknown command: {sub}")
        print_skill_help()


def print_skill_help():
    print("""
WanXiang JiMu CLI - Skill Management

Commands:
  python -m cli skill list             List all installed skills
  python -m cli skill create <name>    Create a new skill project
  python -m cli skill install <path>   Install a skill from path
  python -m cli skill uninstall <id>   Uninstall a skill
  python -m cli skill show <id>        Show skill details
""")


def skill_list():
    skills_dir = _get_skills_dir()
    if not skills_dir.exists():
        print("No skills installed.")
        return

    skills = []
    for d in sorted(skills_dir.iterdir()):
        mf = d / "manifest.json"
        if mf.exists():
            try:
                with open(mf, encoding="utf-8") as f:
                    meta = json.load(f)
                skills.append((d.name, meta))
            except Exception:
                skills.append((d.name, {"name": d.name, "description": "(broken manifest)"}))

    if not skills:
        print("No skills installed.")
        return

    print(f"\nInstalled skills ({len(skills)}):\n")
    for sid, meta in skills:
        name = meta.get("name", sid)
        desc = meta.get("description", "")
        ver = meta.get("version", "0.1.0")
        print(f"  {name} v{ver}  (id: {sid})")
        if desc:
            print(f"    {desc}")
        print()


def skill_create(name: str):
    import re
    safe = re.sub(r'[^a-z0-9_-]', '', name.lower().replace(" ", "-"))
    if not safe:
        print("ERROR: invalid skill name")
        return

    target = Path.cwd() / safe
    if target.exists():
        print(f"ERROR: directory exists: {target}")
        return
    target.mkdir(parents=True)

    manifest = {
        "name": name, "version": "0.1.0",
        "description": f"A brief description of {name}",
        "author": "", "created_at": datetime.now().isoformat(),
        "keywords": [], "triggers": [],
        "system_prompt": f"You are a {name} expert.",
    }
    with open(target / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    handler_code = (
        '"""\n'
        + name + ' Skill Handler\n'
        + '"""\n\n'
        + 'from __future__ import annotations\n'
        + 'from typing import Any\n\n\n'
        + 'async def execute(params: dict[str, Any]) -> dict[str, Any]:\n'
        + '    """Execute the skill."""\n'
        + '    user_input = params.get("input", "")\n'
        + '    return {\n'
        + '        "content": f"Processing ' + name + ': {user_input[:50]}...",\n'
        + '        "success": True,\n'
        + '    }\n'
    )
    with open(target / "handler.py", "w", encoding="utf-8") as f:
        f.write(handler_code)

    init_code = '"""Skill: ' + name + '"""\n'
    with open(target / "__init__.py", "w", encoding="utf-8") as f:
        f.write(init_code)

    print(f"\nSkill created: {target}")
    print(f"  Files: {safe}/")
    print(f"    - manifest.json  (edit to configure)")
    print(f"    - handler.py     (edit to implement)")
    print(f"\nNext: python -m cli skill install {safe}")


def skill_install(path_str: str):
    source = Path(path_str).resolve()
    if not source.exists() or not (source / "manifest.json").exists():
        print(f"ERROR: invalid skill path: {source}")
        return

    skills_dir = _get_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    target = skills_dir / source.name
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)

    with open(target / "manifest.json", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"Installed: {meta.get('name', source.name)} v{meta.get('version', '0.1.0')}")


def skill_uninstall(skill_id: str):
    target = _get_skills_dir() / skill_id
    if not target.exists():
        print(f"ERROR: skill not found: {skill_id}")
        return
    shutil.rmtree(target)
    print(f"Uninstalled: {skill_id}")


def skill_show(skill_id: str):
    mf = _get_skills_dir() / skill_id / "manifest.json"
    if not mf.exists():
        print(f"ERROR: skill not found: {skill_id}")
        return
    with open(mf, encoding="utf-8") as f:
        meta = json.load(f)
    print(f"\nSkill: {meta.get('name', skill_id)}")
    print(f"  Version: {meta.get('version', '?')}")
    print(f"  Description: {meta.get('description', '—')}")
    print(f"  Triggers: {', '.join(meta.get('triggers', [])) or 'none'}")


def _get_skills_dir() -> Path:
    return Path.cwd() / "data" / "memory" / "procedural"


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "--help", "-h"):
        print("Usage: python -m cli skill <command> [args]")
        print("Commands: list, create, install, uninstall, show")
        return
    if sys.argv[1] == "skill":
        cmd_skill(sys.argv[2:])
    else:
        print(f"Unknown: {sys.argv[1]}")


if __name__ == "__main__":
    main()
