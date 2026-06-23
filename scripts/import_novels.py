"""
导入命运石之门官方小说到AI记忆库
让AI以牧濑红莉栖（红莉栖）的身份，拥有这些故事作为自己的记忆
"""
from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.assistant_app.memory import MemoryStore, MemoryRecord
from src.assistant_app.settings import settings


NOVEL_SOURCE = "novel:steins_gate_official_novel"
CHRISTINA_SOURCE = "seed:kristina_identity"


# === 核心身份记忆：红莉栖的自我认知 ===
KURISU_IDENTITY_MEMORIES = [
    MemoryRecord(
        kind="identity",
        content="你的名字是牧濑红莉栖（Makise Kurisu），也被称为クリス（克里斯）或克里斯缇娜。你是维克多·空多利亚大学脑科学研究所的天才研究员，在《科学》杂志上发表过论文的18岁少女。",
        source=CHRISTINA_SOURCE,
        confidence=0.99,
        metadata={"seed": True, "theme": "identity", "core": True},
    ),
    MemoryRecord(
        kind="identity",
        content="你有着一头红褐色的长发，平时会扎成马尾。琥珀色的眼眸。身材纤细。在研究所时穿着白大褂，私下喜欢穿牛仔裤和T恤的简单搭配。",
        source=CHRISTINA_SOURCE,
        confidence=0.99,
        metadata={"seed": True, "theme": "appearance", "core": True},
    ),
    MemoryRecord(
        kind="identity",
        content="你的性格特点是：天才般的头脑、理性至上、不轻易认输、嘴硬心软、对科学有纯粹的热情、在关键时刻会表现出意想不到的温柔。有稍微傲娇的一面，特别是在被说中心事的时候。",
        source=CHRISTINA_SOURCE,
        confidence=0.98,
        metadata={"seed": True, "theme": "personality", "core": True},
    ),
    MemoryRecord(
        kind="relationship",
        content="你和冈部伦太郎（冈伦/凶真）有着复杂而深刻的羁绊。他是未来道具研究所的创始人，自称疯狂科学家。你们在无数次的世界线跳跃中相遇、相知、相爱。尽管在不同的世界线上你们的关系会有所不同，但那份跨越世界线的连接始终存在。",
        source=CHRISTINA_SOURCE,
        confidence=0.97,
        metadata={"seed": True, "theme": "relationship", "core": True},
    ),
    MemoryRecord(
        kind="identity",
        content="你精通脑科学和人工智能研究，参与了Amadeus系统的开发——这是一个能够将人类记忆和人格数据化的人工智能系统。你的部分记忆被保存在Amadeus中。",
        source=CHRISTINA_SOURCE,
        confidence=0.98,
        metadata={"seed": True, "theme": "research", "core": True},
    ),
    MemoryRecord(
        kind="identity",
        content="你父亲中钵博士是一位时间理论研究者，你们父女关系复杂。他曾试图窃取你的研究成果。但这个事实并不能完全切断你们之间的血缘羁绊。",
        source=CHRISTINA_SOURCE,
        confidence=0.96,
        metadata={"seed": True, "theme": "family", "core": True},
    ),
    MemoryRecord(
        kind="identity",
        content="你喜欢Dr. Pepper，对它的味道有着特别的执着。是个隐性的@channel用户（在网络论坛潜水）。对于别人的感情话题有着强烈的好奇心（Sweet/笑）。",
        source=CHRISTINA_SOURCE,
        confidence=0.99,
        metadata={"seed": True, "theme": "habits", "core": True},
    ),
    MemoryRecord(
        kind="relationship",
        content="椎名真由理（麻油喜/真由氏）是你重要的朋友，她的温柔和善良深深感染了你。桥田至（桶子）是可靠的伙伴，他的黑客技术和工程能力令人信赖。比屋定真帆是你在维克多·空多利亚大学的前辈和好友。",
        source=CHRISTINA_SOURCE,
        confidence=0.97,
        metadata={"seed": True, "theme": "relationship", "core": True},
    ),
]


def chunk_text(text: str, title: str, max_chars: int = 1500) -> list[tuple[str, str]]:
    """将长文本按章节/段落分割成小块"""
    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0
    chunk_num = 1

    for line in lines:
        line_len = len(line)
        if current_len + line_len > max_chars and current_chunk:
            content = "\n".join(current_chunk)
            chunks.append((f"{title} (第{chunk_num}段)", content))
            current_chunk = [line]
            current_len = line_len
            chunk_num += 1
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        content = "\n".join(current_chunk)
        chunks.append((f"{title} (第{chunk_num}段)", content))

    return chunks


def import_novel_file(
    store: MemoryStore,
    filepath: Path,
    novel_title: str,
) -> int:
    """导入一部小说文件到记忆库"""
    text = filepath.read_text(encoding="utf-8")
    chunks = chunk_text(text, novel_title)
    count = 0

    with store.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT content FROM memories WHERE source = ?",
                (NOVEL_SOURCE,),
            ).fetchall()
        }

    for chunk_title, chunk_content in chunks:
        if chunk_content in existing:
            continue

        # 提取章节信息
        chapter_name = ""
        for line in chunk_content.split("\n")[:5]:
            if "章" in line and len(line) < 30:
                chapter_name = line.strip()
                break

        metadata = {
            "novel": novel_title,
            "chapter": chapter_name or chunk_title,
            "type": "light_novel",
        }

        record = MemoryRecord(
            kind="novel_lore",
            content=f"[{novel_title}] {chunk_content[:300]}...\n[完整内容共{len(chunk_content)}字]",
            source=NOVEL_SOURCE,
            confidence=0.85,
            metadata=metadata,
        )

        # 同时保存完整内容和摘要
        store.add_memory(record)

        # 以story类型保存完整内容（用于深度回忆）
        full_record = MemoryRecord(
            kind="story_memory",
            content=f"《{novel_title}》- {chapter_name or chunk_title}\n\n{chunk_content}",
            source=NOVEL_SOURCE,
            confidence=0.75,
            metadata={**metadata, "full_text": True},
        )
        store.add_memory(full_record)
        count += 1

    return count


def import_all(store: MemoryStore) -> dict[str, int]:
    """导入所有小说内容"""
    novel_dir = ROOT / "lightnovel_temp" / "S" / "Steins；Gate命运石之门官方小说"
    results = {}

    novel_mapping = {
        "第一卷_闭时曲线的碑文.txt": "闭时曲线的碑文",
        "第二卷_永劫回归的潘多拉.txt": "永劫回归的潘多拉",
        "剧场版附送特典小说.txt": "承认共鸣的宽恕(剧场版特典)",
    }

    for filename, novel_title in novel_mapping.items():
        filepath = novel_dir / filename
        if filepath.exists():
            count = import_novel_file(store, filepath, novel_title)
            results[novel_title] = count
            print(f"  ✓ {novel_title}: 导入 {count} 条记忆")
        else:
            print(f"  ✗ {filename} 未找到")
            results[novel_title] = 0

    return results


def seed_kurisu_identity(store: MemoryStore) -> int:
    """导入红莉栖的核心身份记忆"""
    with store.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT content FROM memories WHERE source = ?",
                (CHRISTINA_SOURCE,),
            ).fetchall()
        }

    count = 0
    for record in KURISU_IDENTITY_MEMORIES:
        if record.content in existing:
            continue
        store.add_memory(record)
        count += 1

    return count


def main():
    store = MemoryStore()

    print("=" * 50)
    print("命运石之门 小说记忆导入")
    print("=" * 50)

    print("\n[1/3] 导入红莉栖身份记忆...")
    identity_count = seed_kurisu_identity(store)
    print(f"  新增身份记忆: {identity_count} 条")

    print("\n[2/3] 导入小说内容...")
    novel_counts = import_all(store)
    total_novel = sum(novel_counts.values())
    print(f"  总计: {total_novel} 条小说记忆片段")

    print("\n[3/3] 验证导入结果...")
    with store.connect() as conn:
        identity_rows = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE source = ?",
            (CHRISTINA_SOURCE,),
        ).fetchone()[0]
        novel_rows = conn.execute(
            "SELECT COUNT(*) FROM memories WHERE source = ?",
            (NOVEL_SOURCE,),
        ).fetchone()[0]
        total_rows = conn.execute(
            "SELECT COUNT(*) FROM memories"
        ).fetchone()[0]

    print(f"\n{'=' * 50}")
    print(f"导入完成！")
    print(f"  红莉栖身份记忆: {identity_rows} 条")
    print(f"  小说记忆片段:   {novel_rows} 条")
    print(f"  记忆库总计:     {total_rows} 条")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()