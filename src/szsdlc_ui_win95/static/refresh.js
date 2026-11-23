// The refresh scheduler: when to refresh the project on screen, and how a
// person's Refresh and the background one take turns. A pure state machine:
// no DOM, no fetch, and an injected clock, so it is tested with a fake one
// (tests/refresh.test.js). app.js supplies `run`, which does the work.
//
//   - At most one refresh runs at a time.
//   - A background tick while a manual refresh runs is skipped; the interval
//     then counts from when the manual one finished.
//   - A manual refresh while a background one runs is queued, once, and runs
//     as its own refresh as soon as the background one ends.
//   - Off (interval 0) and a hidden tab make no background requests.
//   - After three failures in a row the interval doubles, up to 15 minutes,
//     and is back to normal after one success.
(function (root) {
  'use strict';

  const MAX_BACKOFF = 15 * 60 * 1000;
  const FAILURES_BEFORE_BACKOFF = 3;

  function createScheduler({ run, now = () => Date.now(), setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (t) => clearTimeout(t), interval = 60000, onChange = () => {}, onStatus = () => {} }) {
    let every = interval;          // the set interval in ms; 0 is Off
    let visible = true;
    let running = null;            // null | 'manual' | 'background'
    let queuedManual = null;       // the options of the one queued manual refresh, or null
    let arriveAfter = false;       // a project switch while something ran
    let failures = 0;
    let lastDone = now();
    let timer = null;

    function effective() {
      if (failures < FAILURES_BEFORE_BACKOFF) return every;
      return Math.min(MAX_BACKOFF, every * 2 ** (failures - FAILURES_BEFORE_BACKOFF + 1));
    }
    function disarm() { if (timer !== null) { clearTimer(timer); timer = null; } }
    function arm() {
      disarm();
      if (!every || !visible || running) return;
      const wait = Math.max(0, lastDone + effective() - now());
      timer = setTimer(tick, wait);
    }
    function tick() {
      timer = null;
      if (!every || !visible) return;
      if (running) return;  // a manual refresh is bringing it up to date already
      start('background', {});
    }
    async function start(kind, opts) {
      running = kind;
      disarm();
      onChange();
      let result = { ok: true };
      try { result = (await run(kind, opts)) || { ok: true }; } catch (err) { result = { ok: false, error: err }; }
      running = null;
      lastDone = now();
      if (result.ok) {
        failures = 0;
      } else {
        failures += 1;
        if (failures >= FAILURES_BEFORE_BACKOFF && every) {
          onStatus(`Offline: retrying in ${Math.max(1, Math.round(effective() / 60000))} min`);
        }
      }
      if (queuedManual) {
        const next = queuedManual;
        queuedManual = null;
        return start('manual', next);
      }
      if (arriveAfter) {
        arriveAfter = false;
        return start('background', {});
      }
      onChange();
      arm();
      return result;
    }

    return {
      // A person asked: the button, the menu or F5.
      manual(opts = {}) {
        if (running === 'manual' || queuedManual) return;
        if (running === 'background') { queuedManual = opts; onChange(); return; }
        start('manual', opts);
      },
      // The project on screen changed: bring it up to date once, now or after
      // whatever is running.
      arrive() {
        if (running) { arriveAfter = true; return; }
        start('background', {});
      },
      setInterval(ms) { every = Math.max(0, Number(ms) || 0); arm(); },
      setVisible(on) {
        visible = !!on;
        if (!visible) { disarm(); return; }
        if (every && !running && now() - lastDone >= effective()) { tick(); return; }
        arm();
      },
      // The toolbar button: disabled only while a manual refresh runs or waits.
      buttonDisabled() { return running === 'manual' || queuedManual !== null; },
      state() { return { running, queued: queuedManual !== null, failures, interval: every, effective: effective(), armed: timer !== null }; },
      stop() { disarm(); every = 0; },
    };
  }

  const api = { createScheduler, MAX_BACKOFF };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SzRefresh = api;
})(typeof window !== 'undefined' ? window : globalThis);
