const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("companionDesktop", {
  openWorkbench: () => ipcRenderer.invoke("pet:open-workbench"),
  health: () => ipcRenderer.invoke("pet:health"),
  checkin: () => ipcRenderer.invoke("pet:checkin"),
  chat: (payload) => ipcRenderer.invoke("pet:chat", payload),
});
