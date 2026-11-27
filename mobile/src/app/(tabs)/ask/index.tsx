import { ScrollView } from "react-native";

import { Group, Row } from "@/components/group";

export default function Ask() {
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      <Group footer="Ask answers from your books with the AI built into your phone, where it has one. Other phones search the books instead.">
        <Row title="Coming next" detail="Search your books, then ask about what they say." />
      </Group>
    </ScrollView>
  );
}
