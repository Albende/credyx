import { api } from "@/lib/api";
import { FLAGS } from "@/lib/countries";

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
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Adapter coverage</h1>
        <p className="text-muted text-sm mt-1">
          Auto-generated from live health checks. <code>ok</code> = ready,{" "}
          <code>degraded</code> = needs API key, <code>not_implemented</code> = next phase.
        </p>
      </header>

      {error && <div className="card border-bad/40 text-bad text-sm">{error}</div>}

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted">
            <tr>
              <th className="py-2 pr-3"></th>
              <th className="py-2 pr-3">Country</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Search</th>
              <th className="py-2 pr-3">Lookup</th>
              <th className="py-2 pr-3">Financials</th>
              <th className="py-2 pr-3">Notes</th>
            </tr>
          </thead>
          <tbody>
            {countries.map((c) => (
              <tr key={c.country_code} className="border-t border-border">
                <td className="py-2 pr-3 text-xl">{FLAGS[c.country_code] || "🏳️"}</td>
                <td className="py-2 pr-3">
                  <div className="font-medium">{c.country_code}</div>
                  <div className="text-xs text-muted">{c.name}</div>
                </td>
                <td className="py-2 pr-3">
                  <span className={`badge ${
                    c.status === "ok" ? "tag-good"
                    : c.status === "degraded" ? "tag-warn"
                    : c.status === "not_implemented" ? "" : "tag-bad"
                  }`}>{c.status}</span>
                </td>
                <td className="py-2 pr-3">{c.capabilities.search ? "✅" : "—"}</td>
                <td className="py-2 pr-3">{c.capabilities.lookup ? "✅" : "—"}</td>
                <td className="py-2 pr-3">{c.capabilities.financials ? "✅" : "—"}</td>
                <td className="py-2 pr-3 text-xs text-muted max-w-md">{c.notes || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
