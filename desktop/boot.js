'use strict';
// "Starting Orbit…" page: shows progress from main and offers Retry / Choose folder.
(() => {
  const status = document.getElementById('status');
  const retry = document.getElementById('retry');
  const choose = document.getElementById('choose');
  const boot = window.orbitBoot;

  function setBusy(busy) {
    document.body.classList.toggle('failed', !busy);
    retry.disabled = busy;
  }

  if (!boot) { status.textContent = 'Desktop bridge unavailable.'; return; }

  boot.onStatus(({ text, failed }) => {
    if (typeof text === 'string') status.textContent = text;
    setBusy(!failed);
  });
  retry.addEventListener('click', () => {
    status.textContent = 'Trying again…';
    setBusy(true);
    boot.retry();
  });
  choose.addEventListener('click', () => boot.chooseFolder());
  setBusy(true);
})();
