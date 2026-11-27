// Sizes as people read them: 0.4 GB, 2.1 GB, 12 GB, 950 MB.
export function size(bytes: number): string {
  if (bytes < 1e9) return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
  const gb = bytes / 1e9;
  return `${gb < 10 ? gb.toFixed(1) : Math.round(gb)} GB`;
}

// How long a download takes at a speed in bytes per second: "about 4 min", "about 2 hours".
export function duration(bytes: number, perSecond: number): string {
  const minutes = Math.ceil(bytes / perSecond / 60);
  if (minutes < 60) return `about ${minutes} min`;
  const hours = Math.round(minutes / 60);
  return `about ${hours} ${hours === 1 ? "hour" : "hours"}`;
}
