// What every page shares: the site's addresses, each page's metadata, a FAQ entry, structured data and the footer.
// These run only on the server, as the site builds.

export const SITE = "https://tinfoilkit.com";
export const REPO = "https://github.com/tudor-city-ventures/tinfoil-kit";
export const LICENSES = `${REPO}/blob/main/THIRD-PARTY.md`;

// The kit, as each page's structured data names it. The home page describes it in full.
export const APP = { "@type": "SoftwareApplication", "@id": `${SITE}/#app`, name: "Tinfoil Kit", url: `${SITE}/` };

// What a link to the site shows in a chat or a post: the pitch to a friend. Keep the card at /og.png: Facebook and
// Messenger cache it by its address, and a new address starts over with previews that have no picture.
const PREVIEW = {
  title: "Tinfoil Kit",
  description:
    "The world's knowledge, ready when the internet isn't. Wikipedia, medical and survival guides, maps and a local offline AI, on one drive or your laptop. Free and open source.",
};

// A page's own address, title and summary, for search engines and AI answer engines, and its link preview. Addresses
// are in full: the layout sets no metadataBase, which would drop the home page's trailing slash.
export function pageMetadata({ path, title, description, preview = PREVIEW }) {
  const url = SITE + path;
  return {
    title,
    description,
    alternates: {
      canonical: url,
      types: { "text/markdown": [{ url: "/llms.txt", title: "Setup instructions for AI agents" }] },
    },
    openGraph: {
      title: preview.title,
      description: preview.description,
      type: "website",
      url,
      images: [
        {
          url: `${SITE}/og.png`,
          width: 1200,
          height: 630,
          alt: "Tinfoil Kit. The world's knowledge, ready when the internet isn't. Beside it, the logo: a globe wearing a tinfoil hat.",
        },
      ],
    },
    twitter: { card: "summary_large_image" },
  };
}

export function JsonLd({ data }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}

// One question in a page's FAQ, marked up as a schema.org Question and Answer that answer engines can quote. An answer
// with lists or tables is a block, with its own paragraphs.
export function Question({ q, block, children }) {
  const Text = block ? "div" : "p";
  return (
    <details itemScope itemProp="mainEntity" itemType="https://schema.org/Question">
      <summary itemProp="name">{q}</summary>
      <div itemScope itemProp="acceptedAnswer" itemType="https://schema.org/Answer">
        <Text itemProp="text">{children}</Text>
      </div>
    </details>
  );
}

export function Footer() {
  return (
    <footer>
      <div className="wrap">
        <span>
          A side project from the team behind <a href="https://dotheysupportit.com">DoTheySupportIt</a>.
        </span>{" "}
        <span>
          Tinfoil Kit · MIT · No analytics on this site · <a href="/llms.txt">llms.txt</a> for AI agents
        </span>{" "}
        <span className="fine">
          Provided as is, with no warranty, and not medical advice. Not affiliated with Apple, Wikipedia, Kiwix, Project
          NOMAD or any source named here; their names are their owners' trademarks.{" "}
          <a href={LICENSES}>Third-party licenses</a>.
        </span>
      </div>
    </footer>
  );
}
