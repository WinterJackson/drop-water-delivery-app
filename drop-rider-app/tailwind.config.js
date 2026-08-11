/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,ts,tsx}"],
  presets: [require("nativewind/preset")],
  darkMode: "class",
  theme: {
    extend: {
      /**
       * Typography. Karla for body/UI, Fredoka for headings, JetBrains Mono
       * for figures and codes.
       *
       * One token per real font file, on purpose. React Native has no
       * `font-synthesis-weight`: pairing a family with `font-bold` makes the OS
       * thicken the strokes itself, which looks smeared next to the real face.
       * `font-sans-bold` loads Karla's actual Bold instead of faking it.
       *
       * Fredoka stops at 600 — there is no `font-heading-bold`, and that is not
       * an omission. Its heavier weights read as a children's brand.
       */
      fontFamily: {
        sans: ["Karla_400Regular"],
        "sans-light": ["Karla_300Light"],
        "sans-medium": ["Karla_500Medium"],
        "sans-semibold": ["Karla_600SemiBold"],
        "sans-bold": ["Karla_700Bold"],
        "sans-extrabold": ["Karla_800ExtraBold"],

        heading: ["Fredoka_400Regular"],
        "heading-medium": ["Fredoka_500Medium"],
        "heading-semibold": ["Fredoka_600SemiBold"],

        mono: ["JetBrainsMono_400Regular"],
        "mono-medium": ["JetBrainsMono_500Medium"],
        "mono-semibold": ["JetBrainsMono_600SemiBold"],
        "mono-bold": ["JetBrainsMono_700Bold"],
      },
      colors: {
        primary: "#0295f7",
        "primary-container": "#0295f7",
        "on-primary-container": "#002d47",
        "on-primary": "#003351",
        
        secondary: "#0295f7",
        "secondary-container": "#0295f7",
        
        background: "#f9f9f9",
        "dark-background": "#121212",
        "on-background": "#e5e2e1",
        
        accentbg: "#0295f7",
        accenttxt: "#0295f7",
        text: "#333",

        // Stitch Semantic Dark Mode Colors
        "surface": "#121212",
        "surface-dim": "#121212",
        "surface-bright": "#393939",
        "surface-container-lowest": "#0e0e0e",
        "surface-container-low": "#1c1b1b",
        "surface-container": "#201f1f",
        "surface-container-high": "#2a2a2a",
        "surface-container-highest": "#353534",
        "on-surface": "#e5e2e1",
        "on-surface-variant": "#bfc7d2",
        "outline": "#89929b",
        "outline-variant": "#3f4850",
        "surface-variant": "#353534"
      },
      spacing: {
        "base": "4px",
        "xs": "4px",
        "sm": "8px",
        "md": "16px",
        "lg": "24px",
        "xl": "32px",
        "gutter": "16px",
        "margin": "20px"
      }
    },
  },
  plugins: [],
}

