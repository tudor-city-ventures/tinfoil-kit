package main

// The kit's commands that change what goes in it, download it and check it: pick, fit, plan, sync, verify, status,
// search, pins and test.

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"math"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// ----------------------------------------------------------------------------- changing kit.json

// subFirst replaces the first match of re in s with what repl makes of it, as Python's re.sub(count=1) does.
func subFirst(re *regexp.Regexp, s string, repl func(m []string) string) (string, bool) {
	loc := re.FindStringSubmatchIndex(s)
	if loc == nil {
		return s, false
	}
	var groups []string
	for i := 0; i < len(loc); i += 2 {
		if loc[i] < 0 {
			groups = append(groups, "")
		} else {
			groups = append(groups, s[loc[i]:loc[i+1]])
		}
	}
	return s[:loc[0]] + repl(groups) + s[loc[1]:], true
}

func literal(text string) func([]string) string { return func([]string) string { return text } }

// setSetting changes one setting in kit.json (nil removes it), and leaves the rest of the file as it is.
func setSetting(root, key string, value any) {
	path := filepath.Join(dataDir(root), "kit.json")
	data, err := os.ReadFile(path)
	if err != nil {
		die(oserr(err))
	}
	text := string(data)
	val := dumpsLine(value)
	name := `"` + regexp.QuoteMeta(key) + `"\s*:\s*`
	now := `(?:true|false|null|-?[\d.]+|"(?:[^"\\]|\\.)*"|\[[^\[\]{}]*\])`
	var fresh string
	var n bool
	if value == nil { // with the comma and space after it, or before it if it's the last one
		fresh, n = subFirst(regexp.MustCompile(name+now+`\s*,\s*`), text, literal(""))
		if !n {
			fresh, _ = subFirst(regexp.MustCompile(`,\s*`+name+now), text, literal(""))
		}
	} else {
		fresh, n = subFirst(regexp.MustCompile(`(`+name+`)`+now), text, func(m []string) string { return m[1] + val })
		if !n { // a kit.json from before this setting: it goes first in "settings"
			fresh, _ = subFirst(regexp.MustCompile(`("settings"\s*:\s*\{)(\s*)`), text, func(m []string) string {
				return m[1] + m[2] + `"` + key + `": ` + val + "," + m[2]
			})
		}
	}
	ok := false
	if v, err := parseJSON([]byte(fresh)); err == nil {
		if o, isObj := v.(*obj); isObj {
			got, has := o.child("settings").lookup(key)
			ok = pyEqual(got, value) && (has || value == nil)
		}
	}
	if !ok {
		cfg, err := parseObj(data)
		if err != nil {
			die(oserr(err))
		}
		s := cfg.child("settings")
		if s == nil {
			s = newObj()
			cfg.set("settings", s)
		}
		if value == nil {
			s.del(key)
		} else {
			s.set(key, value)
		}
		fresh = dumps(cfg, jsonStyle{indent: 2, ascii: true}) + "\n"
	}
	tmp := filepath.Join(dataDir(root), "kit.tmp")
	if err := os.WriteFile(tmp, []byte(fresh), 0o644); err != nil {
		die(oserr(err))
	}
	if err := replace(tmp, path); err != nil {
		die(oserr(err))
	}
}

// partKeys is what names an entry in each part of kit.json.
var partKeys = [][2]string{{"models", "id"}, {"library", "zim"}, {"extras", "id"}}

func partKey(section string) string {
	for _, p := range partKeys {
		if p[0] == section {
			return p[1]
		}
	}
	return ""
}

// A part of the kit: ("models", "gemma-3-4b"), ("library", "wikipedia_en_all_maxi"), or ("maps", "maps").
type entry struct{ section, id string }

type partChange struct {
	part entry
	on   bool
}

// changes is a dict of parts to on or off that keeps the order they came in.
type changes []partChange

func (c *changes) set(p entry, on bool) {
	for i := range *c {
		if (*c)[i].part == p {
			(*c)[i].on = on
			return
		}
	}
	*c = append(*c, partChange{p, on})
}

func (c changes) get(p entry) (bool, bool) {
	for _, x := range c {
		if x.part == p {
			return x.on, true
		}
	}
	return false, false
}

// jsonKey is one kit.json entry's text with key set to value (true or false), or taken out (nil), keeping its layout.
func jsonKey(o, key string, value any) string {
	pat := `"` + key + `"\s*:\s*(?:true|false)\b`
	if value == nil {
		s, _ := subFirst(regexp.MustCompile(`,\s*`+pat+`|`+pat+`\s*,\s*`), o, literal(""))
		return s
	}
	val := dumpsLine(value)
	if re := regexp.MustCompile(pat); re.MatchString(o) {
		s, _ := subFirst(re, o, literal(`"`+key+`": `+val))
		return s
	}
	gap := " " // an entry on one line gets one space
	if sep := regexp.MustCompile(`,(\s*)"`).FindStringSubmatch(o); sep != nil && strings.Contains(sep[1], "\n") {
		gap = sep[1]
	}
	if note := regexp.MustCompile(`"note"\s*:`).FindStringIndex(o); note != nil {
		return o[:note[0]] + `"` + key + `": ` + val + "," + gap + o[note[0]:]
	}
	body := strings.TrimRightFunc(o[:len(o)-1], isSpace)
	return body + "," + gap + `"` + key + `": ` + val + o[len(body):]
}

// isSpace is what Python's strip() takes off.
func isSpace(r rune) bool { return unicode.IsSpace(r) || r >= 0x1c && r <= 0x1f }

// switchParts switches models, books, extras or the map (("maps", "maps")) on or off in kit.json, and marks the ones
// in essential "essential": true (see essential()), changing only those keys so the file keeps its layout. On is no
// "enabled" at all, since that's the default.
func switchParts(root string, ch changes, essential []entry) {
	path := filepath.Join(dataDir(root), "kit.json")
	data, err := os.ReadFile(path)
	if err != nil {
		die(oserr(err))
	}
	text := string(data)
	cfg, err := parseObj(data)
	if err != nil {
		die(oserr(err))
	}
	type edit struct {
		part  entry
		name  string
		value any
	}
	var edits []edit
	for _, c := range ch {
		var v any
		if !c.on {
			v = false
		}
		edits = append(edits, edit{c.part, "enabled", v})
	}
	for _, p := range essential {
		if p.section != "maps" { // the map always is
			edits = append(edits, edit{p, "essential", true})
		}
	}
	for _, e := range edits {
		if e.part.section == "maps" {
			m := cfg.child("maps")
			if m == nil {
				m = newObj()
				cfg.set("maps", m)
			}
			m.set("enabled", e.value == nil)
			text, _ = subFirst(regexp.MustCompile(`("maps"\s*:\s*\{[^{}]*?"enabled"\s*:\s*)(?:true|false)\b`), text,
				func(g []string) string { return g[1] + dumpsLine(e.value == nil) })
			continue
		}
		key := partKey(e.part.section)
		for _, x := range cfg.objs(e.part.section) {
			if pyEqual(x.get(key), e.part.id) {
				if e.value == nil {
					x.del(e.name)
				} else {
					x.set(e.name, e.value)
				}
			}
		}
		start := regexp.MustCompile(`"` + e.part.section + `"\s*:\s*\[`).FindStringIndex(text)
		if start == nil {
			continue
		}
		hitRE := regexp.MustCompile(`\{[^{}]*"` + key + `"\s*:\s*` + regexp.QuoteMeta(dumpsLine(e.part.id)) + `[^{}]*\}`)
		if hit := hitRE.FindStringIndex(text[start[1]:]); hit != nil {
			a, b := start[1]+hit[0], start[1]+hit[1]
			text = text[:a] + jsonKey(text[a:b], e.name, e.value) + text[b:]
		}
	}
	if v, err := parseJSON([]byte(text)); err != nil || !pyEqual(v, cfg) { // a layout this doesn't know: write it plainly
		text = dumps(cfg, jsonStyle{indent: 2}) + "\n"
	}
	tmp := filepath.Join(dataDir(root), "kit.json.partial")
	if err := os.WriteFile(tmp, []byte(text), 0o644); err != nil {
		die(oserr(err))
	}
	if err := replace(tmp, path); err != nil {
		die(oserr(err))
	}
}

func switchModels(root string, ids []string, on bool) {
	var ch changes
	for _, i := range ids {
		ch.set(entry{"models", i}, on)
	}
	switchParts(root, ch, nil)
}

// partIDs is the names of the entries in each part of kit.json.
func partIDs(cfg *obj) map[string][]string {
	ids := map[string][]string{}
	for _, p := range partKeys {
		ids[p[0]] = []string{}
		for _, e := range cfg.objs(p[0]) {
			if s, ok := e.get(p[1]).(string); ok {
				ids[p[0]] = append(ids[p[0]], s)
			}
		}
	}
	return ids
}

// findParts is what a name in ./kit pick means: a whole part (models, library, extras, maps), one model, book or
// extra, or every book whose name, up to its first underscore, is it ("wikipedia": Wikipedia in whichever language) or
// has it between dots ("stackexchange": every Stack Exchange site, "libretexts": every LibreTexts book).
func findParts(cfg *obj, word string) []entry {
	w := strings.ToLower(strings.TrimSpace(word))
	ids := partIDs(cfg)
	if w == "maps" {
		return []entry{{"maps", "maps"}}
	}
	if list, ok := ids[w]; ok {
		var out []entry
		for _, i := range list {
			out = append(out, entry{w, i})
		}
		return out
	}
	var out []entry
	for _, p := range partKeys {
		for _, i := range ids[p[0]] {
			if strings.ToLower(i) == w {
				out = append(out, entry{p[0], i})
			}
		}
	}
	if len(out) > 0 || w == "" {
		return out
	}
	for _, z := range ids["library"] {
		first := strings.SplitN(strings.ToLower(z), "_", 2)[0]
		if first == w || contains(strings.Split(first, "."), w) {
			out = append(out, entry{"library", z})
		}
	}
	return out
}

var presets = [][3]string{
	{"recommended", "Recommended", "what we'd take"},
	{"essentials", "Essentials", "the AI, the medical, preparedness and repair books, the map, and Wikipedia's best articles"},
	{"everything", "Everything", "every AI model and book, the biggest collections too"},
	{"no-ai", "No AI", "the books and the map"},
}

// readLine is one answer from stdin, read a byte at a time: a script feeding SETUP its answers from a file or pipe
// keeps the lines after it for the prompts that come later. Ctrl-C stops the kit while it waits.
func readLine() string {
	said := make(chan string, 1)
	go func() {
		var b []byte
		one := make([]byte, 1)
		for {
			n, err := os.Stdin.Read(one)
			if n == 0 || err != nil || one[0] == '\n' {
				break
			}
			b = append(b, one[0])
		}
		said <- strings.TrimSpace(strings.ToValidUTF8(string(b), "�"))
	}()
	select {
	case s := <-said:
		return s
	case <-stopping:
		panic(interrupted{})
	}
}

// ask prints a question and reads the answer, as Python's input() did.
func ask(question string) string {
	out(question)
	return readLine()
}

func names(ids []string) string {
	if len(ids) == 1 {
		return ids[0]
	}
	return strings.Join(ids[:len(ids)-1], ", ") + " and " + ids[len(ids)-1]
}

var answerWords = regexp.MustCompile(`[,\s]+`)

// askPicks is ./kit pick --ask: the kit builder's choices on tinfoilkit.com (site/sources.json), asked in a terminal.
// A preset, or each part. The AI in a preset is one this computer runs, and Essentials takes a smaller Wikipedia
// (wikiPreset), as the builder does.
func askPicks(root string) {
	listed, ok := sourcesList(root)
	if !ok {
		die("The kit builder's list (site/sources.json) isn't in this kit. Choose with ./kit pick --skip and --add.")
	}
	cfg := rawConfig(root)
	ids := partIDs(cfg)
	var wikis []string
	for _, z := range ids["library"] {
		if wikipediaRE.MatchString(z) {
			wikis = append(wikis, z)
		}
	}
	parts := func(src *obj) []entry {
		id := pyStr(src.get("id"))
		if id == "maps" {
			return []entry{{"maps", "maps"}}
		}
		var out []entry
		if wikipediaRE.MatchString(id) { // in the place's language
			for _, w := range wikis {
				out = append(out, entry{"library", w})
			}
			return out
		}
		for _, s := range []string{"models", "library"} {
			if contains(ids[s], id) {
				out = append(out, entry{s, id})
			}
		}
		return out
	}
	var sources []*obj
	var ai []string
	for _, s := range listed {
		if len(parts(s)) > 0 {
			sources = append(sources, s)
			if pyEqual(s.get("group"), "AI models") {
				ai = append(ai, pyStr(s.get("id")))
			}
		}
	}
	every := copyOf(cfg).(*obj)
	for _, m := range every.objs("models") {
		m.del("enabled")
	}
	type fit struct {
		fits  bool
		bytes int64
	}
	fitsOf := map[string]fit{}
	for _, m := range fitReport(root, every, loadState(root)).objs("models") {
		fitsOf[pyStr(m.get("id"))] = fit{truthy(m.get("fits")), intOr(orZero(m.get("bytes")), 0)}
	}
	isOn := func(c *obj, p entry) any {
		if p.section == "maps" {
			return truthy(mapsSettings(c).get("enabled"))
		}
		for _, e := range c.objs(p.section) {
			if pyEqual(e.get(partKey(p.section)), p.id) {
				return e.getOr("enabled", true)
			}
		}
		return false
	}
	applied := func(picked map[string]bool) changes {
		var out changes
		for _, s := range sources {
			for _, p := range parts(s) {
				out.set(p, picked[pyStr(s.get("id"))])
			}
		}
		return out
	}
	now := wikipediaEdition(cfg)
	smaller := func(key string) string { // the edition a preset takes Wikipedia down to, if it's bigger now
		e := wikiSize(wikiPreset[key])
		if e != "" && now != "" && editionIndex(now) > editionIndex(e) {
			return e
		}
		return ""
	}
	gb := func(picked map[string]bool, edition string) int64 {
		c := copyOf(cfg).(*obj)
		for _, x := range applied(picked) {
			if x.part.section == "maps" {
				m := c.child("maps")
				if m == nil {
					m = newObj()
					c.set("maps", m)
				}
				m.set("enabled", x.on)
				continue
			}
			for _, e := range c.objs(x.part.section) {
				if pyEqual(e.get(partKey(x.part.section)), x.part.id) {
					e.set("enabled", x.on)
				}
			}
		}
		if edition != "" {
			lib, _ := c.getOr("library", []any{}).([]any)
			c.set("library", withWikipedia(lib, nil, edition))
		}
		return int64(math.Ceil(estimateBytes(root, c, &no, nil, false) / GB))
	}
	preset := func(key string) map[string]bool {
		picked := map[string]bool{}
		for _, s := range sources {
			picked[pyStr(s.get("id"))] = containsAny(s.list("presets"), key)
		}
		var chosen []string
		for _, i := range ai {
			if picked[i] {
				chosen = append(chosen, i)
			}
		}
		anyFits := false
		for _, i := range chosen {
			f, known := fitsOf[i]
			anyFits = anyFits || !known || f.fits
		}
		if len(chosen) > 0 && !anyFits { // none of them runs here
			pick := ""
			for _, i := range ai {
				if f := fitsOf[i]; f.fits && (pick == "" || f.bytes > fitsOf[pick].bytes) {
					pick = i
				}
			}
			if pick == "" {
				for _, i := range ai {
					if pick == "" || fitsOf[i].bytes < fitsOf[pick].bytes {
						pick = i
					}
				}
			}
			for _, i := range chosen {
				picked[i] = false
			}
			picked[pick] = true
		}
		return picked
	}
	log("\nWhat goes in the kit? The same choices as the kit builder on tinfoilkit.com:")
	for n, p := range presets {
		log(fmt.Sprintf("  %d  %s: %s. About %d GB.", n+1, p[1], p[2], gb(preset(p[0]), smaller(p[0]))))
	}
	log(fmt.Sprintf("  %d  Choose each part", len(presets)+1))
	var said string
	for {
		said = ask(fmt.Sprintf("\nType a number, or press %s for 1: ", returnKey))
		if n, err := strconv.Atoi(said); said == "" || err == nil && n >= 1 && n <= len(presets)+1 && strconv.Itoa(n) == said {
			break
		}
		out(fmt.Sprintf("Type a number from 1 to %d.", len(presets)+1))
	}
	n := 1
	if said != "" {
		n, _ = strconv.Atoi(said)
	}
	var picked map[string]bool
	if n <= len(presets) {
		picked = preset(presets[n-1][0])
	} else {
		picked = map[string]bool{}
		for _, s := range sources {
			all := true
			for _, p := range parts(s) {
				all = all && truthy(isOn(cfg, p))
			}
			picked[pyStr(s.get("id"))] = all
		}
		for {
			var group any = nil
			first := true
			for i, s := range sources {
				if first || !pyEqual(s.get("group"), group) {
					first = false
					group = s.get("group")
					log("\n  " + pyStr(group))
				}
				id := pyStr(s.get("id"))
				title, size := pyStr(s.getOr("title", s.get("id"))), fmtSizeAny(s.get("bytes"))
				if wikipediaRE.MatchString(id) { // the kit's own: its languages and size
					t, rest, _ := strings.Cut("Wikipedia: "+describeWikipedia(cfg), " (about ")
					title, size = t, strings.TrimRight(rest, ")")
					if size == "" {
						size = "?"
					}
				}
				mark := " "
				if picked[id] {
					mark = "x"
				}
				log(fmt.Sprintf("  %3d  [%s] %s (%s)", i+1, mark, title, size))
			}
			took := eta(root, float64(gb(picked, "")*GB))
			if took != "" {
				took = ", " + took
			}
			log(fmt.Sprintf("\nIn all: about %d GB%s.", gb(picked, ""), took))
			said = ask(fmt.Sprintf("Type numbers to switch them on or off (like 3 12), or press %s when it's right: ", returnKey))
			if said == "" {
				break
			}
			for _, w := range answerWords.Split(said, -1) {
				if k, err := strconv.Atoi(w); err == nil && allDigits(w) && k >= 1 && k <= len(sources) {
					id := pyStr(sources[k-1].get("id"))
					picked[id] = !picked[id]
				}
			}
		}
	}
	var ch changes
	for _, x := range applied(picked) {
		if !pyEqual(isOn(cfg, x.part), x.on) {
			ch.set(x.part, x.on)
		}
	}
	if len(ch) > 0 {
		switchParts(root, ch, nil)
	}
	if n <= len(presets) && smaller(presets[n-1][0]) != "" {
		log("Wikipedia: " + describeWikipedia(setRegion(root, nil, nil, smaller(presets[n-1][0]))) + ".")
	}
}

// fmtSizeAny is fmt_size of a size from JSON, which may be null.
func fmtSizeAny(v any) string {
	if v == nil {
		return "?"
	}
	f, _ := asNumber(v)
	return fmtSize(f)
}

// cmdPick is what goes in the kit: SETUP's --no-ai, --models, --skip and --add, for setting it up with one command,
// or --ask for the kit builder's questions. Checks every name before it changes anything. Without options, says what's
// on, its size and the time to download it.
func cmdPick(root string, a *cliArgs) {
	if a.flag("ask") {
		askPicks(root)
	}
	cfg := rawConfig(root)
	var models []string
	for _, m := range cfg.objs("models") {
		if m.has("id") {
			models = append(models, pyStr(m.get("id")))
		}
	}
	var ch changes
	var named []entry // comes even with just the essentials, since it was asked for
	want := func(list string, on bool, section string) []string {
		var missing []string
		for _, name := range answerWords.Split(list, -1) {
			var hits []entry
			if name != "" {
				for _, h := range findParts(cfg, name) {
					if section == "" || h.section == section {
						hits = append(hits, h)
					}
				}
			}
			if name != "" && len(hits) == 0 {
				missing = append(missing, name)
			}
			for _, h := range hits {
				ch.set(h, on)
			}
			if on {
				named = append(named, hits...)
			}
		}
		return missing
	}
	if a.flag("no_ai") || a.str("models") != "" {
		for _, m := range models {
			ch.set(entry{"models", m}, false)
		}
	}
	if notModels := want(a.str("models"), true, "models"); len(notModels) > 0 {
		die(fmt.Sprintf("No AI model is called %s. The models: %s.", names(notModels), strings.Join(models, ", ")), 2)
	}
	unknown := append(want(a.str("skip"), false, ""), want(a.str("add"), true, "")...)
	if len(unknown) > 0 {
		var books, extras []string
		for _, z := range cfg.objs("library") {
			if z.has("zim") {
				books = append(books, pyStr(z.get("zim")))
			}
		}
		for _, e := range cfg.objs("extras") {
			if e.has("id") {
				extras = append(extras, pyStr(e.get("id")))
			}
		}
		die(fmt.Sprintf("Nothing in the kit is called %s. AI models: %s. Books: %s. Extras: %s. Also maps, or a whole "+
			"part: models, library, extras.", names(unknown), strings.Join(models, ", "), strings.Join(books, ", "),
			strings.Join(extras, ", ")), 2)
	}
	before := loadConfig(root)
	if a.flag("ask") || a.flag("no_ai") || a.str("models") != "" || a.str("skip") != "" || a.str("add") != "" {
		setSetting(root, "picked", true) // SETUP asks what goes in only until someone has said
	}
	if len(ch) > 0 {
		var ess []entry
		for _, h := range named {
			if on, _ := ch.get(h); on {
				ess = append(ess, h)
			}
		}
		switchParts(root, ch, ess)
		// A model someone picks, or leaves out, by name isn't one to offer back on a computer with more memory.
		skipped := before.child("settings").list("models_off_for_memory")
		var keep []any
		for _, m := range skipped {
			if _, named := ch.get(entry{"models", pyStr(m)}); !named {
				keep = append(keep, m)
			}
		}
		if len(keep) != len(skipped) {
			if len(keep) == 0 {
				setSetting(root, "models_off_for_memory", nil)
			} else {
				setSetting(root, "models_off_for_memory", keep)
			}
		}
	}
	cfg = loadConfig(root)
	on := func(section, key string) []string {
		var out []string
		for _, e := range cfg.objs(section) {
			if e.on() {
				out = append(out, pyStr(e.get(key)))
			}
		}
		return out
	}
	off := func(section, key string) string {
		var out []string
		for _, e := range cfg.objs(section) {
			if !e.on() {
				out = append(out, pyStr(e.get(key)))
			}
		}
		if len(out) == 0 {
			return ""
		}
		more := ""
		if len(out) > 6 {
			more = fmt.Sprintf(" and %d more", len(out)-6)
		}
		return " Off: " + strings.Join(out[:min(6, len(out))], ", ") + more + "."
	}
	orNone := func(l []string) string {
		if len(l) == 0 {
			return "none"
		}
		return strings.Join(l, ", ")
	}
	log("AI models: " + orNone(on("models", "id")) + ".")
	log("Maps: " + map[bool]string{true: "on", false: "off"}[truthy(mapsSettings(cfg).get("enabled"))] + ".")
	log(fmt.Sprintf("Books: %d of %d.%s", len(on("library", "zim")), len(cfg.list("library")), off("library", "zim")))
	if truthy(cfg.get("extras")) {
		log("Extras: " + orNone(on("extras", "id")) + ".")
	}
	log(fmt.Sprintf("All of it is about %d GB; just the essentials, about %d GB.", estimateGB(root, cfg, &no, nil, false),
		estimateGB(root, cfg, &yes, nil, false)))
	if stateItems(loadState(root)).size() > 0 {
		ess := isTrue(cfg.child("settings").get("essentials_only"))
		left := estimateBytes(root, cfg, &ess, nil, true)
		took := eta(root, left)
		if took != "" {
			took = ", " + took
		}
		log(fmt.Sprintf("To download: about %d GB%s.", int64(math.Ceil(left/GB)), took))
	}
}

// cmdFit: --ask reads the answers from stdin even when it isn't a terminal, so SETUP's tests can answer.
// cmdRemove deletes what items downloaded, for their space, and switches them off so sync doesn't get them again.
// Names are pick's (an id, a book's name up to its first underscore, maps, or a whole part), or anything ./kit status
// lists. Asks first at a keyboard; elsewhere, --yes says go ahead.
func cmdRemove(root string, a *cliArgs) {
	cfg := rawConfig(root)
	freed, failed, switched := func() (int64, []string, bool) {
		defer lockKit(root)()
		state := loadState(root)
		items := stateItems(state)
		var parts []entry
		var unknown []string
		for _, name := range answerWords.Split(strings.Join(a.list("names"), " "), -1) {
			if name == "" {
				continue
			}
			hits := findParts(cfg, name)
			if len(hits) == 0 {
				for _, k := range items.Keys() {
					if s, id, _ := strings.Cut(k, "/"); s != "runtimes" && strings.EqualFold(id, name) {
						hits = append(hits, entry{s, id})
					}
				}
			}
			if len(hits) == 0 {
				unknown = append(unknown, name)
			}
			for _, h := range hits {
				if !containsEntry(parts, h) {
					parts = append(parts, h)
				}
			}
		}
		if len(unknown) > 0 {
			die(fmt.Sprintf("Nothing in the kit is called %s. ./kit status lists what it has.", names(unknown)), 2)
		}
		maps := containsEntry(parts, entry{"maps", "maps"})
		wanted := map[string]bool{}
		for _, p := range parts {
			wanted[p.section+"/"+p.id] = true
		}
		var keys []string
		for _, k := range sortedKeys(items) {
			if wanted[k] || maps && strings.HasPrefix(k, "maps/") {
				keys = append(keys, k)
				wanted[k] = true
			}
		}
		dl := dlDir(root)
		partials := state.child("partials")
		var unfinished []string
		for _, rel := range sortedKeys(partials) {
			item := pyStr(partials.child(rel).get("item"))
			if wanted[item] || maps && strings.HasPrefix(item, "maps/") {
				unfinished = append(unfinished, rel)
			}
		}
		for _, p := range parts {
			if p.section != "library" {
				continue
			}
			named := regexp.MustCompile(`^` + regexp.QuoteMeta(p.id) + `_\d{4}-\d{2}\.zim\.partial$`)
			for _, f := range filesIn(filepath.Join(dl, "library"), "*.partial") {
				if rel := "library/" + filepath.Base(f); named.MatchString(filepath.Base(f)) && !contains(unfinished, rel) {
					unfinished = append(unfinished, rel)
				}
			}
		}
		sizes := map[string]int64{}
		var total int64
		for _, k := range keys {
			sizes[k] = driveBytes(items.child(k))
			total += sizes[k]
		}
		var found []string
		for _, rel := range unfinished {
			if st, err := os.Stat(filepath.Join(dl, filepath.FromSlash(rel))); err == nil && st.Mode().IsRegular() {
				found = append(found, rel)
				sizes[rel] = st.Size()
				total += st.Size()
			}
		}
		unfinished = found
		var ch changes
		for _, p := range parts {
			if p.section == "maps" {
				ch.set(p, false)
				continue
			}
			for _, e := range cfg.objs(p.section) {
				if key := partKey(p.section); key != "" && pyEqual(e.get(key), p.id) {
					ch.set(p, false)
					break
				}
			}
		}
		if len(sizes) == 0 {
			var ids []string
			for _, p := range parts {
				ids = append(ids, p.id)
			}
			if len(ch) > 0 {
				switchParts(root, ch, nil)
				setSetting(root, "picked", true)
			}
			said := names(ids) + " isn't in the kit, so there's nothing to delete. "
			if len(ch) > 0 {
				said += "It's switched off now, so sync won't get it."
			}
			log(said)
			exit(0)
		}
		log("This deletes:")
		for _, k := range keys {
			_, id, _ := strings.Cut(k, "/")
			log("  " + padRight(clip(id, 44), 46) + padLeft(fmtSize(float64(sizes[k])), 9))
		}
		for _, rel := range unfinished {
			log("  " + padRight(clip(rel, 44), 46) + padLeft(fmtSize(float64(sizes[rel])), 9) + "   (unfinished download)")
		}
		if !a.flag("yes") {
			if !isTerminal(os.Stdin) {
				log("Nothing is deleted yet. To delete it, run this again with --yes.")
				exit(1)
			}
			out(fmt.Sprintf("Delete it (%s)? [y/N] ", fmtSize(float64(total))))
			if ans := strings.ToLower(readLine()); ans != "y" && ans != "yes" {
				log("Nothing changed.")
				exit(0)
			}
		}
		if len(ch) > 0 {
			switchParts(root, ch, nil)
			setSetting(root, "picked", true) // chosen: SETUP doesn't ask what goes in again
		}
		var freed int64
		var failed []string
		for _, k := range keys {
			v := items.child(k)
			dest := v.str("dest")
			// a model's or a map's own folder goes whole; a folder it shares with others (library), just its files
			own := strings.Contains(strings.Trim(dest, "/"), "/")
			for _, j := range items.Keys() {
				if d := items.child(j).str("dest"); j != k && (d == dest || strings.HasPrefix(d, dest+"/")) {
					own = false
				}
			}
			var err error
			if own {
				err = os.RemoveAll(filepath.Join(dl, filepath.FromSlash(dest)))
			} else {
				for _, name := range v.child("files").Keys() {
					if e := os.Remove(filepath.Join(dl, filepath.FromSlash(dest), name)); e != nil && !errors.Is(e, os.ErrNotExist) {
						err = e
					}
				}
				if b := v.str("binary"); b != "" && err == nil {
					if e := os.Remove(filepath.Join(dl, filepath.FromSlash(b))); e != nil && !errors.Is(e, os.ErrNotExist) {
						err = e
					}
				}
			}
			if err != nil { // open in the kit, on Windows
				_, id, _ := strings.Cut(k, "/")
				failed = append(failed, id+" ("+oserr(err)+")")
				continue
			}
			items.del(k)
			freed += sizes[k]
		}
		for _, rel := range unfinished {
			dropPartial(filepath.Join(dl, filepath.FromSlash(rel)))
			if partials != nil {
				partials.del(rel)
			}
			freed += sizes[rel]
		}
		saveState(root, state)
		writeInventory(root, state)
		return freed, failed, len(ch) > 0
	}()
	said := "Freed " + fmtSize(float64(freed)) + "."
	if switched {
		said += " It's switched off in kit.json; ./kit pick --add NAME brings it back."
	}
	log(said)
	if len(failed) > 0 {
		die("Couldn't delete " + names(failed) + ". Close the kit, then run this again")
	}
}

func containsEntry(list []entry, e entry) bool {
	for _, x := range list {
		if x == e {
			return true
		}
	}
	return false
}

func cmdFit(root string, a *cliArgs) {
	cfg, state := loadConfig(root), loadState(root)
	fit := fitReport(root, cfg, state)
	if a.flag("json") {
		out(dumps(fit, jsonStyle{indent: 2, ascii: true}) + "\n")
		return
	}
	if !truthy(fit.get("runs")) {
		log("No AI model is switched on in kit.json.")
		return
	}
	memory := intOr(fit.get("memory_bytes"), 0)
	if memory == 0 {
		log(fmt.Sprintf("\nThe kit can't tell how much memory %s has. Its AI will be %s if that fits.", this, pyStr(fit.get("runs"))))
		return
	}
	answer := func(question string, def bool) bool {
		hint := "[y/N]"
		if def {
			hint = "[Y/n]"
		}
		said := strings.ToLower(ask("\n" + question + " " + hint + " "))
		if said == "" {
			return def
		}
		return said == "y" || said == "yes"
	}
	downloads := func(ids []string) string {
		var total int64
		for _, m := range fit.objs("models") {
			if contains(ids, pyStr(m.get("id"))) {
				total += intOr(m.get("bytes"), 0)
			}
		}
		return fmtBytes(total) + " of downloads"
	}
	gb := fmt.Sprintf("%s has %d GB of memory", strings.ToUpper(this[:1])+this[1:], int64(pyRound(float64(memory)/(1<<30))))
	offForMemory := func() []string { return strs(cfg.child("settings").list("models_off_for_memory")) }
	if back := strs(fit.list("fits_now")); len(back) > 0 {
		log(fmt.Sprintf("\n%s. It can run %s, skipped before on a computer with less memory (%s).", gb, names(back), downloads(back)))
		if a.flag("restore") || (a.flag("ask") && answer("Download them now?", true)) {
			switchModels(root, back, true)
			var left []string
			for _, m := range uniqueSorted(offForMemory()) {
				if !contains(back, m) {
					left = append(left, m)
				}
			}
			if len(left) == 0 {
				setSetting(root, "models_off_for_memory", nil)
			} else {
				setSetting(root, "models_off_for_memory", anyList(left))
			}
			log("Switched them back on.")
			cfg = loadConfig(root)
			fit = fitReport(root, cfg, state)
		} else if !a.flag("ask") {
			log("To get them: ./kit fit --restore")
		}
		log("Its AI will be " + pyStr(fit.get("runs")) + ".")
	} else {
		log(fmt.Sprintf("\n%s, so its AI will be %s.", gb, pyStr(fit.get("runs"))))
	}
	for _, m := range fit.objs("models") {
		if pyEqual(m.get("id"), fit.get("runs")) {
			if !truthy(m.get("fits")) {
				log("That's the smallest, and it still needs most of the memory: close other apps before asking it something.")
			}
			break
		}
	}
	big := strs(fit.list("too_big"))
	if len(big) == 0 {
		return
	}
	need := int64(math.MaxInt64)
	for _, m := range fit.objs("models") {
		if contains(big, pyStr(m.get("id"))) {
			need = min(need, intOr(m.get("needs_memory_gb"), 0))
		}
	}
	verb := "they need"
	if len(big) == 1 {
		verb = "it needs"
	}
	log(fmt.Sprintf("It can't run %s: %s %d GB of memory or more (%s).", names(big), verb, need, downloads(big)))
	if !onThisComputer(root) {
		log("A computer with more memory could, with this drive plugged in.")
	}
	var asked []string
	for _, i := range big {
		for _, m := range cfg.objs("models") {
			if pyEqual(m.get("id"), i) && isTrue(m.get("essential")) {
				asked = append(asked, i)
				break
			}
		}
	}
	if a.flag("skip") && len(asked) > 0 { // nobody is answering, and these were asked for by name
		verb := "come"
		if len(asked) == 1 {
			verb = "comes"
		}
		log(fmt.Sprintf("%s %s anyway, as asked.", names(asked), verb))
		var rest []string
		for _, i := range big {
			if !contains(asked, i) {
				rest = append(rest, i)
			}
		}
		if big = rest; len(big) == 0 {
			return
		}
	}
	if a.flag("skip") || (a.flag("ask") && !answer("Download them anyway?", false)) {
		switchModels(root, big, false)
		setSetting(root, "models_off_for_memory", anyList(uniqueSorted(append(offForMemory(), big...))))
		log("Skipped them. On a computer with more memory, SETUP offers them again.")
	} else if !a.flag("ask") {
		log("To skip them: ./kit fit --skip")
	}
}

// uniqueSorted is sorted(set(l)).
func uniqueSorted(l []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range l {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}

func anyList(l []string) []any {
	out := []any{}
	for _, s := range l {
		out = append(out, s)
	}
	return out
}

// ----------------------------------------------------------------------------- plan, sync, verify, status

func cmdPlan(root string, a *cliArgs) {
	cfg, state := loadConfig(root), loadState(root)
	if a.flag("json") {
		planJSON(root, cfg, a.list("only"))
		return
	}
	starter, essentials := tier(cfg, a.flag("essentials"), a.flag("starter"))
	items := buildPlan(root, cfg, state, a.list("only"), essentials, starter)
	printPlan(root, items, state, cfg)
	if offline(items) {
		exit(1)
	}
	pending := 0
	for _, i := range items {
		if i.enabled() && (i.status == "new" || i.status == "update") {
			pending++
		}
	}
	if pending > 0 {
		log(fmt.Sprintf("\n%d item(s) to download. Run ./kit sync to do it.", pending))
	} else {
		log("\nEverything is up to date.")
	}
}

// planJSON prints the full download size of every item, disabled ones included, as JSON on stdout. Feeds the
// website's kit builder (site/build_sources.py). Downloads nothing.
func planJSON(root string, cfg *obj, only []string) {
	cfg = copyOf(cfg).(*obj)
	for _, section := range []string{"models", "library", "extras"} {
		for _, e := range cfg.objs(section) {
			e.set("enabled", true)
		}
	}
	m := cfg.child("maps")
	if m == nil {
		m = newObj()
		cfg.set("maps", m)
	}
	m.set("enabled", true)
	stdout := os.Stdout
	os.Stdout = os.Stderr // what it says along the way goes to stderr, so stdout is just the JSON
	items := func() []*item {
		defer func() { os.Stdout = stdout }()
		return buildPlan(root, cfg, newObj("items", newObj()), only, false, false)
	}()
	res := newObj()
	for _, i := range items {
		if !i.enabled() {
			continue
		}
		var total int64
		some, estimated := false, false
		for _, f := range i.files {
			size := f.size
			if size == 0 {
				size = f.estimate
			}
			if size != 0 {
				some = true
				total += size
			}
			estimated = estimated || f.size == 0
		}
		var version, errText, bytes any
		if i.version != "" {
			version = i.version
		}
		if i.err != "" {
			errText = i.err
		}
		if some {
			bytes = total
		}
		res.set(i.key(), newObj("version", version, "error", errText, "bytes", bytes, "estimated", estimated))
	}
	out(dumps(res, jsonStyle{indent: 1, sortKeys: true, ascii: true}) + "\n")
}

var pinsReadme = []any{"The exact build of each program this version of the kit installs, and its SHA-256. ./kit pins writes it,",
	"and every release carries it, signed with the rest. To take each program's newest build instead, set",
	"\"pin_programs\": false in kit.json's settings."}

// cmdPins writes tools/pins.json: the newest build of every program kit.json lists, for every system, with its
// SHA-256 from its publisher, or from downloading it where the publisher gives none. Run before a release (a weekly
// workflow does it). A program that can't be looked up keeps its old pin, and so does one whose file changed under
// the same version, which also fails the command: a publisher shouldn't replace a file it has published.
func cmdPins(root string, a *cliArgs) {
	cfg := copyOf(loadConfig(root)).(*obj)
	cfg.child("settings").set("pin_programs", false)
	cfg.set("models", []any{})
	cfg.set("library", []any{})
	for _, e := range append(cfg.objs("runtimes"), cfg.objs("extras")...) {
		e.set("enabled", true)
	}
	maps := newObj()
	for _, k := range cfg.child("maps").Keys() {
		maps.set(k, cfg.child("maps").get(k))
	}
	maps.set("enabled", true)
	cfg.set("maps", maps)
	path := filepath.Join(appDir(root), "tools", "pins.json")
	old := newObj()
	if data, err := os.ReadFile(path); err == nil {
		if o, err := parseObj(data); err == nil {
			old = o
		}
	}
	pins := map[string]*obj{}
	var problems, changed []string
	// the plan's own lookup, so Photon is the release that opens the newest address database
	for _, it := range buildPlan(root, cfg, newObj("version", 1, "items", newObj()), nil, false, false) {
		if !it.enabled() || !contains(pinnedTypes, it.typ()) {
			continue
		}
		was := old.child(it.id)
		if was == nil {
			was = newObj()
		}
		err := func() error {
			if it.err != "" || len(it.files) == 0 {
				if it.err != "" {
					return errors.New(it.err)
				}
				return errors.New("nothing to download")
			}
			f := it.files[0]
			if it.typ() == "github_archive" { // GitHub can repack its archives, so only the commit is pinned
				last := f.url[strings.LastIndex(f.url, "/")+1:]
				pins[it.id] = newObj("version", strings.SplitN(last, ".", 2)[0])
				return nil
			}
			digest := f.sha256
			if digest == "" && f.sha256Sidecar {
				digest = fetchSHA256Sidecar(f.url)
			}
			if digest == "" && pyEqual(was.get("version"), it.version) && truthy(was.get("sha256")) {
				digest = pyStr(was.get("sha256")) // pinned before and its publisher gives no SHA-256: no need to download it again
			}
			if digest == "" {
				data, err := httpGet(f.url, 900, "")
				if err != nil {
					return err
				}
				for _, c := range f.checks {
					h := newHash(c[0])
					h.Write(data)
					if hex.EncodeToString(h.Sum(nil)) != strings.ToLower(c[1]) {
						return fmt.Errorf("the download doesn't match its published %s", c[0])
					}
				}
				sum := sha256.Sum256(data)
				digest = hex.EncodeToString(sum[:])
			}
			if pyEqual(was.get("version"), it.version) && strings.ToLower(pyStr(was.getOr("sha256", digest))) != strings.ToLower(digest) {
				changed = append(changed, it.id)
				return errors.New("the file published as " + it.version + " changed after it was pinned. Find out why " +
					"before you pin it again: delete its entry in tools/pins.json and run ./kit pins")
			}
			pins[it.id] = newObj("version", it.version, "sha256", strings.ToLower(digest))
			return nil
		}()
		if err != nil {
			problems = append(problems, "  "+it.id+": "+err.Error())
			if was.size() > 0 {
				pins[it.id] = was
			}
		}
		pinned := func(o *obj) string {
			if o.has("version") {
				return pyStr(o.get("version"))
			}
			return "not pinned"
		}
		if !pyEqual(was.get("version"), pins[it.id].get("version")) {
			log("  " + it.id + ": " + pinned(was) + " -> " + pinned(pins[it.id]))
		}
	}
	doc := newObj("_readme", pinsReadme)
	ids := make([]string, 0, len(pins))
	for id := range pins {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		doc.set(id, pins[id])
	}
	if err := os.WriteFile(path, []byte(dumps(doc, jsonStyle{indent: 1, ascii: true})+"\n"), 0o644); err != nil {
		die(oserr(err))
	}
	log(fmt.Sprintf("Pinned %d program builds in tools/pins.json.", len(pins)))
	if len(problems) > 0 {
		log("Couldn't pin these, so each keeps the pin it had, if any:\n" + strings.Join(problems, "\n"))
	}
	if len(changed) > 0 {
		fmt.Fprintf(os.Stderr, "A publisher replaced a file it had already published (%s). Don't release the kit until you "+
			"know why.\n", strings.Join(changed, ", "))
		exit(1)
	}
}

func cmdSync(root string, a *cliArgs) {
	os.MkdirAll(filepath.Join(dataDir(root), "logs"), 0o755)
	logFile = filepath.Join(dataDir(root), "logs", "sync-"+time.Now().Format("2006-01-02")+".log")
	log("\n===== sync started " + nowISO() + " =====")
	code := func() int {
		defer lockKit(root)()
		defer keepAwake()()
		os.MkdirAll(dlDir(root), 0o755)
		prepareFolder(root)
		cfg, state := loadConfig(root), loadState(root)
		starter, essentials := tier(cfg, a.flag("essentials"), a.flag("starter"))
		only := a.list("only")
		items := buildPlan(root, cfg, state, only, essentials, starter)
		part := len(only) > 0 || a.flag("essentials") || a.flag("starter") // just this once: the next full sync gets the rest
		printPlan(root, items, state, cfg)
		if offline(items) {
			exit(1)
		}
		var todo []*item
		need := map[*item]int64{}
		for _, i := range items {
			if i.enabled() && (i.status == "new" || i.status == "update") {
				todo = append(todo, i)
				need[i] = i.needBytes(root)
			}
		}
		sort.SliceStable(todo, func(x, y int) bool {
			if todo[x].priority() != todo[y].priority() {
				return todo[x].priority() < todo[y].priority()
			}
			return need[todo[x]] < need[todo[y]]
		})
		if len(todo) > 0 && !a.flag("yes") && isTerminal(os.Stdin) {
			if said := strings.ToLower(ask(fmt.Sprintf("\nDownload %d item(s) now? [Y/n] ", len(todo)))); said != "" && said != "y" && said != "yes" {
				return 0
			}
		}
		if !part && !starter { // (a try-it kit's plan doesn't list the rest, whose downloads stay)
			sweepPartials(root, state, items)
		}
		type failure struct{ key, msg string }
		var failures []failure
		var doneBytes int64
		start := time.Now()
		func() {
			defer func() {
				if r := recover(); r != nil {
					if _, ok := r.(interrupted); ok {
						noteSpeed(state)
						saveState(root, state)
						log("\nStopped. Everything finished so far is saved; run ./kit sync again to resume.")
						exit(130)
					}
					panic(r)
				}
			}()
			for n, it := range todo {
				log(fmt.Sprintf("\n[%d/%d] %s  (%s)", n+1, len(todo), it.key(), it.version))
				was := stateItems(state).child(it.key())
				sample := starter // (a try-it sync's new items are samples)
				if was.size() > 0 {
					sample = truthy(was.get("sample"))
				}
				got, err := installItem(root, it, state, cfg, a.flag("force"))
				if err == nil {
					doneBytes += got
					if rec := stateItems(state).child(it.key()); sample && rec != nil {
						rec.set("sample", true)
					}
				} else { // one bad item mustn't end a sync that runs for hours
					failures = append(failures, failure{it.key(), err.Error()})
					log("    FAILED: " + err.Error())
				}
				saveState(root, state)
			}
		}()
		noteSpeed(state)
		var errs []*item
		for _, i := range items {
			if i.enabled() && i.status == "error" {
				errs = append(errs, i)
			}
		}
		if !part {
			dropReplacedWikipedias(root, state, items, cfg)
		}
		if len(failures) == 0 && len(errs) == 0 && !part {
			state.set("last_sync", nowISO())
			if !starter {
				dropSamples(root, state, cfg, items)
			}
		}
		saveState(root, state)
		writeInventory(root, state)
		if _, err := buildPortal(root, cfg); err != nil {
			failures = append(failures, failure{"portal page", err.Error()})
		}
		if len(todo) > 0 {
			log(fmt.Sprintf("\nDownloaded %s in %s min.", fmtBytes(doneBytes), strconv.FormatFloat(time.Since(start).Minutes(), 'f', 0, 64)))
		} else if len(failures) == 0 && len(errs) == 0 {
			log("\nEverything is up to date.")
		}
		if len(failures) > 0 || len(errs) > 0 {
			log("\nProblems (everything else is done):")
			for _, f := range failures {
				log("  - " + f.key + ": " + f.msg)
			}
			for _, i := range errs {
				log("  - " + i.key() + ": " + i.err)
			}
			log("Re-run ./kit sync to retry. Fix or disable items in kit.json if they keep failing.")
		}
		if len(todo) > 0 {
			log("\nNow run ./kit test to check that everything starts.")
		}
		if len(failures) > 0 || len(errs) > 0 {
			return 1
		}
		return 0
	}()
	exit(code)
}

// installItem downloads and installs one item. A mistake in the kit itself fails that item, not the whole sync, as
// in kit.py.
func installItem(root string, it *item, state, cfg *obj, force bool) (n int64, err error) {
	defer func() {
		if r := recover(); r != nil {
			switch r.(type) {
			case interrupted, exitCode:
				panic(r)
			}
			err = fmt.Errorf("%v", r)
		}
	}()
	n, err = installerFor(it)(root, it, state, cfg, force)
	if err != nil && err.Error() == "" {
		err = errors.New(fmt.Sprintf("%T", err))
	}
	return n, err
}

func cmdVerify(root string, a *cliArgs) {
	state := loadState(root)
	var bad []string
	checked := 0
	type broken struct{ key, name, path string }
	var gone []broken
	tty := isTerminal(os.Stdout)
	all := stateItems(state)
	for _, key := range sortedKeys(all) {
		v := all.child(key)
		if v.has("files") {
			files := v.child("files")
			for _, name := range files.Keys() {
				meta := files.child(name)
				p := filepath.Join(dlDir(root), filepath.FromSlash(pyStr(v.get("dest"))), name)
				checked++
				st, err := os.Stat(p)
				switch {
				case err != nil:
					bad = append(bad, key+": "+name+" is missing")
					gone = append(gone, broken{key, name, p})
				case !pyEqual(st.Size(), meta.get("size")):
					bad = append(bad, key+": "+name+" has the wrong size")
					gone = append(gone, broken{key, name, p})
				case !a.flag("quick") && truthy(meta.get("sha256")):
					if tty {
						out(clip(padRight("  checking "+name+"...", 78), 78) + "\r")
					}
					if sum, err := sha256File(p); err != nil || sum != pyStr(meta.get("sha256")) {
						bad = append(bad, key+": "+name+" is CORRUPT (checksum mismatch)")
						gone = append(gone, broken{key, name, p})
					}
				}
			}
		} else if truthy(v.get("binary")) {
			checked++
			if !exists(filepath.Join(dlDir(root), filepath.FromSlash(pyStr(v.get("binary"))))) {
				bad = append(bad, key+": "+pyStr(v.get("binary"))+" is missing")
			}
		}
	}
	if tty {
		out(strings.Repeat(" ", 78) + "\r")
	}
	if len(bad) > 0 {
		log("Problems found:\n  " + strings.Join(bad, "\n  "))
		if a.flag("fix") {
			for _, b := range gone {
				os.Remove(b.path)
				all.child(b.key).child("files").del(b.name)
			}
			saveState(root, state)
			log("Removed the bad files. Run ./kit sync (while online) to download fresh copies.")
		} else {
			log("Fix: run ./kit verify --fix, then ./kit sync while online to download fresh copies.")
		}
		exit(1)
	}
	if a.flag("quick") {
		log(fmt.Sprintf("All %d files OK (sizes only; drop --quick for full checksums).", checked))
	} else {
		log(fmt.Sprintf("All %d files OK.", checked))
	}
}

func cmdStatus(root string, a *cliArgs) {
	state := loadState(root)
	free, total := diskUsage(root)
	var content int64
	all := stateItems(state)
	for _, section := range sections {
		var rows []string
		for _, k := range sortedKeys(all) {
			if strings.HasPrefix(k, section+"/") {
				rows = append(rows, k)
			}
		}
		if len(rows) > 0 {
			log("\n[" + section + "]")
		}
		for _, key := range rows {
			v := all.child(key)
			size := driveBytes(v)
			content += size
			shown := ""
			if size != 0 {
				shown = fmtBytes(size)
			}
			log("  " + padRight(clip(strings.SplitN(key, "/", 2)[1], 44), 46) + padRight(pyStr(v.getOr("version", "")), 16) +
				padLeft(shown, 9) + "   " + clip(pyStr(v.getOr("updated", "")), 10))
		}
	}
	dl := dlDir(root)
	seen := map[string]bool{}
	for _, k := range state.child("partials").Keys() {
		seen[k] = true
	}
	for _, pattern := range []string{"library/*.partial", "models/*/*.partial", "maps/*/*.partial", ".partial/*.partial"} {
		for _, p := range filesIn(dl, pattern) {
			if rel, err := filepath.Rel(dl, p); err == nil {
				seen[filepath.ToSlash(rel)] = true
			}
		}
	}
	var left []string
	for rel := range seen {
		if isFile(filepath.Join(dl, filepath.FromSlash(rel))) {
			left = append(left, rel)
		}
	}
	sort.Strings(left)
	if len(left) > 0 {
		log("\nUnfinished downloads (sync resumes them while the item is on in kit.json; delete one to free its space):")
		for _, rel := range left {
			log("  " + padRight(clip(rel, 60), 62) + padLeft(fmtBytes(fileSize(filepath.Join(dl, filepath.FromSlash(rel)))), 9))
		}
	}
	var kept []string
	var keptBytes int64
	for _, i := range itemsFromConfig(loadConfig(root)) {
		if rec := stateItems(state).child(i.key()); !i.enabled() && rec != nil {
			kept = append(kept, i.id)
			keptBytes += driveBytes(rec)
		}
	}
	if len(kept) > 0 {
		log(fmt.Sprintf("\nStill in the kit, switched off: %s (%s). To free the space: ./kit remove NAME",
			strings.Join(kept, ", "), fmtSize(float64(keptBytes))))
	}
	disk := "the drive"
	if onThisComputer(root) {
		disk = "this computer's disk"
	}
	log(fmt.Sprintf("\nKit content: %s.  Free on %s: %s of %s.", fmtBytes(content), disk, fmtBytes(free), fmtBytes(total)))
	if last := pyStrOr(state.get("last_sync")); truthy(state.get("last_sync")) {
		age := "?"
		if t, err := parseISO(last); err == nil {
			age = strconv.FormatInt(int64(math.Floor(naive(time.Now()).Sub(t).Hours()/24)), 10)
		}
		log("Last complete sync: " + clip(last, 10) + " (" + age + " days ago). To get newer versions, run SETUP.command " +
			"again, or ./kit update and then ./kit sync, whenever you like.")
	} else {
		log("Never fully synced. Run ./kit sync.")
	}
	if truthy(state.get("kit_version")) {
		log("Kit version: " + pyStr(state.get("kit_version")) + ".")
	}
}

func cmdSearch(root string, a *cliArgs) {
	cfg := loadConfig(root)
	r := newResolver(root, cfg)
	r.maxAge = 72 * time.Hour
	catalog, err := r.catalog()
	if err != nil {
		die(err.Error())
	}
	var words []string
	for _, w := range a.list("words") {
		words = append(words, strings.ToLower(w))
	}
	var configured []any
	for _, e := range cfg.objs("library") {
		configured = append(configured, e.get("zim"))
	}
	var hits []*obj
	for _, e := range catalog {
		text := strings.ToLower(strings.Join([]string{e.str("prefix"), pyStr(e.getOr("title", "")), pyStr(e.getOr("summary", ""))}, " "))
		all := true
		for _, w := range words {
			all = all && strings.Contains(text, w)
		}
		if all {
			hits = append(hits, e)
		}
	}
	if len(hits) == 0 {
		log("No matches. Try fewer or different words.")
		return
	}
	sort.SliceStable(hits, func(i, j int) bool {
		si, sj := intOr(orZero(hits[i].get("size")), 0), intOr(orZero(hits[j].get("size")), 0)
		if si != sj {
			return si < sj
		}
		return intOr(hits[i].get("order"), 0) < intOr(hits[j].get("order"), 0)
	})
	for _, e := range hits[:min(60, len(hits))] {
		mark := ""
		if containsAny(configured, e.get("prefix")) {
			mark = "  (already in kit.json)"
		}
		summary := e.get("summary")
		if !truthy(summary) {
			summary = ""
		}
		log(fmt.Sprintf("%s  %s  %s%s\n           %s: %s", padLeft(fmtSizeAny(e.get("size")), 9), pyStr(e.get("date")),
			pyStr(e.get("prefix")), mark, pyStr(e.getOr("title", "")), clip(pyStr(summary), 90)))
	}
	if len(hits) > 60 {
		log(fmt.Sprintf("... and %d more; add words to narrow it down.", len(hits)-60))
	}
	log("\nTo add one, put a line like this in the \"library\" list in kit.json, then run ./kit sync:\n" +
		fmt.Sprintf(`    {"zim": "%s", "note": "%s"},`, pyStr(hits[0].get("prefix")), pyStr(hits[0].getOr("title", ""))))
}

// ----------------------------------------------------------------------------- self-test

func platformTag() string { return plat() }

// runtimeBinary finds a program sync installed, in the version it marked current. KIT_<PRODUCT>_BIN stands in for it.
func runtimeBinary(root, product, name string) string {
	envName := "KIT_" + strings.ReplaceAll(strings.ReplaceAll(strings.ToUpper(product), ".", ""), "-", "_") + "_BIN"
	if v := os.Getenv(envName); v != "" {
		return v
	}
	if windows && !strings.HasSuffix(name, ".exe") {
		name += ".exe"
	}
	rel := "bin/" + product + "-" + platformTag()
	if cur := currentDir(root, rel); cur != "" {
		if p := findBinary(cur, name); p != "" {
			return p
		}
	}
	return findBinary(filepath.Join(dlDir(root), filepath.FromSlash(rel)), name)
}

// server is a program cmdTest started, and whether it has quit.
type server struct {
	cmd  *exec.Cmd
	done chan struct{}
}

func (s *server) quit() bool {
	select {
	case <-s.done:
		return true
	default:
		return false
	}
}

// waitHTTP waits for a URL to answer. server, if given, is the program that should answer: if it quits, so does this.
func waitHTTP(url string, timeout time.Duration, s *server) bool {
	end := time.Now().Add(timeout)
	for time.Now().Before(end) {
		if _, err := httpGet(url, 5, ""); err == nil {
			return true
		}
		if s != nil && s.quit() {
			return false // it quit
		}
		sleep(time.Second)
	}
	return false
}

// ephemeralPort is a port nothing is listening on.
func ephemeralPort() int {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

func startServer(servers *[]*server, logPath, dir string, prog string, args ...string) *server {
	s := &server{done: make(chan struct{})}
	f, err := os.Create(logPath) // the server keeps its own handle on the log
	if err != nil {
		close(s.done)
		return s
	}
	defer f.Close()
	s.cmd = exec.Command(prog, args...)
	s.cmd.Dir = dir
	s.cmd.Stdout, s.cmd.Stderr = f, f
	if err := s.cmd.Start(); err != nil {
		fmt.Fprintln(f, err)
		close(s.done)
		return s
	}
	go func() {
		s.cmd.Wait()
		close(s.done)
	}()
	*servers = append(*servers, s)
	return s
}

func itoa(n int) string { return strconv.Itoa(n) }

// testMaps checks the map's servers. starter: a try-it kit, which gets address search and directions with the rest.
func testMaps(root string, m *obj, check func(string, bool, string), servers *[]*server, logs string, starter bool) {
	home := m.child("home")
	pm := runtimeBinary(root, "pmtiles", "pmtiles")
	tiles := filepath.Join(dlDir(root), "maps", "tiles", "basemap.pmtiles")
	detail := ""
	if !exists(tiles) {
		detail = "run ./kit sync"
	}
	check("map tiles present", pm != "" && exists(tiles), detail)
	if pm != "" && exists(tiles) {
		port := ephemeralPort()
		startServer(servers, filepath.Join(logs, "test-tiles.log"), "", pm, "serve", filepath.Dir(tiles), "--port", itoa(port),
			"--interface", "127.0.0.1", "--cors", "http://127.0.0.1:8888",
			"--public-url", "http://127.0.0.1:"+itoa(port)) // without it, /basemap.json is a 501
		ok := false
		if waitHTTP(fmt.Sprintf("http://127.0.0.1:%d/basemap.json", port), 30*time.Second, nil) {
			body, err := httpGet(fmt.Sprintf("http://127.0.0.1:%d/basemap/0/0/0.mvt", port), 0, "")
			ok = err == nil && len(body) > 0
		}
		check("map tile server works", ok, "")
	}
	java := runtimeBinary(root, "java", "java")
	photon := newestFile(filepath.Join(dlDir(root), "bin", "photon"), "photon-*.jar")
	gdir := filepath.Join(dlDir(root), "maps", "geocoder")
	have := java != "" && photon != "" && isDir(filepath.Join(gdir, "photon_data"))
	switch {
	case !have && !truthy(m.get("geocoder_country")):
		log("  SKIP  address search: nobody publishes one for this map's area")
	case !have && starter:
		log("  SKIP  address search: it comes with the rest of the kit")
	case !have && truthy(m.get("geocoder_wide")):
		log("  SKIP  address search: not here yet. It's for a whole region of the world, so it comes after the essentials")
	default:
		check("address search installed", have, "")
	}
	if have {
		port := ephemeralPort()
		startServer(servers, filepath.Join(logs, "test-geocoder.log"), "", java, "-Xmx"+pyStr(m.get("geocoder_heap")),
			"-jar", photon, "serve", "-data-dir", gdir, "-listen-ip", "127.0.0.1", "-listen-port", itoa(port),
			"-cors-origin", "http://127.0.0.1:8888")
		detail, ok := "did not start (see logs/test-geocoder.log)", false
		if waitHTTP(fmt.Sprintf("http://127.0.0.1:%d/status", port), 240*time.Second, nil) {
			// What's near home, then a search for it by name: that finds something in any place and language
			nearHome := "lat=" + pyStr(home.get("lat")) + "&lon=" + pyStr(home.get("lon"))
			features := func(url string) ([]any, error) {
				v, err := httpJSON(url, 0)
				if err != nil {
					return nil, err
				}
				o, _ := v.(*obj)
				f, _ := o.getOr("features", []any{}).([]any)
				return f, nil
			}
			props := func(found []any) *obj {
				if len(found) == 0 {
					return newObj()
				}
				f, _ := found[0].(*obj)
				p := f.child("properties")
				if p == nil {
					p = newObj()
				}
				return p
			}
			found, err := features(fmt.Sprintf("http://127.0.0.1:%d/reverse?%s&radius=10&limit=1", port, nearHome))
			if err == nil {
				name := props(found).get("name")
				if !truthy(name) {
					name = props(found).get("street")
				}
				if truthy(name) {
					found, err = features(fmt.Sprintf("http://127.0.0.1:%d/api?q=%s&limit=1&%s", port, quote(pyStr(name), "/"), nearHome))
				}
			}
			if err != nil {
				detail = err.Error()
			} else {
				ok = len(found) > 0
				if ok {
					var parts []string
					pr := props(found)
					for _, k := range []string{"name", "street", "city", "state", "country"} {
						if truthy(pr.get(k)) {
							parts = append(parts, pyStr(pr.get(k)))
						}
					}
					detail = strings.Join(parts, ", ")
				} else {
					where := home.get("label")
					if !truthy(where) {
						where = "home"
					}
					detail = "nothing found near " + pyStr(where)
				}
			}
		}
		check("address search works", ok, detail)
	}
	gh := newestFile(filepath.Join(dlDir(root), "bin", "graphhopper"), "graphhopper-web-*.jar")
	rdir := filepath.Join(dlDir(root), "maps", "routing")
	routed := java != "" && gh != "" && exists(filepath.Join(rdir, "graph-cache", "properties"))
	if !routed && starter {
		log("  SKIP  directions: they come with the rest of the kit")
	} else {
		check("directions installed", routed, "")
	}
	if routed {
		port := ephemeralPort()
		startServer(servers, filepath.Join(logs, "test-routing.log"), rdir, java, "-Xmx"+pyStr(m.get("routing_heap")),
			fmt.Sprintf("-Ddw.server.application_connectors[0].port=%d", port),
			fmt.Sprintf("-Ddw.server.admin_connectors[0].port=%d", ephemeralPort()), "-jar", gh, "server", "gh-serve.yml")
		detail, ok := "did not start (see logs/test-routing.log)", false
		if waitHTTP(fmt.Sprintf("http://127.0.0.1:%d/health", port), 240*time.Second, nil) {
			profiles := m.list("routing_profiles")
			profile := "car"
			if len(profiles) > 0 {
				profile = pyStr(profiles[0])
			}
			lat, _ := asNumber(home.get("lat"))
			lon, _ := asNumber(home.get("lon"))
			v, err := httpJSON(fmt.Sprintf("http://127.0.0.1:%d/route?point=%s,%s&point=%s,%s&profile=%s&points_encoded=false&locale=en",
				port, pyFloat(lat), pyFloat(lon), pyFloat(lat+0.02), pyFloat(lon+0.02), profile), 0)
			if err != nil {
				detail = clip(err.Error(), 200)
			} else if res, _ := v.(*obj); res == nil || len(res.list("paths")) == 0 {
				detail = "'paths'"
			} else {
				path, _ := res.list("paths")[0].(*obj)
				dist, _ := asNumber(path.get("distance"))
				steps := path.list("instructions")
				ok = dist > 0 && len(steps) > 0
				detail = fmt.Sprintf("%s km, %d steps (%s)", strconv.FormatFloat(dist/1000, 'f', 1, 64), len(steps), profile)
			}
		}
		check("directions work", ok, detail)
	}
}

var (
	kitMaps  = regexp.MustCompile(`(?s)window\.KIT_MAPS = (\{.*?\});</script>`)
	bookLink = regexp.MustCompile(`<link type="text/html" href="[^"]*/content/([^"]+)"`)
	corsRE   = regexp.MustCompile(`access-control-allow-origin:\s*(\S+)`)
)

func cmdTest(root string, a *cliArgs) {
	type result struct {
		name string
		ok   bool
	}
	var results []result
	check := func(name string, ok bool, detail string) {
		results = append(results, result{name, ok})
		line := "  FAIL  " + name
		if ok {
			line = "  PASS  " + name
		}
		if detail != "" {
			line += ": " + detail
		}
		log(line)
	}
	cfg := loadConfig(root)
	portal, err := buildPortal(root, cfg)
	if err != nil {
		log("  (could not build the portal page: " + err.Error() + "; testing the plain one)")
		portal = filepath.Join(appDir(root), "tools", "portal.html")
	}
	kiwix := runtimeBinary(root, "kiwix-tools", "kiwix-serve")
	llama := runtimeBinary(root, "llama.cpp", "llama-server")
	dropFinderFiles(root)
	zims := filesIn(filepath.Join(dlDir(root), "library"), "*.zim")
	var models []string
	for _, p := range filesIn(filepath.Join(dlDir(root), "models"), "*") {
		if isDir(p) && len(filesIn(p, "*.gguf")) > 0 {
			models = append(models, p)
		}
	}
	orSync := func(p string) string {
		if p == "" {
			return "run ./kit sync"
		}
		return p
	}
	log("Platform: " + platformTag())
	check("library server installed", kiwix != "", orSync(kiwix))
	check("AI server installed", llama != "", orSync(llama))
	check("library files present", len(zims) > 0, fmt.Sprintf("%d .zim files", len(zims)))
	someOn := false
	for _, m := range cfg.objs("models") {
		someOn = someOn || m.on()
	}
	if someOn {
		var ns []string
		for _, m := range models {
			ns = append(ns, filepath.Base(m))
		}
		check("models present", len(models) > 0, strings.Join(ns, ", "))
	} else {
		log("  SKIP  models: kit.json switches them all off, so the kit runs without the AI")
	}
	var servers []*server
	logs := filepath.Join(dataDir(root), "logs")
	os.MkdirAll(logs, 0o755)
	func() {
		defer func() {
			for _, s := range servers {
				terminate(s.cmd.Process)
			}
			for _, s := range servers {
				select {
				case <-s.done:
				case <-time.After(15 * time.Second):
					s.cmd.Process.Kill()
				}
			}
		}()
		if kiwix != "" && len(zims) > 0 {
			kport, lib := ephemeralPort(), "127.0.0.1"
			kiwixLog := filepath.Join(logs, "test-kiwix.log")
			args := append([]string{"--port", itoa(kport), "--address", lib, "--customIndex", portal}, zims...)
			up := waitHTTP(fmt.Sprintf("http://%s:%d/", lib, kport), 60*time.Second, startServer(&servers, kiwixLog, "", kiwix, args...))
			if said, _ := os.ReadFile(kiwixLog); !up && strings.Contains(string(said), "not available on this system") {
				// A second IPv4 address on the loopback hides 127.0.0.1 from kiwix-serve: see the launcher, which then
				// runs it on ::1 and forwards 127.0.0.1 there
				log("  (this computer's library server won't use 127.0.0.1, so it's tested on ::1, as the kit runs it)")
				lib = "[::1]"
				args[3] = "::1"
				up = waitHTTP(fmt.Sprintf("http://%s:%d/", lib, kport), 60*time.Second, startServer(&servers, kiwixLog, "", kiwix, args...))
			}
			check("library server starts", up, "")
			if up {
				body, _ := httpGet(fmt.Sprintf("http://%s:%d/", lib, kport), 0, "")
				page := strings.ToValidUTF8(string(body), "�")
				check("portal page served", strings.Contains(page, "Tinfoil Kit") && !strings.Contains(clip(page, 200), "{{"), "")
				if truthy(mapsSettings(cfg).get("enabled")) {
					mi := kitMaps.FindStringSubmatch(page)
					avail := mi != nil && strings.Contains(mi[1], `"available": true`)
					why := ""
					if !avail {
						why = "missing"
						if mi != nil {
							o, _ := parseObj([]byte(mi[1]))
							why = pyStr(o.getOr("reason", ""))
						}
					}
					check("map page built", avail, why)
				}
				body, _ = httpGet(fmt.Sprintf("http://%s:%d/catalog/v2/entries?count=-1", lib, kport), 0, "")
				cat := strings.ToValidUTF8(string(body), "�")
				entries := strings.Count(cat, "<entry>")
				check("all books listed", entries >= len(zims), fmt.Sprintf("%d books", entries))
				hits := 0
				books := bookLink.FindAllStringSubmatch(cat, -1)
				for _, b := range books[:min(5, len(books))] {
					xml, err := httpGet(fmt.Sprintf("http://%s:%d/search?content=%s&pattern=water&format=xml&pageLength=3",
						lib, kport, quote(b[1], "/")), 0, "")
					if err == nil {
						hits += strings.Count(string(xml), "<item>")
					}
				}
				check("full-text search works", hits > 0, fmt.Sprintf("%d results for 'water'", hits))
			}
		}
		// The page's notes, pins and home: this program keeps them in the data folder
		dport := ephemeralPort()
		me, _ := os.Executable()
		up := waitHTTP(fmt.Sprintf("http://127.0.0.1:%d/", dport), 15*time.Second, startServer(&servers,
			filepath.Join(logs, "test-data.log"), "", me, "data", "--data", dataDir(root), "--port", itoa(dport), "--library", "8888"))
		check("notes and pins server starts", up, "")
		if up {
			notes, err := httpJSON(fmt.Sprintf("http://127.0.0.1:%d/notes", dport), 0)
			var places any
			if err == nil {
				places, err = httpJSON(fmt.Sprintf("http://127.0.0.1:%d/places", dport), 0)
			}
			n, _ := notes.(*obj)
			p, _ := places.(*obj)
			text, isText := n.get("text").(string)
			pins, isList := p.get("pins").([]any)
			switch {
			case err != nil:
				check("notes and pins readable", false, err.Error())
			case !isText || !isList:
				check("notes and pins readable", false, "'text'")
			default:
				check("notes and pins readable", true, fmt.Sprintf("%s characters of notes, %d pins",
					thousands(len([]rune(text))), len(pins)))
			}
		}
		if llama != "" && len(models) > 0 {
			lport := ephemeralPort()
			small, smallest := "", int64(math.MaxInt64)
			for _, m := range models {
				var total int64
				for _, f := range filesIn(m, "*.gguf") {
					total += fileSize(f)
				}
				if total < smallest {
					small, smallest = m, total
				}
			}
			name := a.str("model")
			if name == "" {
				name = filepath.Base(small)
			}
			startServer(&servers, filepath.Join(logs, "test-llama.log"), "", llama, "--models-dir",
				filepath.Join(dlDir(root), "models"), "--models-max", "1", "-c", "4096", "--host", "127.0.0.1",
				"--port", itoa(lport), "--cors-origins", "http://127.0.0.1:8888")
			up := waitHTTP(fmt.Sprintf("http://127.0.0.1:%d/v1/models", lport), 90*time.Second, nil)
			check("AI server starts", up, "")
			if up {
				v, _ := httpJSON(fmt.Sprintf("http://127.0.0.1:%d/v1/models", lport), 0)
				var listed []any
				var shown []string
				for _, m := range v.(*obj).objs("data") {
					listed = append(listed, m.get("id"))
					shown = append(shown, pyStr(m.get("id")))
				}
				all := true
				for _, m := range models {
					all = all && containsAny(listed, filepath.Base(m))
				}
				check("models discovered", all, strings.Join(shown, ", "))
				body := dumpsLine(newObj("model", name, "max_tokens", 64, "temperature", 0, "messages",
					[]any{newObj("role", "user", "content", "Reply with just the word OK.")}))
				t0 := time.Now()
				stdout, stderr, rc := output("curl", "-fsS", "--max-time", "600", "-H", "Content-Type: application/json",
					"-d", body, fmt.Sprintf("http://127.0.0.1:%d/v1/chat/completions", lport))
				ok, detail := false, strings.TrimSpace(string(stderr))
				if rc == 0 {
					reply := ""
					if res, err := parseObj(stdout); err == nil {
						if choices := res.list("choices"); len(choices) > 0 {
							msg := choices[0].(*obj).child("message")
							r := msg.get("content")
							if !truthy(r) {
								r = msg.get("reasoning_content")
							}
							if truthy(r) {
								reply = strings.TrimSpace(pyStr(r))
							}
						}
					}
					ok = reply != ""
					detail = fmt.Sprintf("%s answered in %ss: %s", name,
						strconv.FormatFloat(time.Since(t0).Seconds(), 'f', 0, 64), pyRepr(clip(reply, 40)))
				}
				check("model answers", ok, detail)
				pre, _, _ := output("curl", "-sS", "-o", os.DevNull, "-D", "-", "-X", "OPTIONS", "-H", "Origin: http://127.0.0.1:8888",
					"-H", "Access-Control-Request-Method: POST", fmt.Sprintf("http://127.0.0.1:%d/v1/chat/completions", lport))
				acao := corsRE.FindStringSubmatch(strings.ToLower(string(pre)))
				shownOrigin := "no CORS header"
				if acao != nil {
					shownOrigin = acao[1]
				}
				check("portal may call the AI (CORS)", acao != nil && (acao[1] == "*" || acao[1] == "http://127.0.0.1:8888"), shownOrigin)
			}
		}
		if m := mapsSettings(cfg); truthy(m.get("enabled")) {
			testMaps(root, m, check, &servers, logs, isTrue(cfg.child("settings").get("starter_only")))
		}
	}()
	failed := 0
	for _, r := range results {
		if !r.ok {
			failed++
		}
	}
	if failed == 0 {
		log("\nAll checks passed. The kit works offline.")
		exit(0)
	}
	log(fmt.Sprintf("\n%d check(s) failed. Logs are in %s.", failed, logs))
	exit(1)
}

// thousands is a number with commas, as Python's f"{n:,}".
func thousands(n int) string {
	s := strconv.Itoa(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}
