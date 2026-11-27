import { size } from "@/kit/format";
import type { Item } from "@/kit/store";

// One line for a book's state on this phone.
export function statusLine(item: Item, onWifi: boolean, cellular: boolean): string {
  switch (item.status) {
    case "ready":
      return item.total ? `Ready · ${size(item.total)}` : "Ready";
    case "failed":
      return item.error ? `Stopped: ${item.error}` : "Stopped";
    case "downloading":
      return item.total ? `${size(item.received)} of ${size(item.total)}` : "Starting";
    default:
      return onWifi || cellular ? "Waiting to download" : "Waiting for Wi-Fi";
  }
}

export function percent(item: Item): number {
  return item.total ? Math.floor((100 * item.received) / item.total) : 0;
}
