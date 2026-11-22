'use client';

import { useEffect, useRef, useState } from 'react';

// The bar under Read as. On phones the sections fold behind Menu, which closes after a jump to a section or on Escape.
export default function Header() {
  const [open, setOpen] = useState(false);
  const menu = useRef(null);
  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key !== 'Escape') return;
      setOpen(false);
      menu.current.focus();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open]);
  return (
    <header className={open ? 'top open' : 'top'}>
      <div className="wrap">
        <a className="brand" href="#top" aria-label="Tinfoil Kit home">
          <img src="/icon.svg" width="36" height="36" alt="" />
          TINFOIL KIT
        </a>
        <button type="button" className="menu" id="menu" ref={menu} aria-expanded={open} aria-controls="sections" onClick={() => setOpen(!open)}>
          <svg className="bars" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" strokeWidth="2.5" /></svg>
          <svg className="x" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19" stroke="currentColor" strokeWidth="2.5" /></svg>
          Menu
        </button>
        <nav className="links" id="sections" aria-label="Sections" onClick={(e) => e.target.closest('a') && setOpen(false)}>
          <a href="#inside" data-for="human">What's inside</a>
          <a href="#builder" data-for="human">Build your kit</a>
          <a href="#prompts" data-for="human">Set up with AI</a>
          <a href="#trust" data-for="human">Is it safe?</a>
          <a href="#faq" data-for="human">Questions</a>
          <a href="/llms.txt" data-for="agent">llms.txt</a>
          <a href="https://github.com/tudor-city-ventures/tinfoil-kit" data-for="agent">GitHub</a>
        </nav>
      </div>
    </header>
  );
}
