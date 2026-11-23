// The refresh scheduler with a fake clock (WI-0056). Run by tests/test_frontend.py:
//   node tests/refresh.test.js
'use strict';
const assert = require('assert');
const path = require('path');
const { createScheduler, MAX_BACKOFF } = require(path.join(__dirname, '..', 'src', 'szsdlc_ui_win95', 'static', 'refresh.js'));

const MIN = 60000;

function world({ interval = MIN } = {}) {
  let t = 0;
  let timers = [];
  let seq = 0;
  const runs = [];      // { kind, opts, resolve }
  const statuses = [];
  const clock = {
    now: () => t,
    setTimer: (fn, ms) => { const id = ++seq; timers.push({ id, at: t + ms, fn }); return id; },
    clearTimer: (id) => { timers = timers.filter((x) => x.id !== id); },
  };
  const s = createScheduler({
    ...clock, interval,
    run: (kind, opts) => new Promise((resolve) => runs.push({ kind, opts, resolve })),
    onStatus: (text) => statuses.push(text),
  });
  const flush = () => new Promise((r) => setImmediate(r));
  return {
    s, runs, statuses,
    async advance(ms) {
      const end = t + ms;
      for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const next = timers[0];
        if (!next || next.at > end) break;
        timers.shift();
        t = next.at;
        next.fn();
        await flush();
      }
      t = end;
      await flush();
    },
    async finish(result = { ok: true }) {
      const r = runs.find((x) => !x.done);
      assert(r, 'no run in progress');
      r.done = true;
      r.resolve(result);
      await flush(); await flush();
    },
    pending: () => runs.filter((x) => !x.done),
    timers: () => timers.length,
  };
}

const tests = {
  async 'a tick runs at the interval, and the next counts from when it finished'() {
    const w = world();
    w.s.setInterval(MIN);
    await w.advance(MIN - 1);
    assert.strictEqual(w.runs.length, 0);
    await w.advance(1);
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['background']);
    await w.advance(5000);
    await w.finish();
    await w.advance(MIN - 1);
    assert.strictEqual(w.runs.length, 1);
    await w.advance(1);
    assert.strictEqual(w.runs.length, 2);
  },

  async 'Off makes no runs; a manual refresh still works'() {
    const w = world();
    w.s.setInterval(0);
    await w.advance(10 * MIN);
    assert.strictEqual(w.runs.length, 0);
    assert.strictEqual(w.timers(), 0);
    w.s.manual();
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['manual']);
  },

  async 'a hidden tab makes no requests, and catches up once on return'() {
    const w = world();
    w.s.setInterval(MIN);
    w.s.setVisible(false);
    await w.advance(5 * MIN);
    assert.strictEqual(w.runs.length, 0);
    assert.strictEqual(w.timers(), 0);
    w.s.setVisible(true);
    assert.strictEqual(w.runs.length, 1, 'overdue: refreshes once on return');
  },

  async 'returning before the interval waits only for what is left'() {
    const w = world();
    w.s.setInterval(MIN);
    await w.advance(20000);
    w.s.setVisible(false);
    await w.advance(10000);
    w.s.setVisible(true);
    assert.strictEqual(w.runs.length, 0);
    await w.advance(MIN - 30000);
    assert.strictEqual(w.runs.length, 1);
  },

  async 'a tick during a manual refresh is skipped, and the interval counts from its end'() {
    const w = world();
    w.s.setInterval(MIN);
    await w.advance(MIN - 1000);
    w.s.manual();
    await w.advance(5000);  // the tick would have been due inside the manual run
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['manual']);
    await w.finish();
    await w.advance(MIN - 1);
    assert.strictEqual(w.runs.length, 1);
    await w.advance(1);
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['manual', 'background']);
  },

  async 'a manual refresh during a background one runs once afterwards, however often pressed'() {
    const w = world();
    w.s.setInterval(MIN);
    await w.advance(MIN);
    assert.strictEqual(w.runs[0].kind, 'background');
    assert.strictEqual(w.s.buttonDisabled(), false, 'enabled during a background refresh: a click queues');
    w.s.manual({ replace: true });
    assert.strictEqual(w.s.buttonDisabled(), true, 'disabled once a manual refresh is queued');
    w.s.manual(); w.s.manual();
    assert.strictEqual(w.runs.length, 1, 'queued, not started');
    await w.finish();
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['background', 'manual']);
    assert.deepStrictEqual(w.runs[1].opts, { replace: true }, 'its own options are kept');
    assert.strictEqual(w.s.buttonDisabled(), true);
    await w.finish();
    assert.strictEqual(w.runs.length, 2, 'only once');
    assert.strictEqual(w.s.buttonDisabled(), false);
  },

  async 'pressing again during a manual refresh does nothing'() {
    const w = world();
    w.s.manual(); w.s.manual();
    assert.strictEqual(w.runs.length, 1);
  },

  async 'after three failures the interval doubles, caps at 15 minutes, and resets on success'() {
    const w = world();
    w.s.setInterval(MIN);
    const fail = async () => { await w.advance(w.s.state().effective); await w.finish({ ok: false }); };
    await fail(); await fail();
    assert.strictEqual(w.s.state().effective, MIN, 'two failures: no backoff yet');
    await fail();
    assert.strictEqual(w.s.state().effective, 2 * MIN);
    assert.match(w.statuses.at(-1), /^Offline: retrying in 2 min$/);
    for (let i = 0; i < 6; i++) await fail();
    assert.strictEqual(w.s.state().effective, MAX_BACKOFF);
    assert.match(w.statuses.at(-1), /^Offline: retrying in 15 min$/);
    await w.advance(MAX_BACKOFF);
    await w.finish({ ok: true });
    assert.strictEqual(w.s.state().effective, MIN, 'one success returns to the set interval');
  },

  async 'a throwing run counts as a failure, not a crash'() {
    let calls = 0;
    const s = createScheduler({ interval: 0, run: async () => { calls += 1; throw new Error('boom'); },
      setTimer: () => 1, clearTimer: () => {} });
    s.manual();
    await new Promise((r) => setImmediate(r));
    assert.strictEqual(calls, 1);
    assert.strictEqual(s.state().failures, 1);
    assert.strictEqual(s.state().running, null);
  },

  async 'arriving at a project refreshes it now, or right after the current run'() {
    const w = world();
    w.s.arrive();
    assert.deepStrictEqual(w.runs.map((r) => r.kind), ['background']);
    w.s.arrive();
    assert.strictEqual(w.runs.length, 1);
    await w.finish();
    assert.strictEqual(w.runs.length, 2, 'once more, for the project switched to');
    await w.finish();
    assert.strictEqual(w.runs.length, 2);
  },
};

(async () => {
  let failed = 0;
  for (const [name, fn] of Object.entries(tests)) {
    try { await fn(); console.log(`ok   ${name}`); } catch (err) { failed += 1; console.log(`FAIL ${name}\n     ${err.stack}`); }
  }
  if (failed) { console.log(`${failed} failed`); process.exit(1); }
  console.log('refresh scheduler ok');
})();
