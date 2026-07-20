import { ApiKeysPanel, type ApiKey } from "@/components/account/ApiKeysPanel";
import { apiFetch } from "@/lib/api-client";

async function fetchKeys(): Promise<ApiKey[]> {
  try {
    const data = await apiFetch<{ keys: ApiKey[] }>("/api/auth/api-keys", { serverSide: true });
    return data.keys ?? [];
  } catch {
    return [];
  }
}

export default async function ApiKeysPage() {
  const keys = await fetchKeys();
  return <ApiKeysPanel initialKeys={keys} />;
}
