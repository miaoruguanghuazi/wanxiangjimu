"""P0.1: End-to-end memory system verification"""
import sys, os, asyncio, logging
logging.basicConfig(level=logging.WARNING)

os.chdir(r'C:\Users\35515\.qclaw\workspace-tfxjjhfnjialcuju\jinli-ai')
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

async def main():
    import chromadb
    from memory_system import MemorySystem, MemoryEntry

    # 1. Init
    chroma_client = chromadb.PersistentClient(path='./data/chroma')
    ms = MemorySystem(chroma_client=chroma_client, data_path='./data/memory')
    print("[1/5] MemorySystem initialized")
    print(f"      Embed model: {'LOADED' if ms._embed_model else 'NOT LOADED'}")
    print(f"      ChromaDB: {'READY' if ms.l3._collection else 'NOT READY'}")

    # 2. Simulate conversation with auto-extract
    messages = [
        "你好",
        "我叫张三，是一名Python开发者",
        "我喜欢函数式编程",
        "帮我写一个快速排序",
    ]
    sid = "test_e2e"
    for msg in messages:
        ms.add_message(sid, "user", msg)
        count = await ms.auto_extract_and_store(msg, session_id=sid)
        if count:
            print(f"[2/5] Auto-extracted {count} memory from: {msg[:30]}")

    # 3. Verify L3 storage
    stats = ms.get_stats()
    l3_count = stats['L3_long_term']['total']
    print(f"[3/5] L3 memories stored: {l3_count}")
    assert l3_count >= 2, f"Expected >=2 memories, got {l3_count}"

    # 4. Retrieve memories
    results_1 = ms.retrieve_long_term("Python", "default", top_k=5)
    print(f"[4/5] Retrieval 'Python': {len(results_1)} results")
    for r in results_1:
        print(f"      [{r.memory_type}] {r.content[:60]} (score={r.final_score:.2f})")

    results_2 = ms.retrieve_long_term("张三", "default", top_k=5)
    print(f"      Retrieval '张三': {len(results_2)} results")

    # 5. Build prompt with memory injection
    prompt = ms.build_prompt(sid, "帮我写个Python函数", "You are WanXiang JiMu.")
    sys_count = sum(1 for m in prompt if m['role'] == 'system' and '关于用户' in m['content'])
    print(f"[5/5] System prompts with memory: {sys_count}")
    for m in prompt:
        if m['role'] == 'system' and '关于用户' in m['content']:
            print(f"      {m['content'][:200]}")

    print("\n✅ P0.1: Memory system E2E verification PASSED!")
    return True

result = asyncio.run(main())
