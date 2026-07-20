import { Search } from "lucide-react";
import { api } from "@/lib/api";
import { SmartSearch } from "@/components/app/SmartSearch";

export const dynamic = "force-dynamic";

interface SearchProps {
  searchParams: Promise<{ country?: string }>;
}

export default async function SearchPage({ searchParams }: SearchProps) {
  const params = await searchParams;
  let countries: Awaited<ReturnType<typeof api.countries>>["countries"] = [];
  let error: string | null = null;
  try {
    const data = await api.countries();
    countries = data.countries;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-brand-primary">
          <Search className="h-3.5 w-3.5" />
          Search
        </div>
        <h1 className="font-display text-3xl font-semibold tracking-tight md:text-4xl">
          Company search
        </h1>
        <p className="max-w-2xl text-sm text-fg-muted md:text-base">
          Pick a country, then search by company name or registry identifier. Results pull
          live from official registries — never mocked.
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
          Could not load adapters: {error}
        </div>
      ) : (
        <SmartSearch countries={countries} defaultCountry={params.country} />
      )}

      <section className="rounded-lg border border-border-default bg-bg-elevated p-5">
        <h2 className="text-sm font-semibold tracking-tight">Tips</h2>
        <ul className="mt-3 space-y-2 text-sm text-fg-muted">
          <li className="flex gap-2">
            <span className="text-brand-primary">→</span>
            Start typing in the country box to filter by country name or ISO code.
          </li>
          <li className="flex gap-2">
            <span className="text-brand-primary">→</span>
            Switch to <b className="text-fg-default">By identifier</b> when you already have
            a Companies House number, SIREN, KvK, KRS, etc.
          </li>
          <li className="flex gap-2">
            <span className="text-brand-primary">→</span>
            Name search auto-runs after you pause typing — no need to hit Search.
          </li>
        </ul>
      </section>
    </div>
  );
}
