"use client";

import Particles, { initParticlesEngine } from "@tsparticles/react";
import { loadSlim } from "@tsparticles/slim";
import { useEffect, useMemo, useState } from "react";

import { tokenColour, useTheme } from "@/lib/use-theme";

/**
 * The drifting particle field behind the sign-in form.
 *
 * Two things about it are deliberate.
 *
 * **The colour comes from the palette, not from a hex.** A canvas is outside
 * CSS, so the field needs a concrete colour string — and writing `#ffffff` for
 * dark and `#000000` for light would put two more raw colours in a console
 * whose whole styling rule is that colours live in `globals.css`. It reads
 * `--accent` instead, which already has a light and a dark value chosen against
 * their own backgrounds, and re-reads it whenever the theme changes.
 *
 * **It is decoration and announces itself as such.** `aria-hidden` keeps a
 * canvas full of moving dots out of the accessibility tree, and the whole field
 * is dropped for anyone who has asked for reduced motion — a permanently
 * animating background is exactly what that setting is for.
 */
export function ParticlesBackground({ id = "auth-particles" }: { id?: string }) {
  const [ready, setReady] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);
  const { theme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    initParticlesEngine(async (engine) => {
      await loadSlim(engine);
    }).then(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(media.matches);
    const onChange = () => setReducedMotion(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  // `theme` is in the dependency list rather than the body because the token's
  // *value* changes when the attribute does; the name never does.
  const colour = useMemo(
    () => tokenColour("--accent", "#0295f7"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme],
  );

  const options = useMemo(
    () => ({
      // Scoped to this container, not the viewport — the field belongs to the
      // form panel and must not cover the branding panel beside it.
      fullScreen: { enable: false },
      background: { color: { value: "transparent" } },
      fpsLimit: 120,
      interactivity: {
        events: {
          onHover: { enable: true, mode: "grab" },
          onClick: { enable: true, mode: "push" },
        },
        modes: {
          grab: { distance: 140, links: { opacity: 0.6 } },
          push: { quantity: 4 },
        },
      },
      particles: {
        color: { value: colour },
        links: {
          color: colour,
          distance: 150,
          enable: true,
          opacity: 0.2,
          width: 1,
        },
        move: {
          direction: "none" as const,
          enable: true,
          outModes: { default: "bounce" as const },
          random: false,
          speed: 1.5,
          straight: false,
        },
        number: { density: { enable: true }, value: 80 },
        opacity: { value: 0.35 },
        shape: { type: "circle" as const },
        size: { value: { min: 1, max: 3 } },
      },
      detectRetina: true,
    }),
    [colour],
  );

  // The engine initialises asynchronously and the theme is unknown until
  // mount, so there is nothing honest to render on the server. Returning null
  // keeps the first paint identical on both sides of hydration.
  if (!ready || theme === null || reducedMotion) return null;

  return (
    <Particles
      id={id}
      // Remounts on a theme change so the already-drawn particles take the new
      // colour; tsparticles reads `options` once when it builds the container.
      key={theme}
      className="absolute inset-0"
      options={options}
    />
  );
}
