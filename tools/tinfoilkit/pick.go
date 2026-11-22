package main

// What goes in the kit: which AI this computer runs, where you live and Wikipedia's languages and size, the kit
// builder's choices, and how much room it all takes.

import (
	"errors"
	"fmt"
	"math"
	"os"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
)

// ----------------------------------------------------------------------------- the AI models this computer can run

// memoryBytes is this computer's memory, or 0 if it can't tell. KIT_MEMORY_MB stands in for it, as in the launcher.
func memoryBytes() int64 {
	if v := os.Getenv("KIT_MEMORY_MB"); v != "" && allDigits(v) {
		n, _ := strconv.ParseInt(v, 10, 64)
		return n * 1048576
	}
	return physMemory()
}

// sourcesList is the kit builder's list (site/sources.json): each source's id, title, group, size and presets.
func sourcesList(root string) ([]*obj, bool) {
	data, err := os.ReadFile(filepath.Join(appDir(root), "site", "sources.json"))
	if err != nil {
		return nil, false
	}
	o, err := parseObj(data)
	if err != nil {
		return nil, false
	}
	list, ok := o.get("sources").([]any)
	if !ok {
		return nil, false
	}
	var out []*obj
	for _, v := range list {
		s, ok := v.(*obj)
		if !ok || !s.has("id") {
			return nil, false
		}
		out = append(out, s)
	}
	return out, true
}

var noteGB = regexp.MustCompile(`~(\d+(?:\.\d+)?) ?GB`)

// modelSizes is each model's download size, from the kit builder's list, else the "~N GB" in its note.
func modelSizes(root string, cfg *obj) map[string]int64 {
	listed := map[string]int64{}
	if sources, ok := sourcesList(root); ok {
		for _, s := range sources {
			listed[pyStr(s.get("id"))] = intOr(orZero(s.get("bytes")), 0)
		}
	}
	sizes := map[string]int64{}
	for _, m := range cfg.objs("models") {
		id := pyStr(m.get("id"))
		sizes[id] = listed[id]
		if sizes[id] == 0 {
			if n := noteGB.FindStringSubmatch(m.str("note")); n != nil {
				f, _ := strconv.ParseFloat(n[1], 64)
				sizes[id] = int64(f * GB)
			}
		}
	}
	return sizes
}

// orZero is Python's "x or 0".
func orZero(v any) any {
	if !truthy(v) {
		return 0
	}
	return v
}

// fits: a model may take 60% of the memory, leaving the rest for everything else (the launcher's rule too).
func fits(size, memory int64) bool {
	return memory == 0 || size == 0 || float64(size) <= float64(memory)*0.6
}

// memoryFor is the smallest usual amount of memory, in GB, that runs a model of this size.
func memoryFor(size int64) int64 {
	need := float64(size) / 0.6 / (1 << 30)
	for _, g := range []int64{8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 512} {
		if float64(g) >= need {
			return g
		}
	}
	return int64(math.Ceil(need))
}

// fitReport is which model the AI starts with on this computer (the launcher picks the same way: the default model
// if it fits, else the biggest that does, else the smallest), the switched-on models it can't run that aren't
// downloaded yet, and the ones switched off for that on a computer with less memory that this one runs. Those are
// listed in kit.json, not data/.kit/state.json, so the list moves with the kit when SETUP puts it in its place.
func fitReport(root string, cfg, state *obj) *obj {
	memory, sizes := memoryBytes(), modelSizes(root, cfg)
	settings := cfg.child("settings")
	def := settings.get("default_model")
	type model struct {
		id    string
		bytes int64
		fits  bool
		on    bool
		o     *obj
	}
	var models, on []*model
	var all []any
	for _, m := range cfg.objs("models") {
		id := pyStr(m.get("id"))
		x := &model{id: id, bytes: sizes[id], fits: fits(sizes[id], memory), on: truthy(m.getOr("enabled", true))}
		var needs any
		if x.bytes != 0 {
			needs = memoryFor(x.bytes)
		}
		x.o = newObj("id", m.get("id"), "bytes", x.bytes, "fits", x.fits, "needs_memory_gb", needs,
			"enabled", m.getOr("enabled", true))
		models = append(models, x)
		all = append(all, x.o)
		if x.on {
			on = append(on, x)
		}
	}
	size := func(m *model) float64 { // an unknown size sorts last
		if m.bytes == 0 {
			return math.Inf(1)
		}
		return float64(m.bytes)
	}
	var smallest, runs *model
	for _, m := range on {
		if smallest == nil || size(m) < size(smallest) {
			smallest = m
		}
	}
	for _, m := range on {
		if pyEqual(m.o.get("id"), def) && m.fits {
			runs = m
			break
		}
	}
	if runs == nil {
		for _, m := range on {
			if m.fits && (runs == nil || m.bytes > runs.bytes) {
				runs = m
			}
		}
	}
	if runs == nil {
		runs = smallest
	}
	tooBig, fitsNow := []any{}, []any{}
	off := settings.list("models_off_for_memory")
	for _, m := range on {
		if !m.fits && m != runs && !stateItems(state).has("models/"+m.id) {
			tooBig = append(tooBig, m.id)
		}
	}
	for _, m := range models {
		if !m.on && m.fits && containsAny(off, m.id) {
			fitsNow = append(fitsNow, m.id)
		}
	}
	idOf := func(m *model) any {
		if m == nil {
			return nil
		}
		return m.o.get("id")
	}
	return newObj("memory_bytes", memory, "runs", idOf(runs), "smallest", idOf(smallest), "models", all,
		"too_big", tooBig, "fits_now", fitsNow)
}

// containsAny is Python's "x in list" for a list from JSON.
func containsAny(list []any, x any) bool {
	for _, v := range list {
		if pyEqual(v, x) {
			return true
		}
	}
	return false
}

// strs is a JSON list's strings.
func strs(list []any) []string {
	var out []string
	for _, v := range list {
		out = append(out, pyStr(v))
	}
	return out
}

// ----------------------------------------------------------------------------- where you live

const foldPairs = "Àa Áa Âa Ãa Äa Åa Çc Èe Ée Êe Ëe Ìi Íi Îi Ïi Ñn Òo Óo Ôo Õo Öo Ùu Úu Ûu Üu " +
	"Ýy àa áa âa ãa äa åa çc èe ée êe ëe ìi íi îi ïi ñn òo óo ôo õo öo ùu úu ûu " +
	"üu ýy ÿy Āa āa Ăa ăa Ąa ąa Ćc ćc Ĉc ĉc Ċc ċc Čc čc Ďd ďd Ēe ēe Ĕe ĕe Ėe ėe " +
	"Ęe ęe Ěe ěe Ĝg ĝg Ğg ğg Ġg ġg Ģg ģg Ĥh ĥh Ĩi ĩi Īi īi Ĭi ĭi Įi įi İi Ĳij " +
	"ĳij Ĵj ĵj Ķk ķk Ĺl ĺl Ļl ļl Ľl ľl Ŀl· ŀl· Ńn ńn Ņn ņn Ňn ňn ŉʼn Ōo ōo Ŏo " +
	"ŏo Őo őo Ŕr ŕr Ŗr ŗr Řr řr Śs śs Ŝs ŝs Şs şs Šs šs Ţt ţt Ťt ťt Ũu ũu Ūu ūu " +
	"Ŭu ŭu Ůu ůu Űu űu Ųu ųu Ŵw ŵw Ŷy ŷy Ÿy Źz źz Żz żz Žz žz ſs Ơo ơo Ưu ưu Ǆdz " +
	"ǅdz ǆdz Ǉlj ǈlj ǉlj Ǌnj ǋnj ǌnj Ǎa ǎa Ǐi ǐi Ǒo ǒo Ǔu ǔu Ǖu ǖu Ǘu ǘu Ǚu ǚu Ǜu " +
	"ǜu Ǟa ǟa Ǡa ǡa Ǧg ǧg Ǩk ǩk Ǫo ǫo Ǭo ǭo ǰj Ǳdz ǲdz ǳdz Ǵg ǵg Ǹn ǹn Ǻa ǻa Ȁa " +
	"ȁa Ȃa ȃa Ȅe ȅe Ȇe ȇe Ȉi ȉi Ȋi ȋi Ȍo ȍo Ȏo ȏo Ȑr ȑr Ȓr ȓr Ȕu ȕu Ȗu ȗu Șs șs " +
	"Țt țt Ȟh ȟh Ȧa ȧa Ȩe ȩe Ȫo ȫo Ȭo ȭo Ȯo ȯo Ȱo ȱo Ȳy ȳy Ḁa ḁa Ḃb ḃb Ḅb " +
	"ḅb Ḇb ḇb Ḉc ḉc Ḋd ḋd Ḍd ḍd Ḏd ḏd Ḑd ḑd Ḓd ḓd Ḕe ḕe Ḗe ḗe Ḙe " +
	"ḙe Ḛe ḛe Ḝe ḝe Ḟf ḟf Ḡg ḡg Ḣh ḣh Ḥh ḥh Ḧh ḧh Ḩh ḩh Ḫh ḫh Ḭi " +
	"ḭi Ḯi ḯi Ḱk ḱk Ḳk ḳk Ḵk ḵk Ḷl ḷl Ḹl ḹl Ḻl ḻl Ḽl ḽl Ḿm ḿm Ṁm " +
	"ṁm Ṃm ṃm Ṅn ṅn Ṇn ṇn Ṉn ṉn Ṋn ṋn Ṍo ṍo Ṏo ṏo Ṑo ṑo Ṓo ṓo Ṕp " +
	"ṕp Ṗp ṗp Ṙr ṙr Ṛr ṛr Ṝr ṝr Ṟr ṟr Ṡs ṡs Ṣs ṣs Ṥs ṥs Ṧs ṧs Ṩs " +
	"ṩs Ṫt ṫt Ṭt ṭt Ṯt ṯt Ṱt ṱt Ṳu ṳu Ṵu ṵu Ṷu ṷu Ṹu ṹu Ṻu ṻu Ṽv " +
	"ṽv Ṿv ṿv Ẁw ẁw Ẃw ẃw Ẅw ẅw Ẇw ẇw Ẉw ẉw Ẋx ẋx Ẍx ẍx Ẏy ẏy Ẑz " +
	"ẑz Ẓz ẓz Ẕz ẕz ẖh ẗt ẘw ẙy ẚaʾ ẛs Ạa ạa Ảa ảa Ấa ấa Ầa ầa " +
	"Ẩa ẩa Ẫa ẫa Ậa ậa Ắa ắa Ằa ằa Ẳa ẳa Ẵa ẵa Ặa ặa Ẹe ẹe Ẻe ẻe " +
	"Ẽe ẽe Ếe ếe Ềe ềe Ểe ểe Ễe ễe Ệe ệe Ỉi ỉi Ịi ịi Ọo ọo Ỏo ỏo " +
	"Ốo ốo Ồo ồo Ổo ổo Ỗo ỗo Ộo ộo Ớo ớo Ờo ờo Ởo ởo Ỡo ỡo Ợo ợo " +
	"Ụu ụu Ủu ủu Ứu ứu Ừu ừu Ửu ửu Ữu ữu Ựu ựu Ỳy ỳy Ỵy ỵy Ỷy ỷy " +
	"Ỹy ỹy "

var foldTable = func() map[rune]string {
	t := map[rune]string{}
	for _, p := range strings.Fields(foldPairs) {
		r := []rune(p)
		t[r[0]] = string(r[1:])
	}
	return t
}()

var notAlnum = regexp.MustCompile(`[^a-z0-9]+`)

// fold is lower case, without accents or punctuation, for matching what someone typed.
func fold(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case r >= 0x300 && r <= 0x36f: // an accent on the letter before it
			continue
		case foldTable[r] != "":
			b.WriteString(foldTable[r])
			continue
		case r >= 0xff01 && r <= 0xff5e: // a full-width letter or digit
			r -= 0xfee0
		}
		b.WriteString(strings.ToLower(string(r)))
	}
	return strings.Join(strings.Fields(notAlnum.ReplaceAllString(b.String(), " ")), " ")
}

// placesIn is the places someone named, separated by commas: ids, names or other names (a place's own name can have
// commas in it, like "US Northeast (CT, MA...)"). It stops with a message when one matches no place, or several.
func placesIn(text string) []*obj {
	if r := regionByID(strings.TrimSpace(text)); r != nil {
		return []*obj{r}
	}
	if strings.Contains(text, ",") {
		for _, r := range regions().objs("regions") {
			if fold(r.str("name")) == fold(text) {
				return []*obj{r}
			}
		}
	}
	var rs []*obj
	if words := strings.Fields(text); !strings.Contains(text, ",") && len(words) > 1 { // ids, which cmd parts at commas
		for _, w := range words {
			if r := regionByID(w); r != nil && !slices.Contains(rs, r) {
				rs = append(rs, r)
			} else if r == nil {
				rs = nil
				break
			}
		}
		if len(rs) > 0 {
			return rs
		}
	}
	for _, part := range strings.Split(text, ",") {
		if part = strings.TrimSpace(part); part == "" {
			continue
		}
		r := regionByID(part)
		if r == nil {
			found := findRegions(part)
			if len(found) == 0 {
				die(fmt.Sprintf("No place matches \"%s\". Try a US state or a country, in English: ./kit region --find WORDS", part))
			}
			if len(found) > 1 {
				var some []string
				for _, f := range found[:min(12, len(found))] {
					some = append(some, pyStr(f.get("name"))+" ("+pyStr(f.get("id"))+")")
				}
				more := ""
				if len(found) > 12 {
					more = "; ..."
				}
				die(fmt.Sprintf("\"%s\" could be: %s%s. Run it again with the one in brackets.", part, strings.Join(some, "; "), more))
			}
			r = found[0]
		}
		if !slices.Contains(rs, r) {
			rs = append(rs, r)
		}
	}
	if len(rs) == 0 {
		die("Name a place: ./kit region PLACE (several with commas)")
	}
	return rs
}

// findRegions is the places that best match what someone typed: exact names (or other names: "UK", "Bavaria", a big
// town) if any, else names that start with it, else names with a word that starts with it, else names that contain
// it. Nothing typed: all of them.
func findRegions(text string) []*obj {
	q := fold(text)
	all := regions().objs("regions")
	if q == "" {
		return all
	}
	type hit struct {
		rank int
		r    *obj
	}
	var found []hit
	best := 4
	for _, r := range all {
		var keys []string
		name := pyStr(r.get("name"))
		for _, k := range append(append([]string{name, pyStr(r.get("id"))}, strs(r.list("also"))...), strings.Split(name, ": ")[1:]...) {
			keys = append(keys, fold(k))
		}
		rank := -1
		switch {
		case contains(keys, q):
			rank = 0
		case anyKey(keys, func(k string) bool { return strings.HasPrefix(k, q) }):
			rank = 1
		case anyKey(keys, func(k string) bool { return strings.Contains(" "+k, " "+q) }):
			rank = 2
		case len(q) > 2 && anyKey(keys, func(k string) bool { return strings.Contains(k, q) }):
			rank = 3
		}
		if rank >= 0 {
			found = append(found, hit{rank, r})
			best = min(best, rank)
		}
	}
	var out []*obj
	for _, h := range found {
		if h.rank == best {
			out = append(out, h.r)
		}
	}
	return out
}

func anyKey(keys []string, f func(string) bool) bool {
	for _, k := range keys {
		if f(k) {
			return true
		}
	}
	return false
}

// wikipediaLangs is the languages of the Wikipedias switched on in kit.json.
func wikipediaLangs(cfg *obj) []string {
	var out []string
	for _, z := range cfg.objs("library") {
		if m := wikipediaRE.FindStringSubmatch(z.str("zim")); m != nil && z.on() {
			out = append(out, m[1])
		}
	}
	return out
}

// wikipediaEdition is the edition of kit.json's Wikipedia (all_maxi, top_nopic...), switched on or not. "" if it
// has none.
func wikipediaEdition(cfg *obj) string {
	for _, z := range cfg.objs("library") {
		if m := wikipediaRE.FindStringSubmatch(z.str("zim")); m != nil {
			return m[2]
		}
	}
	return ""
}

func editionIndex(e string) int {
	for i, x := range editions {
		if x == e {
			return i
		}
	}
	return -1
}

// wikiEditions is the editions of Wikipedia in a language, and their MB (tools/regions.json).
func wikiEditions(lang string) map[string]float64 {
	v := regions().child("languages").child(lang)
	out := map[string]float64{}
	sizes := v.child("sizes")
	for _, e := range sizes.Keys() {
		if mb, ok := asNumber(sizes.get(e)); ok && editionIndex(e) >= 0 {
			if _, isBool := sizes.get(e).(bool); !isBool {
				out[e] = mb
			}
		}
	}
	if m := wikipediaRE.FindStringSubmatch(v.str("zim")); m != nil {
		if _, ok := out[m[2]]; !ok {
			out[m[2]], _ = asNumber(orZero(v.get("mb")))
		}
	}
	return out
}

// wikiEdition is the edition of lang's Wikipedia nearest to the one asked for: it, else the biggest smaller one, else
// the smallest. "" when there's no Wikipedia in lang.
func wikiEdition(lang, edition string) string {
	var have []string
	for e := range wikiEditions(lang) {
		have = append(have, e)
	}
	sort.Slice(have, func(i, j int) bool { return editionIndex(have[i]) < editionIndex(have[j]) })
	pick := ""
	for _, e := range have {
		if editionIndex(e) <= editionIndex(edition) {
			pick = e
		}
	}
	if pick == "" && len(have) > 0 {
		pick = have[0]
	}
	return pick
}

func gbText(mb float64) string {
	if mb < 9950 {
		return strconv.FormatFloat(mb/1000, 'f', 1, 64)
	}
	return strconv.FormatFloat(pyRound(mb/1000), 'f', 0, 64)
}

// wikiNote is kit.json's note for a Wikipedia: like English Wikipedia: all of it, with pictures (~127 GB).
func wikiNote(lang, edition string) string {
	mb := wikiEditions(lang)[edition]
	name := pyStr(regions().child("languages").child(lang).getOr("name", lang))
	note := name + " Wikipedia: " + editionLabels[edition]
	if mb != 0 {
		note += " (~" + gbText(mb) + " GB)"
	}
	return note
}

// wikiStandIns is what the try-it kit or the essentials (tier: a key of standIns) get of each Wikipedia kit.json
// switches on that isn't in the kit yet: a smaller edition that stands in for it until it's in
// (dropReplacedWikipedias), or itself if it's that small. As kit.json entries.
func wikiStandIns(cfg, state *obj, tier string) []*obj {
	want := standIns[tier]
	var out []*obj
	for _, z := range cfg.objs("library") {
		m := wikipediaRE.FindStringSubmatch(z.str("zim"))
		whole := isTrue(z.get("essential")) || intOr(z.getOr("priority", 2), 2) <= 1
		if tier == "starter" {
			whole = isTrue(z.get("starter"))
		}
		if m == nil || !z.on() || whole || stateItems(state).child("library/"+z.str("zim")).has("files") {
			continue // (a whole one comes anyway)
		}
		lang, chosen := m[1], m[2]
		e := wikiEdition(lang, want.edition)
		if e == "" {
			continue
		}
		if editionIndex(e) >= editionIndex(chosen) {
			e = chosen
		}
		if mb, ok := wikiEditions(lang)[e]; ok && mb <= want.mb {
			s := cloneObj(z)
			s.set("zim", "wikipedia_"+lang+"_"+e)
			s.set("enabled", true)
			if e != chosen {
				s.set("note", wikiNote(lang, e))
			}
			out = append(out, s)
		}
	}
	return out
}

type sizeChoice struct {
	name, label string
	mb          float64
}

// sizeChoices is the sizes of Wikipedia to offer in these languages, biggest first. Only the ones Kiwix makes in
// every one of them.
func sizeChoices(codes []string) []sizeChoice {
	var have []map[string]float64
	for _, c := range codes {
		have = append(have, wikiEditions(c))
	}
	var out []sizeChoice
	for _, ws := range wikiSizes {
		name, e := ws[0], ws[1]
		total, all := 0.0, len(have) > 0
		for _, h := range have {
			mb, ok := h[e]
			all = all && ok
			total += mb
		}
		if all {
			l := editionLabels[e]
			out = append(out, sizeChoice{name, strings.ToUpper(l[:1]) + l[1:], total})
		}
	}
	return out
}

func langNames(codes []string) string {
	var ns []string
	for _, c := range codes {
		ns = append(ns, pyStr(regions().child("languages").child(c).getOr("name", c)))
	}
	if len(ns) > 1 {
		return strings.Join(ns[:len(ns)-1], ", ") + " and " + ns[len(ns)-1]
	}
	return strings.Join(ns, "")
}

type langChoice struct {
	codes []string
	label string
	gb    int64
}

// languageChoices is Wikipedia's languages to offer for a place: each of its own, English, and its first two
// together. A small Wikipedia (under 1 GB) comes only with another, so nobody swaps English for a few thousand
// articles by mistake.
func languageChoices(r *obj) []langChoice {
	langs := regions().child("languages")
	var codes []string
	for _, c := range strs(r.list("langs")) {
		if langs.has(c) {
			codes = append(codes, c)
		}
	}
	if langs.has("en") && !contains(codes, "en") {
		codes = append(codes, "en")
	}
	var picks [][]string
	for _, c := range codes {
		if mb, _ := asNumber(langs.child(c).getOr("mb", 0)); c == "en" || mb >= 1000 {
			picks = append(picks, []string{c})
		}
	}
	if len(codes) > 1 {
		picks = append(picks, codes[:2])
	}
	var out []langChoice
	for _, p := range picks {
		label := langNames(p)
		if len(p) == 1 {
			name, native := pyStr(langs.child(p[0]).get("name")), pyStr(langs.child(p[0]).getOr("native", ""))
			label = name
			if native != "" && native != name {
				label = name + " (" + native + ")"
			}
		}
		total := 0.0
		for _, c := range p {
			mb, _ := asNumber(langs.child(c).getOr("mb", 0))
			total += mb
		}
		out = append(out, langChoice{p, label, max(1, int64(pyRound(total/1000)))})
	}
	return out
}

// describeWikipedia is like: English, all of it, with pictures (about 127 GB).
func describeWikipedia(cfg *obj) string {
	wiki, edition := wikipediaLangs(cfg), wikipediaEdition(cfg)
	if len(wiki) == 0 || edition == "" {
		return "none"
	}
	mb := 0.0
	for _, c := range wiki {
		mb += wikiEditions(c)[wikiEdition(c, edition)]
	}
	s := langNames(wiki) + ", " + editionLabels[edition]
	if mb != 0 {
		s += " (about " + gbText(mb) + " GB)"
	}
	return s
}

func describeRegion(cfg *obj) string {
	m := mapsSettings(cfg)
	region := cfg.child("maps").get("region")
	wiki, edition := wikipediaLangs(cfg), wikipediaEdition(cfg)
	where := pyStr(m.get("label"))
	if _, unknown := regionsOf(region); !truthy(region) || unknown != "" {
		where += " (set by hand in kit.json)"
	}
	maps := "Maps are switched off"
	if truthy(m.get("enabled")) {
		maps = "Maps are for " + where
	}
	if len(wiki) == 0 {
		return maps + ", with no Wikipedia."
	}
	if edition == "" {
		edition = "all_maxi"
	}
	return maps + ", and Wikipedia is in " + langNames(wiki) + ": " + editionLabels[edition] + "."
}

// withWikipedia is kit.json's library with its Wikipedia in these languages (nil: as they are) and this edition
// ("": as it is), in its place. The new entries keep the old one's settings (priority, refresh_days, enabled).
func withWikipedia(lib []any, codes []string, edition string) []any {
	var was []int
	var now [][]string
	for i, v := range lib {
		if z, ok := v.(*obj); ok {
			if m := wikipediaRE.FindStringSubmatch(z.str("zim")); m != nil {
				was = append(was, i)
				now = append(now, m)
			}
		}
	}
	if codes == nil {
		codes = []string{}
		for _, m := range now {
			if !contains(codes, m[1]) {
				codes = append(codes, m[1])
			}
		}
	}
	if edition == "" {
		edition = "all_maxi"
		if len(now) > 0 {
			edition = now[0][2]
		}
	}
	keep := newObj("priority", 2)
	if len(was) > 0 {
		keep = newObj()
		old := lib[was[0]].(*obj)
		for _, k := range old.Keys() {
			if k != "zim" && k != "note" {
				keep.set(k, old.get(k))
			}
		}
	}
	var fresh []any
	for _, c := range codes {
		if e := wikiEdition(c, edition); e != "" {
			z := newObj("zim", "wikipedia_"+c+"_"+e)
			for _, k := range keep.Keys() {
				z.set(k, keep.get(k))
			}
			z.set("note", wikiNote(c, e))
			fresh = append(fresh, z)
		}
	}
	at := len(lib)
	if len(was) > 0 {
		at = was[0]
	}
	var out []any
	for i, z := range lib {
		if !containsInt(was, i) {
			out = append(out, z)
		}
	}
	return append(append(append([]any{}, out[:min(at, len(out))]...), fresh...), out[min(at, len(out)):]...)
}

func containsInt(list []int, x int) bool {
	for _, v := range list {
		if v == x {
			return true
		}
	}
	return false
}

// rawConfig is data/kit.json as it is, without the standard list's settings filled in.
func rawConfig(root string) *obj {
	p := filepath.Join(dataDir(root), "kit.json")
	data, err := os.ReadFile(p)
	if err != nil {
		die(fmt.Sprintf("couldn't read %s: %s", p, strerror(err)))
	}
	v, err := parseJSON(data)
	var je *jsonError
	if errors.As(err, &je) {
		die(fmt.Sprintf("kit.json has a syntax error on line %d, column %d: %s", je.line, je.col, je.msg))
	}
	o, ok := v.(*obj)
	if !ok {
		die("kit.json has a syntax error on line 1, column 1: it isn't a list of settings in { }")
	}
	return o
}

func saveConfig(root string, raw *obj) {
	p := filepath.Join(dataDir(root), "kit.json")
	tmp := filepath.Join(dataDir(root), "kit.tmp")
	if err := os.WriteFile(tmp, []byte(dumps(raw, jsonStyle{indent: 2})+"\n"), 0o644); err != nil {
		die(fmt.Sprintf("couldn't save %s: %s", p, strerror(err)))
	}
	if err := replace(tmp, p); err != nil {
		die(fmt.Sprintf("couldn't save %s: %s", p, strerror(err)))
	}
}

// setRegion points kit.json's maps at places (none: leaves them), and its Wikipedia at these languages (nil: leaves
// them) and this edition ("": leaves it). One place is its id, several a list of them.
func setRegion(root string, rs []*obj, wiki []string, edition string) *obj {
	cfg := loadConfig(root)
	raw := rawConfig(root)
	if len(rs) > 0 {
		old := raw.child("maps")
		enabled := any(true)
		if old != nil {
			enabled = old.getOr("enabled", true)
		}
		var ids []any
		for _, r := range rs {
			ids = append(ids, r.get("id"))
		}
		region := any(ids)
		if len(ids) == 1 {
			region = ids[0]
		}
		maps := newObj("enabled", enabled, "region", region)
		for _, k := range old.Keys() {
			if !maps.has(k) && !contains(regionKeys, k) {
				maps.set(k, old.get(k))
			}
		}
		raw.set("maps", maps)
	}
	if wiki != nil || edition != "" {
		lib, _ := raw.getOr("library", []any{}).([]any)
		raw.set("library", withWikipedia(lib, wiki, edition))
	}
	saveConfig(root, raw)
	out := cloneObj(cfg)
	for _, k := range raw.Keys() {
		out.set(k, raw.get(k))
	}
	return out
}

func wikiSize(name string) string {
	for _, ws := range wikiSizes {
		if ws[0] == name {
			return ws[1]
		}
	}
	return ""
}

// cmdRegion is where you live, and any places nearby: it sets the map areas, the road data for directions, the
// address search, home, units and the language Wikipedia comes in. SETUP and the website's kit builder use it. Also
// how much of Wikipedia.
func cmdRegion(root string, a *cliArgs) {
	if len(regions().list("regions")) == 0 {
		die(regionsFile() + " is missing or broken; get the kit again (./kit update) to restore it")
	}
	if a.has("find") {
		for _, r := range findRegions(strings.Join(a.list("find"), " ")) {
			out(pyStr(r.get("id")) + "\t" + pyStr(r.get("name")) + "\t" + pyStr(r.get("group")) + "\n")
		}
		return
	}
	cfg := loadConfig(root)
	langs := regions().child("languages")
	var wiki []string
	edition := ""
	if w := a.str("wikipedia"); w != "" {
		wiki = []string{}
		var bad []string
		for _, c := range strings.Split(w, ",") {
			if c = strings.ToLower(strings.TrimSpace(c)); c != "" {
				wiki = append(wiki, c)
				if !langs.has(c) {
					bad = append(bad, c)
				}
			}
		}
		if len(bad) > 0 || len(wiki) == 0 {
			var all []string
			for _, c := range sortedKeys(langs) {
				all = append(all, c+" ("+pyStr(langs.child(c).get("name"))+")")
			}
			die("Wikipedia doesn't come in '" + strings.Join(bad, ",") + "' here. Languages: " + strings.Join(all, ", "))
		}
	}
	if s := a.str("wikipedia_size"); s != "" {
		edition = wikiSize(strings.ToLower(strings.TrimSpace(s)))
		if edition == "" {
			var ns []string
			for _, ws := range wikiSizes {
				ns = append(ns, ws[0])
			}
			die(fmt.Sprintf("Wikipedia doesn't come in a size called '%s'. The sizes: %s.", s, strings.Join(ns, ", ")))
		}
		if wiki == nil && wikipediaEdition(cfg) == "" {
			die("kit.json has no Wikipedia. Add one in a language: ./kit region --wikipedia CODES")
		}
	}
	if a.flag("sizes") { // for the languages given, or kit.json's
		codes := wiki
		if len(codes) == 0 {
			codes = wikipediaLangs(cfg)
		}
		for _, c := range sizeChoices(codes) {
			out(c.name + "\t" + c.label + "\t" + gbText(c.mb) + "\n")
		}
		return
	}
	place := a.list("place")
	if len(place) == 0 {
		rs, unknown := regionsOf(cfg.child("maps").get("region"))
		switch {
		case a.flag("languages"): // for the place kit.json has now
			if !truthy(cfg.child("maps").get("region")) || unknown != "" {
				die("kit.json has no region yet: ./kit region PLACE")
			}
			place = []string{pyStr(rs[0].get("id"))}
		case wiki != nil || edition != "":
			cfg = setRegion(root, nil, wiki, edition)
			log("Wikipedia: " + describeWikipedia(cfg) + ".")
			return
		default:
			out(describeRegion(cfg) + "\n")
			return
		}
	}
	rs := placesIn(strings.Join(place, " "))
	first := rs[0]
	if a.flag("languages") {
		for _, c := range languageChoices(first) {
			out(strings.Join(c.codes, ",") + "\t" + c.label + "\t" + strconv.FormatInt(c.gb, 10) + "\n")
		}
		return
	}
	cfg = setRegion(root, rs, wiki, edition)
	m := mapsSettings(cfg)
	label, name := pyStr(m.get("label")), pyStr(first.get("name"))
	log("Maps: " + label + ". Street maps and directions for " + label + ", and a simple map of the whole world.")
	switch {
	case !truthy(first.get("photon")):
		log("Address search: none, since nobody publishes it for " + name + " yet.")
	case truthy(first.get("addresses_wide")):
		mb, _ := asNumber(first.child("mb").getOr("addresses", 0))
		log(fmt.Sprintf("Address search: all of %s (about %d GB), since nobody publishes it for %s alone. Just the "+
			"essentials leave it out.", pyStr(first.get("addresses")), max(1, int64(pyRound(mb/1000))), name))
	default:
		where := first.get("addresses")
		if !truthy(where) {
			where = first.get("name")
		}
		log("Address search: all of " + pyStr(where) + ".")
	}
	// The address search is the first place's: it covers the others in its database (a country, or a whole region of
	// the world's), and not the rest.
	var left []string
	db := first.str("photon")
	for _, r := range rs[1:] {
		in := r.str("photon")
		if db == "" || in != db && !(truthy(first.get("addresses_wide")) && strings.HasPrefix(in, path.Dir(db)+"/")) {
			left = append(left, r.str("name"))
		}
	}
	if len(left) > 0 && db != "" {
		log("Not for " + names(left) + ": the kit has one address search, the first place's.")
	}
	if !truthy(m.get("enabled")) {
		log(`Maps are switched off in kit.json ("enabled": false under "maps"), so none of this downloads.`)
	}
	home := m.child("home").get("label")
	if !truthy(home) {
		home = "the middle of it"
	}
	log("Home: " + pyStr(home) + ". Directions and \"nearest\" searches start there; set your own on the Map tab.")
	log("Wikipedia: " + describeWikipedia(cfg) + ".")
}

// ----------------------------------------------------------------------------- how much room it takes

var yes, no = true, false

// estimateBytes is about how many bytes the switched-on items need, from the sizes the kit builder lists
// (site/sources.json), plus the programs. Needs no internet, so SETUP can say how much room the kit needs before
// choosing where. essentials, starter: only those (see essential() and starterPart()); nil: kit.json's
// essentials_only and starter_only decide. left: only what isn't in the kit yet.
func estimateBytes(root string, cfg *obj, essentials, starter *bool, left bool) float64 {
	s := cfg.child("settings")
	st := essentials == nil && isTrue(s.get("starter_only"))
	if starter != nil {
		st = *starter
	}
	ess := !st && isTrue(s.get("essentials_only"))
	if essentials != nil {
		ess = *essentials
	}
	state := loadState(root)
	have := map[string]bool{}
	if left {
		for _, k := range stateItems(state).Keys() {
			have[k] = true
		}
	}
	fit := newObj()
	if ess {
		fit = fitReport(root, cfg, state)
	}
	sizes := map[string]float64{}
	if listed, ok := sourcesList(root); ok {
		for _, src := range listed {
			sizes[pyStr(src.get("id"))], _ = asNumber(orZero(src.get("bytes")))
		}
	}
	// a place's maps, and Wikipedia in other languages and sizes, are sized in tools/regions.json
	for _, code := range regions().child("languages").Keys() {
		for e, mb := range wikiEditions(code) {
			if k := "wikipedia_" + code + "_" + e; !hasKey(sizes, k) {
				sizes[k] = mb * 1e6
			}
		}
	}
	maps := cfg.child("maps")
	rs, unknown := regionsOf(maps.get("region"))
	mapParts := [][2]string{{"maps/basemap", "tiles"}, {"maps/routing", "roads"}, {"maps/geocoder", "addresses"}}
	if truthy(maps.get("region")) && unknown == "" && !maps.has("detail_bbox") && !maps.has("routing_osm_pbf") &&
		!maps.has("geocoder_country") {
		wide := ess && truthy(rs[0].get("addresses_wide")) // see essential()
		for _, p := range mapParts {
			if !(wide && p[1] == "addresses") && !(st && p[1] != "tiles") {
				// each place's street detail and road data, with one world overview (1 GB in each place's tiles),
				// and the first place's address search
				var mb float64
				for i, r := range rs {
					n, _ := asNumber(r.child("mb").getOr(p[1], 0))
					if i == 0 || p[1] == "roads" {
						mb += n
					} else if p[1] == "tiles" {
						mb += max(0, n-GB/1e6)
					}
				}
				sizes[p[0]] = mb * 1e6
			}
		}
		sizes["maps/basemap"] += 0.1 * GB // plus the map viewer, fonts and icons
	} else {
		sizes["maps/basemap"] = sizes["maps"] // the builder's size, for its own area
	}
	some := func(section string) bool {
		for _, e := range cfg.objs(section) {
			if e.on() {
				return true
			}
		}
		return false
	}
	wanted := func(e *obj, important bool) bool {
		if st {
			return isTrue(e.get("starter"))
		}
		return e.on() && (!ess || isTrue(e.get("essential")) || important)
	}
	type part struct{ key, id string }
	var on []part
	for _, m := range cfg.objs("models") {
		id := pyStr(m.get("id"))
		if (!st || some("models")) && wanted(m, pyEqual(m.get("id"), fit.get("runs")) || pyEqual(m.get("id"), fit.get("smallest"))) {
			on = append(on, part{"models/" + id, id})
		}
	}
	for _, z := range cfg.objs("library") {
		if (!st || some("library")) && wanted(z, intOr(z.getOr("priority", 2), 2) <= 1) {
			on = append(on, part{"library/" + z.str("zim"), z.str("zim")})
		}
	}
	if st || ess {
		t := "essentials"
		if st {
			t = "starter"
		}
		for _, z := range wikiStandIns(cfg, state, t) {
			on = append(on, part{"library/" + z.str("zim"), z.str("zim")})
		}
	}
	if truthy(mapsSettings(cfg).get("enabled")) {
		for _, p := range mapParts {
			if hasKey(sizes, p[0]) {
				on = append(on, part{p[0], p[0]})
			}
		}
	}
	programs := 1.0 * GB
	if st {
		programs = 0.2 * GB
	}
	for k := range have {
		if strings.HasPrefix(k, "runtimes/") {
			programs = 0
		}
	}
	total := 0.0
	for _, p := range on {
		if !have[p.key] {
			total += sizes[p.id]
		}
	}
	return total + programs
}

func hasKey[V any](m map[string]V, k string) bool {
	_, ok := m[k]
	return ok
}

func estimateGB(root string, cfg *obj, essentials, starter *bool, left bool) int64 {
	return int64(math.Ceil(estimateBytes(root, cfg, essentials, starter, left) / GB))
}

func cmdEstimate(root string, a *cliArgs) {
	cfg := loadConfig(root)
	if a.flag("rest") { // what a try-it kit doesn't have yet
		left := estimateBytes(root, cfg, nil, &no, true)
		out(fmt.Sprintf("%d\t%s\n", int64(math.Ceil(left/GB)), eta(root, left)))
		return
	}
	var ess, st *bool
	if a.flag("essentials") {
		ess = &yes
	}
	if a.flag("starter") {
		st = &yes
	}
	out(fmt.Sprintf("%d\n", estimateGB(root, cfg, ess, st, false)))
}

// spaceAt is how the kit would fit at path (its folder, which may not exist yet): the disk's free and total bytes,
// what the kit keeps free there and what a comfortable install leaves, the full kit's size and the essentials', and
// for each of those "fits" (leaving that comfortable amount), "tight" (fits, but leaves less) or "no".
func spaceAt(path, root string, cfg *obj) *obj {
	at := path
	for !exists(at) && filepath.Dir(at) != at {
		at = filepath.Dir(at)
	}
	free, total := diskUsage(at)
	keep, leave := keepFree(at, cfg), leaveFree(at, cfg)
	var have int64
	if resolvePath(path) == resolvePath(root) { // the kit's own folder: what's downloaded already counts
		all := stateItems(loadState(root))
		for _, k := range all.Keys() {
			have += driveBytes(all.child(k))
		}
	}
	full := max(0, estimateGB(root, cfg, &no, nil, false)*GB-have)
	ess := max(0, estimateGB(root, cfg, &yes, nil, false)*GB-have)
	return newObj("path", path, "free_bytes", free, "total_bytes", total, "keeps_free_bytes", int64(keep),
		"leaves_free_bytes", int64(leave), "full_bytes", full, "essentials_bytes", ess, "full", room(free, full, keep, leave),
		"essentials", room(free, ess, keep, leave))
}

// expandUser is os.path.expanduser: ~ is the home folder.
func expandUser(p string) string {
	if p == "~" || strings.HasPrefix(p, "~/") || (windows && strings.HasPrefix(p, `~\`)) {
		if home, err := os.UserHomeDir(); err == nil {
			return home + p[1:]
		}
	}
	return p
}

func absPath(p string) string {
	abs, err := filepath.Abs(expandUser(p))
	if err != nil {
		return p
	}
	return abs
}

// cmdSpace prints one tab-separated line for scripts: the full kit's verdict, the essentials', then GB free, GB in
// all, GB the full kit and the essentials need, and GB a comfortable install leaves free.
func cmdSpace(root string, a *cliArgs) {
	sp := spaceAt(absPath(a.str("path")), root, loadConfig(root))
	if a.flag("json") {
		out(dumps(sp, jsonStyle{indent: 2, ascii: true}) + "\n")
		return
	}
	n := func(k string) int64 { return intOr(sp.get(k), 0) }
	ceil := func(k string) string { return strconv.FormatInt(int64(math.Ceil(float64(n(k))/GB)), 10) }
	out(strings.Join([]string{sp.str("full"), sp.str("essentials"), strconv.FormatInt(n("free_bytes")/GB, 10),
		strconv.FormatInt(int64(pyRound(float64(n("total_bytes"))/GB)), 10), ceil("full_bytes"), ceil("essentials_bytes"),
		ceil("leaves_free_bytes")}, "\t") + "\n")
}

func cmdEssentials(root string, a *cliArgs) {
	if act := a.str("action"); act != "" {
		setSetting(root, "essentials_only", map[bool]any{true: true, false: nil}[act == "on"])
	}
	cfg := loadConfig(root)
	if isTrue(cfg.child("settings").get("essentials_only")) {
		log(fmt.Sprintf("Just the essentials (about %d GB): the programs, the map, the most important books, and the AI "+
			"this computer runs plus the smallest. To get everything: ./kit essentials off", estimateGB(root, cfg, nil, nil, false)))
	} else {
		log(fmt.Sprintf("Everything switched on in kit.json (about %d GB). To get just the essentials: ./kit essentials on",
			estimateGB(root, cfg, nil, nil, false)))
	}
}

func cmdStarter(root string, a *cliArgs) {
	if act := a.str("action"); act != "" {
		setSetting(root, "starter_only", map[bool]any{true: true, false: nil}[act == "on"])
	}
	cfg := loadConfig(root)
	if isTrue(cfg.child("settings").get("starter_only")) {
		left := estimateBytes(root, cfg, nil, &no, true)
		took := eta(root, left)
		if took != "" {
			took = ": " + took
		}
		log(fmt.Sprintf("Just the try-it kit (about %d GB): a small AI, a few small books and the area's map. The rest is "+
			"about %d GB more%s. To get everything: ./kit starter off", estimateGB(root, cfg, nil, nil, false),
			int64(math.Ceil(left/GB)), took))
	} else {
		log(fmt.Sprintf("Everything switched on in kit.json (about %d GB). To get just the try-it kit: ./kit starter on",
			estimateGB(root, cfg, nil, nil, false)))
	}
}
