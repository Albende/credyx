import { UsersTable } from "@/components/admin/users/UsersTable";
import { apiFetch } from "@/lib/api-client";
import type { AdminUsersResponse } from "@/components/admin/users/types";

async function fetchUsers(): Promise<AdminUsersResponse> {
  try {
    return await apiFetch<AdminUsersResponse>("/api/admin/users?page=1&page_size=25", { serverSide: true });
  } catch {
    return { users: [], total: 0, page: 1, page_size: 25 };
  }
}

export default async function UsersPage() {
  const data = await fetchUsers();
  return <UsersTable initialData={data} />;
}
