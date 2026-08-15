/**
 * Money never becomes a float.
 *
 * Every monetary field arrives from the backend as a decimal *string*, because
 * the columns behind them are Postgres `NUMERIC` and Python `Decimal`. Parsing
 * one into a JS number to add or format it reintroduces exactly the binary
 * floating-point error the backend goes out of its way to avoid.
 *
 * These tests are written against the arithmetic a float gets wrong, not against
 * round numbers that happen to work either way. A suite of `formatMoney("100")`
 * would pass just as happily over a broken implementation.
 */
import {
  compareMoney,
  discountPercent,
  discountedPrice,
  formatMoney,
  formatMoneyShort,
  isNegativeMoney,
  isZeroMoney,
  moneyRatio,
  multiplyMoney,
  subtractMoney,
  sumMoney,
} from "../money";

describe("formatMoney", () => {
  it("pads to two decimal places and groups thousands", () => {
    expect(formatMoney("1234.5")).toBe("KSH 1,234.50");
    expect(formatMoney("1234567.89")).toBe("KSH 1,234,567.89");
    expect(formatMoney("100")).toBe("KSH 100.00");
  });

  it("renders a bare figure when the label already says KSH", () => {
    expect(formatMoney("2500", "")).toBe("2,500.00");
  });

  it("treats absent money as zero rather than rendering NaN", () => {
    // A balance that has not loaded is KSH 0.00 on screen, never "KSH NaN" —
    // which is what `Number(undefined).toFixed(2)` produces.
    expect(formatMoney(null)).toBe("KSH 0.00");
    expect(formatMoney(undefined)).toBe("KSH 0.00");
    expect(formatMoney("")).toBe("KSH 0.00");
  });

  it("refuses malformed input instead of propagating it", () => {
    expect(formatMoney("abc")).toBe("KSH 0.00");
    expect(formatMoney("1,234.50")).toBe("KSH 0.00");
  });

  it("keeps the sign on an account in arrears", () => {
    expect(formatMoney("-450.25")).toBe("-KSH 450.25");
  });

  it("truncates beyond cents rather than rounding up a figure it was given", () => {
    // The backend quantizes to two places; anything further is noise from a
    // client-side computation that should not have happened.
    expect(formatMoney("10.999")).toBe("KSH 10.99");
  });
});

describe("formatMoneyShort", () => {
  it("rounds half-up so nothing is shown as less than it is", () => {
    expect(formatMoneyShort("1234.50")).toBe("KSH 1,235");
    expect(formatMoneyShort("1234.49")).toBe("KSH 1,234");
    expect(formatMoneyShort("0.50")).toBe("KSH 1");
  });

  it("keeps the sign", () => {
    expect(formatMoneyShort("-99.60")).toBe("-KSH 100");
  });
});

describe("sumMoney", () => {
  it("adds the case a float gets wrong", () => {
    // 0.1 + 0.2 === 0.30000000000000004 in this runtime.
    expect(sumMoney(["0.10", "0.20"])).toBe("0.30");
    expect(Number("0.1") + Number("0.2")).not.toBe(0.3);
  });

  it("stays exact across a long list of order lines", () => {
    const lines = Array.from({ length: 100 }, () => "0.07");
    expect(sumMoney(lines)).toBe("7.00");
  });

  it("stays exact past the range where a float loses cents", () => {
    // 2^53 cents is about 90 trillion; a platform-wide total would overflow the
    // safe integer range long before BigInt notices.
    expect(sumMoney(["90071992547409.91", "0.01"])).toBe("90071992547409.92");
  });

  it("ignores absent entries rather than producing NaN", () => {
    expect(sumMoney(["10.00", null, undefined, "", "5.50"])).toBe("15.50");
  });

  it("is zero for an empty basket", () => {
    expect(sumMoney([])).toBe("0.00");
  });
});

describe("subtractMoney", () => {
  it("computes what actually reaches the phone after a withdrawal fee", () => {
    // The documented case: a KSH 1,000 withdrawal against a fee an administrator
    // set to 15.50.
    expect(subtractMoney("1000.00", "15.50")).toBe("984.50");
  });

  it("goes negative rather than clamping", () => {
    // A wallet can be in arrears, and hiding that behind a floor of zero is how
    // a debt stops being visible to the person who owes it.
    expect(subtractMoney("10.00", "25.00")).toBe("-15.00");
  });
});

describe("multiplyMoney", () => {
  it("computes a line total exactly", () => {
    expect(multiplyMoney("249.99", 7)).toBe("1749.93");
  });

  it("refuses a fractional count", () => {
    // A percentage of money is a decision the server makes. There is no
    // `divide` here on purpose, and multiplying by 0.5 would be the same thing
    // through the back door.
    expect(multiplyMoney("100.00", 1.5)).toBe("0.00");
  });

  it("handles a zero quantity", () => {
    expect(multiplyMoney("249.99", 0)).toBe("0.00");
  });
});

describe("compareMoney", () => {
  it("compares numerically, not as text", () => {
    // The bug this exists to prevent: "10.00" < "9.00" is true as a string
    // compare, so a rider with KSH 1,000 would fail a KSH 900 minimum.
    expect(compareMoney("10.00", "9.00")).toBe(1);
    expect("10.00" < "9.00").toBe(true);
  });

  it("reports equality across differently written zeros", () => {
    expect(compareMoney("0", "0.00")).toBe(0);
    expect(compareMoney("5", "5.00")).toBe(0);
  });

  it("orders a withdrawal against the platform minimum", () => {
    expect(compareMoney("499.99", "500.00")).toBe(-1);
    expect(compareMoney("500.00", "500.00")).toBe(0);
  });
});

describe("isZeroMoney / isNegativeMoney", () => {
  it("recognises zero however it is written", () => {
    expect(isZeroMoney("0")).toBe(true);
    expect(isZeroMoney("0.00")).toBe(true);
    expect(isZeroMoney(null)).toBe(true);
    expect(isZeroMoney("0.01")).toBe(false);
  });

  it("recognises arrears", () => {
    expect(isNegativeMoney("-0.01")).toBe(true);
    expect(isNegativeMoney("0.00")).toBe(false);
    expect(isNegativeMoney("1200.00")).toBe(false);
  });
});

describe("moneyRatio", () => {
  it("is a fraction for a progress bar", () => {
    expect(moneyRatio("250.00", "1000.00")).toBeCloseTo(0.25, 10);
  });

  it("is zero against a zero denominator rather than Infinity or NaN", () => {
    // A progress bar with a width of NaN renders as nothing at all, silently.
    expect(moneyRatio("100.00", "0")).toBe(0);
    expect(moneyRatio("100.00", null)).toBe(0);
  });

  it("can exceed one, so a caller must clamp for a bar width", () => {
    expect(moneyRatio("1500.00", "1000.00")).toBeCloseTo(1.5, 10);
  });
});

describe("the money path end to end", () => {
  it("keeps a cart total exact through the operations a screen performs", () => {
    // Three 20 L bottles at 249.99, a delivery fee, a bottle deposit, less a
    // welcome discount — the shape of a real first order.
    const lineTotal = multiplyMoney("249.99", 3);
    const total = sumMoney([lineTotal, "120.00", "300.00"]);
    const afterDiscount = subtractMoney(total, "150.00");

    expect(lineTotal).toBe("749.97");
    expect(total).toBe("1169.97");
    expect(afterDiscount).toBe("1019.97");
    expect(formatMoney(afterDiscount)).toBe("KSH 1,019.97");
  });

  it("never lets a displayed total drift from the summed one", () => {
    const parts = ["33.33", "33.33", "33.34"];
    expect(sumMoney(parts)).toBe("100.00");
    expect(formatMoney(sumMoney(parts))).toBe("KSH 100.00");
  });
});

describe("a product's discounted price", () => {
  /**
   * Six screens computed this inline as
   * `Math.round((price - discount) * 100) / 100` on two decimal-string fields.
   * These are the cases that float subtraction gets wrong — the shelf price a
   * customer reads, on the one screen where a wrong figure is also the first
   * one they see.
   */
  it("subtracts in cents rather than in floats", () => {
    expect(discountedPrice("0.30", "0.10")).toBe("0.20");
    // 249.99 - 0.10 is 249.88999999999999 as a float.
    expect(discountedPrice("249.99", "0.10")).toBe("249.89");
    expect(discountedPrice("1000.00", "333.33")).toBe("666.67");
  });

  it("treats a missing discount as none", () => {
    expect(discountedPrice("249.99", null)).toBe("249.99");
    expect(discountedPrice("249.99", undefined)).toBe("249.99");
    expect(discountedPrice("249.99", "")).toBe("249.99");
  });

  it("clamps at zero rather than advertising a negative price", () => {
    // A discount above the price is a data fault. "KSH -20.00" on a shelf
    // label is the worst possible way to surface one.
    expect(discountedPrice("100.00", "150.00")).toBe("0.00");
  });

  it("formats through formatMoney, so every screen groups it the same way", () => {
    expect(formatMoney(discountedPrice("12499.99", "500.00"))).toBe("KSH 11,999.99");
  });
});

describe("a product's discount percentage", () => {
  it("rounds down, so a 49.6% saving is never advertised as 50%", () => {
    expect(discountPercent("1000.00", "496.00")).toBe(49);
    expect(discountPercent("100.00", "25.00")).toBe(25);
    expect(discountPercent("249.99", "50.00")).toBe(20);
  });

  it("is zero rather than NaN or Infinity when there is nothing to divide by", () => {
    // `discount / price` on a free or malformed product produced `Infinity` and
    // `NaN`, and `Math.ceil(NaN)` renders as "NaN%" on the badge.
    expect(discountPercent("0", "50.00")).toBe(0);
    expect(discountPercent(null, "50.00")).toBe(0);
    expect(discountPercent("100.00", null)).toBe(0);
    expect(discountPercent("100.00", "-5.00")).toBe(0);
  });
});
