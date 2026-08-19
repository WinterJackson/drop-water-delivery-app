/**
 * The three states the home screen is allowed to be in, and the two ways the
 * first version of this hook got them wrong.
 *
 * `useDeliveryLocation` decides whether the app knows where to deliver. Every
 * list on the home screen is bounded by a service radius measured from one
 * origin, so "we have not been told" and "we were told and nothing is in range"
 * are different answers that must read differently — the first is a question,
 * the second is bad news. Rendering the first as the second is the "Limited
 * Coverage Area" banner this hook replaced.
 *
 * Both regressions below are silent. Neither changes a type, neither throws,
 * and both put a confident sentence on screen that happens to be false.
 */
/**
 * `renderHook` is asynchronous in @testing-library/react-native v14 — it
 * returns a promise, and `result` is only populated once that has settled.
 * Calling it without `await` destructures `result` off a promise and every
 * assertion dies on `undefined.current`, which reads like a broken hook rather
 * than a broken test. The same footnote sits on `render` in Text.test.tsx.
 */
import { renderHook } from "@testing-library/react-native";

const mockUserDetails = jest.fn();
const mockLocation = jest.fn();

jest.mock("@/hooks/queries/useUser", () => ({
  useUserDetails: () => mockUserDetails(),
}));
jest.mock("@/hooks/useLocation", () => ({
  useLocation: () => mockLocation(),
}));

import { useDeliveryLocation } from "@/hooks/useDeliveryLocation";

/** A `useUserDetails` result in one of the three states a query can be in. */
const reading = () => ({ data: undefined, isSuccess: false, isError: false });
const failed = () => ({ data: undefined, isSuccess: false, isError: true });
const read = (data: unknown) => ({ data, isSuccess: true, isError: false });

beforeEach(() => {
  mockUserDetails.mockReset();
  mockLocation.mockReset();
  mockLocation.mockReturnValue({ location: null });
});

describe("whether the account has been read at all", () => {
  it("is unresolved while the account is still loading", async () => {
    mockUserDetails.mockReturnValue(reading());
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.isResolved).toBe(false);
    expect(result.current.hasAddress).toBe(false);
  });

  it("is unresolved when the account could not be read", async () => {
    // The regression, and it was proven in the worst way: the database hit its
    // compute quota, every endpoint began answering 500, and a hook keyed on
    // `!isPending` put "Where should we deliver?" over an account whose address
    // was visible in the header at that moment. A failed request is also not
    // pending and its `data` is also undefined, so pending alone reads an
    // outage as "this customer has no delivery address".
    mockUserDetails.mockReturnValue(failed());
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.isResolved).toBe(false);
    expect(result.current.isUnavailable).toBe(true);
  });

  it("is resolved only once the read came back", async () => {
    mockUserDetails.mockReturnValue(read({ lat: -1.286389, lng: 36.817223 }));
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.isResolved).toBe(true);
    expect(result.current.isUnavailable).toBe(false);
  });
});

describe("whether a delivery address exists", () => {
  it("counts latitude 0 as an address", async () => {
    // Kenya straddles the equator, so latitude 0 is a real place a customer can
    // live — and `!0` is true, so a truthiness check erases them. The
    // server-side guard had exactly this bug in four endpoints.
    mockUserDetails.mockReturnValue(read({ lat: 0, lng: 36.817223 }));
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.hasAddress).toBe(true);
  });

  it("counts longitude 0 as an address", async () => {
    mockUserDetails.mockReturnValue(read({ lat: -1.286389, lng: 0 }));
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.hasAddress).toBe(true);
  });

  it("needs both halves, not one", async () => {
    mockUserDetails.mockReturnValue(read({ lat: -1.286389, lng: null }));
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.hasAddress).toBe(false);
  });

  it("has no address on an account that carries neither", async () => {
    mockUserDetails.mockReturnValue(read({ location_address: null }));
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.isResolved).toBe(true);
    expect(result.current.hasAddress).toBe(false);
  });

  it("reports the address the customer set, for display", async () => {
    mockUserDetails.mockReturnValue(
      read({ lat: -1.28, lng: 36.81, location_address: "Kilimani, Nairobi" }),
    );
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.address).toBe("Kilimani, Nairobi");
  });
});

describe("the live device fix", () => {
  it("is reported separately from the saved address", async () => {
    // A GPS reading is where the handset is; the saved address is what the
    // server measures from and what checkout enforces against. They are
    // different facts and frequently different places, so a device fix must
    // never stand in for a missing address — it is offered as a one-tap way to
    // set one.
    mockUserDetails.mockReturnValue(read({ location_address: null }));
    mockLocation.mockReturnValue({
      location: { coords: { latitude: -1.3, longitude: 36.8 } },
    });
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.hasAddress).toBe(false);
    expect(result.current.deviceFix).toEqual({ lat: -1.3, lng: 36.8 });
  });

  it("is null when permission was never granted", async () => {
    mockUserDetails.mockReturnValue(read({ lat: -1.28, lng: 36.81 }));
    mockLocation.mockReturnValue({ location: null });
    const { result } = await renderHook(() => useDeliveryLocation());

    expect(result.current.deviceFix).toBeNull();
  });
});
