import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0E1B33", 2: "#14254A", 3: "#22355E" },
        deep: { DEFAULT: "#163A6B", 600: "#1D4B88", 50: "#EAF0F8" },
        teal: { DEFAULT: "#14928A", 600: "#0F7A73", 50: "#E6F5F3" },
        amber: { DEFAULT: "#A86A12", 50: "#FBF2E2" },
        danger: { DEFAULT: "#B4322B", 50: "#FBEAE8" },
        surface: "#F5F8FB",
        rule: "#D8E0EA",
        text: { DEFAULT: "#16202E", 2: "#4A5869", 3: "#7A8797" },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', '"IBM Plex Sans Arabic"', "system-ui", "sans-serif"],
        arabic: ['"IBM Plex Sans Arabic"', '"IBM Plex Sans"', "system-ui", "sans-serif"],
        serif: ['"Source Serif 4"', "Georgia", "serif"],
      },
      fontSize: {
        // modular scale ~1.2, 17px base for long reading sessions
        xs: ["0.8125rem", "1.25rem"],
        sm: ["0.9375rem", "1.4rem"],
        base: ["1.0625rem", "1.65rem"],
        lg: ["1.25rem", "1.75rem"],
        xl: ["1.5rem", "2rem"],
        "2xl": ["1.875rem", "2.3rem"],
        "3xl": ["2.375rem", "2.75rem"],
      },
      maxWidth: { read: "72ch" },
    },
  },
  plugins: [],
} satisfies Config;
