import { NetworkStateType, useNetworkState } from "expo-network";
import { router } from "expo-router";
import { Alert, ScrollView } from "react-native";

import { Group, Pill, Row } from "@/components/group";
import { catalog } from "@/kit/catalog";
import { removeBook } from "@/kit/downloads";
import { size } from "@/kit/format";
import { percent, statusLine } from "@/kit/status";
import { store, useKit, type Item } from "@/kit/store";

const byId = new Map(catalog.map((b) => [b.id, b]));

// Touch and hold: a book comes off the phone, or stops downloading
function offer(id: string, it: Item) {
  const title = byId.get(id)!.title;
  if (it.status === "ready")
    Alert.alert(
      `Remove ${title}?`,
      `It comes off this phone, freeing ${size(it.total)}. You can get it again in Get more.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Remove", style: "destructive", onPress: () => removeBook(id) },
      ],
    );
  else
    Alert.alert(`Stop downloading ${title}?`, "What has downloaded so far is deleted.", [
      { text: "Keep downloading", style: "cancel" },
      { text: "Stop", style: "destructive", onPress: () => removeBook(id) },
    ]);
}

// The books on this phone and the ones on their way, and a Tinfoil Kit nearby
export function Library() {
  const { items, cellular } = useKit();
  const net = useNetworkState().type;
  const onWifi = net === NetworkStateType.WIFI || net === NetworkStateType.ETHERNET;
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
              onPress={it.status === "failed" ? () => store.retry(id) : undefined}
              onLongPress={() => offer(id, it)}
            />
          ))}
        </Group>
      ) : null}
      <Group label="On this phone" footer={ready.length > 0 ? "Touch and hold a book to remove it." : undefined}>
        {ready.length > 0 ? (
          ready.map(([id, it]) => (
            <Row
              key={id}
              testID={`ready-${id}`}
              icon="book"
              title={byId.get(id)!.title}
              detail={statusLine(it, onWifi, cellular)}
              onPress={() => router.push({ pathname: "/book/[id]", params: { id } })}
              onLongPress={() => offer(id, it)}
            />
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
