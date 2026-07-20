"use client";
import { useEffect, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api-client";
import type { TimeSeriesPoint } from "./types";

export function SignupsChart() {
  const [data, setData] = useState<TimeSeriesPoint[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    apiFetch<{ points: TimeSeriesPoint[] }>("/api/admin/metrics/signups-series?days=30")
      .then((r) => setData(r.points ?? []))
      .catch(() => setUnavailable(true));
  }, []);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Signups (last 30 days)</CardTitle>
        <CardDescription>Daily new user count.</CardDescription>
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
            <span className="text-sm text-muted">No signups yet</span>
          </Skeleton>
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 5, right: 12, left: 0, bottom: 5 }}>
                <CartesianGrid stroke="hsl(220 10% 18%)" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="hsl(220 8% 60%)" fontSize={11} />
                <YAxis stroke="hsl(220 8% 60%)" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    background: "hsl(220 14% 8%)",
                    border: "1px solid hsl(220 10% 18%)",
                    fontSize: 12,
                  }}
                />
                <Line type="monotone" dataKey="value" stroke="hsl(140 70% 45%)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
