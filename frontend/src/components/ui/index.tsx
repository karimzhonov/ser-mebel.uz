import {
  forwardRef,
  useEffect,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Inbox, Loader2, Search, X } from "lucide-react";
import { cn } from "@/lib/cn";
import type { Tone } from "@/api/types";

/* ------------------------------------------------------------------ Button */

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success" | "outline";
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand-800 text-white hover:bg-brand-900 shadow-sm shadow-brand-900/20 focus-visible:ring-brand-500/30 dark:bg-accent-200 dark:text-brand-900 dark:hover:bg-accent-300",
  secondary:
    "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700",
  outline:
    "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800",
  ghost: "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800",
  danger: "bg-rose-600 text-white hover:bg-rose-700 shadow-sm shadow-rose-600/20",
  success: "bg-emerald-600 text-white hover:bg-emerald-700 shadow-sm shadow-emerald-600/20",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition",
        "focus-visible:outline-none focus-visible:ring-4 disabled:cursor-not-allowed disabled:opacity-50 active:scale-[.98]",
        size === "sm" && "h-8 px-3 text-xs",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-5 text-base",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

export function IconButton({
  className,
  label,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-500 transition hover:bg-slate-100 hover:text-slate-800",
        "dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------- Badge */

export const TONES: Record<Tone, { badge: string; dot: string; soft: string; text: string }> = {
  ok: {
    badge: "bg-emerald-50 text-emerald-700 ring-emerald-600/15 dark:bg-emerald-500/10 dark:text-emerald-300",
    dot: "bg-emerald-500",
    soft: "bg-emerald-50 dark:bg-emerald-500/10",
    text: "text-emerald-600 dark:text-emerald-400",
  },
  info: {
    badge: "bg-sky-50 text-sky-700 ring-sky-600/15 dark:bg-sky-500/10 dark:text-sky-300",
    dot: "bg-sky-500",
    soft: "bg-sky-50 dark:bg-sky-500/10",
    text: "text-sky-600 dark:text-sky-400",
  },
  warn: {
    badge: "bg-amber-50 text-amber-700 ring-amber-600/20 dark:bg-amber-500/10 dark:text-amber-300",
    dot: "bg-amber-500",
    soft: "bg-amber-50 dark:bg-amber-500/10",
    text: "text-amber-600 dark:text-amber-400",
  },
  danger: {
    badge: "bg-rose-50 text-rose-700 ring-rose-600/15 dark:bg-rose-500/10 dark:text-rose-300",
    dot: "bg-rose-500",
    soft: "bg-rose-50 dark:bg-rose-500/10",
    text: "text-rose-600 dark:text-rose-400",
  },
  idle: {
    badge: "bg-slate-100 text-slate-600 ring-slate-500/15 dark:bg-slate-800 dark:text-slate-300",
    dot: "bg-slate-400",
    soft: "bg-slate-100 dark:bg-slate-800",
    text: "text-slate-500 dark:text-slate-400",
  },
  primary: {
    badge: "bg-brand-50 text-brand-700 ring-brand-600/15 dark:bg-brand-500/10 dark:text-brand-300",
    dot: "bg-brand-500",
    soft: "bg-brand-50 dark:bg-brand-500/10",
    text: "text-brand-600 dark:text-brand-400",
  },
};

export function Badge({
  tone = "idle",
  children,
  dot = true,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        TONES[tone].badge,
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", TONES[tone].dot)} />}
      {children}
    </span>
  );
}

export function Check({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        ok ? TONES.ok.badge : TONES.idle.badge,
      )}
    >
      {ok ? "✓" : "○"} {label}
    </span>
  );
}

/* -------------------------------------------------------------------- Card */

export function Card({
  title,
  actions,
  children,
  className,
  padded = true,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cn("card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5 dark:border-slate-800">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={cn(padded && "p-5")}>{children}</div>
    </section>
  );
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="divide-y divide-slate-100 dark:divide-slate-800">
      {items.map(([k, v], i) => (
        <div key={i} className="flex items-start justify-between gap-4 py-2.5 text-sm">
          <dt className="muted shrink-0">{k}</dt>
          <dd className="min-w-0 text-right font-medium text-slate-800 dark:text-slate-100">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------- Forms */

export function Field({
  label,
  error,
  hint,
  children,
  className,
}: {
  label?: ReactNode;
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("block", className)}>
      {label && <span className="label">{label}</span>}
      {children}
      {error ? (
        <span className="mt-1 block text-xs text-rose-600">{error}</span>
      ) : hint ? (
        <span className="muted mt-1 block text-xs">{hint}</span>
      ) : null}
    </label>
  );
}

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn("input", className)} {...rest} />;
  },
);

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn("input min-h-[84px] resize-y", className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn("input appearance-none bg-[length:16px] pr-9", className)} {...rest}>
      {children}
    </select>
  );
}

export function MoneyInput({
  value,
  onChange,
  currencies = ["USD", "UZS"],
  disabled,
}: {
  value: { amount: number | string; currency: string };
  onChange: (v: { amount: number | string; currency: string }) => void;
  currencies?: string[];
  disabled?: boolean;
}) {
  return (
    <div className="flex">
      <input
        type="number"
        inputMode="decimal"
        className="input rounded-r-none"
        value={value.amount}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, amount: e.target.value })}
      />
      <select
        className="input w-24 rounded-l-none border-l-0"
        value={value.currency}
        disabled={disabled}
        onChange={(e) => onChange({ ...value, currency: e.target.value })}
      >
        {currencies.map((c) => (
          <option key={c}>{c}</option>
        ))}
      </select>
    </div>
  );
}

export function SearchInput({
  value,
  onChange,
  placeholder = "Qidiruv…",
  className,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  useEffect(() => {
    const t = setTimeout(() => local !== value && onChange(local), 300);
    return () => clearTimeout(t);
  }, [local]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className={cn("relative", className)}>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input
        className="input pl-9"
        value={local}
        placeholder={placeholder}
        onChange={(e) => setLocal(e.target.value)}
      />
    </div>
  );
}

/* --------------------------------------------------------- Overlay: modal */

function useLockScroll(open: boolean) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);
}

function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);
}

export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  size = "md",
}: {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  useLockScroll(open);
  useEscape(open, onClose);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      <div className="absolute inset-0 animate-fade-in bg-slate-950/40 backdrop-blur-sm" onClick={onClose} />
      <div
        className={cn(
          "relative flex max-h-[92vh] w-full animate-slide-up flex-col rounded-t-3xl bg-white shadow-pop dark:bg-slate-900 sm:rounded-2xl",
          size === "sm" && "sm:max-w-md",
          size === "md" && "sm:max-w-lg",
          size === "lg" && "sm:max-w-2xl",
          size === "xl" && "sm:max-w-4xl",
        )}
      >
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <h2 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
          <IconButton label="Yopish" onClick={onClose}>
            <X className="h-5 w-5" />
          </IconButton>
        </header>
        <div className="scrollbar-thin overflow-y-auto px-5 py-4">{children}</div>
        {footer && (
          <footer className="flex flex-wrap justify-end gap-2 border-t border-slate-100 px-5 py-3 pb-[max(12px,env(safe-area-inset-bottom))] dark:border-slate-800">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    document.body,
  );
}

export function Confirm({
  open,
  onClose,
  onConfirm,
  title,
  text,
  confirmLabel = "Tasdiqlash",
  variant = "primary",
  loading,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  text?: ReactNode;
  confirmLabel?: string;
  variant?: Variant;
  loading?: boolean;
}) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Bekor qilish
          </Button>
          <Button variant={variant} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <div className="text-sm text-slate-600 dark:text-slate-300">{text}</div>
    </Modal>
  );
}

/* ------------------------------------------------------------- Feedback */

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-5 w-5 animate-spin text-brand-600", className)} />;
}

export function PageLoader() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Spinner className="h-7 w-7" />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-slate-200/70 dark:bg-slate-800", className)} />;
}

export function Empty({ title = "Bo'sh", text, icon }: { title?: string; text?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="mb-1 rounded-2xl bg-slate-100 p-3 text-slate-400 dark:bg-slate-800">
        {icon ?? <Inbox className="h-6 w-6" />}
      </div>
      <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {text && <p className="muted max-w-sm text-sm">{text}</p>}
    </div>
  );
}

/* ----------------------------------------------------------- Page chrome */

export function PageHeader({
  title,
  subtitle,
  actions,
  back,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back}
        <h1 className="truncate text-xl font-semibold tracking-tight text-slate-900 dark:text-white sm:text-2xl">
          {title}
        </h1>
        {subtitle && <div className="muted mt-1 text-sm">{subtitle}</div>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: ReactNode; count?: number }[];
  className?: string;
}) {
  return (
    <div
      className={cn(
        "scrollbar-thin inline-flex max-w-full gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-800/70",
        className,
      )}
    >
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm font-medium transition",
            value === o.value
              ? "bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white"
              : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200",
          )}
        >
          {o.label}
          {o.count !== undefined && (
            <span className="rounded-md bg-slate-200/70 px-1.5 text-xs tabular-nums dark:bg-slate-700">
              {o.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function Chip({
  active,
  onClick,
  children,
  tone,
}: {
  active?: boolean;
  onClick?: () => void;
  children: ReactNode;
  tone?: Tone;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-3 py-1 text-xs font-medium transition",
        active
          ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-500/15 dark:text-brand-200"
          : "border-slate-200 bg-white text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300",
      )}
    >
      {tone && <span className={cn("h-1.5 w-1.5 rounded-full", TONES[tone].dot)} />}
      {children}
    </button>
  );
}

export function Pagination({
  page,
  count,
  pageSize = 25,
  onPage,
}: {
  page: number;
  count: number;
  pageSize?: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="flex items-center justify-between gap-3 border-t border-slate-100 px-4 py-3 text-sm dark:border-slate-800">
      <span className="muted">
        {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, count)} / {count}
      </span>
      <div className="flex items-center gap-1">
        <IconButton label="Orqaga" disabled={page <= 1} onClick={() => onPage(page - 1)} className="disabled:opacity-40">
          <ChevronLeft className="h-4 w-4" />
        </IconButton>
        <span className="px-2 tabular-nums">
          {page} / {pages}
        </span>
        <IconButton label="Oldinga" disabled={page >= pages} onClick={() => onPage(page + 1)} className="disabled:opacity-40">
          <ChevronRight className="h-4 w-4" />
        </IconButton>
      </div>
    </div>
  );
}

export function StatTile({
  label,
  value,
  tone = "primary",
  icon,
  active,
  onClick,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  active?: boolean;
  onClick?: () => void;
  hint?: ReactNode;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      className={cn(
        "card flex min-w-0 items-center gap-3 p-4 text-left transition",
        onClick && "hover:-translate-y-0.5 hover:shadow-pop",
        active && "ring-2 ring-brand-500",
      )}
    >
      {icon && <div className={cn("rounded-xl p-2.5", TONES[tone].soft, TONES[tone].text)}>{icon}</div>}
      <div className="min-w-0">
        <div className="muted truncate text-xs font-medium">{label}</div>
        <div className="text-xl font-semibold tabular-nums text-slate-900 dark:text-white">{value}</div>
        {hint && <div className="muted truncate text-xs">{hint}</div>}
      </div>
    </Comp>
  );
}

/* ------------------------------------------------------------------ Table */

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
  hideOnMobile?: boolean;
}

/** Table on desktop, stacked cards on phones (the panel is used a lot inside Telegram). */
export function DataTable<T>({
  rows,
  columns,
  onRowClick,
  rowKey,
  loading,
  empty,
  mobileCard,
  rowClassName,
}: {
  rows: T[] | undefined;
  columns: Column<T>[];
  onRowClick?: (row: T) => void;
  rowKey: (row: T) => string | number;
  loading?: boolean;
  empty?: ReactNode;
  mobileCard?: (row: T) => ReactNode;
  rowClassName?: (row: T) => string | undefined;
}) {
  if (loading && !rows)
    return (
      <div className="space-y-2 p-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-11" />
        ))}
      </div>
    );
  if (!rows?.length) return <>{empty ?? <Empty title="Hech narsa topilmadi" />}</>;
  return (
    <>
      <div className={cn("hidden overflow-x-auto md:block", loading && "opacity-60")}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left dark:border-slate-800">
              {columns.map((c) => (
                <th
                  key={c.key}
                  className={cn("whitespace-nowrap px-4 py-3 text-xs font-medium uppercase tracking-wide text-slate-500", c.className)}
                >
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {rows.map((row) => (
              <tr
                key={rowKey(row)}
                onClick={() => onRowClick?.(row)}
                className={cn(
                  "transition",
                  onRowClick && "cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50",
                  rowClassName?.(row),
                )}
              >
                {columns.map((c) => (
                  <td key={c.key} className={cn("px-4 py-3 align-middle", c.className)}>
                    {c.cell(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={cn("divide-y divide-slate-100 dark:divide-slate-800 md:hidden", loading && "opacity-60")}>
        {rows.map((row) => (
          <div
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={cn("px-4 py-3", onRowClick && "active:bg-slate-50 dark:active:bg-slate-800/50", rowClassName?.(row))}
          >
            {mobileCard ? (
              mobileCard(row)
            ) : (
              <div className="space-y-1">
                {columns
                  .filter((c) => !c.hideOnMobile)
                  .map((c) => (
                    <div key={c.key} className="flex justify-between gap-3 text-sm">
                      <span className="muted">{c.header}</span>
                      <span className="text-right">{c.cell(row)}</span>
                    </div>
                  ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
