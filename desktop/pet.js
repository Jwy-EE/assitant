const pet = document.getElementById("pet");
const dialogueBox = document.getElementById("dialogueBox");
const statusLine = document.getElementById("status");
const modeTag = document.getElementById("modeTag");
const jaLine = document.getElementById("jaLine");
const zhLine = document.getElementById("zhLine");
const composer = document.getElementById("petComposer");
const petInput = document.getElementById("petInput");
const micButton = document.getElementById("micButton");
const openWorkbench = document.getElementById("openWorkbench");

const states = ["idle", "thinking", "proud", "annoyed"];

// ── VAD 参数 ──
const VAD_POLL_MS = 120;
const SPEECH_THRESHOLD = 0.022;
const SILENCE_HOLD_MS = 2300;
const MAX_WAIT_FOR_SPEECH_MS = 7000;
const MAX_RECORDING_MS = 25000;
const MIN_SPEECH_MS = 900;
const DIALOGUE_LOCK_MS = 90000;

// ── TurnManager 参数 ──
// AI 说话时仍保持低功耗监听，用于打断检测
const INTERRUPT_VAD_MS = 300;
const INTERRUPT_SPEECH_MS = 800; // 用户说超过 800ms 视为打断意图

// ── 状态变量 ──
let stateIndex = 0;
let lastCheckinAt = 0;
let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let isRecording = false;
let isSpeaking = false;
let isChatting = false;          // 防止重复发送
let audioContext = null;
let analyserNode = null;
let sourceNode = null;
let vadInterval = null;
let recordingStartedAt = 0;
let speechStartedAt = 0;
let lastVoiceAt = 0;
let hasDetectedSpeech = false;
let autoListenEnabled = true;
let autoListenTimer = null;
let subtitleTimer = null;
let currentAudio = null;
let dialogueLockUntil = 0;
let lastConversationAt = 0;
let initializedPrompt = false;

// TurnManager 状态
let pendingTranscript = "";       // 等待中的部分识别文本
let currentSilenceMs = 0;        // 当前静音时长
let currentSpeechMs = 0;         // 当前说话时长

// TTS 队列（sentence-level playback）
let ttsQueue = [];
let isPlayingTTS = false;

// ── 辅助函数 ──
function setState(nextState) {
  pet.classList.remove("idle", "thinking", "speaking", "proud", "annoyed");
  pet.classList.add(nextState);
  modeTag.textContent = nextState;
}

function setMicVisual() {
  micButton.textContent = autoListenEnabled ? "AUTO" : "MUTE";
  micButton.classList.toggle("active", autoListenEnabled);
  micButton.title = autoListenEnabled ? "Auto listening enabled" : "Auto listening disabled";
}

function clearSubtitleTimer() {
  if (!subtitleTimer) return;
  clearInterval(subtitleTimer);
  subtitleTimer = null;
}

function setDialogue(jaText, zhText, { lockMs = DIALOGUE_LOCK_MS, live = false } = {}) {
  clearSubtitleTimer();
  jaLine.textContent = jaText;
  zhLine.textContent = zhText;
  dialogueLockUntil = Date.now() + lockMs;
  lastConversationAt = Date.now();
  dialogueBox.classList.toggle("live", live);
}

function animateSubtitle(jaText, zhText, durationMs) {
  clearSubtitleTimer();
  jaLine.textContent = jaText;
  zhLine.textContent = "";
  dialogueBox.classList.add("live");
  dialogueLockUntil = Date.now() + DIALOGUE_LOCK_MS;
  lastConversationAt = Date.now();

  const totalChars = Math.max(zhText.length, 1);
  const startedAt = Date.now();
  subtitleTimer = setInterval(() => {
    const elapsed = Date.now() - startedAt;
    const progress = Math.min(elapsed / Math.max(durationMs, 800), 1);
    const visibleChars = Math.max(1, Math.floor(totalChars * progress));
    zhLine.textContent = zhText.slice(0, visibleChars);
    if (progress >= 1) {
      clearSubtitleTimer();
      zhLine.textContent = zhText;
    }
  }, 40);
}

function canReplaceDialogue() {
  return Date.now() >= dialogueLockUntil && !isRecording && !isSpeaking;
}

function estimateSpeechDurationMs(jaText, zhText) {
  const textWeight = Math.max(jaText.length * 145, zhText.length * 115);
  return Math.min(Math.max(textWeight, 1800), 14000);
}

function scheduleAutoListen(delayMs = 450) {
  if (autoListenTimer) {
    clearTimeout(autoListenTimer);
    autoListenTimer = null;
  }
  if (!autoListenEnabled || isRecording || isSpeaking) return;
  autoListenTimer = setTimeout(() => {
    autoListenTimer = null;
    if (!autoListenEnabled || isRecording || isSpeaking) return;
    void beginListening("auto");
  }, delayMs);
}

function clearAutoListenTimer() {
  if (!autoListenTimer) return;
  clearTimeout(autoListenTimer);
  autoListenTimer = null;
}

function finishSpeech() {
  isSpeaking = false;
  dialogueBox.classList.remove("live");
  if (!isRecording) {
    setState("idle");
  }
  scheduleAutoListen(650);
}

// ── TTS 队列管理（sentence-level playback）──
function enqueueTTS(jaText, zhText, audioUrl) {
  ttsQueue.push({ jaText, zhText, audioUrl });
  if (!isPlayingTTS) {
    playNextTTS();
  }
}

function clearTTSQueue() {
  ttsQueue.length = 0;
  isPlayingTTS = false;
}

function playNextTTS() {
  if (ttsQueue.length === 0) {
    isPlayingTTS = false;
    return;
  }
  isPlayingTTS = true;
  const item = ttsQueue.shift();
  speakOneSentence(item.jaText, item.zhText, item.audioUrl);
}

// ── 打断检测：从 speakJapanese 独立出来 ──
function stopCurrentAudio() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  clearTTSQueue();
}

function speakJapanese(jaText, zhText, audioUrl = null) {
  // 如果正在录音，先停止
  if (isRecording) {
    void stopRecording("cancel", false);
  }
  clearAutoListenTimer();
  stopCurrentAudio();
  clearSubtitleTimer();

  // 单句播放入队列
  enqueueTTS(jaText, zhText, audioUrl);
}

function speakOneSentence(jaText, zhText, audioUrl) {
  if (isRecording) return;
  isSpeaking = true;
  setState("speaking");

  if (audioUrl) {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    const audio = new Audio(audioUrl);
    currentAudio = audio;
    audio.onloadedmetadata = () => {
      const durationMs = Number.isFinite(audio.duration) ? audio.duration * 1000 : estimateSpeechDurationMs(jaText, zhText);
      animateSubtitle(jaText, zhText, durationMs);
    };
    audio.onplay = () => {
      if (!subtitleTimer) {
        animateSubtitle(jaText, zhText, estimateSpeechDurationMs(jaText, zhText));
      }
    };
    audio.onended = () => {
      currentAudio = null;
      zhLine.textContent = zhText;
      // 播完当前句，继续下一句
      if (ttsQueue.length > 0) {
        playNextTTS();
      } else {
        finishSpeech();
        // 播放结束后开启打断监听（低功耗）
        scheduleAutoListen(500);
      }
    };
    audio.onerror = () => {
      currentAudio = null;
      finishSpeech();
      scheduleAutoListen(800);
    };
    audio.play().catch(() => {
      currentAudio = null;
      finishSpeech();
      scheduleAutoListen(800);
    });
    return;
  }

  // 无 audioUrl：浏览器 TTS fallback
  if (!("speechSynthesis" in window)) {
    setDialogue(jaText, zhText, { live: false });
    finishSpeech();
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(jaText);
  utterance.lang = "ja-JP";
  utterance.rate = 0.96;
  utterance.pitch = 0.92;
  utterance.onstart = () => {
    animateSubtitle(jaText, zhText, estimateSpeechDurationMs(jaText, zhText));
  };
  utterance.onend = () => {
    zhLine.textContent = zhText;
    if (ttsQueue.length > 0) {
      playNextTTS();
    } else {
      finishSpeech();
      scheduleAutoListen(500);
    }
  };
  utterance.onerror = () => {
    zhLine.textContent = zhText;
    finishSpeech();
    scheduleAutoListen(800);
  };
  window.speechSynthesis.speak(utterance);
}

// ── 中断 AI 说话（用户打断） ──
function interruptAISpeaking(reason = "user_interrupt") {
  if (!isSpeaking) return;
  stopCurrentAudio();
  isSpeaking = false;
  setState("idle");
  setDialogue("止まったわ。続けて言いなさい。", "我停下了，你继续说吧。", { lockMs: 12000 });
  // 立即重新开始监听
  scheduleAutoListen(300);
}

// ── TurnManager: 决定是否回答 ──
async function decideTurn(text, silenceMs, speechMs, asrConfidence) {
  try {
    const response = await fetch("/api/turn/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript: text,
        silence_ms: silenceMs,
        speech_ms: speechMs,
        asr_confidence: asrConfidence,
        state: isSpeaking ? "AI_SPEAKING" : "LISTENING",
        ai_speaking: isSpeaking,
      }),
    });
    if (!response.ok) throw new Error(`turn decide status ${response.status}`);
    return await response.json();
  } catch (error) {
    console.error("turn decide failed:", error);
    // 如果后端挂了，默认回答
    return { action: "answer_now", confidence: 0.5, reason: "fallback after turn error" };
  }
}

// ── 健康检查 ──
async function refreshHealth() {
  if (!window.companionDesktop) {
    statusLine.textContent = "desktop bridge missing";
    return;
  }

  const result = await window.companionDesktop.health();
  if (!result.ok) {
    statusLine.textContent = `backend offline: ${result.reason}`;
    if (canReplaceDialogue()) {
      setDialogue("バックエンドが起動していないわ。", "后端还没有启动。", { lockMs: 12000 });
    }
    setState("annoyed");
    return;
  }

  const secret = result.data.secret || {};
  const voice = result.data.voice || {};
  const asr = result.data.asr || {};
  const hasKey = Boolean(secret.has_env_key || secret.has_saved_key);
  statusLine.textContent = `${result.data.model} / voice ${voice.provider || "browser"} / asr ${asr.provider || "browser"}`;

  if (!initializedPrompt && hasKey) {
    setDialogue("ここで直接話しなさい。", "已经进入常驻聆听。你正常说话，我会自己判断什么时候该回应。", { lockMs: 25000 });
    initializedPrompt = true;
  } else if (!initializedPrompt && !hasKey) {
    setDialogue("DeepSeek key を設定しなさい。", "请先在工作台设置 DeepSeek key。", { lockMs: 25000 });
    initializedPrompt = true;
  }

  if (!isRecording && !isSpeaking) {
    setState(hasKey ? "idle" : "thinking");
  }
  if (hasKey) {
    await refreshCheckin();
    scheduleAutoListen(900);
  }
}

async function refreshCheckin() {
  if (!window.companionDesktop?.checkin) return;
  const now = Date.now();
  if (now - lastCheckinAt < 55000) return;
  if (now - lastConversationAt < 60000 || isRecording || isSpeaking) return;
  lastCheckinAt = now;

  const result = await window.companionDesktop.checkin();
  if (!result.ok || !result.data?.should_prompt) return;
  setDialogue(result.data.ja_text, result.data.zh_subtitle, { lockMs: 45000 });
  const nextState = result.data.emotion === "concerned_soft" ? "thinking" : result.data.emotion;
  setState(states.includes(nextState) ? nextState : "thinking");
}

// ── 发送消息 ──
async function sendMessage(text, source = "text") {
  if (!window.companionDesktop?.chat) return;
  if (isChatting) return; // 防止重复发送
  isChatting = true;
  const chatT0 = performance.now();
  clearAutoListenTimer();
  setState("thinking");
  statusLine.textContent = "sending";
  setDialogue("考えているわ。少し待ちなさい。", "我在思考，稍等。", { lockMs: 20000, live: true });

  try {
    const result = await window.companionDesktop.chat({ text, source });
    console.log("[chat latency]", { chat_total_ms: Math.round(performance.now() - chatT0), text_len: text.length, ok: result.ok });

    if (!result.ok) {
      setState("annoyed");
      statusLine.textContent = result.reason || `request failed (${result.status || "?"})`;
      setDialogue("設定か通信に問題があるわ。", result.data?.detail || "设置或通信出了问题。", { lockMs: 25000 });
      scheduleAutoListen(1200);
      return;
    }

    const data = result.data;
    statusLine.textContent = `${data.emotion} / ${data.voice?.engine || "browser"}`;
    setState(data.emotion === "focused" ? "thinking" : data.emotion);

    // 先显示字幕，不等 TTS
    setDialogue(data.ja_text, data.zh_subtitle, { lockMs: 45000 });
    console.log("[chat timing]", { subtitle_shown_ms: Math.round(performance.now() - chatT0) });

    // TTS 播放：如果后端返回了 audio_url 就用，否则浏览器 TTS 兜底
    const audioUrl = data.audio_url || null;
    if (audioUrl) {
      // 后端提供的完整音频
      speakJapanese(data.ja_text, data.zh_subtitle, audioUrl);
    } else {
      // TTS 失败或没返回，用浏览器 SSML 兜底
      speakJapanese(data.ja_text, data.zh_subtitle, null);
    }
  } finally {
    isChatting = false;
  }
}

// ── 音频处理 ──
function stopMediaTracks() {
  if (!mediaStream) return;
  for (const track of mediaStream.getTracks()) {
    track.stop();
  }
  mediaStream = null;
}

async function cleanupAudioMonitoring() {
  if (vadInterval) {
    clearInterval(vadInterval);
    vadInterval = null;
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
    try {
      await audioContext.close();
    } catch {
      // ignore close failures
    }
    audioContext = null;
  }
}

function resetRecordingFlags() {
  isRecording = false;
  recordingStartedAt = 0;
  speechStartedAt = 0;
  lastVoiceAt = 0;
  hasDetectedSpeech = false;
}

function calculateLevel() {
  if (!analyserNode) return 0;
  const data = new Uint8Array(analyserNode.fftSize);
  analyserNode.getByteTimeDomainData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i += 1) {
    const centered = (data[i] - 128) / 128;
    sum += centered * centered;
  }
  return Math.sqrt(sum / data.length);
}

async function stopRecording(mode = "finalize", allowRestart = true) {
  if (!mediaRecorder) return;
  const recorder = mediaRecorder;
  recorder.__stopMode = mode;
  recorder.__allowRestart = allowRestart;
  // ── 在 reset 前保存真实 timing ──
  const now = Date.now();
  recorder.__silenceMs = hasDetectedSpeech && lastVoiceAt ? now - lastVoiceAt : 0;
  recorder.__speechMs = hasDetectedSpeech && speechStartedAt && lastVoiceAt
    ? Math.max(0, lastVoiceAt - speechStartedAt)
    : 0;
  await cleanupAudioMonitoring();
  resetRecordingFlags();
  statusLine.textContent = mode === "cancel" ? "idle" : "transcribing";
  if (recorder.state !== "inactive") {
    recorder.stop();
  }
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let i = 0; i < value.length; i += 1) {
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
  for (let i = 0; i < samples.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: "audio/wav" });
}

async function blobToWav(blob) {
  const arrayBuffer = await blob.arrayBuffer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    throw new Error("AudioContext unavailable");
  }

  const decodeContext = new AudioContextClass();
  try {
    const audioBuffer = await decodeContext.decodeAudioData(arrayBuffer.slice(0));
    const samples = audioBuffer.getChannelData(0);
    return encodeWav(samples, audioBuffer.sampleRate);
  } finally {
    await decodeContext.close();
  }
}

async function transcribeAudio(blob) {
  const wavBlob = await blobToWav(blob);
  const formData = new FormData();
  formData.append("audio", wavBlob, "mic.wav");
  const response = await fetch("/api/asr/transcribe", {
    method: "POST",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || `ASR failed (${response.status})`);
  }
  return data;
}

// ── TurnManager: 核心改动 ──
async function finishRecording(blob, allowRestart = true, silenceMs = 0, speechMs = 0) {
  statusLine.textContent = "transcribing";
  setState("thinking");

  try {
    const t0 = performance.now();
    const result = await transcribeAudio(blob);
    const t1 = performance.now();
    const text = (result.text || "").trim();
    petInput.value = text;
    currentSilenceMs = silenceMs;
    currentSpeechMs = speechMs;

    console.log("[voice latency]", {
      asr_ms: Math.round(t1 - t0),
      text: text.slice(0, 50) || "(empty)",
      silence_ms: currentSilenceMs,
      speech_ms: currentSpeechMs,
    });

    statusLine.textContent = `asr ${result.engine || "ready"}`;
    if (!text) {
      setDialogue("うまく拾えなかったわ。", "这句我没有听清。再自然说一次。", { lockMs: 8000 });
      setState("annoyed");
      if (allowRestart) scheduleAutoListen(1200);
      return;
    }

    // ── 调用 TurnManager 决定是否回答 ──
    const decision = await decideTurn(text, currentSilenceMs, currentSpeechMs, result.confidence ?? 0.8);

    switch (decision.action) {
      case "interrupt":
        // 打断 AI
        if (isSpeaking) {
          interruptAISpeaking("turn_interrupt");
        }
        pendingTranscript = text;
        if (allowRestart) scheduleAutoListen(600);
        break;

      case "wait_more":
        // 用户还没说完，追加识别文本，继续听
        pendingTranscript = pendingTranscript ? pendingTranscript + " " + text : text;
        setDialogue("まだ続くんでしょ？聞いてるわ。", `你继续说，我听着。已有: "${pendingTranscript.slice(-30)}"`, {
          lockMs: 10000,
          live: true,
        });
        if (allowRestart) scheduleAutoListen(500);
        break;

      case "backchannel":
        // 用户只是附和，不回答
        setDialogue("うん。", "嗯。", { lockMs: 4000 });
        if (allowRestart) scheduleAutoListen(600);
        break;

      case "answer_now":
      default:
        // 用户说完了，结合 pendingTranscript 一起发送
        const fullText = pendingTranscript ? pendingTranscript + " " + text : text;
        pendingTranscript = "";
        console.log("[voice latency]", { chat_send_ms: Math.round(performance.now() - t1) });
        await sendMessage(fullText, "voice");
        break;
    }
  } catch (error) {
    statusLine.textContent = "asr failed";
    setDialogue("音声経路に問題があるわ。", `语音转写失败：${error?.message || "unknown"}。先用文字输入。`, {
      lockMs: 22000,
    });
    setState("annoyed");
    if (allowRestart) scheduleAutoListen(1400);
  }
}

// ── VAD 监听 ──
function startVoiceMonitor() {
  vadInterval = setInterval(() => {
    if (!isRecording) return;
    const now = Date.now();
    const level = calculateLevel();

    if (level >= SPEECH_THRESHOLD) {
      if (!hasDetectedSpeech) {
        hasDetectedSpeech = true;
        speechStartedAt = now;
        setDialogue("話し続けなさい。", "我在听。", { lockMs: 15000, live: true });
      }
      lastVoiceAt = now;
      statusLine.textContent = `listening ${level.toFixed(3)}`;
    }

    if (!hasDetectedSpeech && now - recordingStartedAt >= MAX_WAIT_FOR_SPEECH_MS) {
      setDialogue("まだ聞こえないわ。", "我没等到你开口，这次先继续待机。", { lockMs: 12000 });
      void stopRecording("cancel", true);
      return;
    }

    if (hasDetectedSpeech) {
      const speechDuration = lastVoiceAt - speechStartedAt;
      const silenceDuration = now - lastVoiceAt;
      if (speechDuration >= MIN_SPEECH_MS && silenceDuration >= SILENCE_HOLD_MS) {
        void stopRecording("finalize", true);
        return;
      }
    }

    if (now - recordingStartedAt >= MAX_RECORDING_MS) {
      setDialogue("この区切りで十分よ。", "这句话已经够长了，我先按当前内容回答。", { lockMs: 15000 });
      void stopRecording(hasDetectedSpeech ? "finalize" : "cancel", true);
    }
  }, VAD_POLL_MS);
}

// ── 开始录音 ──
async function beginListening(trigger = "manual") {
  if (isRecording || isSpeaking || !autoListenEnabled) return;

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    setDialogue("音声入力は無理ね。", "当前环境不支持录音。先用文字输入。", { lockMs: 20000 });
    statusLine.textContent = "recording unsupported";
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    setDialogue("マイク権限を確認しなさい。", "麦克风权限不可用。请检查系统麦克风权限。", { lockMs: 20000 });
    statusLine.textContent = error?.message || "microphone permission denied";
    return;
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    setDialogue("音声解析が使えないわ。", "当前环境不支持音频分析。先用文字输入。", { lockMs: 20000 });
    stopMediaTracks();
    return;
  }

  recordedChunks = [];
  audioContext = new AudioContextClass();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  analyserNode = audioContext.createAnalyser();
  analyserNode.fftSize = 2048;
  sourceNode.connect(analyserNode);

  mediaRecorder = new MediaRecorder(mediaStream);
  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) {
      recordedChunks.push(event.data);
    }
  };
  mediaRecorder.onerror = async () => {
    await cleanupAudioMonitoring();
    stopMediaTracks();
    mediaRecorder = null;
    resetRecordingFlags();
    statusLine.textContent = "recording failed";
    setDialogue("録音に失敗したわ。", "录音失败。先用文字输入。", { lockMs: 20000 });
    setState("annoyed");
  };
  mediaRecorder.onstop = async () => {
    const recorder = mediaRecorder;
    const stopMode = recorder?.__stopMode || "finalize";
    const allowRestart = recorder?.__allowRestart !== false;
    const silenceMs = recorder?.__silenceMs || 0;
    const speechMs = recorder?.__speechMs || 0;
    const blob = new Blob(recordedChunks, { type: recorder?.mimeType || "audio/webm" });
    recordedChunks = [];
    stopMediaTracks();
    mediaRecorder = null;
    if (stopMode === "finalize") {
      await finishRecording(blob, allowRestart, silenceMs, speechMs);
    } else if (allowRestart) {
      scheduleAutoListen(750);
    }
  };

  mediaRecorder.start();
  isRecording = true;
  recordingStartedAt = Date.now();
  speechStartedAt = 0;
  lastVoiceAt = 0;
  hasDetectedSpeech = false;
  statusLine.textContent = trigger === "auto" ? "auto listening" : "listening";
  setDialogue("話しなさい。", "我在待机听你说话。正常开口就行，不用再按按钮。", { lockMs: 18000, live: true });
  setState("thinking");
  startVoiceMonitor();
}

// ── 切换自动监听 ──
async function toggleAutoListen() {
  autoListenEnabled = !autoListenEnabled;
  setMicVisual();
  if (!autoListenEnabled) {
    clearAutoListenTimer();
    if (isRecording) {
      await stopRecording("cancel", false);
    }
    setDialogue("待機音声は止めたわ。", "常驻监听已关闭。你还可以直接打字。", { lockMs: 15000 });
    statusLine.textContent = "auto listen off";
    return;
  }

  setDialogue("常時待機に戻すわ。", "常驻监听已开启。之后你直接说话就行。", { lockMs: 15000 });
  statusLine.textContent = "auto listen on";
  scheduleAutoListen(500);
}

// ── 事件绑定 ──
composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = petInput.value.trim();
  if (!text) return;
  petInput.value = "";
  pendingTranscript = ""; // 清空等待文本
  sendMessage(text);
});

micButton.addEventListener("click", () => {
  void toggleAutoListen();
});
openWorkbench.addEventListener("click", async () => {
  await window.companionDesktop.openWorkbench();
});

setInterval(() => {
  if (pet.classList.contains("speaking") || pet.classList.contains("thinking")) return;
  stateIndex = (stateIndex + 1) % states.length;
  setState(states[stateIndex]);
}, 9000);

setMicVisual();
refreshHealth();
setInterval(refreshHealth, 15000);