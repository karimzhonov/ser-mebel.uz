/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      colors: {
        // Same purple as the unfold admin theme (core/settings.py UNFOLD.COLORS.primary).
        brand: {
          50: "rgb(250 245 255)",
          100: "rgb(243 232 255)",
          200: "rgb(233 213 255)",
          300: "rgb(216 180 254)",
          400: "rgb(192 132 252)",
          500: "rgb(168 85 247)",
          600: "rgb(147 51 234)",
          700: "rgb(126 34 206)",
          800: "rgb(107 33 168)",
          900: "rgb(88 28 135)",
          950: "rgb(59 7 100)",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgb(16 24 40 / 0.04), 0 1px 3px rgb(16 24 40 / 0.06)",
        pop: "0 12px 32px -8px rgb(16 24 40 / 0.18)",
      },
      keyframes: {
        "fade-in": { from: { opacity: 0 }, to: { opacity: 1 } },
        "slide-up": {
          from: { opacity: 0, transform: "translateY(8px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
        "slide-in": {
          from: { transform: "translateX(100%)" },
          to: { transform: "translateX(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in .15s ease-out",
        "slide-up": "slide-up .2s ease-out",
        "slide-in": "slide-in .25s cubic-bezier(.2,.8,.2,1)",
      },
    },
  },
  plugins: [],
};
