import { Frown } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { FLAGS } from "@/lib/countries";
import { CompanyDetailView } from "@/components/app/CompanyDetailView";

export const dynamic = "force-dynamic";

export default async function CompanyPage(props: {
  params: Promise<{ country: string; identifier: string }>;
}) {
  const { country, identifier } = await props.params;
  const cc = country.toUpperCase();

  let detailsRes: Awaited<ReturnType<typeof api.company>> | null = null;
  let financialsRes: Awaited<ReturnType<typeof api.financials>> | null = null;
  let error: string | null = null;
  try {
    detailsRes = await api.company(cc, identifier);
    try {
      financialsRes = await api.financials(cc, identifier);
    } catch {
      financialsRes = null;
    }
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error || !detailsRes) {
    return (
      <div className="space-y-4">
        <Link href="/app/search" className="text-xs text-fg-muted hover:text-fg-default">
          ← Back to search
        </Link>
        <div className="rounded-lg border border-danger/30 bg-danger/10 p-8 text-center">
          <Frown className="mx-auto h-8 w-8 text-danger" />
          <div className="mt-3 text-base font-semibold">
            {FLAGS[cc] ?? "🏳️"} {cc} / {identifier}
          </div>
          <div className="mx-auto mt-2 max-w-md text-sm text-danger/80">
            {error ?? "Company not found"}
          </div>
        </div>
      </div>
    );
  }

  return (
    <CompanyDetailView
      country={cc}
      identifier={identifier}
      details={detailsRes.details}
      cached={detailsRes.cached}
      lastFetchedAt={detailsRes.last_fetched_at}
      filings={financialsRes?.filings ?? []}
      financialsCached={financialsRes?.cached ?? false}
    />
  );
}
