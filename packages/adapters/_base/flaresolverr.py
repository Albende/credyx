"""FlareSolverr client — defeats Cloudflare/Akamai/PerimeterX bot challenges.

FlareSolverr runs a headless undetected Chromium that solves JS challenges and
returns the final HTML + cookies. Wire any adapter whose registry sits behind a
"checking your browser" wall through `fetch_html()`.

Endpoint:    FLARESOLVERR_URL  (default http://localhost:8191)
Container:   `docker run -d --name creditlens-flaresolverr -p 8191:8191
              ghcr.io/flaresolverr/flaresolverr:latest`
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")
DEFAULT_TIMEOUT_MS = int(os.getenv("FLARESOLVERR_TIMEOUT_MS", "60000"))


class FlareSolverrError(RuntimeError):
    pass


@dataclass
class FlareResponse:
    status: int
    url: str
    html: str
    cookies: list[dict]
    user_agent: str


class FlareSolverrClient:
    def __init__(self, base_url: str | None = None, *, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
        self.base_url = (base_url or DEFAULT_URL).rstrip("/")
        self.timeout_ms = timeout_ms

    async def fetch_html(
        self,
        url: str,
        *,
        method: str = "GET",
        post_data: str | None = None,
        cookies: list[dict] | None = None,
        session: str | None = None,
    ) -> FlareResponse:
        """Resolve a Cloudflare-protected page. Returns final HTML."""
        cmd = "request.post" if method.upper() == "POST" else "request.get"
        body: dict = {
            "cmd": cmd,
            "url": url,
            "maxTimeout": self.timeout_ms,
        }
        if post_data is not None:
            body["postData"] = post_data
        if cookies:
            body["cookies"] = cookies
        if session:
            body["session"] = session

        async with httpx.AsyncClient(timeout=self.timeout_ms / 1000 + 10) as client:
            resp = await client.post(f"{self.base_url}/v1", json=body)
            if resp.status_code != 200:
                raise FlareSolverrError(
                    f"FlareSolverr returned {resp.status_code}: {resp.text[:200]}"
                )
            payload = resp.json()
            if payload.get("status") != "ok":
                raise FlareSolverrError(
                    f"FlareSolverr challenge failed: {payload.get('message', 'unknown')}"
                )
            sol = payload["solution"]
            return FlareResponse(
                status=sol["status"],
                url=sol["url"],
                html=sol["response"],
                cookies=sol.get("cookies", []),
                user_agent=sol.get("userAgent", ""),
            )

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self.base_url + "/")
                return resp.status_code == 200 and "FlareSolverr" in resp.text
        except Exception:
            return False


_singleton: FlareSolverrClient | None = None


def get_flaresolverr_client() -> FlareSolverrClient:
    global _singleton
    if _singleton is None:
        _singleton = FlareSolverrClient()
    return _singleton
