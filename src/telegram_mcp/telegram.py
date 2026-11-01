import logging

import httpx

# httpx logs full request URLs at INFO, and the URL contains the bot token
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramError(Exception):
    pass


async def call(token: str, method: str, data=None, files=None, client: httpx.AsyncClient | None = None) -> dict:
    """Call a Bot API method. Errors never include the URL, so the token cannot leak."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=60)
    try:
        r = await client.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files)
        body = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise TelegramError(f"request failed: {type(e).__name__}") from None
    finally:
        if own:
            await client.aclose()
    if not body.get("ok"):
        raise TelegramError(f"Telegram error {body.get('error_code')}: {body.get('description')}")
    return body["result"]
