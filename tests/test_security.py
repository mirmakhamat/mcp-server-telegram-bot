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
    real = security.check_path(c, str(f))
    assert real == str(f.resolve()) and security.is_inside(c, real)
    sub = tmp_path / "sub"
    sub.mkdir()
    out = security.check_path(c, str(sub / ".." / "a.txt"))
    assert security.is_inside(c, out)
    outside = tmp_path.parent / "elsewhere.txt"
    outside.write_text("x")
    assert not security.is_inside(c, security.check_path(c, str(sub / ".." / ".." / "elsewhere.txt")))


def test_symlink_escape(tmp_path):
    allowed = tmp_path / "ok"
    allowed.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    link = allowed / "link.txt"
    os.symlink(secret, link)
    c = cfg(allowed)
    assert not security.is_inside(c, security.check_path(c, str(link)))  # resolves outside, so it must ask


def test_symlink_to_protected_is_refused(tmp_path):
    key = tmp_path / ".ssh"
    key.mkdir()
    (key / "id").write_text("x")
    link = tmp_path / "innocent.txt"
    os.symlink(key / "id", link)
    with pytest.raises(security.DeniedError):
        security.check_path(cfg(tmp_path), str(link))


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


def test_session_dir_auto_allowed(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    f = work / "r.txt"
    f.write_text("x")
    env = {"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1"}
    c = security.load_config(env, cwd=str(work))
    assert security.is_inside(c, security.check_path(c, str(f)))
    other = tmp_path / "other.txt"
    other.write_text("x")
    assert not security.is_inside(c, security.check_path(c, str(other)))


def test_home_or_root_session_is_not_auto_allowed(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    env = {"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1"}
    assert security.load_config(env, cwd=str(tmp_path)).session_dir == ""
    assert security.load_config(env, cwd="/").session_dir == ""


def test_blocked_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = security.load_config(
        {"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1", "DENY_PATHS": str(tmp_path / "mine")}, cwd=str(tmp_path / "w")
    )
    for rel in (".claude/x.json", ".config/gcloud/k", ".git/config", "a/id_rsa", "a/b.pem", "a/.env.local", "mine/f", ".aws/credentials"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
        with pytest.raises(security.DeniedError):
            security.check_path(c, str(p))
    with pytest.raises(security.DeniedError):
        security.check_path(c, "/etc/hostname")
    ok = tmp_path / "w" / "notes.md"
    ok.parent.mkdir()
    ok.write_text("x")
    assert security.check_path(c, str(ok))


def test_bad_access_mode():
    with pytest.raises(security.ConfigError):
        security.load_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1", "ACCESS_MODE": "open"})


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


def test_extra_merge_and_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "s" / "state.json"))
    from telegram_mcp import server

    server._base = cfg(tmp_path)
    d = tmp_path / "more"
    d.mkdir()
    assert server._edit("chats", "7", True) == "7"
    assert server._edit("dirs", str(d), True) == str(d)
    c = server.cfg()
    assert "7" in c.chat_ids and str(d) in c.dirs
    server._edit("chats", "7", False)
    assert "7" not in server.cfg().chat_ids
    with pytest.raises(security.DeniedError):
        server._edit("chats", "1", False)  # env entry cannot be removed
    for bad in ("/", os.path.expanduser("~"), str(tmp_path / "nope")):
        with pytest.raises(security.DeniedError):
            security.validate_dir(server.cfg(), bad)
    with pytest.raises(security.DeniedError):
        security.validate_chat("abc")


def test_approve_fails_closed():
    from types import SimpleNamespace as NS

    from telegram_mcp import server

    class Ctx:
        def __init__(self, r=None, exc=None):
            self.r, self.exc = r, exc

        async def elicit(self, *a):
            if self.exc:
                raise self.exc
            return self.r

    ok = NS(action="accept", data=NS(confirm=True))
    asyncio.run(server._approve(Ctx(ok), "x"))
    for ctx in (Ctx(NS(action="decline", data=None)), Ctx(NS(action="accept", data=NS(confirm=False))), Ctx(exc=RuntimeError())):
        with pytest.raises(security.DeniedError):
            asyncio.run(server._approve(ctx, "x"))


def test_chat_names(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "state.json"))
    from telegram_mcp import server

    server._base = security.load_config(
        {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_CHAT_IDS": "me=1,2", "ALLOWED_DIRS": ""}
    )
    server._edit("chats", "ali=77", True)
    c = server.cfg()
    assert security.resolve_chat(c, "Ali") == "77"
    assert security.resolve_chat(c, "me") == "1"
    assert security.resolve_chat(c, None) == "1"
    assert server.remove_chat("ali") == "removed chat ali=77"
    with pytest.raises(security.DeniedError):
        security.resolve_chat(server.cfg(), "ali")
    with pytest.raises(security.DeniedError):
        server.remove_chat("me")
    with pytest.raises(security.DeniedError):
        security.validate_name("a b=c")


def test_pdf_render_unicode_and_limits():
    from telegram_mcp import pdf

    out = pdf.render("# Sarlavha\nOʻzbekcha: gʻoya, ўзбек, қ\n- band\n" + "x" * 500, title="Hisobot")
    assert out.startswith(b"%PDF")
    with pytest.raises(ValueError):
        pdf.render("x" * (pdf.MAX_CHARS + 1))


def test_send_generated(tmp_path, monkeypatch):
    from telegram_mcp import server

    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("TELEGRAM_MCP_LOG", str(tmp_path / "sent.log"))
    server._base = cfg(tmp_path)
    seen = {}

    async def fake(token, method, data=None, files=None, client=None):
        seen.update(method=method, data=data, files=files)
        return {"message_id": 5}

    monkeypatch.setattr(server.telegram, "call", fake)
    r = asyncio.run(server.send_generated("../../My Report!", "# Hi", "md", chat_id="2"))
    assert r == "sent My_Report.md, message_id=5"
    assert seen["data"]["chat_id"] == "2" and seen["files"]["document"][0] == "My_Report.md"
    asyncio.run(server.send_generated("r", "# Hi", "pdf"))
    assert seen["files"]["document"][1].startswith(b"%PDF")
    with pytest.raises(ValueError):
        asyncio.run(server.send_generated("r", "x", "exe"))
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_generated("r", "x", "md", chat_id="999"))
    assert "generated=My_Report.md" in (tmp_path / "sent.log").read_text()


def test_send_file_tiers(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    from telegram_mcp import server

    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("TELEGRAM_MCP_LOG", str(tmp_path / "sent.log"))
    work = tmp_path / "work"
    work.mkdir()
    (work / "in.txt").write_text("x")
    (tmp_path / "out.txt").write_text("x")
    sent = []

    async def fake(token, method, data=None, files=None, client=None):
        sent.append(method)
        return {"message_id": 1}

    monkeypatch.setattr(server.telegram, "call", fake)

    class Ctx:
        def __init__(self, yes):
            self.yes, self.asked = yes, 0

        async def elicit(self, *a):
            self.asked += 1
            return NS(action="accept", data=NS(confirm=self.yes))

    def run(mode, path, ctx):
        env = {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_CHAT_IDS": "1", "ACCESS_MODE": mode}
        server._base = security.load_config(env, cwd=str(work))
        return asyncio.run(server.send_document(ctx, str(path)))

    c = Ctx(True)
    run("ask", work / "in.txt", c)
    assert c.asked == 0  # inside session dir: no prompt
    run("ask", tmp_path / "out.txt", c)
    assert c.asked == 1  # outside: asked, approved
    with pytest.raises(security.DeniedError):
        run("ask", tmp_path / "out.txt", Ctx(False))
    with pytest.raises(security.DeniedError):
        run("strict", tmp_path / "out.txt", Ctx(True))
    assert len(sent) == 2
