#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { simulatePolicy, simulateEvents, planRun } = require('./scooterinu_planner');

const SEEDS = Number(process.env.BENCHMARK_SEEDS || 500);
const MAX_FRAMES = Number(process.env.BENCHMARK_FRAMES || 40000);
const TERMINAL_MAX_FRAMES = Number(process.env.TERMINAL_MAX_FRAMES || 120000);
const TARGET_MINIMUM = 10000;
const TARGET_MAXIMUM = 11000;
const POLICY = { holdFrames: 4, triggerFrames: 19, closeGapFrames: 28, closeHoldFrames: 3 };
const scores = [];
const replaySeeds = new Set([1, 42, SEEDS]);

for (let seed = 1; seed <= SEEDS; seed++) {
  // A minimum above the benchmark horizon keeps the controller active throughout.
  const result = simulatePolicy(seed, 100000, 1000000, POLICY, MAX_FRAMES);
  assert.ok(result.score > 10000, `seed ${seed} reached only ${result.score}`);
  assert.equal(result.timedOut, true, `seed ${seed} unexpectedly collided before the horizon`);
  scores.push(result.score);

  const terminal = planRun(seed, TARGET_MINIMUM, TARGET_MAXIMUM, { maxFrames: TERMINAL_MAX_FRAMES });
  assert.equal(terminal.matched, true,
    `seed ${seed} did not produce a terminal score in ${TARGET_MINIMUM}-${TARGET_MAXIMUM}: ${terminal.score}`);
  assert.equal(terminal.survived, false, `seed ${seed} did not end in a terminal collision`);

  if (replaySeeds.has(seed)) {
    const replay = simulateEvents(seed, terminal.events, TERMINAL_MAX_FRAMES);
    assert.deepEqual(replay, {
      seed,
      score: terminal.score,
      frames: terminal.frames,
      survived: false,
    }, `transcript replay mismatch for seed ${seed}`);
  }
}

console.log(JSON.stringify({
  testedSeeds: SEEDS,
  maxFrames: MAX_FRAMES,
  terminalMaxFrames: TERMINAL_MAX_FRAMES,
  policy: POLICY,
  passed: scores.length,
  minScore: Math.min(...scores),
  maxScore: Math.max(...scores),
  terminalTarget: `${TARGET_MINIMUM}-${TARGET_MAXIMUM}`,
  terminalMatched: SEEDS,
  replayCheckedSeeds: [...replaySeeds].filter(seed => seed <= SEEDS),
}));
