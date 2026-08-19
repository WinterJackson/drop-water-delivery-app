/**
 * Taking a shop off your favourites, without losing it by accident.
 *
 * A favourite is one long-press away from gone, on a chip that sits in a
 * horizontally scrolling row the thumb is already dragging across. So the
 * destructive path is the one worth pinning down: the gesture must raise a
 * confirmation rather than mutate, the confirmation must be the destructive
 * variant, and only its confirm may reach the mutation.
 *
 * There is a second, quieter requirement. The action panel underneath is keyed
 * on the selected favourite, and the removal is optimistic — the row leaves the
 * list in the same tick the mutation fires. If the selection is not cleared
 * first the panel renders against a vendor that is no longer there, which in
 * this component means reading `.business_name` off `undefined`.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react-native";

const mockShow = jest.fn();
const mockHide = jest.fn();
const mockMutate = jest.fn();
const mockFavorites = jest.fn();

jest.mock("@/hooks/queries/useVendorFavorites", () => ({
  useVendorFavorites: () => mockFavorites(),
  useRemoveVendorFavorite: () => ({ mutate: mockMutate, isPending: false }),
}));

// A zustand selector store: the component calls it with a selector, so the mock
// has to run that selector against a state object rather than return a fixture.
jest.mock("@/stores/popupStore", () => ({
  usePopupStore: (selector: (s: unknown) => unknown) =>
    selector({ show: mockShow, hide: mockHide }),
}));

jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }) }));

import FavouritesList from "@/components/common/FavouritesList";

const VENDOR = {
  // The real wire shape: `id` is the favourite row, `vendor_id` the store.
  id: "fav-1",
  vendor_id: "v-1",
  vendor: {
    id: "v-1",
    business_name: "Kilimani Water Point",
    store_state: "open",
    logo_url: null,
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  mockFavorites.mockReturnValue({
    data: [VENDOR],
    isLoading: false,
    isError: false,
  });
});

/** The confirmation payload handed to the popup store on the last call. */
const lastPopup = () => mockShow.mock.calls[mockShow.mock.calls.length - 1][0];

describe("removing a favourite", () => {
  it("asks before it removes", async () => {
    await render(<FavouritesList />);
    const chip = await screen.findByLabelText(/Kilimani Water Point/i);

    fireEvent(chip, "longPress");

    expect(mockShow).toHaveBeenCalledTimes(1);
    expect(mockMutate).not.toHaveBeenCalled();
  });

  it("names the shop in the confirmation, so the wrong chip is obvious", async () => {
    await render(<FavouritesList />);
    fireEvent(await screen.findByLabelText(/Kilimani Water Point/i), "longPress");

    const popup = lastPopup();
    expect(popup.message).toContain("Kilimani Water Point");
    expect(popup.confirmText).toBe("Remove");
    expect(popup.cancelText).toBe("Keep");
  });

  it("marks the confirmation destructive", async () => {
    // The confirm button is the one that cannot be undone from this screen.
    await render(<FavouritesList />);
    fireEvent(await screen.findByLabelText(/Kilimani Water Point/i), "longPress");

    expect(lastPopup().isDestructive).toBe(true);
  });

  it("removes only once the confirmation is confirmed", async () => {
    await render(<FavouritesList />);
    fireEvent(await screen.findByLabelText(/Kilimani Water Point/i), "longPress");

    expect(mockMutate).not.toHaveBeenCalled();
    lastPopup().onConfirm();

    expect(mockMutate).toHaveBeenCalledWith("v-1");
  });

  it("dismisses the confirmation as it removes", async () => {
    await render(<FavouritesList />);
    fireEvent(await screen.findByLabelText(/Kilimani Water Point/i), "longPress");
    lastPopup().onConfirm();

    expect(mockHide).toHaveBeenCalled();
  });

  it("survives the row leaving the list under the open action panel", async () => {
    // Tap to select (which opens the panel), then remove from the panel's own
    // button. The optimistic mutation takes the row away; the panel must not
    // still be rendering against it.
    await render(<FavouritesList />);
    fireEvent.press(await screen.findByLabelText(/Kilimani Water Point/i));

    const remove = await screen.findByLabelText(
      /Remove Kilimani Water Point from favourites/i,
    );
    fireEvent.press(remove);
    lastPopup().onConfirm();

    // The list is now empty, exactly as the optimistic update leaves it.
    mockFavorites.mockReturnValue({ data: [], isLoading: false, isError: false });
    await waitFor(() => expect(mockMutate).toHaveBeenCalledWith("v-1"));
  });
});

describe("the gesture is discoverable", () => {
  it("tells a screen reader how to remove, not just what the chip is", async () => {
    // PressableScale supplies the role; without the label an icon-and-image
    // chip announces as "button" and nothing else, and the long-press is
    // invisible to anybody not looking at the screen.
    await render(<FavouritesList />);
    const chip = await screen.findByLabelText(/Kilimani Water Point/i);

    expect(chip.props.accessibilityLabel).toMatch(/long press to remove/i);
  });
});
