/**
 * Every piece of text renders in the platform's own face.
 *
 * React Native has no cascade: a font set on a parent view does not reach the
 * text inside it, and every `<Text>` naming no family renders in whatever the OS
 * picked — Roboto on one handset, San Francisco on another. Three apps all using
 * the system font are three apps that look different on every device and match
 * neither the console nor each other.
 *
 * The rule is resolved at render time rather than by a rewrite, because
 * `<Text className={labelStyle}>` is a real pattern here and no find-and-replace
 * can see which branch built that string. These tests cover both halves: the
 * pure resolver, and the components actually rendering with what it returned.
 */
import React from "react";
import { render, screen } from "@testing-library/react-native";

/**
 * `render` is asynchronous in @testing-library/react-native v14 — it returns a
 * promise and only then is `screen` populated. Calling it without `await` gives
 * "`render` function has not been called", which reads like a setup fault rather
 * than a missing await.
 */

import { Text, TextInput, withDefaultFont } from "../Text";

describe("withDefaultFont", () => {
  it("supplies the body face when the class string names none", () => {
    expect(withDefaultFont("text-lg")).toBe("font-sans text-lg");
    expect(withDefaultFont("")).toBe("font-sans");
    expect(withDefaultFont(undefined)).toBe("font-sans");
  });

  it("leaves an explicit family alone", () => {
    for (const explicit of [
      "font-sans-bold",
      "font-sans-semibold",
      "font-heading",
      "font-heading-medium",
      "font-mono",
      "font-mono-semibold",
    ]) {
      expect(withDefaultFont(`text-lg ${explicit}`)).toBe(`text-lg ${explicit}`);
    }
  });

  it("still supplies a family beside a bare weight utility", () => {
    // `font-bold` sets `fontWeight` and names no family, so React Native
    // thickens the *system* font — bold enough in review to look intended, and
    // different on every handset. That is the case this default exists for.
    expect(withDefaultFont("font-bold")).toBe("font-sans font-bold");
    expect(withDefaultFont("text-xl font-semibold")).toBe("font-sans text-xl font-semibold");
  });

  it("is not fooled by a family name inside a longer word", () => {
    // `font-sanserif-ish` is not a family this platform registers.
    expect(withDefaultFont("font-sansation")).toBe("font-sans font-sansation");
  });

  it("finds the family wherever it sits in the string", () => {
    expect(withDefaultFont("font-heading text-2xl")).toBe("font-heading text-2xl");
    expect(withDefaultFont("text-2xl font-heading")).toBe("text-2xl font-heading");
    expect(withDefaultFont("a font-mono b")).toBe("a font-mono b");
  });

  it("returns the same answer for a repeated class string", () => {
    // The result is cached; a cache that could return a stale answer for a
    // different string would be worse than no cache.
    expect(withDefaultFont("text-sm")).toBe(withDefaultFont("text-sm"));
    expect(withDefaultFont("font-mono")).toBe("font-mono");
    expect(withDefaultFont("text-sm")).toBe("font-sans text-sm");
  });
});

describe("<Text>", () => {
  it("renders its children", async () => {
    await render(<Text>KSH 1,200.00</Text>);
    expect(screen.getByText("KSH 1,200.00")).toBeTruthy();
  });

  it("carries the default family through to the rendered element", async () => {
    await render(<Text className="text-lg">Total</Text>);
    expect(screen.getByText("Total").props.className).toBe("font-sans text-lg");
  });

  it("does not override a heading face", async () => {
    await render(<Text className="font-heading text-2xl">Your orders</Text>);
    expect(screen.getByText("Your orders").props.className).toBe("font-heading text-2xl");
  });

  it("passes other props straight through", async () => {
    await render(
      <Text numberOfLines={2} accessibilityRole="header">
        Heading
      </Text>,
    );
    const node = screen.getByText("Heading");
    expect(node.props.numberOfLines).toBe(2);
    expect(node.props.accessibilityRole).toBe("header");
  });
});

describe("<TextInput>", () => {
  it("gets the same default, so a form does not fall back to the OS font", async () => {
    await render(<TextInput placeholder="07XXXXXXXX" className="p-3" />);
    expect(screen.getByPlaceholderText("07XXXXXXXX").props.className).toBe("font-sans p-3");
  });

  it("stays a controlled input", async () => {
    // The wrapper must not swallow `value`/`onChangeText`: every edit screen
    // drives its fields from state.
    const onChangeText = jest.fn();
    await render(<TextInput value="KDG 123X" onChangeText={onChangeText} />);
    expect(screen.getByDisplayValue("KDG 123X")).toBeTruthy();
  });
});
