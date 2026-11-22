import Builder, {
  CopySetup,
  Groups,
  Nearby,
  NearbySelect,
  PlaceSelect,
  Preset,
  SetupText,
  ShareBox,
  SizeSelect,
  Total,
  WhereSelect,
  WikiSelect,
} from "@/components/builder";
import { CopyButton, Toast } from "@/components/copy";
import Download, { SetupLink } from "@/components/download";
import Header from "@/components/header";
import Hero from "@/components/hero";
import { AUDIT_PROMPT, INSTALL_PROMPT, OWN_PROMPT } from "@/components/prompts";
import { APP, Footer, JsonLd, pageMetadata, Question, REPO, SITE } from "@/components/site";

// My AI installs it: for people who live in AI tools and would rather their AI set it up. Technical words are fine
// here: LLM, GGUF, ZIM, PMTiles, the programs' own names.
const PAGE = `${SITE}/ai-setup`;
const DESCRIPTION =
  "Paste one prompt into ChatGPT, Claude or a coding agent. It reads llms.txt, asks what you want, and gives you one command that sets up a local LLM on llama.cpp, Kiwix's offline Wikipedia and offline maps. Free and MIT-licensed.";

export const metadata = pageMetadata({
  path: "/ai-setup",
  title: "Install Tinfoil Kit with your AI: offline LLM, Wikipedia, maps",
  description: DESCRIPTION,
});

const STEPS = [
  [
    "Buy an external SSD",
    "A portable USB SSD with room for the kit, from about 20 GB for just the essentials to about 900 GB for everything, formatted exFAT so it starts on a Mac, Windows or Linux. Or use the computer's own disk.",
  ],
  [
    "Have your AI set it up",
    "Paste the prompt into ChatGPT, Claude or a coding agent. It reads llms.txt, checks the computer and the drive, asks what goes in the kit, and gives you one command: a small kit to try first, then the rest.",
  ],
  [
    "Use it on any computer",
    "Plug the drive into any Mac, Windows or Linux computer and open Tinfoil Kit. It all runs locally, with no internet.",
  ],
];

const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "HowTo",
      "@id": `${PAGE}#howto`,
      name: "Install Tinfoil Kit with your AI",
      description: DESCRIPTION,
      url: PAGE,
      about: APP,
      tool: [{ "@type": "HowToTool", name: "An AI chat or coding agent, such as ChatGPT or Claude" }],
      supply: [
        {
          "@type": "HowToSupply",
          name: "An external SSD with room for the kit, from about 20 GB for just the essentials to about 900 GB for everything (optional)",
        },
      ],
      step: STEPS.map(([name, text], i) => ({
        "@type": "HowToStep",
        position: i + 1,
        name,
        text,
        url: `${PAGE}#how`,
      })),
    },
    {
      "@type": "SoftwareSourceCode",
      name: "Tinfoil Kit",
      codeRepository: REPO,
      programmingLanguage: ["Go", "JavaScript", "Shell"],
      license: "https://opensource.org/license/mit",
      runtimePlatform: "macOS on Apple silicon; Windows and Linux on x64 (experimental)",
      targetProduct: APP,
    },
  ],
};

const SECTIONS = [
  ["#how", "How it works"],
  ["#builder", "Build your kit"],
  ["#prompts", "Prompts"],
  ["#stack", "Under the hood"],
  ["#trust", "Security"],
  ["#faq", "Questions"],
];

// What Open Tinfoil Kit starts (README's How it works has the same table)
const SERVERS = [
  [
    "AI",
    "llama-server (llama.cpp)",
    "port 8080",
    "Serves the LLM, one model at a time. AI chat is its built-in chat page.",
  ],
  ["Library", "kiwix-serve", "port 8888", "Serves the ZIM files with full-text search, and the kit page."],
  ["Map", "pmtiles", "port 8090", "Serves vector tiles: street detail for your region, and a low-zoom world."],
  ["Addresses", "Photon", "port 2322", "Geocoding: addresses, places, and the nearest hospital or pharmacy."],
  ["Directions", "GraphHopper", "port 8989", "Driving and walking routes, on a road graph built from OpenStreetMap."],
  ["Notes and pins", "the kit's program", "port 8095", "Keeps the household notes the AI reads, and the map's pins."],
  [
    "Sharing",
    "the kit's program",
    "port 8000",
    "Off by default. One gate for the devices at home, behind an 8-digit code.",
  ],
];

// llms.txt's example, one step to a line so it wraps where a person reads it
const COMMAND = [
  "mkdir -p ~/Downloads && cd ~/Downloads &&",
  "curl -fsSL https://github.com/tudor-city-ventures/tinfoil-kit/releases/latest/download/TinfoilKit.tar.gz | tar -xz &&",
  "bash TinfoilKit/app/SETUP.command --region texas --drive /Volumes/Kit --yes",
].join("\n");

export default function AISetup() {
  return (
    <>
      <JsonLd data={jsonLd} />
      <Header page="/ai-setup" links={SECTIONS} />
      <main id="top">
        <section className="wrap hero">
          <div className="hero-copy">
            <p className="kicker">Free&nbsp;· Open source&nbsp;· MIT</p>
            <h1>
              The internet's down.
              <br /> Your AI isn't.
            </h1>
            <p className="lede">
              Tinfoil Kit is a local LLM with Wikipedia and maps built in, all offline, in one folder on your laptop or
              an external SSD. Paste one prompt into ChatGPT, Claude or your coding agent: it reads the kit's{" "}
              <a href="/llms.txt">llms.txt</a>, checks your computer and drive, asks what you want, and hands you one
              command to run.
            </p>
            <Download lead="ai">
              <a className="star" href={REPO}>
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M12 2.2L14.6 9L21.9 9.4L16.2 14L18.1 21L12 17L5.9 21L7.8 14L2.1 9.4L9.4 9z"
                    fill="currentColor"
                  />
                </svg>
                Star on GitHub
              </a>
            </Download>
          </div>
          <Hero />
        </section>
        <section id="how" className="how">
          <div className="wrap section">
            <div className="head-row">
              <h2>How it works</h2>
              <p className="mono" style={{ fontSize: "14px", color: "var(--ink2)" }}>
                Your AI sets it up. You run one command.
              </p>
            </div>
            <ol className="how-steps">
              <li>
                <b>01 · GET A DRIVE</b>
                <h3>{STEPS[0][0]}</h3>
                <p>
                  A portable USB SSD with room for the kit: from about 20&nbsp;GB for just the essentials to about
                  900&nbsp;GB for everything. Formatted exFAT, the same drive starts on a Mac, Windows or Linux.
                </p>
                <small>No drive? It can go on your computer's own disk instead.</small>
              </li>
              <li>
                <b>02 · TELL YOUR AI</b>
                <h3>{STEPS[1][0]}</h3>
                <p>
                  Paste the prompt into ChatGPT, Claude or a coding agent like Claude Code or Codex. It reads llms.txt,
                  checks your computer and the drive, asks what you want, and gives you one command to run.
                </p>
                <SetupLink>Get the prompt</SetupLink>
                <small>
                  A 10&nbsp;GB kit to try comes first. Once it works, your AI gives you the command for the rest.
                </small>
              </li>
              <li>
                <b>03 · PLUG IN ANYWHERE</b>
                <h3>{STEPS[2][0]}</h3>
                <p>
                  Plug the drive into any Mac, Windows or Linux computer and open Tinfoil Kit. The LLM, the library and
                  the maps run on 127.0.0.1, with no internet.
                </p>
                <small>Windows and Linux are experimental for now.</small>
              </li>
            </ol>
            <div className="example">
              <div className="example-copy">
                <p className="kicker">What it looks like</p>
                <h3>Your AI checks first, then asks.</h3>
                <p>
                  A coding agent reads llms.txt, then looks at your computer and drives with commands that only read:
                  the chip and memory, which decide the model, and the drive's format and free space. It asks only what
                  it can't see, like where you live, and hands you the command. A chat AI that can't reach your computer
                  asks you instead.
                </p>
              </div>
              <figure className="chat">
                <figcaption>Your AI agent</figcaption>
                <ol>
                  <li className="you">
                    <b>You</b>I want to set up Tinfoil Kit… Its instructions for AI assistants are at
                    https://tinfoilkit.com/llms.txt. Read them first.
                  </li>
                  <li>
                    <b>Your AI</b>Read them. I looked at your Mac and its drives, with commands that only read:
                    <dl>
                      <div>
                        <dt>Mac</dt>
                        <dd>MacBook Air, Apple M4, 32&nbsp;GB of memory</dd>
                      </div>
                      <div>
                        <dt>Drive</dt>
                        <dd>Kit, a 1&nbsp;TB external SSD: exFAT, 998&nbsp;GB free</dd>
                      </div>
                    </dl>
                    Your Mac runs the default AI, Inkling 2 Mini, and all of the kit fits on Kit. Where do you live?
                  </li>
                  <li className="you">
                    <b>You</b>Austin, Texas.
                  </li>
                  <li className="gap">Wikipedia, places nearby, what to leave out…</li>
                  <li>
                    <b>Your AI</b>Paste this into Terminal. It gets a small kit to try first; when it works, I'll give
                    you the command for the rest.
                    <code>{COMMAND}</code>
                  </li>
                </ol>
              </figure>
            </div>
          </div>
        </section>
        <section id="builder" className="band">
          <div className="wrap section">
            <Builder>
              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                <p className="kicker">The kit builder</p>
                <h2>Choose what goes in your kit.</h2>
                <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "680px" }}>
                  Pick what goes in and copy the prompt. Your picks ride along as SETUP's flags, like{" "}
                  <code>--essentials --region us/texas</code>, so your AI asks only about the rest.
                </p>
              </div>
              <div className="where">
                <div className="field">
                  <label htmlFor="place">Where do you live?</label>
                  <PlaceSelect />
                </div>
                <div className="field">
                  <label htmlFor="nearby">Places nearby</label>
                  <NearbySelect />
                </div>
                <Nearby />
                <div className="field">
                  <label htmlFor="wikiLang">Wikipedia in</label>
                  <WikiSelect />
                </div>
                <div className="field">
                  <label htmlFor="wikiSize">How much of Wikipedia</label>
                  <SizeSelect />
                </div>
                <p className="hint" id="placeNote">
                  Why we ask: street maps and directions for the whole world would take hundreds of gigabytes, so your
                  kit gets them only for where you live and any places nearby you add, like the state or country next
                  door. Everywhere else gets a simple map. This page doesn't send your answers anywhere: they only go
                  into the command or prompt you copy.
                </p>
              </div>
              <div className="presets" role="group" aria-label="Preset">
                <Preset value="essentials">Essentials</Preset>
                <Preset value="recommended">Recommended</Preset>
                <Preset value="everything">Everything</Preset>
                <Preset value="no-ai">No AI</Preset>
              </div>
              <Groups />
              <div className="where">
                <div className="field">
                  <label htmlFor="where">Where will it live?</label>
                  <WhereSelect />
                </div>
                <div className="field">
                  <ShareBox />
                </div>
                <p className="hint" id="whereNote">
                  An external drive goes with you and works on any computer. A home server is a computer that stays on,
                  so the phones and laptops at home can use the kit through it, with an access code. Leave it unpicked
                  and your AI asks.
                </p>
              </div>
              <div className="total" role="region" aria-label="Your kit">
                <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: "1 1 320px" }}>
                  <Total />
                  <Toast />
                  <SetupText />
                </div>
                <div className="acts">
                  <CopySetup>
                    Copy AI <span className="long">setup </span>prompt
                  </CopySetup>
                </div>
              </div>
            </Builder>
          </div>
        </section>
        <section id="prompts" className="wrap section">
          <h2>Let any AI chat walk you through it.</h2>
          <div className="prompts">
            <div className="prompt">
              <div className="bar">
                <div>
                  <b>Install ours</b>
                  <span>
                    Paste it into ChatGPT, Claude or another AI chat. It asks what you want in it, then gives you the
                    command to run.
                  </span>
                </div>
                <CopyButton target="installPrompt" />
              </div>
              <pre id="installPrompt">{INSTALL_PROMPT}</pre>
            </div>
            <div className="prompt">
              <div className="bar">
                <div>
                  <b>Build your own</b>
                  <span>Our kit as a starting point. Your AI asks what you need first.</span>
                </div>
                <CopyButton target="ownPrompt" />
              </div>
              <pre id="ownPrompt">{OWN_PROMPT}</pre>
            </div>
          </div>
        </section>
        <section id="stack" className="band">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">Under the hood</p>
              <h2>What runs on your computer.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "760px" }}>
                Open Tinfoil Kit starts these servers from the kit's folder, each on 127.0.0.1, and opens the kit page
                in your browser. No Docker, no runtime to install, no admin password: one Go program, standard library
                only, downloads, checks and runs it all, with curl for every download.
              </p>
            </div>
            <ul className="cards" aria-label="The servers">
              {SERVERS.map(([part, program, port, what]) => (
                <li key={part}>
                  <b>{part}</b>
                  <code>
                    {program} · {port}
                  </code>
                  <span>{what}</span>
                </li>
              ))}
            </ul>
            <ul className="cards">
              <li>
                <b>Ask: answers with sources</b>
                <span>
                  The LLM turns your question into short searches, kiwix-serve runs them over every ZIM, and the LLM
                  answers from the top articles with numbered citations. Map questions go to three tools instead: search
                  places, find nearby, get directions. With the AI off, Ask shows the best passages.
                </span>
              </li>
              <li>
                <b>Models: 4-bit GGUF, all with vision</b>
                <span>
                  From Hugging Face: Inkling 2 Mini by default (a mixture of experts, about 3.4B of its 26B parameters
                  active per token), Qwen3.8 27B, and Gemma 4 26B-A4B, 12B and E4B. A model may take 60% of memory, and{" "}
                  <code>./kit fit</code> picks the one this computer runs.
                </span>
              </li>
              <li>
                <b>Library: Kiwix ZIM files</b>
                <span>
                  Straight from Kiwix: Wikipedia in any language, all of it or the best 50,000 articles, with or without
                  pictures, plus WikiMed, iFixit, Stack Exchange, LibreTexts, US Army manuals and more.{" "}
                  <code>./kit search</code> finds any other ZIM.
                </span>
              </li>
              <li>
                <b>Maps: PMTiles, Photon, GraphHopper</b>
                <span>
                  Protomaps' daily OpenStreetMap build, cut to your region and drawn by MapLibre GL; Photon's address
                  database; and a road graph built from Geofabrik's extract on the first sync. Photon and GraphHopper
                  run on a Java 21 inside the kit.
                </span>
              </li>
              <li>
                <b>One folder, three systems</b>
                <span>
                  The kit carries every program for macOS on Apple silicon and for Windows and Linux on x64, so an exFAT
                  drive starts on any of them. On Windows and Linux the LLM runs on the GPU through Vulkan. Both are
                  experimental for now.
                </span>
              </li>
              <li>
                <b>Updates that keep what you have</b>
                <span>
                  <code>./kit sync</code> asks each publisher for the newest edition, downloads only what changed over
                  eight connections per file, resumes, checks checksums, and keeps the old version until the new one
                  checks out. A new release replaces only the app folder.
                </span>
              </li>
            </ul>
          </div>
        </section>
        <section id="trust" className="oss">
          <div className="wrap">
            <div style={{ flex: "1 1 520px", display: "flex", flexDirection: "column", gap: "16px" }}>
              <p className="kicker" style={{ color: "#E0884F" }}>
                Don't trust, verify
              </p>
              <h2>Signed, pinned and rebuildable.</h2>
              <p>
                Every release is signed, every program is pinned to its SHA-256, and the kit's one binary rebuilds to
                the same bytes from source. The README's <a href={`${REPO}#security`}>Security section</a> also says
                what it can't protect against.
              </p>
            </div>
            <pre className="code" tabIndex={0}>
              {`# check a release before you run it
ssh-keygen -Y verify -f tools/release-signers -I tinfoilkit-release \\
  -n tinfoilkit-release -s tinfoilkit-TAG.tar.gz.sig < tinfoilkit-TAG.tar.gz
# rebuild a kit's program from its source, and compare
tools/tinfoilkit/build.sh verify SHA256SUMS`}
            </pre>
            <ul className="facts">
              <li>
                <b>Signed releases</b>
                <span>
                  <code>./kit update</code> installs code only if the maintainer's SSH key signed it, checked against{" "}
                  <code>tools/release-signers</code> in the copy you have. The key never touches GitHub or CI.
                </span>
              </li>
              <li>
                <b>Reproducible builds</b>
                <span>
                  The Go program builds to the same bytes on any computer. CI and the maintainer's Mac both build each
                  release, and it ships only if they match. Its signed <code>SHA256SUMS</code> lists every file.
                </span>
              </li>
              <li>
                <b>Pinned programs</b>
                <span>
                  <code>tools/pins.json</code> names the exact build and SHA-256 of llama.cpp, kiwix-tools, Java,
                  pmtiles, Photon and GraphHopper. Models, ZIMs and map data are checked against their publisher's
                  checksum when there is one.
                </span>
              </li>
              <li>
                <b>Loopback only, no telemetry</b>
                <span>
                  Every server listens on 127.0.0.1, and sharing on your network is off until you turn it on. No
                  account, analytics or phoning home.
                </span>
              </li>
            </ul>
            <div className="prompt">
              <div className="bar">
                <div>
                  <b>Check the code</b>
                  <span>Have your AI audit it first. It reads the code and runs nothing.</span>
                </div>
                <CopyButton target="auditPrompt" />
              </div>
              <pre id="auditPrompt" tabIndex={0}>
                {AUDIT_PROMPT}
              </pre>
            </div>
          </div>
        </section>
        <section id="faq" className="wrap section">
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <p className="kicker">Questions</p>
            <h2>For the technically curious.</h2>
          </div>
          <div className="faq" itemScope itemType="https://schema.org/FAQPage">
            <Question q="Which LLMs does Tinfoil Kit run?">
              Five open-weight models, as 4-bit GGUF files from Hugging Face, each with a vision projector so it reads
              photos: Inkling 2 Mini by default (Thinking Machines, a mixture of experts, 18&nbsp;GB), Qwen3.8 27B
              (dense, 17.5&nbsp;GB), Gemma 4 26B-A4B (15.7&nbsp;GB), Gemma 4 12B (7.2&nbsp;GB) and Gemma 4 E4B
              (5.3&nbsp;GB). 32&nbsp;GB of memory runs the big three, 16 to 24&nbsp;GB the 12B, and 8&nbsp;GB the E4B.{" "}
              <code>./kit fit</code> says which one a computer runs, and SETUP's <code>--models</code> picks others.
            </Question>
            <Question q="Can my agent just install it?">
              It could, but llms.txt asks it not to. Your agent asks the questions and hands you one command, so you see
              exactly what runs and nothing installs behind your back. Every question SETUP asks is also a flag, and{" "}
              <code>--yes</code> asks nothing, so that one command is the whole setup. Updates, fixes and removal work
              the same way.
            </Question>
            <Question q="Does it need Docker, Python or Node?">
              No. The kit's own program is one Go binary, standard library only, and it uses curl for every download,
              which macOS and Windows come with. The servers are native builds of llama.cpp, kiwix-tools and pmtiles,
              plus Photon and GraphHopper on a Java 21 the kit downloads. Everything it downloads stays in the kit's
              folder.
            </Question>
            <Question q="How do I know the binary matches the source?">
              Run <code>tools/tinfoilkit/build.sh verify</code> in a kit's app folder, with Go installed. It rebuilds
              the program from the source beside it and compares the bytes (for the Mac app's copy, everything but
              Apple's signature). Add the release's signed <code>SHA256SUMS</code> to compare with that too. Releases
              ship only when CI's build and the maintainer's match.
            </Question>
            <Question q="What does it send over the network?">
              Nothing, once it's set up. Setup, sync and update talk only to GitHub, for the kit's own releases, and to
              the publishers: Hugging Face, Kiwix, Protomaps, Geofabrik, GraphHopper, Adoptium, Maven Central and npm.
              There are no accounts, analytics or telemetry, in the kit or on this site.
            </Question>
            <Question q="Can I add my own ZIMs or models?">
              Yes. Everything the kit keeps is listed in <code>data/kit.json</code>, with each publisher's download, and
              a new version merges its changes in without touching yours. <code>./kit search WORDS</code> finds any
              Kiwix ZIM and prints the line to paste, and models are Hugging Face GGUF repos, listed the same way.{" "}
              <code>./kit plan</code> previews, and <code>./kit sync</code> downloads.
            </Question>
            <Question q="How does one drive run on a Mac, Windows and Linux?">
              The kit downloads every program for all three, macOS on Apple silicon and Windows and Linux on x64, and
              the data is the same files on each. It uses no symlinks, since exFAT has none. Windows and Linux are
              experimental for now: the Mac gets the most testing on real hardware.
            </Question>
            <Question q="Can I run it as a home server?">
              Yes, though it's experimental for now. <code>SETUP --home-server</code> shares the kit on your network and
              starts it with the computer: a Linux box, a Mac mini, or a laptop on its charger. The servers stay on
              127.0.0.1 behind one gate, which asks for an 8-digit access code and stops answering a device after 10
              wrong tries. It's plain HTTP, so share it on your own Wi-Fi or hotspot.
            </Question>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
