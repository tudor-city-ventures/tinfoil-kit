import { Stack } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { findKits, type FoundKit } from "../../modules/kit-files";
import { Button } from "@/components/button";
import { Group, Row } from "@/components/group";
import { Icon } from "@/components/icon";
import { catalog } from "@/kit/catalog";
import { size } from "@/kit/format";
import {
  cleanCode,
  KitError,
  kitMapFrom,
  kitPlaces,
  listKit,
  pageUrl,
  phoneBook,
  readAddress,
  zimOf,
  type HomeKit,
  type KitListing,
} from "@/kit/home";
import { spaceLeft } from "@/kit/qa";
import { store, useKit } from "@/kit/store";
import { space, useColors } from "@/theme";

const LOOK = 4; // seconds to look for kits on the Wi-Fi

const byId = new Map(catalog.map((b) => [b.id, b]));

const why = (e: unknown) => (e instanceof KitError ? e.message : "Something went wrong. Try again.");

// The day of the world map a map was cut from (20261120), from its file's name
const dayOf = (file?: string) => /-(\d{8})\.pmtiles$/.exec(file ?? "")?.[1];

// A kit at home, or a phone shared like one: found on the Wi-Fi or typed in, let in with its code, then its books and
// map to copy
export function KitAtHome() {
  const { home } = useKit();
  return (
    <>
      <Stack.Screen options={{ title: home ? home.name : "Copy from a kit or phone", headerLargeTitle: false }} />
      {home ? <Copy kit={home} /> : <Connect />}
    </>
  );
}

// Finds the kits and phones sharing on this Wi-Fi, or takes a typed address, then asks for the code
function Connect() {
  const c = useColors();
  const [found, setFound] = useState<FoundKit[]>();
  const [typing, setTyping] = useState(false);
  const [address, setAddress] = useState("");
  const [picked, setPicked] = useState<FoundKit>();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let gone = false;
    findKits(LOOK)
      .catch(() => [])
      .then((kits) => gone || setFound(kits));
    return () => {
      gone = true;
    };
  }, []);

  const typed = typing ? readAddress(address) : undefined;
  const where = picked ? `${picked.host}:${picked.port}` : typed?.address;
  const theCode = cleanCode(code) || typed?.code || "";

  async function connect() {
    if (!where || busy) return;
    if (theCode.length !== 8) return setProblem("The access code is 8 digits.");
    setBusy(true);
    setProblem(undefined);
    try {
      const listing = await listKit({ address: where, code: theCode, phone: picked?.phone });
      const name = picked?.name ?? listing.name;
      store.setHome({ name, address: where, code: theCode, ...(listing.phone && { phone: true }) });
    } catch (e) {
      setProblem(why(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic" keyboardShouldPersistTaps="handled">
      <Group
        label="On this Wi-Fi"
        footer={
          found?.length === 0
            ? "None found. On a kit's computer, open the kit, then More, then Share with family. On a phone, in Get " +
              "more, tap Share with a phone. A kit on Windows doesn't show here: type its address."
            : undefined
        }
      >
        {found === undefined ? <Row title="Looking…" right={<ActivityIndicator color={c.mute} />} /> : null}
        {(found ?? []).map((k) => (
          <Row
            key={`${k.name}${k.host}`}
            testID={`kit-${k.name}`}
            icon={k.phone ? "phone" : "drive"}
            title={k.name}
            detail={k.host}
            accent={picked === k}
            onPress={() => {
              setPicked(k);
              setTyping(false);
              setProblem(undefined);
            }}
          />
        ))}
        <Row
          testID="kit-type"
          icon="wifi"
          title="Type its address"
          accent={typing}
          onPress={() => {
            setTyping(true);
            setPicked(undefined);
            setProblem(undefined);
          }}
        />
      </Group>
      {typing ? (
        <Group
          label="Address"
          footer="It's on the kit's computer, under More, then Share with family. Or paste the link from there."
        >
          <TextInput
            testID="kit-address"
            value={address}
            onChangeText={setAddress}
            placeholder="192.168.1.20:8000"
            placeholderTextColor={c.mute}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            style={[styles.input, { color: c.ink }]}
          />
        </Group>
      ) : null}
      {where ? (
        <Group
          label="Access code"
          footer={
            problem ??
            (picked?.phone
              ? "The 8 digits on the other phone's screen. You type it once."
              : "The 8 digits on the kit's computer, under More, then Share with family. You type it once.")
          }
        >
          <TextInput
            testID="kit-code"
            value={code || typed?.code || ""}
            onChangeText={setCode}
            onSubmitEditing={connect}
            placeholder="8 digits"
            placeholderTextColor={c.mute}
            keyboardType="number-pad"
            maxLength={9}
            style={[styles.input, styles.code, { color: c.ink }]}
          />
        </Group>
      ) : null}
      {where ? (
        <View style={styles.buttons}>
          {busy ? (
            <ActivityIndicator color={c.accent} />
          ) : (
            <Button title="Connect" onPress={connect} testID="kit-connect" />
          )}
        </View>
      ) : null}
    </ScrollView>
  );
}

// The kit's books and map, each copied to the phone with a tap, and its page in the browser. A phone's the same, with
// no page.
function Copy({ kit }: { kit: HomeKit }) {
  const c = useColors();
  const what = kit.phone ? "phone" : "kit";
  const { items, map, mapDownload } = useKit();
  const [listing, setListing] = useState<KitListing>();
  const [problem, setProblem] = useState<KitError | Error>();
  const [tries, setTries] = useState(0);

  useEffect(() => {
    let gone = false;
    listKit(kit)
      .then((l) => gone || setListing(l))
      .catch((e: Error) => gone || setProblem(e));
    return () => {
      gone = true;
    };
  }, [kit, tries]);

  const books = (listing?.books ?? []).flatMap((part) => {
    const id = phoneBook(part);
    const zim = zimOf(part);
    return id && zim ? [{ id, zim, title: byId.get(id)?.title ?? part.title }] : [];
  });
  const from = kitMapFrom(listing?.map ?? null);
  const places = kitPlaces(listing?.map ?? null, mapDownload?.place ?? map?.place);

  function forget() {
    Alert.alert(`Forget ${kit.name}?`, "Books you copied from it stay on this phone.", [
      { text: "Cancel", style: "cancel" },
      { text: "Forget", style: "destructive", onPress: () => store.setHome(undefined) },
    ]);
  }

  return (
    <ScrollView contentInsetAdjustmentBehavior="automatic">
      {problem ? (
        <Group footer={why(problem)}>
          {problem instanceof KitError && problem.problem === "code" ? (
            <Row title="Type the new code" testID="kit-again" onPress={() => store.setHome(undefined)} />
          ) : (
            <Row
              title="Try again"
              testID="kit-again"
              onPress={() => {
                setProblem(undefined);
                setTries((n) => n + 1);
              }}
            />
          )}
        </Group>
      ) : null}
      {!listing && !problem ? (
        <Group>
          <Row title={`Asking the ${what}…`} right={<ActivityIndicator color={c.mute} />} />
        </Group>
      ) : null}
      {listing ? (
        <Group
          label="Its books"
          footer={
            books.length
              ? `Copies come over the Wi-Fi, without the internet. This phone has ${freeSpace()} free.`
              : `This ${what} has no books this app can open yet.`
          }
        >
          {books.map((b) => {
            const have = items[b.id];
            return (
              <Row
                key={b.id}
                testID={`copy-${b.id}`}
                title={b.title}
                detail={size(b.zim.bytes)}
                right={
                  have ? (
                    <Icon name={have.status === "ready" ? "ready" : "download"} color={c.mute} size={22} />
                  ) : (
                    <Pressable
                      testID={`copy-get-${b.id}`}
                      accessibilityRole="button"
                      accessibilityLabel={`Copy ${b.title}`}
                      hitSlop={12}
                      onPress={() => store.copy(b.id, b.zim)}
                    >
                      <Icon name="add" color={c.accent} size={24} />
                    </Pressable>
                  )
                }
              />
            );
          })}
        </Group>
      ) : null}
      {listing && from ? (
        <Group
          label="Its map"
          footer={
            places.length
              ? `Every street, path and building, cut from the ${what}'s map. It takes the place of the map on this ` +
                "phone."
              : `The ${what}'s map is of a place this app doesn't know.`
          }
        >
          {places.map((p) => {
            const going = mapDownload?.place === p.id;
            const mine = map?.place === p.id && !going;
            // the phone's map of the place, unless the kit's is from a newer world map
            const here = mine && (dayOf(map?.file) ?? "") >= (from.day ?? "");
            return (
              <Row
                key={p.id}
                testID={`copy-map-${p.id}`}
                title={`Map of ${p.name}`}
                detail={here ? "On this phone" : going ? "Copying" : mine ? "Newer than this phone's" : undefined}
                right={
                  here || going ? (
                    <View testID={here ? `map-ready-${p.id}` : undefined}>
                      <Icon name={here ? "ready" : "download"} color={c.mute} size={22} />
                    </View>
                  ) : (
                    <Pressable
                      testID={`copy-map-get-${p.id}`}
                      accessibilityRole="button"
                      accessibilityLabel={`Copy the map of ${p.name}`}
                      hitSlop={12}
                      onPress={() => store.getMap(p.id, from)}
                    >
                      <Icon name="add" color={c.accent} size={24} />
                    </Pressable>
                  )
                }
              />
            );
          })}
        </Group>
      ) : null}
      {kit.phone ? null : (
        <Group footer="The kit's AI, maps and whole library, in this phone's browser, while you're on its Wi-Fi.">
          <Row icon="drive" title="Open the kit" testID="kit-open" onPress={() => void Linking.openURL(pageUrl(kit))} />
        </Group>
      )}
      <Group>
        <Row title={`Forget this ${what}`} testID="kit-forget" onPress={forget} />
      </Group>
      <Text style={[styles.address, { color: c.mute }]}>{kit.address}</Text>
    </ScrollView>
  );
}

function freeSpace(): string {
  try {
    return size(spaceLeft());
  } catch {
    return "some";
  }
}

const styles = StyleSheet.create({
  input: { fontSize: 17, padding: space.l, paddingVertical: space.m },
  code: { fontSize: 22, letterSpacing: 4, fontVariant: ["tabular-nums"] },
  buttons: { marginHorizontal: space.l, marginTop: -space.m, marginBottom: space.xl },
  address: { textAlign: "center", fontSize: 13, marginBottom: space.xl },
});
