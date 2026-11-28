import { size } from "@/kit/format";
import type { Item, MapDownload } from "@/kit/store";

// One line for a book's state on this phone.
export function statusLine(item: Item, onWifi: boolean, cellular: boolean): string {
  const sofar = item.received && item.total ? `${size(item.received)} of ${size(item.total)}` : "";
  switch (item.status) {
    case "ready":
      return item.total ? `Ready · ${size(item.total)}` : "Ready";
    case "failed":
      return `Stopped: ${(item.error || "something went wrong").replace(/\.$/, "")}. Tap to try again.`;
    case "checking":
      return "Checking the download";
    default:
      if (!onWifi && !cellular) return sofar ? `Waiting for Wi-Fi · ${sofar}` : "Waiting for Wi-Fi";
      if (item.status === "queued") return "Waiting to download";
      return sofar || "Starting";
  }
}

export function percent(item: Item): number {
  return item.total ? Math.floor((100 * item.received) / item.total) : 0;
}

// One line for the map's download.
export function mapLine(d: MapDownload): string {
  const sofar = d.received && d.total ? `${size(d.received)} of ${size(d.total)}` : "";
  const plus = (text: string) => (sofar ? `${text} · ${sofar}` : text);
  if (d.status === "failed")
    return `Stopped: ${(d.error || "something went wrong").replace(/\.$/, "")}. Tap to try again.`;
  if (d.waiting === "wifi") return plus("Waiting for Wi-Fi");
  if (d.waiting === "internet") return plus("Waiting for the internet");
  if (d.status === "planning") return "Working out what to download";
  if (d.status === "checking") return "Checking the map";
  return sofar || "Starting";
}
