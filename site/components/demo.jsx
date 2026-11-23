"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import {
  ALL_PAGES,
  AREAS,
  BOOKS,
  BUILDINGS,
  CATEGORIES,
  CHATS,
  GROUPS,
  H,
  LABELS,
  MILE,
  MODELS,
  NOTES,
  PINS,
  PLACES,
  POND,
  PRINT,
  QUESTIONS,
  RIVER,
  SHARE,
  STREETS,
  W,
} from "@/components/demo-data";

// A demo of the kit page (tools/portal.html): its layout and words, with answers written ahead of time
// (components/demo-data.js). It runs no AI, no library and no map server, and keeps nothing anyone types.

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const norm = (s) =>
  String(s)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

/* ------------------------------------------------------------ the sample town: streets as a graph, directions */
const SPEED = { highway: 45, major: 30, minor: 20 }; // mph by car
const WALK = 3.1; // mph on foot
const seg = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
const GRAPH = {};
const ROADS = {}; // each kind of street as one path, for drawing
for (const s of STREETS) {
  ROADS[s.kind] = (ROADS[s.kind] || "") + "M" + s.pts.map((p) => p.xy.join(" ")).join("L");
  let from = null,
    pts = [];
  for (const p of s.pts) {
    pts.push(p.xy);
    if (!p.id) continue;
    if (from) {
      const e = { name: s.name, kind: s.kind, len: pts.slice(1).reduce((t, q, i) => t + seg(pts[i], q), 0) };
      (GRAPH[from] = GRAPH[from] || []).push({ ...e, to: p.id, pts });
      (GRAPH[p.id] = GRAPH[p.id] || []).push({ ...e, to: from, pts: [...pts].reverse() });
    }
    from = p.id;
    pts = [p.xy];
  }
}

// The quickest way by car, or the shortest on foot, as the streets it takes.
function shortest(a, b, mode) {
  const cost = (e) => (mode === "foot" ? e.len : e.len / SPEED[e.kind]);
  const best = { [a]: 0 },
    prev = {},
    done = new Set();
  for (;;) {
    let u = null;
    for (const n of Object.keys(best)) if (!done.has(n) && (u === null || best[n] < best[u])) u = n;
    if (u === null) return null;
    if (u === b) break;
    done.add(u);
    for (const e of GRAPH[u] || []) {
      const c = best[u] + cost(e);
      if (!(e.to in best) || c < best[e.to]) {
        best[e.to] = c;
        prev[e.to] = [u, e];
      }
    }
  }
  const edges = [];
  for (let n = b; n !== a; n = prev[n][0]) edges.unshift(prev[n][1]);
  return edges;
}

// A corner's instruction, in the words of the kit's directions (GraphHopper's): y points down, so a positive cross
// product is a right turn.
function turn([a0, a1], [b0, b1]) {
  const x1 = a1[0] - a0[0],
    y1 = a1[1] - a0[1],
    x2 = b1[0] - b0[0],
    y2 = b1[1] - b0[1];
  const deg = (Math.atan2(x1 * y2 - y1 * x2, x1 * x2 + y1 * y2) * 180) / Math.PI;
  const side = deg > 0 ? "right" : "left",
    d = Math.abs(deg);
  return d < 20 ? "Continue" : d < 60 ? `Turn slight ${side}` : d < 140 ? `Turn ${side}` : `Turn sharp ${side}`;
}

function directions(from, to, mode) {
  const edges = shortest(from.at, to.at, mode);
  if (!edges || !edges.length) return null;
  const steps = [];
  let ms = 0;
  for (const e of edges) {
    ms += (e.len / MILE / (mode === "foot" ? WALK : SPEED[e.kind])) * 3600000;
    const last = steps[steps.length - 1];
    if (last && last.name === e.name) {
      last.len += e.len;
      last.pts.push(...e.pts.slice(1));
      continue;
    }
    const text = (last ? turn(last.pts.slice(-2), e.pts.slice(0, 2)) : "Continue") + " onto " + e.name;
    steps.push({ name: e.name, text, len: e.len, at: e.pts[0], pts: [...e.pts] });
  }
  const pts = [steps[0].pts[0], ...steps.flatMap((s) => s.pts.slice(1))];
  steps.push({ text: "Arrive at destination", len: 0, at: pts[pts.length - 1] });
  return { steps, pts, ms, len: edges.reduce((t, e) => t + e.len, 0), from, to, mode };
}

// Distances and times as the kit page writes them, in miles (fmtDist, fmtTime and bearing in tools/portal.html).
function fmtDist(units) {
  const mi = units / MILE;
  return mi < 0.1 ? Math.round((mi * 5280) / 10) * 10 + " ft" : mi.toFixed(mi < 9.95 ? 1 : 0) + " mi";
}
function fmtTime(ms) {
  const min = Math.max(1, Math.round(ms / 60000));
  return min < 60 ? min + " min" : Math.floor(min / 60) + " h " + (min % 60) + " min";
}
function compass(a, b) {
  const deg = ((Math.atan2(b[0] - a[0], a[1] - b[1]) * 180) / Math.PI + 360) % 360;
  return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][
    Math.round(deg / 45) % 8
  ];
}

const KIND = Object.fromEntries(CATEGORIES);
const HOME = PLACES.find((p) => p.id === "home");
const HOSPITAL = PLACES.find((p) => p.id === "hospital");
const PINNED = PINS.map((p) => ({ ...p, address: "", pin: true }));
const EVERYWHERE = PLACES.concat(PINNED);

// What a search box finds: the name first, then the address, then the kind of place; the nearest first among equals.
function findPlaces(q, origin = HOME) {
  const n = norm(q),
    words = n.split(" ");
  if (n.length < 2) return [];
  return EVERYWHERE.map((p) => {
    const name = norm(p.name),
      where = norm(p.address),
      all = [name, where, norm(KIND[p.kind] || "")].join(" ");
    const score =
      name === n
        ? 5
        : name.startsWith(n)
          ? 4
          : name.includes(n) || n.includes(name)
            ? 3
            : where.includes(n)
              ? 2
              : words.every((w) => all.includes(w))
                ? 1
                : 0;
    return [score, seg(origin.xy, p.xy), p];
  })
    .filter(([s]) => s)
    .sort((a, b) => b[0] - a[0] || a[1] - b[1])
    .map(([, , p]) => p);
}

function nearest(kind, origin = HOME) {
  return PLACES.filter((p) => p.kind === kind)
    .map((p) => ({ ...p, d: seg(origin.xy, p.xy), dir: compass(origin.xy, p.xy) }))
    .sort((a, b) => a.d - b.d);
}

const START = directions(HOME, HOSPITAL, "car");

/* ----------------------------------------------------------------------- answers, as the kit page shows them */
// The kit page's little markdown: paragraphs, lists, **bold** and [n] citations that jump to source n.
function inline(text, cites, onCite) {
  const out = [];
  const re = /\*\*([^*]+)\*\*|\[(\d+(?:\s*,\s*\d+)*)\]/g;
  let last = 0,
    m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    if (m[1] != null) out.push(<strong key={m.index}>{m[1]}</strong>);
    else
      m[2].split(/\s*,\s*/).forEach((n, i) => {
        const k = +n;
        out.push(
          k >= 1 && k <= cites ? (
            <a
              key={m.index + "." + i}
              className="kd-cite"
              href={"#kd-src-" + k}
              onClick={(e) => {
                e.preventDefault();
                onCite(k);
              }}
            >
              [{k}]
            </a>
          ) : (
            "[" + n + "]"
          ),
        );
      });
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Md({ text, cites = 0, onCite }) {
  const blocks = [];
  let para = [],
    list = null;
  const flush = () => {
    if (para.length) blocks.push({ lines: para });
    para = [];
  };
  for (const line of text.split("\n")) {
    const li = /^\s*(?:([-*•])|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      flush();
      const tag = li[1] ? "ul" : "ol";
      if (!list || list.tag !== tag) blocks.push((list = { tag, items: [] }));
      list.items.push(li[2]);
    } else if (!line.trim()) {
      flush();
      list = null;
    } else {
      list = null;
      para.push(line);
    }
  }
  flush();
  return blocks.map((b, i) => {
    if (b.lines)
      return (
        <p key={i}>
          {b.lines.map((l, j) => (
            <Fragment key={j}>
              {j > 0 && <br />}
              {inline(l, cites, onCite)}
            </Fragment>
          ))}
        </p>
      );
    const Tag = b.tag;
    return (
      <Tag key={i}>
        {b.items.map((t, j) => (
          <li key={j}>{inline(t, cites, onCite)}</li>
        ))}
      </Tag>
    );
  });
}

// The AI reads the household's notes with every question: this one quotes where they say to meet.
function meetAnswer(notes) {
  const said = notes
    .split("\n")
    .flatMap((l) => l.match(/[^.!?]+[.!?]*/g) || [])
    .map((s) => s.trim())
    .find((s) => /\bmeet/i.test(s));
  const plan =
    "Ready.gov suggests a second place outside your neighborhood too, in case you can't get there, and one contact out of town that everyone can call or text [1].";
  if (!said) return "Your notes don't say where to meet yet. Write it down there, and Ask will use it.\n\n" + plan;
  const pin = PINS.find((p) => p.id === "meet");
  return (
    "Your notes say: **“" +
    said.replace(/\*/g, "") +
    "”**\n\n" +
    (/library/i.test(said)
      ? `It's pinned on your map as ${pin.name}, ${fmtDist(seg(HOME.xy, pin.xy))} from home. `
      : "") +
    plan
  );
}

const routeSteps = (r) => r.steps.map((s, i) => `${i + 1}. ${s.text}${s.len ? ` (${fmtDist(s.len)})` : ""}`).join("\n");

function hospitalAnswer() {
  const r = START;
  return (
    `The nearest hospital is **${HOSPITAL.name}**, ${HOSPITAL.address}, ${fmtDist(seg(HOME.xy, HOSPITAL.xy))} ${compass(HOME.xy, HOSPITAL.xy)} of home. By car it's ${fmtDist(r.len)}, about ${fmtTime(r.ms)}:\n\n` +
    routeSteps(r) +
    "\n\nIn an emergency, call 911 first if a phone works."
  );
}

// With no AI, the kit plans the route itself and lists it, as describe() does in the kit page.
function routeAnswer() {
  return `**Driving to ${HOSPITAL.name}:** ${fmtDist(START.len)}, about ${fmtTime(START.ms)}.\n\n` + routeSteps(START);
}

const SCOPES = [["all", `Search all books (${BOOKS.length})`, BOOKS.length]].concat(
  GROUPS.map((g) => ["group:" + g, g + " only", BOOKS.filter((b) => b.group === g).length]),
);
const FIRST = QUESTIONS[0];
const words = (s) => s.match(/\s*\S+/g) || []; // how an answer streams in: a word or two at a time

function AskPanel({ notes, cmd, onMap, say }) {
  const [q, setQ] = useState(FIRST.q);
  const [scope, setScope] = useState("all");
  const [model, setModel] = useState(MODELS[0]);
  const [progress, setProgress] = useState(`Done in ${FIRST.seconds}s. Sources are listed below.`);
  const [answer, setAnswer] = useState(FIRST.answer);
  const [sources, setSources] = useState(FIRST.sources);
  const [mapped, setMapped] = useState(false);
  const [searched, setSearched] = useState(null); // the question whose passages Search shows, for the AI to answer
  const [busy, setBusy] = useState(false);
  const [lit, setLit] = useState(0);
  const run = useRef(0);
  useEffect(
    () => () => {
      run.current = -1;
    },
    [],
  );
  useEffect(() => {
    if (!cmd) return;
    setQ(cmd.q);
    ask(cmd.q);
  }, [cmd]); // eslint-disable-line react-hooks/exhaustive-deps

  // As the kit page does it: "ai" (Ask the AI: the AI picks what to search for, then answers), "search" (Search: the
  // question's own words, and the passages, with no AI) or "these" (Have the AI answer from these: no second search).
  async function ask(text, how = "ai") {
    const item = QUESTIONS.find((x) => norm(x.q) === norm(text));
    const id = ++run.current,
      fast = reduced();
    const wait = (ms) => new Promise((r) => setTimeout(r, fast ? 0 : ms)).then(() => run.current === id);
    setAnswer("");
    if (how !== "these") setSources([]);
    setMapped(false);
    setSearched(null);
    setLit(0);
    if (!item) {
      setBusy(false);
      setProgress("This demo only knows the sample questions above. On your laptop, ask or search for anything.");
      return;
    }
    setBusy(true);
    if (item.map) {
      const ai = how === "ai"; // with no AI, the kit goes straight to directions to the nearest hospital
      for (const [t, ms] of [
        ["Looking it up on the offline map...", 900],
        ...(ai ? [["Looked up find nearby...", 600]] : []),
        ["Looked up get directions...", 700],
      ]) {
        setProgress(t);
        if (!(await wait(ms))) return;
      }
      setAnswer(ai ? hospitalAnswer() : routeAnswer());
      setMapped(true);
      setProgress("Done. Map results come from your offline map data.");
      setBusy(false);
      return;
    }
    if (how !== "these") {
      const books = SCOPES.find((s) => s[0] === scope)[2],
        queries = how === "ai" ? item.queries : item.words,
        jobs = books * queries.length;
      const steps = [
        how === "ai" ? ["Working out what to search for...", 700] : ["Searching the library...", 200],
        [`Searching ${books} books for: ${queries.join(" | ")}`, 900],
      ];
      for (let n = 10; n < jobs; n += 20) steps.push([`Searching books... ${n}/${jobs}`, 220]);
      steps.push([`Reading ${item.read} articles...`, 700]);
      for (const [t, ms] of steps) {
        setProgress(t);
        if (!(await wait(ms))) return;
      }
      setSources(item.sources);
    }
    if (how === "search") {
      setSearched(item.q);
      setProgress(`Done in ${item.searchSeconds}s, without the AI: the best passages from your books.`);
      setBusy(false);
      return;
    }
    setProgress(`Found ${item.sources.length} source${item.sources.length === 1 ? "" : "s"}. Asking ${model}...`);
    if (!(await wait(900))) return;
    setProgress("Answering...");
    const toks = words(item.notes ? meetAnswer(notes) : item.answer);
    for (let i = 0; i < toks.length;) {
      i = fast ? toks.length : i + (i % 3 ? 1 : 2);
      setAnswer(toks.slice(0, i).join(""));
      if (!(await wait(30))) return;
    }
    setProgress(
      `Done in ${how === "these" ? item.seconds - item.searchSeconds : item.seconds}s. Sources are listed below.`,
    );
    setBusy(false);
  }
  function stop() {
    run.current++;
    setBusy(false);
    setProgress("Stopped.");
  }
  function cite(k) {
    setLit(k);
    const li = document.getElementById("kd-src-" + k);
    li.focus({ preventScroll: true });
    li.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
  }

  return (
    <>
      <form
        className="kd-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (q.trim() && !busy) ask(q);
        }}
      >
        <label htmlFor="kd-q" className="kd-label">
          Your question
        </label>
        <textarea
          id="kd-q"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              e.currentTarget.form.requestSubmit();
            }
          }}
          placeholder="Ask anything. e.g. How do I make water safe to drink without a filter?"
        />
        <div className="kd-row">
          <select aria-label="Which books to search" value={scope} onChange={(e) => setScope(e.target.value)}>
            {SCOPES.map(([v, t]) => (
              <option key={v} value={v}>
                {t}
              </option>
            ))}
          </select>
          <select
            className="kd-model"
            aria-label="Which AI model answers"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>
                Model: {m}
              </option>
            ))}
          </select>
          <button type="submit" className="kd-btn" disabled={busy}>
            Ask the AI
          </button>
          <button
            type="button"
            className="kd-btn secondary"
            disabled={busy}
            onClick={() => {
              if (q.trim()) ask(q, "search");
            }}
          >
            Search
          </button>
          <button type="button" className="kd-btn secondary" disabled={!busy} onClick={stop}>
            Stop
          </button>
        </div>
        <div className="kd-hint">
          <p>
            <b>Search</b>: the best passages from your books in seconds, without the AI. It uses very little power.
          </p>
          <p>
            <b>Ask the AI</b>: it reads your books and writes an answer, with sources. Slower, and it uses more power
            than Search.
          </p>
        </div>
      </form>
      <div className="kd-try">
        <span>Try one:</span>
        {QUESTIONS.map((x) => (
          <button
            key={x.id}
            type="button"
            className="kd-chip"
            onClick={() => {
              setQ(x.q);
              ask(x.q);
            }}
          >
            {x.chip}
          </button>
        ))}
      </div>
      <div className="kd-progress" role="status">
        {progress}
      </div>
      {searched && (
        <p className="kd-these">
          <button type="button" className="kd-btn secondary" onClick={() => ask(searched, "these")}>
            Have the AI answer from these
          </button>
        </p>
      )}
      {answer && (
        <div className="kd-answer">
          <Md text={answer} cites={sources.length} onCite={cite} />
          {mapped && (
            <p>
              <button type="button" className="kd-btn secondary" onClick={onMap}>
                Show on the map
              </button>
            </p>
          )}
        </div>
      )}
      {sources.length > 0 && (
        <div className={"kd-sources" + (searched ? " kd-passages" : "")}>
          <h3 className="kd-h">{searched ? "Best passages from your library" : "Sources from your library"}</h3>
          <ol>
            {sources.map((s, i) => (
              <li key={s.title} id={"kd-src-" + (i + 1)} tabIndex={-1} className={lit === i + 1 ? "lit" : undefined}>
                <button
                  type="button"
                  className="kd-link"
                  onClick={() => say(`In the kit, this opens “${s.title}” from ${s.book}, offline.`)}
                >
                  {s.title}
                </button>{" "}
                <span className="kd-book">{s.book}</span>
                <blockquote>{s.passage}</blockquote>
              </li>
            ))}
          </ol>
        </div>
      )}
      <p className="kd-note">
        Answers come from an AI on this computer reading your offline library. They can be wrong. Check the sources, and
        follow trained medical help whenever you can reach it.
      </p>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------- the map */
const at = ([x, y]) => ({ left: (x / W) * 100 + "%", top: (y / H) * 100 + "%" });
const FILL = { wood: "#d0ded0", park: "#9cd3b4", hospital: "#e4dad9", school: "#e4ded7", industrial: "#d1dde1" };
const WIDTH = { highway: 14, major: 11, minor: 7 };
const SMALL_ROADS = new Set(STREETS.filter((s) => s.kind === "minor").map((s) => s.name));

// A label near the map's edge lines up with its pin's side instead of running off the map.
function Marker({ p, color, onOpen, width }) {
  const x = (p.xy[0] / W) * width,
    half = p.name.length * 3.5;
  const side = x + half > width - 6 ? " end" : x - half < 6 ? " start" : "";
  return (
    <>
      <button
        type="button"
        className="kd-mk"
        style={at(p.xy)}
        aria-label={(p.pin ? "Pin: " : "") + p.name}
        onClick={(e) => {
          e.stopPropagation();
          onOpen(p);
        }}
      >
        <svg viewBox="0 0 24 34" width="22" height="31" aria-hidden="true">
          <path d="M12 33S2 20 2 12a10 10 0 0 1 20 0c0 8-10 21-10 21z" fill={color} stroke="#fff" strokeWidth="1.5" />
          <circle cx="12" cy="12" r="4" fill="#fff" />
        </svg>
      </button>
      <span className={"kd-mlabel" + side} style={at(p.xy)} aria-hidden="true">
        {p.name}
      </span>
    </>
  );
}

function Popup({ p, onClose, onRoute }) {
  const [x, y] = [p.xy[0] / W, p.xy[1] / H];
  const where = (y < 0.42 ? " below" : "") + (x < 0.3 ? " east" : x > 0.7 ? " west" : "");
  return (
    <div className={"kd-pop" + where} style={at(p.xy)} onClick={(e) => e.stopPropagation()}>
      <button type="button" className="kd-x" aria-label="Close" onClick={onClose}>
        ×
      </button>
      <b>{p.name}</b>
      {p.address && (
        <>
          <br />
          {p.address}
        </>
      )}
      {p.id !== "home" && (
        <small>
          {fmtDist(seg(HOME.xy, p.xy))} {compass(HOME.xy, p.xy)} of home (straight line)
        </small>
      )}
      {p.note && <p className="kd-pinnote">{p.note}</p>}
      {p.id !== "home" && (
        <div className="kd-popbtns">
          <button type="button" className="kd-btn secondary" onClick={() => onRoute(p)}>
            Directions here
          </button>
        </div>
      )}
    </div>
  );
}

// The town, drawn like the kit's map: streets, then the route, with labels that keep their size on screen.
// A place's own label steps aside while its marker shows the name. A small map names only the big streets, once each.
function Town({ scale, route, drawn, hide }) {
  const k = 1 / Math.max(scale, 0.3),
    small = scale < 0.6,
    named = new Set();
  const size = { road: 10.5, water: 11, park: 11, poi: 10.5, area: 10.5 };
  const labels = LABELS.filter(([text, , , , kind, place]) => {
    if (hide.has(place)) return false;
    if (!small) return true;
    if (kind === "road" ? SMALL_ROADS.has(text) || named.has(text) : kind !== "area" && kind !== "water") return false;
    named.add(text);
    return true;
  }).map(([text, x, y, a, kind]) => {
    const half = (text.length * (size[kind] * 0.6 + (kind === "area" ? 1.5 : 0)) * k) / 2; // roughly, to keep it on the map
    return [text, a ? x : Math.min(Math.max(x, half + 4), W - half - 4), y, a, kind];
  });
  const color = { road: "#625c56", water: "#1f6f7c", park: "#2b6a40", poi: "#7a3f38", area: "#6b6f63" };
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={
        "Map of a sample town" + (route ? `, with the route from ${route.from.name} to ${route.to.name}` : "")
      }
    >
      <rect width={W} height={H} fill="#e2dfda" />
      {AREAS.map(([kind, d]) => (
        <path key={d} d={d} fill={FILL[kind]} />
      ))}
      <path d={RIVER} fill="none" stroke="#80deea" strokeWidth="30" />
      <ellipse cx={POND[0]} cy={POND[1]} rx={POND[2]} ry={POND[3]} fill="#80deea" />
      <g fill="#cfcac4">
        {BUILDINGS.map(([x, y, w, h], i) => (
          <rect key={i} x={x} y={y} width={w} height={h} />
        ))}
      </g>
      <g fill="none" strokeLinecap="round" strokeLinejoin="round">
        {["minor", "major", "highway"].map((kind) => (
          <path key={kind} d={ROADS[kind]} stroke="#cbc5bc" strokeWidth={WIDTH[kind] + 2.5} />
        ))}
        {["minor", "major", "highway"].map((kind) => (
          <path key={kind} d={ROADS[kind]} stroke="#fff" strokeWidth={WIDTH[kind]} />
        ))}
      </g>
      <g
        fontFamily="var(--sans)"
        textAnchor="middle"
        dominantBaseline="central"
        stroke="#fff"
        strokeLinejoin="round"
        paintOrder="stroke"
      >
        {labels.map(([text, x, y, a, kind]) => (
          <text
            key={text + x + "," + y}
            x={x}
            y={y}
            transform={a ? `rotate(${a} ${x} ${y})` : undefined}
            fontSize={size[kind] * k}
            fill={color[kind]}
            strokeWidth={(kind === "road" ? 2.5 : 3) * k}
            fontStyle={kind === "water" ? "italic" : undefined}
            fontWeight={kind === "area" || kind === "poi" ? 600 : 500}
            letterSpacing={kind === "area" ? 1.5 * k : undefined}
          >
            {text}
          </text>
        ))}
      </g>
      {route && (
        <g
          key={drawn}
          className={drawn ? "kd-route draw" : "kd-route"}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path
            d={"M" + route.pts.map((p) => p.join(" ")).join("L")}
            stroke="#fff"
            strokeWidth={Math.min(9 * k, 15)}
            pathLength="1"
          />
          <path
            d={"M" + route.pts.map((p) => p.join(" ")).join("L")}
            stroke="#d9531e"
            strokeWidth={Math.min(5 * k, 8.5)}
            pathLength="1"
          />
        </g>
      )}
    </svg>
  );
}

function MapPanel({ cmd }) {
  const [search, setSearch] = useState("");
  const [found, setFound] = useState(null); // what the search box found, while its list is open
  const [from, setFrom] = useState("");
  const [to, setTo] = useState(HOSPITAL.name);
  const [mode, setMode] = useState("car");
  const [route, setRoute] = useState(START);
  const [drawn, setDrawn] = useState(0); // counts new routes, so each draws itself in
  const [msg, setMsg] = useState("");
  const [near, setNear] = useState(null); // Nearest's list
  const [marks, setMarks] = useState([]); // places marked on the map
  const [pop, setPop] = useState(null); // the place whose popup is open
  const [step, setStep] = useState(null); // a step of the directions, flashed on the map
  const [scale, setScale] = useState(1);
  const canvas = useRef(null);
  useEffect(() => {
    const el = canvas.current,
      ro = new ResizeObserver(() => setScale(el.clientWidth / W || 1));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (cmd) go(HOME, HOSPITAL, "car");
  }, [cmd]);

  function go(f, t, m) {
    setTo(t.name);
    setMode(m);
    setPop(null);
    setStep(null);
    setMarks([]);
    const r = f.at === t.at ? null : directions(f, t, m);
    setRoute(r);
    setMsg(r ? "" : f.at === t.at ? "You're there already." : "No directions: no route found.");
    if (r) setDrawn((n) => n + 1);
  }
  function runDirections() {
    const f = from.trim() ? findPlaces(from)[0] : HOME;
    const t = f && findPlaces(to, f)[0];
    if (!to.trim()) return (setMsg("No directions: type where to."), setRoute(null));
    if (!f || !t) {
      setRoute(null);
      setMsg(`No directions: nothing called “${(f ? to : from).trim()}” in this sample town.`);
      return;
    }
    go(f, t, mode);
  }
  function nearby(kind, label) {
    const origin = (from.trim() && findPlaces(from)[0]) || HOME,
      list = nearest(kind, origin);
    setNear({ label, list });
    setMarks(list);
    setPop(null);
  }
  function open(p) {
    setFound(null);
    setPop(p);
  }
  function pick(p) {
    setSearch(p.name);
    setMarks([p]);
    open(p);
  }

  const shown = new Map();
  marks.forEach((p) => shown.set(p.id, p));
  if (route && route.to.id !== "home" && !route.to.pin) shown.set(route.to.id, route.to);
  if (route && route.from.id !== "home" && !route.from.pin)
    shown.set(route.from.id + ":from", { ...route.from, start: true });

  return (
    <div className="kd-map">
      <div className="kd-mside">
        <div className="kd-mpanel">
          <input
            type="search"
            aria-label="Search an address or place"
            placeholder="Address or place"
            autoComplete="off"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setFound(norm(e.target.value).length >= 2 ? findPlaces(e.target.value).slice(0, 6) : null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && found && found[0]) {
                e.preventDefault();
                pick(found[0]);
              }
              if (e.key === "Escape") setFound(null);
            }}
          />
          {found && (
            <div className="kd-results">
              {found.length ? (
                found.map((p) => (
                  <button key={p.id} type="button" onClick={() => pick(p)}>
                    {p.name}
                    <small>{p.address || p.note}</small>
                  </button>
                ))
              ) : (
                <div>Nothing called that in this sample town.</div>
              )}
            </div>
          )}
          <h3 className="kd-h">Directions</h3>
          <input
            aria-label="From (blank means home)"
            placeholder="From: blank means home"
            autoComplete="off"
            value={from}
            onChange={(e) => setFrom(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runDirections()}
          />
          <input
            aria-label="To"
            placeholder="To: an address or place"
            autoComplete="off"
            value={to}
            onChange={(e) => setTo(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runDirections()}
          />
          <div className="kd-row">
            <select aria-label="Travel by" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="car">Drive</option>
              <option value="foot">Walk</option>
            </select>
            <button type="button" className="kd-btn" onClick={runDirections}>
              Go
            </button>
          </div>
          <div className="kd-dirsum" role="status">
            {route
              ? `${fmtDist(route.len)}, ${fmtTime(route.ms)} ${route.mode === "foot" ? "walking" : "driving"} from ${route.from.name} to ${route.to.name}${route.to.address ? ` (${route.to.address})` : ""}`
              : msg}
          </div>
          {route && (
            <ol className="kd-steps">
              {route.steps.map((s, i) => (
                <li key={i}>
                  <button type="button" className="kd-plain" onClick={() => setStep({ xy: s.at, n: Date.now() })}>
                    {s.text}
                    {s.len ? (
                      <>
                        {" "}
                        <small>{fmtDist(s.len)}</small>
                      </>
                    ) : null}
                  </button>
                </li>
              ))}
            </ol>
          )}
          <h3 className="kd-h">Nearest</h3>
          <div className="kd-chips">
            {CATEGORIES.map(([kind, label]) => (
              <button key={kind} type="button" className="kd-chip" onClick={() => nearby(kind, label)}>
                {label}
              </button>
            ))}
          </div>
          {near && (
            <ul className="kd-list" aria-label={"Nearest: " + near.label}>
              {near.list.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className="kd-plain"
                    onClick={() => {
                      setMarks([p]);
                      open(p);
                    }}
                  >
                    {p.name}{" "}
                    <small>
                      {fmtDist(p.d)} {p.dir}
                      {p.address ? " · " + p.address : ""}
                    </small>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <h3 className="kd-h">Pins</h3>
          <ul className="kd-list">
            {PINNED.map((p) => (
              <li key={p.id}>
                <button type="button" className="kd-plain" onClick={() => open(p)}>
                  {p.name}{" "}
                  <small>
                    {fmtDist(seg(HOME.xy, p.xy))} · {p.note}
                  </small>
                </button>
              </li>
            ))}
          </ul>
          <p className="kd-note">
            This sample town stands in for where you live. In the kit, click the map for its coordinates or to pin a
            place, like where the family meets.
          </p>
          <p className="kd-note">Home: {HOME.address}.</p>
        </div>
      </div>
      <div
        className="kd-mcanvas"
        ref={canvas}
        onClick={() => {
          setPop(null);
          setFound(null);
        }}
      >
        <Town scale={scale} route={route} drawn={drawn} hide={new Set([...shown.values()].map((p) => p.id))} />
        <span className="kd-home" style={at(HOME.xy)} title={"Home: " + HOME.address} />
        {PINNED.map((p) => (
          <Marker key={p.id} p={p} color="#1c1f1a" onOpen={open} width={scale * W} />
        ))}
        {[...shown.values()].map((p) => (
          <Marker
            key={p.id + (p.start ? ":from" : "")}
            p={p}
            color={p.start ? "#4a5a2a" : "#d9531e"}
            onOpen={open}
            width={scale * W}
          />
        ))}
        {step && <span key={step.n} className="kd-pulse" style={at(step.xy)} />}
        {pop && (
          <Popup
            p={pop}
            onClose={() => setPop(null)}
            onRoute={(p) => {
              setFrom("");
              go(HOME, p, mode);
            }}
          />
        )}
        <span className="kd-scale" aria-hidden="true" style={{ width: (MILE / 4 / W) * 100 + "%" }}>
          0.25 mi
        </span>
        <span className="kd-sample" aria-hidden="true">
          Sample town
        </span>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------ library, notes, chat */
function LibraryPanel({ say, onPrint }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState(null);
  function search(e) {
    e.preventDefault();
    const terms = norm(q).split(" ").filter(Boolean);
    if (!terms.length) return;
    setHits({
      q: q.trim(),
      list: ALL_PAGES.filter((p) => terms.every((t) => norm(`${p.title} ${p.book} ${p.passage}`).includes(t))),
    });
  }
  return (
    <>
      <form className="kd-row kd-libsearch" onSubmit={search}>
        <input
          type="search"
          aria-label="Search every book"
          placeholder="Search every book for a word or phrase"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button type="submit" className="kd-btn">
          Search
        </button>
      </form>
      <p className="kd-note kd-tight">
        Which pages to print first, while there&apos;s power:{" "}
        <button type="button" className="kd-link small" onClick={onPrint}>
          Print the essentials
        </button>
        .
      </p>
      {hits && (
        <div className="kd-hits">
          <p className="kd-progress" role="status">
            {hits.list.length
              ? `${hits.list.length} of this demo's sample pages ${hits.list.length === 1 ? "mentions" : "mention"} “${hits.q}”. The kit searches every page of every book.`
              : `None of this demo's few sample pages mention “${hits.q}”. The kit searches every page of every book.`}
          </p>
          {hits.list.length > 0 && (
            <ul className="kd-sources kd-unnumbered">
              {hits.list.map((p) => (
                <li key={p.title}>
                  <button
                    type="button"
                    className="kd-link"
                    onClick={() => say(`In the kit, this opens “${p.title}” from ${p.book}, offline.`)}
                  >
                    {p.title}
                  </button>{" "}
                  <span className="kd-book">{p.book}</span>
                  <blockquote>{p.passage}</blockquote>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {GROUPS.map((g) => {
        const list = BOOKS.filter((b) => b.group === g);
        return (
          <Fragment key={g}>
            <h3 className="kd-h">
              {g}
              <span>{list.length} books</span>
            </h3>
            <div className="kd-books">
              {list.map((b) => (
                <button
                  key={b.title}
                  type="button"
                  className="kd-bookcard"
                  onClick={() => say(`In the kit, this opens ${b.title}, offline.`)}
                >
                  <b>{b.title}</b>
                  <span>{b.summary}</span>
                </button>
              ))}
            </div>
          </Fragment>
        );
      })}
    </>
  );
}

function NotesPanel({ notes, setNotes, onAsk, onPrint }) {
  const [edited, setEdited] = useState(false);
  return (
    <>
      <div className="kd-form kd-notes">
        <label htmlFor="kd-notes-text" className="kd-label">
          Your notes
        </label>
        <textarea
          id="kd-notes-text"
          value={notes}
          maxLength={4000}
          onChange={(e) => {
            setNotes(e.target.value);
            setEdited(true);
          }}
        />
        <div className="kd-status" role="status">
          {edited ? "Only in this demo: nothing is sent or saved." : "Saved in the kit"}
        </div>
      </div>
      <div className="kd-try">
        <span>Try:</span>
        <button type="button" className="kd-chip" onClick={onAsk}>
          Ask where to meet
        </button>
      </div>
      <p className="kd-note">
        Write down what you&apos;d need to know in an emergency: who lives here, allergies and medicines, doctors, where
        to meet, where the water shut-off is. Ask reads your notes with every question, so its answers fit your
        household.{" "}
        <button type="button" className="kd-link small" onClick={onPrint}>
          Print them
        </button>{" "}
        with your pins and the nearest hospital, for when the battery&apos;s flat.
      </p>
      <p className="kd-note">
        They&apos;re saved in the kit&apos;s data folder, as notes.txt, which updates never touch. They aren&apos;t
        encrypted: anyone with this drive or computer, or with the kit&apos;s access code when it&apos;s shared, can
        read them. Leave out passwords and bank details.
      </p>
    </>
  );
}

function ChatPanel() {
  const [msgs, setMsgs] = useState([
    { who: "user", text: CHATS[0].q },
    { who: "ai", text: CHATS[0].answer },
  ]);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState("");
  const run = useRef(0);
  useEffect(
    () => () => {
      run.current = -1;
    },
    [],
  );
  async function send(text) {
    const chat = CHATS.find((c) => norm(c.q) === norm(text));
    if (!chat) return setNote("This demo only knows the examples above. In the kit, ask the AI anything.");
    const id = ++run.current,
      fast = reduced();
    setNote("");
    setDraft("");
    const toks = words(chat.answer);
    setMsgs((m) => [...m, { who: "user", text: chat.q }, { who: "ai", text: "" }]);
    await new Promise((r) => setTimeout(r, fast ? 0 : 600));
    for (let i = 0; i < toks.length && run.current === id;) {
      i = fast ? toks.length : i + (i % 3 ? 1 : 2);
      const shown = toks.slice(0, i).join("");
      setMsgs((m) => [...m.slice(0, -1), { who: "ai", text: shown }]);
      await new Promise((r) => setTimeout(r, fast ? 0 : 40));
    }
  }
  return (
    <>
      <p className="kd-note kd-first">
        In the kit, AI chat opens in a tab of its own: a plain chat with the AI on your laptop. It doesn&apos;t search
        your books or read your notes, so check anything important on Ask. You can attach photos there, like a broken
        part or a label.
      </p>
      <div className="kd-chat">
        {msgs.map((m, i) => (
          <div key={i} className={"kd-msg " + m.who}>
            <span className="kd-who">{m.who === "ai" ? "AI" : "You"}</span>
            {m.who === "ai" ? <Md text={m.text || "..."} /> : <p>{m.text}</p>}
          </div>
        ))}
      </div>
      <div className="kd-try">
        <span>Try one:</span>
        {CHATS.map((c) => (
          <button key={c.chip} type="button" className="kd-chip" onClick={() => send(c.q)}>
            {c.chip}
          </button>
        ))}
      </div>
      <form
        className="kd-chatform"
        onSubmit={(e) => {
          e.preventDefault();
          if (draft.trim()) send(draft);
        }}
      >
        <textarea
          aria-label="Message the AI"
          placeholder="Message the AI"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="kd-btn">
          Send
        </button>
      </form>
      <div className="kd-progress" role="status">
        {note}
      </div>
    </>
  );
}

/* ----------------------------------------------------------------------------------- print the essentials */
const NEAR = ["hospital", "urgent_care", "pharmacy", "fire_station", "police"];
const pages = (d) => (d.first ? d.last - d.first + 1 : d.pages);
const BLANKS = [
  "Who lives here",
  "Allergies and medicines",
  "Doctors and pharmacy",
  "Where we meet",
  "Someone to call outside the area",
  "Water, gas and power shut-offs",
];

// Drawn only while it shows, so the date it was printed is the visitor's, not the build's.
function PrintPanel({ notes, say }) {
  const day = new Date().toLocaleDateString(undefined, { dateStyle: "long" });
  const text = notes.trim();
  const doc = (d) => (
    <li key={d.title}>
      <div>
        <b>{d.title}</b>
        <span className="kd-pages">{pages(d)} pages</span>
        <p>
          {d.about && d.about + " "}
          <i>{d.doc}</i>: {d.first ? `pages ${d.first}–${d.last}` : "all of it"}.
        </p>
      </div>
      <button
        type="button"
        className="kd-btn secondary"
        onClick={() => say(`In the kit, this opens ${d.doc}${d.first ? " at page " + d.first : ""}, offline.`)}
      >
        {d.first ? "Open at page " + d.first : "Open it"}
      </button>
    </li>
  );
  return (
    <>
      <h3 className="kd-h" id="kd-print-h">
        Print the essentials
      </h3>
      <p className="kd-lead">
        If you have a printer, print these now, while there&apos;s power, and keep them with the kit. Most important
        first. About {PRINT.reduce((t, d) => t + pages(d), 1)} pages in all.
      </p>
      <ol className="kd-sources kd-print">
        <li>
          <div>
            <b>Your page</b>
            <span className="kd-pages">1 page</span>
            <p>Your home and pins, your notes, and the nearest hospitals. It&apos;s at the bottom.</p>
          </div>
          <button type="button" className="kd-btn" onClick={() => say("In the kit, this prints your page alone.")}>
            Print your page
          </button>
        </li>
        {PRINT.filter((d) => !d.more).map(doc)}
      </ol>
      <h3 className="kd-h">Then, if you can</h3>
      <ol className="kd-sources kd-print">{PRINT.filter((d) => d.more).map(doc)}</ol>
      <p className="kd-note">
        These are the kit&apos;s books, and some of them are decades old: a first aid course teaches what&apos;s
        current. Get trained medical help whenever you can reach it.
      </p>
      <h3 className="kd-h">Your page</h3>
      <div className="kd-sheet">
        <div className="kd-sheethead">
          <span>Tinfoil Kit</span>
          <span>Printed {day}</span>
        </div>
        <h4>Home</h4>
        <p>{HOME.address}</p>
        <h4>Pins</h4>
        <ul>
          {PINS.map((p) => (
            <li key={p.id}>
              <b>{p.name}</b>: {p.note}
              <br />
              <small>{fmtDist(seg(HOME.xy, p.xy))} from home</small>
            </li>
          ))}
        </ul>
        <h4>
          Nearest to home <small>(as the crow flies)</small>
        </h4>
        <ul>
          {NEAR.map((k) => (
            <li key={k}>
              <b>{KIND[k]}</b>:{" "}
              {nearest(k)
                .slice(0, 2)
                .map((p, i) => (
                  <Fragment key={p.id}>
                    {i > 0 && "; "}
                    {p.name}, {p.address}{" "}
                    <small>
                      ({fmtDist(p.d)} {p.dir})
                    </small>
                  </Fragment>
                ))}
            </li>
          ))}
        </ul>
        <h4>Notes</h4>
        {text ? (
          <p className="kd-sheetnotes">{text}</p>
        ) : (
          BLANKS.map((f) => (
            <p key={f} className="kd-fill">
              {f}
              <span />
            </p>
          ))
        )}
        <p className="kd-sheetfoot">
          Tinfoil Kit: an AI, a library and maps that work with no internet. To start it, see Read me first.txt in the
          TinfoilKit folder.
        </p>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------------------------------ share with family */
// What Share copies for the person to text, word for word as the kit page writes it (Kit.invite in tools/portal.html)
const invite = (address, code) =>
  "You can use my Tinfoil Kit: an AI, a library and maps that work without the internet. Join my Wi-Fi, then open " +
  address +
  "/?code=" +
  encodeURIComponent(code.replace(/\s+/g, ""));
const QR_PATH = SHARE.qr
  .map((row, y) => [...row].map((m, x) => (m === "1" ? `M${x + 4},${y + 4}h1v1h-1z` : "")).join(""))
  .join("");

function SharePanel({ shared, setShared, say }) {
  const next = useRef(""); // the button to focus once the page changes, as the one pressed is gone
  useEffect(() => {
    if (next.current) document.getElementById(next.current).focus();
    next.current = "";
  }, [shared]);
  function turn(on) {
    next.current = on ? "kd-invite-copy" : "kd-share-on";
    setShared(on);
    say(on ? "Only in this demo: nothing is shared." : "Turned off, the kit is on this computer only.");
  }
  return (
    <>
      <h3 className="kd-h">
        Share with family and friends{" "}
        <span className={"kd-sharestate" + (shared ? " on" : "")}>{shared ? "On" : "Off"}</span>
      </h3>
      {shared ? (
        <>
          <div className="kd-card kd-shareon">
            <p>
              The kit is shared on this network. To let someone in, text them this message. Its link opens the kit on
              their phone or laptop with no code to type, once they&apos;re on the same{" "}
              <span className="kd-nowrap">Wi-Fi</span>.
            </p>
            <p className="kd-invite">{invite(SHARE.address, SHARE.code)}</p>
            <button
              id="kd-invite-copy"
              type="button"
              className="kd-btn"
              onClick={() => say("In the kit, this copies the message, to text it to your family.")}
            >
              Copy message
            </button>
            <p>
              Or they open <b>{SHARE.address}</b> and type the access code <b>{SHARE.code}</b>, or scan this with the
              phone&apos;s camera:
            </p>
            <svg
              className="kd-qr"
              viewBox="0 0 37 37"
              role="img"
              aria-label="QR code that opens the kit, access code included"
              shapeRendering="crispEdges"
            >
              <rect width="37" height="37" fill="#fff" />
              <path d={QR_PATH} fill="#000" />
            </svg>
            <p className="kd-note">
              No internet needed: a router with power, or a phone&apos;s hotspot, is enough. Anyone with the link or the
              code can get in while they&apos;re on this Wi-Fi.
            </p>
          </div>
          <div className="kd-row">
            <button
              type="button"
              className="kd-btn secondary"
              onClick={() => say("In the kit, this makes a new access code and signs every device out.")}
            >
              New code
            </button>
            <button type="button" className="kd-btn secondary" onClick={() => turn(false)}>
              Turn off sharing
            </button>
          </div>
          <p className="kd-note kd-tight">
            A new code turns old links off and signs every device out. Turned off, the kit is on this computer only.
          </p>
        </>
      ) : (
        <>
          <p className="kd-lead">
            Phones and laptops on your Wi-Fi can use the kit too: the AI, the library, the map and your notes. No
            internet needed: a router with power, or a phone&apos;s hotspot, is enough.
          </p>
          <button id="kd-share-on" type="button" className="kd-btn" onClick={() => turn(true)}>
            Turn on sharing
          </button>
          <p className="kd-note kd-tight">
            Each phone or laptop needs an 8-digit access code once, and this page then gives you a message with it to
            text them. Anyone on the Wi-Fi with the code can use the kit and read your notes and pins, so share on your
            own Wi-Fi or a phone&apos;s hotspot, not a caf&eacute;&apos;s.
          </p>
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------------------------------------------ help */
function HelpPanel({ go }) {
  const to = (id, text) => (
    <button type="button" className="kd-link" onClick={() => go(id)}>
      {text}
    </button>
  );
  return (
    <>
      <h3 className="kd-h">Using the kit</h3>
      <ul>
        <li>
          On <b>Ask</b>, <b>Ask the AI</b> searches your offline books, then the AI answers and cites them as [1], [2].
          Click a source to read it in full. The AI is slower and uses more power than Search.
        </li>
        <li>
          <b>Search</b>, beside it, skips the AI: the best passages from your books in seconds, on very little power.
          Use it to save battery, or when you&apos;d rather read for yourself. <b>Have the AI answer from these</b> then
          turns what it found into an answer. With the AI off, Ask the AI shows the passages too.
        </li>
        <li>
          <b>Library</b> lets you browse every book: Wikipedia, medical guides, repair manuals and more. Its search
          lists every article with the words you type.
        </li>
        <li>
          <b>Notes</b>, under <b>More</b>, is where you write down what matters to your household: allergies, medicines,
          doctors, where to meet. Ask reads them with every question. They&apos;re saved in the kit&apos;s data folder
          as <b>notes.txt</b>, which updates never touch, and they aren&apos;t encrypted.
        </li>
        <li>
          <b>AI chat</b>, under <b>More</b>, is a plain chat with the AI. It doesn&apos;t search your books or read your
          notes, so check anything important on Ask or in the Library. You can attach photos there, e.g. of a broken
          part or a label. Use a model that reads photos (Inkling, Qwen, Gemma).
        </li>
        <li>
          Pick a different <b>model</b> for a second opinion. <b>Gemma-4-E4B</b> is the small one: use it to save
          battery.
        </li>
        <li>
          The first answer after picking a model is slow while it loads into memory (up to a minute). After that
          it&apos;s quick.
        </li>
        <li>
          <b>{to("print", "Print the essentials")}</b> while there&apos;s power: the few pages of the kit&apos;s books
          worth having on paper, and a page of your own with your notes, your pins and the nearest hospital.
        </li>
        <li>
          <b>{to("share", "Share with family")}</b> lets the phones and laptops on your Wi-Fi use the kit too.
        </li>
        <li>
          The button beside the name says how the kit is: <b>Ready</b>, <b>Starting</b> while the AI loads, or{" "}
          <b>AI off</b>, and <b>Shared</b> while others can use it. Click it for more.
        </li>
      </ul>
      <h3 className="kd-h">Maps and directions</h3>
      <ul>
        <li>
          <b>Map</b> works like a simple Google Maps: search an address or place, get driving or walking directions, or
          find the nearest hospital, pharmacy, gas station and more. Your computer has no GPS, so set <b>home</b>{" "}
          (bottom of the map panel) to where you are.
        </li>
        <li>
          Click anywhere on the map for its coordinates, directions there, or a <b>pin</b> with a note, like where the
          family meets. Pins and home are saved in the kit, and search, directions and Ask find pins by name. The search
          box also takes coordinates, e.g. 40.7128, -74.0060 or 40°42&apos;46&quot;N 74°0&apos;22&quot;W.
        </li>
        <li>
          You can also ask in plain words on the Ask page, e.g. &quot;How do I get to the nearest hospital?&quot; or
          &quot;Directions from home to 350 Fifth Avenue, New York&quot;. The answer appears there and the route on the
          Map tab.
        </li>
        <li>
          For driving, a phone with an offline maps app (Organic Maps, or downloaded areas in Apple or Google Maps) is
          better: it has GPS and spoken turn-by-turn directions.
        </li>
      </ul>
      <h3 className="kd-h">If something doesn&apos;t work</h3>
      <ul>
        <li>
          Close the kit&apos;s Terminal window and double-click <b>Open Tinfoil Kit.command</b> again.
        </li>
        <li>
          Logs are in the kit&apos;s <b>data</b> folder, in <b>logs</b>.
        </li>
        <li>If the AI won&apos;t start, the library still works.</li>
        <li>
          Big models need most of the computer&apos;s memory: quit other apps. If a model still won&apos;t load, use
          Gemma-4-E4B.
        </li>
      </ul>
    </>
  );
}

/* --------------------------------------------------------------------------------------------- the window */
// The kit page's tabs, and the pages its More menu holds (nav and #moreMenu in tools/portal.html). In the kit, AI
// chat opens in a tab of its own; here it's a page that says so.
const TABS = [
  ["ask", "Ask"],
  ["map", "Map"],
  ["library", "Library"],
];
const MORE = [
  ["notes", "Notes"],
  ["share", "Share with family"],
  ["print", "Print the essentials"],
  ["chat", "AI chat ↗"],
  ["help", "Help"],
];
const chevron = (
  <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
    <path
      d="m6 9 6 6 6-6"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
// When SETUP last brought everything up to date: a few days back, drawn only while it shows, so it's the visitor's day
function refreshed() {
  const d = new Date();
  d.setDate(d.getDate() - 3);
  return "Refreshed " + d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export default function Demo() {
  const [page, setPage] = useState("ask");
  const [pop, setPop] = useState(""); // "status" or "more" while its panel is open
  const [shared, setShared] = useState(false);
  const [notes, setNotes] = useState(NOTES);
  const [toMap, setToMap] = useState(null);
  const [toAsk, setToAsk] = useState(null);
  const [toast, setToast] = useState("");
  const timer = useRef(0);
  const statusBtn = useRef(null),
    statusBox = useRef(null),
    moreBtn = useRef(null),
    moreBox = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  // As on the kit page: one open at a time, and a click elsewhere or Escape closes it
  useEffect(() => {
    if (!pop) return;
    const [btn, box] = pop === "more" ? [moreBtn, moreBox] : [statusBtn, statusBox];
    function click(e) {
      if (![statusBtn, statusBox, moreBtn, moreBox].some((r) => r.current.contains(e.target))) setPop("");
    }
    function key(e) {
      if (e.key !== "Escape") return;
      if (box.current.contains(document.activeElement)) btn.current.focus();
      setPop("");
    }
    document.addEventListener("click", click);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("click", click);
      document.removeEventListener("keydown", key);
    };
  }, [pop]);
  function say(text) {
    setToast(text);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(""), 4000);
  }
  function go(id) {
    setPage(id);
    setPop("");
  }
  const show = (id) => ({ id: "kd-" + id, hidden: page !== id });
  const current = (id) => (page === id ? "page" : undefined);

  return (
    <div className="kd" role="region" aria-label="Demo of the Tinfoil Kit page">
      <div className="kd-bar">
        <span className="kd-url">127.0.0.1:8888</span>
        <span className="kd-off">
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            aria-hidden="true"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
          >
            <path d="M2 8.8a15 15 0 0 1 20 0M5.5 12.4a10 10 0 0 1 13 0M9 16a5 5 0 0 1 6 0M3 3l18 18" />
            <circle cx="12" cy="19.5" r="1.2" fill="currentColor" stroke="none" />
          </svg>
          Wi-Fi off
        </span>
      </div>
      <div className="kd-head">
        <span className="kd-brand">
          <img src="/icon.svg" width="30" height="30" alt="" />
          Tinfoil Kit
        </span>
        <div className="kd-statuswrap">
          <button
            ref={statusBtn}
            type="button"
            className="kd-statusbtn"
            aria-expanded={pop === "status"}
            aria-controls="kd-statuspanel"
            aria-label={"Kit status: Ready" + (shared ? ", shared on this network" : "")}
            onClick={() => setPop(pop === "status" ? "" : "status")}
          >
            <span>Ready</span>
            {shared && <span>&middot; Shared</span>}
            {chevron}
          </button>
          <div ref={statusBox} id="kd-statuspanel" className="kd-menu" hidden={pop !== "status"}>
            <span className="kd-pill">Library: on</span>
            <span className="kd-pill">AI: ready</span>
            <span className={"kd-pill" + (shared ? "" : " off")}>
              {shared ? "Shared on this network" : "Not shared"}
            </span>
            {pop === "status" && <span className="kd-stamp">{refreshed()}</span>}
          </div>
        </div>
        <div className="kd-nav" role="group" aria-label="The kit page">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" aria-current={current(id)} onClick={() => go(id)}>
              {label}
            </button>
          ))}
          <button
            ref={moreBtn}
            type="button"
            className={MORE.some(([id]) => id === page) ? "on" : undefined}
            aria-expanded={pop === "more"}
            aria-controls="kd-more"
            onClick={() => setPop(pop === "more" ? "" : "more")}
          >
            More
            {chevron}
          </button>
        </div>
        <div ref={moreBox} id="kd-more" className="kd-menu" hidden={pop !== "more"}>
          {MORE.map(([id, label]) => (
            <button
              key={id}
              type="button"
              aria-current={current(id)}
              onClick={() => {
                go(id);
                moreBtn.current.focus();
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div {...show("ask")} className="kd-page">
        <AskPanel
          notes={notes}
          cmd={toAsk}
          say={say}
          onMap={() => {
            setToMap({});
            go("map");
          }}
        />
      </div>
      <div {...show("map")}>
        <MapPanel cmd={toMap} />
      </div>
      <div {...show("library")} className="kd-page">
        <LibraryPanel say={say} onPrint={() => go("print")} />
      </div>
      <div {...show("notes")} className="kd-page">
        <NotesPanel
          notes={notes}
          setNotes={setNotes}
          onPrint={() => go("print")}
          onAsk={() => {
            setToAsk({ q: QUESTIONS.find((x) => x.notes).q });
            go("ask");
          }}
        />
      </div>
      <div {...show("share")} className="kd-page">
        <SharePanel shared={shared} setShared={setShared} say={say} />
      </div>
      <div {...show("print")} className="kd-page">
        {page === "print" && <PrintPanel notes={notes} say={say} />}
      </div>
      <div {...show("chat")} className="kd-page">
        <ChatPanel />
      </div>
      <div {...show("help")} className="kd-page kd-help">
        <HelpPanel go={go} />
      </div>
      <div className="kd-toast" role="status">
        {toast && <span>{toast}</span>}
      </div>
    </div>
  );
}
