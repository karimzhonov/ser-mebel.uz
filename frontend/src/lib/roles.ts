import type { Me } from "@/api/types";

const norm = (s: string) => s.split(/\s+/).filter(Boolean).join(" ").toLowerCase();

/** Owner's rule: the plain «Menejer» (not the «Bosh menejer») — decided by the lavozim, so
 * a right left over from the old per-person switches cannot turn them into the boss. */
export function isPlainManager(user: Me | null | undefined): boolean {
  if (!user || user.is_superuser) return false;
  const lav = (user.lavozims ?? []).map(norm);
  return lav.includes("menejer") && !lav.includes("bosh menejer");
}

/** «Menejer» or «Bosh menejer» lavozim: both get price tasks from the zamerchi. */
export function isAnyManager(user: Me | null | undefined): boolean {
  if (!user || user.is_superuser) return false;
  const lav = (user.lavozims ?? []).map(norm);
  return lav.includes("menejer") || lav.includes("bosh menejer");
}

/** The call-centre operator: works the leads (call_center.view_invoice) and is in the
 * «Operator» lavozim or holds the «Call-center operatori» flag. A flag alone (left from
 * the old per-person switches, e.g. on a manager) is not enough. */
export function isOperator(user: Me | null | undefined, can: (p: string) => boolean): boolean {
  if (!user || user.is_superuser || !can("call_center.view_invoice")) return false;
  return (user.lavozims ?? []).map(norm).includes("operator") || can("oauth.user_call_center");
}
