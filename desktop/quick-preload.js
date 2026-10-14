'use strict';
// Bridge for the Quick Ask panel (sandboxed preload).
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('orbitQuick', {
  submit(text, background) { ipcRenderer.send('quick:submit', String(text), !!background); },
  hide() { ipcRenderer.send('quick:hide'); },
  resize(height) { ipcRenderer.send('quick:resize', Number(height)); },
  onShown(cb) {
    if (typeof cb === 'function') ipcRenderer.on('quick:shown', () => cb());
  },
});
