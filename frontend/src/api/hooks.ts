import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "./client";
import type { Meta, Paginated } from "./types";

export function useMeta() {
  return useQuery({
    queryKey: ["meta"],
    queryFn: async () => (await api.get<Meta>("/meta/")).data,
    staleTime: 10 * 60 * 1000,
  });
}

export function cleanParams(params: Record<string, unknown>) {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length)) continue;
    out[k] = Array.isArray(v) ? v.join(",") : String(v);
  }
  return out;
}

export function useList<T>(resource: string, params: Record<string, unknown> = {}, enabled = true) {
  const clean = cleanParams(params);
  return useQuery({
    queryKey: [resource, "list", clean],
    queryFn: async () => (await api.get<Paginated<T>>(`/${resource}/`, { params: clean })).data,
    placeholderData: keepPreviousData,
    enabled,
  });
}

/** Non-paginated collection (catalogs) */
export function useAll<T>(resource: string, params: Record<string, unknown> = {}, enabled = true) {
  const clean = cleanParams(params);
  return useQuery({
    queryKey: [resource, "all", clean],
    queryFn: async () => (await api.get<T[]>(`/${resource}/`, { params: clean })).data,
    enabled,
  });
}

export function useGet<T>(path: string | null, params: Record<string, unknown> = {}) {
  const clean = cleanParams(params);
  return useQuery({
    queryKey: [path, clean],
    queryFn: async () => (await api.get<T>(path!, { params: clean })).data,
    enabled: !!path,
  });
}

/** POST/PATCH/DELETE with toast + invalidation of everything under `invalidate` keys. */
export function useAction<TVars = void, TResult = unknown>(
  fn: (vars: TVars) => Promise<TResult>,
  opts: { success?: string; invalidate?: string[]; onSuccess?: (r: TResult) => void } = {},
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (result) => {
      if (opts.success) toast.success(opts.success);
      (opts.invalidate ?? []).forEach((key) =>
        qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).includes(key) }),
      );
      opts.onSuccess?.(result);
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
}

export { api };
