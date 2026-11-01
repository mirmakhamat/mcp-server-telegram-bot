import sys

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from . import security, telegram

mcp = FastMCP("telegram")
_base: security.Config | None = None


def base() -> security.Config:
    global _base
    if _base is None:
        _base = security.load_config()
    return _base


def cfg() -> security.Config:
    return security.merge(base(), security.load_extra(security.state_path()))


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


class Confirm(BaseModel):
    confirm: bool = False


async def _approve(ctx: Context, what: str) -> None:
    """Widening access needs a human yes. Fails closed if the client cannot ask."""
    try:
        r = await ctx.elicit(f"Allow telegram-mcp to {what}?", Confirm)
    except Exception:
        raise security.DeniedError("client cannot ask for confirmation; set it in the environment instead") from None
    if r.action != "accept" or not r.data.confirm:
        raise security.DeniedError("not approved")


def _edit(kind: str, value: str, add: bool) -> str:
    path = security.state_path()
    extra = security.load_extra(path)
    items = extra[kind]
    if add and value not in items:
        items.append(value)
    elif not add:
        if value not in items:
            raise security.DeniedError("not a runtime-added entry (env entries are changed in the environment)")
        items.remove(value)
    security.save_extra(path, extra)
    return value


@mcp.tool()
def list_access() -> dict:
    """Show allowed chat ids and directories."""
    extra = security.load_extra(security.state_path())
    c = cfg()
    return {"chat_ids": list(c.chat_ids), "dirs": list(c.dirs), "added_at_runtime": extra}


@mcp.tool()
async def add_chat(chat_id: str, ctx: Context) -> str:
    """Allow another chat id (asks the user to confirm)."""
    cid = security.validate_chat(chat_id)
    await _approve(ctx, f"send messages to chat {cid}")
    return f"added chat {_edit('chats', cid, True)}"


@mcp.tool()
async def add_dir(path: str, ctx: Context) -> str:
    """Allow files from another directory (asks the user to confirm)."""
    real = security.validate_dir(path)
    await _approve(ctx, f"send files from {real}")
    return f"added dir {_edit('dirs', real, True)}"


@mcp.tool()
def remove_chat(chat_id: str) -> str:
    """Remove a chat id that was added at runtime."""
    return f"removed chat {_edit('chats', security.validate_chat(chat_id), False)}"


@mcp.tool()
def remove_dir(path: str) -> str:
    """Remove a directory that was added at runtime."""
    return f"removed dir {_edit('dirs', security.validate_dir(path), False)}"


def main() -> None:
    try:
        base()
    except security.ConfigError as e:
        sys.exit(f"telegram-mcp: {e}")
    mcp.run()


if __name__ == "__main__":
    main()
