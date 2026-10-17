#!/usr/bin/env python3
"""Telegram frontend for authorized Scooter Inu gameplay and score submissions."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
import aiohttp
from scooterinu_api import ScooterApiClient, ScooterApiError

LOG = logging.getLogger("scooterinu_bot")
PLANNER = Path(__file__).with_name("scooterinu_planner.js")
PLAY_RE = re.compile(r"^/play(?:@[A-Za-z0-9_]+)?\s+@?([A-Za-z0-9_]{3,16})\s+(\d{1,6})-(\d{1,6})\s*$", re.I)
HELP = (
    "Scooter Inu game bot\n\n"
    "/play @username MIN-MAX — play a server-issued run and submit only if the validated score is in range\n"
    "Example: /play @kuzhh_89 800-1000\n"
    "/status — show the public top riders\n"
    "/stop — cancel your active search\n"
    "/help — show this message\n\n"
    "Your chosen game name is bound to your Telegram account after your first accepted score. "
    "Only one search runs at a time. Runs and scores are checked by Scooter Inu's server."
)


class IdentityStore:
    """Persist one claimed game nickname per Telegram account and prevent reuse."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS identities (telegram_user TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE)")
        self.db.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get(self, telegram_user: str) -> str | None:
        row = self.db.execute("SELECT name FROM identities WHERE telegram_user=?", (str(telegram_user),)).fetchone()
        return row[0] if row else None

    def owner(self, name: str) -> str | None:
        row = self.db.execute("SELECT telegram_user FROM identities WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        return row[0] if row else None

    def bind(self, telegram_user: str, name: str) -> None:
        try:
            self.db.execute("INSERT INTO identities(telegram_user,name) VALUES(?,?)", (str(telegram_user), name))
            self.db.commit()
        except sqlite3.IntegrityError as exc:
            self.db.rollback()
            raise ValueError("That game name is already bound to a different Telegram account.") from exc

    def close(self) -> None:
        self.db.close()


def parse_play(text: str) -> tuple[str, int, int] | None:
    match = PLAY_RE.fullmatch(text.strip())
    if not match:
        return None
    name, low, high = match.groups()
    minimum, maximum = int(low), int(high)
    if maximum < minimum:
        raise ValueError("The upper score bound must be at least the lower score bound.")
    return name, minimum, maximum


async def run_planner(seed: int, minimum: int, maximum: int, timeout: float = 60.0) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        "node", str(PLANNER), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    body = json.dumps({"seed": seed, "minimum": minimum, "maximum": maximum}).encode()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(body), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise TimeoutError("The run planner exceeded its time limit.") from exc
    if proc.returncode != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-1000:] or "Planner failed")
    result = json.loads(stdout.decode("utf-8"))
    if not isinstance(result, dict) or not isinstance(result.get("events"), list):
        raise RuntimeError("Planner returned an incomplete run transcript.")
    return result


def classify_server_score(server_score: Any, expected: int, minimum: int, maximum: int) -> str:
    if isinstance(server_score, bool) or not isinstance(server_score, int):
        return "missing"
    if not minimum <= server_score <= maximum:
        return "out_of_range"
    if server_score != expected:
        return "in_range_mismatch"
    return "match"


class ScooterTelegramBot:
    def __init__(self, token: str, base_url: str, data_dir: str, allowed_chat: str = ""):
        self.telegram_url = f"https://api.telegram.org/bot{token}"
        self.base_url = base_url
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.identity = IdentityStore(self.data_dir / "identities.sqlite3")
        self.allowed_chat = allowed_chat.strip()
        self.clients: dict[str, ScooterApiClient] = {}
        self.active_task: asyncio.Task[Any] | None = None
        self.active_user: str | None = None
        self.last_run_start = 0.0
        self.start_interval = max(0.0, float(os.getenv("RUN_START_INTERVAL_SECONDS", "10")))
        self.max_attempts = max(1, min(1000, int(os.getenv("MAX_RUN_ATTEMPTS", "30"))))
        self.session: aiohttp.ClientSession | None = None

    def api_client(self, telegram_user: str) -> ScooterApiClient:
        if telegram_user not in self.clients:
            self.clients[telegram_user] = ScooterApiClient(self.base_url, telegram_user, self.data_dir)
        return self.clients[telegram_user]

    async def telegram(self, method: str, payload: dict[str, Any]) -> Any:
        assert self.session is not None
        async with self.session.post(f"{self.telegram_url}/{method}", json=payload) as response:
            data = await response.json(content_type=None)
            if response.status >= 400 or not isinstance(data, dict) or not data.get("ok"):
                raise RuntimeError(f"Telegram {method} failed: {data}")
            return data.get("result")

    async def send(self, chat_id: str, text: str) -> None:
        try:
            await self.telegram("sendMessage", {"chat_id": chat_id, "text": text})
        except Exception:
            LOG.exception("Could not send Telegram reply")

    async def rate_limit_wait(self, chat_id: str) -> None:
        elapsed = time.monotonic() - self.last_run_start
        wait_s = max(0.0, self.start_interval - elapsed)
        if wait_s:
            await self.send(chat_id, f"Waiting {wait_s:.0f}s before the next run request to respect the game's pacing.")
            await asyncio.sleep(wait_s)

    async def begin_run(self, client: ScooterApiClient, chat_id: str) -> dict[str, Any]:
        await self.rate_limit_wait(chat_id)
        self.last_run_start = time.monotonic()
        for retry in range(5):
            try:
                return await client.begin_run()
            except ScooterApiError as exc:
                if exc.status not in {408, 425, 429, 500, 502, 503, 504} or retry == 4:
                    raise
                delay = max(1.0, min(60.0, exc.retry_after or 2 ** retry))
                await self.send(chat_id, f"Run service is temporarily busy; retrying in {delay:.0f}s.")
                await asyncio.sleep(delay)
        raise RuntimeError("Could not obtain a run token.")

    async def play(self, chat_id: str, telegram_user: str, name: str, minimum: int, maximum: int) -> None:
        client = self.api_client(telegram_user)
        try:
            known_name = self.identity.get(telegram_user)
            if known_name and known_name.casefold() != name.casefold():
                await self.send(chat_id, f"This Telegram account is already bound to game name @{known_name}. The game allows one name per device/account.")
                return
            owner = self.identity.owner(name)
            if owner is not None and owner != telegram_user:
                await self.send(chat_id, "That game name is already bound to another Telegram account.")
                return
            board = await client.leaderboard()
            me = board.get("me") if isinstance(board.get("me"), dict) else {}
            remote_name = me.get("name")
            if isinstance(remote_name, str) and remote_name:
                if remote_name.casefold() != name.casefold():
                    await self.send(chat_id, f"This game device is already bound to @{remote_name}; it cannot be changed through the bot.")
                    return
                if known_name is None:
                    self.identity.bind(telegram_user, remote_name)
            await self.send(chat_id, f"Starting Scooter Inu runs for @{name}, target {minimum}-{maximum}. The server's score may differ from the local prediction; if so, the game may already have recorded it before the bot can detect the mismatch. The bot will alert you and stop. Use /stop to cancel.")
            closest: dict[str, Any] | None = None
            for attempt in range(1, self.max_attempts + 1):
                run = await self.begin_run(client, chat_id)
                run_started_at = time.monotonic()
                await self.send(chat_id, f"Run {attempt}/{self.max_attempts}: planning server seed {run['seed']}…")
                result = await run_planner(run["seed"], minimum, maximum)
                result["attempt"] = attempt
                if closest is None or abs(result["score"] - (minimum + maximum) / 2) < abs(closest["score"] - (minimum + maximum) / 2):
                    closest = result
                if not result.get("matched"):
                    await self.send(chat_id, f"Seed {run['seed']}: planner predicts {result['score']} points, outside {minimum}-{maximum}; no score was submitted.")
                    continue
                predicted_score = result.get("score")
                frames = result.get("frames")
                events = result.get("events")
                if (isinstance(predicted_score, bool) or not isinstance(predicted_score, int)
                        or not minimum <= predicted_score <= maximum
                        or result.get("survived") is not False
                        or isinstance(frames, bool) or not isinstance(frames, int) or frames <= 0
                        or not isinstance(events, list) or not events):
                    await self.send(chat_id, f"Safety stop: planner output for seed {run['seed']} did not pass range/terminal-run checks; nothing was submitted.")
                    return
                duration = result["frames"] / 60.0
                remaining_duration = max(0.0, duration - (time.monotonic() - run_started_at))
                await self.send(chat_id, f"Seed {run['seed']}: planner predicts {predicted_score} points ({minimum}-{maximum}); replay is {frames} frames / {len(events)} inputs. Letting the run play out for about {remaining_duration:.0f}s before submission…")
                deadline = time.monotonic() + remaining_duration
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(remaining, 30.0))
                    left = max(0, int(deadline - time.monotonic()))
                    if left and left % 60 < 30:
                        await self.send(chat_id, f"Run is in progress; about {left}s remaining before score submission.")
                submitted = await client.submit_score(run["token"], result["events"], result["score"], name)
                server_score = submitted.get("score")
                accepted_name = submitted.get("name")
                if isinstance(accepted_name, str) and accepted_name.casefold() != name.casefold():
                    await self.send(chat_id, f"The game accepted {server_score} points under the device's existing name @{accepted_name}, not @{name}; check the device binding before using this bot again.")
                    return
                if self.identity.get(telegram_user) is None:
                    self.identity.bind(telegram_user, name)
                score_status = classify_server_score(server_score, predicted_score, minimum, maximum)
                if score_status == "out_of_range":
                    await self.send(chat_id, f"CRITICAL SCORE MISMATCH — not a successful target run. Scooter Inu already accepted and posted {server_score} points, outside {minimum}-{maximum}; the bot has stopped and will not retry. Local prediction was {predicted_score}; seed={run['seed']}, frames={frames}, inputs={len(events)}. The bot cannot undo a score already accepted by the game.")
                    return
                if score_status == "missing":
                    await self.send(chat_id, f"Score submission response did not include an authoritative integer score. Local prediction was {predicted_score}; seed={run['seed']}, frames={frames}. Treat the result as unverified; the bot has stopped.")
                    return
                if score_status == "in_range_mismatch":
                    await self.send(chat_id, f"Score accepted for @{name}: {server_score} points, within {minimum}-{maximum}. Note: the server score differs from the local prediction {predicted_score}; seed={run['seed']}, frames={frames}, inputs={len(events)}.\nRank: {submitted.get('rank', 'not shown')}\nAttempts: {attempt}.")
                    return
                await self.send(chat_id, f"Score accepted for @{name}: {server_score} points (requested {minimum}-{maximum}).\nRank: {submitted.get('rank', 'not shown')}\nAttempts: {attempt}.")
                return
            summary = f"No in-range server run after {self.max_attempts} attempts. Nothing was submitted."
            if closest:
                summary += f" Closest local simulation: {closest['score']} points on seed {closest['seed']}."
            await self.send(chat_id, summary)
        except asyncio.CancelledError:
            await self.send(chat_id, "Search cancelled. No unqualified score was submitted.")
            raise
        except ScooterApiError as exc:
            await self.send(chat_id, f"Scooter Inu API error{f' (HTTP {exc.status})' if exc.status else ''}: {exc}")
        except Exception as exc:
            LOG.exception("/play failed")
            await self.send(chat_id, f"/play failed: {type(exc).__name__}: {exc}")
        finally:
            task = asyncio.current_task()
            if self.active_task is task:
                self.active_task = None
                self.active_user = None

    async def handle(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        telegram_user = str((message.get("from") or {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not chat_id or not telegram_user:
            return
        if self.allowed_chat and chat_id != self.allowed_chat:
            return
        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text else ""
        if command in {"/start", "/help"}:
            await self.send(chat_id, HELP)
            return
        if command in {"/status"}:
            try:
                board = await self.api_client(telegram_user).leaderboard()
                rows = board.get("top", [])
                formatted = [f"{i}. {row.get('name', '?')} — {row.get('score', '?')}" for i, row in enumerate(rows[:10], 1)]
                await self.send(chat_id, "Scooter Inu Top Riders\n" + ("\n".join(formatted) if formatted else "No scores returned."))
            except Exception as exc:
                await self.send(chat_id, f"Could not read leaderboard: {type(exc).__name__}: {exc}")
            return
        if command == "/stop":
            if self.active_task and not self.active_task.done() and self.active_user == telegram_user:
                self.active_task.cancel()
                await self.send(chat_id, "Cancellation requested.")
            else:
                await self.send(chat_id, "You do not have an active search to cancel.")
            return
        try:
            parsed = parse_play(text)
        except ValueError as exc:
            await self.send(chat_id, str(exc))
            return
        if parsed is None:
            if command == "/play":
                await self.send(chat_id, "Use /play @username MIN-MAX, for example: /play @kuzhh_89 800-1000. Game names must be 3-16 letters, digits, or underscores.")
            return
        if chat.get("type") != "private":
            await self.send(chat_id, "For account safety, use /play in a private chat with this bot.")
            return
        name, minimum, maximum = parsed
        if maximum < minimum:
            await self.send(chat_id, "The upper score bound must be at least the lower score bound.")
            return
        if maximum > 100000:
            await self.send(chat_id, "Maximum requested score is 100000.")
            return
        if self.active_task and not self.active_task.done():
            await self.send(chat_id, "Another search is active. Wait for it to finish or use /stop from its starting account.")
            return
        task = asyncio.create_task(self.play(chat_id, telegram_user, name, minimum, maximum))
        self.active_task = task
        self.active_user = telegram_user

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            self.session = session
            await self.telegram("deleteWebhook", {"drop_pending_updates": True})
            offset = 0
            LOG.info("Scooter Inu Telegram bot started; game API=%s", self.base_url)
            while True:
                try:
                    updates = await self.telegram("getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})
                    for update in updates:
                        offset = update["update_id"] + 1
                        message = update.get("message") or {}
                        try:
                            await self.handle(message)
                        except Exception:
                            LOG.exception("Could not handle Telegram update")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOG.exception("Telegram polling failed")
                    await asyncio.sleep(3)

    async def close(self) -> None:
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
            await asyncio.gather(self.active_task, return_exceptions=True)
        await asyncio.gather(*(client.close() for client in self.clients.values()), return_exceptions=True)
        self.identity.close()


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in the environment.")
    bot = ScooterTelegramBot(
        token=token,
        base_url=os.getenv("GAME_BASE_URL", "https://scooterinu.xyz"),
        data_dir=os.getenv("DATA_DIR", "./data"),
        allowed_chat=os.getenv("TELEGRAM_ALLOWED_CHAT_ID", ""),
    )
    try:
        await bot.run()
    finally:
        await bot.close()


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    asyncio.run(main())
