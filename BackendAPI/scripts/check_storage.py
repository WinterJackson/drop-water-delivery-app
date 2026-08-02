"""Is file storage actually S3, and is it private and encrypted?

`utils/s3_utils.py` branches on `AWS_ACCESS_KEY_ID`. With it unset it silently
takes a **development fallback that writes to local disk** — and uploads still
return 200, so nothing about the response tells you which path ran. On Render
that disk is ephemeral: KYC documents (national ID photos) are written to a
filesystem wiped on every deploy, restart and scale event, without the
`ServerSideEncryption='AES256'` the S3 path applies.

Worse, the fallback returns `/api/uploads/<key>` as the file's URL, and nothing
mounts `/api/uploads` — no `StaticFiles`, no route. Those URLs 404 forever.

This script round-trips a real object: upload, presign, fetch, confirm the
encryption header, delete. Anything less would pass with a bucket that exists
but denies `PutObject`, which is the usual way this is misconfigured.

    python scripts/check_storage.py

Exits 0 when storage is correctly configured, 1 otherwise. Writes and then
removes one small object under `healthcheck/`. Prints no secrets.
"""

import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET_NAME", "AWS_REGION")


def main() -> int:
    problems: list[str] = []
    notes: list[str] = []

    present = {name: bool((os.getenv(name) or "").strip()) for name in REQUIRED}

    print("      AWS_ACCESS_KEY_ID      " + ("set" if present["AWS_ACCESS_KEY_ID"] else "NOT SET"))
    print("      AWS_SECRET_ACCESS_KEY  " + ("set" if present["AWS_SECRET_ACCESS_KEY"] else "NOT SET"))
    print(f"      AWS_REGION             {os.getenv('AWS_REGION') or 'NOT SET (defaults to us-east-1)'}")
    print(f"      S3_BUCKET_NAME         {os.getenv('S3_BUCKET_NAME') or 'NOT SET (defaults to drop-kyc-bucket)'}")

    if not present["AWS_ACCESS_KEY_ID"]:
        print()
        print("FAIL  AWS_ACCESS_KEY_ID is not set, so every upload takes the local-disk")
        print("      fallback in utils/s3_utils.py. Uploads return 200 and the files are")
        print("      unencrypted, unserved (nothing mounts /api/uploads), and — on Render —")
        print("      erased on the next deploy. This includes rider KYC identity documents.")
        return 1

    if not present["AWS_SECRET_ACCESS_KEY"]:
        problems.append("AWS_ACCESS_KEY_ID is set but AWS_SECRET_ACCESS_KEY is not.")
    for name in ("AWS_REGION", "S3_BUCKET_NAME"):
        if not present[name]:
            notes.append(
                f"{name} is unset and falling back to a default. Set it explicitly "
                "rather than relying on the default matching your actual bucket."
            )

    if problems:
        for p in problems:
            print(f"FAIL  {p}")
        return 1

    # ── Round-trip a real object ──────────────────────────────────────────
    import boto3
    import httpx
    from botocore.exceptions import ClientError

    from utils.s3_utils import S3_BUCKET_NAME, generate_presigned_url, s3_client

    key = f"healthcheck/{uuid.uuid4()}.txt"
    payload = b"drop storage healthcheck"

    try:
        s3_client.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=payload,
            ContentType="text/plain",
            ServerSideEncryption="AES256",
        )
        print(f"      put_object             ok ({S3_BUCKET_NAME})")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "?")
        print(f"FAIL  Could not write to s3://{S3_BUCKET_NAME}: {code}")
        if code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            print("      The credentials need s3:PutObject on this bucket.")
        elif code in ("NoSuchBucket", "PermanentRedirect"):
            print("      The bucket does not exist, or AWS_REGION names the wrong region.")
        return 1

    exit_code = 0
    try:
        head = s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=key)
        sse = head.get("ServerSideEncryption")
        if sse:
            print(f"      encryption at rest     {sse}")
        else:
            print("FAIL  The object came back with no ServerSideEncryption.")
            exit_code = 1

        url = generate_presigned_url(key, expires_in=60)
        if not url or not url.startswith("http"):
            print(f"FAIL  generate_presigned_url returned {url!r} — not a signed URL.")
            return 1

        got = httpx.get(url, timeout=20.0)
        if got.status_code == 200 and got.content == payload:
            print("      presigned GET          ok")
        else:
            print(f"FAIL  Presigned GET returned {got.status_code}.")
            exit_code = 1

        # The bucket must NOT be publicly readable: KYC documents live here.
        bare = url.split("?")[0]
        anon = httpx.get(bare, timeout=20.0)
        if anon.status_code == 200:
            print("FAIL  The object is readable WITHOUT the signature — this bucket is")
            print("      public. Rider national-ID photos are stored here. Turn on Block")
            print("      Public Access and remove any public-read bucket policy.")
            exit_code = 1
        else:
            print(f"      unsigned GET refused   {anon.status_code} (correct)")
    finally:
        try:
            s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=key)
        except ClientError:
            notes.append(f"Could not delete the test object s3://{S3_BUCKET_NAME}/{key}.")

    for note in notes:
        print(f"NOTE  {note}")

    if exit_code == 0:
        print("OK    Uploads go to S3, encrypted at rest, private, and presignable.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
