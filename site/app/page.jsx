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
import Demo from "@/components/demo";
import Setup, { SetupLink } from "@/components/setup";
import Header from "@/components/header";
import Hero from "@/components/hero";
import { AUDIT_PROMPT, INSTALL_PROMPT, OWN_PROMPT } from "@/components/prompts";
import { APP, Footer, JsonLd, LICENSES, pageMetadata, Question, REPO, SITE } from "@/components/site";

// My AI installs it: the home page. Your AI asks what you want and gives you one command (there's no download until
// the Mac app can be signed). Plain words (AI, never LLM, GGUF or ZIM): llms.txt and the README name the parts for
// technical readers.
const DESCRIPTION =
  "A free, open-source copy of the world's knowledge for when the internet is down for days or weeks: Wikipedia, medical and survival guides, repair manuals, maps and a local offline AI that helps you search through them.";

export const metadata = pageMetadata({
  path: "/",
  title: "Tinfoil Kit: the world's knowledge, available when the internet isn't",
  description: DESCRIPTION,
});

// The drive we like: an Amazon affiliate link. Its card says buying through it supports us, and the footer says it's
// the site's one affiliate link, with Amazon's required line. It stays off the kit page, llms.txt and anything
// printed: Amazon's rules allow no offline use. The link stays as Amazon gives it: its tag credits the sale to us.
const DRIVE_PICK =
  "https://www.amazon.com/dp/B0H4HHBHY8?th=1&gaOptInStatus=true&linkCode=ll2&tag=tudorcityvent-20&linkId=0d121fd04615136d21e63a6aa2d1864c&language=en_US&gaOptInStatus=true&ref_=as_li_ss_tl";

const STEPS = [
  [
    "Buy an external SSD",
    "A portable USB SSD with room for the kit, from about 20 GB for just the essentials to about 900 GB for everything, formatted exFAT so it works on a Mac, Windows or Linux. Or use the computer's own disk.",
  ],
  [
    "Have your AI set it up",
    "Paste the prompt into ChatGPT, Claude or any AI chat. It reads the kit's instructions, asks what goes in the kit, and gives you one command to paste into your terminal: a small kit to try first, then the rest.",
  ],
  [
    "Use it on any computer",
    "Plug the drive into any Mac, Windows or Linux computer and open Tinfoil Kit. The AI, the library and the maps work with no internet.",
  ],
];

// What search engines and AI answer engines read about the kit. Keep its facts in step with the copy.
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "WebSite",
      "@id": `${SITE}/#site`,
      name: "Tinfoil Kit",
      url: `${SITE}/`,
    },
    {
      ...APP,
      description: DESCRIPTION,
      applicationCategory: "UtilitiesApplication",
      operatingSystem: "macOS, Windows, Linux",
      softwareRequirements:
        "A Mac with an M chip (M1 or newer). Windows 10 or 11 and Linux PCs with an Intel or AMD chip work too, but they're experimental for now. The kit goes on the computer's own disk or an external SSD, and on a drive formatted exFAT it starts on all three. Setup is one command in the terminal, which an AI chat writes for you.",
      memoryRequirements:
        "32 GB or more runs the default AI, Inkling 2 Mini; 16 to 24 GB runs Gemma 4 12B; 8 GB runs Gemma 4 E4B",
      storageRequirements:
        "From about 20 GB for just the essentials to about 900 GB for everything; about 200 to 300 GB for the recommended kit",
      featureList: [
        "Plain-word answers from the offline library, with numbered sources you can open",
        "An AI chat that runs on your laptop and can read photos",
        "Library: all of Wikipedia with pictures, the WikiMed medical encyclopedia, Army field and medical manuals, iFixit repair guides and FEMA emergency guides",
        "Map: address search, driving and walking directions, and the nearest hospital or pharmacy",
        "The AI is optional: the library and the map work without it",
        "Search every book without the AI: the best passages in seconds, on very little power",
        "Works with no internet, no account and no telemetry",
      ],
      isAccessibleForFree: true,
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
      },
      license: "https://opensource.org/license/mit",
      sameAs: REPO,
      image: `${SITE}/og.png`,
    },
    {
      "@type": "HowTo",
      "@id": `${SITE}/#howto`,
      name: "Set up Tinfoil Kit with your AI",
      description:
        "Paste one prompt into ChatGPT, Claude or a coding agent. It reads llms.txt, asks what you want, and gives you one command that sets up the kit.",
      url: `${SITE}/`,
      about: { "@id": APP["@id"] },
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
        url: `${SITE}/#how`,
      })),
    },
    {
      "@type": "SoftwareSourceCode",
      name: "Tinfoil Kit",
      codeRepository: REPO,
      programmingLanguage: ["Go", "JavaScript", "Shell"],
      license: "https://opensource.org/license/mit",
      runtimePlatform: "macOS on Apple silicon; Windows and Linux on x64 (experimental)",
      targetProduct: { "@id": APP["@id"] },
    },
  ],
};

const SECTIONS = [
  ["#uses", "What it's for"],
  ["#how", "How it works"],
  ["#demo", "Try it"],
  ["#builder", "Build your kit"],
  ["#trust", "Is it safe?"],
  ["#faq", "Questions"],
];

// On the drive: what the kit holds, named in the hero so nobody has to guess (the builder lists every source)
const DRIVE = [
  ["Wikipedia", "All of it, with pictures, plus textbooks, a dictionary and travel guides."],
  ["Medicine", "WikiMed, MedlinePlus, the CDC's guides and US military medical manuals."],
  ["Survival", "FEMA's guides and US Army field manuals: water, food, shelter, navigation."],
  ["Repair", "iFixit, plus how-tos for the house, the car, solar panels and radios."],
  ["Maps", "Your area's streets, directions and nearest hospital, and a map of the world."],
  ["AI", "Ask in plain words, and it searches everything above for you."],
];

// What it's for: what people need to know in a long outage, and the books that answer it. Medical lines look things
// up; they never diagnose.
const USES = [
  [
    "Someone's hurt",
    "Look up how to treat a burn, a deep cut or a broken bone, step by step.",
    "WikiMed · MedlinePlus · military medical manuals",
  ],
  [
    "The water isn't safe",
    "Boil it, filter it or disinfect it with household bleach: how long, and how much.",
    "CDC · FEMA · water treatment guides",
  ],
  [
    "You need to get somewhere",
    "Driving and walking directions on your own maps, and the nearest hospital or pharmacy.",
    "Offline maps",
  ],
  [
    "Something broke",
    "Fix a leaking pipe, a dead generator or the car, with guides from people who've done it.",
    "iFixit · home and car repair Q&A",
  ],
  [
    "The power's out",
    "Keep food safe without a fridge, and run what matters on solar panels and batteries.",
    "Food storage guides · Energypedia · Ready.gov",
  ],
  [
    "The kids are home",
    "Textbooks, courses and all of Wikipedia, so they can keep learning.",
    "Wikipedia · LibreTexts · Wikibooks",
  ],
];

export default function Home() {
  return (
    <>
      <JsonLd data={jsonLd} />
      <Header page="/" links={SECTIONS} />
      <main id="top">
        <section className="wrap hero">
          <div className="hero-copy">
            <p className="kicker">Free&nbsp;· Open source</p>
            <h1>The world's knowledge, available when the internet isn't.</h1>
            <p className="lede">
              Tinfoil Kit saves all of Wikipedia, medical and survival guides, repair manuals and maps to a drive you
              own, with a local offline AI that helps you search through them. If the internet is down for days or
              weeks, it all still works.
            </p>
            <Setup>
              <a className="star" href={REPO}>
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path
                    d="M12 2.2L14.6 9L21.9 9.4L16.2 14L18.1 21L12 17L5.9 21L7.8 14L2.1 9.4L9.4 9z"
                    fill="currentColor"
                  />
                </svg>
                Star on GitHub
              </a>
            </Setup>
          </div>
          <Hero />
          <div className="manifest" role="region" aria-labelledby="onDrive">
            <p className="manifest-head">
              <span id="onDrive">On the drive</span> <a href="#builder">You pick what goes in</a>
            </p>
            <ul>
              {DRIVE.map(([what, holds]) => (
                <li key={what}>
                  <b>{what}</b>
                  <span>{holds}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
        <section id="uses" className="how">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">What it's for</p>
              <h2>The questions a long outage brings.</h2>
            </div>
            <ul className="uses">
              {USES.map(([when, what, books]) => (
                <li key={when}>
                  <h3>{when}</h3>
                  <p>{what}</p>
                  <small>{books}</small>
                </li>
              ))}
            </ul>
            <p className="uses-foot">
              Ask in plain words, and the AI helps you find the answer in these books. Or skip the AI: Search finds the
              right passages in seconds, on very little power.
            </p>
          </div>
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
                  A portable USB drive with room for the kit: from about 20&nbsp;GB for just the essentials to about
                  900&nbsp;GB for everything.{" "}
                  <a href={DRIVE_PICK} rel="sponsored nofollow">
                    We like this one
                  </a>
                  .
                </p>
                <small>No drive? It can go straight on your computer instead.</small>
                <small>
                  You can support our work by buying your external drive on Amazon through that link (it earns us a
                  commission).
                </small>
              </li>
              <li>
                <b>02 · TELL YOUR AI</b>
                <h3>{STEPS[1][0]}</h3>
                <p>
                  Paste the prompt into ChatGPT, Claude or any AI chat. It asks where you live and what you want in it,
                  then gives you one command to paste into your terminal.
                </p>
                <SetupLink>Get the prompt</SetupLink>
                <small>
                  First it gets a small kit to try, about 10&nbsp;GB. When you're ready, the rest: hours of downloading.
                  It says how long before it starts.
                </small>
              </li>
              <li>
                <b>03 · PLUG IN ANYWHERE</b>
                <h3>{STEPS[2][0]}</h3>
                <p>
                  Plug the drive into any Mac, Windows or Linux computer and open Tinfoil Kit. The AI, the library and
                  the maps work with no internet.
                </p>
                <small>Windows and Linux are experimental for now.</small>
              </li>
            </ol>
          </div>
        </section>
        <section id="demo" className="band">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">Try it</p>
              <h2>See what you get.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "720px" }}>
                Tinfoil Kit opens in your browser like a website, but it all runs on your laptop, with no internet. Ask
                a sample question, plan a route or browse the library. The demo's answers were written ahead of time.
              </p>
            </div>
            <Demo />
          </div>
        </section>
        <section id="builder" className="wrap section">
          <Builder>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">The kit builder</p>
              <h2>Choose what goes in your kit.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "680px" }}>
                Pick what goes in, then copy the prompt for your AI. Your picks go with it, so it asks only about the
                rest.
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
                Why we ask: street maps and directions for the whole world would take hundreds of gigabytes, so your kit
                gets them only for where you live and any places nearby you add, like the state or country next door.
                Everywhere else gets a simple map. This page doesn't send your answers anywhere: they only go into the
                prompt you copy.
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
                An external drive goes with you and works on any computer. A home server is a computer that stays on, so
                the phones and laptops at home can use the kit through it, with an access code. Leave it unpicked and
                your AI asks.
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
        </section>
        <section id="prompts" className="band">
          <div className="wrap section">
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
          </div>
        </section>
        <section id="trust" className="oss">
          <div className="wrap">
            <div style={{ flex: "1 1 520px", display: "flex", flexDirection: "column", gap: "16px" }}>
              <p className="kicker" style={{ color: "#E0884F" }}>
                Don't trust, verify
              </p>
              <h2>Don't trust us? No problem. Have your AI audit the code.</h2>
              <p>
                Before you install anything, paste this into ChatGPT, Claude or any AI chat. It reads the code and tells
                you what the kit does, without running it.
              </p>
            </div>
            <a
              className="btn primary"
              style={{ minHeight: "60px", fontSize: "19px", padding: "0 28px", borderColor: "var(--signal)" }}
              href={REPO}
            >
              <svg
                width="22"
                height="22"
                viewBox="0 0 24 24"
                aria-hidden="true"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.9a3.4 3.4 0 0 0-.9-2.6c3.1-.3 6.4-1.5 6.4-7a5.4 5.4 0 0 0-1.5-3.7 5 5 0 0 0-.1-3.8s-1.2-.3-3.9 1.5a13.4 13.4 0 0 0-7 0C6.3 1.7 5.1 2 5.1 2a5 5 0 0 0-.1 3.8A5.4 5.4 0 0 0 3.5 9.5c0 5.4 3.3 6.6 6.4 7a3.4 3.4 0 0 0-.9 2.6V22" />
              </svg>{" "}
              View the code on GitHub
            </a>
            <div className="prompt">
              <div className="bar">
                <div>
                  <b>Check the code</b>
                  <span>Your AI reads it and reports back. Nothing gets installed.</span>
                </div>
                <CopyButton target="auditPrompt" />
              </div>
              <pre id="auditPrompt" tabIndex={0}>
                {AUDIT_PROMPT}
              </pre>
            </div>
            <ul className="facts">
              <li>
                <b>Every line is public</b>
                <span>
                  The kit's code and this website's are on GitHub. The README's{" "}
                  <a href={`${REPO}#security`}>Security section</a> says what it protects against, and what it can't.
                </span>
              </li>
              <li>
                <b>Nothing leaves your laptop</b>
                <span>
                  No account, no tracking. It goes online only to set up or update, and then only to the publishers it
                  downloads from.
                </span>
              </li>
              <li>
                <b>Every download is checked</b>
                <span>
                  The kit checks every program against the exact copy it expects, and updates itself only from releases
                  signed with the maintainer's key.
                </span>
              </li>
              <li>
                <b>Only you can reach it</b>
                <span>
                  It runs on your computer and answers only you. Sharing with your home network stays off until you turn
                  it on, and then it asks for a code.
                </span>
              </li>
            </ul>
            <pre className="code" tabIndex={0}>
              {`# check a release before you run it
ssh-keygen -Y verify -f tools/release-signers -I tinfoilkit-release \\
  -n tinfoilkit-release -s tinfoilkit-TAG.tar.gz.sig < tinfoilkit-TAG.tar.gz
# rebuild a kit's program from its source, and compare
tools/tinfoilkit/build.sh verify SHA256SUMS`}
            </pre>
          </div>
        </section>
        <section id="faq" className="wrap section">
          <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            <p className="kicker">Questions</p>
            <h2>Before you set it up.</h2>
          </div>
          <div className="faq" itemScope itemType="https://schema.org/FAQPage">
            <Question q="What is Tinfoil Kit?">
              Tinfoil Kit is a free, open-source copy of the world's knowledge for when the internet is down for days or
              weeks. It puts all of Wikipedia, medical and survival guides, repair manuals and maps with directions on
              an external drive or your laptop, with a local offline AI that helps you search through them. You set it
              up while you're online, and after that it all works with no internet.
            </Question>
            <Question q="Do I need ChatGPT or Claude?">
              Any AI chat that can read a web page works, free ones included: it reads the kit's setup instructions at
              tinfoilkit.com/llms.txt. One that can run commands on your computer, like Claude Code or Codex, checks
              your computer and drive itself; a chat asks you instead. Either way, you paste the command it gives you.
              Rather not use an AI? <a href={`${REPO}#set-up`}>The README</a> has the command and its options.
            </Question>
            <Question q="Can my AI just install it?">
              It could, but the kit's instructions ask it not to. Your AI asks the questions and hands you one command,
              so you see exactly what runs and nothing installs behind your back. Updates, fixes and removal work the
              same way.
            </Question>
            <Question q="Is the AI as good as ChatGPT?">
              Not quite. It's small enough to run on a laptop, so it's a step behind the big cloud AIs. It's good at
              explaining things, it shows where its answers come from, and it needs no internet.
            </Question>
            <Question q="Do I need the AI?">
              No. The books and the map work without it, and Search finds the best passages in every book in seconds,
              without the AI, on very little power. The AI is for when you want an answer written for you, with sources.
              Pick No AI in the kit builder, or tell your AI to leave it out.
            </Question>
            <Question q="What do I need?">
              A Mac with an M chip (M1 or newer). Windows and Linux PCs with an Intel or AMD chip work too, but they're
              experimental for now. 32&nbsp;GB of memory runs the full-size AI; with less, you get a lighter one. On
              your laptop or an external SSD, the kit takes from about 20&nbsp;GB for just the essentials (the AI, the
              map, the medical, preparedness and repair books, and Wikipedia's best articles) to about 900&nbsp;GB for
              everything. The recommended kit is about 200 to 300&nbsp;GB. Setup checks that it fits, and says how long
              it takes to download, before it starts: on a 100&nbsp;Mbps connection, about an hour for the essentials
              and 4 to 7 hours for the recommended kit.
            </Question>
            <Question q="Which AI will my laptop run?" block>
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
                    <td>
                      Inkling 2 Mini, the default (18&nbsp;GB). Qwen3.8 27B and Gemma 4 26B fit too, for a second
                      opinion.
                    </td>
                  </tr>
                </tbody>
              </table>
              <p>
                Setup says which one your laptop runs, and offers to skip the ones too big for it, which saves about
                50&nbsp;GB on a 16 or 24&nbsp;GB laptop. To see your memory, open About This Mac, or Settings &gt;
                System &gt; About on Windows. A Windows or Linux PC without a good graphics card should use Gemma 4 E4B.
              </p>
            </Question>
            <Question q="What do the maps cover?">
              Where you live, in street detail, with driving and walking directions and address search: a US state, a
              country, or part of a big one. Add places nearby, like the state next door, and they get street maps and
              directions too. The rest of the world is a simple map. You pick the places when you set it up, and can
              change them any time.
            </Question>
            <Question q="Does anything leave my laptop?">
              No. Once it's set up, everything runs on your laptop, with no account and no tracking. It only goes online
              when you install or update it, and then it only talks to the places it downloads from: GitHub, Kiwix,
              Hugging Face, Protomaps, Geofabrik, GraphHopper, Adoptium, Maven Central and npm, plus any source you add
              yourself.
            </Question>
            <Question q="What does setup change on my computer?" block>
              <p>
                Very little. Everything goes in one folder, TinfoilKit, in your home folder or on the drive, and nothing
                runs unless you start it. It needs no Docker, Python or Node: the kit's own program downloads, checks
                and runs it all with curl, which Macs and Windows come with. Besides that:
              </p>
              <ul>
                <li>
                  Mac: the kit clears macOS's "downloaded from the internet" mark from its own files, and signs a
                  program if macOS won't open it otherwise, so everything opens in an outage.
                </li>
                <li>
                  Mac: what a kit in your home folder downloads stays out of Time Machine, and a kit drive stays out of
                  Spotlight.
                </li>
                <li>Linux: if curl is missing, setup says how to get it.</li>
              </ul>
              <p>
                Only if you ask: a home server starts the kit with the computer and shares it on your home network, with
                an access code. Uninstalling deletes the folder and undoes the rest.
              </p>
            </Question>
            <Question q="How do I know it's safe?">
              All the code is public, and you don't have to trust a server of ours. Before you install, you can have
              your AI read the code and tell you what it does: this page has a prompt for that. The kit installs updates
              to itself only if they're signed with the maintainer's key, which never touches GitHub, and its program
              rebuilds to the same bytes from its source, so anyone can check it. Every model, book, map and program
              comes straight from its publisher, checked against the publisher's checksum when there is one. Nothing
              outside your computer can reach the kit unless you turn on sharing, which asks for a code. The{" "}
              <a href={`${REPO}#security`}>README's Security section</a> says what it protects against, what it can't,
              and how to report a problem.
            </Question>
            <Question q="Can I add my own books or AI models?">
              Yes. Everything the kit downloads is listed in one file in the kit, with each publisher's download, and a
              new version of the kit adds its changes without touching yours. Your AI can find more of Kiwix's offline
              books and add models from Hugging Face: the kit's instructions show it how.
            </Question>
            <Question q="What's the catch?">
              None. It's free and open source (MIT license), with no account, no tracking in the kit and no analytics on
              this site. It's a side project from the team behind{" "}
              <a href="https://dotheysupportit.com">DoTheySupportIt</a>. If you buy the drive we link to, we earn a
              commission. It costs you disk space and hours of downloading.
            </Question>
            <Question q="How is Tinfoil Kit different from Project NOMAD?">
              <a href="https://github.com/Crosstalk-Solutions/project-nomad">Project NOMAD</a>, from Crosstalk
              Solutions, is also free and open source. It turns a PC running Ubuntu or Debian into an offline server, in
              Docker, with an app catalog and an AI that can answer from your own documents. Tinfoil Kit runs on the
              Mac, Windows or Linux computer you have, with no Docker, from one folder that can live on a drive you plug
              into any of them. Its map finds addresses and gives directions, and sharing it at home takes an access
              code. Pick Project NOMAD for a home server with apps. Pick Tinfoil Kit for the laptop you have, or a drive
              that works on any computer.
            </Question>
            <Question q="Can I trust the AI's answers?">
              Check it, like you'd check a well-read friend. Each answer links to its sources, so you can read them
              yourself. For anything medical, use it to look things up in WikiMed and the Army's medical manuals. It
              isn't a doctor: read the source, and get trained help when you can.
            </Question>
            <Question q="Can my family use it from their phones?">
              Yes. Turn on sharing, and phones and laptops on your Wi-Fi or hotspot can open it: they scan its QR code,
              open a link you text them, or type its 8-digit access code. No internet is needed, just your local
              network, and nobody can use it without the code. A computer that stays on can share it all the time, as a
              home server, which is experimental for now.{" "}
              <a href={`${REPO}/blob/main/kit/GUIDE.md#using-it`}>The guide</a> shows how.
            </Question>
            <Question q="How long does it run on battery?">
              The big AI uses a lot of power: expect a couple of hours of active use. The small one uses much less, and
              searching and reading the books without the AI uses almost nothing. A USB-C power station and a folding
              solar panel keep it going.
            </Question>
            <Question q="Does it run on Windows or Linux?">
              Yes, all of it, but Windows and Linux are experimental for now: they're tested less than the Mac, so
              expect rough edges. Your AI sets it up on any of the three. The kit carries the programs for all three, so
              a kit on a drive formatted exFAT works on a Mac, Windows or Linux, whichever one set it up. Without a
              strong graphics card, the AI is slower.
            </Question>
            <Question q="How do I update it?">
              Run setup again whenever you're online: double-click SETUP in the kit's app folder, or ask your AI for the
              command. There's no schedule. It shows what's new before anything downloads, your picks stay, and only
              what changed downloads. Your old files keep working until the new ones check out, and you never have to
              take a newer edition. A new version replaces only the kit's app folder: your downloads and settings stay
              in folders of their own.
            </Question>
            <Question q="How do I remove it?">
              Run the uninstaller in the kit's app folder and type delete. It removes the kit and everything it
              downloaded. On a drive, it leaves everything else alone.
            </Question>
            <Question q="Is all this content legal to download?">
              Yes, for your own use. Everything comes straight from its publishers: openly licensed sites like
              Wikipedia, WikiMed and iFixit, US government guides, and AI models published for anyone to run. Each keeps
              its own license, and some, like iFixit's, forbid commercial use, so don't sell drives you've filled.{" "}
              <a href={LICENSES}>Every source and its license</a>.
            </Question>
          </div>
        </section>
        <section id="built-on" className="band">
          <div className="wrap section">
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <p className="kicker">Built on</p>
              <h2>Built on Wikipedia, OpenStreetMap and Kiwix.</h2>
              <p style={{ fontSize: "18px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "680px" }}>
                We put them together. They do the real work, so if the kit helps you, help them.
              </p>
            </div>
            <ul className="credits">
              <li>
                <a className="name" href="https://kiwix.org/">
                  Kiwix
                </a>
                <span>Makes Wikipedia and other sites work offline.</span>
                <a className="give" href="https://support.kiwix.org/">
                  Donate to Kiwix
                </a>
              </li>
              <li>
                <a className="name" href="https://www.wikipedia.org/">
                  Wikipedia
                </a>
                <span>Most of the library, written by volunteers.</span>
                <a className="give" href="https://donate.wikimedia.org/">
                  Donate to Wikipedia
                </a>
              </li>
              <li>
                <a className="name" href="https://www.openstreetmap.org/">
                  OpenStreetMap
                </a>
                <span>The map, drawn by volunteers.</span>
                <a className="give" href="https://supporting.openstreetmap.org/">
                  Support OpenStreetMap
                </a>
              </li>
              <li>
                <a className="name" href="https://protomaps.com/">
                  Protomaps
                </a>
                <span>Turns OpenStreetMap into one map file.</span>
                <a className="give" href="https://github.com/sponsors/protomaps">
                  Sponsor Protomaps
                </a>
              </li>
              <li>
                <a className="name" href="https://maplibre.org/">
                  MapLibre
                </a>
                <span>Draws the map in your browser.</span>
                <a className="give" href="https://opencollective.com/maplibre">
                  Donate to MapLibre
                </a>
              </li>
              <li>
                <a className="name" href="https://github.com/ggml-org/llama.cpp">
                  llama.cpp
                </a>
                <span>Runs the AI on your laptop.</span>
              </li>
              <li>
                <a className="name" href="https://github.com/graphhopper/graphhopper">
                  GraphHopper
                </a>
                <span>Plans the routes.</span>
              </li>
              <li>
                <a className="name" href="https://github.com/komoot/photon">
                  Photon
                </a>
                <span>Finds addresses.</span>
              </li>
            </ul>
            <p style={{ fontSize: "16px", lineHeight: "1.5", color: "var(--ink2)", maxWidth: "760px" }}>
              The AI models come from Thinking Machines, Alibaba's Qwen team and Google, the road data from Geofabrik,
              and the books from Wikipedia's sister sites, iFixit, LibreTexts, Stack Exchange, the US Army, FEMA and
              more. <a href={LICENSES}>Every source and its license</a>.
            </p>
          </div>
        </section>
      </main>
      <Footer />
    </>
  );
}
