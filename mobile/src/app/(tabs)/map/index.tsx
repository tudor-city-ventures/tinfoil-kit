import { ScrollView } from "react-native";

import { Group, Row } from "@/components/group";

export default function Map() {
  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      <Group footer="Your area's map works without the internet once it's on your phone.">
        <Row title="Coming next" detail="The map of where you live, with places nearby." />
      </Group>
    </ScrollView>
  );
}
