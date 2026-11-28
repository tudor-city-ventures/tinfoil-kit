// The bits of native code Expo lacks: book downloads that are checked and filed in the library with the app closed,
// keeping books out of iOS backups, downloads that take exactly the part of a file asked for, the view that shows a
// book's pages, asking the app for each file they need and reaching nothing else, finding a kit shared on the Wi-Fi,
// sharing this phone like one, and the AI built into the phone.
import { requireNativeView, requireOptionalNativeModule } from "expo";
import type { ComponentType, Ref } from "react";
import type { ViewProps } from "react-native";

const native = requireOptionalNativeModule<{
  excludeFromBackup?(path: string): void; // iOS only: app.json turns Android's backups off
  download(o: DownloadOptions): Promise<number>;
  stopDownloads(): void;
  libraryPath(): string;
  startBook(o: BookOptions): Promise<void>;
  stopBook(id: string): void;
  forgetBook(id: string): void;
  books(): Promise<NativeBook[]>;
  findKits(seconds: number): Promise<FoundKit[]>;
  startSharing(o: ShareOptions): Promise<number>;
  stopSharing(): void;
  sharing(): Sharing;
  newCode(): string;
  aiState?(): string; // iOS only, for now
  aiAnswer?(instructions: string, prompt: string): Promise<string>;
}>("KitFiles");

export type BookOptions = {
  id: string; // this download's own id
  book: string;
  title: string; // Android shows it while it downloads
  url: string;
  incoming: string; // where it lands to be checked
  path: string; // where it goes once it's checked
  sha256?: string;
  cellular: boolean; // false: Wi-Fi only, never a phone's hotspot
  headers?: Record<string, string>; // a kit at home's access code
};

export type BookState = {
  id: string;
  book: string;
  state: "downloading" | "downloaded" | "ready" | "failed"; // downloaded: being checked
  cellular: boolean;
  received?: number;
  total?: number;
  error?: string;
};

type NativeBook = Omit<BookState, "error"> & { error: string };

// The folder books go in, as a path: on Android, the app's own folder on shared storage, where its downloader writes
export function libraryPath(): string | undefined {
  return native?.libraryPath();
}

// A book, downloaded by the phone (it carries on with the app closed), then checked against its SHA-256 and moved
// into the library, also with the app closed. Its progress and outcome come from books().
export function startBook(o: BookOptions): Promise<void> {
  if (!native) return Promise.reject(new Error("Books download in the phone app"));
  return native.startBook(o);
}

// Stops a book's download, or lets go of one that's being checked
export function stopBook(id: string) {
  native?.stopBook(id);
}

// Lets go of a finished download's outcome, once the app has it
export function forgetBook(id: string) {
  native?.forgetBook(id);
}

export async function books(): Promise<BookState[]> {
  if (!native) return [];
  return (await native.books()).map(({ error, ...b }) => (error ? { ...b, error } : b));
}

export type DownloadOptions = {
  url: string;
  path: string;
  cellular: boolean; // false: Wi-Fi only, never a phone's hotspot
  headers?: Record<string, string>; // a kit at home's access code
  offset?: number;
  length?: number;
  at?: number;
};

export function excludeFromBackup(path: string) {
  native?.excludeFromBackup?.(path);
}

// A file on the internet, or `length` bytes of it from `offset`, into a new file, or at `at` into one that's there
// already, while the app is open. Resolves with how many bytes came. Its errors' codes: ERR_NOT_ON_WIFI (only mobile
// data, and it isn't allowed), ERR_OFFLINE, ERR_HTTP_<status>, ERR_NO_RANGE (the server sent other bytes than those
// asked for, and was stopped), ERR_GONE (the file to go into was deleted), ERR_STOPPED.
export function download(o: DownloadOptions): Promise<number> {
  if (!native) return Promise.reject(new Error("Maps download in the phone app"));
  return native.download(o);
}

export function stopDownloads() {
  native?.stopDownloads();
}

export type Page = { url: string; title: string; back: boolean; forward: boolean; loading: boolean; gone?: boolean };
type Event<T> = { nativeEvent: T };

export type BookViewHandle = {
  load(url: string): Promise<void>;
  back(): Promise<void>;
  forward(): Promise<void>;
  find(): Promise<void>; // iOS's find on page
  respond(id: number, status: number, mime: string, body: Uint8Array): Promise<void>;
  respondFile(id: number, status: number, mime: string, path: string, offset: number, length: number): Promise<void>;
};

export type BookViewProps = ViewProps & {
  ref?: Ref<BookViewHandle>;
  start: string; // the first page's address
  onAsk(e: Event<{ id: number; url: string; main: boolean }>): void; // answer with respond or respondFile
  onPage?(e: Event<Page>): void;
  onLeave?(e: Event<{ url: string }>): void; // a link out of the book was tapped
  onOpen?(e: Event<{ url: string; mime: string }>): void; // a file the view can't show itself
};

let view: ComponentType<BookViewProps> | undefined;

export function bookView(): ComponentType<BookViewProps> | undefined {
  if (!native) return undefined;
  view ??= requireNativeView<BookViewProps>("KitFiles");
  return view;
}

// A kit shared on this Wi-Fi, or a phone shared like one: its name, and where it answers
export type FoundKit = { name: string; host: string; port: number; phone: boolean };

// The kits shared on this Wi-Fi, and phones shared like one, found in that many seconds by the name each gives itself
// on the network (Bonjour). The first search asks the person to let the app find devices on the local network.
export async function findKits(seconds: number): Promise<FoundKit[]> {
  return native ? native.findKits(seconds) : [];
}

export type ShareOptions = {
  name: string; // what other phones see
  code: string;
  listing: string; // what /data/files answers: the books and the map, as a kit lists them
  files: Record<string, string>; // each file's path in the listing, and the file on this phone
  folders: Record<string, string>; // a folder's path in it (the map's fonts and icons), and this phone's
};

export type Sharing = {
  on: boolean;
  port: number;
  addresses: string[]; // this phone's on the Wi-Fi
  sent: number; // bytes
  copying: number; // requests being answered
  stopped: "" | "tries" | "failed"; // why it stopped by itself: too many wrong codes, or the network
};

// This phone shared like a kit at home, for another phone on the Wi-Fi to copy from: it answers only with the code,
// and serves only the listing and the files it names. Resolves with the port it listens on.
export function startSharing(o: ShareOptions): Promise<number> {
  if (!native) return Promise.reject(new Error("Sharing works in the phone app"));
  return native.startSharing(o);
}

export function stopSharing() {
  native?.stopSharing();
}

export function sharing(): Sharing {
  return native?.sharing() ?? { on: false, port: 0, addresses: [], sent: 0, copying: 0, stopped: "" };
}

// The code another phone types: 8 digits from the phone's secure random numbers
export function newCode(): string {
  if (!native) throw new Error("Sharing works in the phone app");
  return native.newCode();
}

// The AI built into the phone, where there is one: Apple Intelligence on iPhones from iOS 26. "off" until the person
// turns it on in Settings, "downloading" while its model comes.
export type AIState = "ready" | "off" | "downloading" | "none";

export function aiState(): AIState {
  const s = native?.aiState?.();
  return s === "ready" || s === "off" || s === "downloading" ? s : "none";
}

// Its answer to a prompt, following the instructions
export function aiAnswer(instructions: string, prompt: string): Promise<string> {
  if (!native?.aiAnswer) return Promise.reject(new Error("This phone has no AI built in"));
  return native.aiAnswer(instructions, prompt);
}
