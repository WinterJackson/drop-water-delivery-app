"""`ETag` on safe reads, so an unchanged list costs ~150 bytes instead of 40 KB.

There was no `ETag`, no `If-None-Match` and no `304` anywhere in this codebase.
Every catalogue refresh, every order-list poll and every wallet check transferred
its whole payload again whether or not one byte of it had changed — and the
clients poll: eight `refetchInterval` sites across the three apps, plus a refetch
on every foreground.

That is a bandwidth problem everywhere and a *usability* problem here. Drop's
customers are on Kenyan mobile data: metered, frequently 3G or worse, and
frequently unstable. Two things follow, and the second matters more than the
first:

1. A repeat read stops costing anything measurable.
2. **A request that cannot fail large is a request that mostly succeeds.** A 40 KB
   response over a flaky cell is a transfer with time to be interrupted; a 304 is
   one packet. The screens that felt broken on a bad connection were mostly
   screens re-fetching data the device already had.

## What is excluded, and why it is excluded automatically

A response carrying a **presigned S3 URL** is never given an `ETag`. A presigned
URL embeds its own expiry, so the body is only valid for as long as the signature
is — and a `304` tells the client "what you have is still good", which for such a
body is a lie that surfaces fifteen minutes later as broken images with no error
anywhere. The check is on the rendered body rather than a list of route names, so
a new endpoint that returns a document URL is covered on the day it is written
rather than on the day somebody remembers this file.

Anything served from `/api/admin/` is also excluded: the console renders identity
documents and payout queues, and those are the screens where a stale-but-valid
answer is the wrong kind of correct.
"""

import hashlib
import logging
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

#: Marker of an AWS presigned URL in a rendered body. Cheap substring test on
#: bytes; no parsing, no decoding.
_PRESIGNED_MARKER = b"X-Amz-Signature"

#: Prefixes never given an ETag.
_EXCLUDED_PREFIXES = ("/api/admin/", "/metrics", "/health", "/ready")

#: Bodies larger than this are not hashed. Above it the hash costs more than the
#: saving is worth on the server side, and a payload that big is a paging defect
#: to fix rather than a transfer to optimise.
_MAX_HASHABLE_BYTES = 2 * 1024 * 1024


def _etag_for(body: bytes) -> str:
    """A weak validator. The body is semantically, not byte-for-byte, identical.

    Weak (`W/`) is the honest label: two renderings of the same rows may differ in
    key order or float formatting without meaning anything different, and a weak
    validator is exactly the one permitted for `If-None-Match` on a `GET`.
    """
    return f'W/"{hashlib.sha256(body).hexdigest()[:32]}"'


def _matches(header: str, etag: str) -> bool:
    """Is `etag` named in this `If-None-Match` header?

    `*` matches anything. Otherwise the header is a comma-separated list, and
    comparison is weak: `W/"abc"` and `"abc"` are the same validator for this
    purpose, so the prefix is stripped from both sides before comparing.
    """
    header = header.strip()
    if header == "*":
        return True
    candidates: Iterable[str] = (part.strip() for part in header.split(","))
    normalise = lambda tag: tag[2:] if tag.startswith("W/") else tag  # noqa: E731
    target = normalise(etag)
    return any(normalise(candidate) == target for candidate in candidates if candidate)


class ETagMiddleware(BaseHTTPMiddleware):
    """Adds `ETag` to safe reads and answers `304` when the client already has it.

    Must be registered **before** `GZipMiddleware` so it runs inside it and
    therefore hashes the *uncompressed* body. Hashing the compressed one would
    make the validator depend on whether the client happened to send
    `Accept-Encoding`, so the same data would carry two different tags and a
    device that changed its mind about compression would re-download everything.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method not in ("GET", "HEAD"):
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            return await call_next(request)

        response = await call_next(request)

        if response.status_code != 200:
            return response

        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        def _rebuilt() -> Response:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        if len(body) > _MAX_HASHABLE_BYTES or _PRESIGNED_MARKER in body:
            return _rebuilt()

        etag = _etag_for(body)

        if _matches(request.headers.get("if-none-match", ""), etag):
            # Nothing but the validator and the headers that describe caching may
            # travel on a 304 — a body here is a protocol error, and
            # Content-Length must not survive from the response we are replacing.
            headers = {"ETag": etag, "Cache-Control": "private, must-revalidate"}
            vary = response.headers.get("vary")
            if vary:
                headers["Vary"] = vary
            return Response(status_code=304, headers=headers)

        fresh = _rebuilt()
        fresh.headers["ETag"] = etag
        # `must-revalidate` on purpose: the client asks every time and is answered
        # in one packet when nothing moved. Letting a balance or an order status be
        # served from a cache without asking is how somebody reads a figure that
        # is minutes stale with nothing on screen to say so.
        fresh.headers["Cache-Control"] = "private, must-revalidate"
        return fresh
