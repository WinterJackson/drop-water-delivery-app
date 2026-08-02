import * as ImageManipulator from 'expo-image-manipulator';

import { apiFetch } from '@/API/apiFetch';
import { errorMessage } from '@/API/errors';
import RiderApiRoutes from '@/API/routes/RiderApiRoutes';
import { Toast } from '@/lib/toast';

/**
 * What `POST /api/rider/upload_proof` returns. `secure_url` is the S3 key that
 * gets attached to the delivery-completion call — not a public URL; the backend
 * signs it on the way out.
 */
export interface UploadedProof {
  secure_url: string;
}

const SecureUpload = async (
  uri: string,
  name: string | null | undefined,
  getToken: () => Promise<string | null>
): Promise<UploadedProof> => {
  const formData = new FormData();
  let processedUri = uri;
  let mimeType = 'image/webp';
  let processedName = name ? name.split('.')[0] + '.webp' : 'delivery_proof.webp';

  try {
    const manipResult = await ImageManipulator.manipulateAsync(
      uri,
      [{ resize: { width: 800 } }],
      { compress: 0.7, format: ImageManipulator.SaveFormat.WEBP }
    );
    processedUri = manipResult.uri;
  } catch (e) {
    if (__DEV__) console.warn("Failed to compress to WebP, falling back to original", e);
    // Fall back to jpeg as standard if WebP fails
    mimeType = 'image/jpeg';
    processedName = name ? name.split('.')[0] + '.jpg' : 'delivery_proof.jpg';
  }

  const file = {
    uri: processedUri,
    type: mimeType,
    name: processedName,
  };

  formData.append('file', file as any);

  try {
    const token = await getToken();
    // A photo over a rider's connection needs longer than the default 15s, and
    // this upload is the gate on completing a delivery with missing bottles —
    // timing it out is worse than waiting.
    return await apiFetch<UploadedProof>(RiderApiRoutes.UploadProof.path, {
      method: 'POST',
      token,
      formData,
      timeoutMs: 60_000,
    });
  } catch (err: unknown) {
    if (__DEV__) console.error('Secure upload error:', err);
    // The backend rejects non-images and oversized files with a reason; showing
    // it lets the rider fix the photo instead of retrying the same one.
    Toast.error('Upload Error', errorMessage(err, 'Failed to upload proof photo. Please try again.'));
    throw err;
  }
};

export default SecureUpload;
