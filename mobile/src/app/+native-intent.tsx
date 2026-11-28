import { Alert } from "react-native";

import { addFile, describe } from "@/kit/add";

// A book opened with the app, such as one sent with AirDrop: it's added while Get more shows how that goes. Every
// other link goes where it says.
export function redirectSystemPath({ path }: { path: string; initial: boolean }) {
  if (!/^file:.*\.zim$/i.test(path)) return path;
  const name = decodeURIComponent(path.slice(path.lastIndexOf("/") + 1));
  void addFile(path, name).then((o) => Alert.alert(...describe(o)));
  return "/more";
}
