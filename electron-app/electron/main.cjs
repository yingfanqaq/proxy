const { app, BrowserWindow, Tray, Menu, nativeImage, ipcMain } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

const API_PORT = 39201;
const API_HOST = '127.0.0.1';
const isDev = !app.isPackaged;

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let isQuitting = false;

function findPython() {
  const fs = require('fs');
  const os = require('os');
  const home = os.homedir();
  const candidates = [
    process.env.PYTHON_BIN,
    path.join(home, 'miniforge3', 'bin', 'python3'),
    path.join(home, 'miniconda3', 'bin', 'python3'),
    path.join(home, 'anaconda3', 'bin', 'python3'),
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
  ].filter(Boolean);
  for (const p of candidates) {
    try { if (fs.statSync(p).isFile()) return p; } catch {}
  }
  return 'python3';
}

function startPythonBackend() {
  const python = findPython();
  const args = ['-c', `from proxy_stack.api_server import run_api_server; run_api_server("${API_HOST}", ${API_PORT})`];

  let cwd;
  if (isDev) {
    cwd = path.resolve(__dirname, '..', '..');
  } else {
    cwd = path.resolve(process.resourcesPath, '..', '..', '..', '..', '..');
    const fs = require('fs');
    if (!fs.existsSync(path.join(cwd, 'proxy_stack'))) {
      cwd = path.resolve(app.getPath('home'), 'mycodelibrary', 'proxy');
    }
  }

  console.log(`Starting Python backend: ${python} ${args.join(' ')} in ${cwd}`);
  pythonProcess = spawn(python, args, {
    cwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });

  pythonProcess.stdout.on('data', (data) => console.log(`[python] ${data}`));
  pythonProcess.stderr.on('data', (data) => console.error(`[python] ${data}`));
  pythonProcess.on('error', (err) => {
    console.error(`Failed to start Python at ${python}: ${err.message}`);
    pythonProcess = null;
  });
  pythonProcess.on('close', (code) => {
    console.log(`Python backend exited with code ${code}`);
    pythonProcess = null;
  });
}

function waitForBackend(retries = 30) {
  return new Promise((resolve, reject) => {
    const check = (attempt) => {
      const req = http.get(`http://${API_HOST}:${API_PORT}/api/config`, (res) => {
        if (res.statusCode === 200) resolve();
        else if (attempt < retries) setTimeout(() => check(attempt + 1), 500);
        else reject(new Error('Backend did not start'));
      });
      req.on('error', () => {
        if (attempt < retries) setTimeout(() => check(attempt + 1), 500);
        else reject(new Error('Backend did not start'));
      });
      req.end();
    };
    check(0);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    title: 'proxyEverywhere',
    titleBarStyle: 'hiddenInset',
    trafficLightPosition: { x: 16, y: 18 },
    backgroundColor: '#0a0a0a',
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
  }

  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('ready-to-show', () => {
    // Don't auto-show — tray-only by default
  });
}

function showWindow() {
  if (mainWindow) {
    mainWindow.show();
    mainWindow.focus();
  } else {
    createWindow();
    mainWindow.show();
    mainWindow.focus();
  }
}

function createTray() {
  const icon = nativeImage.createFromDataURL(
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAoUlEQVR4nO1WWxKAIAh0vf+d6cumUAOEnGZi/xRYkHhUSiKR+DvAL4iITiHQyVcx460zpdE5wjk/1159L8QAvFkw29MF3iA4B+ddJtOQah2pawAAnrLCZdoOMreZ5mWW9jV3gURunR3mAKQMWIvMFED7trNXNlnUAOucj+68XTB0tHMOYGZwU3IsJYlTrAHvRpTsv7WMeLRR/wNv8SYSiRAcKrezsKHIOfYAAAAASUVORK5CYII='
  );
  icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.setToolTip('proxyEverywhere');

  const contextMenu = Menu.buildFromTemplate([
    { label: 'Settings...', click: showWindow },
    { type: 'separator' },
    { label: 'Start Services', click: () => { http.get(`http://${API_HOST}:${API_PORT}/api/services/start`, () => {}); } },
    { label: 'Restart Services', click: () => { http.get(`http://${API_HOST}:${API_PORT}/api/services/restart`, () => {}); } },
    { label: 'Stop Services', click: () => { http.get(`http://${API_HOST}:${API_PORT}/api/services/stop`, () => {}); } },
    { type: 'separator' },
    { label: 'Quit proxyEverywhere', click: () => { isQuitting = true; app.quit(); } },
  ]);
  tray.setContextMenu(contextMenu);
  tray.on('click', showWindow);
}

app.whenReady().then(async () => {
  if (process.platform === 'darwin') app.dock.hide();

  ipcMain.handle('get-auto-launch', () => {
    return app.getLoginItemSettings().openAtLogin;
  });
  ipcMain.handle('set-auto-launch', (_event, enabled) => {
    app.setLoginItemSettings({ openAtLogin: enabled });
    return app.getLoginItemSettings().openAtLogin;
  });

  startPythonBackend();
  createTray();

  try {
    await waitForBackend();
    console.log('Python backend is ready');
  } catch (err) {
    console.error('Failed to start Python backend:', err);
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  isQuitting = true;
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM');
    pythonProcess = null;
  }
});
