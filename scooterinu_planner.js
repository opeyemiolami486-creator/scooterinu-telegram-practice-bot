#!/usr/bin/env node
'use strict';
// Mirrors the public game's deterministic runner update and records its native
// {f, a} key events. The server remains authoritative for score validation.
const FRAME_MS = 1000 / 60;
const GROUND_Y = 93;
const PLAYER_HITBOXES = [
  { x: 27, y: 2, w: 13, h: 12 }, { x: 26, y: 12, w: 8, h: 12 },
  { x: 6, y: 22, w: 26, h: 13 }, { x: 4, y: 34, w: 36, h: 12 },
];
const TYPES = [
  { kind: 'small', width: 17, height: 35, y: 105, multipleSpeed: 4, minGap: 120 },
  { kind: 'large', width: 25, height: 50, y: 90, multipleSpeed: 7, minGap: 120 },
];
function rng32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const score = distance => Math.round(0.025 * distance);
function overlap(a, b) {
  return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y;
}
function clampJump(s) {
  if (s.reachedMinHeight && s.vy < -5) s.vy = -5;
}
function collides(s) {
  const player = PLAYER_HITBOXES.map(box => ({ ...box, x: box.x + 50, y: box.y + s.y }));
  for (const obstacle of s.obstacles) {
    if (obstacle.x > 94 || obstacle.x + obstacle.type.width * obstacle.size < 50) continue;
    for (let n = 0; n < obstacle.size; n++) {
      const x = obstacle.x + n * obstacle.type.width;
      const w = obstacle.type.width, h = obstacle.type.height, y = obstacle.type.y;
      const shapes = [
        { x: x + 2, y: y + 0.62 * h, w: w - 4, h: 0.38 * h },
        { x: x + 0.25 * w, y: y + 0.30 * h, w: 0.5 * w, h: 0.34 * h },
        { x: x + 0.4 * w, y: y + 0.08 * h, w: 0.2 * w, h: 0.24 * h },
      ];
      if (shapes.some(shape => player.some(box => overlap(box, shape)))) return true;
    }
  }
  return false;
}
function createState(seed) {
  const random = rng32(seed);
  return {
    status: 'idle', speed: 6, distance: 0, runningTime: 0, y: GROUND_Y,
    vy: 0, jumping: false, reachedMinHeight: false, obstacles: [],
    clouds: [{ x: 480, y: 30 + 40 * random() }], groundOffset: 0,
    random, frame: 0,
  };
}
function applyInput(s, action) {
  if (action === 0) {
    if (s.status === 'over') return;
    if (s.status === 'idle') s.status = 'running';
    if (!s.jumping) {
      s.jumping = true;
      s.reachedMinHeight = false;
      s.vy = -10 - s.speed / 10;
    }
  } else {
    clampJump(s);
  }
}
function step(s) {
  if (s.status !== 'running') return false;
  const random = s.random;
  s.runningTime += FRAME_MS;
  if (s.jumping) {
    s.y += Math.round(s.vy);
    s.vy += 0.6;
    if (s.y < GROUND_Y - 30) s.reachedMinHeight = true;
    if (s.y < 30) clampJump(s);
    if (s.y > GROUND_Y) {
      s.y = GROUND_Y;
      s.vy = 0;
      s.jumping = false;
    }
  }
  const advance = s.speed;
  s.distance += advance;
  s.groundOffset = (s.groundOffset + advance) % 600;
  for (const obstacle of s.obstacles) obstacle.x -= advance;
  s.obstacles = s.obstacles.filter(o => o.x + o.type.width * o.size > 0);
  if (s.runningTime > 3000) {
    const last = s.obstacles.at(-1);
    if (!last || last.x + last.type.width * last.size + last.gap < 600) {
      const type = random() < 0.5 ? TYPES[0] : TYPES[1];
      let size = 1 + Math.floor(3 * random());
      if (s.speed < type.multipleSpeed) size = 1;
      const base = Math.round(type.width * s.speed + 0.6 * type.minGap);
      const upper = Math.round(1.5 * base);
      const gap = base + random() * (upper - base);
      const variant = Math.floor(1000 * random());
      s.obstacles.push({ type, x: 600, size, gap, variant });
    }
  }
  for (const cloud of s.clouds) cloud.x -= 0.2;
  s.clouds = s.clouds.filter(cloud => cloud.x > -50);
  const lastCloud = s.clouds.at(-1);
  if (!lastCloud || lastCloud.x < 500 - 300 * random()) {
    s.clouds.push({ x: 600, y: 20 + 50 * random() });
  }
  // The shipped client increments speed immediately before its collision test.
  if (s.speed < 13) s.speed += 0.001;
  if (collides(s)) {
    s.status = 'over';
    s.frame++;
    return true;
  }
  s.frame++;
  return false;
}
function simulatePolicy(seed, minimum, maximum, policy, maxFrames = 120000) {
  const s = createState(seed);
  const events = [{ f: 0, a: 0 }];
  let eventIndex = 0;
  let releaseFrame = policy.holdFrames;
  let targetReached = false;
  for (let frame = 0; frame < maxFrames; frame++) {
    if (frame === releaseFrame) events.push({ f: frame, a: 1 });
    while (eventIndex < events.length && events[eventIndex].f === frame) {
      applyInput(s, events[eventIndex].a);
      eventIndex++;
    }
    const currentScore = score(s.distance);
    if (currentScore >= minimum) targetReached = true;
    if (!targetReached && !s.jumping) {
      const approaching = s.obstacles.find(o => o.x + o.type.width * o.size >= 48 && o.x <= policy.triggerX);
      if (approaching) {
        events.push({ f: frame, a: 0 });
        releaseFrame = frame + policy.holdFrames;
        applyInput(s, 0);
        eventIndex = events.length;
      }
    }
    if (step(s)) {
      const finalScore = score(s.distance);
      return { seed: seed >>> 0, score: finalScore, distance: Math.floor(s.distance), frames: s.frame, survived: false, events, matched: finalScore >= minimum && finalScore <= maximum, policy };
    }
    if (score(s.distance) > maximum) {
      return { seed: seed >>> 0, score: score(s.distance), distance: Math.floor(s.distance), frames: s.frame, survived: true, events, matched: false, policy, outOfRange: true };
    }
  }
  return { seed: seed >>> 0, score: score(s.distance), distance: Math.floor(s.distance), frames: s.frame, survived: true, events, matched: false, policy, timedOut: true };
}
function simulateEvents(seed, events, maxFrames = 120000) {
  const s = createState(seed);
  let index = 0;
  for (let frame = 0; frame < maxFrames; frame++) {
    while (index < events.length && events[index].f === frame) {
      applyInput(s, events[index].a);
      index++;
    }
    if (index < events.length && events[index].f < frame) {
      throw new Error(`Event ${index} is out of frame order.`);
    }
    if (step(s)) {
      return { seed: seed >>> 0, score: score(s.distance), frames: s.frame, survived: false };
    }
  }
  return { seed: seed >>> 0, score: score(s.distance), frames: s.frame, survived: s.status !== 'over' };
}
function planRun(seed, minimum, maximum, options = {}) {
  if (!Number.isSafeInteger(seed) || seed < 0 || seed > 0xffffffff) throw new Error('Seed must be an unsigned 32-bit integer.');
  if (!Number.isSafeInteger(minimum) || !Number.isSafeInteger(maximum) || minimum < 0 || maximum < minimum) throw new Error('Use a valid inclusive score range, e.g. 800-1000.');
  let best = null;
  let policyTests = 0;
  const holds = options.holds ?? [1, 4, 7, 10, 14];
  const triggers = options.triggers ?? [125, 150, 175, 200, 225, 250, 275];
  for (const holdFrames of holds) {
    for (const triggerX of triggers) {
      policyTests++;
      const result = simulatePolicy(seed, minimum, maximum, { holdFrames, triggerX }, options.maxFrames ?? 120000);
      if (!best || Math.abs(result.score - (minimum + maximum) / 2) < Math.abs(best.score - (minimum + maximum) / 2)) best = result;
      if (result.matched) {
        const replay = simulateEvents(seed, result.events, options.maxFrames ?? 120000);
        if (replay.survived || replay.score !== result.score || replay.frames !== result.frames) {
          throw new Error(`Serialized replay mismatch: planned ${result.score}/${result.frames}, replayed ${replay.score}/${replay.frames}.`);
        }
        return { ...result, policyTests };
      }
    }
  }
  return { ...best, policyTests };
}
function search(minimum, maximum, options = {}) {
  const maxAttempts = Math.max(1, Math.min(1000, options.maxAttempts ?? 20));
  const baseSeed = (options.seed ?? (Date.now() >>> 0)) >>> 0;
  let closest = null;
  for (let i = 0; i < maxAttempts; i++) {
    const seed = (baseSeed + Math.imul(i, 0x9e3779b9)) >>> 0;
    const result = planRun(seed, minimum, maximum, options);
    if (!closest || Math.abs(result.score - (minimum + maximum) / 2) < Math.abs(closest.score - (minimum + maximum) / 2)) closest = { ...result, attempt: i + 1 };
    if (result.matched) return { ...result, attempt: i + 1, attempts: i + 1 };
  }
  return { ...closest, attempts: maxAttempts };
}
if (require.main === module) {
  let input = '';
  process.stdin.setEncoding('utf8');
  process.stdin.on('data', part => { input += part; });
  process.stdin.on('end', () => {
    try {
      const request = JSON.parse(input);
      const result = planRun(request.seed, request.minimum, request.maximum, request.options || {});
      process.stdout.write(JSON.stringify(result));
    } catch (error) {
      process.stderr.write(`${error?.stack || error}\n`);
      process.exitCode = 1;
    }
  });
}
module.exports = { createState, applyInput, step, score, simulatePolicy, simulateEvents, planRun, search, rng32 };
