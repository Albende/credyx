import { api } from "@/lib/api";
import { FLAGS } from "@/lib/countries";
import CompanyView from "@/components/CompanyView";

export const dynamic = "force-dynamic";

export default async function CompanyPage(props: {
  params: Promise<{ country: string; identifier: string }>;
}) {
  const { country, identifier } = await props.params;
  const cc = country.toUpperCase();
  let details: Awaited<ReturnType<typeof api.company>> | null = null;
  let financials: Awaited<ReturnType<typeof api.financials>> | null = null;
  let error: string | null = null;
  try {
    details = await api.company(cc, identifier);
    try {
      financials = await api.financials(cc, identifier);
    } catch (e) {
      // financials may not be implemented for this country; surface inline
      financials = null;
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !details) {
    return (
      <div className="card border-bad/40 text-sm">
        <div className="text-bad font-medium mb-1">
          {(FLAGS[cc] || "🏳️")} {cc} / {identifier}
        </div>
        <div className="text-muted">{error || "Company not found"}</div>
      </div>
    );
  }

  return (
    <CompanyView
      country={cc}
      identifier={identifier}
      details={details.details}
      cached={details.cached}
      filings={financials?.filings || []}
      financialsCached={financials?.cached || false}
    />
  );
}
