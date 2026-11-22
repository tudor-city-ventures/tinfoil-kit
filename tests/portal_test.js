// Runs the portal's core logic (the same code the browser runs) against the live kit servers.
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const m = { exports: {} };
new Function("module", "exports", script)(m, m.exports);
const Kit = m.exports;
const LIB = "http://127.0.0.1:18888",
  AI = "http://127.0.0.1:18080";
// The test model's fixed answer (tests/make_tiny_model.py)
const ANSWER = require("child_process").execFileSync(
  "python3",
  ["-c", "from make_tiny_model import ANSWER; print(ANSWER, end='')"],
  { cwd: __dirname, encoding: "utf8", env: { ...process.env, PYTHONIOENCODING: "utf-8" } },
);
let failures = 0;
const check = (name, ok, detail) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ": " + detail : ""}`);
  if (!ok) failures++;
};

(async () => {
  // unit-level checks
  check(
    "keywords drop stopwords",
    JSON.stringify(Kit.keywords("How do I make water safe to drink?")) === JSON.stringify(["water", "safe", "drink"]),
  );
  check(
    "fallback queries",
    Kit.fallbackQueries("my child has a fever of 103, what should I do").length >= 2,
    JSON.stringify(Kit.fallbackQueries("my child has a fever of 103, what should I do")),
  );
  // Search without the AI searches the question's own words: no contractions, and no search twice in another order
  const split = Kit.fallbackQueries("Where do we meet if we're split up?");
  check(
    "searches without the AI skip contractions and repeats",
    JSON.stringify(split) === JSON.stringify(["meet split", "split", "meet"]),
    JSON.stringify(split),
  );
  check(
    "query line cleanup",
    JSON.stringify(Kit.cleanQueryLines('1. fever\n- Child fever treatment\n"febrile seizure"\nHere are queries:')) ===
      JSON.stringify(["fever", "Child fever treatment", "febrile seizure"]),
  );
  const rendered = Kit.render("## Steps\n1. Boil **1 minute** [1]\n2. Add bleach [2, 3]\n\nDone <script>", 2);
  check(
    "markdown render + citations + escaping",
    rendered.includes("<ol>") &&
      rendered.includes('href="#src-1"') &&
      rendered.includes('href="#src-2"') &&
      !rendered.includes('href="#src-3"') &&
      rendered.includes("&lt;script&gt;"),
    rendered.replace(/\n/g, " "),
  );
  check(
    "html to text",
    Kit.htmlToText(
      "<html><body><h1>T</h1><script>x()</script><p>A &amp; B&nbsp;C</p><ul><li>one</li></ul></body></html>",
    ) === "T\nA & B C\n- one",
  );
  const noted = Kit.buildMessages("What can Sam take for a headache?", [], "  Sam is allergic to ibuprofen.\n");
  check(
    "the household's notes go to the AI with every question",
    noted[0].content.startsWith("You are the assistant") &&
      noted[0].content.endsWith("<notes>\nSam is allergic to ibuprofen.\n</notes>"),
    JSON.stringify(noted[0].content.slice(-60)),
  );
  check(
    "no notes, no notes in the prompt",
    !Kit.buildMessages("x", [], " \n").some((m) => m.content.includes("<notes>")),
  );
  const long = Kit.withNotes("S", "a".repeat(5000));
  check(
    "long notes go to the AI cut to about a page",
    long.length < 4400 && long.includes("a\n[...]\n</notes>"),
    `${long.length} characters`,
  );
  const merge = [
    [{ text: "A", version: "v1" }, { text: "A B", since: "v1" }, "keep"],
    [{ text: "A", version: "v2" }, { text: "A B", since: "v1" }, "ask"],
    [{ text: "", version: "" }, { text: "B", since: "v1" }, "keep"],
    [{ text: "A", version: "v1" }, null, "drop"],
    [{ text: "A", version: "v2" }, { text: "A", since: "v1" }, "drop"],
  ].map(([kit, typed, want]) => Kit.notesMerge(kit, typed) === want);
  check(
    "notes typed while the kit couldn't keep them: kept if the kit's are unchanged or empty, else asked",
    merge.every(Boolean),
    JSON.stringify(merge),
  );
  // Print the essentials, from a kit with two of the books and no Ready.gov
  const printed = Kit.printList(
    [
      { id: "zimgit-post-disaster_en_2024-05", name: "zimgit-post-disaster_en" },
      { id: "zimgit-medicine_en_2024-08", name: "zimgit-medicine_en" },
    ],
    "/root",
  );
  const aid = printed.find((d) => d.first === 124) || { links: [] };
  check(
    "print list: what the kit's books have, linked at the first page to print, the best book first",
    printed.length === Kit.PRINT.length - 1 &&
      !printed.some((d) => /Ready\.gov/.test(d.doc)) &&
      aid.count === 6 &&
      aid.links[0] ===
        "/root/content/zimgit-medicine_en_2024-08/files/First%20Aid%20and%20Medicine%20(11).pdf#page=124" &&
      String(aid.links[1]).startsWith("/root/content/zimgit-post-disaster_en_2024-05/files/") &&
      printed.reduce((t, d) => t + d.count, 1) === 21,
    printed.map((d) => `${d.title}: ${d.count}`).join("; "),
  );

  // live: catalog + search + sources
  const books = Kit.parseCatalog(await (await fetch(LIB + "/catalog/v2/entries?count=-1")).text());
  check("catalog parsed", books.length === 2, books.map((b) => `${b.id} [${b.group}]`).join(", "));
  const q = "How much bleach do I add to a gallon of water to make it safe to drink?";
  const queries = await Kit.makeQueries({ aiBase: AI, model: "Tiny", queryTimeoutMs: 20000 }, q);
  check(
    "queries (the test model's answer isn't a query; fallbacks must still be there)",
    queries.includes("bleach gallon water") || queries.some((x) => /bleach/.test(x)),
    JSON.stringify(queries),
  );
  const progress = [];
  const sources = await Kit.gatherSources(q, books, {
    libraryBase: LIB,
    root: "",
    queries,
    onProgress: (t) => progress.push(t),
  });
  check(
    "found the bleach article",
    sources.length > 0 && sources[0].title === "Water purification",
    sources.map((s) => s.title).join(", "),
  );
  check("passage contains the dose", sources.length > 0 && /8 drops/.test(sources[0].passages.join(" ")));
  const fever = await Kit.gatherSources("my child has a fever what should I do", books, {
    libraryBase: LIB,
    root: "",
    queries: Kit.fallbackQueries("my child has a fever what should I do"),
  });
  check(
    "medical question finds Fever",
    fever.some((s) => s.title === "Fever"),
    fever.map((s) => s.title).join(", "),
  );

  // live: streaming answer
  const msgs = Kit.buildMessages(q, sources);
  check(
    "prompt includes excerpt and question",
    msgs[1].content.includes('[1] "Water purification"') && msgs[1].content.includes(q),
  );
  let content = "",
    reasoning = "",
    deltas = 0;
  await Kit.streamChat({ aiBase: AI, model: "Tiny", maxTokens: 100 }, msgs, (c, r) => {
    content += c;
    reasoning += r;
    deltas++;
  });
  check(
    "streamed the answer with every character intact",
    deltas > 5 && content === ANSWER && !reasoning,
    `${deltas} chunks: ${JSON.stringify(content)}`,
  );
  // second model triggers a swap (models-max 1)
  let c2 = "";
  await Kit.streamChat({ aiBase: AI, model: "Two", maxTokens: 10 }, msgs, (c) => {
    c2 += c;
  });
  check("switching models works", c2.length > 0 && ANSWER.startsWith(c2), JSON.stringify(c2));
  const models = await Kit.listModels(AI);
  check("model list", models.includes("Tiny") && models.includes("Two"), models.join(", "));

  // CORS as a browser on the portal origin would see it
  const pre = await fetch(AI + "/v1/chat/completions", {
    method: "OPTIONS",
    headers: {
      Origin: "http://127.0.0.1:18888",
      "Access-Control-Request-Method": "POST",
      "Access-Control-Request-Headers": "content-type",
    },
  });
  check(
    "CORS preflight allowed for portal",
    pre.headers.get("access-control-allow-origin") === "http://127.0.0.1:18888",
    pre.headers.get("access-control-allow-origin"),
  );
  const evil = await fetch(AI + "/v1/models", { headers: { Origin: "http://evil.example" } });
  check("other websites blocked", evil.status === 403, String(evil.status));

  console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
  process.exit(failures ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
