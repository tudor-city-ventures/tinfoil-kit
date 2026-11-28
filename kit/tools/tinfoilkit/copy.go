package main

// Making a copy of this kit on another drive, to give someone or keep as a spare: ./kit copy, and Make a copy on the
// kit page, which runs ./kit copy (data.go's /copy) and follows it in data/.kit/copy.json. A copy takes what this kit
// has downloaded, as much as fits: a preset, or each part picked. It's a kit of its own, for any computer: it always
// gets the programs for Macs, Windows and Linux, and its kit.json switches on just what it has, so SETUP there, online,
// keeps that up to date. Its drive must be exFAT, which all three use: one that isn't is erased first, as is one too
// full, and a kit already on it is replaced, but only once the person has typed the drive's name. Every file is read
// back from the drive once it's all there, since a failing drive, or a fake one that says it's bigger than it is,
// loses data only then; then the copy is started once from the drive. A card to print and keep with it says how to
// use it.

import (
	"bufio"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"fmt"
	"html"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unsafe"
)

// ----------------------------------------------------------------------------- what this kit has

// copyPart is something a copy can have: the programs, which always go, the map, its address search, an AI model, a
// book or an extra.
type copyPart struct {
	id, title, group, why string
	bytes                 int64 // what it takes on the drive
	priority              int64
	essential             bool
	keys                  []string  // its items in state.json
	files                 []copySrc // what it has here
}

// copySrc is a file or folder to copy, and where it goes in the copy's kit folder.
type copySrc struct {
	from, to string // to is slash-separated: downloads/library/water.zim
	size     int64
	dir      bool
	sum      string // the SHA-256 state.json has for it, if it has one
}

// exFAT gives every file and folder whole clusters: 128 KB each on a drive bigger than 32 GB.
const cluster = 128 * 1024

func filesBytes(files []copySrc) int64 {
	var n int64
	for _, f := range files {
		if f.dir {
			n += cluster
		} else {
			n += (f.size + cluster - 1) / cluster * cluster
		}
	}
	return n
}

// walkFiles is a file, or a folder and everything in it, as files to copy to "to". Not what computers leave in any
// folder. A link to a file is that file, and a link to a folder is left out (the kit makes neither).
func walkFiles(from, to string) []copySrc {
	var out []copySrc
	filepath.WalkDir(from, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		dst := to
		if rel, _ := filepath.Rel(from, p); rel != "." {
			if strings.HasPrefix(d.Name(), "._") || contains(junk, d.Name()) {
				if d.IsDir() {
					return filepath.SkipDir
				}
				return nil
			}
			dst = to + "/" + filepath.ToSlash(rel)
		}
		st, err := os.Stat(p)
		switch {
		case err != nil:
		case st.IsDir():
			if d.Type()&fs.ModeSymlink == 0 {
				out = append(out, copySrc{from: p, to: dst, dir: true})
			}
		case st.Mode().IsRegular():
			out = append(out, copySrc{from: p, to: dst, size: st.Size()})
		}
		return nil
	})
	return out
}

// leftover is what a sync leaves while it works (a download partway, a folder it builds or replaces) and what
// computers leave in any folder.
func leftover(name string) bool {
	for _, s := range []string{".partial", ".parts", ".aria2", ".old", ".new", ".tmp", ".build"} {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return strings.HasPrefix(name, "._") || contains(junk, name)
}

// copyFiles is what an item in state.json has on this drive: its files, or for a program the version in use and the
// file that names it, or for the roads and the address database all they unpacked into. None if any of it is gone.
func copyFiles(dl string, rec *obj) []copySrc {
	dest := pyStr(orEmpty(rec.get("dest")))
	if dest == "" || strings.Contains(dest, "..") {
		return nil
	}
	var names []string
	switch {
	case truthy(rec.get("current")):
		names = []string{"CURRENT", safeName(pyStr(rec.get("current")))}
	case rec.has("unpacked_size"):
		entries, err := os.ReadDir(filepath.Join(dl, filepath.FromSlash(dest)))
		if err != nil {
			return nil
		}
		for _, e := range entries {
			if !leftover(e.Name()) {
				names = append(names, e.Name())
			}
		}
	default:
		names = rec.child("files").Keys()
	}
	var out []copySrc
	for _, n := range names {
		p := filepath.Join(dl, filepath.FromSlash(dest), n)
		if !exists(p) {
			return nil
		}
		got := walkFiles(p, "downloads/"+dest+"/"+n)
		if len(got) == 1 && !got[0].dir {
			got[0].sum = pyStr(orEmpty(rec.child("files").child(n).get("sha256")))
		}
		out = append(out, got...)
	}
	return out
}

// appFiles is this kit's app folder as a copy gets it: what a release has, as copyApp copies it (a git checkout's also
// gets the license, README and THIRD-PARTY.md from beside its kit folder).
func appFiles(root string) []copySrc {
	app := appDir(root)
	out := []copySrc{{from: app, to: "app", dir: true}}
	entries, _ := os.ReadDir(app)
	for _, e := range entries {
		n := e.Name()
		if contains(keepNames, n) || n == "downloads" || n == "data" || strings.HasPrefix(n, "._") || contains(junk, n) {
			continue
		}
	files:
		for _, f := range walkFiles(filepath.Join(app, n), "app/"+n) {
			for _, part := range strings.Split(f.to, "/") {
				if contains(devBuilds, part) {
					continue files
				}
			}
			out = append(out, f)
		}
	}
	if checkout(root) && !exists(filepath.Join(root, ".git")) {
		for _, n := range []string{"LICENSE", "README.md", "THIRD-PARTY.md"} {
			if from := filepath.Join(filepath.Dir(root), n); isFile(from) && !exists(filepath.Join(app, n)) {
				out = append(out, copySrc{from: from, to: "app/" + n, size: fileSize(from)})
			}
		}
	}
	return out
}

// The computers a copy starts on, as bin/ names them, and as people do.
var copyComputers = [][2]string{{"macos-arm64", "Mac"}, {"windows-x64", "Windows"}, {"linux-x64", "Linux"}}

// copySystems is the computers these programs start a kit on: the kit's own program for each, and its library server.
func copySystems(programs *copyPart) []string {
	has := map[string]bool{}
	for _, f := range programs.files {
		has[f.to] = true
	}
	var out []string
	for _, c := range copyComputers {
		prog := "app/tools/tinfoilkit-" + c[0]
		if c[0] == "windows-x64" {
			prog += ".exe"
		}
		if has[prog] && contains(programs.keys, "runtimes/kiwix-tools-"+c[0]) {
			out = append(out, c[1])
		}
	}
	return out
}

// copyParts is what this kit has that a copy can take: the programs first, then the map, its address search, and the
// AI models, books and extras in kit.json's order. What's partly gone from the drive isn't offered.
func copyParts(root string, state, cfg *obj) []*copyPart {
	about := map[string]*obj{}
	if list, ok := sourcesList(root); ok {
		for _, s := range list {
			about[pyStr(s.get("id"))] = s
		}
	}
	conf := map[string]*obj{}
	var order []string
	kept := map[string]*obj{}
	for _, c := range wikiCompanions(cfg) {
		kept["library/"+c.main] = c.entry
	}
	for _, it := range itemsFromConfig(cfg) {
		conf[it.key()] = it.cfg
		order = append(order, it.key())
		if e := kept[it.key()]; e != nil { // the best articles kept for copies, after all of Wikipedia
			conf["library/"+e.str("zim")] = e
			order = append(order, "library/"+e.str("zim"))
		}
	}
	items := stateItems(state)
	for _, k := range sortedKeys(items) {
		if conf[k] == nil { // on the drive, though kit.json has it no more
			order = append(order, k)
		}
	}
	programs := &copyPart{id: "programs", title: "The programs", group: "Programs", files: appFiles(root)}
	theMap := &copyPart{id: "map", title: "Map", group: "Maps", priority: 1}
	addresses := &copyPart{id: "addresses", title: "Address search", group: "Maps", priority: 3,
		why: "Find an address, or a place by its name, on the map."}
	var rest []*copyPart
	directions := false
	for _, k := range order {
		rec := items.child(k)
		if rec == nil {
			continue
		}
		files := copyFiles(dlDir(root), rec)
		if len(files) == 0 {
			continue
		}
		section, id, _ := strings.Cut(k, "/")
		var p *copyPart
		switch {
		case k == "maps/geocoder": // (its server, which is small, goes with the map, as kit.json has it)
			p = addresses
		case section == "maps" || section == "runtimes" && (pyEqual(conf[k].get("requires"), "maps") ||
			strings.HasPrefix(id, "java-") || strings.HasPrefix(id, "pmtiles-") || id == "graphhopper" || id == "photon"):
			p = theMap
			directions = directions || k == "maps/routing"
		case section == "runtimes":
			p = programs
		case section == "models" || section == "library" || section == "extras":
			p = copyPartFor(section, id, conf[k], about)
			rest = append(rest, p)
		default:
			continue
		}
		p.keys = append(p.keys, k)
		p.files = append(p.files, files...)
	}
	label := pyStr(orEmpty(mapsSettings(cfg).get("label")))
	theMap.why = "Streets and places"
	if label != "" && label != "map region" {
		theMap.why += " in " + label
	}
	if directions {
		theMap.title, theMap.why = "Map with directions", theMap.why+", and directions by car or on foot"
	}
	theMap.why += "."
	programs.why = "The kit's page, and the programs that serve its books, AI and map"
	if s := copySystems(programs); len(s) > 0 {
		programs.why += ", for " + names(s)
	}
	programs.why += "."
	out := []*copyPart{programs}
	if theMap.keys != nil {
		out = append(out, theMap)
		if addresses.keys != nil {
			out = append(out, addresses)
		}
	}
	out = append(out, rest...)
	for _, p := range out {
		p.bytes = filesBytes(p.files)
	}
	return out
}

// noteSize is the size at the end of a kit.json note: "Dictionary (~8 GB)".
var noteSize = regexp.MustCompile(`\s*\((?:~|about |a few |small)[^()]*\)\s*$`)

// copyPartFor is an AI model, book or extra, with its title and what it's for from the kit builder's list.
func copyPartFor(section, id string, c *obj, about map[string]*obj) *copyPart {
	p := &copyPart{id: id, title: id, priority: intOr(c.getOr("priority", 2), 2)}
	if s := about[id]; s != nil {
		p.title, p.group, p.why = pyStr(s.getOr("title", id)), pyStr(orEmpty(s.get("group"))), pyStr(orEmpty(s.get("why")))
	} else if note := pyStr(orEmpty(c.get("note"))); note != "" {
		p.why = strings.TrimSpace(noteSize.ReplaceAllString(note, ""))
	}
	switch section {
	case "models":
		p.group = "AI models"
	case "extras":
		p.group, p.priority = "Extras", 3
	default:
		if w := wikipediaRE.FindStringSubmatch(id); w != nil {
			if about[id] == nil {
				p.title, p.group, p.why = "Wikipedia", "Reference", capitalize(editionLabels[w[2]])+"."
				if w[1] != "en" {
					p.title += " in " + langNames([]string{w[1]})
				}
			}
			p.essential = strings.HasPrefix(w[2], "top_") // the best articles, as the essentials have them
		}
		p.essential = p.essential || isTrue(c.get("essential")) || p.priority <= 1
		if p.group == "" {
			p.group = "More books"
		}
	}
	return p
}

func partsByID(parts []*copyPart) map[string]*copyPart {
	by := map[string]*copyPart{}
	for _, p := range parts {
		by[p.id] = p
	}
	return by
}

func isBook(p *copyPart) bool {
	return !contains([]string{"Programs", "Maps", "AI models", "Extras"}, p.group)
}

// smallestAI is the AI model a copy gets when it gets the AI: the smallest this kit has, which runs on the most
// computers.
func smallestAI(parts []*copyPart) *copyPart {
	var best *copyPart
	for _, p := range parts {
		if p.group == "AI models" && (best == nil || p.bytes < best.bytes) {
			best = p
		}
	}
	return best
}

// hasNotes is whether this kit has notes, a home or map pins of its own, which a copy can take.
func hasNotes(root string) bool {
	if b, err := os.ReadFile(filepath.Join(dataDir(root), "notes.txt")); err == nil && strings.TrimSpace(string(b)) != "" {
		return true
	}
	b, err := os.ReadFile(filepath.Join(dataDir(root), "places.json"))
	if err != nil {
		return false
	}
	p, _ := parseObj(bytes.TrimPrefix(b, []byte("\xef\xbb\xbf")))
	return len(p.list("pins")) > 0 || p.child("home") != nil
}

// ----------------------------------------------------------------------------- what goes, and where

// copyDrive is a drive a copy can go on, and the room it has for one.
type copyDrive struct {
	path, name, format string
	free, total        int64
	kit, partial       bool   // a kit on it, which a copy replaces; a copy that stopped partway, which one carries on
	mustErase          string // why it has to be erased first: its format, or a folder in the way
	room, erasedRoom   int64  // for a copy: as it is (with what the copy replaces), and once erased
}

// copySpace is a drive's free and total bytes. KIT_DRIVE_BYTES makes each test drive (in KIT_DRIVES) that big, with
// what's in its folder using that much of it.
func copySpace(p string) (free, total int64) {
	if n, err := strconv.ParseInt(os.Getenv("KIT_DRIVE_BYTES"), 10, 64); err == nil && os.Getenv("KIT_DRIVES") != "" {
		return max(0, n-dirBytes(p)), n
	}
	return diskUsage(p)
}

// fsName is a drive's format as people write it: a Mac says ExFAT, Linux exfat.
func fsName(format string) string {
	if strings.EqualFold(format, "exfat") {
		return "exFAT"
	}
	return format
}

// copyFormatProblem is why a copy can't stay in a drive's format: it must work on Macs, Windows and Linux.
func copyFormatProblem(format string) string {
	f := strings.ToLower(format)
	if p := driveProblem(format); p != "" {
		return p
	}
	switch {
	case strings.Contains(f, "apfs") || strings.Contains(f, "hfs") || strings.Contains(f, "mac os"):
		return "it's formatted as " + format + ", which only Macs use"
	case strings.Contains(f, "ntfs") || strings.Contains(f, "windows nt"):
		return "it's formatted as " + format + ", which Macs can't save to"
	}
	return ""
}

// copyDrives is the drives plugged in that a copy can go on: all but the one this kit is on.
func copyDrives(root string) []*copyDrive {
	var out []*copyDrive
	for _, d := range listDrives() {
		p := d.str("path")
		if samePath(p, root) || within(root, p) {
			continue
		}
		free, total := copySpace(p)
		c := &copyDrive{path: p, name: d.str("name"), format: fsName(d.str("format")), free: free, total: total}
		kit, partial := filepath.Join(p, kitFolder), filepath.Join(p, kitFolder+".partial")
		c.kit, c.partial = isKit(kit) && alone(kit), isDir(filepath.Join(partial, "data", ".kit"))
		var have int64
		if c.kit {
			have += dirBytes(kit)
		}
		if c.partial {
			have += dirBytes(partial)
		}
		margin := GB + total/100 // the copy's notes, logs and page, and room to breathe
		c.room, c.erasedRoom = max(0, free+have-margin), max(0, total-300_000_000-margin)
		switch c.mustErase = copyFormatProblem(c.format); {
		case c.mustErase != "":
		case exists(kit) && !isKit(kit):
			c.mustErase = "it has a folder called " + kitFolder + " that isn't a Tinfoil Kit"
		case exists(kit) && !c.kit: // the kit never deletes what isn't its own
			c.mustErase = "its " + kitFolder + " folder has other things in it besides the kit"
		case exists(partial) && !c.partial:
			c.mustErase = "it has a folder called " + kitFolder + ".partial that isn't a copy of a kit"
		}
		out = append(out, c)
	}
	return out
}

// canErase is whether the kit erases a drive itself: a Mac's diskutil needs no administrator for one plugged in.
func canErase() bool { return mac || os.Getenv("KIT_DRIVES") != "" }

var copyPresets = [][3]string{
	{"essentials", "Essentials", "The programs and the most important books: medicine, preparedness, water, food and repair."},
	{"maps", "Essentials plus maps", "The essentials, the map with directions, and its address search if there's room."},
	{"everything", "Everything that fits", "The most important first, until the drive is full."},
}

// copyWishes is what a preset takes, most important first, for copyFill to take as much of as fits: the programs, the
// AI if it goes, the essential books, then for maps the map and its address search, and for everything the map and
// the rest of the books, address search among them.
func copyWishes(parts []*copyPart, preset string, ai []string) []string {
	wishes := append([]string{"programs"}, ai...)
	var tiers [4][]string
	for _, p := range parts {
		switch {
		case !isBook(p) && p.group != "Extras":
		case p.group == "Extras":
			tiers[3] = append(tiers[3], p.id)
		case p.essential:
			tiers[0] = append(tiers[0], p.id)
		case p.priority <= 2:
			tiers[1] = append(tiers[1], p.id)
		default:
			tiers[2] = append(tiers[2], p.id)
		}
	}
	wishes = append(wishes, tiers[0]...)
	switch preset {
	case "maps":
		wishes = append(wishes, "map", "addresses")
	case "everything":
		wishes = append(append(append(wishes, "map"), tiers[1]...), "addresses")
		wishes = append(append(wishes, tiers[2]...), tiers[3]...)
	}
	return wishes
}

// copyFill takes each wish that still fits in room, in order. The programs go whatever the room, and address search
// only with the map. The kit page does the same (Kit.copyFill), so its presets match.
func copyFill(parts []*copyPart, wishes []string, room int64) (took []*copyPart, bytes int64) {
	by, in := partsByID(parts), map[string]bool{}
	for _, id := range wishes {
		p := by[id]
		if p == nil || in[id] || id == "addresses" && !in["map"] {
			continue
		}
		if id == "programs" || bytes+p.bytes <= room {
			took, in[id], bytes = append(took, p), true, bytes+p.bytes
		}
	}
	return took, bytes
}

// copyWords is what names in --only, --add, --skip and --models mean: a part's id (map, addresses, an AI model, a
// book, an extra), a whole part (models, books, extras), or the books whose name, up to its first underscore, is it
// (wikipedia) or has it between dots or dashes (stackexchange, water).
func copyWords(parts []*copyPart, said string) ([]string, error) {
	var out []string
	for _, word := range answerWords.Split(strings.TrimSpace(said), -1) {
		w := strings.ToLower(word)
		if w == "" {
			continue
		}
		var hits []string
		for _, p := range parts {
			id := strings.ToLower(p.id)
			first := strings.SplitN(id, "_", 2)[0]
			if id == w || w == "maps" && id == "map" || (w == "models" || w == "ai") && p.group == "AI models" ||
				(w == "books" || w == "library") && isBook(p) || w == "extras" && p.group == "Extras" ||
				isBook(p) && (first == w || contains(strings.FieldsFunc(first, func(r rune) bool { return r == '.' || r == '-' }), w)) {
				hits = append(hits, p.id)
			}
		}
		if hits == nil {
			return nil, fmt.Errorf("This kit has no %s to copy. %s lists what it has.", word, kitCmd("copy --json"))
		}
		out = append(out, hits...)
	}
	return out, nil
}

// copyChoice is what goes in a copy, and what that does to its drive.
type copyChoice struct {
	parts          []*copyPart
	left           []*copyPart // what the preset would take, with no room for it
	bytes          int64
	erase, replace bool // the drive is erased first; the kit on it is replaced
	notes          bool
}

// copyChoose is what goes in a copy: just these (only), or a preset with the AI, as much of it as fits, and these
// added, which must fit, or skipped. The room is the drive's as it is, or all of it if it must be erased, or the
// person said it may be. It erases the drive only if what goes needs that.
func copyChoose(parts []*copyPart, d *copyDrive, preset string, ai, only, add, skip []string, eraseOK bool) (*copyChoice, error) {
	room := d.room
	if d.mustErase != "" || eraseOK {
		room = max(room, d.erasedRoom)
	}
	by, ch, in := partsByID(parts), &copyChoice{}, map[string]bool{}
	var put func(id string)
	put = func(id string) {
		if p := by[id]; p != nil && !in[id] {
			if id == "addresses" {
				put("map")
			}
			ch.parts, in[id], ch.bytes = append(ch.parts, p), true, ch.bytes+p.bytes
		}
	}
	put("programs")
	var wishes []string
	if only != nil {
		wishes = only
	} else {
		for _, w := range copyWishes(parts, preset, ai) {
			if !contains(skip, w) {
				wishes = append(wishes, w)
			}
		}
		took, _ := copyFill(parts, wishes, room)
		for _, p := range took {
			put(p.id)
		}
		wishes = add
	}
	for _, id := range wishes {
		put(id)
	}
	if only == nil {
		for _, w := range copyWishes(parts, preset, ai) {
			if by[w] != nil && !in[w] && !contains(skip, w) {
				ch.left = append(ch.left, by[w])
			}
		}
	}
	ch.erase = d.mustErase != "" || ch.bytes > d.room
	ch.replace = !ch.erase && d.kit
	if ch.erase && ch.bytes > d.erasedRoom {
		return ch, fmt.Errorf("That's %s, and %s has room for %s, even erased. Pick less.", fmtBytes(ch.bytes), d.name,
			fmtBytes(d.erasedRoom))
	}
	return ch, nil
}

// copyLines is what goes in a copy, in words: a line for each part, the books on one line, then the notes.
func copyLines(ch *copyChoice) []string {
	var lines, books []string
	for _, p := range ch.parts {
		switch {
		case isBook(p):
			books = append(books, p.title)
		case p.id == "programs":
			lines = append(lines, "The programs, for "+names(append(copySystems(p), "")[:max(1, len(copySystems(p)))]))
		default:
			lines = append(lines, p.title)
		}
	}
	if len(books) == 1 {
		lines = append(lines, "1 book: "+books[0])
	} else if len(books) > 1 {
		lines = append(lines, fmt.Sprintf("%d books: %s", len(books), strings.Join(books, ", ")))
	}
	if ch.notes && ch.replace {
		lines = append(lines, "Your notes, home and map pins, if it has none of its own")
	} else if ch.notes {
		lines = append(lines, "Your notes, home and map pins")
	}
	return lines
}

// copyWarning is what a copy deletes on its drive, said before it does.
func copyWarning(d *copyDrive, ch *copyChoice) string {
	if !ch.erase {
		return d.name + " has a Tinfoil Kit already. The copy replaces it: what's the same stays, and so do its notes " +
			"and map pins."
	}
	why := fmt.Sprintf("%s has %s of room as it is, so it needs erasing first.", d.name, fmtBytes(d.room))
	if d.mustErase != "" {
		why = d.name + " needs erasing first: " + d.mustErase + ". Erasing it makes it exFAT, which Macs, Windows " +
			"and Linux all use."
	}
	goes := " Everything on " + d.name + " goes"
	if held := driveHolds(d.path); len(held) > 4 {
		goes += fmt.Sprintf(", including %s and %d more", strings.Join(held[:3], ", "), len(held)-3)
	} else if len(held) > 0 {
		goes += ", including " + names(held)
	}
	return why + goes + "."
}

// driveHolds is what's on a drive as a person sees it, for the warning before it's erased: not the system's hidden
// files and folders.
func driveHolds(path string) []string {
	entries, _ := os.ReadDir(path)
	var held []string
	for _, e := range entries {
		if n := e.Name(); !strings.HasPrefix(n, ".") && !strings.HasPrefix(n, "$") && n != "System Volume Information" {
			held = append(held, n)
		}
	}
	return held
}

// ----------------------------------------------------------------------------- erasing a drive

// eraseHow is how to erase a drive as exFAT by hand, for when the kit can't.
func eraseHow(d *copyDrive) string {
	switch {
	case windows:
		return "Windows erases a drive only with an administrator's OK, so erase it yourself: in File Explorer, " +
			"right-click " + d.name + ", choose Format, pick exFAT and click Start. Then make the copy again."
	case mac:
		return "Erase it yourself in Disk Utility: choose it, click Erase, and pick ExFAT and GUID Partition Map. " +
			"Then make the copy again."
	}
	return "Erasing a drive takes an administrator, so erase it yourself: in the Disks app, choose it, then Format " +
		"Partition, and pick exFAT. Then make the copy again."
}

// eraseDrive erases a drive as exFAT and returns where it's mounted now. A Mac does it with diskutil, and only to an
// external disk that holds nothing but this one drive, and is neither this Mac's own disk nor this kit's. A test's
// drive (KIT_DRIVES) is a folder, emptied.
func eraseDrive(root string, d *copyDrive) (string, error) {
	if os.Getenv("KIT_DRIVES") != "" {
		entries, err := os.ReadDir(d.path)
		for _, e := range entries {
			if err == nil {
				err = os.RemoveAll(filepath.Join(d.path, e.Name()))
			}
		}
		return d.path, err
	}
	if !mac {
		return "", errors.New(eraseHow(d))
	}
	disk, mounts := macDisk(d.path)
	if disk == "" {
		return "", fmt.Errorf("Couldn't tell which disk %s is. %s", d.name, eraseHow(d))
	}
	for _, m := range mounts {
		if !samePath(resolvePath(m), resolvePath(d.path)) {
			return "", fmt.Errorf("%s shares its disk with %s, which erasing would erase too. To erase just %s, use "+
				"Disk Utility. Then make the copy again.", d.name, filepath.Base(m), d.name)
		}
	}
	if boot, _ := macDisk("/"); boot == disk {
		return "", fmt.Errorf("%s is on this Mac's own disk, which the kit never erases.", d.name)
	}
	if mine, _ := macDisk(mountOf(root)); mine == disk {
		return "", fmt.Errorf("%s is on the same disk as this kit, which the kit never erases.", d.name)
	}
	if info := diskutil("info", "-plist", disk); info["Internal"] == true && info["Ejectable"] != true {
		return "", fmt.Errorf("%s is inside this Mac, and the kit erases only drives plugged into it.", d.name)
	}
	var said bytes.Buffer
	c := exec.Command("diskutil", "eraseDisk", "ExFAT", exfatLabel(d.name), "GPT", disk)
	c.Stdout, c.Stderr = &said, &said
	if err := run(c); err != nil {
		return "", fmt.Errorf("diskutil couldn't erase %s (%s). %s", d.name, lastLine(said.String()), eraseHow(d))
	}
	for i := 0; i < 60; i++ {
		if _, mounts := macDisk(disk); len(mounts) > 0 {
			return mounts[0], nil
		}
		sleep(time.Second)
	}
	return "", fmt.Errorf("%s is erased, but didn't come back. Unplug it, plug it in again, then make the copy again.", d.name)
}

// exfatLabel is a drive's name as exFAT can have it: 11 letters, digits, spaces, - or _ at most.
func exfatLabel(name string) string {
	var b strings.Builder
	for _, r := range name {
		if b.Len() < 11 && (r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || strings.ContainsRune(" -_", r)) {
			b.WriteRune(r)
		}
	}
	if s := strings.TrimSpace(b.String()); s != "" {
		return s
	}
	return "TINFOILKIT"
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	return strings.TrimSpace(lines[len(lines)-1])
}

// mountOf is the top of the disk a folder is on.
func mountOf(p string) string {
	p = resolvePath(p)
	for !isMount(p) && filepath.Dir(p) != p {
		p = filepath.Dir(p)
	}
	return p
}

var wholeDisk = regexp.MustCompile(`^disk\d+`)

// macDisk is the disk a volume or disk is on (disk4), past an APFS container to the disk that holds it, and every
// volume mounted from that disk.
func macDisk(where string) (disk string, mounts []string) {
	dev, _ := diskutil("info", "-plist", where)["DeviceIdentifier"].(string)
	return macDiskIn(dev, diskutil("list", "-plist"))
}

// macDiskIn is macDisk with what diskutil said: the device, and its list of disks.
func macDiskIn(dev string, list map[string]any) (disk string, mounts []string) {
	if disk = wholeDisk.FindString(dev); disk == "" {
		return "", nil
	}
	all := plistList(list["AllDisksAndPartitions"])
	stores := func(e map[string]any) []string { // the disks an APFS container is on
		var out []string
		for _, s := range plistList(e["APFSPhysicalStores"]) {
			if id, _ := plistMap(s)["DeviceIdentifier"].(string); id != "" {
				out = append(out, wholeDisk.FindString(id))
			}
		}
		return out
	}
	for _, e := range all {
		if m := plistMap(e); m["DeviceIdentifier"] == disk && len(stores(m)) > 0 {
			disk = stores(m)[0]
		}
	}
	for _, e := range all {
		m := plistMap(e)
		vols := []any{m} // a disk that's one volume, with no partitions
		if m["DeviceIdentifier"] == disk {
			vols = append(vols, plistList(m["Partitions"])...)
		} else if contains(stores(m), disk) {
			vols = append(vols, plistList(m["APFSVolumes"])...)
		} else {
			continue
		}
		for _, v := range vols {
			if mp, _ := plistMap(v)["MountPoint"].(string); mp != "" {
				mounts = append(mounts, mp)
			}
		}
	}
	return disk, mounts
}

// diskutil runs diskutil for what it says as a property list.
func diskutil(args ...string) map[string]any {
	stdout, _, rc := output("diskutil", args...)
	if rc != 0 {
		return nil
	}
	m, _ := plist(stdout).(map[string]any)
	return m
}

func plistMap(v any) map[string]any { m, _ := v.(map[string]any); return m }
func plistList(v any) []any         { l, _ := v.([]any); return l }

// plist reads a property list, as diskutil -plist writes one: dicts, arrays, strings, numbers (as strings) and true
// and false.
func plist(b []byte) any {
	d := xml.NewDecoder(bytes.NewReader(b))
	for {
		t, err := d.Token()
		if err != nil {
			return nil
		}
		if se, ok := t.(xml.StartElement); ok && se.Name.Local != "plist" {
			v, _ := plistValue(d, se)
			return v
		}
	}
}

func plistValue(d *xml.Decoder, se xml.StartElement) (any, error) {
	switch se.Name.Local {
	case "dict", "array":
		m, l, key := map[string]any{}, []any{}, ""
		for {
			t, err := d.Token()
			if err != nil {
				return nil, err
			}
			switch t := t.(type) {
			case xml.StartElement:
				if t.Name.Local == "key" {
					if err := d.DecodeElement(&key, &t); err != nil {
						return nil, err
					}
					continue
				}
				v, err := plistValue(d, t)
				if err != nil {
					return nil, err
				}
				if se.Name.Local == "dict" {
					m[key] = v
				} else {
					l = append(l, v)
				}
			case xml.EndElement:
				if se.Name.Local == "dict" {
					return m, nil
				}
				return l, nil
			}
		}
	case "true", "false":
		return se.Name.Local == "true", d.Skip()
	}
	var s string
	err := d.DecodeElement(&s, &se)
	return strings.TrimSpace(s), err
}

// ----------------------------------------------------------------------------- copying

// copyJob is a copy as it goes: shown in the terminal, and kept in data/.kit/copy.json for the kit page.
type copyJob struct {
	file               string
	rec                *obj
	wrote, since       time.Time
	tty                bool
	done, total, tenth int64
}

func newCopyJob(root string) *copyJob {
	return &copyJob{file: filepath.Join(metaDir(root), "copy.json"), tty: isTerminal(os.Stdout),
		rec: newObj("step", "starting", "started", nowISO(), "pid", os.Getpid())}
}

// set changes what the page reads, and saves it.
func (j *copyJob) set(kv ...any) {
	for i := 0; i+1 < len(kv); i += 2 {
		j.rec.set(kv[i].(string), kv[i+1])
	}
	j.wrote = time.Now()
	j.rec.set("updated", nowISO())
	os.MkdirAll(filepath.Dir(j.file), 0o755)
	tmp := strings.TrimSuffix(j.file, ".json") + ".tmp"
	if os.WriteFile(tmp, []byte(dumps(j.rec, jsonStyle{indent: 2, ascii: true})+"\n"), 0o644) == nil {
		replace(tmp, j.file)
	}
}

// step starts a step: what it does, and how many bytes it goes through.
func (j *copyJob) step(name, say string, total int64) {
	j.endLine()
	if say != "" {
		log(say)
	}
	j.done, j.total, j.since, j.tenth = 0, total, time.Now(), 0
	j.set("step", name, "done", 0, "total", total, "file", "", "rate", 0, "left", "")
}

// add counts bytes copied or read, and shows how it's going a few times a second.
func (j *copyJob) add(n int64, file string) {
	j.done += n
	if time.Since(j.wrote) < 500*time.Millisecond {
		return
	}
	rate := 0.0
	if secs := time.Since(j.since).Seconds(); secs > 2 {
		rate = float64(j.done) / secs
	}
	left := ""
	if rate > 0 && j.total > j.done {
		left = fmtTime(float64(j.total-j.done) / rate)
	}
	j.set("done", j.done, "file", file, "rate", int64(rate), "left", left)
	line := progressLine(j.done, j.total, 0, rate, 0)
	if j.tty {
		cols := terminalWidth()
		if cols < 20 {
			cols = 80
		}
		out("\r" + padRight(clip(line, cols-1), cols-1))
	} else if t := j.done * 10 / max(j.total, 1); t > j.tenth {
		j.tenth = t
		log(line)
	}
}

func (j *copyJob) endLine() {
	if j.tty && j.total > 0 {
		cols := terminalWidth()
		if cols < 20 {
			cols = 80
		}
		out("\r" + strings.Repeat(" ", cols-1) + "\r")
	}
	j.total = 0
}

func (j *copyJob) fail(msg string) {
	j.endLine()
	j.set("step", "failed", "message", msg)
	die(msg)
}

// copier copies files into the copy's folder, hashing what it reads, and keeps what each should read back as.
type copier struct {
	job  *copyJob
	to   string // the copy's kit folder, while it's TinfoilKit.partial
	buf  []byte
	sums map[string]string // each file of the copy (slash-separated) and its SHA-256
	from map[string]string // and where it came from
}

// damaged is a file of this kit's that isn't what it was when it downloaded.
type damaged struct{ file string }

func (e *damaged) Error() string { return e.file + " isn't what it was when it downloaded" }

// copy copies one file, or keeps what's there already if it's the same size (a copy that stopped partway, or the
// kit it replaces): reading it all back checks it.
func (c *copier) copy(f copySrc) error {
	dst := filepath.Join(c.to, filepath.FromSlash(f.to))
	if f.dir {
		return os.MkdirAll(dst, 0o755)
	}
	c.from[f.to] = f.from
	if st, err := os.Stat(dst); err == nil && st.Mode().IsRegular() && st.Size() == f.size {
		sum := f.sum
		if sum == "" {
			if sum, err = c.hash(f.from, f.to, false); err != nil {
				return err
			}
		} else {
			c.job.add(f.size, f.to)
		}
		c.sums[f.to] = sum
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	sum, err := c.write(f.from, dst, f.to)
	if err != nil {
		return err
	}
	if f.sum != "" && sum != f.sum {
		os.Remove(dst)
		return &damaged{f.to}
	}
	c.sums[f.to] = sum
	return nil
}

// write copies a file, hashing it as it goes. What it writes stays out of the computer's memory (noCache, dropCache),
// so reading it back reads the drive.
func (c *copier) write(src, dst, shown string) (string, error) {
	in, err := os.Open(src)
	if err != nil {
		return "", err
	}
	defer in.Close()
	o, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return "", err
	}
	defer o.Close()
	noCache(o)
	h := sha256.New()
	for {
		checkStop()
		n, err := in.Read(c.buf)
		if n > 0 {
			h.Write(c.buf[:n])
			if _, err := o.Write(c.buf[:n]); err != nil {
				return "", err
			}
			c.job.add(int64(n), shown)
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", err
		}
	}
	if err := dropCache(o); err != nil {
		return "", err
	}
	if err := o.Close(); err != nil {
		return "", err
	}
	if st, err := in.Stat(); err == nil {
		os.Chmod(dst, st.Mode().Perm())
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// hash reads a file through and returns its SHA-256: straight from the drive when it's the copy's (fresh), or as the
// computer can if it can't read that drive that way.
func (c *copier) hash(p, shown string, fresh bool) (string, error) {
	if fresh {
		if sum, got, err := c.hashWith(openFresh, p, shown); err == nil || got > 0 {
			return sum, err
		}
	}
	sum, _, err := c.hashWith(os.Open, p, shown)
	return sum, err
}

func (c *copier) hashWith(open func(string) (*os.File, error), p, shown string) (string, int64, error) {
	f, err := open(p)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return "", 0, err
	}
	h, got := sha256.New(), int64(0)
	for got < st.Size() { // and no further: reading past the end in whole sectors is an error on Windows
		checkStop()
		n, err := f.Read(c.buf)
		h.Write(c.buf[:n])
		got += int64(n)
		c.job.add(int64(n), shown)
		if err == io.EOF {
			break
		}
		if err != nil {
			return "", got, err
		}
	}
	return hex.EncodeToString(h.Sum(nil)), got, nil
}

// alignedBuffer is n bytes of memory that start on a 4 KB boundary, as reading whole sectors on Windows needs.
func alignedBuffer(n int) []byte {
	b := make([]byte, n+4096)
	off := int(-uintptr(unsafe.Pointer(&b[0])) & 4095)
	return b[off : off+n]
}

// made notes a file the copy wrote itself (its kit.json, its records, its page), to read back with the rest.
func (c *copier) made(rel string) error {
	sum, err := sha256File(filepath.Join(c.to, filepath.FromSlash(rel)))
	if err == nil {
		c.sums[rel] = sum
	}
	return err
}

// check reads back these files of the copy, and returns the ones that aren't what went in.
func (c *copier) check(files []string) []string {
	var bad []string
	for _, rel := range files {
		if got, err := c.hash(filepath.Join(c.to, filepath.FromSlash(rel)), rel, true); err != nil || got != c.sums[rel] {
			bad = append(bad, rel)
		}
	}
	return bad
}

// pruneCopy takes out of the copy's app and downloads folders what the copy won't have: what a copy that stopped
// partway had, or the kit it replaces. Its data folder stays: what the copy writes there replaces what's there.
func pruneCopy(work string, files []copySrc) {
	want := map[string]bool{"app": true, "downloads": true}
	for _, f := range files {
		for p := f.to; p != "." && !want[p]; p = path.Dir(p) {
			want[p] = true
		}
	}
	for _, top := range []string{"app", "downloads"} {
		var gone []string
		filepath.WalkDir(filepath.Join(work, top), func(p string, d fs.DirEntry, err error) error {
			rel, _ := filepath.Rel(work, p)
			if err == nil && !want[filepath.ToSlash(rel)] {
				gone = append(gone, p)
				if d.IsDir() {
					return filepath.SkipDir
				}
			}
			return nil
		})
		for _, p := range gone {
			os.RemoveAll(p)
		}
	}
}

// copyFailed is what to tell the person when copying stops partway.
func copyFailed(err error, p *copyPart, d *copyDrive) string {
	var bad *damaged
	if errors.As(err, &bad) {
		return fmt.Sprintf("This kit's own copy of %s is damaged: %s. Run %s here, then SETUP while online to get it "+
			"again, or leave it out of the copy.", p.title, bad.file, kitCmd("verify --fix"))
	}
	return fmt.Sprintf("Copying %s stopped partway: %s. Is %s still plugged in? Make the copy again to carry on where it "+
		"left off.", p.title, errText(err), d.name)
}

// runCopy makes the copy: erases the drive first if it must, copies into TinfoilKit.partial there (carrying on with
// one a copy left, or with the kit it replaces), writes the copy's own data, reads every file back, names it
// TinfoilKit and starts it once. Returns where it is.
func runCopy(root string, cfg *obj, d *copyDrive, ch *copyChoice, j *copyJob) string {
	where := d.path
	if ch.erase {
		j.step("erasing", "Erasing "+d.name+" as exFAT...", 0)
		p, err := eraseDrive(root, d)
		if err != nil {
			j.fail(err.Error())
		}
		where = p
		j.set("path", where)
	}
	final, work := filepath.Join(where, kitFolder), filepath.Join(where, kitFolder+".partial")
	if ch.replace && isKit(final) && alone(final) {
		os.RemoveAll(work)
		if err := os.Rename(final, work); err != nil {
			j.fail("Couldn't replace the kit on " + d.name + ": " + errText(err) + ".")
		}
	}
	if err := os.MkdirAll(filepath.Join(work, "data", ".kit"), 0o755); err != nil {
		j.fail(fmt.Sprintf("Couldn't save anything on %s: %s.", d.name, errText(err)))
	}
	var files []copySrc
	var total, need int64
	for _, p := range ch.parts {
		files = append(files, p.files...)
	}
	pruneCopy(work, files)
	for _, f := range files {
		if !f.dir {
			total += f.size
			if fileSize(filepath.Join(work, filepath.FromSlash(f.to))) != f.size {
				need += f.size
			}
		}
	}
	if free, _ := copySpace(where); need > free {
		j.fail(fmt.Sprintf("%s has %s free now, and the copy needs %s more. Pick less, then make the copy again.",
			d.name, fmtBytes(free), fmtBytes(need)))
	}
	c := &copier{job: j, to: work, buf: alignedBuffer(8 << 20), sums: map[string]string{}, from: map[string]string{}}
	j.step("copying", fmt.Sprintf("Copying %s to %s...", fmtBytes(total), d.name), total)
	for _, p := range ch.parts {
		for _, f := range p.files {
			if err := c.copy(f); err != nil {
				j.fail(copyFailed(err, p, d))
			}
		}
	}
	if err := copyData(root, cfg, work, ch, c, d); err != nil {
		j.fail(fmt.Sprintf("Couldn't save the copy's settings on %s: %s.", d.name, errText(err)))
	}
	var all []string
	var size int64
	for rel := range c.sums {
		all = append(all, rel)
		size += fileSize(filepath.Join(work, filepath.FromSlash(rel)))
	}
	sort.Strings(all)
	j.step("checking", "Reading every file back from "+d.name+" to check it...", size)
	if bad := c.check(all); len(bad) > 0 {
		j.endLine()
		log(fmt.Sprintf("  %d of them didn't read back as they went in. Copying those again...", len(bad)))
		var again int64
		for _, rel := range bad {
			again += fileSize(c.from[rel])
		}
		j.step("checking", "", 2*again)
		for _, rel := range bad {
			if src := c.from[rel]; src != "" {
				if sum, err := c.write(src, filepath.Join(work, filepath.FromSlash(rel)), rel); err != nil || sum != c.sums[rel] {
					continue // (the check says)
				}
			}
		}
		if bad = c.check(bad); len(bad) > 0 {
			j.fail(fmt.Sprintf("%d files on %s didn't read back as they went in, even copied again (%s). The drive may be "+
				"failing, or smaller than it says. Try another drive.", len(bad), d.name, bad[0]))
		}
	}
	j.endLine()
	log(fmt.Sprintf("All %s files read back right.", thousands(len(all))))
	if err := os.Rename(work, final); err != nil {
		j.fail(fmt.Sprintf("Couldn't name the copy %s on %s: %s.", kitFolder, d.name, errText(err)))
	}
	prepareFolder(final)
	return final
}

// copyData writes the copy's own data folder: its kit.json, which is this kit's with just what the copy has switched
// on; its records (state.json, and the standard list kit.json last took in, for merging a new version's); the notes
// and pins if they go, but never over a kit's own; its page, INVENTORY.md and the card; and the launchers beside its
// three folders.
func copyData(root string, cfg *obj, work string, ch *copyChoice, c *copier, d *copyDrive) error {
	in := map[string]bool{}
	var models []string
	for _, p := range ch.parts {
		for _, k := range p.keys {
			in[k] = true
		}
		if p.group == "AI models" {
			models = append(models, p.id)
		}
	}
	if err := copyFile(filepath.Join(dataDir(root), "kit.json"), filepath.Join(work, "data", "kit.json")); err != nil {
		return err
	}
	var sw changes
	for _, s := range []string{"models", "library", "extras"} {
		for _, e := range cfg.objs(s) {
			id := pyStr(e.get(partKey(s)))
			if on := in[s+"/"+id]; on != e.on() {
				sw.set(entry{s, id}, on)
			}
		}
	}
	mapOn := in["maps/basemap"]
	if mapOn != truthy(mapsSettings(cfg).get("enabled")) {
		sw.set(entry{"maps", "maps"}, mapOn)
	}
	if len(sw) > 0 {
		switchParts(work, sw, nil)
	}
	copyWikipedia(work, in)
	if mapOn && !in["maps/geocoder"] && truthy(mapsSettings(cfg).get("geocoder_country")) {
		if err := mapsSetting(work, "geocoder_country", ""); err != nil { // no address search
			return err
		}
	}
	set := [][2]any{{"picked", true}}
	for _, k := range []string{"essentials_only", "starter_only"} { // what's switched on is what it has
		if cfg.child("settings").has(k) {
			set = append(set, [2]any{k, nil})
		}
	}
	if truthy(cfg.child("settings").get("share_on_network")) { // someone else's home network
		set = append(set, [2]any{"share_on_network", false})
	}
	if def := pyStr(cfg.child("settings").get("default_model")); len(models) > 0 && !contains(models, def) {
		set = append(set, [2]any{"default_model", models[0]})
	}
	for _, s := range set {
		if err := saveSetting(work, s[0].(string), s[1]); err != nil {
			return err
		}
	}
	if base := filepath.Join(metaDir(root), "kit.base.json"); isFile(base) {
		if err := copyFile(base, filepath.Join(work, "data", ".kit", "kit.base.json")); err != nil {
			return err
		}
	}
	state, items := newObj("version", 1, "items", newObj()), stateItems(loadState(root))
	if v := loadState(root).get("last_sync"); v != nil {
		state.set("last_sync", v)
	}
	for _, k := range sortedKeys(items) {
		if in[k] {
			rec := cloneObj(items.child(k))
			if truthy(rec.get("current")) { // just the version in use goes
				rec.set("versions", []any{rec.get("current")})
			}
			stateItems(state).set(k, rec)
		}
	}
	saveState(work, state)
	if ch.notes {
		for _, n := range []string{"notes.txt", "places.json"} {
			from := filepath.Join(dataDir(root), n)
			if isFile(from) && !exists(filepath.Join(work, "data", n)) {
				if err := c.copy(copySrc{from: from, to: "data/" + n, size: fileSize(from)}); err != nil {
					return err
				}
			}
		}
	}
	writeInventory(work, state)
	if _, err := buildPortal(work, loadConfig(work)); err != nil {
		return err
	}
	if checkout(root) { // as copyApp does
		if head, _, rc := output("git", "-C", root, "rev-parse", "HEAD"); rc == 0 && commitLine.Match(bytes.TrimSpace(head)) {
			if err := os.WriteFile(filepath.Join(work, "app", "tools", "commit"), append(bytes.TrimSpace(head), '\n'), 0o644); err != nil {
				return err
			}
			c.made("app/tools/commit")
		}
	}
	if err := os.WriteFile(filepath.Join(work, "data", ".kit", "card.html"), []byte(copyCard(d.name, ch)), 0o644); err != nil {
		return err
	}
	ensureTop(work)
	made := []string{"data/kit.json", "data/.kit/state.json", "data/.kit/portal.html", "data/.kit/card.html",
		"downloads/INVENTORY.md"}
	for _, rel := range append([]string{"data/.kit/kit.base.json", "data/.kit/top.json"}, topNames()...) {
		if isFile(filepath.Join(work, filepath.FromSlash(rel))) {
			made = append(made, rel)
		}
	}
	for _, rel := range made {
		if err := c.made(rel); err != nil {
			return err
		}
	}
	return nil
}

func topNames() []string {
	var out []string
	for _, f := range topFiles {
		out = append(out, f.name)
	}
	return out
}

// copyWikipedia points the copy's kit.json at the Wikipedia it has in each language: when kit.json's own didn't go,
// the smaller one that did (the best articles kept for copies, or one standing in), switched on.
func copyWikipedia(work string, in map[string]bool) {
	raw := rawConfig(work)
	lib, _ := raw.getOr("library", []any{}).([]any)
	listed := map[string]bool{}
	for _, v := range lib {
		if z, ok := v.(*obj); ok {
			listed[z.str("zim")] = true
		}
	}
	changed := false
	for _, v := range lib {
		z, ok := v.(*obj)
		if !ok {
			continue
		}
		m := wikipediaRE.FindStringSubmatch(z.str("zim"))
		if m == nil || in["library/"+z.str("zim")] {
			continue
		}
		for i := len(editions) - 1; i >= 0; i-- {
			if zim := "wikipedia_" + m[1] + "_" + editions[i]; in["library/"+zim] && !listed[zim] {
				z.set("zim", zim)
				z.set("note", wikiNote(m[1], editions[i]))
				z.del("enabled")
				listed[zim], changed = true, true
				break
			}
		}
	}
	if changed {
		saveConfig(work, raw)
	}
}

// mapsSetting sets one of kit.json's map settings, keeping the rest of the file as it is.
func mapsSetting(root, key string, value any) error {
	p := filepath.Join(dataDir(root), "kit.json")
	data, err := os.ReadFile(p)
	if err != nil {
		return err
	}
	text, val := string(data), dumpsLine(value)
	fresh, done := subFirst(regexp.MustCompile(`("`+regexp.QuoteMeta(key)+`"\s*:\s*)(?:"(?:[^"\\]|\\.)*"|[^,}\s]+)`), text,
		func(m []string) string { return m[1] + val })
	if !done {
		fresh, done = subFirst(regexp.MustCompile(`("maps"\s*:\s*\{)(\s*)`), text, func(m []string) string {
			return m[1] + m[2] + `"` + key + `": ` + val + "," + m[2]
		})
	}
	cfg, err := parseObj(data)
	if err != nil {
		return err
	}
	if cfg.child("maps") == nil {
		cfg.set("maps", newObj())
	}
	cfg.child("maps").set(key, value)
	if v, err := parseJSON([]byte(fresh)); !done || err != nil || !pyEqual(v, cfg) { // a layout this doesn't know
		fresh = dumps(cfg, jsonStyle{indent: 2}) + "\n"
	}
	return saveText(p, fresh)
}

// copyTest runs the copy's own ./kit test, from the drive: its program for this computer, with servers on ports of
// their own, so a kit open here keeps running. Returns whether it passed, and the first check that failed.
func copyTest(kit string, j *copyJob) (bool, string) {
	prog := filepath.Join(kit, "app", "tools", "tinfoilkit-"+plat())
	if windows {
		prog += ".exe"
	}
	if !isFile(prog) {
		log("  (the copy has no program for " + this + " to start it with)")
		return true, ""
	}
	c := exec.Command(prog, "--root", kit, "test")
	pipe, err := c.StdoutPipe()
	if err != nil {
		return false, errText(err)
	}
	c.Stderr = c.Stdout
	if err := c.Start(); err != nil {
		return false, errText(err)
	}
	var lines []any
	failed := ""
	sc := bufio.NewScanner(pipe)
	for sc.Scan() {
		line := strings.TrimRight(sc.Text(), " \r")
		if line == "" || strings.HasPrefix(line, "Platform:") {
			continue
		}
		log("  " + line)
		if lines = append(lines, line); len(lines) > 40 {
			lines = lines[1:]
		}
		if t := strings.TrimSpace(line); failed == "" && strings.HasPrefix(t, "FAIL") {
			failed = strings.TrimSpace(strings.TrimPrefix(t, "FAIL"))
		}
		j.set("lines", lines)
	}
	err = c.Wait()
	checkStop()
	if err != nil && failed == "" {
		failed = "it stopped: " + errText(err)
	}
	return err == nil, failed
}

// copyCard is the page to print and keep with a copy: how to start it, and what's on it.
func copyCard(drive string, ch *copyChoice) string {
	var systems, have, books []string
	ai, maps := "", ""
	for _, p := range ch.parts {
		switch {
		case p.id == "programs":
			systems = copySystems(p)
		case p.group == "AI models" && ai == "":
			ai = p.title
		case p.id == "map":
			maps = p.title + ": " + strings.TrimSuffix(p.why, ".")
		case p.id == "addresses":
			maps += ", and address search"
		case isBook(p):
			books = append(books, html.EscapeString(p.title))
		}
	}
	if ai != "" {
		have = append(have, "Ask and AI chat, with the AI "+html.EscapeString(ai))
	} else {
		have = append(have, "Ask, which finds answers in the books (there's no AI on this drive)")
	}
	if maps != "" {
		have = append(have, html.EscapeString(maps))
	}
	if len(books) > 0 {
		have = append(have, fmt.Sprintf("%d books: %s", len(books), strings.Join(books, ", ")))
	}
	start := map[string]string{
		"Mac": "Plug in the drive and open it, open the TinfoilKit folder, and double-click <b>Open Tinfoil Kit.command</b>. " +
			"If your Mac asks whether Terminal may use files on a removable volume, click Allow.",
		"Windows": "Plug in the drive and open it, open the TinfoilKit folder, and double-click <b>Open Tinfoil Kit for " +
			"Windows</b>.",
		"Linux": "Open a terminal in the drive's TinfoilKit folder and type <code>bash \"Open Tinfoil Kit.command\"</code>",
	}
	var rows strings.Builder
	for _, s := range systems {
		rows.WriteString("<dt>" + s + "</dt><dd>" + start[s] + "</dd>\n")
	}
	var kinds []string // what's on it, for the line under the name: just what this copy has
	if ai != "" {
		kinds = append(kinds, "an AI")
	}
	if len(books) > 0 {
		kinds = append(kinds, "a library")
	}
	if maps != "" {
		kinds = append(kinds, "maps")
	}
	lead := "A Tinfoil Kit that works without the internet"
	if len(kinds) > 0 {
		verb := " that work"
		if len(kinds) == 1 && kinds[0] != "maps" {
			verb = " that works"
		}
		lead = names(kinds)
		lead = strings.ToUpper(lead[:1]) + lead[1:] + verb + " without the internet"
	}
	return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tinfoil Kit: how to use this drive</title>
<style>
  @page { margin: 14mm; }
  html { background: #f4efe6; color: #1b1a17; font: 11pt/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  body { max-width: 44em; margin: 0 auto; padding: 1.5em 1.25em; }
  h1 { font-size: 24pt; margin: 0; letter-spacing: -0.01em; }
  .bar { height: 6px; background: #e8590c; margin: 0.7em 0 1em; }
  h2 { font-size: 10.5pt; text-transform: uppercase; letter-spacing: 0.08em; margin: 1.3em 0 0.4em; padding-bottom: 0.2em; border-bottom: 1px solid #cfc6b6; }
  dl { display: grid; grid-template-columns: 5.5em 1fr; gap: 0.4em 1em; margin: 0; }
  dt { font-weight: 700; }
  dd, ul, p { margin: 0; }
  ul { padding-left: 1.2em; }
  li + li { margin-top: 0.25em; }
  p + p, dl + p { margin-top: 0.6em; }
  code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.95em; }
  .small { color: #5d574d; font-size: 9pt; margin-top: 1.6em; }
  .print { margin-bottom: 1.2em; }
  .print button { font: inherit; padding: 0.4em 1em; border: 1px solid #1b1a17; border-radius: 4px; background: #e8590c; color: #fff; cursor: pointer; }
  @media print { .print { display: none; } html { background: #fff; } }
</style>
</head>
<body>
<p class="print"><button onclick="print()">Print this card</button> and keep it with the drive.</p>
<h1>Tinfoil Kit</h1>
<p>` + lead + `, all on the drive <b>` + html.EscapeString(drive) + `</b>.</p>
<div class="bar"></div>
<h2>Start it</h2>
<dl>
` + rows.String() + `</dl>
<p>A window opens, then the kit's page in your web browser. No internet needed. Keep the window open while you use the kit: closing it stops the kit.</p>
<h2>What's on it</h2>
<ul>
<li>` + strings.Join(have, "</li>\n<li>") + `</li>
</ul>
<h2>Look after it</h2>
<ul>
<li>Eject the drive before you unplug it.</li>
<li>Your notes and map pins stay on the drive, in its data folder.</li>
<li>When you have internet, open the app folder and double-click SETUP (SETUP-Windows on Windows) to get newer books and maps.</li>
</ul>
<p class="small">Made ` + time.Now().Format("January 2, 2006") + `. Windows and Linux are experimental for now: tested less than the Mac. tinfoilkit.com</p>
</body>
</html>
`
}

// ----------------------------------------------------------------------------- ./kit copy

// copyInfo is what Make a copy on the kit page shows, and ./kit copy --json prints: what this kit has, the presets,
// and the drives a copy can go on, with the room on each.
func copyInfo(root string, parts []*copyPart) *obj {
	ps, presets, drives := []any{}, []any{}, []any{}
	for _, p := range parts {
		ps = append(ps, newObj("id", p.id, "title", p.title, "group", p.group, "why", p.why, "bytes", p.bytes,
			"essential", p.essential))
	}
	for _, pr := range copyPresets {
		presets = append(presets, newObj("id", pr[0], "name", pr[1], "about", pr[2], "wishes", anyList(copyWishes(parts, pr[0], nil))))
	}
	for _, d := range copyDrives(root) {
		var why any
		if d.mustErase != "" {
			why = d.mustErase
		}
		drives = append(drives, newObj("path", d.path, "name", d.name, "format", d.format, "free", d.free, "total", d.total,
			"room", d.room, "erasedRoom", d.erasedRoom, "kit", d.kit, "partial", d.partial, "mustErase", why))
	}
	var ai any
	if p := smallestAI(parts); p != nil {
		ai = p.id
	}
	return newObj("kit", root, "drive", driveName(root), "parts", ps, "presets", presets, "ai", ai, "notes", hasNotes(root),
		"canErase", canErase(), "drives", drives)
}

// copyPlan is what a copy on d would be, for --json with a drive: the parts, their size, and what it does to the
// drive, said as the command would say it before going ahead.
func copyPlan(d *copyDrive, ch *copyChoice) *obj {
	ids, left := []any{}, []any{}
	for _, p := range ch.parts {
		ids = append(ids, p.id)
	}
	for _, p := range ch.left {
		left = append(left, p.id)
	}
	plan := newObj("drive", d.name, "path", d.path, "parts", ids, "bytes", ch.bytes, "lines", anyList(copyLines(ch)),
		"left", left, "erase", ch.erase, "replace", ch.replace, "notes", ch.notes)
	if ch.erase || ch.replace {
		plan.set("warning", copyWarning(d, ch))
	}
	if ch.erase && !canErase() {
		plan.set("eraseHow", eraseHow(d))
	}
	return plan
}

// copyDriveFor is the drive a copy goes on: the one named (by its name, or its folder), or the one picked from the
// list, in a terminal.
func copyDriveFor(drives []*copyDrive, named string, asking bool) *copyDrive {
	if named != "" {
		for _, d := range drives {
			if strings.EqualFold(d.name, named) || samePath(d.path, absPath(named)) {
				return d
			}
		}
		die(fmt.Sprintf("There's no drive %s plugged in that a copy can go on. %s lists them.", named, kitCmd("copy")))
	}
	if len(drives) == 0 {
		die("Plug in the drive to copy to, then try again. (The drive this kit is on can't take a copy of it.)")
	}
	log("Drives a copy can go on:")
	for i, d := range drives {
		note := ""
		switch {
		case d.mustErase != "":
			note = " (it needs erasing: " + d.mustErase + ")"
		case d.kit:
			note = " (it has a Tinfoil Kit, which the copy replaces)"
		case d.partial:
			note = " (a copy stopped partway on it, which this carries on)"
		}
		log(fmt.Sprintf("  %d  %s: %s, %s free%s", i+1, d.name, d.format, fmtBytes(d.free), note))
	}
	if !asking {
		log("\nName the one to copy to: " + kitCmd("copy "+quoteArg(drives[0].name)))
		exit(1)
	}
	for {
		q := "\nWhich drive? Type its number: "
		if len(drives) == 1 {
			q = fmt.Sprintf("\nCopy to %s? Press %s, or Ctrl-C to stop: ", drives[0].name, returnKey)
		}
		said := ask(q)
		if n, err := strconv.Atoi(said); err == nil && n >= 1 && n <= len(drives) {
			return drives[n-1]
		}
		if said == "" && len(drives) == 1 {
			return drives[0]
		}
	}
}

// quoteArg is a name as a command line takes it.
func quoteArg(s string) string {
	if strings.ContainsAny(s, " '\"&()") {
		return `"` + s + `"`
	}
	return s
}

func askYes(question string) bool {
	return strings.HasPrefix(strings.ToLower(ask(question)), "y")
}

// askCopy asks what goes on the drive: a preset, or each part. Returns the preset, or the parts picked.
func askCopy(parts []*copyPart, d *copyDrive, eraseOK bool) (string, []string) {
	room := d.room
	if d.mustErase != "" || eraseOK {
		room = d.erasedRoom
	}
	log(fmt.Sprintf("\nWhat goes on %s? It has room for %s.", d.name, fmtBytes(room)))
	for i, p := range copyPresets {
		_, n := copyFill(parts, copyWishes(parts, p[0], nil), room)
		rec := ""
		if p[0] == "maps" {
			rec = " (recommended)"
		}
		log(fmt.Sprintf("  %d  %s: %s.%s %s", i+1, p[1], fmtBytes(n), rec, p[2]))
	}
	log(fmt.Sprintf("  %d  Pick each part", len(copyPresets)+1))
	for {
		said := ask(fmt.Sprintf("\nType a number, or press %s for 2: ", returnKey))
		if said == "" {
			return "maps", nil
		}
		n, err := strconv.Atoi(said)
		if err == nil && n >= 1 && n <= len(copyPresets) {
			return copyPresets[n-1][0], nil
		}
		if n == len(copyPresets)+1 {
			break
		}
	}
	took, _ := copyFill(parts, copyWishes(parts, "maps", nil), room)
	on := map[string]bool{}
	for _, p := range took {
		on[p.id] = true
	}
	for {
		var bytes int64
		group := ""
		for i, p := range parts {
			if p.group != group {
				group = p.group
				log("\n  " + group)
			}
			mark := " "
			if on[p.id] || p.id == "programs" {
				mark, bytes = "x", bytes+p.bytes
			}
			log(fmt.Sprintf("  %3d  [%s] %s (%s)", i+1, mark, p.title, fmtBytes(p.bytes)))
		}
		log(fmt.Sprintf("\nIn all: %s, and %s has room for %s.", fmtBytes(bytes), d.name, fmtBytes(room)))
		said := ask(fmt.Sprintf("Type numbers to switch them on or off (like 3 12), or press %s when it's right: ", returnKey))
		if said == "" {
			break
		}
		for _, w := range answerWords.Split(said, -1) {
			if k, err := strconv.Atoi(w); err == nil && k >= 1 && k <= len(parts) && parts[k-1].id != "programs" {
				on[parts[k-1].id] = !on[parts[k-1].id]
			}
		}
	}
	picked := []string{}
	for _, p := range parts {
		if on[p.id] && p.id != "programs" {
			picked = append(picked, p.id)
		}
	}
	return "", picked
}

func cmdCopy(root string, a *cliArgs) {
	state, cfg := loadState(root), loadConfig(root)
	parts := copyParts(root, state, cfg)
	plan := a.flag("json") && a.str("drive") != "" // what a copy on that drive would be, without making it
	if a.flag("json") && !plan {
		out(dumps(copyInfo(root, parts), jsonStyle{indent: 2, ascii: true}) + "\n")
		return
	}
	if len(parts) < 2 {
		die("This kit has nothing downloaded to copy yet. Set it up first: double-click SETUP, while online.")
	}
	asking := !a.flag("yes") && !plan && isTerminal(os.Stdin)
	d := copyDriveFor(copyDrives(root), a.str("drive"), asking)
	words := func(dest string) []string {
		if !a.has(dest) {
			return nil
		}
		ids, err := copyWords(parts, a.str(dest))
		if err != nil {
			die(err.Error())
		}
		return append([]string{}, ids...) // --only with nothing in it: just the programs
	}
	preset, only := "", words("only")
	for _, p := range copyPresets {
		if a.flag(p[0]) {
			preset = p[0]
		}
	}
	erase := strings.TrimSpace(a.str("erase"))
	if erase != "" && !plan && !strings.EqualFold(erase, d.name) {
		die(fmt.Sprintf("--erase names the drive, to be sure: this one is %s, not %s.", d.name, erase))
	}
	eraseOK := erase != ""
	if asking && !eraseOK && d.mustErase == "" && d.erasedRoom-d.room > max(5*GB, d.total/10) {
		eraseOK = askYes(fmt.Sprintf("\n%s has room for %s as it is: other files use the rest. Erase it first, for room "+
			"for %s? Everything on it would go. (y/N) ", d.name, fmtBytes(d.room), fmtBytes(d.erasedRoom)))
	}
	if preset == "" && only == nil && !a.has("add") && !a.has("skip") && asking {
		preset, only = askCopy(parts, d, eraseOK) // only, if they pick each part
	}
	if preset == "" {
		preset = "maps"
	}
	var ai []string
	smallest := smallestAI(parts)
	switch {
	case a.has("models"):
		for _, id := range words("models") {
			if partsByID(parts)[id].group != "AI models" {
				die(id + " isn't an AI model.")
			}
			ai = append(ai, id)
		}
	case a.flag("ai") && smallest == nil:
		log("This kit has no AI to copy, so the copy goes without.")
	case a.flag("ai"):
		ai = []string{smallest.id}
	case asking && smallest != nil && only == nil:
		if askYes(fmt.Sprintf("\nAdd the AI too? %s, %s. %s Without it, Ask finds answers in the books. (y/N) ",
			smallest.title, fmtBytes(smallest.bytes), smallest.why)) {
			ai = []string{smallest.id}
		}
	}
	if only != nil {
		only = append(only, ai...)
	}
	notes := a.flag("notes")
	if !notes && asking && hasNotes(root) {
		notes = askYes("\nCopy your notes and map pins too? (y/N) ")
	}
	ch, err := copyChoose(parts, d, preset, ai, only, words("add"), words("skip"), eraseOK)
	if err != nil {
		die(err.Error())
	}
	ch.notes = notes
	if plan {
		out(dumps(copyPlan(d, ch), jsonStyle{indent: 2, ascii: true}) + "\n")
		return
	}
	log(fmt.Sprintf("\nThe copy: %s on %s.", fmtBytes(ch.bytes), d.name))
	for _, line := range copyLines(ch) {
		log("  " + line)
	}
	if len(ch.left) > 0 {
		var t []string
		for _, p := range ch.left {
			t = append(t, p.title+" ("+fmtBytes(p.bytes)+")")
		}
		log("  Left out, for room: " + strings.Join(t, ", "))
	}
	if ch.erase || ch.replace {
		log("\n" + copyWarning(d, ch))
		if ch.erase && !canErase() {
			die(eraseHow(d))
		}
		if erase == "" {
			if !asking {
				log(fmt.Sprintf("To go ahead, add --erase %s.", quoteArg(d.name)))
				exit(1)
			}
			if said := ask(fmt.Sprintf("Type %s to go ahead, or press %s to stop: ", d.name, returnKey)); !strings.EqualFold(strings.TrimSpace(said), d.name) {
				log("Stopped. Nothing changed on " + d.name + ".")
				exit(1)
			}
		}
	}
	unlock, ok := tryLockKit(root)
	if !ok {
		die("This kit is busy: a sync or another copy is running on it. Try again once it's done.")
	}
	defer unlock()
	os.MkdirAll(filepath.Join(dataDir(root), "logs"), 0o755)
	logFile = filepath.Join(dataDir(root), "logs", "copy.log")
	logEnd("", fmt.Sprintf("\n=== %s: copying to %s (%s)\n", nowISO(), d.name, d.path))
	j := newCopyJob(root)
	j.set("drive", d.name, "path", d.path, "bytes", ch.bytes)
	stop := filepath.Join(metaDir(root), "copy.stop") // Stop, on Make a copy's page: as Ctrl-C
	os.Remove(stop)
	go func() {
		for ; !stopped(); time.Sleep(time.Second) {
			if isFile(stop) {
				stopOnce.Do(func() { close(stopping) })
			}
		}
	}()
	defer func() {
		if r := recover(); r != nil {
			if _, stop := r.(interrupted); stop {
				j.endLine()
				j.set("step", "stopped", "message", "Stopped. Make the copy again to carry on where it left off.")
			} else if s := j.rec.str("step"); s != "failed" && s != "done" {
				j.set("step", "failed", "message", "The copy stopped with an error. "+filepath.Join("data", "logs", "copy.log")+
					" says what.")
			}
			panic(r)
		}
	}()
	final := runCopy(root, cfg, d, ch, j)
	j.step("testing", "\nStarting the copy once, from "+d.name+", to be sure it works...", 0)
	works, failed := copyTest(final, j)
	card := filepath.Join(metaDir(final), "card.html")
	copyFile(card, filepath.Join(metaDir(root), "card.html")) // for this kit's page to print
	systems := copySystems(ch.parts[0])
	if !works {
		msg := fmt.Sprintf("The copy is on %s, but it didn't start when tested: %s. Its logs are in %s.", d.name, failed,
			filepath.Join(final, "data", "logs"))
		j.set("step", "done", "works", false, "message", msg, "folder", final, "systems", anyList(systems))
		log("\n" + msg)
		exit(1)
	}
	msg := fmt.Sprintf("%s has a Tinfoil Kit of its own, for %s. Eject it before you unplug it.", d.name, names(systems))
	if len(systems) == 0 {
		msg = fmt.Sprintf("%s has a Tinfoil Kit of its own. Eject it before you unplug it.", d.name)
	}
	j.set("step", "done", "works", true, "message", msg, "folder", final, "systems", anyList(systems))
	log("\nDone: " + msg)
	if j.tty {
		log("The card to print and keep with it is open in your browser: " + card)
		openBrowser(card)
	} else {
		log("The card to print and keep with it: " + card)
	}
}

// ----------------------------------------------------------------------------- Make a copy, from the kit page

// Make a copy, under More on the kit page, opens a page of its own: the notes server serves it at /copy, on its own
// address. The kit page's address also serves the books, whose pages can run scripts, and none of those may start a
// copy, let alone erase a drive. So /copy answers only its own page and programs on this computer: never the kit page's
// address, a page that frames it, or a device through the gate. The page is the kit page's own file, which sees where
// it is and shows just Make a copy. It runs ./kit copy, which does it all, and follows data/.kit/copy.json.

const copyHereOnly = "Only the computer the kit runs on can make a copy, with the drive plugged into it."

// copyRunning: the steps of a copy that's being made.
var copyRunning = []string{"starting", "erasing", "copying", "checking", "testing"}

// copyRun is the copy the page started, while it runs, and the end of what it printed.
type copyRun struct {
	mu   sync.Mutex
	cmd  *exec.Cmd
	tail *tailWriter
}

// tailWriter keeps the end of what a program prints, to say why it stopped before copy.json could.
type tailWriter struct {
	mu  sync.Mutex
	buf []byte
}

func (t *tailWriter) Write(p []byte) (int, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.buf = append(t.buf, p...); len(t.buf) > 8192 {
		t.buf = t.buf[len(t.buf)-8192:]
	}
	return len(p), nil
}

func (t *tailWriter) last() string {
	t.mu.Lock()
	defer t.mu.Unlock()
	return strings.TrimPrefix(lastLine(string(t.buf)), "ERROR: ")
}

// copyAsked turns away what a page sends from another address on its own (Sec-Fetch-Site), like a book's page at
// the kit page's: only following the link to Make a copy may come from there.
func copyAsked(r *http.Request, path string) bool {
	switch r.Header.Get("Sec-Fetch-Site") {
	case "", "same-origin", "none":
		return r.Header.Get("Sec-Fetch-Dest") != "iframe"
	}
	return path == "/copy" && r.Header.Get("Sec-Fetch-Mode") == "navigate" && r.Header.Get("Sec-Fetch-Dest") == "document"
}

// copyPage serves Make a copy's page (/copy, the kit page's file) and the card to print (/copy/card), which may not
// be framed, load anything, or reach anything but this server. False: it's not one of those.
func (n *notesServer) copyPage(w http.ResponseWriter, r *http.Request, path string) bool {
	if r.Method != http.MethodGet && r.Method != http.MethodHead || path != "/copy" && path != "/copy/card" {
		return false
	}
	if n.kit == "" {
		n.reply(w, r, 404, map[string]any{"error": "Make a copy works in a kit opened with its launcher."}, "")
		return true
	}
	file := filepath.Join(appDir(n.kit), "tools", "portal.html")
	if path == "/copy/card" {
		file = filepath.Join(metaDir(n.kit), "card.html")
	}
	b, err := os.ReadFile(file)
	if err != nil {
		n.reply(w, r, 404, map[string]any{"error": "There's no card yet: make a copy first."}, "")
		return true
	}
	h := w.Header()
	h.Set("Content-Type", "text/html; charset=utf-8")
	h.Set("Content-Length", strconv.Itoa(len(b)))
	h.Set("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "+
		"img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
	h.Set("X-Frame-Options", "DENY")
	h.Set("Referrer-Policy", "no-referrer")
	h.Set("Cache-Control", "no-store")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Server", "TinfoilKit-notes")
	w.WriteHeader(200)
	if r.Method != http.MethodHead {
		w.Write(b)
	}
	return true
}

var copyID = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$`)

// copyArgs is ./kit copy's options for what the page asks: drive, preset (essentials, maps, everything), ai,
// models and only (lists of ids, only even if empty: just the programs), notes, and erase (the drive's name, typed).
func copyArgs(ask map[string]any) ([]string, error) {
	text := func(k string) (string, error) {
		s, _ := ask[k].(string)
		if len(s) > 4096 || strings.ContainsAny(s, "\x00\r\n") {
			return "", &turnedDown{400, "That " + k + " can't be right.", nil}
		}
		return s, nil
	}
	drive, err := text("drive")
	if err != nil || drive == "" {
		return nil, &turnedDown{400, "Pick the drive the copy goes on.", nil}
	}
	var args []string
	switch p, _ := ask["preset"].(string); p {
	case "":
	case "essentials", "maps", "everything":
		args = append(args, "--"+p)
	default:
		return nil, &turnedDown{400, "There's no preset called " + p + ".", nil}
	}
	if b, _ := ask["ai"].(bool); b {
		args = append(args, "--ai")
	}
	for _, k := range []string{"models", "only"} {
		list, given := ask[k].([]any)
		if !given || k == "models" && len(list) == 0 {
			continue
		}
		var ids []string
		for _, v := range list {
			id, _ := v.(string)
			if !copyID.MatchString(id) {
				return nil, &turnedDown{400, "This kit has nothing called " + fmt.Sprint(v) + " to copy.", nil}
			}
			ids = append(ids, id)
		}
		args = append(args, "--"+k+"="+strings.Join(ids, ","))
	}
	if b, _ := ask["notes"].(bool); b {
		args = append(args, "--notes")
	}
	if name, err := text("erase"); err != nil {
		return nil, err
	} else if name != "" {
		args = append(args, "--erase="+name)
	}
	return append(args, "--", drive), nil
}

// kitRun runs this program's ./kit copy on this kit, and what it printed; an error says what it said went wrong.
func (n *notesServer) kitRun(args ...string) ([]byte, error) {
	if n.kit == "" {
		return nil, &turnedDown{404, "Make a copy works in a kit opened with its launcher.", nil}
	}
	self, err := os.Executable()
	if err != nil {
		return nil, err
	}
	cmd := exec.Command(self, append([]string{"--root=" + n.kit, "copy"}, args...)...)
	var stdout bytes.Buffer
	tail := &tailWriter{}
	cmd.Stdout, cmd.Stderr = io.MultiWriter(&stdout, tail), tail
	done := make(chan error, 1)
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	go func() { done <- cmd.Wait() }()
	select {
	case err = <-done:
	case <-time.After(2 * time.Minute):
		cmd.Process.Kill()
		<-done
		return nil, &turnedDown{504, "The kit took too long to look at the drives. Try again.", nil}
	}
	if err != nil {
		return nil, &turnedDown{400, tail.last(), nil}
	}
	return stdout.Bytes(), nil
}

// copyAnswer is ./kit copy --json for the page: what this kit has and the drives (/copy/info, with the copy being
// made, if there is one, and the kit page's address), or what a copy on one drive would be (/copy/plan).
func (n *notesServer) copyAnswer(q url.Values, plan bool) (int, any, error) {
	args := []string{"--json"}
	if plan {
		ask := map[string]any{"drive": q.Get("drive"), "preset": q.Get("preset"), "ai": q.Get("ai") == "1",
			"notes": q.Get("notes") == "1"}
		for _, k := range []string{"models", "only"} {
			if q.Has(k) {
				list := []any{}
				for _, id := range strings.Split(q.Get(k), ",") {
					if id != "" {
						list = append(list, id)
					}
				}
				ask[k] = list
			}
		}
		more, err := copyArgs(ask)
		if err != nil {
			return 0, nil, err
		}
		args = append(args, more...)
	}
	b, err := n.kitRun(args...)
	if err != nil {
		return 0, nil, err
	}
	v, _ := decodeJSON(b)
	m, ok := v.(map[string]any)
	if !ok {
		return 0, nil, &turnedDown{500, "The kit's answer about its drives didn't make sense.", nil}
	}
	if !plan {
		m["job"] = n.copyJob()
		for o := range n.origins {
			if strings.HasPrefix(o, "http://127.0.0.1:") {
				m["kitPage"] = o + "/"
			}
		}
	}
	return 200, m, nil
}

func (n *notesServer) copyFile(name string) string { return filepath.Join(metaDir(n.kit), name) }

// copyJob is the copy being made, or the last one (copy.json), with running: whether it still is, even when a
// terminal started it. A copy whose program has gone without saying how it ended stopped.
func (n *notesServer) copyJob() map[string]any {
	n.copying.mu.Lock()
	defer n.copying.mu.Unlock()
	return n.copyJobLocked()
}

// copySaid is copy.json as ./kit copy last saved it.
func (n *notesServer) copySaid() map[string]any {
	if n.kit != "" {
		if b, err := os.ReadFile(n.copyFile("copy.json")); err == nil {
			if v, _ := decodeJSON(b); v != nil {
				if m, ok := v.(map[string]any); ok {
					return m
				}
			}
		}
	}
	return map[string]any{}
}

func (n *notesServer) copyJobLocked() map[string]any {
	job := n.copySaid()
	if n.kit == "" {
		return job
	}
	step, _ := job["step"].(string)
	going := contains(copyRunning, step)
	alive := n.copying.cmd != nil
	if pid, _ := strconv.Atoi(fmt.Sprint(job["pid"])); going && !alive && pid > 0 { // a copy started in a terminal
		alive = pidAlive(pid)
	}
	if going && !alive {
		job["step"], job["message"] = "stopped", "The copy stopped before it was done. Make it again to carry on "+
			"where it left off."
	}
	job["running"] = going && alive
	job["stopping"] = going && alive && isFile(n.copyFile("copy.stop"))
	job["card"] = isFile(n.copyFile("card.html"))
	return job
}

// startCopy starts ./kit copy with what the page asked for (copyArgs), unless a copy is being made already.
func (n *notesServer) startCopy(ask map[string]any) (map[string]any, error) {
	args, err := copyArgs(ask)
	if err != nil {
		return nil, err
	}
	if n.kit == "" {
		return nil, &turnedDown{404, "Make a copy works in a kit opened with its launcher.", nil}
	}
	self, err := os.Executable()
	if err != nil {
		return nil, err
	}
	n.copying.mu.Lock()
	defer n.copying.mu.Unlock()
	if running, _ := n.copyJobLocked()["running"].(bool); running {
		return nil, &turnedDown{409, "A copy is being made already. One at a time: wait for it to finish, or stop it.", nil}
	}
	os.Remove(n.copyFile("copy.stop"))
	drive, _ := ask["drive"].(string)
	if err := writeWhole(n.copyFile("copy.json"), encodeJSON(map[string]any{"step": "starting", "path": drive,
		"started": nowISO()}, "  ")); err != nil {
		return nil, err
	}
	cmd := exec.Command(self, append([]string{"--root=" + n.kit, "copy", "--yes"}, args...)...)
	tail := &tailWriter{}
	cmd.Stdout, cmd.Stderr = tail, tail
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	n.copying.cmd, n.copying.tail = cmd, tail
	go func() {
		cmd.Wait()
		n.copying.mu.Lock()
		defer n.copying.mu.Unlock()
		n.copying.cmd = nil
		// a copy that ended before saying how in copy.json: what it printed last says why
		if job := n.copySaid(); contains(copyRunning, fmt.Sprint(job["step"])) {
			msg, step := tail.last(), "failed"
			if isFile(n.copyFile("copy.stop")) {
				msg, step = "Stopped. Make the copy again to carry on where it left off.", "stopped"
			}
			job["step"], job["message"] = step, msg
			writeWhole(n.copyFile("copy.json"), encodeJSON(job, "  "))
		}
		os.Remove(n.copyFile("copy.stop"))
	}()
	return n.copyJobLocked(), nil
}

// stopCopy asks the copy being made to stop, whoever started it: it notices copy.stop within a second, keeps what
// it copied, and carries on from there next time.
func (n *notesServer) stopCopy() (map[string]any, error) {
	n.copying.mu.Lock()
	defer n.copying.mu.Unlock()
	if running, _ := n.copyJobLocked()["running"].(bool); !running {
		return nil, &turnedDown{409, "No copy is being made.", nil}
	}
	if err := writeWhole(n.copyFile("copy.stop"), []byte(nowISO()+"\n")); err != nil {
		return nil, err
	}
	return n.copyJobLocked(), nil
}
