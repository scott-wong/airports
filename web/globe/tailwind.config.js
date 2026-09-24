/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        hud: {
          bg: "#04070f",
          panel: "rgba(8, 18, 32, 0.78)",
          line: "rgba(80, 200, 255, 0.28)",
          cyan: "#4de3ff",
          dim: "#7d94b5",
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
