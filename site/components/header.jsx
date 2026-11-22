"use client";

import { useEffect, useRef, useState } from "react";

// The two versions of the site, one for each way in. Each is a page of its own, so search engines rank them apart.
const VERSIONS = [
  ["/", "My AI installs it"],
  ["/agents", "I'm an AI"],
];

// The versions, then the bar with this page's sections (links: [href, label] pairs). On phones the sections fold
// behind Menu, which closes after a jump to a section or on Escape; a flat bar keeps its few links listed.
export default function Header({ page, links, flat }) {
  const [open, setOpen] = useState(false);
  const menu = useRef(null);
  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key !== "Escape") return;
      setOpen(false);
      menu.current.focus();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <>
      <nav className="versions" aria-label="Versions of this site">
        <div className="wrap">
          {VERSIONS.map(([href, label]) => (
            <a key={href} href={href} aria-current={href === page ? "page" : undefined}>
              {label}
            </a>
          ))}
        </div>
      </nav>
      <header className={["top", flat && "flat", open && "open"].filter(Boolean).join(" ")}>
        <div className="wrap">
          <a className="brand" href="/" aria-label="Tinfoil Kit home">
            <img src="/icon.svg" width="36" height="36" alt="" />
            TINFOIL KIT
          </a>
          {flat ? null : (
            <button
              type="button"
              className="menu"
              id="menu"
              ref={menu}
              aria-expanded={open}
              aria-controls="sections"
              onClick={() => setOpen(!open)}
            >
              <svg className="bars" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" strokeWidth="2.5" />
              </svg>
              <svg className="x" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2.5" />
              </svg>
              Menu
            </button>
          )}
          <nav
            className="links"
            id="sections"
            aria-label="Sections"
            onClick={(e) => e.target.closest("a") && setOpen(false)}
          >
            {links.map(([href, label]) => (
              <a key={href} href={href}>
                {label}
              </a>
            ))}
          </nav>
        </div>
      </header>
    </>
  );
}
