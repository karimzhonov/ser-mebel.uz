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
        // SerMebel logo: deep teal #002B31 + blush #FED1C8.
        brand: {
          50: "#ecf6f6",
          100: "#cfe8ea",
          200: "#a3d2d6",
          300: "#6fb4ba",
          400: "#3f9199",
          500: "#1f747d",
          600: "#105e67",
          700: "#0a4c54",
          800: "#053c43",
          900: "#002b31",
          950: "#001c20",
        },
        accent: {
          50: "#fff7f5",
          100: "#ffeee9",
          200: "#fed1c8",
          300: "#fbb6a8",
          400: "#f59684",
          500: "#e97863",
          600: "#d05c48",
          700: "#ad4637",
          800: "#8c3a30",
          900: "#73332c",
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
