# Scooter Inu Telegram Practice Bot

A small Telegram bot and local jump-planner prototype inspired by Scooter Inu's browser runner at [scooterinu.xyz/#game](https://scooterinu.xyz/#game). It parses commands such as `/play @kuzhh_89 800-1000` and runs a seeded, local-only simulation to estimate whether the range is reachable.

## Safety and scope

This is an **offline practice tool**, not a leaderboard bot. It does not open the game, request `/api/leaderboard/run` tokens, replay button events, claim a run ID, or post a score. The target website says it rejects scores that could not really happen; this prototype makes no claim that its simplified model will match the live build or reach any particular score. Results are explicitly labeled simulated.

No wallet, seed phrase, private key, run token, or Telegram token belongs in source control. The only runtime secret is a Telegram BotFather token supplied through the environment.

## Run a local simulation

Requires Node.js 20+:

```bash
node scooterinu_planner.js 800-1000 42
npm test
```

The optional seed makes the result reproducible. It reports a local estimate, not a valid website score.

## Run the Telegram bot

Requires Python 3.10+ and `pip install -r requirements.txt`:

```bash
export TELEGRAM_BOT_TOKEN='your BotFather token'
python telegram_scooter_bot.py
```

Optional environment variables are shown in `.env.example`. In Telegram, send `/play @username 800-1000`. The username is a label for the practice response; it is not used to access or impersonate that account. Use a private chat and configure `TELEGRAM_ALLOWED_CHAT_ID` before exposing the bot to others.

## Planner notes

The simulator is a lightweight local approximation of the visible client mechanics: 60 Hz ticks, speed progression, distance-derived score, seeded obstacle generation, jump arc, and collision geometry. The actual game may change and its server's authoritative validation is not reproduced here. `MAX_LOCAL_ATTEMPTS` bounds the work. This project makes no guarantee of surviving to 9,000+ points.
