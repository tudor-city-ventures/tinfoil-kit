import { fileURLToPath } from "node:url";

// A static site: `next build` writes plain files to out/, which Vercel serves with the headers in vercel.json.
const config = {
  output: "export",
  images: { unoptimized: true },
  agentRules: false, // next dev would write site/AGENTS.md; the repo's own AGENTS.md covers the site
  // The site is site/, not the repo root, whose package-lock.json is the kit page's developer tools.
  turbopack: { root: fileURLToPath(new URL(".", import.meta.url)) },
};

export default config;
