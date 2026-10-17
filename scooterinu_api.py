"""HTTP client for Scooter Inu's public runner leaderboard flow."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import aiohttp


class ScooterApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class ScooterApiClient:
    def __init__(self, base_url: str, telegram_user_id: str, data_dir: str | Path):
        self.base_url = base_url.rstrip("/")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("GAME_BASE_URL must use HTTPS (HTTP is allowed only for loopback tests)")
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.data_dir, 0o700)
        except OSError:
            pass
        digest = hashlib.sha256(str(telegram_user_id).encode()).hexdigest()[:24]
        self.cookie_path = self.data_dir / f"cookie-{digest}.jar"
        jar = aiohttp.CookieJar(unsafe=True)
        if self.cookie_path.is_file():
            try:
                jar.load(self.cookie_path)
            except (OSError, ValueError, EOFError):
                self.cookie_path.unlink(missing_ok=True)
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30), cookie_jar=jar
        )

    async def close(self) -> None:
        self._save_cookies()
        await self.session.close()

    def _save_cookies(self) -> None:
        try:
            self.session.cookie_jar.save(self.cookie_path)
            os.chmod(self.cookie_path, 0o600)
        except (OSError, AttributeError):
            pass

    async def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Origin": self.origin,
            "Referer": f"{self.origin}/#game",
        }
        url = f"{self.base_url}{path}"
        try:
            async with self.session.post(url, json=payload, headers=headers) as response:
                try:
                    data = await response.json(content_type=None)
                except Exception:
                    text = (await response.text())[:500]
                    data = {"message": text or "Non-JSON response"}
                self._save_cookies()
                if not isinstance(data, dict):
                    raise ScooterApiError("Scooter Inu API returned an unexpected response.", status=response.status)
                if response.status >= 400:
                    retry_after = response.headers.get("Retry-After")
                    try:
                        retry_value = float(retry_after) if retry_after else None
                    except ValueError:
                        retry_value = None
                    message = data.get("message") or data.get("error") or f"HTTP {response.status}"
                    raise ScooterApiError(str(message), status=response.status, retry_after=retry_value)
                return data
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise ScooterApiError(f"Could not reach Scooter Inu: {type(exc).__name__}: {exc}") from exc

    async def begin_run(self) -> dict[str, Any]:
        result = await self._request("/api/leaderboard/run")
        token = result.get("token")
        seed = result.get("seed")
        if not isinstance(token, str) or not token:
            raise ScooterApiError("Run endpoint did not return a token.")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 0xFFFFFFFF:
            raise ScooterApiError("Run endpoint did not return a valid 32-bit seed.")
        return {"token": token, "seed": seed}

    async def submit_score(
        self, token: str, events: list[dict[str, int]], score: int, name: str
    ) -> dict[str, Any]:
        # The website first submits a completed score without a name. If this
        # device has not claimed one yet, it repeats the exact run with `name`.
        run = {"token": token, "events": events, "score": score}
        result = await self._request("/api/leaderboard/score", run)
        if result.get("reason") == "needs-name":
            result = await self._request("/api/leaderboard/score", {**run, "name": name})
        if result.get("ok") is not True:
            reason = result.get("message") or result.get("reason") or "Score was not accepted."
            raise ScooterApiError(str(reason))
        return result

    async def leaderboard(self) -> dict[str, Any]:
        # Match the website's read-only leaderboard GET without creating a run.
        async with self.session.get(
            f"{self.base_url}/api/leaderboard",
            headers={"Accept": "application/json", "Origin": self.origin, "Referer": f"{self.origin}/#game"},
        ) as response:
            try:
                data = await response.json(content_type=None)
            except Exception as exc:
                raise ScooterApiError("Leaderboard endpoint returned invalid JSON.") from exc
            if response.status >= 400 or not isinstance(data, dict):
                raise ScooterApiError(f"Leaderboard request failed with HTTP {response.status}.", status=response.status)
            self._save_cookies()
            return data
