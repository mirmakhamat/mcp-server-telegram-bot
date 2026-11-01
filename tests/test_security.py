import asyncio
import os

import httpx
import pytest

from telegram_mcp import security, telegram

TOKEN = "123456:secret-token"


def cfg(tmp_path, chats=("1", "2")):
    return security.load_config(
        {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_CHAT_IDS": ",".join(chats), "ALLOWED_DIRS": str(tmp_path)}
    )


def test_missing_env():
    with pytest.raises(security.ConfigError):
        security.load_config({"ALLOWED_CHAT_IDS": "1"})
    with pytest.raises(security.ConfigError):
        security.load_config({"TELEGRAM_BOT_TOKEN": "x"})


def test_chat(tmp_path):
    c = cfg(tmp_path)
    assert security.resolve_chat(c, None) == "1"
    assert security.resolve_chat(c, 2) == "2"
    with pytest.raises(security.DeniedError):
        security.resolve_chat(c, "999")


def test_path_ok_and_traversal(tmp_path):
    c = cfg(tmp_path)
    f = tmp_path / "a.txt"
    f.write_text("hi")
    assert security.check_path(c, str(f)) == str(f.resolve())
    with pytest.raises(security.DeniedError):
        security.check_path(c, str(tmp_path / ".." / "a.txt"))


def test_symlink_escape(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    link = allowed / "link.txt"
    os.symlink(secret, link)
    with pytest.raises(security.DeniedError):
        security.check_path(cfg(allowed), str(link))


def test_protected_and_size(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    (tmp_path / ".env").write_text("x")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id").write_text("x")
    for p in (tmp_path / ".env", tmp_path / ".ssh" / "id"):
        with pytest.raises(security.DeniedError):
            security.check_path(c, str(p))
    big = tmp_path / "big.bin"
    big.write_text("x")
    monkeypatch.setattr(security, "MAX_BYTES", 0)
    with pytest.raises(security.DeniedError):
        security.check_path(c, str(big))


def test_no_dirs_disables_files(tmp_path):
    c = security.load_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1"})
    with pytest.raises(security.DeniedError):
        security.check_path(c, str(tmp_path))


def test_error_hides_token():
    def boom(request):
        raise httpx.ConnectError("fail " + str(request.url))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as cl:
            await telegram.call(TOKEN, "sendMessage", client=cl)

    with pytest.raises(telegram.TelegramError) as e:
        asyncio.run(run())
    assert "secret-token" not in str(e.value)


def test_httpx_logger_silenced():
    import logging

    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
