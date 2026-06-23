"""Unit tests for turn.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.assistant_app.turn import calc_endscore


def test_wait_more():
    # 句尾"就是" = 继续说
    d = calc_endscore("我觉得这个方案不错，就是", 1800, 5000, 0.85, False)
    assert d.action == "wait_more", f"Expected wait_more, got {d.action}"
    print(f"  ✓ wait_more: {d.reason}")


def test_answer_now():
    # "你觉得呢" = 交出话语权
    d = calc_endscore("你觉得呢", 2000, 3000, 0.9, False)
    assert d.action == "answer_now", f"Expected answer_now, got {d.action}"
    print(f"  ✓ answer_now: {d.reason}")

    # 句尾"吗" = 疑问
    d = calc_endscore("这样可以吗", 1800, 4000, 0.85, False)
    assert d.action == "answer_now", f"Expected answer_now, got {d.action}"
    print(f"  ✓ answer_now (question): {d.reason}")


def test_backchannel():
    # "嗯" = 附和
    d = calc_endscore("嗯", 1000, 500, 0.95, True)
    assert d.action == "backchannel", f"Expected backchannel, got {d.action}"
    print(f"  ✓ backchannel: {d.reason}")


def test_interrupt():
    # "停" = 打断
    d = calc_endscore("停", 500, 1000, 0.9, True)
    assert d.action == "interrupt", f"Expected interrupt, got {d.action}"
    print(f"  ✓ interrupt: {d.reason}")

    # AI说话时用户连续说1秒 = 打断
    d = calc_endscore("不是这个意思", 300, 1000, 0.85, True)
    assert d.action == "interrupt", f"Expected interrupt, got {d.action}"
    print(f"  ✓ interrupt (long speech): {d.reason}")


def test_long_silence():
    # 停2.6秒 = 默认回答（新阈值 >= 2500ms）
    d = calc_endscore("我想让她更像真人", 2600, 6000, 0.85, False)
    assert d.action == "answer_now", f"Expected answer_now, got {d.action}"
    print(f"  ✓ long silence => answer_now: {d.reason}")

    # 停3.8秒 = 还是默认回答
    d = calc_endscore("我想让她更像真人", 3800, 6000, 0.85, False)
    assert d.action == "answer_now", f"Expected answer_now, got {d.action}"
    print(f"  ✓ long silence (3800ms) => answer_now: {d.reason}")


if __name__ == "__main__":
    print("Running turn.py tests...")
    test_wait_more()
    test_answer_now()
    test_backchannel()
    test_interrupt()
    test_long_silence()
    print("\n✅ All turn tests passed!")