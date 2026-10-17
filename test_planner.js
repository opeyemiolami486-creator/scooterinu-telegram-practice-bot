'use strict';
const assert = require('node:assert/strict');
const { planRun, simulateEvents, score, rng32 } = require('./scooterinu_planner');

assert.equal(score(40000), 1000);
assert.deepEqual([rng32(42)(), rng32(42)()], [rng32(42)(), rng32(42)()]);
const normal = planRun(42, 800, 1000);
assert.equal(normal.matched, true);
assert.ok(normal.score >= 800 && normal.score <= 1000);
assert.ok(normal.frames > 0);
assert.ok(normal.events.length > 0);
assert.deepEqual(normal.events[0], { f: 0, a: 0 });
for (let i = 1; i < normal.events.length; i++) {
  assert.ok(normal.events[i].f > normal.events[i - 1].f, 'event frames must be strictly increasing');
  assert.ok([0, 1].includes(normal.events[i].a), "only the game's ordinary jump key actions are used");
}
const high = planRun(42, 9000, 11000);
assert.equal(high.matched, true, 'seed 42 must demonstrate the planner can reach 9000+');
assert.ok(high.score >= 9000 && high.score <= 11000);
assert.ok(high.events.length > 2);
const replay = simulateEvents(high.seed, high.events);
assert.deepEqual(replay, { seed: high.seed, score: high.score, frames: high.frames, survived: false });
for (let i = 0; i < high.events.length; i++) {
  assert.ok(high.events[i].f >= 0 && high.events[i].f < high.frames);
  assert.ok([0, 1].includes(high.events[i].a));
  if (i) assert.ok(high.events[i].f > high.events[i - 1].f, 'high-score events must be strictly ordered');
}
assert.throws(() => planRun(42, 100, 50), /valid inclusive score range/);
assert.throws(() => planRun(-1, 100, 200), /unsigned 32-bit integer/);
console.log(`Planner tests passed; high-score fixture reached ${high.score} at seed ${high.seed}.`);
