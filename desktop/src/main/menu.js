'use strict';
// The native application menu. Page-level items send commands to the focused
// main window; see README "IPC contract".
const { app, Menu } = require('electron');
const { prefs } = require('./prefs');
const windows = require('./windows');
const actions = require('./actions');
const links = require('./links');
const server = require('./server');
const updater = require('./updater');

/** Orbit › Updates submenu, bound to the update prefs. */
function updatesSubmenu(hooks) {
  const p = updater.getState().prefs;
  const set = (patch) => () => hooks.setUpdatePrefs(patch);
  const mode = (label, value) => ({ label, type: 'radio', checked: p.autoUpdate === value, click: set({ autoUpdate: value }) });
  const every = (label, hours) => ({ label, type: 'radio', checked: p.updateCheckEvery === hours, click: set({ updateCheckEvery: hours }) });
  return [
    mode('Install Automatically', 'auto'),
    mode('Notify Me', 'notify'),
    mode('Don’t Check', 'off'),
    { type: 'separator' },
    every('Check Every Hour', 1),
    every('Check Every 6 Hours', 6),
    every('Check Every Day', 24),
    every('Check Every Week', 168),
    { type: 'separator' },
    {
      label: 'Include Beta Versions', type: 'checkbox', checked: p.updateChannel === 'beta',
      click: (mi) => hooks.setUpdatePrefs({ updateChannel: mi.checked ? 'beta' : 'stable' }),
    },
    { type: 'separator' },
    { label: updater.lastCheckedLabel(), enabled: false },
  ];
}

/** hooks: { quickAsk, setKeepInMenuBar(bool), onPrefsChanged(), checkForUpdates(), setUpdatePrefs(patch) } */
function build(hooks) {
  const cmd = (name, arg) => (_mi, focused) => {
    // In a preview window, Cmd+W just closes that window.
    if (name === 'close-tab' && focused && !windows.isMainWindow(focused)) { focused.close(); return; }
    windows.sendCommand(name, arg);
  };
  const item = (label, accelerator, name, arg) => ({ label, accelerator, click: cmd(name, arg) });
  // Extra accelerator for an existing action, invisible in the menu (macOS only).
  const alias = (accelerator, click) => ({ label: accelerator, accelerator, click, visible: false, acceleratorWorksWhenHidden: true });

  const template = [
    {
      label: app.name || 'Orbit',
      submenu: [
        { role: 'about', label: 'About Orbit' },
        { label: 'Check for Updates…', click: () => hooks.checkForUpdates() },
        { label: 'Updates', submenu: updatesSubmenu(hooks) },
        { type: 'separator' },
        item('Settings…', 'Cmd+,', 'settings'),
        { type: 'separator' },
        {
          label: 'Launch at Login', type: 'checkbox', checked: actions.launchAtLogin(),
          click: (mi) => { actions.setLaunchAtLogin(mi.checked); hooks.onPrefsChanged(); },
        },
        {
          label: 'Keep Running in Menu Bar', type: 'checkbox', checked: prefs.get('keepInMenuBar') !== false,
          click: (mi) => hooks.setKeepInMenuBar(mi.checked),
        },
        {
          label: 'Notify When Answers Finish', type: 'checkbox', checked: prefs.get('notifications') !== false,
          click: (mi) => { prefs.set('notifications', mi.checked); hooks.onPrefsChanged(); },
        },
        { type: 'separator' },
        { role: 'services' },
        { type: 'separator' },
        { role: 'hide', label: 'Hide Orbit' },
        { role: 'hideOthers' },
        { role: 'unhide' },
        { type: 'separator' },
        { role: 'quit', label: 'Quit Orbit', accelerator: 'Cmd+Q' },
      ],
    },
    {
      label: 'File',
      submenu: [
        item('New Chat', 'Cmd+N', 'new-chat'),
        item('New Chat With…', 'Cmd+Shift+N', 'new-chat-with'),
        { label: 'Quick Ask', accelerator: 'Alt+Space', click: () => hooks.quickAsk() },
        { label: 'New Window', accelerator: 'Cmd+Alt+N', click: () => windows.createMainWindow() },
        { type: 'separator' },
        item('Close Tab', 'Cmd+W', 'close-tab'),
        item('Reopen Closed Tab', 'Cmd+Shift+T', 'reopen-tab'),
        { type: 'separator' },
        { label: 'Export Chat as PDF…', accelerator: 'Cmd+Shift+E', click: () => actions.exportPDF() },
        { type: 'separator' },
        { label: 'Close Window', accelerator: 'Cmd+Shift+W', role: 'close' },
      ],
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'pasteAndMatchStyle' },
        { role: 'selectAll' },
        { type: 'separator' },
        item('Find in Chat', 'Cmd+F', 'find'),
      ],
    },
    {
      label: 'View',
      submenu: [
        item('Command Palette', 'Cmd+P', 'palette'),
        item('Toggle Sidebar', 'Cmd+B', 'toggle-sidebar'),
        item('Toggle Terminal', 'Ctrl+`', 'toggle-terminal'),
        item('Files', 'Cmd+J', 'files'),
        { type: 'separator' },
        { role: 'reload', accelerator: 'Cmd+R' },
        { role: 'forceReload' },
        { role: 'toggleDevTools', accelerator: 'Alt+Cmd+I' },
        { type: 'separator' },
        { label: 'Actual Size', accelerator: 'Cmd+0', click: () => windows.setZoom(1) },
        { label: 'Zoom In', accelerator: 'Cmd+Plus', click: () => windows.zoomBy(0.1) },
        alias('Cmd+=', () => windows.zoomBy(0.1)),
        { label: 'Zoom Out', accelerator: 'Cmd+-', click: () => windows.zoomBy(-0.1) },
        { type: 'separator' },
        { role: 'togglefullscreen' },
      ],
    },
    {
      label: 'Chat',
      submenu: [
        item('Stop Answer', 'Cmd+.', 'stop'),
        { type: 'separator' },
        // Ctrl+Tab / Ctrl+Shift+Tab are caught in before-input-event (macOS menus don't own them reliably).
        item('Next Tab', 'Cmd+Shift+]', 'next-tab'),
        item('Previous Tab', 'Cmd+Shift+[', 'prev-tab'),
        alias('Ctrl+Tab', cmd('next-tab')),
        alias('Ctrl+Shift+Tab', cmd('prev-tab')),
        {
          label: 'Go to Tab',
          submenu: Array.from({ length: 9 }, (_, i) => item(`Tab ${i + 1}`, `Cmd+${i + 1}`, 'tab', { n: i + 1 })),
        },
        { type: 'separator' },
        item('Jump to Chat…', 'Cmd+G', 'jump'),
      ],
    },
    { role: 'windowMenu' },
    {
      role: 'help',
      submenu: [
        { label: 'Open Orbit in Browser', click: () => links.openExternal(server.baseURL() + '/') },
        { type: 'separator' },
        { label: 'Orbit Website', click: () => links.openExternal('https://runtianwu.com') },
        { label: 'Orbit on GitHub', click: () => links.openExternal('https://github.com/Micropeptide/Orbit') },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

module.exports = { build };
