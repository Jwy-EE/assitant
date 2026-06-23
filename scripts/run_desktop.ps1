# 本地 AI 语音交互系统升级技术设计文档

## 1. 背景

当前项目是一个本地桌面 AI companion 原型，整体形态为：

```text
Electron / Web 前端
    ↓
FastAPI 后端
    ↓
ASR / DeepSeek / Memory / Soul / TTS / VTube Studio
```

当前语音链路大致为：

```text
用户点击 Mic
    ↓
前端录音
    ↓
能量阈值 VAD 判断用户停顿
    ↓
停止录音
    ↓
把完整录音转成 wav
    ↓
POST /api/asr/transcribe
    ↓
得到最终文本
    ↓
POST /api/chat
    ↓
DeepSeek 生成完整 JSON
    ↓
后端合成整段 TTS
    ↓
前端播放音频
```

这个流程能跑通，但存在三个核心不足：

1. 语音转文字准确率不够，尤其是长语音、中文夹英文、技术术语、项目名、论文名、动漫角色名。
2. 轮次判断不自然，当前更接近“检测到静音就回答”，而不是像人一样判断用户是否真的说完。
3. 响应速度不够快，因为 ASR、LLM、TTS 都是整段阻塞式处理，用户说完后需要等待完整生成和完整合成。

本升级方案目标是把当前系统从：

```text
录一句 → 转一句 → 回一句
```

升级为：

```text
持续监听 → 流式识别 → 智能轮次判断 → 流式回答 → 边说边听 → 可自然打断
```

---

## 2. 目标

### 2.1 功能目标

系统升级后应满足以下用户体验：

```text
1. 用户说中文，AI 能高准确率转写。
2. 用户说话中间犹豫、停顿、换气时，AI 不应立刻抢答。
3. 用户明确问完或交出话语权时，AI 应快速开始回答。
4. AI 正在说话时，用户可以自然打断。
5. 用户只是“嗯 / 对 / 好”这种附和时，AI 不应错误停止。
6. AI 回复应尽快开始，而不是等完整长回答生成后才开口。
7. AI 的语音、字幕、表情、动作仍然与现有 companion 系统集成。
```

### 2.2 技术目标

```text
ASR 准确率：优先提升长语音和技术词识别
Endpointing：判断用户是否说完
Turn-taking：判断当前是否该 AI 接话
Barge-in：AI 说话时支持用户打断
Streaming LLM：降低首字响应时间
Sentence-level TTS：按句合成和播放，降低首句语音延迟
Interrupt-safe playback：支持停止当前语音和清空 TTS 队列
```

---

## 3. 当前系统问题分析

### 3.1 ASR 层问题

当前 ASR 只支持一个 provider：

```text
ASSISTANT_ASR_PROVIDER=google
```

当前转写方式是：

```text
整段 audio/wav → speech_recognition → recognize_google → 最终文本
```

问题：

```text
1. 不适合长语音。
2. 不适合大量专业名词。
3. 不支持上下文提示词。
4. 不支持局部流式转写。
5. 不支持多候选修正。
6. 一旦识别错，后续 LLM 会基于错误文本回答。
```

因此 ASR 层需要从“简单远程识别器”升级为“可配置、多 provider、可上下文增强的识别层”。

---

### 3.2 VAD / Endpointing 问题

当前前端使用固定能量阈值：

```text
SPEECH_THRESHOLD = 0.022
SILENCE_HOLD_MS = 1400 ms
MAX_RECORDING_MS = 18000 ms
```

逻辑近似为：

```text
如果声音能量超过阈值，认为用户正在说话；
如果检测到语音后静音超过 1400ms，认为用户说完；
如果录音超过 18s，强行结束。
```

问题：

```text
1. 能量阈值只能判断“声音大不大”，不能判断“是不是人在说话”。
2. 噪声、键盘声、环境声可能误触发。
3. 用户思考停顿 1~2 秒时可能被误判为说完。
4. 用户长句中间停顿会被切断。
5. 无法区分“用户说完了”和“用户还在想”。
```

所以需要引入更专业的 VAD，同时在 VAD 后增加语义级 endpointing。

---

### 3.3 轮次管理问题

当前系统是：

```text
停止录音 → ASR → sendMessage() → AI 回答
```

也就是说，只要系统认为录音结束，就直接进入 AI 回答，没有单独判断：

```text
用户是否真的说完？
用户是否只是在犹豫？
用户是否明确要求 AI 回答？
用户是否说了“先别回答”？
用户是否正在打断 AI？
```

这会导致 AI 不像真人，而像一个“静音触发器”。

自然对话需要区分：

```text
短暂停顿：继续听
思考停顿：继续等
语义完整：准备回答
明确交权：立即回答
用户打断：停止当前输出
用户附和：继续输出
```

因此需要新增 `TurnManager`。

---

### 3.4 LLM 响应速度问题

当前 DeepSeek 请求是非流式：

```json
{
  "stream": false,
  "response_format": {
    "type": "json_object"
  }
}
```

后端必须等完整 JSON 生成完，再解析：

```text
ja_text
zh_subtitle
emotion
gesture
voice_style
memory_update
tool_intent
```

然后才开始 TTS。

问题：

```text
1. 首字响应时间高。
2. 首句语音延迟高。
3. 长回答必须完整生成完才能播放。
4. 用户打断时，当前请求不容易取消。
5. JSON 模式不利于边生成边播放。
```

需要把回复拆成：

```text
快速路径：先流式生成可说出口的正文
慢速路径：再生成 emotion / gesture / memory_update / tool_intent
```

---

### 3.5 TTS 播放控制问题

当前 TTS 是整段合成和整段播放。

问题：

```text
1. TTS 要等完整回复生成后才能开始。
2. 长句合成慢。
3. AI 正在说话时，用户打断不能优雅停止后端生成。
4. 没有 TTS 队列。
5. 没有 sentence-level playback。
```

目标是改成：

```text
模型生成第一句话
    ↓
立刻合成第一句话
    ↓
立刻播放
    ↓
模型继续生成后续句子
    ↓
后续句子进入 TTS 队列
```

---

## 4. 目标架构

升级后的整体架构如下：

```text
┌────────────────────────────────────────────┐
│              Electron / Web UI             │
│                                            │
│  Mic Input                                 │
│     ↓                                      │
│  AudioWorklet / MediaStream                │
│     ↓                                      │
│  PCM Frame Sender                          │
│     ↓                                      │
│  Subtitle Renderer                         │
│  TTS Playback Queue                        │
│  Interrupt Listener                        │
└────────────────────────────────────────────┘
                    ↓ WebSocket / HTTP
┌────────────────────────────────────────────┐
│                FastAPI Backend             │
│                                            │
│  /ws/audio                                 │
│     ↓                                      │
│  VAD Service                               │
│     ↓                                      │
│  Streaming ASR Service                     │
│     ↓                                      │
│  Transcript Stabilizer                     │
│     ↓                                      │
│  TurnManager                               │
│     ├── WAIT_MORE                          │
│     ├── BACKCHANNEL                        │
│     ├── ANSWER_NOW                         │
│     ├── INTERRUPT                          │
│     └── IGNORE                             │
│     ↓                                      │
│  Chat Orchestrator                         │
│     ↓                                      │
│  LLM Streaming Client                      │
│     ↓                                      │
│  Sentence Segmenter                        │
│     ↓                                      │
│  TTS Queue                                 │
│     ↓                                      │
│  VTube Event Emitter                       │
└────────────────────────────────────────────┘
```

---

## 5. 模块设计

## 5.1 ASR Service 升级

### 5.1.1 目标

把当前单一 `google` ASR 改成多 provider 架构。

建议支持：

```text
google           旧方案，作为 fallback
faster_whisper   主力高准确率方案
whisper_cpp      可选本地轻量方案
```

### 5.1.2 配置项

新增环境变量：

```text
ASSISTANT_ASR_PROVIDER=faster_whisper
ASSISTANT_ASR_MODEL=large-v3
ASSISTANT_ASR_DEVICE=cuda
ASSISTANT_ASR_COMPUTE=float16
ASSISTANT_ASR_LANGUAGE=zh
ASSISTANT_ASR_VAD_FILTER=true
ASSISTANT_ASR_BEAM_SIZE=5
```

低配置电脑建议：

```text
ASSISTANT_ASR_MODEL=small
ASSISTANT_ASR_DEVICE=cpu
ASSISTANT_ASR_COMPUTE=int8
```

中等配置电脑建议：

```text
ASSISTANT_ASR_MODEL=medium
ASSISTANT_ASR_DEVICE=cpu
ASSISTANT_ASR_COMPUTE=int8
```

有 NVIDIA 显卡建议：

```text
ASSISTANT_ASR_MODEL=large-v3
ASSISTANT_ASR_DEVICE=cuda
ASSISTANT_ASR_COMPUTE=float16
```

### 5.1.3 上下文提示词

为了识别技术词和项目词，ASR 应支持 `initial_prompt`。

示例：

```text
以下是一个中文语音助手场景。
用户可能会提到：
DeepSeek、FastAPI、Electron、VTube Studio、Amadeus、命运石之门、
arXiv、Whisper、faster-whisper、Silero VAD、I-20、休斯顿大学、
傅里叶变换、互信息、信息瓶颈、Domain Watermark、ANCHOR、ADC、RF。
请保留英文技术词，不要强行翻译。
```

### 5.1.4 输出结构

ASR 不应只返回文本，应返回置信度、耗时、片段等信息。

```json
{
  "ok": true,
  "text": "我想让她更加像真人，但是我中间说话会犹豫一下",
  "engine": "faster_whisper",
  "language": "zh",
  "duration_ms": 1840,
  "segments": [
    {
      "start": 0.0,
      "end": 2.1,
      "text": "我想让她更加像真人"
    }
  ],
  "confidence": 0.86
}
```

---

## 5.2 VAD Service 升级

### 5.2.1 当前问题

能量阈值 VAD 只能计算 RMS：

```text
level = sqrt(mean(x_i^2))
```

然后判断：

```text
level >= threshold
```

这会把很多非人声声音也识别成语音。

### 5.2.2 新方案

引入神经网络 VAD：

```text
Silero VAD
```

处理单位：

```text
16kHz mono PCM
每帧 20~30ms
```

输出：

```text
speech_probability ∈ [0, 1]
```

判断：

```text
speech_probability >= 0.5 → speech
speech_probability < 0.5  → non-speech
```

### 5.2.3 前端采集建议

前端不要再用：

```text
MediaRecorder → webm blob → decodeAudioData → wav
```

建议改成：

```text
getUserMedia
    ↓
AudioWorklet
    ↓
16kHz mono PCM frame
    ↓
WebSocket /ws/audio
```

麦克风配置：

```js
navigator.mediaDevices.getUserMedia({
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true
  }
})
```

这对 AI 说话时的打断检测非常重要，因为需要减少 TTS 声音被麦克风重新录进去。

---

## 5.3 Endpointing：判断用户是否说完

### 5.3.1 设计原则

静音不等于说完。

真实对话中，以下情况都不能立刻回答：

```text
“我想让她更像真人，就是……”
“然后……”
“不是，我的意思是……”
“等一下，我想一下……”
“先别回答，我还没说完……”
```

所以 endpointing 需要综合：

```text
1. 静音时间
2. 当前文本是否语义完整
3. 句尾是否像继续说
4. 是否包含明确交权词
5. 是否包含禁止回答词
6. ASR 置信度
7. 当前是否处于 AI_SPEAKING 状态
```

### 5.3.2 停顿分层

建议停顿阈值：

```text
0 ~ 600ms：
    正常语流停顿，不处理。

600 ~ 1200ms：
    轻微犹豫，继续听。

1200 ~ 2200ms：
    可能说完，但要看语义。

2200 ~ 3500ms：
    大概率说完，除非有继续说标记。

> 3500ms：
    基本认为用户说完，除非用户明确说“别回答 / 我还没说完”。
```

### 5.3.3 EndScore 数学模型

定义：

```text
S_end = S_silence + S_semantic + S_question + S_handoff
        - P_continue - P_hesitation - P_low_confidence
```

其中：

```text
S_silence：静音时长得分
S_semantic：语义完整得分
S_question：疑问句得分
S_handoff：交出话语权得分
P_continue：继续说标记惩罚
P_hesitation：犹豫标记惩罚
P_low_confidence：低置信度惩罚
```

具体可设：

```text
S_silence =
    0.0, silence_ms < 600
    0.2, 600 <= silence_ms < 1200
    0.5, 1200 <= silence_ms < 2200
    0.8, 2200 <= silence_ms < 3500
    1.0, silence_ms >= 3500

S_question =
    0.4, 文本以“吗 / 呢 / ？ / ?”结尾
    0.0, otherwise

S_handoff =
    1.0, 包含“你说 / 你觉得 / 你来回答 / 给我建议 / 我说完了”
    0.0, otherwise

P_continue =
    1.0, 句尾包含“然后 / 还有 / 就是 / 比如 / 我的意思是”
    0.0, otherwise

P_hesitation =
    0.5, 包含“嗯 / 呃 / 怎么说 / 我想一下”
    0.0, otherwise

P_low_confidence =
    0.5, ASR confidence < 0.6
    0.0, otherwise
```

决策：

```text
S_end >= 1.0       → ANSWER_NOW
0.4 <= S_end < 1.0 → WAIT_MORE
S_end < 0.4        → LISTENING
```

这样可以避免用户只是犹豫一下，AI 就抢话。

---

## 5.4 TurnManager 设计

### 5.4.1 状态机

新增对话状态：

```text
IDLE              空闲
LISTENING         正在听用户说话
THINKING_PAUSE    用户短暂停顿，等待其继续
WAITING_MORE      用户语义未完，继续听
ANSWERING         后端正在生成回答
AI_SPEAKING       AI 正在播放语音
INTERRUPTED       用户打断 AI
ERROR             出错
```

状态转移：

```text
IDLE
  ↓ 用户开始说话
LISTENING
  ↓ 检测到短暂停顿
THINKING_PAUSE
  ↓ 用户继续说话
LISTENING
  ↓ 判断语义完整
ANSWERING
  ↓ 首句生成
AI_SPEAKING
  ↓ 播放结束
IDLE
```

打断路径：

```text
AI_SPEAKING
  ↓ 用户强打断
INTERRUPTED
  ↓ 停止音频 / 取消请求 / 清空队列
LISTENING
```

### 5.4.2 TurnDecision 输出

新增 API：

```text
POST /api/turn/decide
```

请求：

```json
{
  "transcript": "我想让她更像真人，就是",
  "partial": false,
  "silence_ms": 1800,
  "speech_ms": 4200,
  "asr_confidence": 0.81,
  "state": "LISTENING",
  "ai_speaking": false
}
```

返回：

```json
{
  "action": "wait_more",
  "confidence": 0.87,
  "reason": "句尾是“就是”，语义明显未完成，属于思考停顿",
  "backchannel": null
}
```

可能 action：

```text
ignore       忽略噪声或无意义文本
listening    继续听
wait_more    用户可能还没说完，继续等
backchannel  轻微反馈，不正式回答
answer_now   用户说完，可以回答
interrupt    用户正在打断 AI
```

### 5.4.3 规则词表

继续说标记：

```python
WAIT_MORE_MARKERS = [
    "然后",
    "还有",
    "而且",
    "另外",
    "就是",
    "就是说",
    "怎么说",
    "比如",
    "比如说",
    "举个例子",
    "我的意思是",
    "不是",
    "不对",
    "等一下",
    "我想一下",
    "我还没说完",
    "先别回答",
    "接着说"
]
```

交出话语权标记：

```python
ANSWER_NOW_MARKERS = [
    "你觉得",
    "你说",
    "你来",
    "回答我",
    "帮我",
    "怎么做",
    "怎么改",
    "给我建议",
    "我说完了",
    "就这样",
    "开始吧",
    "你怎么看"
]
```

强打断标记：

```python
INTERRUPT_MARKERS = [
    "停",
    "先停",
    "别说了",
    "等一下",
    "等等",
    "打断一下",
    "我打断一下",
    "不是这个",
    "不对",
    "闭嘴"
]
```

附和词：

```python
BACKCHANNEL_ONLY_MARKERS = [
    "嗯",
    "对",
    "好",
    "是的",
    "哦",
    "可以",
    "继续"
]
```

---

## 5.5 Barge-in：自然打断设计

### 5.5.1 目标

AI 说话时，用户应该可以打断，但不能因为用户轻微附和就错误停止。

### 5.5.2 判断逻辑

AI 正在说话时：

```text
1. 如果检测到短噪声 < 300ms：
       忽略。

2. 如果用户只说“嗯 / 对 / 好 / 是的”：
       认为是附和，不打断。

3. 如果用户连续说话 > 600~800ms：
       认为用户要插话，停止 AI 语音。

4. 如果识别到强打断词：
       立即停止 AI 语音。
```

### 5.5.3 打断后的动作

```text
1. stopCurrentAudio()
2. window.speechSynthesis.cancel()
3. 清空 TTS 队列
4. AbortController 取消前端 chat 请求
5. 后端取消 LLM streaming
6. 状态切换到 LISTENING
7. 字幕显示：“我停下了，你说。”
```

### 5.5.4 不应打断的情况

```text
用户只是说：
“嗯”
“对”
“好”
“继续”
“是”
```

这些属于 backchannel，不是 interrupt。

---

## 5.6 LLM Streaming 设计

### 5.6.1 当前问题

当前 `/api/chat` 是完整 JSON 返回，不适合实时播放。

### 5.6.2 新接口

保留旧接口：

```text
POST /api/chat
```

新增流式接口：

```text
POST /api/chat/stream
```

建议返回 Server-Sent Events：

```text
event: status
data: {"state": "thinking"}

event: delta_ja
data: {"text": "そうね、"}

event: delta_zh
data: {"text": "是这样，"}

event: sentence_done
data: {
  "ja_text": "そうね、まず会話の割り込み判定を分けるべきよ。",
  "zh_subtitle": "是这样，首先应该把对话打断判断拆开。"
}

event: emotion
data: {"emotion": "thinking", "gesture": "explain"}

event: done
data: {"finish_reason": "stop"}
```

### 5.6.3 快慢路径拆分

当前模型一次生成：

```json
{
  "ja_text": "...",
  "zh_subtitle": "...",
  "emotion": "...",
  "gesture": "...",
  "voice_style": "...",
  "memory_update": [...],
  "tool_intent": {...}
}
```

建议拆成：

```text
快速路径：
    ja_text
    zh_subtitle

慢速路径：
    emotion
    gesture
    voice_style
    memory_update
    tool_intent
```

快速路径用于立刻说话；慢速路径用于表情、动作、记忆、权限判断。

---

## 5.7 Sentence-level TTS 设计

### 5.7.1 目标

AI 不再等完整长回答生成完才说话，而是按句播放。

```text
LLM 生成第一句
    ↓
TTS 合成第一句
    ↓
播放第一句
    ↓
LLM 继续生成第二句
    ↓
TTS 合成第二句并排队
```

### 5.7.2 句子切分

日语句子终止符：

```text
。！？!? 
```

中文字幕句子终止符：

```text
。！？!?
```

句子切分器维护 buffer：

```text
buffer += delta
if buffer contains sentence_end:
    emit sentence_done
```

### 5.7.3 TTS 队列

前端维护：

```js
const ttsQueue = [];
let isPlayingTTS = false;
let currentAudio = null;
```

行为：

```text
enqueue(sentence_audio_url)
    ↓
如果当前没播放，立刻播放
    ↓
播放结束后取下一句
```

打断时：

```text
currentAudio.pause()
currentAudio.currentTime = 0
ttsQueue.length = 0
speechSynthesis.cancel()
```

---

## 6. 推荐实施路线

## Phase 1：快速提升 ASR 准确率

优先级：最高

改动：

```text
1. 保留现有 google provider。
2. 新增 faster_whisper provider。
3. 新增 ASR initial_prompt。
4. 新增 ASR 配置项。
5. /api/health 显示当前 ASR provider、model、device。
```

验收标准：

```text
1. 普通中文语音识别准确率明显提升。
2. 技术词如 FastAPI、DeepSeek、Electron、Amadeus 不再频繁识别错。
3. 10~20 秒长语音识别稳定性提升。
4. google provider 仍可作为 fallback。
```

---

## Phase 2：优化停顿判断，避免抢话

优先级：最高

改动：

```text
1. 新增 TurnManager。
2. 新增 /api/turn/decide。
3. 前端 finishRecording() 不再直接 sendMessage()。
4. ASR 完成后先调用 /api/turn/decide。
5. 根据 action 决定继续听、轻反馈、回答、打断。
```

新流程：

```text
finishRecording(blob)
    ↓
transcribeAudio(blob)
    ↓
turnDecision = /api/turn/decide
    ↓
if answer_now:
    sendMessage(text)
elif wait_more:
    append transcript and restart listening
elif backchannel:
    play small feedback and restart listening
elif interrupt:
    stop AI and listen
```

验收标准：

```text
1. 用户说“我想一下”“就是……”时，AI 不抢答。
2. 用户说“你觉得怎么改”时，AI 能快速回答。
3. 用户说“先别回答”时，AI 继续听。
```

---

## Phase 3：支持自然打断

优先级：高

改动：

```text
1. AI_SPEAKING 状态下仍保留 interrupt listener。
2. 新增 stopCurrentAudio()。
3. 新增 ttsQueue 清空逻辑。
4. 新增 AbortController。
5. 新增 pet:cancel-chat 或前端直接 fetch 支持 abort。
```

验收标准：

```text
1. AI 正在说话时，用户说“停”能立刻停止。
2. 用户说“不是这个”能中断当前回答。
3. 用户只是“嗯 / 对 / 好”时，AI 不停止。
```

---

## Phase 4：LLM 流式响应

优先级：中高

改动：

```text
1. 保留 /api/chat。
2. 新增 /api/chat/stream。
3. DeepSeekClient 新增 stream_chat_text()。
4. 前端支持 SSE。
5. 第一完整句生成后立刻进入 TTS。
```

验收标准：

```text
1. 用户说完后 1~2 秒内 AI 开始说第一句话。
2. 长回答不再等待完整生成后才播放。
3. 用户可以中途打断 streaming。
```

---

## Phase 5：Streaming ASR 和 AudioWorklet

优先级：中

改动：

```text
1. 前端从 MediaRecorder 改成 AudioWorklet。
2. 音频以 16kHz mono PCM frame 通过 WebSocket 发送。
3. 后端新增 /ws/audio。
4. 后端做 VAD、partial transcript、final transcript。
```

验收标准：

```text
1. 用户说话时前端能实时显示 partial transcript。
2. 用户停顿时 endpointing 更准确。
3. 长语音不需要等整段录完再识别。
```

---

## 7. API 设计

## 7.1 `/api/turn/decide`

### Request

```json
{
  "transcript": "我想让她更像真人，就是",
  "silence_ms": 1800,
  "speech_ms": 5200,
  "asr_confidence": 0.82,
  "state": "LISTENING",
  "ai_speaking": false
}
```

### Response

```json
{
  "action": "wait_more",
  "confidence": 0.87,
  "reason": "句尾包含继续说标记“就是”，语义未完成",
  "backchannel": null
}
```

---

## 7.2 `/api/chat/stream`

### Request

```json
{
  "text": "我想让她更像真人，怎么改？",
  "source": "voice",
  "model": "deepseek-v4-flash"
}
```

### SSE Response

```text
event: status
data: {"state": "thinking"}

event: delta
data: {"ja": "まず", "zh": "首先"}

event: sentence_done
data: {
  "ja_text": "まず、聞く状態と話す状態を分けるべきよ。",
  "zh_subtitle": "首先，应该把听的状态和说的状态分开。",
  "voice_style": "normal"
}

event: done
data: {}
```

---

## 7.3 `/api/audio/interrupt`

可选接口，用于通知后端当前回答被用户打断。

### Request

```json
{
  "conversation_id": "conv_2026_06_23_001",
  "reason": "user_barge_in",
  "transcript": "等一下，不是这个"
}
```

### Response

```json
{
  "ok": true,
  "cancelled": true
}
```

---

## 8. 前端改造点

### 8.1 `finishRecording()`

当前逻辑：

```text
ASR → sendMessage()
```

应改为：

```text
ASR → TurnManager → 根据 action 决策
```

伪代码：

```js
async function finishRecording(blob) {
  const result = await transcribeAudio(blob);
  const text = (result.text || "").trim();

  if (!text) {
    zhText.textContent = "这句我没有听清。再自然说一次。";
    return;
  }

  const decision = await decideTurn({
    transcript: text,
    silence_ms: currentSilenceMs,
    speech_ms: currentSpeechMs,
    asr_confidence: result.confidence ?? 0.8,
    state: currentDialogState,
    ai_speaking: isAISpeaking,
  });

  if (decision.action === "answer_now") {
    await sendMessageStream(text, "voice");
  } else if (decision.action === "wait_more") {
    appendPendingTranscript(text);
    restartListening();
  } else if (decision.action === "backchannel") {
    playBackchannel(decision.backchannel);
    restartListening();
  } else if (decision.action === "interrupt") {
    stopCurrentAudio();
    restartListening();
  }
}
```

---

### 8.2 `speakJapanese()`

当前是单段播放。应扩展为：

```text
playAudio(url)
enqueueTTS(sentence)
clearTTSQueue()
stopCurrentAudio()
```

伪代码：

```js
function stopCurrentAudio() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  ttsQueue.length = 0;
  avatar.classList.remove("speaking");
}
```

---

### 8.3 打断监听

AI 说话时不应完全关闭监听，而应进入 interrupt listening：

```text
AI_SPEAKING
    ↓
开启高阈值监听
    ↓
检测到强打断词或连续语音
    ↓
stopCurrentAudio()
    ↓
取消当前请求
    ↓
切换 LISTENING
```

---

## 9. 后端改造点

### 9.1 新增文件

建议新增：

```text
src/assistant_app/turn.py
src/assistant_app/audio_stream.py
src/assistant_app/transcript.py
```

### 9.2 `turn.py`

职责：

```text
1. 根据 transcript、silence_ms、speech_ms、asr_confidence、state 判断动作。
2. 维护规则词表。
3. 计算 EndScore。
4. 输出 TurnDecision。
```

### 9.3 `asr.py`

职责升级：

```text
1. 保留 Google ASR。
2. 新增 faster-whisper ASR。
3. 支持模型缓存。
4. 支持 initial_prompt。
5. 支持 segments 和 confidence。
```

### 9.4 `providers/deepseek.py`

职责升级：

```text
1. 保留 chat_json()。
2. 新增 chat_stream()。
3. 复用 httpx.AsyncClient，避免每次请求重新建立连接。
4. 支持 cancellation。
```

### 9.5 `app.py`

新增 endpoint：

```text
POST /api/turn/decide
POST /api/chat/stream
POST /api/audio/interrupt
WS   /ws/audio
```

---

## 10. 性能指标

建议记录以下指标：

```text
ASR latency:
    从用户停止说话到转写完成的时间

ASR accuracy:
    人工抽样评估字错率 / 关键词错率

Endpoint false positive:
    用户没说完但 AI 抢答的比例

Endpoint false negative:
    用户说完但 AI 长时间不回答的比例

First token latency:
    LLM 第一个 token 返回时间

First speech latency:
    用户说完到 AI 发出第一句语音的时间

Interrupt latency:
    用户说“停”到 AI 停止播放的时间

TTS first sentence latency:
    第一完整句生成到音频播放的时间
```

目标值：

```text
First speech latency:
    理想：1.0 ~ 2.0 秒
    可接受：2.0 ~ 3.5 秒

Interrupt latency:
    理想：< 300ms
    可接受：< 800ms

Endpoint false positive:
    目标：低于 5%

关键词识别准确率：
    目标：DeepSeek / FastAPI / Electron / Amadeus 等高频词 > 95%
```

---

## 11. 风险与处理

### 11.1 本地 Whisper 模型慢

处理：

```text
1. 提供 small / medium / large-v3 多档配置。
2. CPU 默认 int8。
3. GPU 默认 float16。
4. 保留 google fallback。
```

### 11.2 AI 自己的声音被麦克风录进去

处理：

```text
1. 开启 echoCancellation。
2. AI_SPEAKING 时提高 interrupt 阈值。
3. 对附和词和强打断词做区分。
4. 尽量使用耳机或系统级回声消除。
```

### 11.3 TurnManager 规则过死

处理：

```text
1. 第一版用规则。
2. 第二版引入轻量 LLM classifier。
3. 保留用户可调参数。
4. 记录误判样本，用于优化规则。
```

### 11.4 流式 JSON 难解析

处理：

```text
1. 不要流式生成完整 JSON。
2. 正文和元数据拆分。
3. 正文用 SSE delta。
4. 元数据在 done 前后单独生成。
```

---

## 12. 最终推荐结论

为了满足“像真人一样说话”的目标，系统不应只追求“更快回答”，而应追求：

```text
该快的时候快；
该等的时候等；
该停的时候停；
该继续听的时候继续听。
```

因此推荐升级优先级为：

```text
1. faster-whisper ASR
2. TurnManager 轮次判断
3. 自然打断 barge-in
4. LLM streaming
5. sentence-level TTS
6. AudioWorklet + streaming ASR
```

最终系统应形成如下体验：

```text
用户自然说话：
    AI 持续听。

用户中间犹豫：
    AI 不抢话，只等待。

用户说“你觉得怎么改”：
    AI 快速回答。

AI 正在说话，用户说“等一下，不是这个”：
    AI 立即停下。

用户只是“嗯，对”：
    AI 不误停，继续说。

长回答：
    AI 第一两秒先开口，后续边生成边播放。
```

这才是接近真人对话的技术路径。
