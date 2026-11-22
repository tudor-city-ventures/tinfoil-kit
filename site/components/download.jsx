'use client';

import { useEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';

const RELEASES = 'https://github.com/tudor-city-ventures/tinfoil-kit/releases';
const DOWNLOADS = [
  { os: 'mac', name: 'Mac', detail: 'Apple silicon (M1 or newer)', note: 'For Macs with Apple silicon (M1 or newer).', file: 'TinfoilKit-Mac.zip' },
  { os: 'windows', name: 'Windows', detail: 'Windows 10 or 11, Intel or AMD (x64)', note: 'For Windows 10 or 11 PCs with Intel or AMD chips.', file: 'TinfoilKit-Windows.zip' },
  { os: 'linux', name: 'Linux', detail: 'Ubuntu, Debian, Fedora, Arch and others, Intel or AMD (x64)', note: 'For Linux PCs with Intel or AMD chips.', file: 'TinfoilKit.tar.gz' },
];

function detectOS() {
  const ua = navigator.userAgent;   // iPads ask for the desktop site as a Mac, but have a touch screen
  if (/iPhone|iPad|iPod|Android/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return 'phone';
  if (/Windows/.test(ua)) return 'windows';
  if (/Macintosh/.test(ua)) return 'mac';
  if (/Linux|X11/.test(ua) && !/CrOS/.test(ua)) return 'linux';
  return '';
}

// Download: the hero button gets this computer's file, All downloads lists them all, and once a download starts the
// dialog says what to click next. Before the script runs, the button opens the release page, which lists every file.
// The children are the hero's other links, beside the button.
export default function Download({ children }) {
  const dialog = useRef(null);
  const [os, setOS] = useState('');
  const [view, setView] = useState('all');
  useEffect(() => {
    if (dialog.current.showModal) setOS(detectOS());   // the user agent is only known here, after the server's HTML
  }, []);
  const mine = DOWNLOADS.find((d) => d.os === os);
  const list = mine ? [mine, ...DOWNLOADS.filter((d) => d !== mine)] : DOWNLOADS;

  function show(next) {
    if (!dialog.current.showModal) return;
    flushSync(() => setView(next));
    if (!dialog.current.open) dialog.current.showModal();
    dialog.current.querySelector('.dl-box').scrollTop = 0;
  }
  function get(e) {
    if (mine) return show(mine.os);   // the download starts, and the dialog says what to click
    if (!dialog.current.showModal) return;   // the release page lists every file
    e.preventDefault();
    show('all');
  }

  return (
    <>
      <div className="ctas">
        <a className="btn primary" id="getKit" href={mine ? `${RELEASES}/latest/download/${mine.file}` : `${RELEASES}/latest`} onClick={get}>{mine ? `Download for ${mine.name}` : 'Download free'}</a>
        {children}
      </div>
      <p className="cta-note"><span id="getFor">{mine ? mine.note : 'For Mac, Windows and Linux.'}</span> <button type="button" className="all-dl" id="allDl" aria-haspopup="dialog" onClick={() => show('all')}>All downloads</button></p>
      <dialog id="downloads" className="dl" aria-labelledby="dlTitle" ref={dialog} onClick={(e) => e.target === dialog.current && dialog.current.close()}>
        <div className="dl-box">
          <div className="dl-head">
            <h2 id="dlTitle">Download Tinfoil Kit</h2>
            <button type="button" className="dl-x" aria-label="Close" onClick={() => dialog.current.close()}><svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2.5" /></svg></button>
          </div>
          <div data-view="all" hidden={view !== 'all'}>
            <p className="dl-phone" hidden={os !== 'phone'}>Tinfoil Kit runs on a laptop or desktop, not on a phone or tablet. Open this page on your computer to download it.</p>
            <ul className="dl-list">
              {list.map((d) => (
                <li key={d.os} data-os={d.os} className={d === mine ? 'mine' : undefined}>
                  <div><b>{d.name}</b><span>{d.detail}</span></div>
                  <a className="btn" data-get={d.os} href={`${RELEASES}/latest/download/${d.file}`} onClick={() => show(d.os)}>Download for {d.name}</a>
                </li>
              ))}
            </ul>
            <p className="dl-fine">It's the same kit on all three, and a kit on an exFAT drive starts on any of them. Intel Macs can't run it. Every version, and the source code: <a href={RELEASES}>GitHub releases</a>.</p>
          </div>
          <div data-view="mac" hidden={view !== 'mac'}>
            <p>Your download has started. Here's what to click.</p>
            <ol className="dl-steps">
              <li>Open your Downloads folder. Safari unzips the download into the <b>Tinfoil Kit</b> app by itself. In another browser, double-click <b>TinfoilKit-Mac.zip</b> first.</li>
              <li>
                Double-click <b>Tinfoil Kit</b>. Your Mac asks whether to open an app from the internet: click <b>Open</b>.
                <div className="mock mac-alert" aria-hidden="true"><img src="/icon.svg" width="32" height="32" alt="" /><b>“Tinfoil Kit” is an app downloaded from the Internet. Are you sure you want to open it?</b><span>Apple checked it for malicious software and none was detected.</span><span className="mbtn">Cancel</span><span className="mbtn hit">Open</span></div>
              </li>
              <li>It offers to move itself to your Applications folder, where you'll look for it in an outage: click <b>Move to Applications</b>. Then click <b>Set Up</b>.</li>
            </ol>
            <p>Setup runs in a Terminal window. It asks where you live, and whether the kit goes on this Mac or an external drive, with what fits on each. If your Mac asks whether Terminal may use files on a removable volume, click Allow. Then it downloads a small sample to try, about 8&nbsp;GB, and offers to open it. Its last message says how big the rest is, how long it will take on your connection, and how to get it: click <b>Update</b> in the app. In an outage, open Tinfoil Kit from Applications.</p>
            <button type="button" className="dl-back" onClick={() => show('all')}>All downloads</button>
          </div>
          <div data-view="windows" hidden={view !== 'windows'}>
            <p>Your download has started. Here's what to click.</p>
            <ol className="dl-steps">
              <li>In your Downloads folder, right-click <b>TinfoilKit-Windows</b>, choose <b>Extract All</b>, then <b>Extract</b>.</li>
              <li>In the new TinfoilKit folder, double-click <b>SETUP-Windows</b>.</li>
              <li>If Windows says it protected your PC, click <b>More info</b>, then <b>Run anyway</b>. It only asks once.</li>
            </ol>
            <p>SETUP then gets the Python the kit's tools run on (about 15&nbsp;MB), and asks where you live and whether the kit goes on this PC or an external drive, with what fits on each. Then it downloads a small sample to try, about 8&nbsp;GB, and offers to open it. Its last message says how big the rest is, how long it will take on your connection, and how to get it: double-click SETUP-Windows again.</p>
            <button type="button" className="dl-back" onClick={() => show('all')}>All downloads</button>
          </div>
          <div data-view="linux" hidden={view !== 'linux'}>
            <p>Your download has started. In a terminal, install python3 and curl if they're missing:</p>
            <ul className="dl-distros">
              <li><span>Ubuntu, Debian, Mint</span><code>sudo apt install python3 curl</code></li>
              <li><span>Fedora</span><code>sudo dnf install python3 curl openssl3-libs</code></li>
              <li><span>Arch, Manjaro</span><code>sudo pacman -S python curl</code></li>
            </ul>
            <p>Then unpack the kit and start SETUP:</p>
            <pre className="dl-cmd">{'cd ~/Downloads && tar -xf TinfoilKit.tar.gz && bash TinfoilKit/SETUP.command'}</pre>
            <p>It asks where you live, and whether the kit goes on this computer or an external drive, with what fits on each. Then it downloads a small sample to try, about 8&nbsp;GB, and offers to open it. Its last message says how big the rest is, how long it will take on your connection, and how to get it.</p>
            <button type="button" className="dl-back" onClick={() => show('all')}>All downloads</button>
          </div>
        </div>
      </dialog>
    </>
  );
}
