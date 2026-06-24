const { app, BrowserWindow, Menu, Tray, ipcMain, nativeImage, globalShortcut, session } = require("electron");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const ROOT_DIR = path.resolve(__dirname, "..");
const BACKEND_URL = "http://127.0.0.1:8765";
const TRAY_ICON_PATH = path.join(__dirname, "effect-preview.png");
const ELECTRON_USER_DATA = path.join(ROOT_DIR, ".electron-user-data");
const ELECTRON_CACHE_DIR = path.join(ELECTRON_USER_DATA, "cache");
const ELECTRON_SESSION_DIR = path.join(ELECTRON_USER_DATA, "session");

for (const dir of [ELECTRON_USER_DATA, ELECTRON_CACHE_DIR, ELECTRON_SESSION_DIR]) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}
app.commandLine.appendSwitch("user-data-dir", ELECTRON_USER_DATA);
app.setPath("userData", ELECTRON_USER_DATA);
app.setPath("sessionData", ELECTRON_SESSION_DIR);
app.setPath("cache", ELECTRON_CACHE_DIR);
app.disableHardwareAcceleration();
app.commandLine.appendSwitch("disable-gpu");
app.commandLine.appendSwitch("disable-gpu-compositing");
app.commandLine.appendSwitch("disable-software-rasterizer");

let backendProcess = null;
let petWindow = null;
let workbenchWindow = null;
let tray = null;

function getPythonCommand() {
  const venvPython = path.join(ROOT_DIR, ".venv", "Scripts", "python.exe");
  return fs.existsSync(venvPython) ? venvPython : "python";
}

function waitForBackend(timeoutMs = 12000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const retry = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Backend did not become ready in time."));
        return;
      }
      setTimeout(probe, 450);
    };
    const probe = () => {
      const req = http.get(`${BACKEND_URL}/api/health`, (res) => {
        res.resume();
        if (res.statusCode >= 200 && res.statusCode < 500) {
          resolve(true);
          return;
        }
        retry();
      });
      req.on("error", retry);
      req.setTimeout(900, () => {
        req.destroy();
        retry();
      });
    };
    probe();
  });
}

function startBackend() {
  if (process.env.ASSISTANT_BACKEND_MANAGED === "1") {
    return;
  }
  if (backendProcess) return;
  backendProcess = childProcess.spawn(getPythonCommand(), ["-m", "assistant_app"], {
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      PYTHONPATH: path.join(ROOT_DIR, "src"),
      PYTHONUTF8: "1",
      ASSISTANT_TTS_PROVIDER: "http",
      ASSISTANT_TTS_ENDPOINT: "http://127.0.0.1:8767/tts",
      ASSISTANT_TTS_VOICE: "kurisu_ja",
    },
    windowsHide: true,
    stdio: "ignore",
  });
  backendProcess.once("exit", () => {
    backendProcess = null;
  });
}

function createPetWindow() {
  petWindow = new BrowserWindow({
    width: 340,
    height: 620,
    minWidth: 300,
    minHeight: 540,
    maxWidth: 420,
    frame: false,
    transparent: true,
    resizable: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  petWindow.loadURL(`${BACKEND_URL}/desktop-assets/pet.html`);
  petWindow.once("ready-to-show", () => petWindow.show());
  petWindow.on("closed", () => {
    petWindow = null;
  });
}

function createWorkbenchWindow() {
  workbenchWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 960,
    minHeight: 680,
    show: false,
    backgroundColor: "#101310",
    title: "Research Companion Workbench",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  workbenchWindow.loadURL(BACKEND_URL);
  workbenchWindow.on("closed", () => {
    workbenchWindow = null;
  });
}

function showWorkbench() {
  if (!workbenchWindow) {
    createWorkbenchWindow();
  }
  if (!workbenchWindow.isVisible()) {
    workbenchWindow.show();
  }
  workbenchWindow.focus();
}

function hideOrShowPet() {
  if (!petWindow) {
    createPetWindow();
    return;
  }
  petWindow.isVisible() ? petWindow.hide() : petWindow.show();
}

function createTray() {
  const trayIcon = nativeImage.createFromPath(TRAY_ICON_PATH);
  tray = new Tray(trayIcon);
  tray.setToolTip("DeepSeek Research Companion");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "Open Workbench", click: showWorkbench },
      { label: "Show / Hide Pet", click: hideOrShowPet },
      { type: "separator" },
      { label: "Quit", click: () => app.quit() },
    ]),
  );
}

app.whenReady().then(async () => {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(permission === "media" || permission === "microphone" || permission === "audioCapture");
  });
  if (session.defaultSession.setPermissionCheckHandler) {
    session.defaultSession.setPermissionCheckHandler((_webContents, permission) =>
      permission === "media" || permission === "microphone" || permission === "audioCapture"
    );
  }
  if (process.env.ASSISTANT_BACKEND_MANAGED !== "1") {
    startBackend();
  }
  await waitForBackend().catch(() => undefined);
  createPetWindow();
  createTray();
  globalShortcut.register("CommandOrControl+Shift+Space", showWorkbench);
});

ipcMain.handle("pet:open-workbench", () => {
  showWorkbench();
  return true;
});

ipcMain.handle("pet:health", async () => getBackendJson("/api/health", 1200));
ipcMain.handle("pet:checkin", async () => getBackendJson("/api/proactive/checkin", 1200));
ipcMain.handle("pet:chat", async (_event, payload) =>
  postBackendJson("/api/chat", payload ?? {}, 90000),
);

function getBackendJson(pathname, timeoutMs) {
  return new Promise((resolve) => {
    const req = http.get(`${BACKEND_URL}${pathname}`, (res) => {
      let body = "";
      res.setEncoding("utf8");
      res.on("data", (chunk) => {
        body += chunk;
      });
      res.on("end", () => {
        try {
          resolve({ ok: true, data: JSON.parse(body) });
        } catch {
          resolve({ ok: false, reason: "Invalid backend response." });
        }
      });
    });
    req.on("error", (error) => resolve({ ok: false, reason: error.message }));
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve({ ok: false, reason: "Backend timeout." });
    });
  });
}

function postBackendJson(pathname, payload, timeoutMs) {
  return new Promise((resolve) => {
    const body = JSON.stringify(payload);
    const req = http.request(
      `${BACKEND_URL}${pathname}`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(body),
        },
      },
      (res) => {
        let responseBody = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          responseBody += chunk;
        });
        res.on("end", () => {
          try {
            const data = JSON.parse(responseBody || "{}");
            resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, data, status: res.statusCode });
          } catch {
            resolve({ ok: false, reason: "Invalid backend response.", status: res.statusCode });
          }
        });
      },
    );
    req.on("error", (error) => resolve({ ok: false, reason: error.message }));
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve({ ok: false, reason: "Backend timeout." });
    });
    req.write(body);
    req.end();
  });
}

app.on("window-all-closed", (event) => {
  event.preventDefault();
});

app.on("before-quit", () => {
  globalShortcut.unregisterAll();
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});