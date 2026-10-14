'use strict';
// Quick Ask panel: one auto-growing textarea.
(() => {
  const input = document.getElementById('input');
  const form = document.getElementById('form');
  const quick = window.orbitQuick;
  const CHROME = 26 + 30; // panel padding above + room below the text

  function grow() {
    input.style.height = 'auto';
    input.style.height = input.scrollHeight + 'px';
    quick.resize(Math.min(input.scrollHeight, 340) + CHROME);
  }

  function send(background) {
    const text = input.value.trim();
    if (!text) return;
    quick.submit(text, background);
    input.value = '';
    grow();
  }

  input.addEventListener('input', grow);
  input.addEventListener('keydown', (e) => {
    if (e.isComposing || e.keyCode === 229) return; // IME composition in progress
    if (e.key === 'Escape') {
      e.preventDefault();
      quick.hide();
    } else if (e.key === 'Enter' && !e.shiftKey && !e.altKey) {
      e.preventDefault();
      send(e.metaKey || e.ctrlKey);
    }
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); send(false); });

  quick.onShown(() => {
    input.focus();
    input.select();
    grow();
  });
  grow();
})();
