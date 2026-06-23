const form = document.getElementById("chatForm");
const userText = document.getElementById("userText");
const jaText = document.getElementById("jaText");
const zhText = document.getElementById("zhText");
const toolBox = document.getElementById("toolBox");
const emotion = document.getElementById("emotion");
const workMode = document.getElementById("workMode");
const avatar = document.getElementById("avatar");
const saveKey = document.getElementById("saveKey");
const apiKey = document.getElementById("apiKey");
const health = document.getElementById("health");
const micButton = document.getElementById("micButton");
const refreshButton = document.getElementById("refreshButton");
const researchForm = document.getElementById("researchForm");
const researchQuery = document.getElementById("researchQuery");
const paperList = document.getElementById("paperList");
const memoryForm = document.getElementById("memoryForm");
const memoryKind = document.getElementById("memoryKind");
const memoryContent = document.getElementById("memoryContent");
const memoryList = document.getElementById("memoryList");
const commandText = document.getElementById("commandText");
const inspectCommand = document.getElementById("inspectCommand");
const commandResult = document.getElementById("commandResult");
const loadDivergence = document.getElementById("loadDivergence");
const loadDivergenceNews = document.getElementById("loadDivergenceNews");
const divergenceResult = document.getElementById("divergenceResult");

const VAD_POLL_MS = 120;
const SPEECH_THRESHOLD = 0.022;
const SILENCE_HOLD_MS = 1400;
const MAX_WAIT_FOR_SPEECH_MS = 6000;
const MAX_RECORDING_MS = 18000;
const MIN_SPEECH_MS = 500;

let mediaRecorder = null;
let mediaStream = null;
let recordedChunks = [];
let isRecording = false;
let audioContext = null;
let analyserNode = null;
let sourceNode = null;
let vadInterval = null;
let recordingStartedAt = 0;
let speechStartedAt = 0;
let lastVoiceAt = 0;
let hasDetectedSpeech = false;

async function refreshHealth() {
  const res = await fetch("/api/health");
  const data = await res.json();
  const hasKey = data.secret.has_env_key || data.secret.has_saved_key;
  const voice = data.voice || {};
  const asr = data.asr || {};
  health.textContent = `DeepSeek key: ${hasKey ? "已配置" : "未配置"} · ${data.mode || "server"} · ${data.model} · voice: ${voice.provider || "browser"} · asr: ${asr.provider || "browser"}`;
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

async function sendMessage(text, source = "text") {
  jaText.textContent = "考えているわ。少し待ちなさい。";
  zhText.textContent = "我在思考，稍等。";
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, source }),
  });
  const data = await res.json();
  if (!res.ok) {
    jaText.textContent = "設定か通信に問題があるわ。";
    zhText.textContent = data.detail || "设置或通信出了问题。";
    return;
  }
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
  speakJapanese(data.ja_text, data.audio_url);
  await loadMemories();
}

function speakJapanese(text, audioUrl = null) {
  if (audioUrl) {
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    const audio = new Audio(audioUrl);
    audio.onplay = () => avatar.classList.add("speaking");
    audio.onended = () => avatar.classList.remove("speaking");
    audio.onerror = () => {
      avatar.classList.remove("speaking");
      speakJapanese(text, null);
    };
    audio.play().catch(() => speakJapanese(text, null));
    return;
  }

  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "ja-JP";
  utterance.rate = 0.96;
  utterance.pitch = 0.92;
  utterance.onstart = () => avatar.classList.add("speaking");
  utterance.onend = () => avatar.classList.remove("speaking");
  utterance.onerror = () => avatar.classList.remove("speaking");
  window.speechSynthesis.speak(utterance);
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

async function stopRecording(mode = "finalize") {
  if (!mediaRecorder) return;
  const recorder = mediaRecorder;
  recorder.__stopMode = mode;
  await cleanupAudioMonitoring();
  resetRecordingFlags();
  micButton.textContent = "Mic";
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

async function finishRecording(blob) {
  zhText.textContent = "我判断你这句话结束了，正在转写。";
  try {
    const result = await transcribeAudio(blob);
    const text = (result.text || "").trim();
    userText.value = text;
    if (!text) {
      zhText.textContent = "这句我没有听清。再自然说一次。";
      return;
    }
    await sendMessage(text, "voice");
  } catch (error) {
    zhText.textContent = `语音转写失败：${error?.message || "unknown"}。先用文字输入。`;
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
        zhText.textContent = "我在听。你停下来时我会自己回答。";
      }
      lastVoiceAt = now;
    }

    if (!hasDetectedSpeech && now - recordingStartedAt >= MAX_WAIT_FOR_SPEECH_MS) {
      zhText.textContent = "我没等到你开口。这次先取消。";
      void stopRecording("cancel");
      return;
    }

    if (hasDetectedSpeech) {
      const speechDuration = lastVoiceAt - speechStartedAt;
      const silenceDuration = now - lastVoiceAt;
      if (speechDuration >= MIN_SPEECH_MS && silenceDuration >= SILENCE_HOLD_MS) {
        void stopRecording("finalize");
        return;
      }
    }

    if (now - recordingStartedAt >= MAX_RECORDING_MS) {
      zhText.textContent = "这句已经够长了。我先按当前内容回答。";
      void stopRecording(hasDetectedSpeech ? "finalize" : "cancel");
    }
  }, VAD_POLL_MS);
}

async function toggleRecording() {
  if (isRecording) {
    zhText.textContent = "这次监听已取消。";
    await stopRecording("cancel");
    return;
  }

  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    zhText.textContent = "当前环境不支持录音。先用文字输入。";
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    zhText.textContent = "麦克风权限不可用。请检查系统麦克风权限。";
    return;
  }

  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) {
    zhText.textContent = "当前环境不支持音频分析。先用文字输入。";
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
    micButton.textContent = "Mic";
    zhText.textContent = "录音失败。先用文字输入。";
  };
  mediaRecorder.onstop = async () => {
    const stopMode = mediaRecorder?.__stopMode || "finalize";
    const blob = new Blob(recordedChunks, { type: mediaRecorder?.mimeType || "audio/webm" });
    recordedChunks = [];
    stopMediaTracks();
    mediaRecorder = null;
    if (stopMode === "finalize") {
      await finishRecording(blob);
    }
  };

  mediaRecorder.start();
  isRecording = true;
  recordingStartedAt = Date.now();
  speechStartedAt = 0;
  lastVoiceAt = 0;
  hasDetectedSpeech = false;
  micButton.textContent = "Cancel";
  zhText.textContent = "开始听了。你自然说完就行。";
  startVoiceMonitor();
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

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = userText.value.trim();
  if (!text) return;
  userText.value = "";
  sendMessage(text);
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
micButton.addEventListener("click", () => {
  void toggleRecording();
});
refreshButton.addEventListener("click", async () => {
  await refreshHealth();
  await loadMemories();
});
inspectCommand.addEventListener("click", inspectCommandRisk);
loadDivergence.addEventListener("click", fetchDivergence);
loadDivergenceNews.addEventListener("click", fetchDivergenceNews);

refreshHealth();
loadMemories();
