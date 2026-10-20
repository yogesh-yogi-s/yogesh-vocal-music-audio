'use strict';

const { app, BrowserWindow, dialog, session } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');

let window = null;
let backend = null;
let stopping = false;
let backendErrors = '';
const smokeTest = process.argv.includes('--smoke-test');

if (!app.requestSingleInstanceLock()) {
  if (smokeTest) process.exitCode = 1;
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });

  app.whenReady().then(start).catch((error) => {
    if (smokeTest) {
      process.stderr.write(`${error.stack || error}\n`);
      process.exitCode = 1;
    } else {
      dialog.showErrorBox('VMA could not start', String(error.message || error));
    }
    app.quit();
  });
}

function backendExecutable() {
  const folder = app.isPackaged
    ? path.join(process.resourcesPath, 'backend')
    : path.join(__dirname, 'dist', 'backend', 'VMA-Backend');
  return path.join(folder, 'VMA-Backend.exe');
}

function waitForPort(child) {
  return new Promise((resolve, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('Backend startup timed out.')), 30000);
    const fail = (error) => { clearTimeout(timeout); reject(error); };
    child.once('error', fail);
    child.once('exit', (code) => fail(new Error(`Backend exited before startup (${code}).`)));
    child.stdout.on('data', (chunk) => {
      output += chunk.toString('utf8');
      const match = output.match(/(?:^|\r?\n)VMA_PORT=(\d+)\r?\n/);
      if (match) {
        const port = Number(match[1]);
        if (port < 1 || port > 65535) return fail(new Error('Backend returned an invalid port.'));
        clearTimeout(timeout);
        resolve(port);
      }
      if (output.length > 4096) output = output.slice(-512);
    });
  });
}

async function waitUntilReady(origin, child) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error('Backend stopped during startup.');
    try {
      const response = await fetch(`${origin}/api/ready`);
      if (response.ok) return;
    } catch {
      // The backend may still be initializing.
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error('Backend did not become ready.');
}

async function start() {
  const executable = backendExecutable();
  backend = spawn(executable, [], {
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
    env: { ...process.env, VMA_ENVIRONMENT: 'development' },
  });
  backend.stderr.on('data', (chunk) => {
    backendErrors = (backendErrors + chunk.toString('utf8')).slice(-8192);
  });
  let origin;
  try {
    const port = await waitForPort(backend);
    origin = `http://127.0.0.1:${port}`;
    await waitUntilReady(origin, backend);
  } catch (error) {
    throw new Error(`${error.message}\n${backendErrors}`);
  }

  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 650,
    show: false,
    title: 'VMA — Vocal Music Audio',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-attach-webview', (event) => event.preventDefault());
  window.webContents.on('will-navigate', (event, url) => {
    try {
      if (new URL(url).origin !== origin) event.preventDefault();
    } catch {
      event.preventDefault();
    }
  });
  await window.loadURL(origin);
  if (smokeTest) {
    const loaded = await window.webContents.executeJavaScript(
      "Boolean(document.querySelector('#site-nav') && document.querySelector('#create-form') && document.querySelector('#try-demo'))"
    );
    if (!loaded) throw new Error('Packaged UI is missing VMA workflow controls.');
    const demoLoaded = await window.webContents.executeJavaScript(`
      new Promise((resolve) => {
        document.querySelector('#try-demo').click();
        const deadline = Date.now() + 10000;
        const check = () => {
          const message = document.querySelector('#demo-status').textContent;
          if (message.includes('Welcome demo loaded')) return resolve(true);
          if (Date.now() >= deadline) return resolve(false);
          setTimeout(check, 100);
        };
        check();
      })
    `);
    if (!demoLoaded) throw new Error('Packaged UI could not load the playback demo.');
    window.destroy();
    app.quit();
    return;
  }
  window.show();
  window.on('closed', () => { window = null; });
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', (event) => {
  if (!backend || stopping || backend.exitCode !== null) return;
  event.preventDefault();
  stopping = true;
  const timeout = setTimeout(() => backend.kill(), 5000);
  backend.once('exit', () => {
    clearTimeout(timeout);
    backend = null;
    app.quit();
  });
  backend.stdin.write('shutdown\n');
});
