import type { Config } from "tailwindcss";

/**
 * ChAAMP design system — Tailwind theme.
 *
 * Source of truth for these tokens is docs/design/DESIGN_SYSTEM.md.
 * Do not invent new colors here; everything derives from indigo + the
 * teal pairing reserved for the audio gradient.
 */
const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0F172A",
        slate: {
          50: "#F8FAFC",
          100: "#F1F5F9",
          200: "#E2E8F0",
          300: "#CBD5E1",
          400: "#94A3B8",
          500: "#64748B",
          600: "#475569",
          700: "#334155",
          800: "#1E293B",
          900: "#0F172A",
        },
        surface: {
          DEFAULT: "#FAFAF7",     // warm off-white, app background
          2: "#F4F3EE",           // section dividers, info chips
        },
        card: "#FFFFFF",
        accent: {
          DEFAULT: "#4F46E5",     // indigo-500-ish — brand
          700: "#4338CA",         // hover for accent buttons
          soft: "#EEF2FF",        // accent badge bg, selected-nav bg
          softer: "#F5F6FF",      // tinted card bg for staged/info content
        },
        teal: {
          DEFAULT: "#06B6D4",     // secondary accent — gradient pair only
        },
        success: {
          DEFAULT: "#059669",
          soft: "#ECFDF5",
        },
        warning: {
          DEFAULT: "#D97706",
          soft: "#FFFBEB",
        },
        critical: {
          DEFAULT: "#DC2626",
          soft: "#FEF2F2",
        },
      },
      backgroundImage: {
        // Brand gradient — logo, assistant avatar, accent rails. Used sparingly.
        "audio-gradient": "linear-gradient(90deg, #4F46E5 0%, #06B6D4 100%)",
        "audio-gradient-soft": "linear-gradient(90deg, rgba(79,70,229,0.10) 0%, rgba(6,182,212,0.10) 100%)",
      },
      borderRadius: {
        // r-1..r-4 from design tokens, plus the standards
        "1": "6px",
        "2": "10px",
        "3": "14px",
        "4": "20px",
      },
      boxShadow: {
        "1": "0 1px 2px rgba(15,23,42,.04)",
        "2": "0 1px 2px rgba(15,23,42,.04), 0 8px 24px -8px rgba(15,23,42,.08)",
        "3": "0 1px 2px rgba(15,23,42,.04), 0 12px 40px -12px rgba(15,23,42,.16)",
        "modal": "0 24px 64px -12px rgba(15,23,42,.24), 0 4px 12px rgba(15,23,42,.08)",
      },
      fontFamily: {
        ui: ["Inter", "system-ui", "-apple-system", "BlinkMacSystemFont", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
      fontSize: {
        // Scale from the README: 10..28px. Tailwind defaults are close;
        // we add the project-specific sizes the design uses heavily.
        "10": ["10px", { lineHeight: "1.4" }],
        "11": ["11px", { lineHeight: "1.4" }],
        "12": ["12px", { lineHeight: "1.5" }],
        "13": ["13px", { lineHeight: "1.5" }],
        "14": ["14px", { lineHeight: "1.6" }],   // body default
        "15": ["15px", { lineHeight: "1.6" }],
        "17": ["17px", { lineHeight: "1.4" }],
        "18": ["18px", { lineHeight: "1.4" }],
        "20": ["20px", { lineHeight: "1.3" }],
        "22": ["22px", { lineHeight: "1.3" }],
        "28": ["28px", { lineHeight: "1.2", letterSpacing: "-0.01em" }],
      },
      letterSpacing: {
        tight: "-0.01em",
        tighter: "-0.02em",
        "label-caps": "0.06em",
      },
      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "none" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "pulse-dot": {
          "0%, 100%": { boxShadow: "0 0 0 0 currentColor" },
          "50%":      { boxShadow: "0 0 0 6px transparent" },
        },
      },
      animation: {
        "fade-up": "fade-up .25s ease",
        "fade-in": "fade-in .15s ease",
        "pulse-dot": "pulse-dot 2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
