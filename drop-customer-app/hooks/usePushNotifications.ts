import { ROUTES } from '@/API/routes/ApiRoutes';
import { useApiRequest } from '@/API/useApiClient';
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

export function usePushNotifications(queryPrefix: string = 'customer') {
    const [expoPushToken, setExpoPushToken] = useState('');
    const [notification, setNotification] = useState<Notification | undefined>(undefined);
    const notificationListener = useRef<Subscription | null>(null);
    const responseListener = useRef<Subscription | null>(null);
    const { isSignedIn } = useAuth();
    const api = useApiRequest();
    const router = useRouter();
    const queryClient = useQueryClient();

    // Kept in a ref so the effect below depends only on `isSignedIn`; `api` is a
    // new object whenever Clerk's auth context re-renders.
    const apiRef = useRef(api);
    useEffect(() => { apiRef.current = api; }, [api]);

    useEffect(() => {
        if (!isSignedIn || !Notifications) return;

        let cancelled = false;

        // A cold-start response is replayed on every mount of this hook, so guard
        // against navigating to the same notification twice in one session.
        const handled = new Set<string>();
        const openFromNotification = (response: NotificationResponse | null) => {
            const url = response?.notification?.request?.content?.data?.url;
            if (!url) return;
            const id = response?.notification?.request?.identifier ?? String(url);
            if (handled.has(id)) return;
            handled.add(id);
            router.push(url as Href);
        };

        registerForPushNotificationsAsync().then(async (token) => {
            if (!token || cancelled) return;
            setExpoPushToken(token);
            try {
                // Endpoint comes from the shared route table, not a hand-built
                // string, so it is covered by the route-contract test.
                await apiRef.current.post(ROUTES.REGISTER_PUSH_TOKEN, {
                    push_token: token,
                    app_type: 'customer',
                });
            } catch (e) {
                if (__DEV__) console.error("Push token registration failed:", e);
            }
        });

        notificationListener.current = Notifications.addNotificationReceivedListener((notif: Notification) => {
            setNotification(notif);
            Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications'] });
            queryClient.invalidateQueries({ queryKey: [queryPrefix, 'notifications', 'unread-count'] });

            // Order pushes mean the order state changed; refresh the lists that
            // render it so the app agrees with the notification the user just saw.
            const type = notif?.request?.content?.data?.type;
            if (!type || String(type).includes('order') || String(type).includes('delivery')) {
                queryClient.invalidateQueries({ queryKey: [queryPrefix, 'orders'] });
            }
        });

        responseListener.current = Notifications.addNotificationResponseReceivedListener((response: NotificationResponse | null) => {
            openFromNotification(response);
        });

        // The listener above only fires while it is mounted, so a notification
        // tapped while the app was *killed* was delivered to nobody and the tap
        // just opened the home screen. This replays the response that launched
        // the app — the cold-start case is the common one for an order update
        // that arrives hours after the user last opened Drop.
        Notifications.getLastNotificationResponseAsync?.()
            .then((response: NotificationResponse | null) => {
                if (!cancelled) openFromNotification(response);
            })
            .catch(() => {});

        return () => {
            cancelled = true;
            notificationListener.current?.remove();
            responseListener.current?.remove();
        };
    }, [isSignedIn]);

    /**
     * Detach this device's push token from the account.
     *
     * Must run before sign-out: on a shared device the token otherwise stays
     * registered and the next person to sign in keeps receiving the previous
     * account's order notifications.
     */
    const clearPushToken = useCallback(async () => {
        try {
            await apiRef.current.del(ROUTES.CLEAR_PUSH_TOKEN);
            setExpoPushToken('');
        } catch (e) {
            if (__DEV__) console.warn('Push token de-registration failed:', e);
        }
    }, []);

    return { expoPushToken, notification, clearPushToken };
}
