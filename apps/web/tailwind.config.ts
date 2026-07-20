import type { Config } from "tailwindcss";

/*
  CreditLens — "Bureau" design foundation.
  Security-print aesthetic: banker's green + gold leaf + intaglio
  blue over bond paper (light) / vault ink (dark).
  All legacy token names preserved as shims so existing pages
  continue to render unchanged.
*/

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
      screens: { "2xl": "1280px" },
    },
    extend: {
      colors: {
        bg: {
          DEFAULT: "hsl(var(--color-bg-base) / <alpha-value>)",
          base: "hsl(var(--color-bg-base) / <alpha-value>)",
          elevated: "hsl(var(--color-bg-elevated) / <alpha-value>)",
          overlay: "hsl(var(--color-bg-overlay) / <alpha-value>)",
          inset: "hsl(var(--color-bg-inset) / <alpha-value>)",
        },
        fg: {
          DEFAULT: "hsl(var(--color-fg-default) / <alpha-value>)",
          default: "hsl(var(--color-fg-default) / <alpha-value>)",
          muted: "hsl(var(--color-fg-muted) / <alpha-value>)",
          subtle: "hsl(var(--color-fg-subtle) / <alpha-value>)",
          inverted: "hsl(var(--color-fg-inverted) / <alpha-value>)",
        },
        border: {
          DEFAULT: "hsl(var(--color-border-default) / <alpha-value>)",
          default: "hsl(var(--color-border-default) / <alpha-value>)",
          strong: "hsl(var(--color-border-strong) / <alpha-value>)",
          focus: "hsl(var(--color-border-focus) / <alpha-value>)",
        },
        brand: {
          primary: {
            DEFAULT: "hsl(var(--color-brand-primary) / <alpha-value>)",
            fg: "hsl(var(--color-brand-primary-fg) / <alpha-value>)",
            soft: "hsl(var(--color-brand-primary) / 0.12)",
          },
          secondary: {
            DEFAULT: "hsl(var(--color-brand-secondary) / <alpha-value>)",
            fg: "hsl(var(--color-brand-secondary-fg) / <alpha-value>)",
          },
        },
        accent: "hsl(var(--color-accent) / <alpha-value>)",
        success: "hsl(var(--color-success) / <alpha-value>)",
        warning: "hsl(var(--color-warning) / <alpha-value>)",
        danger: "hsl(var(--color-danger) / <alpha-value>)",
        info: "hsl(var(--color-info) / <alpha-value>)",
        surface: "hsl(var(--color-bg-elevated) / <alpha-value>)",
        text: "hsl(var(--color-fg-default) / <alpha-value>)",
        muted: "hsl(var(--color-fg-muted) / <alpha-value>)",
        good: "hsl(var(--color-success) / <alpha-value>)",
        warn: "hsl(var(--color-warning) / <alpha-value>)",
        bad: "hsl(var(--color-danger) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        display: [
          "var(--font-display)",
          "Georgia",
          "Times New Roman",
          "serif",
        ],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        "display-2xl": [
          "clamp(3.25rem, 5.5vw + 1rem, 6rem)",
          { lineHeight: "1.0", letterSpacing: "-0.045em", fontWeight: "700" },
        ],
        "display-xl": [
          "clamp(2.5rem, 4vw + 1rem, 4.5rem)",
          { lineHeight: "1.04", letterSpacing: "-0.04em", fontWeight: "700" },
        ],
        "display-lg": [
          "clamp(2rem, 3vw + 1rem, 3.5rem)",
          { lineHeight: "1.08", letterSpacing: "-0.035em", fontWeight: "700" },
        ],
        "display-md": [
          "clamp(1.75rem, 2vw + 1rem, 2.5rem)",
          { lineHeight: "1.12", letterSpacing: "-0.03em", fontWeight: "600" },
        ],
        "display-sm": [
          "clamp(1.5rem, 1.4vw + 1rem, 2rem)",
          { lineHeight: "1.2", letterSpacing: "-0.025em", fontWeight: "600" },
        ],
        h1: ["2.25rem", { lineHeight: "1.15", letterSpacing: "-0.025em", fontWeight: "600" }],
        h2: ["1.75rem", { lineHeight: "1.2", letterSpacing: "-0.02em", fontWeight: "600" }],
        h3: ["1.375rem", { lineHeight: "1.3", letterSpacing: "-0.015em", fontWeight: "600" }],
        h4: ["1.125rem", { lineHeight: "1.4", letterSpacing: "-0.01em", fontWeight: "600" }],
        body: ["0.9375rem", { lineHeight: "1.55" }],
        small: ["0.8125rem", { lineHeight: "1.5" }],
      },
      spacing: {
        "safe-x": "max(1.25rem, env(safe-area-inset-left))",
      },
      borderRadius: {
        sm: "4px",
        md: "6px",
        lg: "10px",
        xl: "14px",
        "2xl": "20px",
        "3xl": "28px",
      },
      boxShadow: {
        soft:
          "0 1px 2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 2)), 0 0 0 0.5px hsl(var(--color-border-default) / 0.5)",
        "glow-brand":
          "0 0 40px hsl(var(--color-brand-primary) / 0.25), 0 0 0 1px hsl(var(--color-brand-primary) / 0.3)",
        "glow-amber":
          "0 0 40px hsl(var(--color-brand-secondary) / 0.25), 0 0 0 1px hsl(var(--color-brand-secondary) / 0.3)",
        "glow-accent":
          "0 0 40px hsl(var(--color-accent) / 0.22), 0 0 0 1px hsl(var(--color-accent) / 0.28)",
        "depth-1":
          "0 1px 2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 2)), 0 2px 4px hsl(var(--shadow-color) / var(--shadow-strength))",
        "depth-2":
          "0 4px 8px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 2)), 0 8px 16px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 1.25))",
        "depth-3":
          "0 12px 24px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 2.2)), 0 24px 48px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 1.5))",
        "elev-1":
          "inset 0 0 0 1px hsl(var(--color-border-default) / 0.7), 0 1px 2px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 1.5))",
        "elev-2":
          "inset 0 0 0 1px hsl(var(--color-border-default) / 0.6), 0 12px 32px -10px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 2.5))",
        "elev-3":
          "inset 0 0 0 1px hsl(var(--color-border-default) / 0.5), 0 32px 64px -16px hsl(var(--shadow-color) / calc(var(--shadow-strength) * 3))",
      },
      backgroundImage: {
        "aurora-mesh":
          "radial-gradient(at 12% 8%, hsl(var(--color-brand-primary) / 0.32) 0px, transparent 48%), radial-gradient(at 88% 22%, hsl(var(--color-brand-secondary) / 0.24) 0px, transparent 52%), radial-gradient(at 46% 92%, hsl(var(--color-accent) / 0.22) 0px, transparent 56%)",
        aurora:
          "radial-gradient(at 20% 0%, hsl(var(--color-brand-primary) / 0.28) 0px, transparent 50%), radial-gradient(at 90% 20%, hsl(var(--color-brand-secondary) / 0.20) 0px, transparent 55%), radial-gradient(at 50% 100%, hsl(var(--color-accent) / 0.20) 0px, transparent 60%)",
        "grid-fade":
          "linear-gradient(to bottom, transparent, hsl(var(--color-bg-base)) 90%), linear-gradient(to right, hsl(var(--color-border-default) / 0.5) 1px, transparent 1px), linear-gradient(to bottom, hsl(var(--color-border-default) / 0.5) 1px, transparent 1px)",
        grid:
          "linear-gradient(to right, hsl(var(--color-border-default) / 0.6) 1px, transparent 1px), linear-gradient(to bottom, hsl(var(--color-border-default) / 0.6) 1px, transparent 1px)",
        noise:
          "url(\"data:image/svg+xml;utf8,<svg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.55 0'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>\")",
      },
      backgroundSize: {
        grid: "32px 32px",
        "grid-lg": "56px 56px",
      },
      keyframes: {
        aurora: {
          "0%": { transform: "translate3d(0,0,0) rotate(0deg)" },
          "50%": { transform: "translate3d(2%, -1%, 0) rotate(180deg)" },
          "100%": { transform: "translate3d(0,0,0) rotate(360deg)" },
        },
        "gradient-x": {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%": { backgroundPosition: "100% 50%" },
        },
        shimmer: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.6" },
        },
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        scan: {
          "0%": { transform: "translateY(-100%)", opacity: "0" },
          "8%": { opacity: "1" },
          "92%": { opacity: "1" },
          "100%": { transform: "translateY(100%)", opacity: "0" },
        },
      },
      animation: {
        aurora: "aurora 12s linear infinite",
        "gradient-x": "gradient-x 8s ease-in-out infinite",
        shimmer: "shimmer 2s linear infinite",
        "pulse-soft": "pulse-soft 4s ease-in-out infinite",
        "fade-in-up": "fade-in-up 400ms cubic-bezier(0.16, 1, 0.3, 1) both",
        scan: "scan 5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      transitionTimingFunction: {
        spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
        "out-expo": "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [],
};

export default config;
