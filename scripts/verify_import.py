"""验证命运石之门小说和红莉栖身份记忆是否成功导入"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.assistant_app.memory import MemoryStore

store = MemoryStore()
conn = store.connect()

# 总计数
total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
print(f"记忆库总计: {total} 条")

# 按source统计
sources = conn.execute(
    "SELECT source, COUNT(*) as cnt FROM memories GROUP BY source ORDER BY cnt DESC"
).fetchall()
print("\n来源分布:")
for s in sources:
    print(f"  {s['source']}: {s['cnt']}条")

# 按kind统计
kinds = conn.execute(
    "SELECT kind, COUNT(*) as cnt FROM memories GROUP BY kind ORDER BY cnt DESC"
).fetchall()
print("\n类型分布:")
for k in kinds:
    print(f"  {k['kind']}: {k['cnt']}条")

# 红莉栖身份记忆
kurisu_count = conn.execute(
    "SELECT COUNT(*) FROM memories WHERE source LIKE '%kristina%' OR source LIKE '%kurisu%'"
).fetchone()[0]
print(f"\n红莉栖身份记忆: {kurisu_count}条")

# 小说记忆
novel_count = conn.execute(
    "SELECT COUNT(*) FROM memories WHERE source = 'novel:steins_gate_official_novel'"
).fetchone()[0]
print(f"小说记忆: {novel_count}条")

# 搜索查询测试
print("\n搜索测试: 搜索 '红莉栖'")
results = store.search("红莉栖", limit=3)
for r in results:
    print(f"  [{r['kind']}] {r['content'][:100]}...")

print("\n搜索测试: 搜索 '世界线'")
results = store.search("世界线", limit=3)
for r in results:
    print(f"  [{r['kind']}] {r['content'][:100]}...")

# 显示最新的一些记忆
print("\n最新记忆(前5条):")
latest = conn.execute(
    "SELECT id, kind, content, source FROM memories ORDER BY id DESC LIMIT 5"
).fetchall()
for r in latest:
    content_preview = r['content'][:120].replace('\n', ' ')
    print(f"  #{r['id']} [{r['kind']}] {content_preview}...")
    print(f"    来源: {r['source']}")

conn.close()
print("\n✅ 验证完成")