import { apiFetch } from '@/API/apiFetch';
import { useAuth } from '@clerk/clerk-expo';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { LogBox, Platform } from 'react-native';
import { useQueryClient } from '@tanstack/react-query';
import * as Haptics from 'expo-haptics';

// ── Expo Go Detection ────────────────────────────────────────────────────────
// expo-notifications internally console.error()s during module init in Expo Go
// SDK 53+. require() won't throw — the module loads fine — but it logs a red
// error that panics the dev overlay. The only way to prevent it is to never
// load the module in the first place when running inside Expo Go.
const isExpoGo = Constants.appOwnership === 'expo';

// Suppress the two non-actionable warnings from Expo Go
LogBox.ignoreLogs([
    'expo-notifications',
    'SafeAreaView has been deprecated',
]);

let Notifications: any = null;
if (!isExpoGo) {
    try {
        Notifications = require('expo-notifications');
        Notifications?.setNotificationHandler?.({
            handleNotification: async () => ({
                shouldShowAlert: true,
                shouldPlaySound: true,
                shouldSetBadge: false,
                shouldShowBanner: true,
                shouldShowList: true,
            }),
        });
    } catch {
        // Silently degrade — notifications become a no-op
    }
}

async function registerForPushNotificationsAsync(): Promise<string | undefined> {
    if (!Notifications) return undefined;

    let token: string | undefined;
    if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('default', {
            name: 'default',
            importance: Notifications.AndroidImportance.MAX,
            vibrationPattern: [0, 250, 250, 250],
            lightColor: '#FF231F7C',
        });
    }

    if (Device.isDevice) {
        const { status: existingStatus } = await Notifications.getPermissionsAsync();
        let finalStatus = existingStatus;
        if (existingStatus !== 'granted') {
            const { status } = await Notifications.requestPermissionsAsync();
            finalStatus = status;
        }
        if (finalStatus !== 'granted') {
            if (__DEV__) console.log('Failed to get push token for push notification!');
            return;
        }
        try {
            const projectId = Constants?.expoConfig?.extra?.eas?.projectId ?? Constants?.easConfig?.projectId;
            if (!projectId) {
                throw new Error('Project ID not found');
            }
            token = (await Notifications.getExpoPushTokenAsync({ projectId })).data;
        } catch (e) {
            try {
                token = (await Notifications.getExpoPushTokenAsync({ projectId: '' })).data;
            } catch {
                if (__DEV__) console.warn('Could not obtain push token.');
            }
        }
    } else {
        if (__DEV__) console.log('Must use physical device for Push Notifications');
    }
    return token;
}

export function usePushNotifications(queryPrefix: string = 'vendor') {
    const [expoPushToken, setExpoPushToken] = useState('');
    const [notification, setNotification] = useState<any>(undefined);
    const notificationListener = useRef<any>(null);
    const responseListener = useRef<any>(null);
    const { getToken, isSignedIn } = useAuth();
    const router = useRouter();
    const queryClient = useQueryClient();

    useEffect(() => {
        if (!isSignedIn || !Notifications) return;

        registerForPushNotificationsAsync().then(async (token) => {
            if (token) {
                setExpoPushToken(token);
                try {
                    await apiFetch(`${process.env.EXPO_PUBLIC_BACKEND_BASE_URL}/api/auth/push-token`, {
                        method: 'POST',
                        token: await getToken(),
                        body: { push_token: token, app_type: 'vendor' },
                    });
                } catch (e) {
                    // Not fatal — the in-app notification list still works, and
                    // registration retries on the next launch. Deliberately not
                    // routed through `useApiRequest`: a 401 here would sign the
                    // vendor out during startup.
                    if (__DEV__) console.warn('Push token registration failed:', e);
                }
            }
        });

        notificationListener.current = Notifications.addNotificationReceivedListener((notif: any) => {
            setNotification(notif);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications'] });
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications', 'unread-count'] });
        });

        responseListener.current = Notifications.addNotificationResponseReceivedListener((response: any) => {
            const data = (response as any).notification.request.content.data;
            if (data?.url) {
                router.push(data.url as any);
            }
        });

        return () => {
            notificationListener.current?.remove();
            responseListener.current?.remove();
        };
    }, [isSignedIn]);

    /**
     * Detach this device's push token from the vendor account.
     *
     * Must run *before* `signOut()` — the endpoint is authenticated, so there is
     * no way to do it afterwards. Skipping it leaves the token registered against
     * the account, and on a shared till device the next person to sign in keeps
     * receiving the previous store's incoming-order notifications.
     */
    const clearPushToken = useCallback(async () => {
        try {
            const authToken = await getToken();
            if (!authToken) return;
            // `?app_type=vendor` is not optional: the endpoint defaults to
            // `customer` and clears `User.push_token` for a clerk id that has no
            // User row. Without it this call returned 404 and the vendor's token
            // stayed registered — exactly the failure the docstring above
            // describes it as preventing.
            await apiFetch(
                `${process.env.EXPO_PUBLIC_BACKEND_BASE_URL}/api/auth/push-token?app_type=vendor`,
                { method: 'DELETE', token: authToken }
            );
            setExpoPushToken('');
        } catch (e) {
            if (__DEV__) console.warn('Push token de-registration failed:', e);
        }
    }, [getToken]);

    return { expoPushToken, notification, clearPushToken };
}
