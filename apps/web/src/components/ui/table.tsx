"use client";

import * as React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";

export const Table = React.forwardRef<
  HTMLTableElement,
  React.HTMLAttributes<HTMLTableElement>
>(({ className, ...props }, ref) => (
  <div className="relative w-full overflow-auto">
    <table
      ref={ref}
      className={cn("w-full caption-bottom text-sm", className)}
      {...props}
    />
  </div>
));
Table.displayName = "Table";

export const THead = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <thead
    ref={ref}
    className={cn(
      "[&_tr]:border-b [&_tr]:border-border-default bg-bg-elevated/40",
      className
    )}
    {...props}
  />
));
THead.displayName = "THead";

export const TBody = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tbody
    ref={ref}
    className={cn("[&_tr:last-child]:border-0", className)}
    {...props}
  />
));
TBody.displayName = "TBody";

export const TFoot = React.forwardRef<
  HTMLTableSectionElement,
  React.HTMLAttributes<HTMLTableSectionElement>
>(({ className, ...props }, ref) => (
  <tfoot
    ref={ref}
    className={cn(
      "border-t border-border-default bg-bg-elevated/40 font-medium",
      className
    )}
    {...props}
  />
));
TFoot.displayName = "TFoot";

export const TR = React.forwardRef<
  HTMLTableRowElement,
  React.HTMLAttributes<HTMLTableRowElement>
>(({ className, ...props }, ref) => (
  <tr
    ref={ref}
    className={cn(
      "border-b border-border-default transition-colors hover:bg-bg-elevated/60 data-[state=selected]:bg-bg-overlay",
      className
    )}
    {...props}
  />
));
TR.displayName = "TR";

export const TH = React.forwardRef<
  HTMLTableCellElement,
  React.ThHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <th
    ref={ref}
    className={cn(
      "h-10 px-3 text-left align-middle font-medium text-fg-muted text-xs uppercase tracking-wider",
      "[&:has([role=checkbox])]:pr-0",
      className
    )}
    {...props}
  />
));
TH.displayName = "TH";

export const TD = React.forwardRef<
  HTMLTableCellElement,
  React.TdHTMLAttributes<HTMLTableCellElement>
>(({ className, ...props }, ref) => (
  <td
    ref={ref}
    className={cn(
      "p-3 align-middle text-fg-default [&:has([role=checkbox])]:pr-0",
      className
    )}
    {...props}
  />
));
TD.displayName = "TD";

export interface TableEmptyProps
  extends React.HTMLAttributes<HTMLDivElement> {
  message?: React.ReactNode;
}

export const TableEmpty: React.FC<TableEmptyProps> = ({
  className,
  message = "No results.",
  ...props
}) => (
  <div
    className={cn(
      "flex items-center justify-center px-4 py-10 text-sm text-fg-muted",
      className
    )}
    {...props}
  >
    {message}
  </div>
);

export interface TablePaginationProps
  extends React.HTMLAttributes<HTMLDivElement> {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
}

export const TablePagination: React.FC<TablePaginationProps> = ({
  className,
  page,
  pageSize,
  total,
  onPageChange,
  ...props
}) => {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, total);

  return (
    <div
      className={cn(
        "flex items-center justify-between border-t border-border-default px-3 py-3 text-sm text-fg-muted",
        className
      )}
      {...props}
    >
      <span>
        {start}–{end} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <span className="tabular-nums text-fg-default">
          {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Next page"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
};

// Long-name aliases for shadcn-style imports (used by some components)
export const TableHeader = THead;
export const TableBody = TBody;
export const TableFooter = TFoot;
export const TableRow = TR;
export const TableHead = TH;
export const TableCell = TD;
