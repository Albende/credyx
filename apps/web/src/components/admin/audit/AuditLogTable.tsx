"use client";
import { useEffect, useState } from "react";
import { format } from "date-fns";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { apiFetch } from "@/lib/api-client";
import type { AuditLogEntry } from "../users/types";

interface AuditResponse {
  entries: AuditLogEntry[];
  total: number;
}

function formatDate(iso: string) {
  try {
    return format(new Date(iso), "PPp");
  } catch {
    return iso;
  }
}

export function AuditLogTable({ initialData }: { initialData: AuditResponse }) {
  const [data, setData] = useState<AuditResponse>(initialData);
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [targetType, setTargetType] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    const params = new URLSearchParams();
    if (actor) params.set("actor", actor);
    if (action) params.set("action", action);
    if (targetType) params.set("target_type", targetType);
    if (start) params.set("start", start);
    if (end) params.set("end", end);

    const handle = setTimeout(() => {
      apiFetch<AuditResponse>(`/api/admin/audit-log?${params.toString()}`)
        .then(setData)
        .catch(() => undefined);
    }, 250);
    return () => clearTimeout(handle);
  }, [actor, action, targetType, start, end]);

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="mt-1 text-sm text-muted">All admin actions, immutable.</p>
      </div>

      <Card>
        <CardContent className="grid gap-3 md:grid-cols-5">
          <div className="space-y-1.5">
            <Label htmlFor="actor">Actor</Label>
            <Input id="actor" value={actor} onChange={(e) => setActor(e.target.value)} placeholder="email" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="action">Action</Label>
            <Input id="action" value={action} onChange={(e) => setAction(e.target.value)} placeholder="grant_plan" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="target_type">Target type</Label>
            <Input id="target_type" value={targetType} onChange={(e) => setTargetType(e.target.value)} placeholder="user" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="start">From</Label>
            <Input id="start" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="end">To</Label>
            <Input id="end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </CardContent>
      </Card>

      <Card>
        {data.entries.length === 0 ? (
          <EmptyState title="No entries" description="No audit log entries match the filters." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>Time</TableHead>
                <TableHead>Actor</TableHead>
                <TableHead>Action</TableHead>
                <TableHead>Target</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.entries.map((e) => {
                const isOpen = expanded.has(e.id);
                return (
                  <>
                    <TableRow key={e.id} className="cursor-pointer" onClick={() => toggle(e.id)}>
                      <TableCell>
                        {isOpen ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      </TableCell>
                      <TableCell className="text-muted">{formatDate(e.created_at)}</TableCell>
                      <TableCell>{e.actor_email ?? <span className="text-muted">system</span>}</TableCell>
                      <TableCell className="font-mono text-xs">{e.action}</TableCell>
                      <TableCell className="text-xs text-muted">
                        {e.target_type ? `${e.target_type}/${e.target_id ?? "—"}` : "—"}
                      </TableCell>
                    </TableRow>
                    {isOpen ? (
                      <TableRow key={`${e.id}-payload`}>
                        <TableCell colSpan={5}>
                          <pre className="overflow-auto rounded bg-bg p-3 text-[11px] text-muted">
                            {JSON.stringify(e.payload ?? {}, null, 2)}
                          </pre>
                        </TableCell>
                      </TableRow>
                    ) : null}
                  </>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
