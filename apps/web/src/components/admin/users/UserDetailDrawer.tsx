"use client";
import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Drawer, DrawerBody, DrawerContent, DrawerHeader, DrawerTitle, DrawerDescription } from "@/components/ui/drawer";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";
import { GrantPlanForm } from "./GrantPlanForm";
import { RevokeSubscriptionDialog } from "./RevokeSubscriptionDialog";
import type { AdminSubscription, AdminUser, AuditLogEntry } from "./types";

interface FullUserDetail {
  user: AdminUser;
  subscription: AdminSubscription | null;
  audit_log: AuditLogEntry[];
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return format(new Date(iso), "PPp");
  } catch {
    return iso;
  }
}

export function UserDetailDrawer({
  userId,
  onClose,
  onUserChanged,
}: {
  userId: string | null;
  onClose: () => void;
  onUserChanged: (u: AdminUser) => void;
}) {
  const [detail, setDetail] = useState<FullUserDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [savingRole, setSavingRole] = useState(false);

  useEffect(() => {
    if (!userId) {
      setDetail(null);
      return;
    }
    setLoading(true);
    apiFetch<FullUserDetail>(`/api/admin/users/${userId}`)
      .then(setDetail)
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [userId]);

  async function saveRole(role: "user" | "admin") {
    if (!detail) return;
    setSavingRole(true);
    try {
      const updated = await apiFetch<AdminUser>(`/api/admin/users/${detail.user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      });
      toast.success("Role updated");
      setDetail({ ...detail, user: updated });
      onUserChanged(updated);
    } catch (e) {
      const detailMsg = e instanceof ApiError ? e.message : "Failed to update";
      toast.error(detailMsg);
    } finally {
      setSavingRole(false);
    }
  }

  function refresh() {
    if (!userId) return;
    apiFetch<FullUserDetail>(`/api/admin/users/${userId}`).then(setDetail).catch(() => undefined);
  }

  return (
    <Drawer open={userId !== null} onOpenChange={(v) => !v && onClose()}>
      <DrawerContent>
        {loading || !detail ? (
          <>
            <DrawerHeader>
              <DrawerTitle>Loading user…</DrawerTitle>
            </DrawerHeader>
            <DrawerBody className="space-y-3">
              <Skeleton className="h-6 w-40" />
              <Skeleton className="h-32 w-full" />
            </DrawerBody>
          </>
        ) : (
          <>
            <DrawerHeader>
              <DrawerTitle>{detail.user.email}</DrawerTitle>
              <DrawerDescription>
                Joined {formatDate(detail.user.created_at)}{" "}
                {detail.user.is_verified ? <Badge variant="success">Verified</Badge> : <Badge variant="secondary">Unverified</Badge>}
              </DrawerDescription>
            </DrawerHeader>
            <DrawerBody>
              <Tabs defaultValue="profile">
                <TabsList>
                  <TabsTrigger value="profile">Profile</TabsTrigger>
                  <TabsTrigger value="subscription">Subscription</TabsTrigger>
                  <TabsTrigger value="audit">Audit</TabsTrigger>
                </TabsList>

                <TabsContent value="profile" className="space-y-4">
                  <dl className="grid grid-cols-2 gap-3 text-sm">
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">First name</dt>
                      <dd>{detail.user.first_name || <span className="text-muted">—</span>}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">Last name</dt>
                      <dd>{detail.user.last_name || <span className="text-muted">—</span>}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">User ID</dt>
                      <dd className="font-mono text-xs">{detail.user.id}</dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-wider text-muted">Joined</dt>
                      <dd>{formatDate(detail.user.created_at)}</dd>
                    </div>
                  </dl>
                  <div className="space-y-1.5">
                    <Label>Role</Label>
                    <div className="flex items-center gap-2">
                      <Select value={detail.user.role} onValueChange={(v) => saveRole(v as "user" | "admin")}>
                        <SelectTrigger className="w-40">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="user">User</SelectItem>
                          <SelectItem value="admin">Admin</SelectItem>
                        </SelectContent>
                      </Select>
                      {savingRole ? <span className="text-xs text-muted">Saving…</span> : null}
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="subscription" className="space-y-6">
                  {detail.subscription ? (
                    <div className="rounded-lg border border-border p-4 text-sm">
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="font-medium">{detail.subscription.plan.name}</div>
                          <div className="text-xs text-muted">
                            {detail.subscription.billing_period} · renews {formatDate(detail.subscription.current_period_end)}
                          </div>
                        </div>
                        <Badge variant={detail.subscription.status === "active" ? "success" : "warning"}>
                          {detail.subscription.status}
                        </Badge>
                      </div>
                      <div className="mt-3">
                        <Button variant="destructive" size="sm" onClick={() => setRevokeOpen(true)}>
                          Revoke subscription
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-muted">No active subscription.</p>
                  )}

                  <div>
                    <h4 className="mb-2 text-xs uppercase tracking-wider text-muted">Grant plan</h4>
                    <GrantPlanForm userId={detail.user.id} onSuccess={refresh} />
                  </div>
                </TabsContent>

                <TabsContent value="audit">
                  {detail.audit_log.length === 0 ? (
                    <EmptyState title="No audit entries" description="No actions have been logged for this user." />
                  ) : (
                    <ul className="space-y-2 text-sm">
                      {detail.audit_log.map((e) => (
                        <li key={e.id} className="rounded-md border border-border p-3">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-xs">{e.action}</span>
                            <span className="text-xs text-muted">{formatDate(e.created_at)}</span>
                          </div>
                          {e.actor_email ? <div className="text-xs text-muted">by {e.actor_email}</div> : null}
                          {e.payload ? (
                            <pre className="mt-2 overflow-auto rounded bg-bg p-2 text-[11px] text-muted">
                              {JSON.stringify(e.payload, null, 2)}
                            </pre>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </TabsContent>
              </Tabs>
            </DrawerBody>

            <RevokeSubscriptionDialog
              userId={detail.user.id}
              open={revokeOpen}
              onOpenChange={setRevokeOpen}
              onRevoked={refresh}
            />
          </>
        )}
      </DrawerContent>
    </Drawer>
  );
}
