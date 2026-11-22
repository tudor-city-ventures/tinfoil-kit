// A static site: `next build` writes plain files to out/, which Vercel serves with the headers in vercel.json.
const config = {
  output: 'export',
  images: { unoptimized: true },
  agentRules: false,   // next dev would write site/AGENTS.md; the repo's own AGENTS.md covers the site
};

export default config;
