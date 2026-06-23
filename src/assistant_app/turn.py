"""
TurnManager: 判断用户是否说完，决定 AI 是否该回答。

只做规则判断（词表 + 停顿时间 + ASR 置信度），不依赖 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── 继续说标记：用户句尾含有这些词，说明还没说完 ──
WAIT_MORE_MARKERS: set[str] = {
    "然后", "还有", "而且", "另外",
    "就是", "就是说", "怎么说", "怎么说呢",
    "比如", "比如说", "举个例子",
    "我的意思是", "不是", "不对",
    "等一下", "我想一下", "我想想",
    "我还没说完", "先别回答", "接着说",
    "但是", "不过", "然而", "其实",
    "首先", "第一", "第二",
}

# ── 交出话语权标记：用户明确要 AI 回答 ──
ANSWER_NOW_MARKERS: set[str] = {
    "你觉得", "你说说", "你怎么看",
    "你来", "回答我", "告诉我",
    "帮我", "怎么做", "怎么改",
    "给我建议", "有什么建议",
    "我说完了", "就这样",
    "开始吧", "你来说吧",
    "吧",       # "吧" 结尾通常是请求
}

# ── 强打断标记 ──
INTERRUPT_MARKERS: set[str] = {
    "停", "先停", "别说了",
    "等一下", "等等",
    "打断一下", "我打断一下",
    "不是这个", "不对",
    "闭嘴", "别说了",
}

# ── 附和词：用户只是在附和，AI 不应停止 ──
BACKCHANNEL_MARKERS: set[str] = {
    "嗯", "对", "好", "是的",
    "哦", "可以", "继续",
    "嗯嗯", "对对", "好好",
}


@dataclass
class TurnDecision:
    action: str          # ignore | listening | wait_more | backchannel | answer_now | interrupt
    confidence: float    # 0.0 ~ 1.0
    reason: str          # 人类可读的解释
    backchannel: str | None = None  # 如果是 backchannel，可选的轻反馈文字


def calc_endscore(
    transcript: str,
    silence_ms: int,
    speech_ms: int,
    asr_confidence: float,
    ai_speaking: bool,
) -> TurnDecision:
    """计算 EndScore 并返回轮次决策。

    Args:
        transcript: ASR 转写文本（已 trim）
        silence_ms: 用户停顿时长
        speech_ms: 用户本次说话时长
        asr_confidence: ASR 置信度 0~1
        ai_speaking: AI 当前是否在说话
    """
    text = transcript.strip()
    text_lower = text.lower()

    # ── 0. 空文本 → ignore ──
    if not text:
        return TurnDecision(
            action="ignore",
            confidence=0.3,
            reason="空文本，忽略",
        )

    # ── 1. 如果是单附和词 → backchannel ──
    if text in BACKCHANNEL_MARKERS:
        return TurnDecision(
            action="backchannel",
            confidence=0.95,
            reason=f"用户附和行为: '{text}'",
            backchannel=text,
        )

    # ── 2. 如果 AI 正在说话，检查打断 ──
    if ai_speaking:
        # 检查打断词
        for marker in INTERRUPT_MARKERS:
            if marker in text:
                return TurnDecision(
                    action="interrupt",
                    confidence=0.92,
                    reason=f"检测到打断词: '{marker}'",
                )

        # 用户连续说话 > 800ms，可能想插话
        if speech_ms >= 800:
            return TurnDecision(
                action="interrupt",
                confidence=0.70,
                reason=f"AI说话时用户连续说话 {speech_ms}ms，判定为打断意图",
            )

        # 短语音可能是附和或环境声，不打断
        return TurnDecision(
            action="ignore",
            confidence=0.50,
            reason="AI说话中，用户短语音视为背景",
        )

    # ── 3. ASR 置信度过低 → wait_more ──
    if asr_confidence < 0.5:
        return TurnDecision(
            action="wait_more",
            confidence=asr_confidence,
            reason=f"ASR 置信度 {asr_confidence:.2f} 过低，需更多上下文",
        )

    # ── 4. 检查继续说标记 ──
    for marker in WAIT_MORE_MARKERS:
        if marker in text[-10:]:  # 只看句尾 10 个字
            return TurnDecision(
                action="wait_more",
                confidence=0.88,
                reason=f"句尾包含继续说标记: '{marker}'",
            )

    # ── 5. 检查交出话语权标记 ──
    for marker in ANSWER_NOW_MARKERS:
        if marker in text:
            return TurnDecision(
                action="answer_now",
                confidence=0.90,
                reason=f"检测到交出话语权标记: '{marker}'",
            )

    # 句尾是"吗/呢/?" → 疑问句，该回答
    if any(text.rstrip().endswith(c) for c in ("吗", "呢", "？", "?", "吧")):
        return TurnDecision(
            action="answer_now",
            confidence=0.85,
            reason="句尾疑问词，判定为提问",
        )

    # ── 6. 按停顿时间判断 ──
    # 4 个沉默区间
    if silence_ms < 600:
        return TurnDecision(
            action="listening",
            confidence=0.60,
            reason=f"静音仅 {silence_ms}ms，正常语流停顿",
        )
    elif silence_ms < 1200:
        return TurnDecision(
            action="listening",
            confidence=0.65,
            reason=f"静音 {silence_ms}ms，轻微犹豫，继续听",
        )
    elif silence_ms < 2200:
        # 在 1.2s~2.2s 之间：看语义是否显得完整
        # 如果句子比较短(<5字)且没有WAIT_MORE标记，可以回答
        if len(text) <= 5:
            return TurnDecision(
                action="answer_now",
                confidence=0.70,
                reason=f"短句({len(text)}字) + 静音 {silence_ms}ms，判定说完",
            )
        return TurnDecision(
            action="wait_more",
            confidence=0.72,
            reason=f"静音 {silence_ms}ms，但语义可能未完",
        )
    elif silence_ms < 3500:
        return TurnDecision(
            action="answer_now",
            confidence=0.78,
            reason=f"静音 {silence_ms}ms，大概率说完",
        )
    else:
        return TurnDecision(
            action="answer_now",
            confidence=0.85,
            reason=f"静音 {silence_ms}ms，默认回答",
        )