/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Teal brand scale (600/700 pass WCAG AA for text on white)
        brand: { 50: "#effaf9", 100: "#d5f3f0", 200: "#aee6e1", 300: "#7bd2cc", 400: "#45b8b3", 500: "#269d9a", 600: "#1b7f80", 700: "#186566", 800: "#175152", 900: "#154445" },
        // Deep blue for ink and secondary accents
        navy: { 50: "#f3f6fb", 100: "#e4eaf4", 200: "#c9d5e9", 300: "#9fb3d4", 400: "#6e88b8", 500: "#4c6a9f", 600: "#3a5384", 700: "#2f4269", 800: "#1f2f4d", 900: "#13203a" },
        sky: { 50: "#eff7ff", 100: "#dbeeff", 600: "#1d6fd1", 700: "#1a58a6" },
        warm: { 50: "#fffaf2", 100: "#fff1d9", 700: "#8a5a00" },
        alert: { 50: "#fff1f1", 100: "#ffdede", 600: "#c62828", 700: "#a31f1f" },
      },
      fontFamily: {
        sans: ['"Inter"', '"Noto Sans Devanagari"', "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ['"Plus Jakarta Sans"', '"Noto Sans Devanagari"', '"Inter"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(19,32,58,0.04), 0 4px 16px rgba(19,32,58,0.06)",
        pop: "0 8px 30px rgba(19,32,58,0.16)",
      },
      keyframes: {
        rise: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        dots: { "0%,80%,100%": { opacity: "0.25", transform: "scale(0.8)" }, "40%": { opacity: "1", transform: "scale(1)" } },
        slide: { from: { transform: "translateX(100%)" }, to: { transform: "none" } },
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
      },
      animation: {
        rise: "rise .25s ease-out both",
        dots: "dots 1.2s infinite ease-in-out both",
        slide: "slide .22s ease-out both",
        fade: "fade .18s ease-out both",
      },
    },
  },
  plugins: [],
};
