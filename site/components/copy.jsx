"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";

// The clipboard API needs https and a focused page; the old copy command covers the rest.
export function copyText(text) {
  function legacy() {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {}
    ta.remove();
    return ok ? Promise.resolve() : Promise.reject();
  }
  return navigator.clipboard ? navigator.clipboard.writeText(text).catch(legacy) : legacy();
}

export function selectNode(node) {
  const range = document.createRange();
  range.selectNodeContents(node);
  getSelection().removeAllRanges();
  getSelection().addRange(range);
}

// One line of feedback in the kit builder's bar, for every copy button on the page.
let message = "";
let timer = 0;
const listeners = new Set();
const subscribe = (l) => (listeners.add(l), () => listeners.delete(l));
function say(text) {
  message = text;
  listeners.forEach((l) => l());
}

export function toast(text, ms = 3000) {
  say(text);
  clearTimeout(timer);
  timer = setTimeout(() => say(""), ms);
}

export function Toast() {
  const text = useSyncExternalStore(
    subscribe,
    () => message,
    () => "",
  );
  return (
    <div className="toast" id="toast" aria-live="polite">
      {text}
    </div>
  );
}

// Copies the text of the element with the id `target`.
export function CopyButton({ target }) {
  const [label, setLabel] = useState("Copy");
  const reset = useRef(0);
  useEffect(() => () => clearTimeout(reset.current), []);
  function show(text, ms) {
    setLabel(text);
    clearTimeout(reset.current);
    reset.current = setTimeout(() => setLabel("Copy"), ms);
  }
  function copy() {
    const node = document.getElementById(target);
    copyText(node.textContent).then(
      () => show("Copied", 2000),
      () => {
        // leave it selected, so Cmd-C copies it
        selectNode(node);
        show("Press Cmd-C", 4000);
        toast("Selected. Press Cmd-C (Ctrl-C on Windows) to copy.");
      },
    );
  }
  return (
    <button type="button" data-copy={target} onClick={copy}>
      {label}
    </button>
  );
}
