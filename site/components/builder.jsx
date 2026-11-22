'use client';

import { createContext, use, useEffect, useMemo, useReducer, useState } from 'react';
import { flushSync } from 'react-dom';
import { copyText, selectNode, toast } from '@/components/copy';
import { INSTALL_PROMPT } from '@/components/prompts';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectTrigger, SelectValue } from '@/components/ui/select';
import { loadJSON } from '@/lib/data';

// The kit builder. Builder holds what's picked and the parts below read and change it, so the section's copy stays
// in page.jsx. The data: sources.json (the cards), kit.json (the kit's own place) and regions.json (where you live:
// the same places as SETUP's question and ./kit region).

const VISIBLE = 6;   // cards a group shows before "Show all"
const WIKI = /^wikipedia_[a-z-]+_all_/;
const GROUPS = ['United States', 'North America', 'Central America', 'South America', 'Europe', 'Africa', 'Asia'];

function gb(bytes) {
  if (bytes == null) return 'size TBD';
  if (bytes === 0) return '0 GB';   // a group with nothing picked, like the models under No AI
  const g = bytes / 1e9;
  return '~' + (g < 1 ? '<1' : g < 10 ? g.toFixed(1).replace(/\.0$/, '') : Math.round(g)) + ' GB';
}

function langName(regions, codes) {
  const names = codes.map((c) => regions.languages[c].name);
  return names.length > 1 ? names.slice(0, -1).join(', ') + ' and ' + names[names.length - 1] : names[0];
}

// A place's own languages, English, and its first two together; a small Wikipedia only alongside another.
function languageChoices(regions, place) {
  const langs = regions.languages;
  const codes = (place.langs || []).filter((c) => langs[c]);
  if (langs.en && !codes.includes('en')) codes.push('en');
  const out = codes.filter((c) => c === 'en' || (langs[c].mb || 0) >= 1000).map((c) => [c]);
  if (codes.length > 1) out.push(codes.slice(0, 2));
  return out;
}

function wikiCard(regions, code, like) {
  const l = regions.languages[code];
  if (code === 'en' && like.id === 'wikipedia_en_all_maxi') return like;
  return {
    id: l.zim, group: like.group, presets: like.presets, estimated: true, bytes: Math.round((l.mb || 0) * 1e6),
    title: 'Wikipedia in ' + l.name + (l.pictures ? ', with images' : ''),
    why: 'All of ' + l.name + ' Wikipedia' + (l.native && l.native !== l.name ? ' (' + l.native + ')' : '') + '. The reference for nearly any question.',
  };
}

function mapsCard(kit, place, like) {
  const addr = !place.photon ? 'no address search, since nobody publishes it there yet'
    : 'address search for all of ' + (place.addresses || place.name) + (place.addresses_wide ? ', since nobody publishes it for ' + place.name + ' alone' : '');
  const card = {
    id: like.id, group: like.group, presets: like.presets, title: like.title, estimated: like.estimated, bytes: like.bytes,
    why: 'Street maps and driving or walking directions for ' + place.name + ', with ' + addr + '.',
  };
  if (place.id !== kit.maps.region) {   // the builder's own sizes are for kit.json's place
    card.bytes = Math.round(0.1e9 + Object.values(place.mb).reduce((t, mb) => t + mb, 0) * 1e6);
    card.estimated = true;
  }
  return card;
}

// The cards: the place's map, and Wikipedia in the languages picked.
function cardsFor({ data, place, wiki }) {
  if (!data) return [];
  if (!place) return data.base;
  return data.base.flatMap((s) => (s.id === 'maps' ? [mapsCard(data.kit, place, s)]
    : WIKI.test(s.id) ? wiki.map((c) => wikiCard(data.regions, c, s)) : [s]));
}

function withPreset(state, preset) {
  return { ...state, preset, picked: Object.fromEntries(cardsFor(state).map((s) => [s.id, s.presets.includes(preset)])) };
}

// New Wikipedia cards keep the old ones' tick.
function withWiki(state, wiki) {
  const wasOn = cardsFor(state).some((s) => WIKI.test(s.id) && state.picked[s.id]);
  const next = { ...state, wiki, picked: { ...state.picked } };
  cardsFor(next).forEach((s) => { if (WIKI.test(s.id)) next.picked[s.id] = wasOn; });
  return next;
}

function reducer(state, a) {
  switch (a.type) {
    case 'loaded': {
      const data = { base: a.sources.sources, kit: a.kit, regions: a.regions };
      const home = a.regions.regions.find((r) => r.id === a.kit.maps.region) || null;
      const wiki = home ? languageChoices(a.regions, home)[0] : state.wiki;
      return withPreset({ ...state, data, place: home, wiki }, state.preset || 'recommended');
    }
    case 'failed': return { ...state, failed: true };
    case 'preset': return withPreset({ ...state, from: a.preset }, a.preset);
    case 'pick': return { ...state, preset: null, picked: { ...state.picked, [a.id]: a.on } };
    case 'more': return { ...state, open: { ...state.open, [a.group]: !state.open[a.group] } };
    case 'place': return withWiki({ ...state, chosen: true, place: a.place }, languageChoices(state.data.regions, a.place)[0]);
    case 'wiki': return withWiki({ ...state, chosen: true }, a.wiki);
    default: throw new Error(a.type);
  }
}

// chosen: the person picked where they live (until then the AI asks). from: the preset their picks started from.
const START = { data: null, failed: false, place: null, wiki: ['en'], picked: {}, preset: 'recommended', from: 'recommended', chosen: false, open: {} };
const Kit = createContext(null);

export default function Builder({ children }) {
  const [state, dispatch] = useReducer(reducer, START);
  const [setupText, showSetup] = useState(null);   // the setup prompt, shown selected when copying fails
  useEffect(() => {
    let live = true;
    Promise.all(['sources.json', 'kit.json', 'regions.json'].map(loadJSON)).then(
      ([sources, kit, regions]) => live && dispatch({ type: 'loaded', sources, kit, regions }),
      () => live && dispatch({ type: 'failed' }),
    );
    return () => { live = false; };
  }, []);
  const { data, place, wiki } = state;
  const cards = useMemo(() => cardsFor({ data, place, wiki }), [data, place, wiki]);
  return <Kit value={{ state, cards, dispatch, setupText, showSetup }}>{children}</Kit>;
}

// The places by group, nearest groups first, then A to Z.
function placeGroups(regions) {
  const groups = {};
  regions.forEach((r) => (groups[r.group] ||= []).push(r));
  const rank = (g) => (GROUPS.includes(g) ? GROUPS.indexOf(g) : GROUPS.length);
  return Object.keys(groups).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b))
    .map((g) => [g, groups[g].sort((a, b) => a.name.localeCompare(b.name))]);
}

export function PlaceSelect() {
  const { state, dispatch } = use(Kit);
  const regions = state.data?.regions;
  const groups = useMemo(() => (regions ? placeGroups(regions.regions) : []), [regions]);
  function pick(id) {
    dispatch({ type: 'place', place: regions.regions.find((r) => r.id === id) });
  }
  return (
    <Select value={state.place?.id ?? ''} onValueChange={pick} disabled={!regions}>
      <SelectTrigger id="place" aria-describedby="placeNote"><SelectValue placeholder={regions ? 'Choose a place' : 'Loading places…'} /></SelectTrigger>
      <SelectContent>
        {groups.map(([group, places]) => (
          <SelectGroup key={group}>
            <SelectLabel>{group}</SelectLabel>
            {places.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}

export function WikiSelect() {
  const { state, dispatch } = use(Kit);
  const { data, place, wiki } = state;
  const choices = place ? languageChoices(data.regions, place) : [];
  return (
    <Select value={place ? wiki.join(',') : ''} onValueChange={(v) => dispatch({ type: 'wiki', wiki: v.split(',') })} disabled={!place}>
      <SelectTrigger id="wikiLang"><SelectValue /></SelectTrigger>
      <SelectContent>
        {choices.map((codes) => {
          const bytes = codes.reduce((t, c) => t + (data.regions.languages[c].mb || 0) * 1e6, 0);
          return <SelectItem key={codes.join(',')} value={codes.join(',')}>{`${langName(data.regions, codes)} (${gb(bytes).replace('~', '')})`}</SelectItem>;
        })}
      </SelectContent>
    </Select>
  );
}

export function Preset({ value, children }) {
  const { state, dispatch } = use(Kit);
  return <button type="button" data-preset={value} aria-pressed={state.preset === value} onClick={() => dispatch({ type: 'preset', preset: value })}>{children}</button>;
}

export function Groups() {
  const { state, cards, dispatch } = use(Kit);
  const style = { display: 'flex', flexDirection: 'column', gap: '32px' };
  if (!state.data) {
    return <div id="groups" style={style}><p className="mono">{state.failed ? "Couldn't load the list of sources. Reload the page to try again." : 'Loading sources…'}</p></div>;
  }
  return (
    <div id="groups" style={style}>
      {[...new Set(cards.map((s) => s.group))].map((group) => {
        const items = cards.filter((s) => s.group === group);
        const on = items.filter((s) => state.picked[s.id]);
        const bytes = on.reduce((t, s) => t + (s.bytes || 0), 0);
        return (
          <div className="group" key={group}>
            <h3><span>{group}</span><span>{`${on.length} of ${items.length} · ${gb(bytes).replace('~', '')}`}</span></h3>
            <div className="cards">
              {(state.open[group] ? items : items.slice(0, VISIBLE)).map((s) => (
                <label className={state.picked[s.id] ? 'card' : 'card off'} key={s.id}>
                  <Checkbox className="mt-0.5" checked={!!state.picked[s.id]} onCheckedChange={(checked) => dispatch({ type: 'pick', id: s.id, on: checked === true })} aria-describedby={`why-${s.id}`} />
                  <span className="body">
                    <span className="row"><strong>{s.title}</strong><span className="size">{gb(s.bytes)}</span></span>
                    <span className="why" id={`why-${s.id}`}>{s.why}</span>
                  </span>
                </label>
              ))}
            </div>
            {items.length > VISIBLE && (
              <button type="button" className="more" onClick={() => dispatch({ type: 'more', group })}>{state.open[group] ? 'Show fewer' : `Show all ${items.length}`}</button>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function Total() {
  const { state, cards } = use(Kit);
  let text = 'YOUR KIT';
  if (state.data) {
    const on = cards.filter((s) => state.picked[s.id]);
    const unknown = on.filter((s) => s.bytes == null).length;
    text += ` · ABOUT ${Math.round(on.reduce((t, s) => t + (s.bytes || 0), 0) / 1e9)} GB`
      + (unknown ? ` + ${unknown} ${unknown === 1 ? 'SMALL ITEM' : 'SMALL ITEMS'}` : '');
  }
  return <div className="mono sum" id="totalText" aria-live="polite">{text}</div>;
}

// The picks as SETUP's options: the preset they started from (the recommended kit, or just the essentials),
// with --skip and --add for what's different.
function setupOptions(state, cards) {
  const base = state.from === 'essentials' ? 'essentials' : 'recommended';
  const on = (s) => !!state.picked[s.id];
  const inBase = (s) => s.presets.includes(base);
  const ids = (list) => list.map((s) => s.id);
  const wiki = cards.filter((s) => WIKI.test(s.id));
  const langs = wiki.filter(on).map((s) => s.id.split('_')[1]);
  const models = cards.filter((s) => s.group === 'AI models');
  const rest = cards.filter((s) => s.group !== 'AI models' && !WIKI.test(s.id));
  const skip = ids(rest.filter((s) => inBase(s) && !on(s)));
  const add = ids(rest.filter((s) => !inBase(s) && on(s)));
  if (wiki.some(inBase) && !langs.length) skip.unshift('wikipedia');
  if (!wiki.some(inBase) && langs.length) add.unshift('wikipedia');
  const opts = state.chosen ? ['--region ' + state.place.id, '--wikipedia ' + (langs.length ? langs : state.wiki).join(',')] : [];
  if (base === 'essentials') opts.push('--essentials');
  if (!models.some(on)) opts.push('--no-ai');
  else if (models.some((s) => on(s) !== inBase(s))) opts.push('--models ' + ids(models.filter(on)).join(','));
  if (skip.length) opts.push('--skip ' + skip.join(','));
  if (add.length) opts.push('--add ' + add.join(','));
  return opts;
}

function setupPrompt(state, cards) {
  const opts = setupOptions(state, cards);
  const gbs = Math.round(cards.filter((s) => state.picked[s.id]).reduce((t, s) => t + (s.bytes || 0), 0) / 1e9);
  return INSTALL_PROMPT + `\n\nI already picked what goes in with the kit builder on tinfoilkit.com. It comes to about ${gbs} GB`
    + (opts.length ? `. In the setup command, that's:\n${opts.join(' ')}\nUse those options as they are. ` : ', the recommended kit. ')
    + "Tell me if it won't fit my computer, and ask me only about the rest.";
}

export function CopySetup({ children }) {
  const { state, cards, showSetup } = use(Kit);
  function copy() {
    const text = setupPrompt(state, cards);
    copyText(text).then(() => toast('Copied. Paste it into ChatGPT, Claude or another AI chat.', 8000), () => {
      flushSync(() => showSetup(text));   // show it selected, so Cmd-C copies it
      selectNode(document.getElementById('setupText'));
      toast('Selected. Press Cmd-C (Ctrl-C on Windows) to copy.', 8000);
    });
  }
  return <button type="button" className="btn primary" id="copySetup" onClick={copy}>{children}</button>;
}

export function SetupText() {
  const { setupText } = use(Kit);
  return <pre id="setupText" hidden={setupText == null}>{setupText}</pre>;
}
