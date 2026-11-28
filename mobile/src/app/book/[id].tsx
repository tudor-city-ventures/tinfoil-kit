import { useLocalSearchParams } from "expo-router";

import { Reader } from "@/screens/reader";

export default function Book() {
  const { id } = useLocalSearchParams<{ id: string }>();
  return <Reader id={id} />;
}
