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
const VAD_POLL_MS = 120;
const SPEECH_THRESHOLD = 0.022;
const SILENCE_HOLD_MS = 1450;
const MAX_WAIT_FOR_SPEECH_MS = 7000;
const MAX_RECORDING_MS = 18000;
const MIN_SPEECH_MS = 500;
const DIALOGUE_LOCK_MS = 90000;

let stateIndex = 0;
let lastCheckinAt = 0;
let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let isRecording = false;
let isSpeaking = false;
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

function stopCurrentAudio() {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }
}

function speakJapanese(jaText, zhText, audioUrl = null) {
  if (isRecording) {
    void stopRecording("cancel", false);
  }
  clearAutoListenTimer();
  stopCurrentAudio();
  clearSubtitleTimer();
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
      finishSpeech();
    };
    audio.onerror = () => {
      currentAudio = null;
      speakJapanese(jaText, zhText, null);
    };
    audio.play().catch(() => {
      currentAudio = null;
      speakJapanese(jaText, zhText, null);
    });
    return;
  }

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
    finishSpeech();
  };
  utterance.onerror = () => {
    zhLine.textContent = zhText;
    finishSpeech();
  };
  window.speechSynthesis.speak(utterance);
}

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

async function sendMessage(text, source = "text") {
  if (!window.companionDesktop?.chat) return;
  clearAutoListenTimer();
  setState("thinking");
  statusLine.textContent = "sending";
  setDialogue("考えているわ。少し待ちなさい。", "我在思考，稍等。", { lockMs: 20000, live: true });

  const result = await window.companionDesktop.chat({ text, source });
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
  speakJapanese(data.ja_text, data.zh_subtitle, data.audio_url || null);
}

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

async function finishRecording(blob, allowRestart = true) {
  statusLine.textContent = "transcribing";
  setDialogue("……聞き取りを整理しているわ。", "我判断你这句话结束了，正在转写。", { lockMs: 20000, live: true });
  setState("thinking");

  try {
    const result = await transcribeAudio(blob);
    const text = (result.text || "").trim();
    petInput.value = text;
    statusLine.textContent = `asr ${result.engine || "ready"}`;
    if (!text) {
      setDialogue("うまく拾えなかったわ。", "这句我没有听清。再自然说一次。", { lockMs: 18000 });
      setState("annoyed");
      if (allowRestart) scheduleAutoListen(800);
      return;
    }
    await sendMessage(text, "voice");
  } catch (error) {
    statusLine.textContent = "asr failed";
    setDialogue("音声経路に問題があるわ。", `语音转写失败：${error?.message || "unknown"}。先用文字输入。`, { lockMs: 22000 });
    setState("annoyed");
    if (allowRestart) scheduleAutoListen(1400);
  }
}

function startVoiceMonitor() {
  vadInterval = setInterval(() => {
    if (!isRecording) return;
    const now = Date.now();
    const level = calculateLevel();

    if (level >= SPEECH_THRESHOLD) {
      if (!hasDetectedSpeech) {
        hasDetectedSpeech = true;
        speechStartedAt = now;
        setDialogue("話し続けなさい。", "我在听。你停下来时我会自己回答。", { lockMs: 15000, live: true });
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
    const blob = new Blob(recordedChunks, { type: recorder?.mimeType || "audio/webm" });
    recordedChunks = [];
    stopMediaTracks();
    mediaRecorder = null;
    if (stopMode === "finalize") {
      await finishRecording(blob, allowRestart);
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

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = petInput.value.trim();
  if (!text) return;
  petInput.value = "";
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
