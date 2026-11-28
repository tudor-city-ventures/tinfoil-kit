// The Map tab: the map of where the person lives, on their phone. Until there is one, the places to pick from and how
// its download is going.
import {
  Camera,
  LocationManager,
  Map as MapView,
  NativeUserLocation,
  type CameraRef,
  type GeolocationPosition,
} from "@maplibre/maplibre-react-native";
import { Stack } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { FlatList, Linking, PermissionsAndroid, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Group, Pill, Row } from "@/components/group";
import { Icon } from "@/components/icon";
import { mapDay, mapsPath, mapStyle, WORLD } from "@/kit/maps";
import { findPlaces, place, type Place } from "@/kit/places";
import { type Box } from "@/kit/pmtiles";
import { mapLine } from "@/kit/status";
import { store, useKit, type MapDownload } from "@/kit/store";
import { radius, space, useColors } from "@/theme";

export function MapScreen() {
  const { map, mapDownload } = useKit();
  const [picking, setPicking] = useState(false);
  if (map && !picking)
    return <Shown id={map.place} file={map.file} download={mapDownload} onChange={() => setPicking(true)} />;
  return <Picker mine={map} download={mapDownload} onDone={map ? () => setPicking(false) : undefined} />;
}

function Picker({
  mine,
  download,
  onDone,
}: {
  mine?: { place: string; file: string };
  download?: MapDownload;
  onDone?: () => void;
}) {
  const c = useColors();
  const [typed, setTyped] = useState("");
  const groups = useMemo(() => {
    const by = new Map<string, Place[]>();
    for (const p of findPlaces(typed)) by.set(p.group, [...(by.get(p.group) ?? []), p]);
    return [...by].map(([name, list]) => ({ name, list }));
  }, [typed]);
  // The place already on the phone, or on its way, isn't downloaded again by a tap on its name
  const pick = (id: string) => {
    if (id !== mine?.place && id !== download?.place) store.getMap(id);
    onDone?.();
  };
  const day = mine && mapDay(mine.file);
  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerSearchBarOptions: {
            placeholder: "Search places",
            hideWhenScrolling: false,
            onChangeText: (e) => setTyped(e.nativeEvent.text),
          },
          headerRight: onDone
            ? () => (
                <Pressable accessibilityRole="button" onPress={onDone} hitSlop={space.s}>
                  <Text style={[styles.headerButton, { color: c.accent }]}>Cancel</Text>
                </Pressable>
              )
            : undefined,
        }}
      />
      <FlatList
        contentInsetAdjustmentBehavior="automatic"
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
        data={groups}
        keyExtractor={(g) => g.name}
        initialNumToRender={2}
        ListHeaderComponent={
          download ? (
            <Downloading d={download} />
          ) : (
            <>
              <Text style={[styles.intro, { color: c.mute }]}>
                Where do you live? Its map has every street, path and building, and the rest of the world in less
                detail. It works without the internet once it&apos;s on your phone.
              </Text>
              {mine ? (
                <Group footer={day ? `Yours is from ${day}.` : undefined}>
                  <Row
                    testID="map-update"
                    icon="download"
                    accent
                    title={`Get the newest map of ${place(mine.place)?.name ?? mine.place}`}
                    onPress={() => {
                      store.getMap(mine.place);
                      onDone?.();
                    }}
                  />
                </Group>
              ) : null}
            </>
          )
        }
        renderItem={({ item }) => (
          <Group label={item.name}>
            {item.list.map((p) => (
              <Row
                key={p.id}
                testID={`place-${p.id}`}
                title={p.name}
                detail={p.id === download?.place ? "Downloading" : p.id === mine?.place ? "On your phone" : undefined}
                onPress={() => pick(p.id)}
              />
            ))}
          </Group>
        )}
        ListEmptyComponent={
          <Group>
            <Row title="No place by that name" detail="Try your country, state or a big city near you." />
          </Group>
        }
      />
    </>
  );
}

function Downloading({ d }: { d: MapDownload }) {
  const failed = d.status === "failed";
  return (
    <Group
      label="Downloading"
      footer="The map downloads only while the app is open, and keeps your screen on until it's done."
    >
      <Row
        testID="map-download"
        icon={failed ? "failed" : "download"}
        accent
        title={place(d.place)?.name ?? d.place}
        detail={mapLine(d)}
        right={
          d.status === "downloading" && d.total ? (
            <Pill text={`${Math.floor((100 * d.received) / d.total)}%`} />
          ) : undefined
        }
        onPress={failed ? () => store.getMap(d.place) : undefined}
      />
      <Row testID="map-stop" title="Stop" onPress={() => store.stopMap()} />
    </Group>
  );
}

// Asked the first time the person wants to see where they are. On Android an approximate location is enough.
async function allowed(): Promise<boolean> {
  if (Platform.OS !== "android") return LocationManager.requestPermissions();
  const { ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION } = PermissionsAndroid.PERMISSIONS;
  const got = await PermissionsAndroid.requestMultiple([ACCESS_FINE_LOCATION, ACCESS_COARSE_LOCATION]);
  return Object.values(got).includes(PermissionsAndroid.RESULTS.GRANTED);
}

const inside = ([w, s, e, n]: Box, [lon, lat]: [number, number]) => lon >= w && lon <= e && lat >= s && lat <= n;

function Shown({
  id,
  file,
  download,
  onChange,
}: {
  id: string;
  file: string;
  download?: MapDownload;
  onChange: () => void;
}) {
  const c = useColors();
  const top = useSafeAreaInsets().top + space.s;
  const p = place(id);
  const name = p?.name ?? id;
  const style = useMemo(() => mapStyle(mapsPath(), file, p?.langs ?? []), [file, p]);
  const [drawn, setDrawn] = useState<{ file: string; ok: boolean }>(); // how the map's last try at drawing went
  const ok = drawn?.file === file ? drawn.ok : undefined;
  const camera = useRef<CameraRef>(null);
  const [me, setMe] = useState<"finding" | "here" | "outside" | "off">(); // where the person is, once they ask
  const waiting = useRef<(at: GeolocationPosition) => void>(undefined);
  const unwait = () => waiting.current && LocationManager.removeListener(waiting.current);
  useEffect(() => unwait, []);

  // Flies to the person's first fix; the dot then follows them on its own
  const locate = async () => {
    if (!(await allowed())) return setMe("off");
    unwait();
    setMe((m) => (m === "here" || m === "outside" ? m : "finding")); // a dot already there stays while it asks again
    waiting.current = (at) => {
      unwait();
      const here: [number, number] = [at.coords.longitude, at.coords.latitude];
      const near = !!p && inside(p.bbox, here);
      camera.current?.flyTo({ center: here, zoom: near ? 15 : WORLD });
      setMe(near ? "here" : "outside");
    };
    LocationManager.addListener(waiting.current);
  };
  return (
    <View style={styles.fill}>
      <Stack.Screen options={{ headerShown: false }} />
      <View
        style={styles.fill}
        accessible
        accessibilityLabel={ok ? `Map of ${name}` : ok === false ? `${name}'s map can't be shown` : "Drawing the map"}
      >
        <MapView
          key={file}
          testID="map"
          style={styles.fill}
          mapStyle={style}
          logo={false}
          onDidFinishLoadingMap={() => setDrawn({ file, ok: true })}
          onDidFailLoadingMap={() => setDrawn({ file, ok: false })}
        >
          {p ? (
            <Camera ref={camera} initialViewState={{ center: [p.home.lon, p.home.lat], zoom: 12 }} maxZoom={18} />
          ) : null}
          {me && me !== "off" ? <NativeUserLocation /> : null}
        </MapView>
      </View>
      <View style={[styles.over, { top }]} pointerEvents="box-none">
        <View style={styles.bar} pointerEvents="box-none">
          <Pressable
            testID="map-place"
            accessibilityRole="button"
            accessibilityHint="Pick another place"
            onPress={onChange}
            style={[styles.chip, { backgroundColor: c.cell }]}
          >
            <Text style={[styles.chipText, { color: c.ink }]}>{name}</Text>
            <Icon name="down" color={c.accent} size={14} />
          </Pressable>
          <Pressable
            testID="map-locate"
            accessibilityRole="button"
            accessibilityLabel="Show where I am"
            onPress={locate}
            hitSlop={space.s}
            style={[styles.round, { backgroundColor: c.cell }]}
          >
            <Icon name="locate" color={c.accent} size={18} />
          </Pressable>
        </View>
        {me === "finding" ? (
          <View style={[styles.note, { backgroundColor: c.cell }]}>
            <Text style={{ color: c.ink }}>Finding where you are</Text>
          </View>
        ) : null}
        {me === "outside" ? (
          <Pressable onPress={onChange} style={[styles.note, { backgroundColor: c.cell }]}>
            <Text style={{ color: c.ink }}>You&apos;re outside {name}&apos;s map. Tap to pick another place.</Text>
          </Pressable>
        ) : null}
        {me === "off" ? (
          <Pressable onPress={() => Linking.openSettings()} style={[styles.note, { backgroundColor: c.cell }]}>
            <Text style={{ color: c.ink }}>Location is off for Tinfoil Kit. Tap to turn it on in Settings.</Text>
          </Pressable>
        ) : null}
        {ok === false && !download ? (
          <Pressable onPress={() => store.getMap(id)} style={[styles.note, { backgroundColor: c.cell }]}>
            <Text style={{ color: c.ink }}>This map can&apos;t be shown. Tap to get it again.</Text>
          </Pressable>
        ) : null}
        {download ? (
          <Pressable
            testID="map-download"
            onPress={download.status === "failed" ? () => store.getMap(download.place) : undefined}
            style={[styles.note, { backgroundColor: c.cell }]}
          >
            <Text style={{ color: c.ink }}>
              {place(download.place)?.name ?? download.place}: {mapLine(download)}
            </Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  intro: { fontSize: 15, lineHeight: 21, marginHorizontal: space.xl, marginBottom: space.xl },
  headerButton: { fontSize: 17 },
  over: { position: "absolute", left: space.l, right: space.l, alignItems: "flex-start", gap: space.s },
  bar: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", alignSelf: "stretch" },
  round: { width: 40, height: 40, borderRadius: 20, alignItems: "center", justifyContent: "center" },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.xs,
    borderRadius: radius.pill,
    paddingHorizontal: space.l,
    paddingVertical: space.s,
  },
  chipText: { fontSize: 15, fontWeight: "600" },
  note: { borderRadius: radius.cell, paddingHorizontal: space.l, paddingVertical: space.s },
});
