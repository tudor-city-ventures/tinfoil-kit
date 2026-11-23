"use client";

import { useEffect, useRef, useState } from "react";
import { copyText, selectNode } from "@/components/copy";
import { INSTALL_PROMPT } from "@/components/prompts";

// Where each computer pastes the command the AI gives. Windows and Linux are experimental until they've had the Mac's
// testing on real computers.
const COMPUTERS = {
  mac: { name: "Mac", shell: "Terminal" },
  windows: { name: "Windows", shell: "PowerShell", experimental: true },
  linux: { name: "Linux", shell: "a terminal", experimental: true },
};

function detectOS() {
  const ua = navigator.userAgent; // iPads ask for the desktop site as a Mac, but have a touch screen
  if (/iPhone|iPad|iPod|Android/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "phone";
  if (/Windows/.test(ua)) return "windows";
  if (/Macintosh/.test(ua)) return "mac";
  if (/Linux|X11/.test(ua) && !/CrOS/.test(ua)) return "linux";
  return "";
}

// Set up with your AI opens a dialog with the setup prompt to copy into any AI chat. Before the script runs, it goes to
// the prompts further down the page.
let openSetup = null;
export function SetupLink(props) {
  return <a {...props} href="#prompts" aria-haspopup="dialog" onClick={(e) => openSetup && openSetup(e)} />;
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

// The hero's way in: Set up with your AI, the hero's other links (the children), and where the AI's command goes on
// this computer. The site offers no download until the Mac app can be signed (docs/RELEASING.md).
export default function Setup({ children }) {
  const [os, setOS] = useState(null); // the user agent is only known here, after the server's HTML
  useEffect(() => {
    setOS(detectOS());
  }, []);
  const mine = COMPUTERS[os];
  return (
    <>
      <div className="ctas">
        <SetupLink className="btn primary" id="askAI">
          Set up with your AI
        </SetupLink>
        {children}
      </div>
      <p className="cta-note" id="getFor" data-os={os ?? undefined}>
        Paste one prompt into ChatGPT, Claude or any AI chat. It asks what you want, then gives you one command to paste
        into {mine ? mine.shell : "your terminal"}.
        {mine && mine.experimental ? ` On ${mine.name}, the kit is experimental for now.` : ""}
      </p>
      <SetupDialog phone={os === "phone"} />
    </>
  );
}
