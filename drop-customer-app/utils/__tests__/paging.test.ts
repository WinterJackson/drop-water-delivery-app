/**
 * Offset paging over a list that keeps changing underneath the reader.
 *
 * Every list endpoint pages with `limit`/`offset`, and offset measures from the
 * top of a result that moves. A new order arrives, a notification lands, a
 * vendor accepts — every row below shifts down one, so the first row of page 2
 * is the row that was last on page 1 and arrives a second time.
 *
 * These tests assert the client's half of the fix: flatten by row id, so at
 * worst a row is missing until the next refresh, never duplicated.
 */
import { flattenPages, keepPaging, nextOffset } from "../paging";

type Row = { id: string; label: string };

const page = (...rows: Row[]) => rows;

describe("flattenPages", () => {
  it("concatenates pages in order", () => {
    const rows = flattenPages<Row>({
      pages: [page({ id: "a", label: "1" }), page({ id: "b", label: "2" })],
    });
    expect(rows.map((r) => r.id)).toEqual(["a", "b"]);
  });

  it("drops the duplicate a shifting window produces", () => {
    // Page 1 ends on `c`; a row was inserted above, so page 2 begins with `c`
    // again. Without this the customer sees one order twice.
    const rows = flattenPages<Row>({
      pages: [
        page({ id: "a", label: "1" }, { id: "b", label: "2" }, { id: "c", label: "3" }),
        page({ id: "c", label: "3" }, { id: "d", label: "4" }),
      ],
    });
    expect(rows.map((r) => r.id)).toEqual(["a", "b", "c", "d"]);
  });

  it("keeps the first copy of a duplicated row, not the last", () => {
    const rows = flattenPages<Row>({
      pages: [page({ id: "a", label: "first" }), page({ id: "a", label: "second" })],
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].label).toBe("first");
  });

  it("reads both response envelopes the platform uses", () => {
    // Bare arrays, `{data: []}` and `{items: []}` all appear across the three
    // apps' endpoints; a screen must not care which it got.
    expect(flattenPages<Row>({ pages: [{ data: [{ id: "a", label: "1" }] }] })).toHaveLength(1);
    expect(flattenPages<Row>({ pages: [{ items: [{ id: "b", label: "2" }] }] })).toHaveLength(1);
  });

  it("keeps a row with no id rather than hiding it", () => {
    // A missing id is a schema surprise. Silently dropping rows is a worse
    // answer than showing a duplicate — an order that vanishes is unexplainable.
    const rows = flattenPages<any>({ pages: [[{ label: "no id" }, { label: "also none" }]] });
    expect(rows).toHaveLength(2);
  });

  it("survives the states a query passes through before it has data", () => {
    expect(flattenPages<Row>(undefined)).toEqual([]);
    expect(flattenPages<Row>(null)).toEqual([]);
    expect(flattenPages<Row>({ pages: [] })).toEqual([]);
    expect(flattenPages<Row>({ pages: [null, undefined] })).toEqual([]);
  });

  it("accepts a custom identity for a row keyed on something else", () => {
    const rows = flattenPages<{ vendor_id: string }>(
      { pages: [[{ vendor_id: "v1" }], [{ vendor_id: "v1" }, { vendor_id: "v2" }]] },
      (row) => row.vendor_id,
    );
    expect(rows.map((r) => r.vendor_id)).toEqual(["v1", "v2"]);
  });
});

describe("keepPaging", () => {
  it("asks for the next page once", () => {
    const fetchNextPage = jest.fn();
    keepPaging({ hasNextPage: true, isFetchingNextPage: false, fetchNextPage })();
    expect(fetchNextPage).toHaveBeenCalledTimes(1);
  });

  it("does not ask again while a page is already in flight", () => {
    // `onEndReached` fires repeatedly while a long list settles. A bare
    // `fetchNextPage()` there requests the same page several times, on exactly
    // the slow connections where the extra requests hurt most.
    const fetchNextPage = jest.fn();
    keepPaging({ hasNextPage: true, isFetchingNextPage: true, fetchNextPage })();
    expect(fetchNextPage).not.toHaveBeenCalled();
  });

  it("stops at the end of the list", () => {
    const fetchNextPage = jest.fn();
    keepPaging({ hasNextPage: false, isFetchingNextPage: false, fetchNextPage })();
    expect(fetchNextPage).not.toHaveBeenCalled();
  });

  it("treats an undefined flag as no next page", () => {
    const fetchNextPage = jest.fn();
    keepPaging({ fetchNextPage })();
    expect(fetchNextPage).not.toHaveBeenCalled();
  });
});

describe("nextOffset", () => {
  const next = nextOffset<Row>(25);

  it("stops on a short page", () => {
    expect(next(page({ id: "a", label: "1" }), [page({ id: "a", label: "1" })])).toBeUndefined();
  });

  it("counts the rows already held rather than assuming full pages", () => {
    // `allPages.length * size` walks past rows the moment one page is short —
    // which happens whenever a row is removed between requests.
    const full = Array.from({ length: 25 }, (_, i) => ({ id: `a${i}`, label: "x" }));
    const short = Array.from({ length: 20 }, (_, i) => ({ id: `b${i}`, label: "x" }));
    expect(next(full, [full])).toBe(25);
    expect(next(full, [short, full])).toBe(45);
  });

  it("stops at the end of an empty list", () => {
    expect(next([], [[]])).toBeUndefined();
  });

  it("stops when the page is missing entirely", () => {
    expect(next(undefined, [])).toBeUndefined();
    expect(next(null, [])).toBeUndefined();
  });
});
