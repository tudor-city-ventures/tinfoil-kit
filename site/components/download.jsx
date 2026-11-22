"use client";

import { useEffect, useRef, useState } from "react";
import { copyText, selectNode } from "@/components/copy";
import { INSTALL_PROMPT } from "@/components/prompts";

// The downloads are coming soon: the Mac's waits for Apple to sign and notarize the Mac app (docs/RELEASING.md). Until
// then they show, marked coming soon, and setup is the command an AI gives: it downloads the same kit with curl, so
// neither macOS nor Windows marks it as downloaded from the internet and stops it.
const DOWNLOADS = [
  { os: "mac", name: "Mac", detail: "Apple silicon (M1 or newer)", shell: "Terminal" },
  {
    os: "windows",
    name: "Windows",
    detail: "Windows 10 or 11, Intel or AMD (x64)",
    shell: "PowerShell",
    experimental: true,
  },
  {
    os: "linux",
    name: "Linux",
    detail: "Ubuntu, Debian, Fedora, Arch and others, Intel or AMD (x64)",
    shell: "a terminal",
    experimental: true,
  },
];

function detectOS() {
  const ua = navigator.userAgent; // iPads ask for the desktop site as a Mac, but have a touch screen
  if (/iPhone|iPad|iPod|Android/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "phone";
  if (/Windows/.test(ua)) return "windows";
  if (/Macintosh/.test(ua)) return "mac";
  if (/Linux|X11/.test(ua) && !/CrOS/.test(ua)) return "linux";
  return "";
}

// Set up with your AI opens a dialog with the setup prompt to copy into any AI chat. Before the script runs, it goes to
// the prompts further down the page. onClick runs first, as when the downloads dialog closes to make way.
let openSetup = null;
export function SetupLink({ onClick, ...props }) {
  return (
    <a
      {...props}
      href="#prompts"
      aria-haspopup="dialog"
      onClick={(e) => {
        if (onClick) onClick(e);
        if (openSetup) openSetup(e);
      }}
    />
  );
}

function SetupDialog({ phone }) {
  const dialog = useRef(null);
  const [label, setLabel] = useState("Copy prompt");
  const reset = useRef(0);
  useEffect(() => () => clearTimeout(reset.current), []);
  function open(e) {
    if (!dialog.current.showModal) return;
    e.preventDefault();
    setLabel("Copy prompt");
    dialog.current.showModal();
  }
  function copy() {
    const node = document.getElementById("heroPrompt");
    copyText(INSTALL_PROMPT).then(
      () => setLabel("Copied"),
      () => {
        // leave it selected, so Cmd-C copies it
        selectNode(node);
        setLabel(/Mac|iPhone|iPad/.test(navigator.userAgent) ? "Press Cmd-C" : "Press Ctrl-C");
      },
    );
    clearTimeout(reset.current);
    reset.current = setTimeout(() => setLabel("Copy prompt"), 4000);
  }
  const close = () => dialog.current.close();
  useEffect(() => {
    openSetup = open;
    return () => {
      openSetup = null;
    };
  });
  return (
    <dialog
      id="aiSetup"
      className="dl"
      aria-labelledby="aiTitle"
      ref={dialog}
      onClick={(e) => e.target === dialog.current && close()}
    >
      <div className="dl-box">
        <div className="dl-head">
          <h2 id="aiTitle">Set up with your AI</h2>
          <button type="button" className="dl-x" aria-label="Close" onClick={close}>
            <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2.5" />
            </svg>
          </button>
        </div>
        <div className="dl-body">
          <p className="dl-phone" hidden={!phone}>
            Tinfoil Kit runs on a laptop or desktop, so do this on that computer.
          </p>
          <p>Your AI asks what you want in your kit, then gives you the command to run.</p>
          <ol className="dl-steps">
            <li>
              <span className="dl-row">
                Copy this prompt.{" "}
                <button type="button" className="btn primary" id="copyHero" onClick={copy}>
                  {label}
                </button>
              </span>
              <pre className="dl-prompt" id="heroPrompt" tabIndex={0}>
                {INSTALL_PROMPT}
              </pre>
            </li>
            <li>Paste it into ChatGPT, Claude or any AI chat, and send it.</li>
            <li>Answer its questions. It gives you a command to paste into your terminal, and tells you how.</li>
          </ol>
          <p className="dl-fine">
            Want to choose what goes in first? Use the{" "}
            <a href="#builder" onClick={close}>
              kit builder
            </a>
            . Want to check the code before you run it?{" "}
            <a href="#trust" onClick={close}>
              Have your AI read it
            </a>
            .
          </p>
        </div>
      </div>
    </dialog>
  );
}

// The hero's way in, Set up with your AI, then "or" and this computer's download, which is coming soon. All downloads
// lists the three, each coming soon, with the way in that works now. The children are the hero's other links.
export default function Download({ children }) {
  const dialog = useRef(null);
  const [os, setOS] = useState("");
  useEffect(() => {
    if (dialog.current.showModal) setOS(detectOS()); // the user agent is only known here, after the server's HTML
  }, []);
  const mine = DOWNLOADS.find((d) => d.os === os);
  const list = mine ? [mine, ...DOWNLOADS.filter((d) => d !== mine)] : DOWNLOADS;
  const close = () => dialog.current.close();
  function showAll() {
    if (!dialog.current.showModal) return;
    dialog.current.showModal();
    dialog.current.querySelector(".dl-box").scrollTop = 0;
  }
  return (
    <>
      <div className="ctas">
        <SetupLink className="btn primary" id="askAI">
          Set up with your AI
        </SetupLink>
        <span className="or">or</span>
        <button type="button" className="btn" id="getKit" disabled>
          {mine ? `Download for ${mine.name}` : "Download"} <em className="soon">Coming soon</em>
        </button>
        {children}
      </div>
      <p className="cta-note">
        <span id="getFor">
          Paste one prompt into ChatGPT, Claude or any AI chat. It asks what you want, then gives you one command to
          paste into {mine ? mine.shell : "your terminal"}.
          {mine && mine.experimental ? ` On ${mine.name}, the kit is experimental for now.` : ""}
        </span>{" "}
        <button type="button" className="all-dl" id="allDl" aria-haspopup="dialog" onClick={showAll}>
          All downloads
        </button>
      </p>
      <SetupDialog phone={os === "phone"} />
      <dialog
        id="downloads"
        className="dl"
        aria-labelledby="dlTitle"
        ref={dialog}
        onClick={(e) => e.target === dialog.current && close()}
      >
        <div className="dl-box">
          <div className="dl-head">
            <h2 id="dlTitle">Download Tinfoil Kit</h2>
            <button type="button" className="dl-x" aria-label="Close" onClick={close}>
              <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2.5" />
              </svg>
            </button>
          </div>
          <div className="dl-body">
            <p className="dl-phone" hidden={os !== "phone"}>
              Tinfoil Kit runs on a laptop or desktop, not on a phone or tablet. Open this page on your computer to set
              it up.
            </p>
            <p>
              Downloads you double-click are coming soon. Until then, your AI sets the kit up with one command, on all
              three.
            </p>
            <ul className="dl-list">
              {list.map((d) => (
                <li key={d.os} data-os={d.os} className={d === mine ? "mine" : undefined}>
                  <div>
                    <b>
                      {d.name}
                      {d.experimental ? <em className="exp">Experimental</em> : null}
                    </b>
                    <span>{d.detail}</span>
                  </div>
                  <em className="soon">Coming soon</em>
                </li>
              ))}
            </ul>
            <SetupLink className="btn primary dl-ai" onClick={close}>
              Set up with your AI
            </SetupLink>
            <p className="dl-fine">
              It's the same kit on all three, and a kit on an exFAT drive starts on any of them. Windows and Linux are
              experimental for now: they're tested less than the Mac, so expect rough edges.
            </p>
          </div>
        </div>
      </dialog>
    </>
  );
}
