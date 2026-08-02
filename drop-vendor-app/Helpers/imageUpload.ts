import * as ImageManipulator from 'expo-image-manipulator';

import { apiFetch } from '@/API/apiFetch';
import { errorMessage } from '@/API/errors';
import VendorApiRoutes from '@/API/routes/VendorApiRoutes';
import { Toast } from '@/lib/toast';

/**
 * What `POST /api/vendor/upload-image` returns. `secure_url` is the S3 key that
 * gets stored on the product or the store — not a public URL; the backend signs
 * it for 15 minutes on the way out.
 */
export interface UploadedImage {
  secure_url: string;
}

/**
 * Upload a product photo or store avatar through our own backend.
 *
 * This used to POST straight to Cloudinary with `upload_preset: 'drop_uploads'`
 * and no signature. An unsigned preset in a shipped bundle is a public write
 * endpoint: anyone who unzips the APK can upload arbitrary files to the account
 * from any machine, at the account owner's expense, and nothing in the request
 * identifies who did it. Revoking it meant deleting the preset for every vendor.
 *
 * Going through the backend also means the upload is authenticated, scoped to
 * the active store, size-capped, and content-sniffed — the old path accepted
 * whatever the client sent, including an SVG carrying script.
 */
const SecureUpload = async (
  uri: string,
  name: string | null | undefined,
  getToken: () => Promise<string | null>,
  storeId?: string | null
): Promise<UploadedImage> => {
  const formData = new FormData();
  let processedUri = uri;
  let mimeType = 'image/webp';
  let processedName = name ? name.split('.')[0] + '.webp' : `drop_${Date.now()}.webp`;

  try {
    // 800px wide is more than any screen in either app renders a product at,
    // and it is the difference between a 4 MB phone photo and ~80 KB.
    const manipResult = await ImageManipulator.manipulateAsync(
      uri,
      [{ resize: { width: 800 } }],
      { compress: 0.8, format: ImageManipulator.SaveFormat.WEBP }
    );
    processedUri = manipResult.uri;
  } catch (e) {
    if (__DEV__) console.warn('Failed to compress to WebP, falling back to original', e);
    mimeType = 'image/jpeg';
    processedName = name ? name.split('.')[0] + '.jpg' : `drop_${Date.now()}.jpg`;
  }

  formData.append('file', { uri: processedUri, type: mimeType, name: processedName } as any);

  try {
    const token = await getToken();
    // A photo over a shop's connection needs longer than the default 15s, and
    // this upload gates saving a product — timing it out is worse than waiting.
    return await apiFetch<UploadedImage>(VendorApiRoutes.UploadImage.path, {
      method: 'POST',
      token,
      formData,
      storeId,
      timeoutMs: 60_000,
    });
  } catch (err: unknown) {
    if (__DEV__) console.error('Secure upload error:', err);
    // The backend rejects non-images and oversized files with a reason; showing
    // it lets the vendor fix the photo instead of retrying the same one.
    Toast.error('Upload Error', errorMessage(err, 'Could not upload that image. Please try again.'));
    throw err;
  }
};

export default SecureUpload;
