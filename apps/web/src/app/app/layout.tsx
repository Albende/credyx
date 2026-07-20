import { requireSession } from "@/lib/auth";
import { AppShell } from "@/components/app/AppShell";
import { Toaster } from "@/components/ui/toast";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const user = await requireSession();
  return (
    <>
      <Toaster />
      <AppShell user={user}>{children}</AppShell>
    </>
  );
}
