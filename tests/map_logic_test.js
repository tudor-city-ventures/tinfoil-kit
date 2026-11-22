// Runs the portal's map logic (the same code the browser runs) against mock Photon / GraphHopper / tool-calling AI.
// usage: node map_logic_test.js portal.html   (mocks: photon :12322, old photon :12323, graphhopper :18989, llama :18081)
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const m = { exports: {} };
new Function("module", "exports", script)(m, m.exports);
const Kit = m.exports;
let failures = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ": " + detail : ""}`); if (!ok) failures++; };
const home = { lat: 40.7128, lon: -74.006, label: "New York, NY" };
const opts = { geoBase: "http://127.0.0.1:12322", routeBase: "http://127.0.0.1:18989", home, units: "imperial", label: "US Northeast" };

(async () => {
  // pure helpers
  check("fmtDist imperial", Kit.fmtDist(50, "imperial") === "160 ft" && Kit.fmtDist(16093, "imperial") === "10 mi" && Kit.fmtDist(3000, "imperial") === "1.9 mi",
        [50, 3000, 16093].map(x => Kit.fmtDist(x, "imperial")).join(" | "));
  check("fmtDist metric", Kit.fmtDist(420, "metric") === "420 m" && Kit.fmtDist(3456, "metric") === "3.5 km", Kit.fmtDist(3456, "metric"));
  check("fmtTime", Kit.fmtTime(20000) === "1 min" && Kit.fmtTime(95 * 60000) === "1 h 35 min", Kit.fmtTime(95 * 60000));
  check("parseLatLon", JSON.stringify(Kit.parseLatLon("40.7428, -73.986")) === JSON.stringify({ lat: 40.7428, lon: -73.986, name: "40.7428, -73.986", address: "" }) &&
        Kit.parseLatLon("100 Main St") === null);
  check("haversine ~1 deg lat = 111 km", Math.abs(Kit.haversine({ lat: 40, lon: -74 }, { lat: 41, lon: -74 }) - 111195) < 200);
  check("address search asks in the place's language, or in local names where Photon has none",
        Kit.photonLang("de") === "de" && Kit.photonLang(undefined) === "en" && Kit.photonLang("nb") === "default");
  const books = [{ id: "a", name: "mdwiki_en_all", language: "eng" }, { id: "b", name: "wikipedia_de_all_maxi", language: "deu" },
    { id: "c", name: "gutenberg_en", language: "eng" }, { id: "d", name: "x", language: "fra" }];
  check("library search: its Wikipedia's language first, then by number of books",
        JSON.stringify(Kit.libraryLanguages(books)) === JSON.stringify(["deu", "eng", "fra"]) &&
        JSON.stringify(Kit.libraryLanguages(books.filter(b => b.id !== "b"))) === JSON.stringify(["eng", "fra"]),
        JSON.stringify(Kit.libraryLanguages(books)));
  check("categoryFor", Kit.categoryFor("hospital") === "hospital" && Kit.categoryFor("drug store") === "pharmacy" &&
        Kit.categoryFor("Gas Station") === "gas" && Kit.categoryFor("urgent care") === "urgent_care" && Kit.categoryFor("pizza") === null);
  const intents = {
    "Directions to Kestrel Bay Medical Center": ["get_directions", a => a.to === "Kestrel Bay Medical Center" && a.from === "home" && a.mode === "car"],
    "walk from 100 Main St Testville to Larkspur General Hospital?": ["get_directions", a => a.from === "100 Main St Testville" && a.to === "Larkspur General Hospital" && a.mode === "foot"],
    "where is the nearest pharmacy": ["find_nearby", a => a.category === "pharmacy"],
    "closest hospital": ["find_nearby", a => a.category === "hospital"],
    "Where is Pellwood Hospital?": ["search_places", a => a.query === "Pellwood Hospital"],
  };
  for (const [q, [tool, ok]] of Object.entries(intents)) {
    const g = Kit.guessMapIntent(q);
    check(`intent: ${q}`, g.tool === tool && ok(g.args), JSON.stringify(g));
  }
  const mapQs = ["how do I get to the hospital", "nearest gas station", "directions to 41 East Lark Rd", "how far is Testville",
    "What's the nearest hospital and how do I get there?", "Where is the closest ER?", "where is Pellwood Hospital?",
    "walking directions to the shelter", "how do I drive to Albany", "address of 100 Main St"];
  const libQs = ["how do I purify water", "treating a burn", "what is the dose of ibuprofen for a child",
    "how far should I stay from a downed power line", "where is the femoral artery", "where's the best place to apply a tourniquet",
    "how do I get rid of lice", "what should I do if the power goes out"];
  check("map questions detected", mapQs.every(q => Kit.isMapQuestion(q)), mapQs.filter(q => !Kit.isMapQuestion(q)).join(" | "));
  check("library questions not taken by the map", libQs.every(q => !Kit.isMapQuestion(q)), libQs.filter(q => Kit.isMapQuestion(q)).join(" | "));

  // address search
  const hits = await Kit.searchPlaces(opts, "100 Main Street Testville", 5);
  check("address search", hits.length >= 1 && hits[0].name === "100 Main Street" && /Testville/.test(hits[0].address) && hits[0].distance_m > 0,
        JSON.stringify(hits[0]));
  const named = await Kit.searchPlaces(opts, "Kestrel Bay Medical", 5);
  check("place-name search", named[0] && named[0].name === "Kestrel Bay Medical Center" && named[0].direction,
        named[0] && `${named[0].name}, ${Kit.fmtDist(named[0].distance_m, "imperial")} ${named[0].direction}`);
  const coords = await Kit.searchPlaces(opts, "40.76,-73.93", 5);
  check("coordinates accepted as a place", coords.length === 1 && coords[0].lat === 40.76);
  let err = null;
  try { await Kit.resolvePlace(opts, "Nowhereville Zzz"); } catch (e) { err = e; }
  check("unknown place gives a clear error", err && /Couldn't find/.test(err.message), err && err.message);

  // nearest
  const near = await Kit.findNearby(opts, "hospital", "home", 5);
  check("nearest hospitals, sorted by distance", near.places.length === 3 && near.places.every((p, i, a) => !i || a[i - 1].distance_m <= p.distance_m),
        near.places.map(p => `${p.name} ${Kit.fmtDist(p.distance_m, "imperial")}`).join(" | "));
  const oldPhoton = await Kit.findNearby({ ...opts, geoBase: "http://127.0.0.1:12323" }, "pharmacy", "", 5);
  check("nearest works on an older Photon (tag filter fallback)", oldPhoton.places.length === 1 && oldPhoton.places[0].name === "Corner Pharmacy",
        oldPhoton.places.map(p => p.name).join(", "));

  // directions
  const r = await Kit.getDirections(opts, "home", "Kestrel Bay Medical Center", "car");
  check("driving directions", r.distance_m > 1000 && r.steps.length === 3 && r.coordinates.length === 20 && r.steps[1].at && r.to.name === "Kestrel Bay Medical Center",
        `${Kit.fmtDist(r.distance_m, "imperial")}, ${Kit.fmtTime(r.time_ms)}, ${r.steps.map(s => s.text).join(" / ")}`);
  const w = await Kit.getDirections(opts, { lat: 40.7428, lon: -73.986, name: "A" }, "Larkspur General Hospital", "walk");
  check("walking directions use the foot profile", w.profile === "foot" && w.time_ms > r.time_ms * 0 && w.from.name === "A");

  // tool results for the AI
  const t1 = await Kit.runMapTool(opts, "find_nearby", { category: "hospital" });
  check("find_nearby tool output", t1.display.type === "places" && t1.model.results.length === 3 && /mi (north|south|east|west|northeast|northwest|southeast|southwest)/.test(t1.model.results[0].distance),
        JSON.stringify(t1.model).slice(0, 160));
  const t2 = await Kit.runMapTool(opts, "get_directions", { to: "Kestrel Bay Medical Center" });
  check("get_directions tool output", t2.display.type === "route" && t2.model.steps.length === 3 && /mi$/.test(t2.model.distance), JSON.stringify(t2.model).slice(0, 160));

  // full AI tool loop (mock model calls find_nearby, then get_directions, then answers)
  const seen = [];
  const ans = await Kit.mapAgent({ ...opts, aiBase: "http://127.0.0.1:18081", model: "Mock-Tools" },
    "What's the nearest hospital and how do I get there?", (name, args, res, e) => seen.push(name + (e ? "!" : "")));
  check("AI tool loop", seen.join(",") === "find_nearby,get_directions" && /Mock answer/.test(ans) && /Turn left/.test(ans), seen.join(",") + " -> " + ans.slice(0, 120));
  const seen2 = [];
  const ans2 = await Kit.mapAgent({ ...opts, aiBase: "http://127.0.0.1:18081", model: "Mock-Tools" },
    "directions to Nowhereville Zzz", (name, args, res, e) => seen2.push(name + (e ? "!" : "")));
  check("tool errors are passed back to the AI", seen2.join(",") === "get_directions!" && /error/.test(ans2), ans2.slice(0, 120));
  let aiErr = null;
  try { await Kit.mapAgent({ ...opts, aiBase: "http://127.0.0.1:18081/nope", model: "x" }, "nearest hospital"); } catch (e) { aiErr = e; }
  check("AI HTTP errors surface with a status", aiErr && aiErr.status === 404, aiErr && aiErr.message.slice(0, 60));

  console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
