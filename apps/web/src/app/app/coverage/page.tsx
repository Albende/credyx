import { Globe } from "lucide-react";
import { api } from "@/lib/api";
import { CoverageExplorer } from "@/components/app/CoverageExplorer";

export const dynamic = "force-dynamic";

export default async function CoveragePage() {
  let countries: Awaited<ReturnType<typeof api.countries>>["countries"] = [];
  let error: string | null = null;
  try {
    countries = (await api.countries()).countries;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  return (
    <div className="space-y-8">
      <header className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-[0.18em] text-brand-primary">
          <Globe className="h-3.5 w-3.5" />
          Coverage
        </div>
        <h1 className="font-display text-3xl font-semibold tracking-tight md:text-4xl">
          Adapter coverage
        </h1>
        <p className="max-w-2xl text-sm text-fg-muted md:text-base">
          Every adapter is auto-health-checked. Filter by status or capability to find where
          live data is available right now.
        </p>
      </header>

      {error ? (
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-4 text-sm text-danger">
          {error}
        </div>
      ) : (
        <CoverageExplorer countries={countries} />
      )}
    </div>
  );
}
