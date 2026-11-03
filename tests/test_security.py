import asyncio
import io
import json
import sys
import time
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


def test_split_text():
    from telegram_mcp import text

    assert text.split_text("short") == ["short"]
    long = "\n".join(f"line {i} " + "x" * 50 for i in range(300))
    parts = text.split_text(long)
    assert len(parts) > 1 and all(len(p) <= text.MESSAGE_LIMIT for p in parts)
    assert "".join(parts) == long
    giant = "y" * 10000  # one line longer than the limit
    parts = text.split_text(giant)
    assert [len(p) for p in parts] == [4096, 4096, 1808] and "".join(parts) == giant
    assert text.split_text("") == []


def test_caption_clip():
    from telegram_mcp import text

    assert text.clip_caption(None) is None and text.clip_caption("ok") == "ok"
    assert len(text.clip_caption("z" * 2000)) == text.CAPTION_LIMIT


def test_send_message_split_and_parse_mode(tmp_path, monkeypatch):
    from telegram_mcp import server

    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("TELEGRAM_MCP_LOG", str(tmp_path / "sent.log"))
    server._base = cfg(tmp_path)
    calls = []

    async def fake(token, method, data=None, files=None, client=None):
        calls.append(data)
        return {"message_id": len(calls)}

    monkeypatch.setattr(server.telegram, "call", fake)
    assert asyncio.run(server.send_message("*hi*", parse_mode="MarkdownV2")) == "sent 1 message(s), message_id=1"
    assert calls[0]["parse_mode"] == "MarkdownV2"
    calls.clear()
    assert asyncio.run(server.send_message("a" * 9000, parse_mode="HTML")) == "sent 3 message(s), message_id=3"
    assert all("parse_mode" not in d for d in calls)  # split text goes out plain
    for bad in (dict(text="  "), dict(text="x", parse_mode="Markdown")):
        with pytest.raises(ValueError):
            asyncio.run(server.send_message(**bad))


FAKE_TG = "123456789:" + "A" * 35
SECRETS = [
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    FAKE_TG,
    "AKIAABCDEFGHIJKLMNOP",
    "ghp_" + "a" * 36,
    "sk-ant-" + "b" * 30,
    "xoxb-1234567890-abcdef",
    "AIza" + "c" * 35,
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk",
    "password = Sup3rS3cret!",
]
HARMLESS = ["password: required", "the token expires soon", "ssh keys live in ~/.ssh", "id 123456789 done", "sk-learn"]


def test_redact_find():
    from telegram_mcp import redact

    for s in SECRETS:
        assert redact.find(s), s
        assert s not in redact.redact(s) or "BEGIN" in s
    for s in HARMLESS:
        assert not redact.find(s), s
    assert redact.find("x mytoken y", ("mytoken",)) and "mytoken" not in redact.redact("x mytoken y", ("mytoken",))


def _server(tmp_path, monkeypatch, scan="block", extra_env=None):
    from telegram_mcp import server

    monkeypatch.setenv("TELEGRAM_MCP_STATE", str(tmp_path / "s.json"))
    monkeypatch.setenv("TELEGRAM_MCP_LOG", str(tmp_path / "sent.log"))
    server._sent_at.clear()
    server._base = security.load_config(
        {"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_CHAT_IDS": "1", "SECRET_SCAN": scan, **(extra_env or {})}, cwd=str(tmp_path)
    )
    sent = []

    async def fake(token, method, data=None, files=None, client=None):
        sent.append((method, data, files))
        return {"message_id": 1}

    monkeypatch.setattr(server.telegram, "call", fake)
    return server, sent


def test_scan_modes(tmp_path, monkeypatch):
    server, sent = _server(tmp_path, monkeypatch, "block")
    for tool, args in (
        (server.send_message, dict(text="key " + FAKE_TG)),
        (server.send_message, dict(text="own " + TOKEN)),
        (server.send_generated, dict(name="r", content="ghp_" + "a" * 36, format="md")),
    ):
        with pytest.raises(security.DeniedError) as e:
            asyncio.run(tool(**args))
        assert FAKE_TG not in str(e.value) and TOKEN not in str(e.value)
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_generated("r", "ok", "md", caption=FAKE_TG))
    assert sent == []
    server, sent = _server(tmp_path, monkeypatch, "redact")
    asyncio.run(server.send_message("key " + FAKE_TG))
    assert FAKE_TG not in sent[0][1]["text"] and "REDACTED" in sent[0][1]["text"]
    server, sent = _server(tmp_path, monkeypatch, "off")
    asyncio.run(server.send_message("key " + FAKE_TG))
    assert FAKE_TG in sent[0][1]["text"]


def test_scan_files(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch, "block")
    ctx = NS()
    bad, good, binary = tmp_path / "a.txt", tmp_path / "b.txt", tmp_path / "c.bin"
    bad.write_text("config\npassword = Sup3rS3cret!\n")
    good.write_text("just a report\n")
    binary.write_bytes(b"\xff\xfe" + FAKE_TG.encode() + b"\x00")
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_document(ctx, str(bad)))
    asyncio.run(server.send_document(ctx, str(good)))
    asyncio.run(server.send_document(ctx, str(binary)))  # binary is not scanned
    assert len(sent) == 2
    server, sent = _server(tmp_path, monkeypatch, "redact")
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_document(ctx, str(bad)))  # files cannot be masked


def test_bad_scan_mode():
    with pytest.raises(security.ConfigError):
        security.load_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1", "SECRET_SCAN": "maybe"})


def test_notify_cli(tmp_path, monkeypatch, capsys):
    server, sent = _server(tmp_path, monkeypatch, "block")
    assert server.notify_main(["Build", "done"]) == 0
    assert sent[-1][1]["text"] == "Build done"
    stop = json.dumps({"hook_event_name": "Stop", "cwd": "/some/project/"})
    assert server.notify_main(["--hook"], stop) == 0
    assert sent[-1][1]["text"] == "Task finished (project)"
    note = json.dumps({"hook_event_name": "Notification", "message": "Claude needs your permission"})
    assert server.notify_main(["--hook", "--silent"], note) == 0
    assert sent[-1][1]["text"] == "Claude needs your permission"
    assert sent[-1][1]["disable_notification"] is True
    assert server.notify_main(["--hook"], "not json") == 0  # bad hook input still notifies
    assert sent[-1][1]["text"] == "Claude Code: event"
    n = len(sent)
    for argv, err in ((["--chat", "999", "x"], "not in ALLOWED"), ([], "no text"), (["key " + FAKE_TG], "possible secret")):
        assert server.notify_main(argv) == 1
        assert err in capsys.readouterr().err
    assert len(sent) == n


def test_notify_dispatch_from_main(tmp_path, monkeypatch):
    server, sent = _server(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["prog", "notify", "hello"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    with pytest.raises(SystemExit) as e:
        server.main()
    assert e.value.code == 0 and sent[-1][1]["text"] == "hello"


class FakeTG:
    """Scripted Bot API: getUpdates pops one batch per call."""

    def __init__(self, batches=(), baseline=None):
        self.calls, self.batches, self.baseline, self.next_id = [], list(batches), baseline or [], 10

    async def __call__(self, token, method, data=None, files=None, client=None):
        self.calls.append((method, data))
        await asyncio.sleep(0.01)
        if method == "getUpdates":
            if data.get("offset") == -1:
                return self.baseline
            return self.batches.pop(0) if self.batches else []
        if method == "sendMessage":
            self.next_id += 1
            return {"message_id": self.next_id}
        return True

    def methods(self):
        return [m for m, _ in self.calls]


def cb(uid, data, msg=11, chat=1):
    return {"update_id": uid, "callback_query": {"id": f"cb{uid}", "data": data, "message": {"message_id": msg, "chat": {"id": chat}}}}


def msg(uid, text, chat=1, date=None):
    return {"update_id": uid, "message": {"text": text, "chat": {"id": chat}, "date": date or int(time.time()) + 5}}


def ask(tmp_path, monkeypatch, fake, options=("Yes", "No"), timeout=2, mode="block"):
    server, _ = _server(tmp_path, monkeypatch, mode)
    monkeypatch.setattr(server.telegram, "call", fake)
    return server, lambda: asyncio.run(server._ask(server.cfg(), "1", "Deploy?", list(options), timeout))


def test_ask_button(tmp_path, monkeypatch):
    fake = FakeTG([[cb(8, "9", msg=11), cb(9, "1", chat=555)], [cb(10, "1", msg=11)]], baseline=[{"update_id": 7}])
    _, run = ask(tmp_path, monkeypatch, fake)
    assert run() == "No"  # wrong message / wrong chat ignored
    polls = [d for m, d in fake.calls if m == "getUpdates"]
    assert polls[0]["offset"] == -1 and polls[1]["offset"] == 8  # starts after pre-existing updates
    assert "answerCallbackQuery" in fake.methods() and fake.methods()[-1] == "editMessageText"


def test_ask_free_text_and_stale(tmp_path, monkeypatch):
    fake = FakeTG([[msg(1, "old", date=1), msg(2, "elsewhere", chat=9), msg(3, "do X instead")]])
    _, run = ask(tmp_path, monkeypatch, fake, options=())
    assert run() == "do X instead"
    assert "reply_markup" not in fake.calls[1][1]


def test_ask_timeout_and_validation(tmp_path, monkeypatch):
    fake = FakeTG([[cb(1, "0", chat=555)]])
    server, run = ask(tmp_path, monkeypatch, fake, timeout=0.3)
    assert run().startswith("timeout:")
    assert fake.methods()[-1] == "editMessageText"
    for bad in ([""], ["a"] * 9, ["x" * 61]):
        with pytest.raises(ValueError):
            asyncio.run(server.ask_user("q", options=bad))
    with pytest.raises(security.DeniedError):
        asyncio.run(server.ask_user("leak " + FAKE_TG))


def test_ask_serialized(tmp_path, monkeypatch):
    fake = FakeTG([[cb(1, "0", msg=11)], [cb(2, "1", msg=12)]])
    server, _ = ask(tmp_path, monkeypatch, fake)

    async def both():
        return await asyncio.gather(
            server._ask(server.cfg(), "1", "A?", ["Yes", "No"], 2), server._ask(server.cfg(), "1", "B?", ["Yes", "No"], 2)
        )

    assert asyncio.run(both()) == ["Yes", "No"]
    sends = [i for i, m in enumerate(fake.methods()) if m == "sendMessage"]
    assert "editMessageText" in fake.methods()[sends[0] : sends[1]]  # second question waited for the first


def test_edit_message(tmp_path, monkeypatch):
    server, sent = _server(tmp_path, monkeypatch)
    assert asyncio.run(server.edit_message(7, "progress 70%", parse_mode="HTML")) == "edited message_id=7"
    method, data, _ = sent[-1]
    assert method == "editMessageText" and data == {"chat_id": "1", "message_id": 7, "text": "progress 70%", "parse_mode": "HTML"}
    for bad in (dict(text=" "), dict(text="x" * 4097), dict(text="x", parse_mode="Markdown")):
        with pytest.raises(ValueError):
            asyncio.run(server.edit_message(7, **bad))
    with pytest.raises(security.DeniedError):
        asyncio.run(server.edit_message(7, "x", chat_id="999"))
    with pytest.raises(security.DeniedError):
        asyncio.run(server.edit_message(7, "key " + FAKE_TG))


def test_rate_limit(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch, extra_env={"MAX_SENDS_PER_MINUTE": "3"})
    f = tmp_path / "a.txt"
    f.write_text("x")
    asyncio.run(server.send_message("1"))
    asyncio.run(server.send_document(NS(), str(f)))
    asyncio.run(server.send_generated("r", "x", "md"))
    for call in (lambda: server.send_message("4"), lambda: server.edit_message(1, "x"), lambda: server.ask_user("q")):
        with pytest.raises(security.DeniedError, match="rate limit"):
            asyncio.run(call())
    assert len(sent) == 3
    real = time.monotonic
    monkeypatch.setattr(server.time, "monotonic", lambda: real() + 61)
    asyncio.run(server.send_message("later"))  # window has passed
    assert len(sent) == 4


def test_rate_zero_means_unlimited_and_bad_value(tmp_path, monkeypatch):
    server, sent = _server(tmp_path, monkeypatch, extra_env={"MAX_SENDS_PER_MINUTE": "0"})
    for i in range(30):
        asyncio.run(server.send_message(str(i)))
    assert len(sent) == 30
    for bad in ("-1", "many"):
        with pytest.raises(security.ConfigError):
            security.load_config({"TELEGRAM_BOT_TOKEN": "x", "ALLOWED_CHAT_IDS": "1", "MAX_SENDS_PER_MINUTE": bad})


def test_silent_flag(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch)
    f = tmp_path / "a.txt"
    f.write_text("x")
    asyncio.run(server.send_message("q", silent=True))
    asyncio.run(server.send_document(NS(), str(f), silent=True))
    asyncio.run(server.send_generated("r", "x", "md", silent=True))
    asyncio.run(server.send_message("loud"))
    assert [d.get("disable_notification") for _, d, _ in sent] == [True, True, True, None]


def _tg_client(responses, seen):
    def handler(request):
        seen.append(request.content)
        status = responses.pop(0)
        return httpx.Response(200, json=status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_429_retry_rewinds_upload(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(telegram.asyncio, "sleep", fake_sleep)
    seen = []
    flood = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 3}}
    client = _tg_client([flood, {"ok": True, "result": {"message_id": 9}}], seen)
    r = asyncio.run(telegram.call(TOKEN, "sendDocument", {"chat_id": "1"}, {"document": io.BytesIO(b"PAYLOAD")}, client=client))
    assert r == {"message_id": 9} and sleeps == [3]
    assert len(seen) == 2 and b"PAYLOAD" in seen[0] and b"PAYLOAD" in seen[1]  # file re-sent from the start


def test_429_long_wait_and_second_flood_are_reported(monkeypatch):
    async def no_sleep(s):
        raise AssertionError("must not sleep")

    monkeypatch.setattr(telegram.asyncio, "sleep", no_sleep)
    long = {"ok": False, "error_code": 429, "description": "Too Many Requests", "parameters": {"retry_after": 500}}
    with pytest.raises(telegram.TelegramError, match="retry after 500 s"):
        asyncio.run(telegram.call(TOKEN, "sendMessage", client=_tg_client([long], [])))
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(telegram.asyncio, "sleep", fake_sleep)
    short = {**long, "parameters": {"retry_after": 1}}
    seen = []
    with pytest.raises(telegram.TelegramError, match="429"):
        asyncio.run(telegram.call(TOKEN, "sendMessage", client=_tg_client([short, short], seen)))
    assert len(seen) == 2 and sleeps == [1]  # retried once only


def test_video_audio_photo_fallback_and_thread(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch)
    f = tmp_path / "m.bin"
    f.write_bytes(b"data")
    asyncio.run(server.send_video(NS(), str(f), thread_id=5))
    asyncio.run(server.send_audio(NS(), str(f)))
    asyncio.run(server.send_photo(NS(), str(f)))
    assert [m for m, _, _ in sent] == ["sendVideo", "sendAudio", "sendPhoto"]
    assert [list(fl) for _, _, fl in sent] == [["video"], ["audio"], ["photo"]]
    assert sent[0][1]["message_thread_id"] == 5 and "message_thread_id" not in sent[1][1]
    monkeypatch.setattr(server, "PHOTO_MAX_BYTES", 2)
    asyncio.run(server.send_photo(NS(), str(f)))
    assert sent[-1][0] == "sendDocument" and list(sent[-1][2]) == ["document"]


def test_thread_id_everywhere(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch)
    f = tmp_path / "a.txt"
    f.write_text("x")
    asyncio.run(server.send_message("m", thread_id=3))
    asyncio.run(server.send_document(NS(), str(f), thread_id=3))
    asyncio.run(server.send_generated("r", "x", "md", thread_id=3))
    assert [d["message_thread_id"] for _, d, _ in sent] == [3, 3, 3]


def test_album(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch)
    files = []
    for n in "abc":
        p = tmp_path / f"{n}.jpg"
        p.write_bytes(b"img" + n.encode())
        files.append(str(p))

    async def album_ok(token, method, data=None, files=None, client=None):
        sent.append((method, data, files))
        return [{"message_id": i} for i in range(len(files))]

    monkeypatch.setattr(server.telegram, "call", album_ok)
    out = asyncio.run(server.send_album(NS(), files, caption="trip", silent=True, thread_id=2))
    assert out == "sent album of 3, message_ids=[0, 1, 2]"
    method, data, fl = sent[-1]
    media = json.loads(data["media"])
    assert method == "sendMediaGroup" and list(fl) == ["f0", "f1", "f2"]
    assert [m["media"] for m in media] == ["attach://f0", "attach://f1", "attach://f2"]
    assert media[0]["caption"] == "trip" and "caption" not in media[1] and media[0]["type"] == "photo"
    assert data["disable_notification"] is True and data["message_thread_id"] == 2
    for bad in (dict(paths=files[:1]), dict(paths=files * 4), dict(paths=files, kind="gif")):
        with pytest.raises(ValueError):
            asyncio.run(server.send_album(NS(), **bad))


def test_album_vetting_is_all_or_nothing(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch, "block")
    ok = tmp_path / "ok.jpg"
    ok.write_bytes(b"x")
    env = tmp_path / ".env"
    env.write_text("x")
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_album(NS(), [str(ok), str(env)]))  # one protected file blocks the whole album
    leaky = tmp_path / "n.txt"
    leaky.write_text("password = Sup3rS3cret!")
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_album(NS(), [str(ok), str(leaky)], kind="document"))
    assert sent == []


def test_album_asks_once_for_outside_files(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    server, sent = _server(tmp_path, monkeypatch)
    work = tmp_path / "work"
    work.mkdir()
    server._base = security.load_config({"TELEGRAM_BOT_TOKEN": TOKEN, "ALLOWED_CHAT_IDS": "1"}, cwd=str(work))
    inside = work / "i.jpg"
    inside.write_bytes(b"x")
    out1, out2 = tmp_path / "o1.jpg", tmp_path / "o2.jpg"
    out1.write_bytes(b"x")
    out2.write_bytes(b"x")

    class Ctx:
        asked = 0

        async def elicit(self, *a):
            Ctx.asked += 1
            return NS(action="accept", data=NS(confirm=True))

    async def album_ok(token, method, data=None, files=None, client=None):
        return [{"message_id": 1}, {"message_id": 2}, {"message_id": 3}]

    monkeypatch.setattr(server.telegram, "call", album_ok)
    asyncio.run(server.send_album(Ctx(), [str(inside), str(out1), str(out2)]))
    assert Ctx.asked == 1
    Ctx.asked = 0
    asyncio.run(server.send_album(Ctx(), [str(inside), str(inside)]))
    assert Ctx.asked == 0


def test_send_rich_message(tmp_path, monkeypatch):
    server, sent = _server(tmp_path, monkeypatch)
    md = "# Report\n| a | b |\n|:--|--:|\n| 1 | 2 |\n```python\nprint(1)\n```"
    assert asyncio.run(server.send_rich_message(md, silent=True, thread_id=4)) == "sent, message_id=1"
    method, data, _ = sent[-1]
    assert method == "sendRichMessage" and json.loads(data["rich_message"]) == {"markdown": md}
    assert data["chat_id"] == "1" and data["disable_notification"] is True and data["message_thread_id"] == 4
    for bad in ("  ", "x" * 32769, "see ![](https://evil.example/?k=1)", '<img src="https://evil.example">', "<tg-map lat='1' long='2'/>"):
        with pytest.raises(ValueError):
            asyncio.run(server.send_rich_message(bad))
    assert asyncio.run(server.send_rich_message("[link](https://example.com) and `code` and *it*")) == "sent, message_id=1"
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_rich_message("# t\nkey " + FAKE_TG))
    with pytest.raises(security.DeniedError):
        asyncio.run(server.send_rich_message("x", chat_id="999"))
    assert len(sent) == 2
