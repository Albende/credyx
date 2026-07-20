"use client";
import { format } from "date-fns";
import { Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";

export interface Invoice {
  id: string;
  number: string;
  created_at: string;
  amount_cents: number;
  currency: string;
  status: "paid" | "open" | "void" | "uncollectible";
  pdf_url: string | null;
}

function formatMoney(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: currency.toUpperCase() }).format(cents / 100);
}

function formatDate(iso: string) {
  try {
    return format(new Date(iso), "PP");
  } catch {
    return iso;
  }
}

export function BillingHistory({ invoices }: { invoices: Invoice[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Billing history</CardTitle>
        <CardDescription>All invoices issued for your subscription.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {invoices.length === 0 ? (
          <div className="p-5">
            <EmptyState title="No invoices yet" description="Invoices appear here after your first paid period." />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Number</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">PDF</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.map((inv) => (
                <TableRow key={inv.id}>
                  <TableCell className="font-mono text-xs">{inv.number}</TableCell>
                  <TableCell>{formatDate(inv.created_at)}</TableCell>
                  <TableCell className="tabular-nums">{formatMoney(inv.amount_cents, inv.currency)}</TableCell>
                  <TableCell>
                    <Badge variant={inv.status === "paid" ? "success" : inv.status === "open" ? "warning" : "secondary"}>
                      {inv.status}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {inv.pdf_url ? (
                      <a
                        href={inv.pdf_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-accent hover:underline"
                      >
                        <Download className="h-3 w-3" /> Download
                      </a>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
