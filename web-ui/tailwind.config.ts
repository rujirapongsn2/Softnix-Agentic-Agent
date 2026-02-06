import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(220 14% 90%)",
        input: "hsl(220 14% 90%)",
        ring: "hsl(210 80% 45%)",
        background: "hsl(220 22% 98%)",
        foreground: "hsl(224 26% 12%)",
        primary: {
          DEFAULT: "hsl(150 70% 27%)",
          foreground: "hsl(145 80% 96%)"
        },
        secondary: {
          DEFAULT: "hsl(210 18% 94%)",
          foreground: "hsl(224 18% 20%)"
        },
        muted: {
          DEFAULT: "hsl(210 18% 94%)",
          foreground: "hsl(220 9% 45%)"
        },
        accent: {
          DEFAULT: "hsl(24 95% 90%)",
          foreground: "hsl(18 67% 27%)"
        },
        card: {
          DEFAULT: "hsl(0 0% 100%)",
          foreground: "hsl(224 26% 12%)"
        }
      },
      borderRadius: {
        lg: "0.8rem",
        md: "0.6rem",
        sm: "0.4rem"
      },
      boxShadow: {
        float: "0 16px 40px -20px rgba(13, 35, 24, 0.35)"
      }
    }
  },
  plugins: []
} satisfies Config;
