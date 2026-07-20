import { AccountTabs } from "@/components/account/AccountTabs";
import { requireSession } from "@/lib/auth";
import { Toaster } from "@/components/ui/toast";

export default async function AccountLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  return (
    <>
      <Toaster />
      <AccountTabs>{children}</AccountTabs>
    </>
  );
}
