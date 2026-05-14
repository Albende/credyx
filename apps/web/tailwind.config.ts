import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "hsl(220 18% 5%)",
        surface: "hsl(220 14% 8%)",
        border: "hsl(220 10% 18%)",
        text: "hsl(0 0% 96%)",
        muted: "hsl(220 8% 60%)",
        accent: "hsl(180 80% 55%)",
        good: "hsl(140 70% 45%)",
        warn: "hsl(40 90% 55%)",
        bad: "hsl(0 75% 55%)",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
