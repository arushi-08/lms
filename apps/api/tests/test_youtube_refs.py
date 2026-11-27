"""Parsing whatever an admin pasted into a YouTube id.

This value ends up in an ``<iframe src>``, so the tests lean on rejection at
least as hard as on acceptance. The accepted shapes are the ones people
actually paste; the rejected ones are the ways that goes wrong.
"""

from __future__ import annotations

import pytest

from app.domain.youtube import InvalidYouTubeReference, extract_video_id, watch_url

#: A syntactically valid id. Not a real video, deliberately.
ID = "dQw4w9WgXcQ"


class TestAcceptedShapes:
    @pytest.mark.parametrize(
        "pasted",
        [
            ID,
            f"https://www.youtube.com/watch?v={ID}",
            f"http://www.youtube.com/watch?v={ID}",
            f"https://youtube.com/watch?v={ID}",
            f"https://m.youtube.com/watch?v={ID}",
            f"https://music.youtube.com/watch?v={ID}",
            f"https://youtu.be/{ID}",
            f"youtu.be/{ID}",
            f"www.youtube.com/watch?v={ID}",
            f"https://www.youtube.com/embed/{ID}",
            f"https://www.youtube-nocookie.com/embed/{ID}",
            f"https://www.youtube.com/shorts/{ID}",
            f"https://www.youtube.com/live/{ID}",
            f"https://www.youtube.com/v/{ID}",
            # Extra parameters are the normal case, not the exception: the
            # share button adds a timestamp, and copying from a playlist adds
            # the list.
            f"https://www.youtube.com/watch?v={ID}&t=42s",
            f"https://www.youtube.com/watch?v={ID}&list=PLabc&index=2",
            f"https://youtu.be/{ID}?t=42",
            f"https://www.youtube.com/watch?app=desktop&v={ID}",
            # Whitespace from a copy-paste.
            f"  https://youtu.be/{ID}  ",
        ],
    )
    def test_the_id_comes_out(self, pasted: str) -> None:
        assert extract_video_id(pasted) == ID


class TestRejectedShapes:
    @pytest.mark.parametrize(
        ("pasted", "why"),
        [
            ("", "empty"),
            ("   ", "whitespace only"),
            ("not a url at all", "prose"),
            ("https://vimeo.com/123456789", "a different host"),
            ("https://example.com/watch?v=" + ID, "the right shape, wrong host"),
            # The lookalike that matters: a host ending in youtube.com is not
            # youtube.com. This is how an allowlist beats a `.endswith()`.
            ("https://notyoutube.com/watch?v=" + ID, "a lookalike host"),
            ("https://youtube.com.evil.test/watch?v=" + ID, "a suffixed host"),
            ("https://www.youtube.com/@somechannel", "a channel page"),
            ("https://www.youtube.com/playlist?list=PLabc", "a playlist, no video"),
            ("https://www.youtube.com/watch", "a watch URL with no id"),
            ("https://www.youtube.com/watch?v=", "an empty id"),
            ("https://www.youtube.com/watch?v=tooshort", "an id of the wrong length"),
            (f"https://www.youtube.com/watch?v={ID}X", "twelve characters"),
            ("https://www.youtube.com/watch?v=abcdefghij.", "an illegal character"),
            ("https://www.youtube.com/embed/", "an embed URL with no id"),
            # Scheme games. The value reaches an iframe src, so neither of
            # these should ever be mistaken for a video.
            (f"javascript:alert(1)//youtu.be/{ID}", "a script URL"),
            (f"data:text/html,<iframe src=youtu.be/{ID}>", "a data URL"),
            (f"file:///etc/passwd#{ID}", "a file URL"),
        ],
    )
    def test_it_is_refused(self, pasted: str, why: str) -> None:
        with pytest.raises(InvalidYouTubeReference):
            extract_video_id(pasted)

    def test_an_id_embedded_in_a_longer_string_is_not_accepted(self) -> None:
        """Anchored matching, not "contains". The id is interpolated into a
        URL, so a string that merely holds a valid id is not a valid id."""
        with pytest.raises(InvalidYouTubeReference):
            extract_video_id(f'{ID}" onload="alert(1)')


class TestWatchUrl:
    def test_it_builds_the_canonical_link(self) -> None:
        assert watch_url(ID) == f"https://www.youtube.com/watch?v={ID}"

    def test_it_refuses_to_build_a_url_from_junk(self) -> None:
        """The admin panel links to this. A rejected id must not become an
        attacker-chosen href just because it got past an earlier check."""
        with pytest.raises(InvalidYouTubeReference):
            watch_url('x" onmouseover="alert(1)')
