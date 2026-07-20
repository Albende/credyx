"use client";
import { useEffect, useState } from "react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { TimeSeriesPoint } from "./types";

export function MrrChart() {
  const [data, setData] = useState<TimeSeriesPoint[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    apiFetch<{ points: TimeSeriesPoint[] }>("/api/admin/metrics/mrr-series?days=90")
      .then((r) => setData(r.points ?? []))
      .catch(() => setUnavailable(true));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>MRR (last 90 days)</CardTitle>
        <CardDescription>Monthly recurring revenue trend.</CardDescription>
      </CardHeader>
      <CardContent>
        {unavailable ? (
          <Skeleton className="flex h-64 items-center justify-center">
            <span className="text-sm text-muted">Coming soon</span>
          </Skeleton>
        ) : data === null ? (
          <Skeleton className="h-64 w-full" />
        ) : data.length === 0 ? (
          <Skeleton className="flex h-64 items-center justify-center">
            <span className="text-sm text-muted">No data yet</span>
          </Skeleton>
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="mrr" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="hsl(180 80% 55%)" stopOpacity={0.6} />
                    <stop offset="95%" stopColor="hsl(180 80% 55%)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="hsl(220 10% 18%)" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="hsl(220 8% 60%)" fontSize={11} />
                <YAxis stroke="hsl(220 8% 60%)" fontSize={11} tickFormatter={(v) => `$${(v / 100).toFixed(0)}`} />
                <Tooltip
                  contentStyle={{
                    background: "hsl(220 14% 8%)",
                    border: "1px solid hsl(220 10% 18%)",
                    fontSize: 12,
                  }}
                  formatter={(v: number) => [`$${(v / 100).toFixed(2)}`, "MRR"]}
                />
                <Area type="monotone" dataKey="value" stroke="hsl(180 80% 55%)" fill="url(#mrr)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
