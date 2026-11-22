"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

// Read as: the human page, or the agent page (llms.txt as markdown). The script in the layout's <head> sets
// data-reader on <html> before the page draws, and the CSS shows each page's parts from it. This keeps it, the
// address and the last pick in step.
const listeners = new Set();
const subscribe = (l) => (listeners.add(l), () => listeners.delete(l));
const current = () => document.documentElement.getAttribute("data-reader") || "human";

function useReader() {
  return useSyncExternalStore(subscribe, current, () => "human");
}

function pick(reader) {
  const root = document.documentElement;
  const url = new URL(location.href);
  if (reader === "agent") root.setAttribute("data-reader", reader);
  else root.removeAttribute("data-reader");
  try {
    localStorage.setItem("reader", reader);
  } catch {}
  if (reader === "agent") url.searchParams.set("for", reader);
  else url.searchParams.delete("for");
  history.replaceState(null, "", url);
  listeners.forEach((l) => l());
}

export default function ReadAs() {
  const reader = useReader();
  return (
    <section className="readas" aria-labelledby="readas-label">
      <div className="wrap">
        <span id="readas-label">Read as</span>
        <div className="seg">
          <button type="button" data-reader="human" aria-pressed={reader === "human"} onClick={() => pick("human")}>
            Human
          </button>
          <button type="button" data-reader="agent" aria-pressed={reader === "agent"} onClick={() => pick("agent")}>
            AI agent
          </button>
        </div>
      </div>
    </section>
  );
}

// llms.txt is the one copy of the agent instructions; this shows it, headings in bold so the raw markdown scans.
// Until then, and for crawlers, it shows its children.
export function AgentDoc({ children }) {
  const wanted = useReader() === "agent";
  const [lines, setLines] = useState(null);
  useEffect(() => {
    if (!wanted || lines) return;
    let live = true;
    fetch("/llms.txt")
      .then((r) => {
        if (!r.ok) throw r;
        return r.text();
      })
      .then(
        (text) => live && setLines(text.replace(/\n$/, "").split("\n")),
        () => {},
      );
    return () => {
      live = false;
    };
  }, [wanted, lines]);
  return (
    <pre className="doc" id="agentDoc">
      {lines
        ? lines.map((line, i) =>
            line.charAt(0) === "#" ? <b key={i}>{line + "\n"}</b> : <span key={i}>{line + "\n"}</span>,
          )
        : children}
    </pre>
  );
}
