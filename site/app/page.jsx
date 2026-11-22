import Builder, { CopySetup, Groups, PlaceSelect, Preset, SetupText, SizeSelect, Total, WikiSelect } from '@/components/builder';
import { CopyButton, Toast } from '@/components/copy';
import Demo from '@/components/demo';
import Download, { DownloadLink, SetupLink } from '@/components/download';
import Header from '@/components/header';
import Hero from '@/components/hero';
import { AUDIT_PROMPT, INSTALL_PROMPT, OWN_PROMPT } from '@/components/prompts';
import ReadAs, { AgentDoc } from '@/components/read-as';

export const metadata = {
  title: "Tinfoil Kit: the internet's down, your AI isn't",
  description: "A free, open-source kit that keeps an AI, all of Wikipedia, medical and repair guides, and maps with directions on an external drive or your laptop. No internet needed.",
  alternates: {
    canonical: "https://tinfoilkit.com/",
    types: {
      "text/markdown": [
        {
          url: "/llms.txt",
          title: "Setup instructions for AI agents",
        },
      ],
    },
  },
  openGraph: {
    title: "Tinfoil Kit",
    description: "The internet's down. Your AI isn't. An AI, Wikipedia, medical guides and maps on one drive or your laptop. Free and open source.",
    type: "website",
    url: "https://tinfoilkit.com/",
    images: [
      {
        url: "https://tinfoilkit.com/og.png",
        width: 1200,
        height: 630,
        alt: "Tinfoil Kit. The internet's down. Your AI isn't. Beside it, the logo: a globe wearing a tinfoil hat.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
  },
};

// What search engines and AI answer engines read about the kit. Keep its facts in step with the copy.
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      name: "Tinfoil Kit",
      url: "https://tinfoilkit.com/",
    },
    {
      "@type": "SoftwareApplication",
      name: "Tinfoil Kit",
      url: "https://tinfoilkit.com/",
      description: "A free, open-source kit that keeps an AI, all of Wikipedia, medical and repair guides, and maps with directions on an external drive or your laptop. No internet needed.",
      applicationCategory: "UtilitiesApplication",
      operatingSystem: "macOS, Windows, Linux",
      softwareRequirements: "A Mac with an M chip (M1 or newer), or a Windows 10 or 11 or Linux PC with an Intel or AMD chip. The kit goes on the computer's own disk or an external SSD, and on a drive formatted exFAT it starts on all three.",
      memoryRequirements: "32 GB or more runs the default AI, Inkling 2 Mini; 16 to 24 GB runs Gemma 4 12B; 8 GB runs Gemma 4 E4B",
      storageRequirements: "About 300 GB for the recommended kit, or 35 to 55 GB for just the essentials",
      featureList: [
        "Plain-word answers from the offline library, with numbered sources you can open",
        "An AI chat that runs on your laptop and can read photos",
        "Library: all of Wikipedia with pictures, the WikiMed medical encyclopedia, Army field and medical manuals, iFixit repair guides and FEMA emergency guides",
        "Map: address search, driving and walking directions, and the nearest hospital or pharmacy",
        "The AI is optional: the library and the map work without it",
        "Works with no internet, no account and no telemetry",
      ],
      isAccessibleForFree: true,
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
      },
      license: "https://opensource.org/license/mit",
      downloadUrl: "https://github.com/tudor-city-ventures/tinfoil-kit/releases/latest",
      sameAs: "https://github.com/tudor-city-ventures/tinfoil-kit",
      image: "https://tinfoilkit.com/og.png",
    },
  ],
};

export default function Home() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, '\\u003c') }} />
      <ReadAs />
      <Header />
      <main id="top">
        <section className="wrap hero" data-for="human">
          <div className="hero-copy">
            <p className="kicker">Free&nbsp;· Open source</p>
            <h1>The internet's down.<br /> Your AI isn't.</h1>
            <p className="lede">An opinionated, easy-to-install local AI with the world's knowledge built in. Ask anything, look up first aid, fix a leak, find the nearest hospital.</p>
            <Download>
              <a className="star" href="https://github.com/tudor-city-ventures/tinfoil-kit"><svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.2L14.6 9L21.9 9.4L16.2 14L18.1 21L12 17L5.9 21L7.8 14L2.1 9.4L9.4 9z" fill="currentColor" /></svg>Star on GitHub</a>
            </Download>
          </div>
          <Hero label={"A dotted globe spins up and streams into a drive until the drive holds the whole kit. Then the Wi-Fi goes off, the globe goes dark, and the drive lights up what it holds: Wikipedia, AI models, maps and guides."} />
        </section>
        <section id="instructions" className="wrap agent" data-for="agent">
          <p className="kicker">For AI agents&nbsp;· Markdown at /llms.txt</p>
          <h1>Your agent can set this&nbsp;up.</h1>
          <p className="lede">Point ChatGPT, Claude or any other AI at <a href="/llms.txt">tinfoilkit.com/llms.txt</a>, or paste in the markdown below. It asks what you want, then gives you the command to run.</p>
          <div className="prompt">
            <div className="bar">
              <div>
                <b>llms.txt</b>
                <span>How it works, setup, updates, fixes and sources, in markdown.</span>
              </div>
              <CopyButton target="agentDoc" />
            </div>
            <AgentDoc>The setup instructions for AI agents are at https://tinfoilkit.com/llms.txt</AgentDoc>
          </div>
        </section>
        <section id="how" className="how" data-for="human">
          <div className="wrap section">
            <div className="head-row">
              <h2>How it works</h2>
              <p className="mono" style={{ fontSize: "14px", color: "var(--ink2)" }}>Set it up once. Use it on any computer.</p>
            </div>
            <ol className="how-steps">
              <li>
                <b>01 · GET A DRIVE</b>
                <h3>Buy an external SSD</h3>
                <p>A portable USB drive with room for the kit, about 300&nbsp;GB. Everything goes on it.</p>
                <small>No drive? It can go straight on your Mac, Windows or Linux computer instead.</small>
              </li>
              <li>
                <b>02 · TELL YOUR AI</b>
                <h3>Have your AI set it up</h3>
                <p>Paste our prompt into ChatGPT, Claude or any AI chat. It asks what you want, then tells you what to run to put Tinfoil Kit on the drive.</p>
                <SetupLink>Get the prompt</SetupLink>
                <small>Rather not use an AI? <DownloadLink>Download the installer</DownloadLink> instead. It asks you the same questions.</small>
              </li>
              <li>
                <b>03 · PLUG IN ANYWHERE</b>
                <h3>Use it on any computer</h3>
                <p>Plug the drive into any Mac, Windows or Linux computer and open Tinfoil Kit. The AI, the library and the maps work with no internet.</p>
              </li>
            </ol>
          </div>
        </section>
        <section id="demo" className="band" data-for="human">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">Try it</p>
              <h2>See what you get.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "720px" }}>Tinfoil Kit opens in your browser like a website, but it all runs on your laptop, with no internet. Ask a sample question, plan a route or browse the library. The demo's answers were written ahead of time.</p>
            </div>
            <Demo />
          </div>
        </section>
        <section id="builder" className="wrap section" data-for="human">
          <Builder>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">The kit builder</p>
              <h2>Choose what goes in your kit.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "680px" }}>Pick what goes in, copy the prompt and paste it into any AI chat. It asks what else it needs, then gives you the command to run. Or skip this: the installer asks you the same questions.</p>
            </div>
            <div className="where">
              <div className="field">
                <label htmlFor="place">Where do you live?</label>
                <PlaceSelect />
              </div>
              <div className="field">
                <label htmlFor="wikiLang">Wikipedia in</label>
                <WikiSelect />
              </div>
              <div className="field">
                <label htmlFor="wikiSize">How much of Wikipedia</label>
                <SizeSelect />
              </div>
              <p className="hint" id="placeNote" aria-live="polite">Sets your map, and offers Wikipedia in your language, in the size you want.</p>
            </div>
            <div className="presets" role="group" aria-label="Preset">
              <Preset value="essentials">Essentials</Preset>
              <Preset value="recommended">Recommended</Preset>
              <Preset value="everything">Everything</Preset>
              <Preset value="no-ai">No AI</Preset>
            </div>
            <Groups />
            <div className="total" role="region" aria-label="Your kit">
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", flex: "1 1 320px" }}>
                <Total />
                <Toast />
                <SetupText />
              </div>
              <div className="acts">
                <CopySetup>Copy AI <span className="long">setup </span>prompt</CopySetup>
              </div>
            </div>
          </Builder>
        </section>
        <section id="prompts" className="band" data-for="human">
          <div className="wrap section">
            <h2>Let any AI chat walk you through it.</h2>
            <div className="prompts">
              <div className="prompt">
                <div className="bar">
                  <div>
                    <b>Install ours</b>
                    <span>Paste it into ChatGPT, Claude or another AI chat. It asks what you want in it, then gives you the command to run.</span>
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
          </div>
        </section>
        <section id="trust" className="oss" data-for="human">
          <div className="wrap">
            <div style={{ flex: "1 1 520px", display: "flex", flexDirection: "column", gap: "16px" }}>
              <p className="kicker" style={{ color: "#E0884F" }}>Open source, MIT license</p>
              <h2>Don't trust us? Good. Have your AI audit the code.</h2>
              <p>Before you install anything, paste this into ChatGPT, Claude or any AI chat. It reads the code and tells you what the kit does, without running it.</p>
            </div>
            <a className="btn primary" style={{ minHeight: "60px", fontSize: "19px", padding: "0 28px", borderColor: "var(--signal)" }} href="https://github.com/tudor-city-ventures/tinfoil-kit"><svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.9a3.4 3.4 0 0 0-.9-2.6c3.1-.3 6.4-1.5 6.4-7a5.4 5.4 0 0 0-1.5-3.7 5 5 0 0 0-.1-3.8s-1.2-.3-3.9 1.5a13.4 13.4 0 0 0-7 0C6.3 1.7 5.1 2 5.1 2a5 5 0 0 0-.1 3.8A5.4 5.4 0 0 0 3.5 9.5c0 5.4 3.3 6.6 6.4 7a3.4 3.4 0 0 0-.9 2.6V22" /></svg> View the code on GitHub</a>
            <div className="prompt">
              <div className="bar">
                <div>
                  <b>Check the code</b>
                  <span>Your AI reads it and reports back. Nothing gets installed.</span>
                </div>
                <CopyButton target="auditPrompt" />
              </div>
              <pre id="auditPrompt" tabIndex={0}>{AUDIT_PROMPT}</pre>
            </div>
            <ul className="facts">
              <li><b>Every line is public</b><span>The kit's code and this website's are on GitHub. The README's <a href="https://github.com/tudor-city-ventures/tinfoil-kit#security">Security section</a> says what it protects against, and what it can't.</span></li>
              <li><b>Nothing leaves your laptop</b><span>No account, no tracking. It goes online only to set up or update, and then only to the publishers it downloads from.</span></li>
              <li><b>Every download is checked</b><span>Each program is pinned to an exact build and its checksum. The kit updates itself only from releases signed with the maintainer's key.</span></li>
              <li><b>Only you can reach it</b><span>It runs on your computer and answers only you. Sharing with your home network stays off until you turn it on, and then it asks for a code.</span></li>
            </ul>
          </div>
        </section>
        <section id="faq" className="wrap section" data-for="human">
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <p className="kicker">Questions</p>
            <h2>Before you set it up.</h2>
          </div>
          <div className="faq" itemScope itemType="https://schema.org/FAQPage">
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">What is Tinfoil Kit?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Tinfoil Kit is a free, open-source kit for when the internet goes down. It puts an AI, all of Wikipedia, medical and repair guides, and maps with directions on an external drive or your laptop. You set it up while you're online, and after that it all works with no internet.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Is the AI as good as ChatGPT?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Not quite. It's small enough to run on a laptop, so it's a step behind the big cloud AIs. It's good at explaining things, it shows where its answers come from, and it needs no internet.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Do I need the AI?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">No. The books and the map work without it. With the AI off, a question still searches every book and shows the best passages. To leave it out, pick No AI in the kit builder above.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">What do I need?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">A Mac with an M chip (M1 or newer), or a Windows or Linux PC with an Intel or AMD chip. 32&nbsp;GB of memory runs the full-size AI; with less, you get a lighter one. The recommended kit takes about 300&nbsp;GB on your laptop or an external SSD, and the kit builder above shows the size of yours. Short on room? The installer can get just the essentials, about 35 to 55&nbsp;GB: the AI, the map, the medical, preparedness and repair books, and Wikipedia's best articles.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Which AI will my laptop run?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <div itemProp="text">
                  <p>It depends on your laptop's memory. The kit picks for you, and you can switch any time.</p>
                  <table>
                    <thead>
                      <tr>
                        <th scope="col">Memory</th>
                        <th scope="col">The AI it runs</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr>
                        <td>8&nbsp;GB</td>
                        <td>Gemma 4 E4B, the small model (5&nbsp;GB). Close other apps before you ask it something.</td>
                      </tr>
                      <tr>
                        <td>16 to 24&nbsp;GB</td>
                        <td>Gemma 4 12B, the mid-size model (7&nbsp;GB). It reads photos too.</td>
                      </tr>
                      <tr>
                        <td>32&nbsp;GB or more</td>
                        <td>Inkling 2 Mini, the default (18&nbsp;GB). Qwen3.8 27B and Gemma 4 26B fit too, for a second opinion.</td>
                      </tr>
                    </tbody>
                  </table>
                  <p>The installer says which one your laptop runs, and offers to skip the ones too big for it, which saves about 50&nbsp;GB on a 16 or 24&nbsp;GB laptop. To see your memory, open About This Mac, or Settings &gt; System &gt; About on Windows. A Windows or Linux PC without a good graphics card should use Gemma 4 E4B.</p>
                </div>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Does anything leave my laptop?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">No. Once it's set up, everything runs on your laptop, with no account and no tracking. It only goes online when you install or update it, and then it only talks to the places it downloads from: GitHub, Kiwix, Hugging Face, Protomaps, Geofabrik, GraphHopper, Adoptium, Maven Central and npm, plus any source you add yourself.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">What does setup change on my computer?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <div itemProp="text">
                  <p>Very little. Everything goes in one folder, TinfoilKit, in your home folder or on the drive, and nothing runs unless you start it. Besides that:</p>
                  <ul>
                    <li>Mac: the Tinfoil Kit app goes in your Applications folder.</li>
                    <li>Mac: the kit clears macOS's "downloaded from the internet" mark from its own files, and signs a program if macOS won't open it otherwise, so everything opens in an outage.</li>
                    <li>Mac: what a kit in your home folder downloads stays out of Time Machine, and a kit drive stays out of Spotlight.</li>
                    <li>Linux: if curl is missing, the installer says how to get it.</li>
                  </ul>
                  <p>Only if you ask: a home server starts the kit with the computer and shares it on your home network, with an access code. Uninstalling deletes the folder and undoes the rest.</p>
                </div>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">How do I know it's safe?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">All the code is public, and you don't have to trust a server of ours. Before you install, you can have your AI read the code and tell you what it does: this page has a prompt for that. The kit installs updates to itself only if they're signed with the maintainer's key, which never touches GitHub. Every model, book, map and program comes straight from its publisher, checked against the publisher's checksum when there is one. Nothing outside your computer can reach the kit unless you turn on sharing, which asks for a code. The <a href="https://github.com/tudor-city-ventures/tinfoil-kit#security">README's Security section</a> says what it protects against, what it can't, and how to report a problem.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">What's the catch?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">None. It's free and open source (MIT license), with no account, no tracking in the kit and no analytics on this site. It's a side project from the team behind <a href="https://dotheysupportit.com">DoTheySupportIt</a>. It costs you disk space and a few hours of downloading.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">How is Tinfoil Kit different from Project NOMAD?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text"><a href="https://github.com/Crosstalk-Solutions/project-nomad">Project NOMAD</a>, from Crosstalk Solutions, is also free and open source. It turns a PC running Ubuntu or Debian into an offline server, in Docker, with an app catalog and an AI that can answer from your own documents. Tinfoil Kit runs on the Mac, Windows or Linux computer you have, with no Docker, from one folder that can live on a drive you plug into any of them. Its map finds addresses and gives directions, and sharing it at home takes an access code. Pick Project NOMAD for a home server with apps. Pick Tinfoil Kit for the laptop you have, or a drive that works on any computer.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Can I trust the AI's answers?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Check it, like you'd check a well-read friend. Each answer shows the pages it came from, so you can read them yourself. For anything medical, use it to look things up in WikiMed and the Army's medical manuals. It isn't a doctor: read the source, and get trained help when you can.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">What's under the hood?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Open-source parts, all running on your laptop: llama.cpp runs the AI, kiwix-serve runs the library, and Protomaps, Photon and GraphHopper run the map. One list in the kit says where every model, book and map comes from. Each update checks every download against its publisher's checksum, and keeps the old version until the new one checks out. The <a href="https://github.com/tudor-city-ventures/tinfoil-kit#readme">README</a> has the commands.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Can my family use it from their phones?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Yes. Turn on sharing, and phones and laptops on your Wi-Fi or hotspot can open it: they scan its QR code or type its 8-digit access code. No internet is needed, just your local network, and nobody can use it without the code. A computer that stays on can share it all the time, as a home server. <a href="https://github.com/tudor-city-ventures/tinfoil-kit/blob/main/GUIDE.md#using-it">The guide</a> shows how.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">How long does it run on battery?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">The big AI uses a lot of power: expect a couple of hours of active use. The small one uses much less, and reading with the AI off uses almost nothing. A USB-C power station and a folding solar panel keep it going.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Does it run on Windows or Linux?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Yes, all of it. Download and open it on any of the three. A kit on a drive formatted exFAT works on a Mac, Windows or Linux, whichever one set it up. Without a strong graphics card, the AI is slower. Windows and Linux are newer to the kit, so they're tested less than the Mac.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">How do I update it?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Open the installer again whenever you're online. There's no schedule. It shows what's new before anything downloads, your picks stay, and only what changed downloads. A newer download of Tinfoil Kit finds the kit you have and updates that one, so nothing downloads twice. Your old files keep working until the new ones check out, and you never have to take a newer edition. A new version replaces only the kit's app folder: your downloads and settings stay in folders of their own.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">How do I remove it?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Run the uninstaller in the kit's app folder and type delete. It removes the kit and everything it downloaded. On a drive, it leaves everything else alone.</p>
              </div>
            </details>
            <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
              <summary itemProp="name">Is all this content legal to download?</summary>
              <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
                <p itemProp="text">Yes, for your own use. Everything comes straight from its publishers: openly licensed sites like Wikipedia, WikiMed and iFixit, US government guides, and AI models published for anyone to run. Each keeps its own license, and some, like iFixit's, forbid commercial use, so don't sell drives you've filled. <a href="https://github.com/tudor-city-ventures/tinfoil-kit/blob/main/THIRD-PARTY.md">Every source and its license</a>.</p>
              </div>
            </details>
          </div>
        </section>
        <section id="built-on" className="band" data-for="human">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">Built on</p>
              <h2>Built on Wikipedia, OpenStreetMap and Kiwix.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "680px" }}>We put them together. They do the real work, so if the kit helps you, help them.</p>
            </div>
            <ul className="credits">
              <li><a className="name" href="https://kiwix.org/">Kiwix</a><span>Makes Wikipedia and other sites work offline.</span><a className="give" href="https://support.kiwix.org/">Donate to Kiwix</a></li>
              <li><a className="name" href="https://www.wikipedia.org/">Wikipedia</a><span>Most of the library, written by volunteers.</span><a className="give" href="https://donate.wikimedia.org/">Donate to Wikipedia</a></li>
              <li><a className="name" href="https://www.openstreetmap.org/">OpenStreetMap</a><span>The map, drawn by volunteers.</span><a className="give" href="https://supporting.openstreetmap.org/">Support OpenStreetMap</a></li>
              <li><a className="name" href="https://protomaps.com/">Protomaps</a><span>Turns OpenStreetMap into one map file.</span><a className="give" href="https://github.com/sponsors/protomaps">Sponsor Protomaps</a></li>
              <li><a className="name" href="https://maplibre.org/">MapLibre</a><span>Draws the map in your browser.</span><a className="give" href="https://opencollective.com/maplibre">Donate to MapLibre</a></li>
              <li><a className="name" href="https://github.com/ggml-org/llama.cpp">llama.cpp</a><span>Runs the AI on your laptop.</span></li>
              <li><a className="name" href="https://github.com/graphhopper/graphhopper">GraphHopper</a><span>Plans the routes.</span></li>
              <li><a className="name" href="https://github.com/komoot/photon">Photon</a><span>Finds addresses.</span></li>
            </ul>
            <p style={{ fontSize: "16px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "760px" }}>The AI models come from Thinking Machines, Alibaba's Qwen team and Google, the road data from Geofabrik, and the books from Wikipedia's sister sites, iFixit, LibreTexts, Stack Exchange, the US Army, FEMA and more. <a href="https://github.com/tudor-city-ventures/tinfoil-kit/blob/main/THIRD-PARTY.md">Every source and its license</a>.</p>
          </div>
        </section>
      </main>
      <footer>
        <div className="wrap">
          <span>A side project from the team behind <a href="https://dotheysupportit.com">DoTheySupportIt</a>.</span>
          {' '}
          <span>Tinfoil Kit · MIT · No analytics on this site · <a href="/llms.txt">llms.txt</a> for AI agents</span>
          {' '}
          <span className="fine">Provided as is, with no warranty, and not medical advice. Not affiliated with Apple, Wikipedia, Kiwix, Project NOMAD or any source named here; their names are their owners' trademarks. <a href="https://github.com/tudor-city-ventures/tinfoil-kit/blob/main/THIRD-PARTY.md">Third-party licenses</a>.</span>
        </div>
      </footer>
    </>
  );
}
