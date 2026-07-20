import { BillingHistory, type Invoice } from "@/components/account/BillingHistory";
import { apiFetch } from "@/lib/api-client";

async function fetchInvoices(): Promise<Invoice[]> {
  try {
    const data = await apiFetch<{ invoices: Invoice[] }>("/api/billing/invoices", { serverSide: true });
    return data.invoices ?? [];
  } catch {
    return [];
  }
}

export default async function BillingPage() {
  const invoices = await fetchInvoices();
  return <BillingHistory invoices={invoices} />;
}
