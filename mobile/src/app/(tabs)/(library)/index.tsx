import { NetworkStateType, useNetworkState } from "expo-network";
import { ScrollView } from "react-native";

import { Group, Pill, Row } from "@/components/group";
import { catalog } from "@/kit/catalog";
import { percent, statusLine } from "@/kit/status";
import { useKit } from "@/kit/store";

const byId = new Map(catalog.map((b) => [b.id, b]));

export default function Library() {
  const { items, cellular } = useKit();
  const onWifi = useNetworkState().type === NetworkStateType.WIFI;
  const mine = Object.entries(items).filter(([id]) => byId.has(id));
  const getting = mine.filter(([, it]) => it.status !== "ready");
  const ready = mine.filter(([, it]) => it.status === "ready");

  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      {getting.length > 0 ? (
        <Group label="Downloading">
          {getting.map(([id, it]) => (
            <Row
              key={id}
              testID={`getting-${id}`}
              icon={it.status === "failed" ? "failed" : "download"}
              accent
              title={byId.get(id)!.title}
              detail={statusLine(it, onWifi, cellular)}
              right={it.status === "downloading" ? <Pill text={`${percent(it)}%`} /> : undefined}
            />
          ))}
        </Group>
      ) : null}
      <Group label="On this phone">
        {ready.length > 0 ? (
          ready.map(([id, it]) => (
            <Row key={id} icon="book" title={byId.get(id)!.title} detail={statusLine(it, onWifi, cellular)} />
          ))
        ) : (
          <Row title="Nothing yet" detail="Books you get show up here, ready without the internet." />
        )}
      </Group>
      <Group label="Nearby" footer="A Tinfoil Kit on this Wi-Fi can share its books and maps with your phone.">
        <Row
          icon="drive"
          title="No kit found on this Wi-Fi"
          detail="Turn on Share with family on the kit's computer."
        />
      </Group>
    </ScrollView>
  );
}
