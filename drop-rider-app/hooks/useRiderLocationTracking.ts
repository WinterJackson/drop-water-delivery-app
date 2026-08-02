/**
 * Mounts the background location machinery for the signed-in rider.
 *
 * Two jobs, both of which have to happen outside the screen that starts
 * tracking, because tracking outlives that screen:
 *
 *  1. Publish Clerk's `getToken` into `services/locationTracking`, which runs in
 *     a task with no React context and therefore cannot obtain a token itself.
 *  2. Drain the on-disk ping buffer whenever the app comes back to the
 *     foreground. A rider who spent a delivery in a coverage hole has fixes
 *     waiting on disk, and nothing else would ever send them.
 *
 * Mounted once, in `(screens)/_layout.tsx`.
 */
import { useAuth } from "@clerk/clerk-expo";
import { useEffect } from "react";
import { AppState, AppStateStatus } from "react-native";

import {
  flushLocationPings,
  setLocationTokenProvider,
} from "@/services/locationTracking";

export function useRiderLocationTracking() {
  const { getToken, isSignedIn } = useAuth();

  useEffect(() => {
    if (!isSignedIn) {
      setLocationTokenProvider(null);
      return;
    }

    setLocationTokenProvider(() => getToken());
    // Anything buffered while the app was closed goes now.
    flushLocationPings({ force: true });

    const subscription = AppState.addEventListener("change", (status: AppStateStatus) => {
      if (status === "active") flushLocationPings({ force: true });
    });

    return () => {
      subscription.remove();
      setLocationTokenProvider(null);
    };
  }, [getToken, isSignedIn]);
}
