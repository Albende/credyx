import Link from "next/link";
import { api } from "@/lib/api";
import { FLAGS } from "@/lib/countries";
import SearchPanel from "@/components/SearchPanel";

export const dynamic = "force-dynamic";

export default async function Home() {
  let countries: Awaited<ReturnType<typeof api.countries>>["countries"] = [];
  let error: string | null = null;
  try {
    const data = await api.countries();
    countries = data.countries;
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  const usable = countries.filter((c) => c.status === "ok" || c.status === "degraded");

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-3xl font-semibold tracking-tight">B2B Credit Intelligence</h1>
        <p className="mt-2 max-w-2xl text-muted">
          Search real company data from official European, Turkish, and US government
          registries. Pull filed balance sheets, then run an AI-powered credit risk
          analysis end to end.
        </p>
      </section>

      {error && (
        <div className="card border-bad/40 bg-bad/10 text-bad text-sm">
          Could not load adapter status: {error}
        </div>
      )}

      <SearchPanel countries={countries} />

      <section className="space-y-3">
        <h2 className="text-sm uppercase tracking-wider text-muted">
          Live adapter coverage ({usable.length}/{countries.length} usable)
        </h2>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
          {countries.map((c) => (
            <Link
              key={c.country_code}
              href={`/?country=${c.country_code}`}
              className="card flex flex-col gap-1 hover:border-accent/60 transition"
            >
              <div className="flex items-center gap-2">
                <span className="text-xl">{FLAGS[c.country_code] || "🏳️"}</span>
                <span className="text-sm font-medium">{c.country_code}</span>
              </div>
              <div className="text-xs text-muted truncate">{c.name}</div>
              <StatusBadge status={c.status} />
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "ok"
      ? "tag-good"
      : status === "degraded"
        ? "tag-warn"
        : status === "not_implemented"
          ? ""
          : "tag-bad";
  const label =
    status === "ok"
      ? "live"
      : status === "degraded"
        ? "needs key"
        : status === "not_implemented"
          ? "soon"
          : status;
  return <span className={`badge ${cls}`}>{label}</span>;
}
