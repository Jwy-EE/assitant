const { app, BrowserWindow } = require("electron");

app.whenReady().then(() => {
  const win = new BrowserWindow({ width: 420, height: 280, show: false });
  win.loadURL("data:text/html,<h1>electron smoke ok</h1>");
  win.once("ready-to-show", () => {
    console.log("electron smoke ready");
    app.quit();
  });
});
