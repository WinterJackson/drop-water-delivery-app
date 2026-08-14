import * as ImageManipulator from 'expo-image-manipulator';

import { apiFetch } from '@/API/apiFetch';
import { errorMessage } from '@/API/errors';
import { ROUTES } from '@/API/routes/ApiRoutes';
import { Toast } from '@/lib/toast';

/**
 * What `POST /api/auth/upload-profile-pic` returns. `secure_url` is the S3 key
 * that gets stored on the account — not a public URL; `BaseUser.profile_pic`
 * turns it into a stable, cacheable one on the way out.
 */
export interface UploadedImage {
  secure_url: string;
}

/**
 * Upload a customer's avatar through our own backend.
 *
 * This used to POST straight to Cloudinary with `upload_preset: 'drop_uploads'`
 * and no signature, with the cloud name and preset both hardcoded as fallbacks
 * in this file. An unsigned preset in a shipped bundle is a public write
 * endpoint: anyone who unzips the APK can upload arbitrary files to the account,
 * from any machine, at the account owner's expense, and nothing in the request
 * identifies who did it. Revoking it means deleting the preset for everybody at
 * once.
 *
 * The rider and vendor apps were moved off exactly this path, and their guides
 * say so in as many words. This app kept it, because the raw-`fetch` guard that
 * covers the other two was never written for this one — so the change stopped at
 * two of three apps and nothing said otherwise.
 *
 * Going through the backend also means the upload is authenticated, rate
 * limited, size-capped and content-sniffed. The old path accepted whatever the
 * client sent, including an SVG carrying script.
 */
const SecureUpload = async (
  uri: string,
  name: string | null | undefined,
  getToken: () => Promise<string | null>
): Promise<UploadedImage> => {
  const formData = new FormData();
  let processedUri = uri;
  let mimeType = 'image/webp';
  let processedName = name ? name.split('.')[0] + '.webp' : `drop_${Date.now()}.webp`;

  try {
    // 800px wide is more than any screen renders an avatar at, and it is the
    // difference between a 4 MB phone photo and ~80 KB on a metered connection.
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
    // `kind: 'upload'` rather than a number: `netBudget` gives a photograph the
    // longest budget there is, and stretches it further on a slow connection.
    // Aborting an avatar at 90% and starting again is strictly worse than
    // waiting, and costs the customer the data twice.
    return await apiFetch<UploadedImage>(ROUTES.UPLOAD_PROFILE_PIC, {
      method: 'POST',
      token,
      formData,
    });
  } catch (err: unknown) {
    if (__DEV__) console.error('Secure upload error:', err);
    // The backend rejects non-images and oversized files with a reason; showing
    // it lets the customer pick a different photo instead of retrying this one.
    Toast.error('Upload Error', errorMessage(err, 'Could not upload that image. Please try again.'));
    throw err;
  }
};

export default SecureUpload;
