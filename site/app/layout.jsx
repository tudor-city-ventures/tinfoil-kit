import localFont from 'next/font/local';
import './globals.css';

const plexSans = localFont({ src: './fonts/plex-sans.woff2', weight: '400 700', variable: '--font-plex-sans' });
const plexMono = localFont({
  src: [
    { path: './fonts/plex-mono-400.woff2', weight: '400' },
    { path: './fonts/plex-mono-500.woff2', weight: '500' },
    { path: './fonts/plex-mono-600.woff2', weight: '600' },
  ],
  variable: '--font-plex-mono',
});

// No metadataBase: the page gives its addresses in full, and Next.js would drop the canonical's trailing slash.
export const metadata = {
  icons: {
    icon: [{ url: '/favicon.ico', sizes: '32x32' }, { url: '/icon.svg', type: 'image/svg+xml' }],
    apple: '/apple-touch-icon.png',
  },
};

export const viewport = { themeColor: '#F3F0E6' };

// Which version of the page to show: ?for=agent in the address, else the last pick, else the human one.
// It runs before the body draws, so the page never flashes the wrong version.
const pickReader = `(function (d) {
  var r = null;
  d.classList.add("js");
  try { r = new URLSearchParams(location.search).get("for") || localStorage.getItem("reader"); } catch (e) {}
  if (r === "agent") d.setAttribute("data-reader", r);
})(document.documentElement);`;

export default function RootLayout({ children }) {
  return (
    // the script above changes <html> before React starts, so its attributes differ from the server's on purpose
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`} data-scroll-behavior="smooth" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: pickReader }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
