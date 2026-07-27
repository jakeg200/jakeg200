import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // The room is paper and ink. Nothing competes with the learner's own working.
        paper: "#faf9f7",
        ink: "#1c1b19",
        rule: "#e8e4dd",
      },
    },
  },
  plugins: [],
} satisfies Config;
