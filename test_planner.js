'use strict';
const assert = require('node:assert/strict');
const { createState, applyInput, step, planRun, simulateEvents, score, rng32 } = require('./scooterinu_planner');

assert.equal(score(40000), 1000);
assert.deepEqual([rng32(42)(), rng32(42)()], [rng32(42)(), rng32(42)()]);
const speedFixture = createState(1);
applyInput(speedFixture, 0);
for (let i = 0; i < 60; i++) step(speedFixture);
assert.ok(Math.abs(speedFixture.speed - 6.06) < 1e-9, `60-tick speed should be 6.06, got ${speedFixture.speed}`);
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
const replay = simulateEvents(normal.seed, normal.events);
assert.deepEqual(replay, { seed: normal.seed, score: normal.score, frames: normal.frames, survived: false });
const high = planRun(42, 8500, 10000);
assert.equal(high.matched, false, 'correct physics must not repeat the obsolete high-score overestimate');
assert.ok(high.score < 8500);
assert.throws(() => planRun(42, 100, 50), /valid inclusive score range/);
assert.throws(() => planRun(-1, 100, 200), /unsigned 32-bit integer/);
console.log(`Planner physics tests passed; seed 42 correctly fails closed for 9000+ (best simulation ${high.score}).`);
