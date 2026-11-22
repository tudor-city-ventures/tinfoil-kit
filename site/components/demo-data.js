// What the demo of the kit page shows (components/demo.jsx): sample questions with answers written ahead of time, the
// books, sample notes and a sample town with its streets. Nothing here comes from a model, a book or a map server.
// Medical answers follow the kit's own rule (tools/portal.html, SYSTEM): warning signs first, no doses.

export const MODELS = ["Inkling-2-Mini", "Qwen3.8-27B", "Gemma-4-26B-A4B", "Gemma-4-12B", "Gemma-4-E4B"];

// The books, in the kit page's groups (classify in tools/portal.html), with the summaries the kit builder gives them.
export const BOOKS = [
  ["Medical", "WikiMed", "A medical encyclopedia: conditions, drugs, procedures."],
  [
    "Medical",
    "MedlinePlus",
    "Plain-language guides to illnesses, tests and medicines, from the US National Library of Medicine.",
  ],
  ["Medical", "Military medicine", "Trauma care manuals from the US military."],
  ["Medical", "CDC Travelers' Health", "The CDC's guide to diseases, vaccines and safe food and water."],
  ["Survival & how-to", "Water treatment", "How to find, filter and disinfect drinking water."],
  ["Survival & how-to", "Ready.gov", "FEMA's guides for every kind of emergency."],
  ["Survival & how-to", "Post-disaster guides", "Shelter, sanitation and recovery after a disaster."],
  ["Survival & how-to", "Knots", "Illustrated knots for rope, tarps and rescue."],
  ["Survival & how-to", "iFixit", "Step-by-step repair guides for phones, appliances, cars and tools."],
  ["Survival & how-to", "US Army publications", "Field manuals on survival, first aid, navigation and more."],
  ["Survival & how-to", "Home improvement Q&A", "Plumbing, wiring, heating and repairs around the house."],
  ["Survival & how-to", "Appropedia", "Off-grid and low-tech solutions: solar, water, building."],
  [
    "Reference & learning",
    "Wikipedia",
    "All of English Wikipedia, with images. The reference for nearly any question.",
  ],
  ["Reference & learning", "Wiktionary", "A full dictionary and thesaurus."],
  ["Reference & learning", "Wikivoyage", "Travel guides for places you might need to go."],
  ["Reference & learning", "Wikibooks", "Open textbooks and how-tos."],
].map(([group, title, summary]) => ({ group, title, summary }));
export const GROUPS = ["Medical", "Survival & how-to", "Reference & learning"];

// Pages from the books, short: the sources the answers cite, and a few more for the library's search.
const PAGES = {
  boil: [
    "Water disinfection",
    "CDC Travelers' Health",
    "Boiling is the most reliable way to make water safe to drink. Bring it to a rolling boil for 1 minute. Above 6,500 feet (2,000 m), boil it for 3 minutes. Let it cool on its own, and store it in clean containers with lids.",
  ],
  bleach: [
    "Emergency disinfection of drinking water",
    "Water treatment",
    "Use regular, unscented chlorine bleach. Add 2 drops per quart or liter. For a gallon, add 8 drops of 6% bleach, or 6 drops of 8.25% bleach. Stir and let it stand for 30 minutes. The water should smell slightly of chlorine. If it doesn't, add the same amount again and wait 15 more minutes.",
  ],
  sodis: [
    "Solar water disinfection",
    "Wikipedia",
    "Water is put in clear plastic bottles of 2 liters or less and left in full sunlight for six hours. Ultraviolet light and heat kill the germs. If more than half the sky is cloudy, the bottles need two days in a row. It doesn't work in steady rain, or with cloudy water.",
  ],
  fuel: [
    "Water",
    "Ready.gov",
    "Boiling or disinfecting won't make water safe if it has fuel or toxic chemicals in it. If you know or suspect that it does, use a different source of water.",
  ],
  burn: [
    "Burn",
    "WikiMed",
    "Cool the burn with cool running water for 20 minutes, as soon as you can. Use cool water, not ice or ice water, which can injure the skin further. Cooling a large area can make the person dangerously cold.",
  ],
  armyBurn: [
    "First aid for burns",
    "US Army publications",
    "Remove the casualty from the source of the burn. Take off clothing and jewelry near the burn, but don't pull off anything stuck to it. Cover the burn loosely with a clean, dry dressing. Don't break blisters or put ointment on the burn.",
  ],
  medBurn: [
    "Burns",
    "MedlinePlus",
    "Get emergency help for burns that are large or deep, burns on the face, hands, feet, groin or a major joint, and burns from electricity or chemicals, or if the person breathed in smoke. Watch a burn for signs of infection: more pain, redness, swelling or pus.",
  ],
  faucet: [
    "Faucet troubleshooting",
    "iFixit",
    "A drip from the spout usually means a worn washer, seal or cartridge. A leak around the handle usually means a worn O-ring. Close the shut-off valves under the sink before you take the faucet apart.",
  ],
  faucetQA: [
    "How do I fix a dripping bathroom faucet?",
    "Home improvement Q&A",
    "Plug the drain first, so you don't lose the little screw. Pull the stem or cartridge and take it to the hardware store, so you come home with one that fits. Turn the water back on slowly when you're done.",
  ],
  plan: [
    "Make a plan",
    "Ready.gov",
    "Pick a place to meet right outside your home, and another outside your neighborhood in case you can't get home. Choose one contact out of town that everyone can call or text, and make sure the whole family, kids too, knows both places.",
  ],
  cold: [
    "Hypothermia",
    "WikiMed",
    "Hypothermia is a body temperature below 35 °C (95 °F). Shivering and confusion are early signs. Move the person somewhere warm and dry, take off wet clothing, and warm the middle of the body first.",
  ],
  generator: [
    "Portable generators",
    "Ready.gov",
    "Never run a generator inside a home or garage, even with the doors open. Keep it outside, at least 20 feet from windows and doors, so carbon monoxide can't get in.",
  ],
  outage: [
    "Power outages",
    "Ready.gov",
    "Keep the refrigerator and freezer closed. A refrigerator keeps food cold for about 4 hours, and a full freezer for about 48 hours.",
  ],
  bowline: [
    "Bowline",
    "Knots",
    "The bowline makes a loop at the end of a rope that won't slip or jam. It's easy to untie, even after holding a heavy load.",
  ],
};
const page = (k) => ({ title: PAGES[k][0], book: PAGES[k][1], passage: PAGES[k][2] });
export const ALL_PAGES = Object.keys(PAGES).map(page);

// The sample questions. `answer` is markdown, as the AI writes it: [n] cites source n. The answers to `notes` and
// `map` questions are written in demo.jsx, from the notes and the town below.
export const QUESTIONS = [
  {
    id: "water",
    chip: "Safe drinking water",
    q: "How do I make water safe to drink without a filter?",
    queries: ["boil drinking water", "disinfect water bleach", "solar water disinfection"],
    read: 9,
    seconds: 12,
    sources: ["boil", "bleach", "sodis", "fuel"].map(page),
    answer: `**Boil it if you can.** It's the surest way to kill the germs that make people sick [1].

1. If the water is cloudy, let it settle, then pour it through a clean cloth or coffee filter.
2. Bring it to a rolling boil for 1 minute, or 3 minutes above 6,500 feet (2,000 m) [1].
3. Let it cool, and keep it in clean containers with lids [1].

**No way to boil it?** Use plain, unscented household bleach [2]:
- 2 drops per liter or quart
- 8 drops per gallon of 6% bleach, or 6 drops of 8.25% bleach
- Stir and wait 30 minutes. It should smell slightly of chlorine. If it doesn't, add the same amount again and wait 15 more minutes.

**No bleach either?** Fill clear plastic bottles, 2 liters or smaller, and leave them in full sun for 6 hours, or 2 days if it's cloudy [3].

None of this removes fuel or chemicals. If the water might have them, find another source [4].`,
  },
  {
    id: "burn",
    chip: "Treat a burn",
    q: "How do I treat a burn?",
    queries: ["burn first aid", "treating burns", "burn blisters infection"],
    read: 8,
    seconds: 11,
    sources: ["burn", "armyBurn", "medBurn"].map(page),
    answer: `**Get emergency help now if the burn:**
- is bigger than the person's hand, or the skin looks white, brown or charred [3]
- is on the face, hands, feet, groin or a joint [3]
- came from electricity or a chemical, or they breathed in smoke [3]

**For a small burn:**
1. Get away from the heat. Take off rings, watches and clothing near the burn, but leave anything stuck to the skin [2].
2. Cool it under cool running water for 20 minutes. Don't use ice, butter or creams [1].
3. Keep the rest of them warm, so they don't get chilled [1].
4. Cover it loosely with plastic wrap or a clean, dry dressing [2].
5. Don't pop blisters [2].

Over the next few days, watch for more pain, redness, swelling or pus. Those can mean an infection [3].`,
  },
  {
    id: "faucet",
    chip: "Fix a dripping faucet",
    q: "Our faucet keeps dripping. How do I fix it?",
    queries: ["dripping faucet repair", "replace faucet washer cartridge"],
    read: 7,
    seconds: 10,
    sources: ["faucet", "faucetQA"].map(page),
    answer: `A dripping faucet almost always needs a new washer, O-ring or cartridge [1]. You'll need a screwdriver and an adjustable wrench.

1. Close the shut-off valves under the sink, then open the faucet to let the water out [1].
2. Plug the drain so small parts can't fall in [2].
3. Pry the cap off the handle, take out the screw under it, and pull the handle off.
4. Loosen the nut with the wrench and pull out the stem or cartridge.
5. Take the old part to a hardware store and get one that matches [2].
6. Put it back together in reverse order, and turn the water back on slowly [2].

A drip from the spout usually means the washer or cartridge. A leak around the handle usually means the O-ring [1].`,
  },
  {
    id: "meet",
    chip: "Where do we meet?",
    q: "Where do we meet if we're split up?",
    queries: ["family meeting place", "family emergency plan"],
    read: 4,
    seconds: 7,
    notes: true,
    sources: ["plan"].map(page),
  },
  {
    id: "hospital",
    chip: "Nearest hospital",
    q: "How do I get to the nearest hospital?",
    map: true,
  },
];

export const NOTES = `Sam is allergic to penicillin.
Dad takes his heart pills at 8 every morning.
If we're split up, we meet at the library on Main Street.
Water shut-off: in the basement, by the furnace.
Dr. Patel: (802) 555-0147`;

// AI chat: a plain chat with the AI, no books.
export const CHATS = [
  {
    chip: "Translate to Spanish",
    q: "Translate into Spanish: We need clean water and a doctor.",
    answer: `**Necesitamos agua potable y un médico.**

Say it like this: neh-seh-see-TAH-mohs AH-gwah poh-TAH-bleh ee oon MEH-dee-koh.`,
  },
  {
    chip: "A note for the door",
    q: "Write a note for our front door: we're safe and went to the library on Main Street.",
    answer: `**WE ARE SAFE**

We've gone to the library on Main Street.

Left on: ____________ at ____________
Back by: ____________`,
  },
];

/* ------------------------------------------------------------------------------------------- the sample town */
// Points are in map units: the map is 800 wide and 560 tall, about 420 to the mile, north up.
export const W = 800,
  H = 560,
  MILE = 420;

// Where streets meet, and where places sit on them.
const N = {
  mW: [-20, 300],
  mCedar: [60, 300],
  fire: [105, 300],
  mElm: [150, 300],
  pharm: [228, 300],
  mOak: [300, 300],
  clinic: [338, 300],
  mChurch: [380, 300],
  lib: [440, 300],
  hardware: [478, 300],
  mRiver: [590, 300],
  market: [645, 300],
  mRidge: [700, 300],
  mE: [820, 300],
  r9W: [-20, 70],
  r9Oak: [300, 70],
  gas: [362, 70],
  r9River: [548, 70],
  r9E: [820, 70],
  oN: [300, -20],
  oBirch: [300, 150],
  oSpring: [300, 230],
  oMill: [300, 360],
  oMaple: [300, 440],
  oS: [300, 580],
  rN: [540, -20],
  rHosp: [576, 180],
  rHill: [600, 360],
  rPharm: [611, 395],
  rS: [676, 580],
  eBirch: [150, 150],
  eSpring: [150, 230],
  eMill: [150, 360],
  eMaple: [150, 440],
  home: [150, 482],
  eS: [150, 580],
  cSpring: [60, 230],
  cMaple: [60, 440],
  cS: [60, 525],
  school: [228, 230],
  police: [340, 230],
  chSpring: [380, 230],
  sE: [470, 230],
  bW: [40, 150],
  bE: [452, 150],
  chMill: [380, 360],
  park: [440, 360],
  millE: [500, 360],
  mapleW: [-20, 440],
  hosp: [640, 180],
  ridgeHill: [700, 376],
  ridgeS: [700, 580],
  hillE: [820, 386],
};

// Each street: its name, its kind (how wide it's drawn and how fast a car goes on it), and its points west to
// east or north to south. A name is a point above; a pair of numbers only shapes the street between them.
export const STREETS = [
  ["Route 9", "highway", ["r9W", "r9Oak", "gas", "r9River", "r9E"]],
  [
    "Main Street",
    "major",
    [
      "mW",
      "mCedar",
      "fire",
      "mElm",
      "pharm",
      "mOak",
      "clinic",
      "mChurch",
      "lib",
      "hardware",
      "mRiver",
      "market",
      "mRidge",
      "mE",
    ],
  ],
  ["Oak Avenue", "major", ["oN", "r9Oak", "oBirch", "oSpring", "mOak", "oMill", "oMaple", "oS"]],
  [
    "River Road",
    "major",
    ["rN", "r9River", [566, 130], "rHosp", [585, 240], "mRiver", "rHill", "rPharm", [624, 440], [650, 500], "rS"],
  ],
  ["Elm Street", "minor", ["eBirch", "eSpring", "mElm", "eMill", "eMaple", "home", "eS"]],
  ["Cedar Lane", "minor", ["cSpring", "mCedar", "cMaple", "cS"]],
  ["Spring Street", "minor", ["cSpring", "eSpring", "school", "oSpring", "police", "chSpring", "sE"]],
  ["Birch Street", "minor", ["bW", "eBirch", "oBirch", "bE"]],
  ["Church Street", "minor", ["chSpring", "mChurch", "chMill"]],
  ["Mill Street", "minor", ["eMill", "oMill", "chMill", "park", "millE"]],
  ["Maple Street", "minor", ["mapleW", "cMaple", "eMaple", "oMaple"]],
  ["Hospital Drive", "minor", ["rHosp", "hosp"]],
  ["Ridge Road", "minor", ["mRidge", "ridgeHill", "ridgeS"]],
  ["Hill Street", "minor", ["rHill", "ridgeHill", "hillE"]],
].map(([name, kind, pts]) => ({
  name,
  kind,
  pts: pts.map((p) => (typeof p === "string" ? { id: p, xy: N[p] } : { xy: p })),
}));

// The places search, directions and Nearest find. `at` is the point on a street that directions go to.
export const PLACES = [
  ["home", "Home", "14 Elm Street", null, [150, 482], "home"],
  ["hospital", "Riverside General Hospital", "200 Hospital Drive", "hospital", [640, 180], "hosp"],
  ["clinic", "Main Street Clinic", "210 Main Street", "urgent_care", [338, 316], "clinic"],
  ["pharmacy", "Corner Pharmacy", "88 Main Street", "pharmacy", [228, 286], "pharm"],
  ["pharmacy2", "River Road Pharmacy", "310 River Road", "pharmacy", [627, 396], "rPharm"],
  ["police", "Police Department", "10 Spring Street", "police", [340, 216], "police"],
  ["fire", "Fire Station 2", "5 Main Street", "fire_station", [105, 286], "fire"],
  ["school", "Lincoln Elementary School", "40 Spring Street (emergency shelter)", "shelter", [228, 204], "school"],
  ["center", "Community Center", "25 Hill Street (emergency shelter)", "shelter", [724, 356], "ridgeHill"],
  ["gas", "Route 9 Gas", "500 Route 9", "gas", [362, 84], "gas"],
  ["market", "Riverside Market", "400 Main Street", "grocery", [645, 316], "market"],
  ["hardware", "Main Street Hardware", "150 Main Street", "hardware", [478, 286], "hardware"],
  ["fountain", "Drinking fountain", "Veterans Park", "drinking_water", [432, 404], "park"],
  ["library", "Main Street Library", "120 Main Street", null, [440, 318], "lib"],
].map(([id, name, address, kind, xy, at]) => ({ id, name, address, kind, xy, at }));

export const PINS = [
  {
    id: "meet",
    name: "Family meeting spot",
    note: "If we're split up, meet at the library.",
    xy: [440, 318],
    at: "lib",
  },
  { id: "aunt", name: "Aunt Rosa's", note: "Spare key under the blue pot.", xy: [742, 420], at: "ridgeHill" },
];

// Nearest's buttons, as the kit page has them (CATEGORIES in tools/portal.html).
export const CATEGORIES = [
  ["hospital", "Hospital"],
  ["urgent_care", "Urgent care / clinic"],
  ["pharmacy", "Pharmacy"],
  ["police", "Police"],
  ["fire_station", "Fire station"],
  ["shelter", "Shelter"],
  ["gas", "Gas station"],
  ["grocery", "Grocery"],
  ["hardware", "Hardware"],
  ["drinking_water", "Drinking water"],
];

// What the map draws under the streets, in the colors of the kit's map style (Protomaps' light flavor).
export const RIVER = "M450 -20C462 70 505 120 512 200C518 270 528 330 552 390C576 450 610 500 640 580";
export const AREAS = [
  ["wood", "M-10 84H135L128 136L60 140L-10 138Z"],
  ["park", "M392 378H548L604 530H392Z"],
  ["hospital", "M612 112H736V250H612Z"],
  ["school", "M192 160H282V220H192Z"],
  ["industrial", "M600 8H770V58H600Z"],
];
export const POND = [455, 456, 34, 19];

// Buildings: the larger ones by hand, then houses along the residential streets.
const BIG = [
  [650, 124, 76, 40],
  [698, 164, 28, 66],
  [206, 172, 50, 24],
  [326, 198, 28, 22],
  [92, 270, 26, 18],
  [214, 268, 28, 20],
  [326, 310, 26, 22],
  [420, 308, 42, 32],
  [466, 268, 26, 20],
  [630, 310, 34, 26],
  [622, 384, 22, 22],
  [350, 82, 24, 12],
  [708, 340, 34, 24],
  [612, 18, 50, 26],
  [680, 22, 70, 24],
  [166, 270, 22, 20],
  [192, 272, 16, 18],
  [246, 270, 24, 20],
  [272, 270, 18, 20],
  [318, 268, 30, 20],
  [352, 270, 18, 20],
  [392, 268, 30, 20],
  [428, 270, 26, 20],
  [166, 310, 26, 20],
  [198, 310, 20, 18],
  [228, 310, 30, 22],
  [262, 310, 26, 20],
  [356, 310, 18, 20],
  [392, 310, 20, 18],
  [486, 310, 18, 22],
  [604, 270, 30, 20],
  [660, 268, 26, 20],
  [716, 270, 30, 20],
  [756, 272, 24, 18],
  [716, 310, 28, 22],
  [756, 312, 26, 20],
  [312, 240, 20, 16],
  [390, 240, 26, 18],
  [430, 240, 24, 16],
  [312, 372, 26, 18],
  [346, 372, 22, 18],
];
function houses() {
  const out = [];
  const row = (x0, x1, y, step) => {
    for (let x = x0; x <= x1; x += step) out.push([x - 5, y - 5, 10, 10]);
  };
  const col = (x, y0, y1, step) => {
    for (let y = y0; y <= y1; y += step) out.push([x - 5, y - 5, 10, 10]);
  };
  col(132, 322, 420, 24);
  col(168, 322, 420, 24);
  col(132, 460, 548, 22);
  col(168, 456, 548, 22);
  col(42, 252, 280, 24);
  col(78, 322, 420, 24);
  col(42, 322, 420, 24);
  col(42, 460, 500, 22);
  col(78, 460, 500, 22);
  col(132, 170, 210, 20);
  col(168, 172, 210, 18);
  col(132, 250, 280, 24);
  col(168, 250, 280, 24);
  row(182, 280, 422, 22);
  row(182, 280, 458, 22);
  row(70, 130, 168, 22);
  row(320, 430, 168, 22);
  row(320, 430, 132, 22);
  row(184, 280, 342, 24);
  row(184, 280, 378, 24);
  row(320, 360, 342, 20);
  row(720, 790, 400, 20);
  col(682, 400, 548, 24);
  col(718, 446, 548, 24);
  row(720, 790, 432, 20);
  row(626, 680, 336, 22);
  row(740, 790, 330, 24);
  row(318, 360, 400, 22);
  row(318, 360, 470, 22);
  row(318, 370, 520, 24);
  row(232, 280, 500, 24);
  row(232, 280, 540, 24);
  row(184, 210, 500, 24);
  return out;
}
export const BUILDINGS = BIG.concat(houses());

// Labels: streets (drawn on the street), places and areas. [text, x, y, angle, kind, the place it names]
export const LABELS = [
  ["Main Street", 760, 300, 0, "road"],
  ["Main Street", 105, 300, 0, "road"],
  ["Route 9", 690, 70, 0, "road"],
  ["Route 9", 200, 70, 0, "road"],
  ["Oak Avenue", 300, 400, -90, "road"],
  ["Oak Avenue", 300, 110, -90, "road"],
  ["River Road", 607, 470, -66, "road"],
  ["River Road", 557, 100, -73, "road"],
  ["Elm Street", 150, 190, -90, "road"],
  ["Spring Street", 424, 230, 0, "road"],
  ["Birch Street", 376, 150, 0, "road"],
  ["Mill Street", 226, 360, 0, "road"],
  ["Maple Street", 226, 440, 0, "road"],
  ["Cedar Lane", 60, 372, -90, "road"],
  ["Ridge Road", 700, 470, -90, "road"],
  ["Hill Street", 762, 381, 5, "road"],
  ["Mill River", 497, 150, 76, "water"],
  ["Veterans Park", 480, 506, 0, "park"],
  ["Hemlock Woods", 58, 112, 0, "park"],
  ["Riverside General", 674, 210, 0, "poi", "hospital"],
  ["Hospital", 674, 224, 0, "poi", "hospital"],
  ["Lincoln Elementary", 237, 212, 0, "poi", "school"],
  ["DOWNTOWN", 424, 258, 0, "area"],
  ["EAST SIDE", 748, 482, 0, "area"],
  ["NORTH END", 196, 116, 0, "area"],
];
