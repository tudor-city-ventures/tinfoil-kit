// Runs the portal's core logic (the same code the browser runs) against the live kit servers.
const fs = require("fs");
const html = fs.readFileSync(process.argv[2], "utf8");
const script = html.split("<script>")[1].split("</script>")[0];
const m = { exports: {} };
new Function("module", "exports", script)(m, m.exports);
const Kit = m.exports;
const LIB = "http://127.0.0.1:18888", AI = "http://127.0.0.1:18080";
let failures = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ": " + detail : ""}`); if (!ok) failures++; };

(async () => {
  // unit-level checks
  check("keywords drop stopwords", JSON.stringify(Kit.keywords("How do I make water safe to drink?")) === JSON.stringify(["water", "safe", "drink"]));
  check("fallback queries", Kit.fallbackQueries("my child has a fever of 103, what should I do").length >= 2,
        JSON.stringify(Kit.fallbackQueries("my child has a fever of 103, what should I do")));
  check("query line cleanup", JSON.stringify(Kit.cleanQueryLines("1. fever\n- Child fever treatment\n\"febrile seizure\"\nHere are queries:")) ===
        JSON.stringify(["fever", "Child fever treatment", "febrile seizure"]));
  const rendered = Kit.render("## Steps\n1. Boil **1 minute** [1]\n2. Add bleach [2, 3]\n\nDone <script>", 2);
  check("markdown render + citations + escaping", rendered.includes("<ol>") && rendered.includes('href="#src-1"') &&
        rendered.includes('href="#src-2"') && !rendered.includes('href="#src-3"') && rendered.includes("&lt;script&gt;"), rendered.replace(/\n/g, " "));
  check("html to text", Kit.htmlToText("<html><body><h1>T</h1><script>x()</script><p>A &amp; B&nbsp;C</p><ul><li>one</li></ul></body></html>") === "T\nA & B C\n- one");

  // live: catalog + search + sources
  const books = Kit.parseCatalog(await (await fetch(LIB + "/catalog/v2/entries?count=-1")).text());
  check("catalog parsed", books.length === 2, books.map(b => `${b.id} [${b.group}]`).join(", "));
  const q = "How much bleach do I add to a gallon of water to make it safe to drink?";
  const queries = await Kit.makeQueries({ aiBase: AI, model: "Tiny", queryTimeoutMs: 20000 }, q);
  check("queries (tiny model gives gibberish; fallbacks must still be there)", queries.includes("bleach gallon water") || queries.some(x => /bleach/.test(x)), JSON.stringify(queries));
  const progress = [];
  const sources = await Kit.gatherSources(q, books, { libraryBase: LIB, root: "", queries, onProgress: t => progress.push(t) });
  check("found the bleach article", sources.length > 0 && sources[0].title === "Water purification", sources.map(s => s.title).join(", "));
  check("passage contains the dose", sources.length > 0 && /8 drops/.test(sources[0].passages.join(" ")));
  const fever = await Kit.gatherSources("my child has a fever what should I do", books,
    { libraryBase: LIB, root: "", queries: Kit.fallbackQueries("my child has a fever what should I do") });
  check("medical question finds Fever", fever.some(s => s.title === "Fever"), fever.map(s => s.title).join(", "));

  // live: streaming answer
  const msgs = Kit.buildMessages(q, sources);
  check("prompt includes excerpt and question", msgs[1].content.includes("[1] \"Water purification\"") && msgs[1].content.includes(q));
  let content = "", reasoning = "", deltas = 0;
  await Kit.streamChat({ aiBase: AI, model: "Tiny", maxTokens: 40 }, msgs, (c, r) => { content += c; reasoning += r; deltas++; });
  check("streamed an answer", deltas > 5 && (content.length + reasoning.length) > 0, `${deltas} chunks`);
  // second model triggers a swap (models-max 1)
  let c2 = "";
  await Kit.streamChat({ aiBase: AI, model: "Two", maxTokens: 10 }, msgs, c => { c2 += c; });
  check("switching models works", c2.length > 0);
  const models = await Kit.listModels(AI);
  check("model list", models.includes("Tiny") && models.includes("Two"), models.join(", "));

  // CORS as a browser on the portal origin would see it
  const pre = await fetch(AI + "/v1/chat/completions", { method: "OPTIONS", headers: { Origin: "http://127.0.0.1:18888", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type" } });
  check("CORS preflight allowed for portal", pre.headers.get("access-control-allow-origin") === "http://127.0.0.1:18888", pre.headers.get("access-control-allow-origin"));
  const evil = await fetch(AI + "/v1/models", { headers: { Origin: "http://evil.example" } });
  check("other websites blocked", evil.status === 403, String(evil.status));

  console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
