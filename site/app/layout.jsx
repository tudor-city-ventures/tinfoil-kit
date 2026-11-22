import localFont from "next/font/local";
import "./globals.css";

const plexSans = localFont({ src: "./fonts/plex-sans.woff2", weight: "400 700", variable: "--font-plex-sans" });
const plexMono = localFont({
  src: [
    { path: "./fonts/plex-mono-400.woff2", weight: "400" },
    { path: "./fonts/plex-mono-500.woff2", weight: "500" },
    { path: "./fonts/plex-mono-600.woff2", weight: "600" },
  ],
  variable: "--font-plex-mono",
});

// No metadataBase: the page gives its addresses in full, and Next.js would drop the canonical's trailing slash.
export const metadata = {
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "32x32" },
      { url: "/icon.svg", type: "image/svg+xml" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

export const viewport = { themeColor: "#F3F0E6" };

// Before the page draws: mark that scripts run (the CSS uses it), and send old links to the agent version on to
// /agents. It was /?for=agent (Vercel redirects that too), and its instructions were at #instructions.
const early = `(function (d, l) {
  d.classList.add("js");
  if (l.pathname !== "/") return;
  if (new URLSearchParams(l.search).get("for") === "agent" || l.hash === "#instructions") l.replace("/agents");
})(document.documentElement, location);`;

export default function RootLayout({ children }) {
  return (
    // the script above changes <html> before React starts, so its class differs from the server's on purpose
    <html
      lang="en"
      className={`${plexSans.variable} ${plexMono.variable}`}
      data-scroll-behavior="smooth"
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: early }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
