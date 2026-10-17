#!/usr/bin/env node
'use strict';

// Offline approximation of the public runner's published client-side rules.
// It never contacts scooterinu.xyz and cannot submit leaderboard results.
const FRAME_MS = 1000 / 60;
const GROUND_Y = 93;
const PLAYER_HITBOXES = [
  { x: 27, y: 2, w: 13, h: 12 }, { x: 26, y: 12, w: 8, h: 12 },
  { x: 6, y: 22, w: 26, h: 13 }, { x: 4, y: 34, w: 36, h: 12 },
];
const TYPES = [
  { width: 17, height: 35, y: 105, multipleSpeed: 4, minGap: 120 },
  { width: 25, height: 50, y: 90, multipleSpeed: 7, minGap: 120 },
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
function score(distance) { return Math.round(0.025 * distance); }
function overlaps(a, b) { return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y; }
function hit(state) {
  const player = PLAYER_HITBOXES.map(b => ({ ...b, x: b.x + 50, y: b.y + state.y }));
  for (const obstacle of state.obstacles) {
    if (obstacle.x > 94 || obstacle.x + obstacle.type.width * obstacle.size < 50) continue;
    for (let n = 0; n < obstacle.size; n++) {
      const x = obstacle.x + n * obstacle.type.width, w = obstacle.type.width, h = obstacle.type.height, y = obstacle.type.y;
      const shapes = [
        { x: x + 2, y: y + 0.62 * h, w: w - 4, h: 0.38 * h },
        { x: x + 0.25 * w, y: y + 0.30 * h, w: 0.5 * w, h: 0.34 * h },
        { x: x + 0.4 * w, y: y + 0.08 * h, w: 0.2 * w, h: 0.24 * h },
      ];
      if (shapes.some(o => player.some(p => overlaps(p, o)))) return true;
    }
  }
  return false;
}
function chooseJump(state) {
  if (state.jumping) return false;
  const next = state.obstacles.find(o => o.x + o.type.width * o.size >= 48 && o.x <= 190);
  if (!next) return false;
  // Trigger before contact. This is a simple look-ahead policy, not an exploit.
  return next.x <= 190;
}
function simulate(seed, maxFrames = 120000) {
  const random = rng32(seed);
  const s = { speed: 6, distance: 0, runningTime: 0, y: GROUND_Y, vy: 0, jumping: false, reachedMinHeight: false, obstacles: [], frames: 0, alive: true };
  while (s.alive && s.frames < maxFrames) {
    if (chooseJump(s)) { s.jumping = true; s.reachedMinHeight = false; s.vy = -10 - s.speed / 10; }
    else if (s.jumping && s.reachedMinHeight && s.vy < -5) s.vy = -5;
    if (s.jumping) {
      s.y += Math.round(s.vy); s.vy += 0.6;
      if (s.y < GROUND_Y - 30) s.reachedMinHeight = true;
      if (s.y < 30 && s.reachedMinHeight && s.vy < -5) s.vy = -5;
      if (s.y > GROUND_Y) { s.y = GROUND_Y; s.vy = 0; s.jumping = false; }
    }
    const advance = s.speed;
    s.distance += advance; s.runningTime += FRAME_MS;
    for (const o of s.obstacles) o.x -= advance;
    s.obstacles = s.obstacles.filter(o => o.x + o.type.width * o.size > 0);
    if (s.runningTime > 3000) {
      const last = s.obstacles.at(-1);
      if (!last || last.x + last.type.width * last.size + last.gap < 600) {
        const type = TYPES[random() < 0.5 ? 0 : 1];
        let size = 1 + Math.floor(3 * random());
        if (s.speed < type.multipleSpeed) size = 1;
        const base = Math.round(type.width * s.speed + 0.6 * type.minGap);
        const upper = Math.round(1.5 * base);
        const gap = base + random() * (upper - base);
        s.obstacles.push({ type, x: 600, size, gap });
      }
    }
    s.frames++;
    if (hit(s)) s.alive = false;
    if (s.speed < 13) s.speed += 0.001 * FRAME_MS;
  }
  return { seed: seed >>> 0, score: score(s.distance), distance: Math.floor(s.distance), frames: s.frames, seconds: +(s.frames / 60).toFixed(1), survived: s.alive };
}
function search(minimum, maximum, options = {}) {
  if (!Number.isSafeInteger(minimum) || !Number.isSafeInteger(maximum) || minimum < 0 || maximum < minimum) throw new Error('Use a valid inclusive score range, e.g. 800-1000.');
  const maxAttempts = options.maxAttempts ?? 100;
  const baseSeed = (options.seed ?? (Date.now() >>> 0)) >>> 0;
  let closest = null;
  for (let i = 0; i < maxAttempts; i++) {
    const result = simulate((baseSeed + Math.imul(i, 0x9e3779b9)) >>> 0);
    if (!closest || Math.abs(result.score - (minimum + maximum) / 2) < Math.abs(closest.score - (minimum + maximum) / 2)) closest = result;
    if (result.score >= minimum && result.score <= maximum) return { ...result, attempt: i + 1, matched: true, attempts: i + 1 };
  }
  return { ...closest, attempt: maxAttempts, matched: false, attempts: maxAttempts };
}
if (require.main === module) {
  const [range, seedArg] = process.argv.slice(2);
  if (!range || !/^\d+-\d+$/.test(range)) {
    console.log('Offline practice only. Usage: node scooterinu_planner.js 800-1000 [seed]');
    process.exit(0);
  }
  const [min, max] = range.split('-').map(Number);
  console.log(JSON.stringify(search(min, max, { seed: seedArg ? Number(seedArg) : undefined }), null, 2));
}
module.exports = { simulate, search, score };
