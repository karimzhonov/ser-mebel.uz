import type { Money } from "@/api/types";

const nf = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 });

export function money(m: Money | null | undefined, fallback = "—") {
  if (!m || m.amount === null || m.amount === undefined) return fallback;
  const symbol = m.currency === "USD" ? "$" : m.currency === "UZS" ? " so'm" : ` ${m.currency}`;
  return m.currency === "USD" ? `${symbol}${nf.format(m.amount)}` : `${nf.format(m.amount)}${symbol}`;
}

export function num(n: number | null | undefined, fallback = "—") {
  return n === null || n === undefined ? fallback : nf.format(n);
}

function toDate(value: string | Date) {
  return value instanceof Date ? value : new Date(value.length === 10 ? value + "T00:00:00" : value);
}

export function date(value: string | null | undefined, fallback = "—") {
  if (!value) return fallback;
  return toDate(value).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function dateTime(value: string | null | undefined, fallback = "—") {
  if (!value) return fallback;
  return toDate(value).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relative(value: string | null | undefined) {
  if (!value) return "";
  const diff = (Date.now() - toDate(value).getTime()) / 1000;
  if (diff < 60) return "hozirgina";
  if (diff < 3600) return `${Math.floor(diff / 60)} daqiqa oldin`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} soat oldin`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} kun oldin`;
  return date(value);
}

export function phone(value: string | null | undefined) {
  if (!value) return "";
  const d = value.replace(/\D/g, "");
  if (d.length === 12 && d.startsWith("998"))
    return `+998 ${d.slice(3, 5)} ${d.slice(5, 8)}-${d.slice(8, 10)}-${d.slice(10)}`;
  return value;
}

export function fileSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

/** "2026-10-25T10:00" for <input type="datetime-local"> */
export function toLocalInput(value: string | null | undefined) {
  if (!value) return "";
  return value.slice(0, 16);
}

export function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
