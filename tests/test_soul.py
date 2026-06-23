from assistant_app.soul import SoulEngine, SoulState


def test_research_text_switches_to_research_mode() -> None:
    state = SoulState()
    updated = SoulEngine().update(state, "帮我查一篇 arxiv 论文并分析实验")
    assert updated.work_mode == "research"
    assert updated.emotion == "focused"


def test_anxious_text_switches_to_care_mode() -> None:
    state = SoulState()
    updated = SoulEngine().update(state, "我最近签证很烦，感觉有点焦虑")
    assert updated.work_mode == "care"
    assert updated.vector["concern"] > 0.35

def test_bond_text_updates_relationship_state() -> None:
    state = SoulState()
    updated = SoulEngine().update(state, "我需要你像有灵魂一样主动关心我，也要记住我")
    assert updated.relationship_state == "bonded_research_partner"
    assert updated.task_state == "attentive"
    assert updated.vector["protectiveness"] > 0.42
