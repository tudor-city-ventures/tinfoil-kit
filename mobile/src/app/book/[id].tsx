import { useLocalSearchParams } from "expo-router";

import { Reader } from "@/screens/reader";

export default function Book() {
  const { id, page } = useLocalSearchParams<{ id: string; page?: string }>();
  return <Reader id={id} page={page} />;
}
