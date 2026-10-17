"""Telegram interface for local Scooter Inu practice simulation only."""
from __future__ import annotations
import asyncio, json, os, re, logging
from pathlib import Path
import aiohttp

LOG = logging.getLogger("scooterinu_practice")
PLANNER = Path(__file__).with_name("scooterinu_planner.js")
RANGE = re.compile(r"^/play(?:@[A-Za-z0-9_]+)?\s+(@[A-Za-z0-9_]{3,32})\s+(\d+)-(\d+)\s*$", re.I)
HELP = (
    "Scooter Inu Practice Bot\n\n"
    "Run an offline practice simulation with:\n/play @username 800-1000\n\n"
    "The planner uses a local approximation of the runner and reports a simulated result. "
    "It does not control the website, request run tokens, or submit leaderboard scores.\n"
    "/help — show this message"
)

async def local_search(low: int, high: int) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "node", str(PLANNER), f"{low}-{high}",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    if proc.returncode:
        raise RuntimeError(err.decode(errors="replace")[-500:] or "Planner failed")
    return json.loads(out)

async def telegram_call(session: aiohttp.ClientSession, token: str, method: str, payload: dict):
    async with session.post(f"https://api.telegram.org/bot{token}/{method}", json=payload) as response:
        data = await response.json()
        if not response.ok or not data.get("ok"):
            raise RuntimeError(f"Telegram API error: {data.get('description', response.status)}")
        return data["result"]

async def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment.")
    allowed = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
    attempts = max(1, min(500, int(os.getenv("MAX_LOCAL_ATTEMPTS", "100"))))
    timeout = aiohttp.ClientTimeout(total=40)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        offset = 0
        LOG.info("Scooter Inu practice bot is online; external game APIs are disabled")
        while True:
            try:
                updates = await telegram_call(session, token, "getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})
                for update in updates:
                    offset = update["update_id"] + 1
                    msg = update.get("message") or {}
                    text = (msg.get("text") or "").strip()
                    chat = msg.get("chat") or {}
                    chat_id = str(chat.get("id", ""))
                    if not chat_id or (allowed and chat_id != allowed):
                        continue
                    if text.split(maxsplit=1)[0].split("@", 1)[0].lower() in {"/start", "/help"}:
                        await telegram_call(session, token, "sendMessage", {"chat_id": chat_id, "text": HELP})
                        continue
                    match = RANGE.fullmatch(text)
                    if not match:
                        continue
                    username, low, high = match.group(1), int(match.group(2)), int(match.group(3))
                    if high < low:
                        reply = "The upper score bound must be at least the lower bound."
                    else:
                        await telegram_call(session, token, "sendMessage", {"chat_id": chat_id, "text": f"Running local practice for {username} in range {low}-{high} (up to {attempts} simulated seeds)…"})
                        try:
                            result = await asyncio.wait_for(local_search(low, high), timeout=90)
                            if result["matched"]:
                                reply = (f"Practice result for {username}: {result['score']} simulated points "
                                         f"in {result['attempt']} attempt(s), seed {result['seed']}, "
                                         f"{result['seconds']}s simulated.\n\nThis is an offline estimate only; nothing was played or submitted on scooterinu.xyz.")
                            else:
                                reply = (f"No match in {attempts} local attempts. Closest result: {result['score']} "
                                         f"points (seed {result['seed']}). No website run was started and no score was submitted.")
                        except Exception as exc:
                            LOG.exception("practice simulation failed")
                            reply = f"Local simulation failed: {type(exc).__name__}. No website interaction occurred."
                    await telegram_call(session, token, "sendMessage", {"chat_id": chat_id, "text": reply})
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("Telegram polling error")
                await asyncio.sleep(3)

if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
