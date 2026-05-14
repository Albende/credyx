import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "CreditLens — B2B Credit Intelligence",
  description: "Search company registries across Europe, Turkey, and the USA. Fetch real filed financials and run AI credit risk analysis.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <div className="min-h-screen">
          <header className="border-b border-border bg-surface/50 backdrop-blur sticky top-0 z-10">
            <div className="mx-auto max-w-6xl px-6 py-3 flex items-center justify-between">
              <Link href="/" className="font-semibold tracking-tight">
                <span className="text-accent">Credit</span>Lens
              </Link>
              <nav className="flex items-center gap-4 text-sm text-muted">
                <Link href="/" className="hover:text-text">Search</Link>
                <Link href="/coverage" className="hover:text-text">Coverage</Link>
                <a
                  href="http://localhost:8000/docs"
                  target="_blank"
                  rel="noreferrer"
                  className="hover:text-text"
                >
                  API
                </a>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-6 py-10">{children}</main>
          <footer className="mx-auto max-w-6xl px-6 pb-12 pt-4 text-xs text-muted">
            Data sources: government registries (UK Companies House, SEC EDGAR, INSEE Sirene,
            Brønnøysund, PRH, ARES, Inforegister) + GLEIF + OpenCorporates + OpenSanctions.
            No commercial paid APIs in this MVP.
          </footer>
        </div>
      </body>
    </html>
  );
}
