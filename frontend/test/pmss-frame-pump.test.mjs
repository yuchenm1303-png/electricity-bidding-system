import assert from 'node:assert/strict';
import test from 'node:test';
import {createFramePump} from '../src/pmssFramePump.ts';

function harness(capture, blocked = () => false) {
  const timers = new Map();
  let next = 0;
  const pump = createFramePump({capture, blocked,
    schedule(fn, delay) { const id = ++next; timers.set(id, {fn, delay}); return id; },
    cancel(id) { timers.delete(id); }, onError() {},
  });
  return {pump, timers,
    fire() { const [id, entry] = timers.entries().next().value; timers.delete(id); entry.fn(); },
  };
}

test('input completion replaces the idle delay with a 40ms frame request', async () => {
  let captures = 0;
  const h = harness(async () => { captures++; });
  h.pump.request(); h.fire(); await Promise.resolve();
  assert.equal([...h.timers.values()][0].delay, 1200);
  h.pump.request(); h.pump.request();
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].delay, 40);
  h.fire(); await Promise.resolve();
  assert.equal(captures, 2);
  h.pump.stop();
});

test('slow screenshots coalesce repeated input into one follow-up without overlap', async () => {
  let release;
  let captures = 0;
  const h = harness(() => { captures++; return new Promise(resolve => { release = resolve; }); });
  h.pump.request(); h.fire();
  for (let i = 0; i < 20; i++) h.pump.request();
  assert.equal(captures, 1); assert.equal(h.timers.size, 0);
  release(); await Promise.resolve();
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].delay, 40);
  h.fire(); assert.equal(captures, 2);
  h.pump.stop(); release(); await Promise.resolve();
  assert.equal(h.timers.size, 0);
});

test('queued input has priority and closing prevents late captures', async () => {
  let busy = true;
  let captures = 0;
  const h = harness(async () => { captures++; }, () => busy);
  h.pump.request(); h.fire(); assert.equal(captures, 0);
  busy = false; h.pump.request(); h.fire(); await Promise.resolve();
  assert.equal(captures, 1);
  h.pump.stop(); h.pump.request();
  assert.equal(h.timers.size, 0);
});

test('capture errors keep polling alive instead of leaving a stuck pending frame', async () => {
  const h = harness(async () => { throw new Error('network'); });
  h.pump.request(); h.fire(); await Promise.resolve();
  assert.equal(h.timers.size, 1);
  assert.equal([...h.timers.values()][0].delay, 1200);
  h.pump.stop();
});
