import type { Me } from "@/api/types";

const norm = (s: string) => s.split(/\s+/).filter(Boolean).join(" ").toLowerCase();

/** Owner's rule: the plain «Menejer» (not the «Bosh menejer») — decided by the lavozim, so
 * a right left over from the old per-person switches cannot turn them into the boss. */
export function isPlainManager(user: Me | null | undefined): boolean {
  if (!user || user.is_superuser) return false;
  const lav = (user.lavozims ?? []).map(norm);
  return lav.includes("menejer") && !lav.includes("bosh menejer");
}
