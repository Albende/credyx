"use client";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api, type CompanyMatch, type CountryHealth } from "@/lib/api";
import { FLAGS, IDENTIFIER_LABELS } from "@/lib/countries";

type Mode = "name" | "identifier";

export default function SearchPanel({ countries }: { countries: CountryHealth[] }) {
  const router = useRouter();
  const usable = useMemo(
    () => countries.filter((c) => c.status === "ok" || c.status === "degraded"),
    [countries],
  );
  const [country, setCountry] = useState<string>(usable[0]?.country_code || "GB");
  const [mode, setMode] = useState<Mode>("name");
  const [value, setValue] = useState("");
  const [results, setResults] = useState<CompanyMatch[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setResults([]);
    setErr(null);
  }, [country, mode]);

  const labels = IDENTIFIER_LABELS[country] || { primary: "Identifier", placeholder: "" };

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      if (mode === "name") {
        const data = await api.search(country, value);
        setResults(data.results);
      } else {
        router.push(`/company/${country}/${encodeURIComponent(value.trim())}`);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-muted">Country</label>
        <select
          value={country}
          onChange={(e) => setCountry(e.target.value)}
          className="input max-w-[14rem]"
        >
          {countries.map((c) => (
            <option key={c.country_code} value={c.country_code}>
              {(FLAGS[c.country_code] || "🏳️") + "  " + c.country_code + " — " + c.name +
                (c.status === "ok" ? "" : c.status === "degraded" ? " (needs key)" : " (soon)")}
            </option>
          ))}
        </select>

        <div className="ml-auto flex rounded-lg border border-border overflow-hidden">
          <button
            onClick={() => setMode("name")}
            className={`px-3 py-1.5 text-sm ${mode === "name" ? "bg-accent text-black" : "hover:bg-white/5"}`}
          >
            Search by name
          </button>
          <button
            onClick={() => setMode("identifier")}
            className={`px-3 py-1.5 text-sm ${mode === "identifier" ? "bg-accent text-black" : "hover:bg-white/5"}`}
          >
            Lookup by {labels.primary}
          </button>
        </div>
      </div>

      <form onSubmit={run} className="flex gap-2">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={mode === "name" ? "Company name..." : labels.placeholder || labels.primary}
          className="input"
        />
        <button type="submit" disabled={!value.trim() || loading} className="btn btn-primary">
          {loading ? "Loading..." : mode === "name" ? "Search" : "Lookup"}
        </button>
      </form>

      {err && <div className="text-bad text-sm">{err}</div>}

      {results.length > 0 && (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {results.map((r) => (
            <li key={r.id} className="px-4 py-3 hover:bg-white/5">
              <a
                href={`/company/${country}/${encodeURIComponent(r.id)}`}
                className="flex items-start justify-between gap-4"
              >
                <div>
                  <div className="font-medium">{r.name}</div>
                  <div className="text-xs text-muted">
                    {r.identifiers.map((i) => `${i.label || i.type}: ${i.value}`).join(" · ")}
                    {r.address ? ` · ${r.address}` : ""}
                  </div>
                </div>
                {r.status && <span className="badge tag-good shrink-0">{r.status}</span>}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
