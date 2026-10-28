import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

const ACCESS = "sm.access";
const REFRESH = "sm.refresh";

function read(key: string) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* private mode — tokens then live only for this tab */
  }
}

export const tokens = {
  get access() {
    return read(ACCESS);
  },
  get refresh() {
    return read(REFRESH);
  },
  set(access: string, refresh?: string) {
    write(ACCESS, access);
    if (refresh) write(REFRESH, refresh);
  },
  clear() {
    write(ACCESS, null);
    write(REFRESH, null);
  },
};

export const api = axios.create({
  baseURL: (import.meta.env.VITE_API_URL || "") + "/api/v1",
});

api.interceptors.request.use((config) => {
  const access = tokens.access;
  if (access) config.headers.Authorization = `Bearer ${access}`;
  return config;
});

let refreshing: Promise<string | null> | null = null;
let onAuthLost: () => void = () => {};
export function setOnAuthLost(fn: () => void) {
  onAuthLost = fn;
}

async function refreshAccess(): Promise<string | null> {
  const refresh = tokens.refresh;
  if (!refresh) return null;
  try {
    const { data } = await axios.post(
      (import.meta.env.VITE_API_URL || "") + "/api/v1/auth/refresh/",
      { refresh },
    );
    tokens.set(data.access, data.refresh);
    return data.access as string;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      refreshing = refreshing ?? refreshAccess().finally(() => (refreshing = null));
      const access = await refreshing;
      if (access) {
        original.headers.Authorization = `Bearer ${access}`;
        return api(original);
      }
      tokens.clear();
      onAuthLost();
    }
    return Promise.reject(error);
  },
);

/** Human-readable message out of a DRF error response. */
export function errorMessage(error: unknown): string {
  const err = error as AxiosError<any>;
  const status = err?.response?.status;
  const data = err?.response?.data;
  // Gateway / server error pages are HTML — never show that markup to staff.
  if (status === 502 || status === 503 || status === 504)
    return `Server javob bermadi (${status}). Qayta urinishdan oldin sahifani yangilang va amal saqlanganini tekshiring.`;
  if (status && status >= 500) return `Serverda xatolik (${status}). Administratorga xabar bering.`;
  if (!data) return err?.message || "Tarmoq xatosi";
  if (typeof data === "string")
    return data.trimStart().startsWith("<") ? `Xatolik (${status ?? "tarmoq"})` : data.slice(0, 200);
  if (data.detail) return String(data.detail);
  const first = Object.entries(data)[0];
  if (first) {
    const [field, value] = first;
    const text = Array.isArray(value) ? value.join(" ") : typeof value === "object" ? JSON.stringify(value) : String(value);
    return field === "non_field_errors" ? text : `${field}: ${text}`;
  }
  return "Xatolik";
}

/** Field → message map for forms. */
export function fieldErrors(error: unknown): Record<string, string> {
  const data = (error as AxiosError<any>)?.response?.data;
  if (!data || typeof data !== "object") return {};
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(data)) {
    if (k === "detail") continue;
    out[k] = Array.isArray(v) ? v.join(" ") : typeof v === "object" ? JSON.stringify(v) : String(v);
  }
  return out;
}

/** A file from the API as a Blob. Files never come from a bare /media/ link: a missing
 * file there is redirected to the Django admin by the server, and the panel must never
 * end up there. Errors carry {"detail": …} so errorMessage() reads them. */
export async function fetchBlob(url: string): Promise<Blob> {
  const resp = await api.get(url, { responseType: "blob" }).catch(async (e: AxiosError<any>) => {
    // the error body arrives as a Blob too: turn {"detail": …} back into JSON
    const data = e?.response?.data;
    if (data instanceof Blob && e.response) {
      try {
        e.response.data = JSON.parse(await data.text());
      } catch {
        e.response.data = undefined;
      }
    }
    throw e;
  });
  const type = String(resp.headers["content-type"] || "");
  if (type.startsWith("text/html")) throw new Error("Fayl o'rniga sahifa keldi — fayl serverda topilmadi.");
  return resp.data;
}

export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export async function downloadFile(url: string, filename: string) {
  saveBlob(await fetchBlob(url), filename);
}
