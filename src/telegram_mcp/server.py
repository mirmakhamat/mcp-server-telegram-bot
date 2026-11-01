import sys

from mcp.server.fastmcp import FastMCP

from . import security, telegram

mcp = FastMCP("telegram")
_cfg: security.Config | None = None


def cfg() -> security.Config:
    global _cfg
    if _cfg is None:
        _cfg = security.load_config()
    return _cfg


@mcp.tool()
async def send_message(text: str, chat_id: str | None = None) -> str:
    """Send a text message to an allowed Telegram chat."""
    c = cfg()
    r = await telegram.call(c.token, "sendMessage", {"chat_id": security.resolve_chat(c, chat_id), "text": text})
    return f"sent, message_id={r['message_id']}"


async def _send_file(method: str, field: str, path: str, caption: str | None, chat_id: str | None) -> str:
    c = cfg()
    chat = security.resolve_chat(c, chat_id)
    real = security.check_path(c, path)
    data = {"chat_id": chat, **({"caption": caption} if caption else {})}
    with open(real, "rb") as f:
        r = await telegram.call(c.token, method, data, {field: f})
    return f"sent, message_id={r['message_id']}"


@mcp.tool()
async def send_document(path: str, caption: str | None = None, chat_id: str | None = None) -> str:
    """Send a file from an allowed directory as a document."""
    return await _send_file("sendDocument", "document", path, caption, chat_id)


@mcp.tool()
async def send_photo(path: str, caption: str | None = None, chat_id: str | None = None) -> str:
    """Send an image from an allowed directory as a photo."""
    return await _send_file("sendPhoto", "photo", path, caption, chat_id)


@mcp.tool()
async def get_updates(limit: int = 10) -> list[dict]:
    """List recent messages sent to the bot (shows chat ids; helps first-time setup)."""
    r = await telegram.call(cfg().token, "getUpdates", {"limit": limit})
    return [
        {"chat_id": m["chat"]["id"], "from": m.get("from", {}).get("first_name"), "text": (m.get("text") or "")[:200]}
        for u in r
        if (m := u.get("message"))
    ]


def main() -> None:
    try:
        cfg()
    except security.ConfigError as e:
        sys.exit(f"telegram-mcp: {e}")
    mcp.run()


if __name__ == "__main__":
    main()
