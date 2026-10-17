# Scooter Inu Telegram Game Bot

A Telegram bot for the Scooter Inu runner at [scooterinu.xyz/#game](https://scooterinu.xyz/#game). In a private chat, request a score range with `/play @username MIN-MAX`, for example `/play @kuzhh_89 800-1000`. The bot requests a fresh server-issued run token, plans ordinary jump key events for the returned seed, and submits only if its local simulation predicts an in-range run. **The live server's returned score may differ and may already have been recorded before the bot can detect the mismatch. Do not use live submissions until the game/server replay has been validated against the current controller.**

The public site's shipped client uses `POST /api/leaderboard/run` to obtain a run token and seed. When a run ends, it sends `{token, events, score}` to `POST /api/leaderboard/score`; each event has the client's `{f, a}` frame/action shape. For a new device name, the client first receives `needs-name` and repeats the same completed run with `name`. `/status` reads the public `GET /api/leaderboard` endpoint. The bot does not submit an arbitrary client score without a replay transcript.

## Identity and controls

The bot binds one game name to each Telegram user after the first accepted score. A game name cannot be claimed by another Telegram account through this bot, and the bound name cannot be changed through `/play`, matching the game's one-name-per-device behavior. Game names are 3–16 letters, digits, or underscores. Use `/stop` from the initiating Telegram account to cancel an active search. The bot permits only one active search at a time, waits between run-token requests, and caps each search with `MAX_RUN_ATTEMPTS`.

The chosen name is a display label; the game does not verify control of an unrelated social-media account. Only use a name you are entitled to use. Keep the bot in private chat and optionally set `TELEGRAM_ALLOWED_CHAT_ID` to restrict access.

## Controller and score expectations

`scooterinu_planner.js` mirrors the runner's public client-side state update: its seeded random generator, obstacle creation, jump physics, collision boxes, and distance-based score. The speed ramp is `.001` per fixed 60 Hz tick because the client multiplies `.001` by the normalized tick factor (`dt / (1000/60) = 1`); it is not `.001 × 16.67 ms`. For each server-provided seed the planner tries a bounded set of ordinary jump timing/hold policies and independently replays any candidate transcript before marking it locally matched. The game server remains authoritative. If its returned score differs, the bot stops and reports the seed and transcript diagnostics, but cannot undo a score already recorded by the server.

The earlier seed-42 estimate of 9,007 was invalid: the planner multiplied the speed ramp by milliseconds, reaching maximum speed about 16.7 times too quickly. That estimate is retracted. The corrected physics regression now fails closed for that seed at a 9,000-point target; **this controller has not demonstrated 9,000+ under the corrected timing and must not be described as hackathon-ready for that target.** A different controller policy and authoritative server/staging replay test are needed before using high-score submissions.

## Setup

Requires Node.js and Python 3.10+:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `TELEGRAM_BOT_TOKEN` from BotFather. Never commit it. Export the environment and start the worker:

```bash
set -a
. ./.env
set +a
python3 telegram_scooter_bot.py
```

Configuration:

- `TELEGRAM_BOT_TOKEN`: required Telegram token.
- `TELEGRAM_ALLOWED_CHAT_ID`: optional single-chat allowlist.
- `GAME_BASE_URL`: defaults to `https://scooterinu.xyz`.
- `DATA_DIR`: defaults to `./data`; stores account-to-name bindings and per-Telegram-user game cookies. Keep this directory private and persistent.
- `MAX_RUN_ATTEMPTS`: maximum server-issued run tokens per `/play`; defaults to 30.
- `RUN_START_INTERVAL_SECONDS`: minimum gap between run requests; defaults to 10.

Run one worker replica so in-memory run coordination and Telegram polling stay consistent. The bot uses per-Telegram-user HTTP cookie jars so one device's name does not overwrite another's. `DATA_DIR` must be persisted by the deployment host if identity continuity across restarts is required.

## Tests

Tests use local simulations and a mock HTTP API; they do not request public run tokens or submit to the live leaderboard.

```bash
node --check scooterinu_planner.js
npm test
python3 -m unittest -v
```
