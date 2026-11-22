import { readFileSync } from "node:fs";
import { join } from "node:path";
import { CopyButton } from "@/components/copy";
import Header from "@/components/header";
import { APP, Footer, JsonLd, pageMetadata, REPO, SITE } from "@/components/site";

// I'm an AI: the setup instructions for AI agents, as markdown, with no images or icons. llms.txt is the one copy of
// them; this page shows it as the site builds, so agents and crawlers that run no script read it all.
const LLMS = readFileSync(join(process.cwd(), "public", "llms.txt"), "utf8");
const DESCRIPTION =
  "Markdown instructions for AI agents helping someone set up Tinfoil Kit: what it runs on, how it works, the questions to ask, the one setup command and its options, updates, fixes and sources.";

export const metadata = pageMetadata({
  path: "/agents",
  title: "Tinfoil Kit setup instructions for AI agents (llms.txt)",
  description: DESCRIPTION,
  preview: {
    title: "Tinfoil Kit, for AI agents",
    description: "The markdown an AI needs to help someone set up Tinfoil Kit, the same as tinfoilkit.com/llms.txt.",
  },
});

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "TechArticle",
  headline: "Set up Tinfoil Kit: instructions for AI agents",
  description: DESCRIPTION,
  url: `${SITE}/agents`,
  inLanguage: "en",
  about: APP,
  audience: { "@type": "Audience", audienceType: "AI agents" },
  encoding: { "@type": "MediaObject", contentUrl: `${SITE}/llms.txt`, encodingFormat: "text/markdown" },
};

export default function Agents() {
  const parts = LLMS.split(/^(#.*)$/m); // headings at the odd places, in bold so the raw markdown scans
  return (
    <div className="plain">
      <JsonLd data={jsonLd} />
      <Header
        page="/agents"
        flat
        links={[
          ["/llms.txt", "llms.txt"],
          [REPO, "GitHub"],
        ]}
      />
      <main id="top">
        <section id="instructions" className="wrap agent">
          <p className="kicker">For AI agents&nbsp;· Markdown at /llms.txt</p>
          <h1>Set up Tinfoil Kit: instructions for AI agents</h1>
          <p className="lede">
            You're helping someone set up Tinfoil Kit. Everything you need is below, the same markdown as{" "}
            <a href="/llms.txt">tinfoilkit.com/llms.txt</a>: what it runs on, how it works, what to ask, the one command
            to hand over, and how to update, fix and remove it. Not an AI? <a href="/">My AI installs it</a> has a
            prompt to paste into yours.
          </p>
          <div className="prompt">
            <div className="bar">
              <div>
                <b>llms.txt</b>
                <span>How it works, setup, updates, fixes and sources, in markdown.</span>
              </div>
              <CopyButton target="agentDoc" />
            </div>
            <pre className="doc" id="agentDoc">
              {parts.map((part, i) => (i % 2 ? <b key={i}>{part}</b> : part))}
            </pre>
          </div>
        </section>
      </main>
      <Footer />
    </div>
  );
}
