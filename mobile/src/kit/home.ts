// A kit at home: a Tinfoil Kit shared on this Wi-Fi, whose books and map the phone copies without the internet. The
// kit asks for its access code, the one Share with family shows on its computer, which the phone sends with each
// request (gate.go takes it as a Bearer token). Its notes server lists what a phone can copy (/data/files) and hands
// over each file, whole or in parts. Another phone shared like a kit (share.ts) answers the same way, with its code.
import { getNetworkStateAsync, NetworkStateType } from "expo-network";

import { catalog, editions } from "./catalog";
import { places, type Place } from "./places";
import type { Box } from "./pmtiles";

export type KitFile = { path: string; bytes: number; sha256?: string };
export type KitPart = { id: string; title: string; group: string; why: string; files: KitFile[] };
// The kit's map: the areas it has in street detail, the day of the world map it's from (20261120), and the folder of
// its fonts and icons. A kit from before phones could copy maps has none of them.
export type KitMap = KitPart & { areas?: Box[]; day?: string; assets?: string };
export type KitListing = { name: string; phone?: boolean; books: KitPart[]; map: KitMap | null };
export type HomeKit = { name: string; address: string; code: string; phone?: boolean }; // address: host:port
// A map the phone cuts from the kit's: its file there, and what the listing said of it
export type KitMapFrom = { path: string; day?: string; assets?: string };

export type Problem = "code" | "tries" | "unreachable" | "old";

export class KitError extends Error {
  constructor(
    readonly problem: Problem,
    message: string,
  ) {
    super(message);
  }
}

const PORT = 8000; // share_port's own

export const FORGOTTEN = "The kit or phone this came from was forgotten. Find it again in Get more.";
export const NEW_CODE = "The code for the kit or phone this comes from has changed. Type the new one in Get more.";

const WAIT = 10_000; // for the kit to answer

// The access code as typed: its 8 digits, whatever spaces or dashes came with them
export function cleanCode(typed: string): string {
  return typed.replace(/\D/g, "");
}

// What the person typed or pasted for the kit's address: 192.168.1.20, 192.168.1.20:8000, a name, or the whole link
// from Share with family's message (http://192.168.1.20:8000/?code=48217736), which has the code too.
export function readAddress(typed: string): { address: string; code?: string } | undefined {
  const text = typed.trim();
  if (!text) return undefined;
  try {
    const url = new URL(/^[a-z]+:\/\//i.test(text) ? text : `http://${text}`);
    if (url.protocol !== "http:" || !url.hostname || url.username || url.password) return undefined;
    const code = cleanCode(url.searchParams.get("code") ?? "");
    return { address: `${url.hostname}:${url.port || PORT}`, ...(code && { code }) };
  } catch {
    return undefined;
  }
}

export function fileUrl(kit: HomeKit, path: string): string {
  return `http://${kit.address}/data/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

export function headers(kit: Pick<HomeKit, "code">): Record<string, string> {
  return { Authorization: `Bearer ${kit.code}` };
}

// The kit's page in the phone's browser: the link lets the browser in, as the QR code's does
export function pageUrl(kit: HomeKit): string {
  return `http://${kit.address}/?code=${kit.code}`;
}

// What the kit, or a phone shared like one, has for this phone to copy. Its errors say what to do, in the person's
// words.
export async function listKit(
  kit: Pick<HomeKit, "address" | "code" | "phone">,
  get: typeof fetch = fetch,
): Promise<KitListing> {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), WAIT);
  let answer: Response;
  try {
    answer = await get(`http://${kit.address}/data/files`, { headers: headers(kit), signal: stop.signal });
  } catch {
    // On a Wi-Fi without the internet, Android uses mobile data where it can, and the kit isn't there
    const cellular = (await getNetworkStateAsync().catch(() => undefined))?.type === NetworkStateType.CELLULAR;
    throw new KitError(
      "unreachable",
      (kit.phone
        ? "Can't reach that phone. Check that both phones are on the same Wi-Fi, and that it's still on Share with " +
          "a phone."
        : "Can't reach the kit. Check that this phone is on the same Wi-Fi, and that the kit is shared: on its " +
          "computer, More, then Share with family.") +
        (cellular ? " If the Wi-Fi has no internet, turn off mobile data while you copy." : ""),
    );
  } finally {
    clearTimeout(timer);
  }
  if (answer.status === 401)
    throw new KitError(
      "code",
      kit.phone
        ? "That code didn't work. It's on the other phone, under Share with a phone."
        : "That code didn't work. It's on the kit's computer: More, then Share with family.",
    );
  if (answer.status === 429) throw new KitError("tries", "Too many tries. Wait a few minutes, then try again.");
  const listing = answer.ok ? await answer.json().catch(() => undefined) : undefined;
  if (!listing || !Array.isArray(listing.books))
    throw new KitError("old", "This kit can't share with phones yet. Update it: run SETUP on its computer, online.");
  return listing as KitListing;
}

const byEdition = new Map(catalog.flatMap((b) => editions(b.id).map((e) => [e, b.id] as const)));

// Which of the phone's books a kit's book is: the same one, or another edition of it (the kit may have Wikipedia with
// pictures, the phone's own is the smallest). Undefined for a book this version of the app doesn't know.
export function phoneBook(part: KitPart): string | undefined {
  return byEdition.get(part.id);
}

// The book's file: its one ZIM
export function zimOf(part: KitPart): KitFile | undefined {
  return part.files.find((f) => f.path.endsWith(".zim"));
}

export function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

const NEAR = 1e-6; // degrees: the same box, as the kit and this app each have it from regions.json

// The places whose map the phone can cut from the kit's: the kit's own, whose areas its map has, and the place the
// phone's map is of when it's inside them
export function kitPlaces(map: KitMap | null, mine?: string): Place[] {
  const areas = map?.areas ?? [];
  if (!kitMapFile(map)) return [];
  const same = (b: Box) => areas.some((a) => a.every((x, i) => Math.abs(x - b[i]) < NEAR));
  const inside = (b: Box) =>
    areas.some((a) => b[0] >= a[0] - NEAR && b[1] >= a[1] - NEAR && b[2] <= a[2] + NEAR && b[3] <= a[3] + NEAR);
  return places.filter((p) => same(p.bbox) || (p.id === mine && inside(p.bbox)));
}

// Where the phone cuts its map from: the kit's map file, with what the listing said of it
export function kitMapFrom(map: KitMap | null): KitMapFrom | undefined {
  const file = kitMapFile(map);
  if (!map || !file) return undefined;
  return { path: file.path, ...(map.day && { day: map.day }), ...(map.assets && { assets: map.assets }) };
}

function kitMapFile(map: KitMap | null): KitFile | undefined {
  return map?.files.find((f) => f.path.endsWith(".pmtiles"));
}
