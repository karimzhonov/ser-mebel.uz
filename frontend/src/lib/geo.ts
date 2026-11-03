/** Yandex Maps links — the same rules as backend core.geo.yandex_url. */

/** Tashkent centre: text searches are biased to the city the company works in. */
const TASHKENT = "69.279737,41.311081";

export function yandexSearchUrl(address: string) {
  return `https://yandex.uz/maps/?text=${encodeURIComponent(address)}&ll=${TASHKENT}&z=12`;
}

export function yandexPointUrl(lat: string | number, lon: string | number) {
  return `https://yandex.uz/maps/?ll=${lon},${lat}&pt=${lon},${lat}&z=17&l=map`;
}

const YANDEX_HOSTS = ["yandex.uz", "yandex.ru", "yandex.com", "yandex.kz", "yandex.by", "yandex.com.tr"];

/** The link parsed as an http(s) URL, else null (javascript:, data:, garbage…). */
function httpUrl(link: string | null | undefined): URL | null {
  if (!link) return null;
  try {
    const url = new URL(link.trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

/** Only an http(s) URL is ever used as an href. */
export function safeHref(link: string | null | undefined): string | null {
  return httpUrl(link)?.href ?? null;
}

function isYandex(link: string) {
  const host = httpUrl(link)?.hostname.toLowerCase();
  if (!host) return false;
  return YANDEX_HOSTS.some((h) => host === h || host.endsWith("." + h));
}

/** Where a click on an address goes: the API's map_url, else a Yandex link, else a Yandex
 * text search for the address, else whatever link was pasted. */
export function mapHref({
  address,
  link,
  mapUrl,
  lat,
  lon,
}: {
  address?: string | null;
  link?: string | null;
  mapUrl?: string | null;
  lat?: string | null;
  lon?: string | null;
}): string | null {
  const api = safeHref(mapUrl);
  if (api) return api;
  if (lat && lon) return yandexPointUrl(lat, lon);
  if (link && isYandex(link)) return safeHref(link);
  if (address && address.trim()) return yandexSearchUrl(address.trim());
  return safeHref(link);
}
