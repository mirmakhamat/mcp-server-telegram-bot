import os
import re
import sys
from datetime import datetime

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from . import pdf, security, telegram, text as txt

FORMATS = ("pdf", "md", "txt", "csv", "json")
mcp = FastMCP("telegram")
_base: security.Config | None = None


def base() -> security.Config:
    global _base
    if _base is None:
        _base = security.load_config()
    return _base


def cfg() -> security.Config:
    return security.merge(base(), security.load_extra(security.state_path()))


def _data(chat: str, caption: str | None = None) -> dict:
    caption = txt.clip_caption(caption)
    return {"chat_id": chat, **({"caption": caption} if caption else {})}


@mcp.tool()
async def send_message(text: str, chat_id: str | None = None, parse_mode: str | None = None) -> str:
    """Send a text message; long text is split into several messages. chat_id is an allowed id or name
    (see list_access); omitted = default chat. parse_mode (MarkdownV2 or HTML) applies only when the text fits one message."""
    if not text.strip():
        raise ValueError("text is empty")
    if parse_mode not in (None, *txt.PARSE_MODES):
        raise ValueError(f"parse_mode must be one of: {', '.join(txt.PARSE_MODES)}")
    c = cfg()
    chat = security.resolve_chat(c, chat_id)
    chunks = txt.split_text(text)
    ids = []
    for chunk in chunks:
        extra = {"parse_mode": parse_mode} if parse_mode and len(chunks) == 1 else {}
        r = await telegram.call(c.token, "sendMessage", {"chat_id": chat, "text": chunk, **extra})
        ids.append(r["message_id"])
    _log(chat, f"message chars={len(text)} parts={len(ids)}")
    return f"sent {len(ids)} message(s), message_id={ids[-1]}"


def _log(chat: str, what: str) -> None:
    """Append-only record of what was sent where. Never stores file contents."""
    path = os.path.expanduser(os.environ.get("TELEGRAM_MCP_LOG", "~/.local/state/telegram-mcp/sent.log"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\tchat={chat}\t{what}\n")
    except OSError:
        pass  # logging must never block a send


async def _send_file(ctx: Context, method: str, field: str, path: str, caption: str | None, chat_id: str | None) -> str:
    c = cfg()
    chat = security.resolve_chat(c, chat_id)
    real = security.check_path(c, path)
    if not security.is_inside(c, real):
        if c.mode == "strict":
            raise security.DeniedError("file is outside the session directory and ALLOWED_DIRS (ACCESS_MODE=strict)")
        await _approve(ctx, f"send {real} to chat {chat}")
    data = _data(chat, caption)
    with open(real, "rb") as f:
        r = await telegram.call(c.token, method, data, {field: f})
    _log(chat, f"file={real}")
    return f"sent, message_id={r['message_id']}"


@mcp.tool()
async def send_document(ctx: Context, path: str, caption: str | None = None, chat_id: str | None = None) -> str:
    """Send an existing file. Files in the session directory send directly; elsewhere the user is asked. Secrets (.ssh, .env, keys) are always refused."""
    return await _send_file(ctx, "sendDocument", "document", path, caption, chat_id)


@mcp.tool()
async def send_photo(ctx: Context, path: str, caption: str | None = None, chat_id: str | None = None) -> str:
    """Send an existing image as a photo. Same access rules as send_document."""
    return await _send_file(ctx, "sendPhoto", "photo", path, caption, chat_id)


@mcp.tool()
async def send_generated(
    name: str, content: str, format: str = "pdf", caption: str | None = None, chat_id: str | None = None
) -> str:
    """Create a file from text and send it; reads nothing from disk. format: pdf, md, txt, csv, json.
    For a pdf, '# ' / '## ' lines are headings and '- ' lines are bullets. Use it for reports, summaries, logs, tables."""
    if format not in FORMATS:
        raise ValueError(f"format must be one of: {', '.join(FORMATS)}")
    c = cfg()
    chat = security.resolve_chat(c, chat_id)
    stem = re.sub(r"[^\w.-]+", "_", os.path.splitext(os.path.basename(name))[0]).strip("._") or "file"
    filename = f"{stem}.{format}"
    body = pdf.render(content, title=name if format == "pdf" else None) if format == "pdf" else content.encode()
    if len(body) > security.MAX_BYTES:
        raise security.DeniedError("file is larger than 50 MB")
    data = _data(chat, caption)
    r = await telegram.call(c.token, "sendDocument", data, {"document": (filename, body)})
    _log(chat, f"generated={filename} bytes={len(body)}")
    return f"sent {filename}, message_id={r['message_id']}"


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
        r = await ctx.elicit(f"Allow mcp-server-telegram-bot to {what}?", Confirm)
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
    """Show allowed chats (id and name) and directories. Use names as chat_id when sending."""
    extra = security.load_extra(security.state_path())
    c = cfg()
    by_id = {v: k for k, v in c.names.items()}
    return {
        "chats": [{"id": i, "name": by_id.get(i)} for i in c.chat_ids],
        "dirs": list(c.dirs),
        "added_at_runtime": extra,
    }


@mcp.tool()
async def add_chat(chat_id: str, ctx: Context, name: str | None = None) -> str:
    """Allow another chat id, optionally with a name (e.g. "ali") usable as chat_id later. Asks the user to confirm."""
    cid = security.validate_chat(chat_id)
    entry = f"{security.validate_name(name)}={cid}" if name else cid
    await _approve(ctx, f"send messages to chat {entry}")
    _edit("chats", entry, True)
    return f"added chat {entry}"


@mcp.tool()
async def add_dir(path: str, ctx: Context) -> str:
    """Allow files from another directory (asks the user to confirm)."""
    real = security.validate_dir(cfg(), path)
    await _approve(ctx, f"send files from {real}")
    return f"added dir {_edit('dirs', real, True)}"


@mcp.tool()
def remove_chat(chat: str) -> str:
    """Remove a chat (id or name) that was added at runtime."""
    for e in security.load_extra(security.state_path())["chats"]:
        name, cid = security.parse_chat(e)
        if chat.strip() in (cid, name):
            _edit("chats", e, False)
            return f"removed chat {e}"
    raise security.DeniedError("not a runtime-added entry (env entries are changed in the environment)")


@mcp.tool()
def remove_dir(path: str) -> str:
    """Remove a directory that was added at runtime."""
    return f"removed dir {_edit('dirs', security.validate_dir(cfg(), path), False)}"


def main() -> None:
    try:
        base()
    except security.ConfigError as e:
        sys.exit(f"mcp-server-telegram-bot: {e}")
    mcp.run()


if __name__ == "__main__":
    main()
