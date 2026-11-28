#!/usr/bin/env python3
"""First contact with VdoCipher: does the account work, and what does the CSP need?

`VdoCipherProvider` has been unit-tested against a fake HTTP layer since the day
it was written and has never spoken to VdoCipher. This runs the real code
against the real API, outside the app, so the first thing that talks to a new
account is twenty lines of script rather than a student pressing play.

It also answers the question the browser cannot ask on our behalf. The admin's
browser uploads a file straight to a URL VdoCipher mints per upload, by XHR,
which Content-Security-Policy's connect-src governs. That host is not knowable
in advance and is not in the policy, so the first real upload is refused by the
browser before it is sent -- and a CSP refusal and a dead network look
identical from JavaScript. `--upload-host` asks VdoCipher for a ticket and
prints the line to paste into apps/web/csp.mjs, which turns an evening of
confusion into one command.

    export VDOCIPHER_API_SECRET=<the secret from the VdoCipher dashboard>

    python3 scripts/check_vdocipher.py                 # read-only
    python3 scripts/check_vdocipher.py --upload-host   # also probes an upload URL

Read-only by default. `--upload-host` creates an empty placeholder video to get
a ticket and deletes it again; if the delete fails it tells you the id so you
can remove it by hand.
"""

from __future__ import annotations

import asyncio
import os
import sys
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "apps", "api"))

try:
    from app.providers.video.base import VideoProviderError
    from app.providers.video.vdocipher import VdoCipherProvider
except ImportError:
    sys.exit(
        "Run this with the API's virtualenv active:\n"
        "  cd apps/api && . .venv/bin/activate && "
        "python ../../scripts/check_vdocipher.py"
    )

#: Matches the default in app/config.py. Override if VdoCipher moves it.
BASE_URL = os.environ.get("VDOCIPHER_API_BASE", "https://dev.vdocipher.com/api")


async def main(probe_upload: bool) -> int:
    secret = os.environ.get("VDOCIPHER_API_SECRET", "").strip()
    if not secret:
        print(
            "set VDOCIPHER_API_SECRET (VdoCipher dashboard -> Config -> API Credentials)",
            file=sys.stderr,
        )
        return 2

    provider = VdoCipherProvider(secret, base_url=BASE_URL)
    print(f"api base   {BASE_URL}")
    print(f"secret     {secret[:4]}…{secret[-4:]} ({len(secret)} chars)")

    # 1. Does the credential work at all? get_status on an id that cannot exist
    #    separates "the account rejects us" from "no such video": the first is a
    #    401/403, the second a 404, and the provider reports the status.
    print("\n[1/2] authenticating…")
    try:
        await provider.get_status("000000000000000000000000000000ff")
        print("      ok -- the API answered (and claims that video exists, oddly)")
    except VideoProviderError as exc:
        message = str(exc)
        if "401" in message or "403" in message:
            print(f"      FAILED: {message}")
            print("      The secret is wrong, or it is not an API secret.")
            print("      VdoCipher dashboard -> Config -> API Credentials.")
            return 1
        if "404" in message:
            print("      ok -- authenticated (404 for a video that does not exist)")
        elif "request failed" in message:
            # The provider says "request failed: <ExceptionName>" only when the
            # request never completed. Blaming the URL here would be wrong: the
            # usual causes are no outbound network, a proxy, or DNS.
            print(f"      FAILED: {message}")
            print("      The request did not reach VdoCipher at all -- check network,")
            print(f"      proxy and DNS for {urlparse(BASE_URL).netloc}.")
            return 1
        else:
            print(f"      FAILED: {message}")
            print(f"      Unexpected status. Check the API base URL is right: {BASE_URL}")
            return 1

    if not probe_upload:
        print("\nRead-only run. Add --upload-host to find the host the CSP needs.")
        return 0

    # 2. Mint a ticket, purely to see where the browser would be told to POST.
    print("\n[2/2] requesting an upload ticket…")
    video_id = None
    try:
        ticket = await provider.create_upload("csp-probe (safe to delete)")
        video_id = ticket.video_id
        origin = urlparse(ticket.upload_url).scheme + "://" + urlparse(ticket.upload_url).netloc
        print(f"      video id     {video_id}")
        print(f"      upload URL   {ticket.upload_url}")
        print(f"      fields       {', '.join(sorted(ticket.upload_fields)) or '(none)'}")
        print(f"\n      upload origin: {origin}")
        print("\nAdd this to apps/web/csp.mjs, in VDOCIPHER_UPLOAD_HOSTS:")
        print(f'\n    export const VDOCIPHER_UPLOAD_HOSTS = ["{origin}"];\n')
        print(
            "If the host varies per upload -- run this twice to find out -- use the\n"
            "wildcard form its parent allows, e.g. https://*.example-cdn.com, rather\n"
            "than pinning one bucket."
        )
    except VideoProviderError as exc:
        print(f"      FAILED: {exc}")
        return 1
    finally:
        if video_id:
            try:
                await provider.delete(video_id)
                print(f"\n(placeholder {video_id} deleted)")
            except VideoProviderError as exc:
                print(
                    f"\n(could not delete placeholder {video_id}: {exc} -- "
                    "remove it in the VdoCipher dashboard)"
                )
    return 0


if __name__ == "__main__":
    flags = set(sys.argv[1:])
    unknown = flags - {"--upload-host"}
    if unknown:
        sys.exit(f"unknown option(s): {', '.join(sorted(unknown))}\n\n{__doc__}")
    raise SystemExit(asyncio.run(main("--upload-host" in flags)))
