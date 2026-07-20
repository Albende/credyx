"use client";

import * as React from "react";
import { cn } from "@/lib/cn";

export interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  strokeWidth?: number;
  fill?: boolean;
  className?: string;
}

/**
 * Compact inline sparkline. Renders a polyline path with optional
 * gradient fill underneath. No external charting deps; pure SVG.
 */
export function Sparkline({
  data,
  width = 80,
  height = 24,
  color = "currentColor",
  strokeWidth = 1.5,
  fill = false,
  className,
}: SparklineProps) {
  const id = React.useId();
  const gradientId = `sparkline-grad-${id.replace(/:/g, "")}`;

  if (!data.length) {
    return <svg width={width} height={height} aria-hidden className={className} />;
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = data.length > 1 ? width / (data.length - 1) : 0;
  const pad = strokeWidth;
  const innerH = height - pad * 2;

  const points = data.map((v, i) => {
    const x = i * stepX;
    const y = pad + innerH - ((v - min) / range) * innerH;
    return [x, y] as const;
  });

  const polyline = points.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");

  const lastX = points[points.length - 1][0];
  const firstX = points[0][0];
  const areaPath = `M ${firstX},${height} L ${polyline.replace(/,/g, " ").replace(/\s+/g, " L ")} L ${lastX},${height} Z`
    .replace("L M", "M");

  // Build the area path more carefully
  let area = `M ${firstX.toFixed(2)},${height.toFixed(2)} `;
  for (const [x, y] of points) {
    area += `L ${x.toFixed(2)},${y.toFixed(2)} `;
  }
  area += `L ${lastX.toFixed(2)},${height.toFixed(2)} Z`;

  return (
    <svg
      aria-hidden
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={cn("overflow-visible", className)}
      preserveAspectRatio="none"
    >
      {fill && (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
      )}
      {fill && <path d={area} fill={`url(#${gradientId})`} stroke="none" />}
      <polyline
        points={polyline}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default Sparkline;
