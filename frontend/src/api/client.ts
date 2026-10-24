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
  const data = err?.response?.data;
  if (!data) return err?.message || "Ошибка сети";
  if (typeof data === "string") return data.slice(0, 200);
  if (data.detail) return String(data.detail);
  const first = Object.entries(data)[0];
  if (first) {
    const [field, value] = first;
    const text = Array.isArray(value) ? value.join(" ") : typeof value === "object" ? JSON.stringify(value) : String(value);
    return field === "non_field_errors" ? text : `${field}: ${text}`;
  }
  return "Ошибка";
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

export async function downloadFile(url: string, filename: string) {
  const resp = await api.get(url, { responseType: "blob" });
  const href = URL.createObjectURL(resp.data);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}
