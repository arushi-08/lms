"""Turning whatever an admin pasted into a YouTube video id.

Separate from the routes and from any provider because it is pure, it has no
database and no network, and it is the one place a string from outside reaches
an ``<iframe src>``. That makes it worth testing exhaustively and worth reading
carefully.

The rule is an allowlist: the id must be exactly eleven characters of
``[A-Za-z0-9_-]``, which is the shape YouTube has used for every video id, and
the host must be one YouTube actually serves from. Anything else is rejected
outright rather than cleaned up. A sanitiser that tries to rescue a malformed
input is a sanitiser someone will eventually find a way past; refusing is both
safer and more honest to the admin, who can see what they pasted.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

#: Eleven characters, URL-safe base64 alphabet. Anchored, so a longer string
#: containing a valid id is not accepted -- the id ends up in a URL, and
#: "contains something valid" is not the same as "is valid".
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: Hosts whose URLs carry a video id in a shape this module understands.
#: youtube-nocookie is included because it is what the player embeds from.
_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
    }
)

#: Path prefixes that are followed by the id: /embed/<id>, /shorts/<id>, …
_PATH_PREFIXES = ("embed", "shorts", "live", "v", "e")


class InvalidYouTubeReference(ValueError):
    """The pasted value is not a YouTube video this platform can embed."""


def extract_video_id(raw: str) -> str:
    """Return the 11-character id, or raise InvalidYouTubeReference.

    Accepts a bare id, a watch URL, a short youtu.be link, an embed URL, a
    Shorts link and a live link, with or without extra query parameters such as
    a timestamp or a playlist. Rejects everything else -- including other
    Google properties, a playlist with no video, and a channel page.
    """
    candidate = (raw or "").strip()
    if not candidate:
        raise InvalidYouTubeReference("no video given")

    # A bare id, which is what someone pasting from the admin panel's own
    # display will have.
    if VIDEO_ID.match(candidate):
        return candidate

    # Be forgiving about the scheme only. "youtu.be/abc" without one is a
    # normal thing to paste, and urlparse reads it as a path, not a host.
    if "//" not in candidate:
        candidate = f"https://{candidate}"

    try:
        url = urlparse(candidate)
    except ValueError as exc:
        raise InvalidYouTubeReference("that does not parse as a URL") from exc

    if url.scheme not in ("http", "https"):
        raise InvalidYouTubeReference("only http and https links are accepted")

    host = (url.hostname or "").lower()
    if host not in _HOSTS:
        raise InvalidYouTubeReference(
            "that is not a YouTube link. Paste the video URL or its id."
        )

    segments = [s for s in url.path.split("/") if s]

    # youtu.be/<id>
    if host == "youtu.be":
        found = segments[0] if segments else ""
    # /watch?v=<id>
    elif segments and segments[0] == "watch":
        found = (parse_qs(url.query).get("v") or [""])[0]
    # /embed/<id>, /shorts/<id>, /live/<id>, /v/<id>, /e/<id>
    elif len(segments) >= 2 and segments[0] in _PATH_PREFIXES:
        found = segments[1]
    # Bare youtube.com/<id> is not a thing -- that shape is a channel handle --
    # so it is not guessed at.
    else:
        raise InvalidYouTubeReference(
            "that YouTube link does not point at a single video"
        )

    if not VIDEO_ID.match(found):
        raise InvalidYouTubeReference(
            "that YouTube link does not contain a valid video id"
        )
    return found


def watch_url(video_id: str) -> str:
    """The canonical public URL, for the admin panel to link to."""
    if not VIDEO_ID.match(video_id):
        raise InvalidYouTubeReference("not a valid video id")
    return f"https://www.youtube.com/watch?v={video_id}"
