import os
import boto3
from botocore.exceptions import NoCredentialsError, ClientError
from fastapi import UploadFile
import uuid
import mimetypes
from fastapi import HTTPException

import logging

logger = logging.getLogger(__name__)

# Initialize S3 client
# In production, these should be loaded from environment variables
# For now, we will use a fallback logic if keys are missing
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

S3_BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'drop-kyc-bucket')

async def upload_file_to_s3(file: UploadFile, prefix: str = "kyc") -> str:
    """
    Securely uploads a file to AWS S3 and returns the S3 key.
    Enforces a strict 8MB memory cap on file reads.
    """
    try:
        # Enforce 8MB limit (8 * 1024 * 1024 bytes)
        MAX_SIZE = 8 * 1024 * 1024
        file_content = await file.read(MAX_SIZE + 1)
        if len(file_content) > MAX_SIZE:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 8MB.")
        
        # Determine content type and extension
        content_type = file.content_type
        extension = mimetypes.guess_extension(content_type) or ".jpg"
        
        # Generate a unique file name to prevent overwrites
        file_name = f"{prefix}/{uuid.uuid4()}{extension}"
        
        # Upload to S3
        if os.getenv('AWS_ACCESS_KEY_ID'):
            s3_client.put_object(
                Bucket=S3_BUCKET_NAME,
                Key=file_name,
                Body=file_content,
                ContentType=content_type,
                # Server-side encryption for PII compliance
                ServerSideEncryption='AES256' 
            )
            # Return the secure key instead of a public URL
            return file_name
            
        elif os.getenv("ENV", "development").lower() != "development":
            # Fail closed. This branch used to be taken on *any* deployment
            # missing a credential, because it tested the credential and not
            # the environment — so in production a rider's national ID was
            # written to the container's own disk, unencrypted, and the
            # function returned a *truthy* path. That path sailed past the KYC
            # route's own `if not front_url` guard, the submission reported
            # success, `kyc_status` went to `pending`, and the file was
            # unreachable immediately: `/api/uploads/…` is not a mounted route,
            # and the disk is wiped on the next deploy in any case.
            #
            # Nobody could then be approved — the reviewer's `<img>` 404s — so
            # every rider sat in `VerificationWall` indefinitely, with no error
            # anywhere to say why. A 503 here is strictly better: the rider is
            # told to try again, nothing is half-recorded, and the operator
            # finds out from the first submission rather than the first
            # complaint.
            #
            # Money, KYC and cash gates fail closed on this platform. Storage
            # for identity documents is the same kind of gate.
            logger.error(
                "Refusing an upload to prefix '%s': AWS credentials are not "
                "configured and ENV is not development. Set AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY and S3_BUCKET_NAME.",
                prefix,
            )
            raise HTTPException(
                status_code=503,
                detail="File storage is not configured. Please try again later.",
            )
        else:
            # DEVELOPMENT FALLBACK: Local file storage
            os.makedirs(f"uploads/{prefix}", exist_ok=True)
            local_path = f"uploads/{file_name}"
            with open(local_path, "wb") as f:
                f.write(file_content)
            # In development, serve from local URL or just return the path
            return f"/api/uploads/{file_name}"
            
    except ClientError as e:
        logger.error(f"S3 Upload Error: {e}", exc_info=True)
        return None
    except NoCredentialsError:
        logger.error("AWS Credentials not available for S3 upload")
        return None
    finally:
        # Reset file cursor for subsequent reads if needed
        await file.seek(0)

def generate_presigned_url(s3_key: str, expires_in: int = 900) -> str:
    """
    Generates a presigned URL for secure access to a private S3 object.
    Defaults to a 15 minute (900s) expiration.

    **This is for private objects only** — identity documents, KYC photographs,
    delivery proof, dispute evidence. For a product photograph, a store logo or an
    avatar, use `public_asset_url`: see its docstring for why presigning one of
    those is a bandwidth defect rather than a security measure.
    """
    if not s3_key:
        return None

    if not os.getenv('AWS_ACCESS_KEY_ID'):
        # Fallback for development if using local storage paths
        if s3_key.startswith("/api/uploads/"):
            return s3_key
        return f"/api/uploads/{s3_key}"

    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': S3_BUCKET_NAME, 'Key': s3_key},
            ExpiresIn=expires_in
        )
        return url
    except ClientError as e:
        logger.error(f"Error generating presigned URL: {e}", exc_info=True)
        return None


#: Origin that serves the public asset bucket — CloudFront in production. Unset,
#: everything falls back to presigning exactly as before, so this ships dark and
#: turns on when the distribution exists.
PUBLIC_ASSET_BASE_URL = (os.getenv("PUBLIC_ASSET_BASE_URL") or "").rstrip("/")


def public_asset_url(s3_key: str) -> str:
    """A **stable** URL for an asset that is not a secret.

    Every image on this platform was presigned, including the ones that are not
    private: product photographs, store logos, customer and rider avatars. A
    presigned URL embeds `X-Amz-Date` and an expiry in its signature, so the same
    product photo has a *different URL in every response*.

    Every image cache in the stack keys on the URL — `expo-image`, React Native's
    own, the OS HTTP cache, and any CDN. A URL that changes per response therefore
    means a cache key that changes per response, so **every image is re-downloaded
    every time a list is refreshed**, whether or not the device already holds a
    byte-identical copy. Twenty-six components across the three apps render images
    this way, and the `cachePolicy` props already set in the vendor app were doing
    nothing at all.

    In numbers: a twenty-item catalogue at roughly 40 KB an image is 800 KB
    re-fetched on every refresh, on metered Kenyan mobile data, repeated on every
    foreground. It is the largest single data cost in the platform and the reason
    the apps feel broken on exactly the handsets most of Drop's customers own. It
    also means a customer who browses and then loses signal holds images that
    expire in fifteen minutes.

    The presigning was right for what it was designed for and stays exactly as it
    is for those objects. The defect was applying the same mechanism to a
    photograph of a water bottle.

    A key is served from `PUBLIC_ASSET_BASE_URL` unchanged, so the URL is a pure
    function of the object: it changes if and only if the image does, which is what
    makes `Cache-Control: public, max-age=31536000, immutable` safe on the bucket.
    Uploads must therefore write content-addressed keys — never overwrite a key
    with different bytes, or caches will serve the old image forever.
    """
    if not s3_key:
        return None
    if str(s3_key).startswith("http"):
        return s3_key
    if not PUBLIC_ASSET_BASE_URL:
        # No distribution configured. Presign, so behaviour is unchanged rather
        # than broken — this is the state every environment is in until the
        # bucket split is provisioned.
        return generate_presigned_url(s3_key)
    return f"{PUBLIC_ASSET_BASE_URL}/{str(s3_key).lstrip('/')}"
