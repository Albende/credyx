export interface AdminUser {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: "user" | "admin";
  email_verified: boolean;
  is_verified?: boolean;
  active_plan_slug: string | null;
  plan_slug?: string | null;
  has_active_subscription?: boolean;
  stripe_customer_id?: string | null;
  created_at: string;
}

export interface AdminUsersResponse {
  users: AdminUser[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminSubscription {
  id: string;
  status: "active" | "trialing" | "past_due" | "canceled" | "incomplete";
  billing_period: "monthly" | "yearly";
  current_period_end: string;
  cancel_at_period_end: boolean;
  granted_by_admin_id: string | null;
  plan: { slug: string; name: string };
  user?: { id: string; email: string };
}

export interface AuditLogEntry {
  id: string;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  created_at: string;
  payload: Record<string, unknown> | null;
}
