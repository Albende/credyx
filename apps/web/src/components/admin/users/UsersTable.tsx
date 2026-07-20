"use client";
import { useEffect, useState, useTransition } from "react";
import { format } from "date-fns";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { apiFetch } from "@/lib/api-client";
import { UserDetailDrawer } from "./UserDetailDrawer";
import type { AdminUser, AdminUsersResponse } from "./types";

const PAGE_SIZE = 25;

function formatDate(iso: string): string {
  try {
    return format(new Date(iso), "PP");
  } catch {
    return iso;
  }
}

interface Filters {
  search: string;
  role: "all" | "user" | "admin";
  verified: boolean;
  hasSub: boolean;
}

export function UsersTable({ initialData }: { initialData: AdminUsersResponse }) {
  const [data, setData] = useState<AdminUsersResponse>(initialData);
  const [page, setPage] = useState(1);
  const [filters, setFilters] = useState<Filters>({ search: "", role: "all", verified: false, hasSub: false });
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    if (filters.search) params.set("search", filters.search);
    if (filters.role !== "all") params.set("role", filters.role);
    if (filters.verified) params.set("verified", "true");
    if (filters.hasSub) params.set("has_sub", "true");

    const handle = setTimeout(() => {
      startTransition(async () => {
        try {
          const result = await apiFetch<AdminUsersResponse>(`/api/admin/users?${params.toString()}`);
          setData(result);
        } catch {
          /* keep stale data; toast handled by mutations only */
        }
      });
    }, 250);
    return () => clearTimeout(handle);
  }, [page, filters]);

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-muted">All registered users. Click a row to manage.</p>
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-end gap-4">
          <div className="min-w-[220px] flex-1 space-y-1.5">
            <Label htmlFor="user_search">Search</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
              <Input
                id="user_search"
                value={filters.search}
                onChange={(e) => {
                  setPage(1);
                  setFilters((f) => ({ ...f, search: e.target.value }));
                }}
                placeholder="email or name"
                className="pl-9"
              />
            </div>
          </div>
          <div className="w-40 space-y-1.5">
            <Label>Role</Label>
            <Select
              value={filters.role}
              onValueChange={(v) => {
                setPage(1);
                setFilters((f) => ({ ...f, role: v as Filters["role"] }));
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All roles</SelectItem>
                <SelectItem value="user">User</SelectItem>
                <SelectItem value="admin">Admin</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <label className="flex items-center gap-2">
            <Switch
              checked={filters.verified}
              onCheckedChange={(v) => {
                setPage(1);
                setFilters((f) => ({ ...f, verified: v }));
              }}
            />
            <span className="text-sm">Verified only</span>
          </label>
          <label className="flex items-center gap-2">
            <Switch
              checked={filters.hasSub}
              onCheckedChange={(v) => {
                setPage(1);
                setFilters((f) => ({ ...f, hasSub: v }));
              }}
            />
            <span className="text-sm">Has subscription</span>
          </label>
        </CardContent>
      </Card>

      <Card>
        {data.users.length === 0 ? (
          <CardContent>
            <EmptyState title="No users found" description="Try adjusting filters." />
          </CardContent>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Email</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Verified</TableHead>
                <TableHead>Plan</TableHead>
                <TableHead>Joined</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.users.map((u) => (
                <TableRow key={u.id} className="cursor-pointer" onClick={() => setSelectedUserId(u.id)}>
                  <TableCell className="font-medium">{u.email}</TableCell>
                  <TableCell>
                    {[u.first_name, u.last_name].filter(Boolean).join(" ") || (
                      <span className="text-muted">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.role === "admin" ? "warning" : "secondary"}>{u.role}</Badge>
                  </TableCell>
                  <TableCell>
                    {(u.email_verified ?? u.is_verified) ? <Badge variant="success">Verified</Badge> : <Badge variant="secondary">No</Badge>}
                  </TableCell>
                  <TableCell>
                    {(u.active_plan_slug ?? u.plan_slug) ? <Badge>{u.active_plan_slug ?? u.plan_slug}</Badge> : <span className="text-muted">free</span>}
                  </TableCell>
                  <TableCell className="text-muted">{formatDate(u.created_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <div className="flex items-center justify-between">
        <div className="text-xs text-muted">
          {data.total.toLocaleString()} users · page {page} of {totalPages}
          {pending ? " · refreshing…" : ""}
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft className="h-4 w-4" /> Prev
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <UserDetailDrawer
        userId={selectedUserId}
        onClose={() => setSelectedUserId(null)}
        onUserChanged={(updated: AdminUser) =>
          setData((d) => ({ ...d, users: d.users.map((u) => (u.id === updated.id ? updated : u)) }))
        }
      />
    </div>
  );
}
