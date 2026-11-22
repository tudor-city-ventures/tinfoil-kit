// Vercel serves this, as 404.html, for any address the site doesn't have.
export const metadata = { title: 'Not found · Tinfoil Kit' };   // Next.js adds noindex to it

export default function NotFound() {
  return (
    <div className="nf">
      <main>
        <p className="tag">404 · NOT FOUND</p>
        <h1>That page isn't here.</h1>
        <p>The link may be old or mistyped. Everything about the kit is on the home page.</p>
        <a href="/">Go to Tinfoil Kit</a>
      </main>
    </div>
  );
}
