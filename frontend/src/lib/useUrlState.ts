import { useSearchParams } from "react-router-dom";

/** List filters live in the URL so a filtered list can be shared or reloaded. */
export function useUrlState<T extends Record<string, string>>(defaults: T) {
  const [params, setParams] = useSearchParams();
  const state = { ...defaults } as T;
  for (const key of Object.keys(defaults)) {
    const v = params.get(key);
    if (v !== null) (state as Record<string, string>)[key] = v;
  }
  const page = Number(params.get("page") || 1);
  function set(patch: Record<string, string | number | undefined>) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(patch)) {
      const value = v === undefined || v === null ? "" : String(v);
      if (value === "" || (k !== "page" && value === (defaults as Record<string, string>)[k]) || (k === "page" && value === "1")) next.delete(k);
      else next.set(k, value);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  }
  return { state, page, set, params, setParams };
}
