import * as ImagePicker from 'expo-image-picker';
import { useCallback, useState } from 'react';

import { errorMessage } from '@/API/errors';
import SecureUpload from '@/Helpers/imageUpload';
import { Toast } from '@/lib/toast';
import { useActiveStore } from '@/stores/activeStoreStore';
import { useAuth } from '@clerk/clerk-expo';

/**
 * Pick a product photo and upload it.
 *
 * The upload itself lives in `Helpers/imageUpload.ts` — this hook is the picker
 * and the loading state around it. It used to hold a second, divergent copy of
 * the upload: the same unsigned Cloudinary preset, different compression
 * settings, and a `catch` that swallowed the failure and returned `null`, so a
 * screen that did not check the return value saved a product with no image.
 */
export const useImageUpload = () => {
  const { getToken } = useAuth();
  const activeStoreId = useActiveStore((s) => s.activeStoreId);
  const [imageUri, setImageUri] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pickImage = useCallback(async () => {
    const permissionResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permissionResult.granted) {
      Toast.error('Permission denied', 'We need permission to access your photos');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      allowsEditing: true,
      aspect: [4, 3],
      quality: 1,
    });

    if (!result.canceled && result.assets && result.assets.length > 0) {
      setImageUri(result.assets[0].uri);
      setError(null);
    }
  }, []);

  const uploadImage = useCallback(
    async (uri: string): Promise<string | null> => {
      setUploading(true);
      setError(null);
      try {
        const result = await SecureUpload(uri, `product_${Date.now()}`, getToken, activeStoreId);
        return result.secure_url;
      } catch (err: unknown) {
        // `SecureUpload` has already shown the backend's own reason.
        setError(errorMessage(err, 'Could not upload that image.'));
        return null;
      } finally {
        setUploading(false);
      }
    },
    [getToken, activeStoreId]
  );

  const handleImageUpload = useCallback(async () => {
    if (!imageUri) {
      Toast.info('Error', 'Please select an image first');
      return null;
    }

    return await uploadImage(imageUri);
  }, [imageUri, uploadImage]);

  return {
    imageUri,
    setImageUri,
    uploading,
    error,
    pickImage,
    uploadImage,
    handleImageUpload,
  };
};
