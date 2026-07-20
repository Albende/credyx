import { AuditLogTable } from "@/components/admin/audit/AuditLogTable";
import { apiFetch } from "@/lib/api-client";
import type { AuditLogEntry } from "@/components/admin/users/types";

async function fetchAudit(): Promise<{ entries: AuditLogEntry[]; total: number }> {
  try {
    return await apiFetch<{ entries: AuditLogEntry[]; total: number }>("/api/admin/audit-log", {
      serverSide: true,
    });
  } catch {
    return { entries: [], total: 0 };
  }
}

export default async function AuditLogPage() {
  const data = await fetchAudit();
  return <AuditLogTable initialData={data} />;
}
