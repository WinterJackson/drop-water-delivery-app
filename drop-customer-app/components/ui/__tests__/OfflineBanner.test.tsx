/**
 * "No internet connection" is a claim, and it needs a definitive answer.
 *
 * NetInfo's `isInternetReachable` is tri-state: `true`, `false`, and `null` for
 * "the reachability probe has not come back yet". Only `false` says there is no
 * internet. `null` is an unanswered question, and this app has a rule about
 * those — the coverage banner that told a customer their neighbourhood was
 * unserved before anybody had asked where they lived was the same mistake.
 *
 * The regression is invisible by reading: `!!state.isInternetReachable !== false`
 * looks like it tolerates `null`. It does not. `!!` binds tighter than `!==`,
 * so it collapses to `!!state.isInternetReachable`, and `!!null` is `false` —
 * the banner fired on precisely the state the comment beside it said to ignore.
 * That is every cold start while the probe is in flight, and permanently on any
 * network where NetInfo's probe endpoint (a Google URL, not this API) is
 * blocked or slow while the API itself answers fine.
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react-native";
import NetInfo from "@react-native-community/netinfo";

import OfflineBanner from "@/components/ui/OfflineBanner";

const BANNER = /No internet connection/i;

/** Drive both the initial `fetch()` and the subscription with one state. */
const withNetworkState = (state: {
  isConnected: boolean | null;
  isInternetReachable: boolean | null;
}) => {
  (NetInfo.fetch as jest.Mock).mockResolvedValue(state);
  (NetInfo.addEventListener as jest.Mock).mockImplementation((cb: (s: unknown) => void) => {
    cb(state);
    return jest.fn();
  });
};

beforeEach(() => jest.clearAllMocks());

describe("while the answer is still unknown", () => {
  it("stays hidden when reachability has not been determined", async () => {
    // The cold-start state on every launch.
    withNetworkState({ isConnected: true, isInternetReachable: null });
    await render(<OfflineBanner />);

    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
  });

  it("stays hidden when connectivity itself is not yet known", async () => {
    withNetworkState({ isConnected: null, isInternetReachable: null });
    await render(<OfflineBanner />);

    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
  });
});

describe("on a definitive answer", () => {
  it("shows when the probe came back negative", async () => {
    withNetworkState({ isConnected: true, isInternetReachable: false });
    await render(<OfflineBanner />);

    await waitFor(() => expect(screen.getByText(BANNER)).toBeTruthy());
  });

  it("shows when there is no transport at all", async () => {
    withNetworkState({ isConnected: false, isInternetReachable: false });
    await render(<OfflineBanner />);

    await waitFor(() => expect(screen.getByText(BANNER)).toBeTruthy());
  });

  it("stays hidden when the network is genuinely up", async () => {
    withNetworkState({ isConnected: true, isInternetReachable: true });
    await render(<OfflineBanner />);

    await waitFor(() => expect(screen.queryByText(BANNER)).toBeNull());
  });
});
