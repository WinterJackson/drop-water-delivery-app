import { apiFetch } from '@/API/apiFetch';
import VendorApiRoutes from '@/API/routes/VendorApiRoutes';
import { useAuth } from '@clerk/clerk-expo';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { useRouter } from 'expo-router';
import type { Href } from 'expo-router';
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

import type * as ExpoNotifications from 'expo-notifications';
import type {
    Notification,
    NotificationResponse,
    Subscription,
} from 'expo-notifications';

/**
 * The module handle, typed without importing the module.
 *
 * `expo-notifications` is `require`d rather than imported because it is absent
 * from Expo Go, so a static import would crash the dev client on launch. Its
 * *types* have no such problem: `import type` is erased entirely at compile
 * time, emits no require, and gives the real signatures for every call below —
 * so `Notifications` is the actual module shape or `null`, and every call site
 * has to prove it checked for `null` first.
 *
 * It was `any`, which meant the null check was the only thing standing between
 * a typo in a listener name and a silent no-op on the one path that tells a
 * user their order moved.
 */
let Notifications: typeof ExpoNotifications | null = null;
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
    const [notification, setNotification] = useState<Notification | undefined>(undefined);
    const notificationListener = useRef<Subscription | null>(null);
    const responseListener = useRef<Subscription | null>(null);
    const { getToken, isSignedIn } = useAuth();
    const router = useRouter();
    const queryClient = useQueryClient();

    useEffect(() => {
        if (!isSignedIn || !Notifications) return;

        registerForPushNotificationsAsync().then(async (token) => {
            if (token) {
                setExpoPushToken(token);
                try {
                    await apiFetch(VendorApiRoutes.RegisterPushToken.path, {
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

        notificationListener.current = Notifications.addNotificationReceivedListener((notif: Notification) => {
            setNotification(notif);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications'] });
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications', 'unread-count'] });
        });

        responseListener.current = Notifications.addNotificationResponseReceivedListener((response: NotificationResponse | null) => {
            const data = response?.notification.request.content.data;
            if (typeof data?.url === 'string') {
                router.push(data.url as Href);
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
            // The `?app_type=vendor` this depends on is declared with the path
            // in the route table, where the reason it is mandatory is written.
            await apiFetch(VendorApiRoutes.DeletePushToken.path, {
                method: 'DELETE',
                token: authToken,
            });
            setExpoPushToken('');
        } catch (e) {
            if (__DEV__) console.warn('Push token de-registration failed:', e);
        }
    }, [getToken]);

    return { expoPushToken, notification, clearPushToken };
}
