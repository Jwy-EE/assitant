/*
 * Research Companion — 连续对话状态机
 *
 * 状态: IDLE → LISTENING → DECIDING → ANSWERING → (自动回到 LISTENING)
 *          → IDLE (手动取消)
 *
 * 关键特性:
 * 1. 连续对话: AI 说完自动开始听
 * 2. 智能轮次: 调用 /api/turn/decide，支持 wait_more / backchannel
 * 3. 自然打断: AI 说话时后台监听，用户说话即打断
 * 4. 字幕同步: 逐句显示，与 TTS 播放同步
 */

/* ============================================================
   常量
   ============================================================ */
const STATE = {
  IDLE: "IDLE",
  LISTENING: "LISTENING",
  DECIDING: "DECIDING",
  ANSWERING: "ANSWERING",
};

const VAD_POLL_MS = 80;          // VAD 轮询间隔 (ms)
const SPEECH_THRESHOLD = 0.024;  // 能量阈值
const INTERRUPT_SPEECH_MS = 400; // 打断需要的连续说话时长
const DECIDE_POLL_MS = 600;      // 轮次判断轮询间隔
const MIN_SPEECH_MS = 400;       // 最小有效语音时长
const MAX_RECORDING_MS = 30000;  // 单次最长录音
const MAX_WAIT_FOR_SPEECH_MS = 8000; // 最长等用户开口
const BACKCHANNEL_COOLDOWN_MS = 3000; // 附和冷却 (避免连发)

/* ============================================================
   DOM 引用
   ============================================================ */
const $ = (id) => document.getElementById(id);
const form = $("chatForm");
const userText = $("userText");
const jaText = $("jaText");
const zhText = $("zhText");
const subtitleSentences = $("subtitleSentences");
const toolBox = $("toolBox");
const emotion = $("emotion");
const workMode = $("workMode");
const avatar = $("avatar");
const saveKey = $("saveKey");
const apiKey = $("apiKey");
const health = $("health");
const micButton = $("micButton");
const refreshButton = $("refreshButton");
const researchForm = $("researchForm");
const researchQuery = $("researchQuery");
const paperList = $("paperList");
const memoryForm = $("memoryForm");
const memoryKind = $("memoryKind");
const memoryContent = $("memoryContent");
const memoryList = $("memoryList");
const commandText = $("commandText");
const inspectCommand = $("inspectCommand");
const commandResult = $("commandResult");
const loadDivergence = $("loadDivergence");
const loadDivergenceNews = $("loadDivergenceNews");
const divergenceResult = $("divergenceResult");
const micIndicator = $("micIndicator");

/* ============================================================
   状态变量
   ============================================================ */
let currentState = STATE.IDLE;
let isRecording = false;

// 录音
let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let audioContext = null;
let analyserNode = null;
let sourceNode = null;
let vadInterval = null;
let decideInterval = null;

// 时间
let recordingStartedAt = 0;
let speechStartedAt = 0;
let lastVoiceAt = 0;
let hasDetectedSpeech = false;
let lastDecideAt = 0;
let pendingTranscript = "";

// 播放
let currentAudio = null;
let isSpeaking = false;
let conversationHistory = [];
let lastBackchannelAt = 0;

// AbortController (用于取消进行中的 chat 请求)
let currentChatAbort = null;

// 打断监听 (AI 说话时后台用的)
let interruptLevel = null;
let interruptSpeechStart = 0;
let interruptStream = null;

/* ============================================================
   状态机核心
   ============================================================ */
function setState(newState) {
  console.log(`[state] ${currentState} → ${newState}`);
  currentState = newState;
  updateMicButton();
  updateMicIndicator();
}

function updateMicButton() {
  switch (currentState) {
    case STATE.IDLE:
      micButton.textContent = "🎤 说话";
      micButton.classList.remove("recording", "answering", "thinking");
      break;
    case STATE.LISTENING:
      micButton.textContent = "⬛ 停止";
      micButton.classList.add("recording");
      micButton.classList.remove("answering", "thinking");
      break;
    case STATE.DECIDING:
      micButton.textContent = "⏳ 思考";
      micButton.classList.add("thinking");
      micButton.classList.remove("recording", "answering");
      break;
    case STATE.ANSWERING:
      micButton.textContent = "🔊 说话中";
      micButton.classList.add("answering");
      micButton.classList.remove("recording", "thinking");
      break;
  }
}

function updateMicIndicator() {
  if (!micIndicator) return;
  micIndicator.className = "mic-indicator";
  switch (currentState) {
    case STATE.LISTENING:
      micIndicator.classList.add("listening");
      break;
    case STATE.DECIDING:
      micIndicator.classList.add("deciding");
      break;
    case STATE.ANSWERING:
      micIndicator.classList.add("answering");
      break;
    default:
      micIndicator.classList.add("idle");
  }
}

/* ============================================================
   音频工具
   ============================================================ */
function stopMediaTracks(stream) {
  if (!stream) return;
  for (const track of stream.getTracks()) {
    track.stop();
  }
}

async function cleanupAudio() {
  if (vadInterval) {
    clearInterval(vadInterval);
    vadInterval = null;
  }
  if (decideInterval) {
    clearInterval(decideInterval);
    decideInterval = null;
  }
  if (sourceNode) {
    sourceNode.disconnect();
    sourceNode = null;
  }
  if (analyserNode) {
    analyserNode.disconnect();
    analyserNode = null;
  }
  if (audioContext) {
    try { await audioContext.close(); } catch { /* ignore */ }
    audioContext = null;
  }
  stopMediaTracks(mediaStream);
  mediaStream = null;
  mediaRecorder = null;
}

function resetRecordingVars() {
  isRecording = false;
  recordingStartedAt = 0;
  speechStartedAt = 0;
  lastVoiceAt = 0;
  hasDetectedSpeech = false;
  lastDecideAt = 0;
  recordedChunks = [];
}

function calculateLevel() {
  if (!analyserNode) return 0;
  const data = new Uint8Array(analyserNode.fftSize);
  analyserNode.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const centered = (data[i] - 128) / 128;
    sum += centered * centered;
  }
  return Math.sqrt(sum / data.length);
}

/* ============================================================
   打断监听 (AI 说话时后台运行)
   ============================================================ */
async function startInterruptMonitor() {
  try {
    interruptStream = await navigator.mediaDevices.getUserMedia({ audio: true, echoCancellation: true });
  } catch {
    return; // 没有麦克风，无法打断
  }

  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(interruptStream);
  const anl = ctx.createAnalyser();
  anl.fftSize = 1024;
  src.connect(anl);

  interruptSpeechStart = 0;
  const poll = () => {
    if (currentState !== STATE.ANSWERING) {
      // 不在回答状态，停止打断监听
      src.disconnect();
      ctx.close().catch(() => {});
      stopMediaTracks(interruptStream);
      interruptStream = null;
      return;
    }
    const data = new Uint8Array(anl.fftSize);
    anl.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const centered = (data[i] - 128) / 128;
      sum += centered * centered;
    }
    const level = Math.sqrt(sum / data.length);
    
    if (level >= SPEECH_THRESHOLD) {
      if (interruptSpeechStart === 0) {
        interruptSpeechStart = Date.now();
      } else if (Date.now() - interruptSpeechStart >= INTERRUPT_SPEECH_MS) {
        // 用户说话足够长 → 打断
        console.log("[interrupt] 检测到用户说话，打断 AI");
        doInterrupt();
        return;
      }
    } else {
      interruptSpeechStart = 0;
    }
    requestAnimationFrame(poll);
  };
  requestAnimationFrame(poll);
}

function doInterrupt() {
  // 停止当前音频播放
  stopSpeaking();
  // 取消进行中的 chat 请求
  if (currentChatAbort) {
    currentChatAbort.abort();
    currentChatAbort = null;
  }
  // 显示状态
  zhText.textContent = "好的，你先说。";
  jaText.textContent = "わかった。聞いているわ。";
  // 回到监听状态
  setState(STATE.LISTENING);
  // 开始监听
  startListening();
}

/* ============================================================
   播放 & 字幕同步
   ============================================================ */
function stopSpeaking() {
  isSpeaking = false;
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if ("speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
  avatar.classList.remove("speaking");
}

/**
 * 逐句播放 & 字幕同步
 * @param {string} jaText - 日语文本
 * @param {string} zhText - 中文字幕
 * @param {string} audioUrl - 可选的音频 URL
 * @param {Function} onDone - 播放完毕回调
 */
function speakWithSubtitles(jaText, zhText, audioUrl, onDone) {
  if (!jaText && !zhText) {
    onDone?.();
    return;
  }

  // 清空字幕区
  subtitleSentences.innerHTML = "";
  
  // 按句号/感叹号/问号/换行分句
  const jaSentences = splitSentences(jaText);
  const zhSentences = splitSentences(zhText);
  
  // 先显示全部字幕（备用）
  const fullJa = $("jaText");
  const fullZh = $("zhText");
  fullJa.textContent = jaText;
  fullZh.textContent = zhText;
  
  let currentIndex = 0;
  isSpeaking = true;
  avatar.classList.add("speaking");
  
  // 并行启动打断监听
  startInterruptMonitor();

  function playNextSentence() {
    if (!isSpeaking || currentIndex >= jaSentences.length) {
      // 全部播完
      avatar.classList.remove("speaking");
      isSpeaking = false;
      onDone?.();
      return;
    }

    const jaSentence = jaSentences[currentIndex];
    const zhSentence = zhSentences[currentIndex] || zhSentences[zhSentences.length - 1] || "";
    
    // 添加字幕行并高亮当前句
    const sentEl = document.createElement("div");
    sentEl.className = "subtitle-sentence";
    sentEl.innerHTML = `<span class="sentence-ja">${escapeHtml(jaSentence)}</span><span class="sentence-zh">${escapeHtml(zhSentence)}</span>`;
    subtitleSentences.appendChild(sentEl);
    
    // 滚动到当前句
    sentEl.scrollIntoView({ behavior: "smooth", block: "nearest" });

    // 移除其他高亮
    document.querySelectorAll(".subtitle-sentence.active").forEach(el => el.classList.remove("active"));
    sentEl.classList.add("active");

    // 播放
    if (audioUrl) {
      // 后端合成音频 — 整体播放，但仍然逐句高亮字幕
      if (!currentAudio) {
        currentAudio = new Audio(audioUrl);
        currentAudio.onplay = () => avatar.classList.add("speaking");
        currentAudio.onended = () => {
          avatar.classList.remove("speaking");
          isSpeaking = false;
          onDone?.();
        };
        currentAudio.onerror = () => {
          // 回退到浏览器 TTS
          currentAudio = null;
          playNextSentenceWithBrowserTTS(jaSentences, zhSentences, 0, onDone);
        };
        currentAudio.play().catch(() => {
          currentAudio = null;
          playNextSentenceWithBrowserTTS(jaSentences, zhSentences, 0, onDone);
        });
        // 字幕按时间推进（基于句子数均分时长）
        if (currentAudio) {
          const totalDuration = jaSentences.length * 1500; // 估算
          const perSentence = totalDuration / jaSentences.length;
          setTimeout(() => {
            sentEl.classList.remove("active");
            currentIndex++;
            playNextSentence();
          }, perSentence);
        }
      }
    } else {
      // 浏览器 TTS 逐句播放
      playNextSentenceWithBrowserTTS(jaSentences, zhSentences, currentIndex, onDone, sentEl);
    }
  }

  function playNextSentenceWithBrowserTTS(jaSents, zhSents, idx, done, activeEl) {
    if (!isSpeaking || idx >= jaSents.length) {
      avatar.classList.remove("speaking");
      isSpeaking = false;
      done?.();
      return;
    }
    
    if (!("speechSynthesis" in window)) {
      // 不支持 TTS，快速过字幕
      const step = () => {
        if (!isSpeaking) { done?.(); return; }
        if (idx >= jaSents.length) { isSpeaking = false; done?.(); return; }
        idx++;
        setTimeout(step, 300);
      };
      setTimeout(step, 300);
      return;
    }

    const utterance = new SpeechSynthesisUtterance(jaSents[idx]);
    utterance.lang = "ja-JP";
    utterance.rate = 0.96;
    utterance.pitch = 0.92;
    
    utterance.onstart = () => {
      avatar.classList.add("speaking");
      // 高亮当前句
      document.querySelectorAll(".subtitle-sentence.active").forEach(el => el.classList.remove("active"));
      if (activeEl) activeEl.classList.add("active");
    };
    utterance.onend = () => {
      if (activeEl) activeEl.classList.remove("active");
      idx++;
      // 播放下一句
      if (isSpeaking) {
        const nextJa = jaSents[idx];
        const nextZh = zhSents[idx] || "";
        if (nextJa) {
          const nextEl = document.createElement("div");
          nextEl.className = "subtitle-sentence";
          nextEl.innerHTML = `<span class="sentence-ja">${escapeHtml(nextJa)}</span><span class="sentence-zh">${escapeHtml(nextZh)}</span>`;
          subtitleSentences.appendChild(nextEl);
          nextEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
          playNextSentenceWithBrowserTTS(jaSents, zhSents, idx, done, nextEl);
        } else {
          avatar.classList.remove("speaking");
          isSpeaking = false;
          done?.();
        }
      }
    };
    utterance.onerror = () => {
      // 跳过当前句继续
      idx++;
      if (isSpeaking) {
        playNextSentenceWithBrowserTTS(jaSents, zhSents, idx, done, activeEl);
      }
    };
    window.speechSynthesis.speak(utterance);
  }

  playNextSentence();
}

function splitSentences(text) {
  if (!text) return [];
  // 按句号/感叹号/问号/换行/分句，保留分隔符
  const parts = text.match(/[^。！？\n.!?]+[。！？\n.!?]?/g);
  return parts ? parts.map(s => s.trim()).filter(s => s.length > 0) : [text];
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/* ============================================================
   录音 & 连续对话核心
   ============================================================ */
async function toggleRecording() {
  if (currentState === STATE.IDLE) {
    // 开始对话
    await startListening();
  } else {
    // 停止一切
    await cancelAll();
  }
}

async function cancelAll() {
  console.log("[cancel] 取消所有操作");
  stopSpeaking();
  if (currentChatAbort) {
    currentChatAbort.abort();
    currentChatAbort = null;
  }
  await stopListening();
  setState(STATE.IDLE);
  zhText.textContent = "已停止。再点 🎤 开始对话。";
}

async function startListening() {
  if (currentState === STATE.LISTENING || currentState === STATE.DECIDING) return;
  
  console.log("[listen] 开始监听");
  
  // 清理旧的
  await cleanupAudio();
  resetRecordingVars();
  stopSpeaking();

  // 请求麦克风
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    zhText.textContent = "当前环境不支持录音。";
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true, echoCancellation: true });
  } catch {
    zhText.textContent = "麦克风权限不可用。";
    setState(STATE.IDLE);
    return;
  }

  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) {
    zhText.textContent = "不支持音频分析。";
    stopMediaTracks(mediaStream);
    setState(STATE.IDLE);
    return;
  }

  // 设置音频分析
  recordedChunks = [];
  audioContext = new AudioCtx();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  analyserNode = audioContext.createAnalyser();
  analyserNode.fftSize = 2048;
  sourceNode.connect(analyserNode);

  // 设置 MediaRecorder
  mediaRecorder = new MediaRecorder(mediaStream);
  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      recordedChunks.push(event.data);
    }
  };
  mediaRecorder.onerror = () => {
    console.error("[recorder] 错误");
    handleListenError();
  };
  mediaRecorder.onstop = async () => {
    // MediaRecorder 停止时由 decide 逻辑触发，不在此处做 finalize
  };

  mediaRecorder.start();
  isRecording = true;
  recordingStartedAt = Date.now();
  speechStartedAt = 0;
  lastVoiceAt = 0;
  hasDetectedSpeech = false;
  lastDecideAt = 0;
  pendingTranscript = "";

  setState(STATE.LISTENING);
  zhText.textContent = "我在听。你自然说完就行。";
  jaText.textContent = "聞いているわ。自然に話しなさい。";

  // 启动 VAD + 轮次判断
  startVADLoop();
  startDecideLoop();
}

function startVADLoop() {
  if (vadInterval) clearInterval(vadInterval);
  vadInterval = setInterval(() => {
    if (currentState !== STATE.LISTENING && currentState !== STATE.DECIDING) return;
    const now = Date.now();
    const level = calculateLevel();

    if (level >= SPEECH_THRESHOLD) {
      if (!hasDetectedSpeech) {
        hasDetectedSpeech = true;
        speechStartedAt = now;
        zhText.textContent = "我在听。你停下来时我会判断。";
      }
      lastVoiceAt = now;
    }

    // 超时无语音
    if (!hasDetectedSpeech && now - recordingStartedAt >= MAX_WAIT_FOR_SPEECH_MS) {
      zhText.textContent = "没等到你开口。我先等着。";
      // 重置计时器，继续等（不关闭）
      recordingStartedAt = now;
      return;
    }

    // 录音超长
    if (now - recordingStartedAt >= MAX_RECORDING_MS) {
      zhText.textContent = "这句够长了。我来判断一下。";
      void flushDecide();
    }
  }, VAD_POLL_MS);
}

function startDecideLoop() {
  if (decideInterval) clearInterval(decideInterval);
  decideInterval = setInterval(() => {
    if (currentState !== STATE.LISTENING) return;
    const now = Date.now();
    // 只在检测到过语音且距离上次判断足够久才触发
    if (!hasDetectedSpeech) return;
    if (now - lastDecideAt < DECIDE_POLL_MS) return;

    const silenceMs = lastVoiceAt > 0 ? now - lastVoiceAt : 0;
    const speechMs = speechStartedAt > 0 ? (lastVoiceAt > 0 ? lastVoiceAt - speechStartedAt : now - speechStartedAt) : 0;

    // 语音太短，不判断
    if (speechMs < MIN_SPEECH_MS) return;

    // 静音不足 500ms，跳过
    if (silenceMs < 500) return;

    // 把当前录音送去 ASR + turn decide
    void doDecide(silenceMs, speechMs);
  }, DECIDE_POLL_MS);
}

async function doDecide(silenceMs, speechMs) {
  if (currentState !== STATE.LISTENING) return;
  if (lastDecideAt > 0 && Date.now() - lastDecideAt < 500) return; // 防抖

  lastDecideAt = Date.now();
  setState(STATE.DECIDING);
  zhText.textContent = "我在判断你是否说完了……";

  // 1. 获取当前录音 blob 并做 ASR
  let text = pendingTranscript;
  let confidence = 0.8;

  try {
    const result = await transcribeCurrentAudio();
    if (result && result.text) {
      text = result.text.trim();
      confidence = result.confidence || 0.8;
      pendingTranscript = text;
    }
  } catch (err) {
    console.warn("[decide] ASR 失败", err);
  }

  // 2. 调 turn/decide
  try {
    const res = await fetch("/api/turn/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: text || "",
        silence_ms: silenceMs,
        speech_ms: speechMs,
        asr_confidence: confidence,
        ai_speaking: false,
      }),
    });
    const decision = await res.json();
    console.log("[decide]", decision);

    // 如果状态已经被改变了（例如用户手动按停止），则退出
    if (currentState !== STATE.DECIDING) return;

    switch (decision.action) {
      case "ignore":
        // 不是有效语音，继续听
        setState(STATE.LISTENING);
        break;

      case "backchannel":
        // 用户附和，给个轻反馈继续听
        zhText.textContent = "嗯，继续。";
        lastBackchannelAt = Date.now();
        setState(STATE.LISTENING);
        break;

      case "wait_more":
        // 用户没说完，继续听
        zhText.textContent = "好，你继续说。";
        setState(STATE.LISTENING);
        break;

      case "answer_now":
        // 用户说完了，开始回答
        if (text) {
          await doAnswer(text, "voice");
        } else {
          // 没有有效文本，继续听
          setState(STATE.LISTENING);
        }
        break;

      case "interrupt":
        // 用户在 AI 说话时打断了（AI 不在说话时罕见）
        setState(STATE.LISTENING);
        break;

      default:
        setState(STATE.LISTENING);
    }
  } catch (err) {
    console.error("[decide] 请求失败", err);
    setState(STATE.LISTENING);
  }
}

async function flushDecide() {
  // 强制判断
  const now = Date.now();
  const silenceMs = lastVoiceAt > 0 ? now - lastVoiceAt : 0;
  const speechMs = speechStartedAt > 0 ? (lastVoiceAt > 0 ? lastVoiceAt - speechStartedAt : now - speechStartedAt) : 0;
  if (speechMs >= MIN_SPEECH_MS && pendingTranscript) {
    await doAnswer(pendingTranscript, "voice");
  } else {
    // 尝试 ASR
    try {
      const result = await transcribeCurrentAudio();
      if (result && result.text) {
        await doAnswer(result.text.trim(), "voice");
      }
    } catch {
      setState(STATE.LISTENING);
    }
  }
}

async function transcribeCurrentAudio() {
  // 暂停 MediaRecorder 以获取当前数据
  if (!mediaRecorder || mediaRecorder.state === "inactive") return null;
  
  // 请求当前数据
  return new Promise((resolve) => {
    const chunks = recordedChunks.slice();
    if (chunks.length === 0) {
      resolve(null);
      return;
    }
    const blob = new Blob(chunks, { type: mediaRecorder.mimeType || "audio/webm" });
    
    blobToWav(blob).then(wavBlob => {
      const formData = new FormData();
      formData.append("audio", wavBlob, "mic.wav");
      fetch("/api/asr/transcribe", {
        method: "POST",
        body: formData,
      })
        .then(r => r.json())
        .then(data => {
          if (data.text) {
            resolve({ text: data.text, confidence: data.confidence || 0.8 });
          } else {
            resolve(null);
          }
        })
        .catch(() => resolve(null));
    }).catch(() => resolve(null));
  });
}

async function stopListening() {
  if (vadInterval) {
    clearInterval(vadInterval);
    vadInterval = null;
  }
  if (decideInterval) {
    clearInterval(decideInterval);
    decideInterval = null;
  }
  isRecording = false;
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    try { mediaRecorder.stop(); } catch { /* ignore */ }
  }
  await cleanupAudio();
  resetRecordingVars();
}

function handleListenError() {
  void stopListening();
  setState(STATE.IDLE);
  zhText.textContent = "监听异常，请重试。";
}

/* ============================================================
   AI 回答
   ============================================================ */
async function doAnswer(text, source = "text") {
  if (!text) return;

  // 停止录音（进入回答阶段）
  await stopListening();
  
  setState(STATE.ANSWERING);
  zhText.textContent = "我在思考，稍等。";
  jaText.textContent = "考えているわ。少し待ちなさい。";

  // 创建 AbortController
  currentChatAbort = new AbortController();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, source }),
      signal: currentChatAbort.signal,
    });
    const data = await res.json();
    currentChatAbort = null;

    if (!res.ok) {
      jaText.textContent = "設定か通信に問題があるわ。";
      zhText.textContent = data.detail || "设置或通信出了问题。";
      setState(STATE.IDLE);
      return;
    }

    // 更新 UI
    jaText.textContent = data.ja_text;
    zhText.textContent = data.zh_subtitle;
    emotion.textContent = data.emotion;
    workMode.textContent = data.soul_state.work_mode;
    toolBox.textContent = JSON.stringify(
      {
        tool_intent: data.tool_intent,
        permission: data.permission,
        vtube: data.vtube?.connected ? "connected" : data.vtube?.reason || "not connected",
      },
      null,
      2,
    );

    // 同步播放语音和字幕
    speakWithSubtitles(data.ja_text, data.zh_subtitle, data.audio_url, () => {
      console.log("[speak] 播放完毕，自动回到监听");
      // AI 说完 → 自动回到监听
      if (currentState === STATE.ANSWERING) {
        setState(STATE.IDLE); // 先切到 IDLE 再 startListening 避免冲突
        setTimeout(() => {
          void startListening();
        }, 300);
      }
    });

    await loadMemories();
  } catch (err) {
    if (err.name === "AbortError") {
      console.log("[chat] 请求被用户打断");
      return;
    }
    console.error("[chat] 失败", err);
    jaText.textContent = "……応答の生成に失敗したわ。";
    zhText.textContent = "回复生成失败。再说一次？";
    setState(STATE.IDLE);
  }
}

/* ============================================================
   WAV 转换
   ============================================================ */
function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let i = 0; i < value.length; i++) {
      view.setUint8(offset + i, value.charCodeAt(i));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

async function blobToWav(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) throw new Error("AudioContext unavailable");
  const decodeContext = new AudioCtx();
  try {
    const audioBuffer = await decodeContext.decodeAudioData(arrayBuffer.slice(0));
    const samples = audioBuffer.getChannelData(0);
    return encodeWav(samples, audioBuffer.sampleRate);
  } finally {
    await decodeContext.close();
  }
}

/* ============================================================
   文本聊天模式
   ============================================================ */
async function sendMessageText(text, source = "text") {
  if (currentState !== STATE.IDLE) {
    // 如果正在对话中，先取消
    await cancelAll();
  }
  await doAnswer(text, source);
}

/* ============================================================
   其他功能 (不变)
   ============================================================ */
async function refreshHealth() {
  const res = await fetch("/api/health");
  const data = await res.json();
  const hasKey = data.secret.has_env_key || data.secret.has_saved_key;
  const voice = data.voice || {};
  const asr = data.asr || {};
  health.textContent = `Key: ${hasKey ? "已配置" : "未配置"} · ${data.mode || "server"} · ${data.model} · voice: ${voice.provider || "browser"} · asr: ${asr.provider || "browser"}`;
}

async function saveApiKey() {
  const key = apiKey.value.trim();
  if (!key) return;
  const res = await fetch("/api/config/deepseek-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: key }),
  });
  if (!res.ok) {
    const data = await res.json();
    health.textContent = `保存失败: ${data.detail || res.statusText}`;
    return;
  }
  apiKey.value = "";
  await refreshHealth();
}

async function searchPapers(query) {
  paperList.textContent = "正在搜索 arXiv...";
  const res = await fetch("/api/research/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_results: 8 }),
  });
  const data = await res.json();
  if (!res.ok) {
    paperList.textContent = data.detail || "论文搜索失败。";
    return;
  }
  paperList.innerHTML = "";
  for (const paper of data.papers) {
    const item = document.createElement("article");
    item.className = "list-item";
    const title = document.createElement("a");
    title.href = paper.url;
    title.target = "_blank";
    title.rel = "noreferrer";
    title.textContent = paper.title;
    const meta = document.createElement("p");
    meta.textContent = `${paper.published.slice(0, 10)} · ${paper.authors.slice(0, 3).join(", ")}`;
    const summary = document.createElement("p");
    summary.textContent = paper.summary.slice(0, 360);
    item.append(title, meta, summary);
    paperList.append(item);
  }
}

async function loadMemories() {
  const res = await fetch("/api/memories?limit=20");
  const data = await res.json();
  memoryList.innerHTML = "";
  for (const memory of data) {
    const item = document.createElement("article");
    item.className = "list-item memory-item";
    const content = document.createElement("p");
    content.textContent = `[${memory.kind}] ${memory.content}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "删除";
    remove.addEventListener("click", () => deleteMemory(memory.id));
    item.append(content, remove);
    memoryList.append(item);
  }
}

async function addMemory() {
  const content = memoryContent.value.trim();
  if (!content) return;
  await fetch("/api/memories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: memoryKind.value.trim() || "manual", content, source: "ui" }),
  });
  memoryContent.value = "";
  await loadMemories();
}

async function deleteMemory(id) {
  await fetch(`/api/memories/${id}`, { method: "DELETE" });
  await loadMemories();
}

async function fetchDivergence() {
  divergenceResult.textContent = "正在读取 divergence...";
  const res = await fetch("/api/tools/divergence");
  const data = await res.json();
  if (!res.ok) {
    divergenceResult.textContent = data.detail || "Divergence 读取失败。";
    return;
  }
  divergenceResult.textContent = JSON.stringify(data, null, 2);
}

async function fetchDivergenceNews() {
  divergenceResult.textContent = "正在读取 divergence news...";
  const res = await fetch("/api/tools/divergence/news", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ page: 1, per_page: 5, min_impact: 0.1 }),
  });
  const data = await res.json();
  if (!res.ok) {
    divergenceResult.textContent = data.detail || "Divergence news 读取失败。";
    return;
  }
  divergenceResult.textContent = JSON.stringify(data, null, 2);
}

async function inspectCommandRisk() {
  const command = commandText.value.trim();
  if (!command) return;
  const res = await fetch("/api/tools/inspect-command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  const data = await res.json();
  commandResult.textContent = JSON.stringify(data, null, 2);
}

/* ============================================================
   事件绑定
   ============================================================ */
form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = userText.value.trim();
  if (!text) return;
  userText.value = "";
  void sendMessageText(text);
});

researchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = researchQuery.value.trim();
  if (query) searchPapers(query);
});

memoryForm.addEventListener("submit", (event) => {
  event.preventDefault();
  addMemory();
});

saveKey.addEventListener("click", saveApiKey);
micButton.addEventListener("click", () => { void toggleRecording(); });
refreshButton.addEventListener("click", async () => {
  await refreshHealth();
  await loadMemories();
});
inspectCommand.addEventListener("click", inspectCommandRisk);
loadDivergence.addEventListener("click", fetchDivergence);
loadDivergenceNews.addEventListener("click", fetchDivergenceNews);

// 初始化
refreshHealth();
loadMemories();
setState(STATE.IDLE);