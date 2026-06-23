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
2. 轮次判断不自然，当前更接近"检测到静音就回答"，而不是像人一样判断用户是否真的说完。
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
5. 用户只是"嗯 / 对 / 好"这种附和时，AI 不应错误停止。
6. AI 回复应尽快开始，而不是等完整长回答生成后才开口。
7. AI 的语音、字幕、表情、动作仍然与现有 companion 系统集成。
```

### 2.2 技术目标

ASR 准确率：优先提升长语音和技术词识别，目标 WER ≤ 15%。轮次判断延迟：从静音判断升级为语义+语音综合判断，端到端延迟 ≤ 1.5s。响应速度：首句 TTS 延迟从等待完整回答改为 streaming 输出，首句延迟 ≤ 2s。打断响应：用户打断后系统在 1s 内停止当前回放并切到监听模式。资源占用：在本地 GPU 或纯 CPU 环境下可持续运行。

---

## 3. 架构变更

### 3.1 新增模块

```
src/
├── assistant_app/
│   ├── turn.py          # 轮次判断模块（新任）
│   ├── asr_stream.py    # 流式 ASR 封装（未来）
│   └── tts_stream.py    # 流式 TTS 封装（未来）
```

### 3.2 新增 API 端点

```text
POST /api/turn/decide
```

请求体：

```json
{
  "text": "用户当前转录文本",
  "silence_ms": 1200,
  "speech_ms": 3500,
  "confidence": 0.85,
  "ai_speaking": false
}
```

响应体：

```json
{
  "action": "answer_now | wait_more | backchannel | interrupt",
  "reason": "交出话语权标记: '你觉得呢'",
  "score": 0.72
}
```

---

## 4. 轮次判断模块（TurnManager）

### 4.1 规则结构

```
WAIT_MORE_MARKERS      → 倾向于等用户把话说完
ANSWER_NOW_MARKERS     → 用户交出了话语权
INTERRUPT_MARKERS      → 用户想打断 AI
BACKCHANNEL_ONLY_MARKERS → 用户只是附和
```

### 4.2 核心规则

句尾包含"就是 / 然后 / 我的意思是 / 我想一下"会倾向于 wait_more。AI 正在说话时检测到"停 / 别说了 / 打断一下 / 不是这个"会返回 interrupt。AI 正在说话时用户只说"嗯 / 对 / 好"会走 backchannel。长静音（> 3s）默认 answer_now 回答。

### 4.3 分数计算（calc_endscore）

```
endscore = base_score * silence_factor * confidence_factor * speech_duration_factor
```

- base_score: 根据文本内容给出初始分
- silence_factor: 用户停顿越长，越倾向回答
- confidence_factor: ASR 置信度越低，越倾向多听一会儿
- speech_duration_factor: 用户已说很长时间，适当提高回答倾向

---

## 5. 前端变更

### 5.1 流程

```
录音结束 → ASR → /api/turn/decide → wait_more / backchannel / answer_now / interrupt
```

### 5.2 新增数据结构

- ttsQueue: TTS 播放队列
- isPlayingTTS: 是否正在播放 TTS
- pendingTranscript: 累积的 ASR 结果
- decisionCache: turn 决定的缓存

### 5.3 状态变更

```
IDLE → LISTENING → PROCESSING (ASR) → DECIDING (TurnManager) → 
  ├─ WAITING (wait_more → 继续监听)
  ├─ ANSWERING (answer_now → /api/chat → TTS)
  ├─ BACKCHANNEL (短回应用户附和 → 继续监听)
  └─ INTERRUPTING (停止当前 TTS → 切换为监听)
```

---

## 6. 实现计划

### Phase 1: TurnManager 后端 + 前端骨架（已完成）

- [x] turn.py 后端模块
- [x] /api/turn/decide 接口
- [x] 前端 ASR 后先调用 decideTurn()
- [x] pendingTranscript 累积逻辑
- [x] backchannel / wait_more / answer_now / interrupt 分支
- [x] TTS queue 初步框架
- [x] 单元测试（test_turn.py）

### Phase 2: 真正可打断（TODO）

- [ ] AI 说话时继续监听（interrupt-only recorder）
- [ ] 真正 barge-in 打断
- [ ] AbortController 取消正在进行的 chat 请求

### Phase 3: 流式处理（TODO）

- [ ] faster-whisper ASR
- [ ] ASR confidence 返回值
- [ ] LLM streaming
- [ ] sentence-level TTS 分句播放

### Phase 4: 优化与稳定（TODO）

- [ ] 启动脚本稳定性
- [ ] 对话上下文管理
- [ ] 性能调优