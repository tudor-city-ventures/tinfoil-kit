// The phone's own handling of book files, where Expo has none: on iOS, keeping them out of backups and a SHA-256
// that reads a megabyte at a time. Android needs neither (app.json turns its backups off; Expo's digest is fine there).
import { requireOptionalNativeModule } from "expo";
import { File } from "expo-file-system";

const native = requireOptionalNativeModule<{
  excludeFromBackup(path: string): void;
  sha256(path: string): Promise<string>;
}>("KitFiles");

export function excludeFromBackup(path: string) {
  native?.excludeFromBackup(path);
}

export function sha256(path: string): Promise<string> {
  return native ? native.sha256(path) : new File(`file://${path}`).digest("SHA-256");
}
