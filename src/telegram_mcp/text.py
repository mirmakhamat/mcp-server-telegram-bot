MESSAGE_LIMIT = 4096
CAPTION_LIMIT = 1024
PARSE_MODES = ("MarkdownV2", "HTML")


def split_text(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Split on line boundaries into chunks of at most `limit` chars; ''.join(chunks) == text."""
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur:
        chunks.append(cur)
    return chunks


def clip_caption(caption: str | None) -> str | None:
    if caption and len(caption) > CAPTION_LIMIT:
        return caption[: CAPTION_LIMIT - 1] + "…"
    return caption
