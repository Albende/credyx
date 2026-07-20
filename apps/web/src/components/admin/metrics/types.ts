export interface AdminMetrics {
  total_users: number;
  active_subscriptions: number;
  mrr_cents: number;
  arr_cents: number;
  churn_30d_pct: number;
  dau_today: number;
  currency: string;
}

export interface TimeSeriesPoint {
  date: string;
  value: number;
}
