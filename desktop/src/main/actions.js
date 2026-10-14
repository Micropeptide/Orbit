'use strict';
// App-level actions shared by the menu, tray, and IPC.
const fs = require('fs/promises');
const path = require('path');
const { app, dialog, BrowserWindow } = require('electron');
const windows = require('./windows');
const server = require('./server');

const LETTER_COUNTRIES = new Set(['US', 'CA', 'MX', 'PH', 'CL', 'CO', 'VE', 'GT', 'CR', 'PR', 'DO', 'PA', 'SV', 'NI', 'HN', 'BZ', 'BO']);

function pdfPageSize() {
  let cc = '';
  try { cc = (app.getLocaleCountryCode() || '').toUpperCase(); } catch { /* unknown */ }
  return LETTER_COUNTRIES.has(cc) ? 'Letter' : 'A4';
}

function safeFileName(name) {
  const clean = String(name || '').replace(/[\/\\:*?"<>|\u0000-\u001f]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
  return clean || 'Orbit Chat';
}

/** Print the focused main window's page to a PDF the user picks. */
async function exportPDF(win = windows.targetWindow()) {
  if (!win || win.isDestroyed()) return;
  const title = windows.activeTitle(win) || win.webContents.getTitle().replace(/\s*[—–-]\s*Orbit$/, '') || 'Orbit Chat';
  const { canceled, filePath } = await dialog.showSaveDialog(win, {
    title: 'Export Chat as PDF',
    defaultPath: path.join(app.getPath('downloads'), `${safeFileName(title)}.pdf`),
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (canceled || !filePath) return;
  try {
    const data = await win.webContents.printToPDF({ pageSize: pdfPageSize(), printBackground: true });
    await fs.writeFile(filePath, data);
  } catch (err) {
    dialog.showMessageBox(win, { type: 'error', message: 'Couldn’t export the PDF', detail: String(err.message || err) });
  }
}

/** Stop the local model server (port 8011) after the user confirms. */
async function stopLocalModel() {
  const parent = BrowserWindow.getFocusedWindow() || undefined;
  const { response } = await dialog.showMessageBox(parent, {
    type: 'question',
    buttons: ['Stop Model', 'Cancel'],
    defaultId: 1,
    cancelId: 1,
    message: 'Stop the local model?',
    detail: 'Answers in progress that use the local model will stop. Orbit itself keeps running and will start the model again when it is needed.',
  });
  if (response !== 0) return;
  try {
    await server.postJSON('/api/server/stop');
  } catch (err) {
    dialog.showMessageBox(parent, { type: 'error', message: 'Couldn’t stop the local model', detail: String(err.message || err) });
  }
}

function launchAtLogin() { return !!app.getLoginItemSettings().openAtLogin; }
function setLaunchAtLogin(on) { app.setLoginItemSettings({ openAtLogin: !!on }); }

module.exports = { exportPDF, stopLocalModel, launchAtLogin, setLaunchAtLogin };
