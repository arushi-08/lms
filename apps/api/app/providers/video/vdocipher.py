"""VdoCipher implementation: DRM playback with a per-viewer watermark.

Two properties this file exists to guarantee:

1. The API secret never leaves the server. The browser receives only an OTP and
   a playbackInfo blob, both scoped to one video and expiring in minutes. No
   stream URL is ever produced on our side, so there is nothing to copy out of
   devtools or the page source.
2. Every grant is watermarked with the viewer's identity. DRM stops casual
   copying; it does not stop a camera pointed at a screen. The watermark is what
   makes a leak traceable to an account, which is the deterrent that actually
   works.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.providers.video.base import (
    PlaybackGrant,
    UploadTicket,
    VideoProviderError,
    Viewer,
)


def build_watermark(viewer: Viewer) -> str:
    """The annotation payload VdoCipher burns into the picture.

    Semi-transparent and moving, so it is legible in a recording but not
    obtrusive during honest viewing. Carries the email (identifies the account)
    and a short user-id prefix (survives an email change).
    """
    identity = f"{viewer.email} - {str(viewer.user_id)[:8]}"
    return json.dumps(
        [
            {
                "type": "rtext",
                "text": identity,
                "alpha": "0.55",
                "color": "0xFFFFFF",
                "size": "12",
                "interval": "8000",
            }
        ]
    )


class VdoCipherProvider:
    name = "vdocipher"

    def __init__(
        self,
        api_secret: str,
        *,
        base_url: str = "https://dev.vdocipher.com/api",
        otp_ttl_seconds: int = 300,
        watermark_enabled: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._secret = api_secret
        self._base = base_url.rstrip("/")
        self._ttl = otp_ttl_seconds
        self._watermark = watermark_enabled
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Apisecret {self._secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            if self._client is not None:
                response = await self._client.request(
                    method, url, headers=self._headers(), **kwargs
                )
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.request(
                        method, url, headers=self._headers(), **kwargs
                    )
        except httpx.HTTPError as exc:
            # Deliberately does not interpolate the exception's request headers.
            raise VideoProviderError(f"vdocipher request failed: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            # Body may echo request context, so only the status is surfaced.
            raise VideoProviderError(f"vdocipher returned HTTP {response.status_code}")

        payload: dict[str, Any] = response.json()
        return payload

    async def create_upload(self, title: str) -> UploadTicket:
        payload = await self._request("PUT", "/videos", params={"title": title})
        credentials = payload.get("clientPayload") or {}
        video_id = payload.get("videoId")
        upload_url = credentials.get("uploadLink")

        if not video_id or not upload_url:
            raise VideoProviderError("vdocipher upload response was missing required fields")

        fields = {
            key: str(credentials[key])
            for key in ("policy", "key", "x-amz-signature", "x-amz-algorithm",
                        "x-amz-date", "x-amz-credential", "success_action_status")
            if key in credentials
        }
        return UploadTicket(
            video_id=str(video_id), upload_url=str(upload_url), upload_fields=fields
        )

    async def issue_playback(self, video_id: str, viewer: Viewer) -> PlaybackGrant:
        body: dict[str, Any] = {"ttl": self._ttl}
        if self._watermark:
            body["annotate"] = build_watermark(viewer)

        payload = await self._request("POST", f"/videos/{video_id}/otp", json=body)
        otp = payload.get("otp")
        playback_info = payload.get("playbackInfo")

        if not otp or not playback_info:
            raise VideoProviderError("vdocipher otp response was missing required fields")

        return PlaybackGrant(
            video_id=video_id,
            otp=str(otp),
            playback_info=str(playback_info),
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl),
        )

    async def get_status(self, video_id: str) -> str:
        payload = await self._request("GET", f"/videos/{video_id}")
        return str(payload.get("status", "unknown")).lower()

    async def delete(self, video_id: str) -> None:
        await self._request("DELETE", "/videos", params={"videoIds": video_id})
