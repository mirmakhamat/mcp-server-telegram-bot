import asyncio
import logging

import httpx

# httpx logs full request URLs at INFO, and the URL contains the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramError(Exception):
    pass


MAX_RETRY_WAIT = 30  # seconds; a longer flood wait is reported instead of blocking the agent


async def call(token: str, method: str, data=None, files=None, client: httpx.AsyncClient | None = None) -> dict:
    """Call a Bot API method. Errors never include the URL, so the token cannot leak.
    On HTTP 429 it waits `retry_after` (when short) and retries once."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        for attempt in (1, 2):
            try:
                r = await client.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files)
                body = r.json()
            except (httpx.HTTPError, ValueError) as e:
                raise TelegramError(f"request failed: {type(e).__name__}") from None
            wait = (body.get("parameters") or {}).get("retry_after")
            if body.get("error_code") == 429 and attempt == 1 and wait is not None and wait <= MAX_RETRY_WAIT:
                for f in (files or {}).values():
                    if hasattr(f, "seek"):
                        f.seek(0)  # the upload was consumed by the first attempt
                await asyncio.sleep(wait)
                continue
            break
    finally:
        if own:
            await client.aclose()
    if not body.get("ok"):
        hint = f" (retry after {wait} s)" if wait else ""
        raise TelegramError(f"Telegram error {body.get('error_code')}: {body.get('description')}{hint}")
    return body["result"]
