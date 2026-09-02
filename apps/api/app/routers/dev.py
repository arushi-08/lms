"""Development-only endpoints.

Registered solely when the mock video provider is active, and Settings already
refuses to start production on the mock. The point is that the *frontend* upload
path is identical for the mock and for VdoCipher: get a ticket, POST the file to
the URL it names, poll for status. If the mock had no endpoint to receive the
file, the browser code would need a branch for it, and the branch that only runs
in development is the one that breaks in production.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/video-upload", status_code=status.HTTP_204_NO_CONTENT)
async def accept_mock_upload(
    video_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> None:
    """Accept and discard an upload, so the real flow can be exercised."""
    # Drain in chunks rather than read() so a large test file does not have to
    # fit in memory to be thrown away.
    while await file.read(1024 * 1024):
        pass
