"use client";
import { usePathname, useRouter } from "next/navigation";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

const TABS = [
  { value: "profile", label: "Profile" },
  { value: "subscription", label: "Subscription" },
  { value: "api-keys", label: "API Keys" },
  { value: "billing", label: "Billing" },
] as const;

type TabSlug = (typeof TABS)[number]["value"];

function slugFromPath(pathname: string): TabSlug {
  const last = pathname.split("/").filter(Boolean).pop() || "";
  if ((TABS as readonly { value: string }[]).some((t) => t.value === last)) {
    return last as TabSlug;
  }
  return "profile";
}

export function AccountTabs({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const value = slugFromPath(pathname);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Account</h1>
        <p className="mt-1 text-sm text-muted">Manage your profile, subscription, API keys, and billing.</p>
      </div>
      <Tabs value={value} onValueChange={(v) => router.push(`/app/account/${v}`)}>
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <div>{children}</div>
    </div>
  );
}
