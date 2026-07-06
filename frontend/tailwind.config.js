/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // "Council chamber" base — deep ink charcoal, not pure black.
        chamber: {
          DEFAULT: "#16171B",
          panel: "#1E2025",
          raised: "#26282E",
          line: "#33353C",
        },
        ink: {
          primary: "#EDEAE3",
          secondary: "#9A9CA5",
          tertiary: "#6C6E76",
        },
        // Verdict accent — used sparingly, only for the stamp + red flags.
        verdict: "#FF4E3A",
        // Per-agent mandate colors — the visual language for "who said what".
        agent: {
          growth: "#E8A33D",
          risk: "#D64545",
          legal: "#5B6EE8",
          techdebt: "#4FA8A0",
          customer: "#C15FC1",
        },
      },
      fontFamily: {
        display: ["'Fraunces'", "serif"],
        body: ["'Inter'", "sans-serif"],
        mono: ["'IBM Plex Mono'", "monospace"],
      },
      keyframes: {
        "pulse-seat": {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.55 },
        },
        "stamp-in": {
          "0%": { transform: "rotate(-8deg) scale(1.4)", opacity: 0 },
          "60%": { transform: "rotate(-6deg) scale(0.95)", opacity: 1 },
          "100%": { transform: "rotate(-6deg) scale(1)", opacity: 1 },
        },
      },
      animation: {
        "pulse-seat": "pulse-seat 1.6s ease-in-out infinite",
        "stamp-in": "stamp-in 0.45s cubic-bezier(0.2, 0.8, 0.3, 1) forwards",
      },
    },
  },
  plugins: [],
};
