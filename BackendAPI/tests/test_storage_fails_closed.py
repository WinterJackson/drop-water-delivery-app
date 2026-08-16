"""An identity document is never accepted with nowhere to store it.

`upload_file_to_s3` branched on the *credential* rather than the *environment*:

    if os.getenv('AWS_ACCESS_KEY_ID'):
        s3_client.put_object(...)
    else:
        # DEVELOPMENT FALLBACK: Local file storage

So a production deployment with no AWS key took the development path. A rider's
national ID was written unencrypted to the container's own disk, and the
function returned a **truthy** string — which passed the KYC route's own
`if not front_url or not back_url` guard. The submission reported success,
`kyc_status` moved to `pending`, and the document was unreachable from that
moment: `/api/uploads/…` is not a mounted route (there is no `StaticFiles` in
`main.py`), and the disk is wiped on the next deploy regardless.

The reviewer's `<img>` then 404s, so nobody can be approved, so every rider sits
in `VerificationWall` — a gate that opens only on a positively confirmed
`approved` — with no error anywhere naming the cause.

Money, KYC and cash gates fail closed here. Storage for identity documents is
the same kind of gate, and this is the test that says so.
"""
from __future__ import annotations

import io
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException, UploadFile

from utils import s3_utils


def _upload(name: str = "id.jpg") -> UploadFile:
    return UploadFile(
        filename=name,
        file=io.BytesIO(b"\xff\xd8\xff\xe0 pretend this is a national id"),
        headers={"content-type": "image/jpeg"},
    )


def _no_aws(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")}
    env.update(extra)
    return patch.dict(os.environ, env, clear=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["production", "PRODUCTION", "staging"])
async def test_an_upload_without_credentials_refuses_outside_development(env):
    with _no_aws(ENV=env):
        with pytest.raises(HTTPException) as excinfo:
            await s3_utils.upload_file_to_s3(_upload(), prefix="kyc/id_front")

    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_the_refusal_never_returns_a_usable_looking_path():
    """The whole defect was a *truthy* return value.

    The KYC route only checks `if not front_url`, so anything non-empty reads
    as a successful upload. Raising is what makes that impossible; this asserts
    the failure mode directly rather than trusting the branch.
    """
    with _no_aws(ENV="production"):
        try:
            result = await s3_utils.upload_file_to_s3(_upload(), prefix="kyc/id_back")
        except HTTPException:
            result = None

    assert not result, (
        "a falsy return or a raise are both fine; a path is not — the caller "
        "cannot tell one from a real S3 key"
    )


@pytest.mark.asyncio
async def test_development_still_writes_locally(tmp_path, monkeypatch):
    """The fallback is genuinely useful on a laptop and must survive."""
    monkeypatch.chdir(tmp_path)
    with _no_aws(ENV="development"):
        result = await s3_utils.upload_file_to_s3(_upload(), prefix="kyc/id_front")

    assert result.startswith("/api/uploads/kyc/id_front/")
    written = list((tmp_path / "uploads" / "kyc" / "id_front").iterdir())
    assert len(written) == 1


@pytest.mark.asyncio
async def test_an_unset_env_is_treated_as_development(tmp_path, monkeypatch):
    """`ENV` unset means a laptop, consistent with every other gate that reads
    it. A deployment is expected to say so explicitly."""
    # `chdir` because the fallback writes relative to the working directory —
    # without it this test drops an `uploads/` tree into the repo.
    monkeypatch.chdir(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if k not in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "ENV")}
    with patch.dict(os.environ, env, clear=True):
        # Does not raise.
        result = await s3_utils.upload_file_to_s3(_upload(), prefix="kyc/id_front")
    assert result


def test_the_fallback_path_is_still_not_served_by_the_app():
    """Non-vacuity for the premise above: if someone mounts `/api/uploads`,
    this test should fail and the reasoning here be revisited."""
    from main import app

    served = {getattr(route, "path", "") for route in app.routes}
    assert not any(str(p).startswith("/api/uploads") for p in served), (
        "an /api/uploads route now exists — the development fallback would be "
        "reachable, and the comment in `upload_file_to_s3` needs rewriting"
    )
