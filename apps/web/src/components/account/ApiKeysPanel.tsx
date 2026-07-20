"use client";
import { useState } from "react";
import { format } from "date-fns";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import { apiFetch, ApiError } from "@/lib/api-client";

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at: string | null;
  created_at: string;
}

function formatDate(iso: string | null): string {
  if (!iso) return "Never";
  try {
    return format(new Date(iso), "PPp");
  } catch {
    return iso;
  }
}

function CreateKeyDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  onCreated: (key: ApiKey & { key: string }) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function create() {
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }
    setBusy(true);
    try {
      const result = await apiFetch<ApiKey & { key: string }>("/api/auth/api-keys", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      onCreated(result);
      setName("");
      onOpenChange(false);
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to create key";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create API key</DialogTitle>
          <DialogDescription>Give the key a descriptive name. You'll see it once.</DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="key_name">Name</Label>
          <Input
            id="key_name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Production server"
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={create} disabled={busy}>
            {busy ? "Creating..." : "Create key"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevealDialog({
  apiKey,
  onClose,
}: {
  apiKey: (ApiKey & { key: string }) | null;
  onClose: () => void;
}) {
  const [stored, setStored] = useState(false);

  async function copy() {
    if (!apiKey) return;
    try {
      await navigator.clipboard.writeText(apiKey.key);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Clipboard access denied");
    }
  }

  return (
    <Dialog
      open={apiKey !== null}
      onOpenChange={(v) => {
        if (!v && stored) {
          setStored(false);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Your new API key</DialogTitle>
          <DialogDescription>
            This is the only time we'll show this key. Store it somewhere safe before closing.
          </DialogDescription>
        </DialogHeader>
        {apiKey ? (
          <div className="space-y-3">
            <div className="rounded-lg border border-border bg-bg p-3 font-mono text-xs break-all">{apiKey.key}</div>
            <Button type="button" variant="secondary" size="sm" onClick={copy}>
              <Copy className="h-3 w-3" /> Copy
            </Button>
            <label className="flex items-center gap-2 pt-2 text-sm">
              <input
                type="checkbox"
                checked={stored}
                onChange={(e) => setStored(e.target.checked)}
                className="rounded border-border"
              />
              I've stored it safely
            </label>
          </div>
        ) : null}
        <DialogFooter>
          <Button
            disabled={!stored}
            onClick={() => {
              setStored(false);
              onClose();
            }}
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RevokeDialog({
  keyToRevoke,
  onClose,
  onRevoked,
}: {
  keyToRevoke: ApiKey | null;
  onClose: () => void;
  onRevoked: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  async function revoke() {
    if (!keyToRevoke) return;
    setBusy(true);
    try {
      await apiFetch<void>(`/api/auth/api-keys/${keyToRevoke.id}`, { method: "DELETE" });
      toast.success("Key revoked");
      onRevoked(keyToRevoke.id);
      onClose();
    } catch (e) {
      const detail = e instanceof ApiError ? e.message : "Failed to revoke";
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open={keyToRevoke !== null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Revoke API key?</DialogTitle>
          <DialogDescription>
            Any service using <span className="font-mono">{keyToRevoke?.key_prefix}…</span> will immediately stop
            working. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={revoke} disabled={busy}>
            {busy ? "Revoking..." : "Revoke"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function ApiKeysPanel({ initialKeys }: { initialKeys: ApiKey[] }) {
  const [keys, setKeys] = useState<ApiKey[]>(initialKeys);
  const [createOpen, setCreateOpen] = useState(false);
  const [revealed, setRevealed] = useState<(ApiKey & { key: string }) | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle>API keys</CardTitle>
            <CardDescription>Use these to authenticate the Credyx REST API.</CardDescription>
          </div>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> New key
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {keys.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="No API keys yet"
              description="Create one to programmatically access the Credyx API."
              icon={<KeyRound className="h-6 w-6" />}
              action={<Button onClick={() => setCreateOpen(true)}>Create key</Button>}
            />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Prefix</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {keys.map((k) => (
                <TableRow key={k.id}>
                  <TableCell className="font-medium">{k.name}</TableCell>
                  <TableCell className="font-mono text-xs">{k.key_prefix}…</TableCell>
                  <TableCell className="text-muted">{formatDate(k.last_used_at)}</TableCell>
                  <TableCell className="text-muted">{formatDate(k.created_at)}</TableCell>
                  <TableCell className="text-right">
                    <Button variant="ghost" size="sm" onClick={() => setRevoking(k)}>
                      <Trash2 className="h-4 w-4 text-bad" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <CreateKeyDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(full) => {
          setKeys((prev) => [
            { id: full.id, name: full.name, key_prefix: full.key_prefix, last_used_at: full.last_used_at, created_at: full.created_at },
            ...prev,
          ]);
          setRevealed(full);
        }}
      />
      <RevealDialog apiKey={revealed} onClose={() => setRevealed(null)} />
      <RevokeDialog
        keyToRevoke={revoking}
        onClose={() => setRevoking(null)}
        onRevoked={(id) => setKeys((prev) => prev.filter((k) => k.id !== id))}
      />
    </Card>
  );
}
