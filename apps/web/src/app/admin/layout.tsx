import { AdminShell } from "@/components/admin/AdminShell";
import { Toaster } from "@/components/ui/toast";
import { requireAdmin } from "@/lib/auth";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const user = await requireAdmin();
  return (
    <>
      <Toaster />
      <AdminShell user={user}>{children}</AdminShell>
    </>
  );
}
