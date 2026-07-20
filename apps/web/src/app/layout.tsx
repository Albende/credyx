import "./globals.css";
import type { Metadata } from "next";
import { cookies } from "next/headers";
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
  axes: ["opsz"],
});

const jb = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["400", "500"],
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://credyx.ai"),
  title: "Credyx — Credit intelligence at registry-speed",
  description:
    "Live data, audit-ready reports. Pull official registry filings and score B2B credit risk in seconds across 100+ jurisdictions.",
};

const themeScript = `
(function () {
  try {
    var stored = localStorage.getItem('cl-theme');
    var selection = stored === 'light' || stored === 'dark' || stored === 'system' ? stored : null;
    if (!selection) return;
    var effective;
    if (selection === 'system') {
      effective = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    } else {
      effective = selection;
    }
    var root = document.documentElement;
    var isDark = root.classList.contains('dark');
    if ((effective === 'dark') !== isDark) {
      root.classList.toggle('dark', effective === 'dark');
      root.style.colorScheme = effective;
    }
  } catch (e) {
    /* ignore */
  }
})();
`;

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const cookieValue = cookieStore.get("cl-theme")?.value;
  const selection: "system" | "light" | "dark" =
    cookieValue === "light" || cookieValue === "dark" || cookieValue === "system"
      ? cookieValue
      : "dark";
  const initialEffective: "light" | "dark" =
    selection === "light" ? "light" : "dark";

  return (
    <html
      lang="en"
      className={`${initialEffective === "dark" ? "dark" : ""} ${inter.variable} ${fraunces.variable} ${jb.variable}`}
      style={{ colorScheme: initialEffective }}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="font-sans antialiased bg-bg-base text-fg-default min-h-screen">
        {children}
      </body>
    </html>
  );
}
