package main

// The kit's command line, as ./kit and kit.cmd run it: tinfoilkit --root KIT COMMAND.

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const kitDoc = `Tinfoil Kit: keeps an offline AI + knowledge library up to date, on an external drive or this computer.

Commands (run from the kit's app folder, e.g.  ./kit sync):
  plan [--json]      Show what would be downloaded or updated. Changes nothing.
                     --json prints every item's size, disabled ones too.
  sync [-y]          Download/update everything enabled in kit.json, verify every file
                     (SHA-256), then remove the old versions. Safe to interrupt and re-run.
                     --essentials: only the programs, the map, the most important books and the AI
                     this computer runs plus the smallest. --starter: just the try-it kit.
  verify [--quick]   Re-check every downloaded file against its recorded SHA-256.
                     --fix deletes the bad ones so the next sync replaces them.
  status             What's installed, when it was last updated, free space.
  search WORDS...    Search the Kiwix catalog for more library content to add to kit.json.
  test               Start the offline servers briefly and check they actually work.
  open [--share]     Start the servers and open the kit's page, as Open Tinfoil Kit does, until this
                     window closes. --share lets the home network in too, --model=NAME picks the AI,
                     --no-browser doesn't open the page, --no-maps leaves the map's servers off.
  update [-y]        Replace the kit's own code with its newest release on GitHub, if it's signed
                     with the kit's release key (tools/release-signers), keeping your kit.json
                     changes. Shows what's new and asks first. SETUP.command runs it first.
  pins               Pin the newest build of every program, with its SHA-256, in tools/pins.json.
                     Run before a release: drives install exactly those builds.
  estimate           About how many GB this kit.json needs, from the sizes the website's kit
                     builder lists (--essentials: just those; --starter: the try-it kit). Needs no
                     internet. --rest: the GB still to download for everything switched on, then how
                     long that takes at this connection's speed, tab-separated. SETUP.command uses it.
  drives [--json]    The plugged-in drives the kit could go on: folder, format, GB free, and why
                     not (or -). --json adds this computer's free space and what the kit needs.
  place DEST         Put the kit at DEST (a TinfoilKit folder at the top of a drive or in the home
                     folder), ready to set up there. Prints its folder. SETUP.command uses it.
  kits               Kits set up before, in the home folder or on a drive plugged in (besides this
                     one), the one synced last first: folder, where, GB, last sync. A new download's
                     SETUP.command carries on with that kit, so nothing it has downloads again.
  space PATH         Whether the kit, or just its essentials, fits at PATH (a kit folder, or where one
                     would go) and leaves 10% of the computer's disk, or 5% of a drive, free.
  essentials [on|off]
                     Get just the essentials from now on (on), or everything switched on (off).
  starter [on|off]   Get just the try-it kit from now on (on): a few GB to try the kit with, the
                     smallest AI, a few small books and the area's map. off: everything switched on.
                     Without on or off, says how big the rest is and how long it takes to download.
  fit [--ask]        Which AI model this computer runs, given its memory, and the switched-on ones
                     too big for it. --ask (SETUP.command) asks whether to download those anyway;
                     --skip-too-big switches them off, --restore back on. --json for scripts and agents.
  share [on|off|new-code]
                     Let phones and laptops on your home network use the kit, once they type its
                     access code. Shows the address, the code and a QR code.
  autostart [on|off] Start the kit whenever this computer starts, for a home server (Linux: a
                     systemd user service; Mac: when you log in).
  region [PLACE]     Where you live (a US state or a country; places nearby too, with commas): sets the map
                     areas, the road data for directions, address search, home and units. --wikipedia en,es
                     also picks Wikipedia's languages; --find WORDS lists places; --languages lists a place's
                     languages.
  pick               What goes in the kit, as SETUP's options and the website's kit builder say it: a
                     preset to start over from (--recommended, --essentials, --everything), where you
                     live and Wikipedia (--region, --wikipedia, --wikipedia-size), then by name: --no-ai,
                     --models IDS (just those), --skip IDS, --add IDS. Without a preset, these change
                     the kit as it is. --ask asks the kit builder's questions instead. Choosing sets
                     "picked" in kit.json, so SETUP doesn't ask again. Without options, says what's
                     on, its size, and the time to download it.
  remove NAME...     Delete what these downloaded (names as pick takes them), for the space, and switch
                     them off so sync doesn't get them again. Asks first; --yes doesn't.
  layout             Move a kit from before its app, downloads and data folders into them, by
                     renaming: nothing downloads again. Every command does it first; SETUP runs it.

The kit folder holds app/ (this code, as released: replace it with a new version's any time),
downloads/ (what sync downloads) and data/ (your kit.json, logs, and the kit's records in .kit/).
Beside them, every command keeps Open Tinfoil Kit for each kind of computer, and Read me first.txt.

Only needs curl, which macOS and Windows come with, as do most Linux PCs. A big file comes over
several connections at once, which is often several times faster than one.
`

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

const userAgent = "TinfoilKit/1.0 (+https://github.com/tudor-city-ventures/tinfoil-kit)"

var (
	kiwixCatalog       = envOr("KIT_KIWIX_CATALOG", "https://library.kiwix.org/catalog/v2/entries?count=-1")
	kiwixReleases      = envOr("KIT_KIWIX_RELEASES", "https://download.kiwix.org/release/{product}/")
	githubAPI          = envOr("KIT_GITHUB_API", "https://api.github.com")
	kitRepo            = envOr("KIT_REPO", "tudor-city-ventures/tinfoil-kit") // where ./kit update gets the kit's code
	hfURL              = envOr("KIT_HF", "https://huggingface.co")
	adoptiumAPI        = envOr("KIT_ADOPTIUM_API", "https://api.adoptium.net")
	mavenURL           = envOr("KIT_MAVEN", "https://repo1.maven.org/maven2")
	npmURL             = envOr("KIT_NPM", "https://registry.npmjs.org")
	githubWeb          = envOr("KIT_GITHUB_WEB", "https://github.com")
	protomapsBuilds    = envOr("KIT_PROTOMAPS_BUILDS", "https://build-metadata.protomaps.dev/builds.json")
	protomapsBuildBase = envOr("KIT_PROTOMAPS_BUILD_BASE", "https://build.protomaps.com")
	photonDumps        = envOr("KIT_PHOTON_DUMPS", "https://download1.graphhopper.com/public/")
	geofabrik          = envOr("KIT_GEOFABRIK", "https://download.geofabrik.de") // the road data in tools/regions.json
)

const GB = 1_000_000_000

var sections = []string{"runtimes", "models", "maps", "library", "extras"}

func mapsDefaults() *obj {
	return newObj(
		"enabled", false,
		"label", "map region",
		"home", newObj("lat", 40.75, "lon", -73.99, "zoom", 10, "label", "Home"),
		"detail_bbox", []any{-80.6, 38.8, -66.8, 47.6},
		"detail_maxzoom", 15,
		"world_maxzoom", 7,
		"routing_osm_pbf", strings.TrimRight(geofabrik, "/")+"/north-america/us-northeast-latest.osm.pbf",
		"routing_profiles", []any{"car", "foot"},
		"geocoder_country", "us",
		"units", "imperial",
		"tiles_port", 8090,
		"geocoder_port", 2322,
		"routing_port", 8989,
		"routing_import_heap", "auto",
		"routing_heap", "2g",
		"geocoder_heap", "3g",
		"lang", "en",
	)
}

// What a place in tools/regions.json sets ("Where do you live?"). Any of these in kit.json's maps wins over it.
var regionKeys = []string{"label", "home", "detail_bbox", "routing_osm_pbf", "geocoder_country", "geocoder_wide", "units", "lang"}

var wikipediaRE = regexp.MustCompile(`^wikipedia_([a-z]{2,3}(?:-[a-z]+)?)_((?:all|top)_(?:maxi|nopic|mini))$`)

// Wikipedia comes in sizes, Kiwix's editions of it (smallest first). ./kit region --wikipedia-size names the ones the
// kit offers; a language that lacks one gets the next smaller edition it has.
var editions = []string{"top_mini", "top_nopic", "top_maxi", "all_mini", "all_nopic", "all_maxi"}

var wikiSizes = [][2]string{{"all", "all_maxi"}, {"all-text", "all_nopic"}, {"top", "top_maxi"}, {"top-text", "top_nopic"},
	{"top-intros", "top_mini"}}

var editionLabels = map[string]string{"all_maxi": "all of it, with pictures", "all_nopic": "all of it, text only",
	"all_mini": "every article's opening paragraphs", "top_maxi": "the best 50,000 articles, with pictures",
	"top_nopic": "the best 50,000 articles, text only", "top_mini": "the best 50,000 articles' opening paragraphs"}

// The try-it kit and the essentials get a smaller edition of the Wikipedia kit.json lists while that one isn't in the
// kit yet, up to so many MB: the best articles' opening paragraphs, and their text.
var standIns = map[string]struct {
	edition string
	mb      float64
}{"starter": {"top_mini", 1000}, "essentials": {"top_nopic", 5000}}

var ghEncodedValues = map[string][]string{
	"car": {"car_access", "car_average_speed", "road_access"},
	"foot": {"foot_access", "foot_priority", "foot_average_speed", "foot_road_access", "hike_rating", "mtb_rating",
		"country", "road_class"},
	"bike": {"bike_priority", "bike_access", "roundabout", "bike_average_speed", "bike_road_access", "foot_road_access",
		"mtb_rating", "hike_rating", "country", "road_class"},
}

var (
	glyphFonts      = []string{"Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic"}
	glyphRanges     = []string{"0-255", "256-511", "8192-8447"}
	archiveSuffixes = []string{".tar.gz", ".tgz", ".zip"}
	shardRE         = regexp.MustCompile(`-\d{5}-of-\d{5}\.gguf$`)
	zimRE           = regexp.MustCompile(`^(.+)_(\d{4}-\d{2})\.zim$`)
	hex64           = regexp.MustCompile(`\b([0-9a-fA-F]{64})\b`)
)

func isArchive(name string) bool {
	for _, s := range archiveSuffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return false
}

// codeRoot is this code's own folder: the app folder this program is in (app/tools), or a git checkout. KIT_CODE
// names it for a copy of the program run from elsewhere: Windows won't move the folder of a program that's running,
// so SETUP-Windows.bat moves a kit's code into its app folder with a copy in TEMP. A program in a tools folder pays
// it no mind, so one left set can't send the kit's own program to a folder its code has left.
var codeRoot = findCodeRoot()

func findCodeRoot() string {
	exe, err := os.Executable()
	if err != nil {
		wd, _ := os.Getwd()
		return wd
	}
	if r, err := filepath.EvalSymlinks(exe); err == nil {
		exe = r
	}
	if c := os.Getenv("KIT_CODE"); c != "" && !strings.EqualFold(filepath.Base(filepath.Dir(exe)), "tools") {
		if abs, err := filepath.Abs(c); err == nil {
			return abs
		}
	}
	return filepath.Dir(filepath.Dir(exe))
}

func regionsFile() string { return filepath.Join(codeRoot, "tools", "regions.json") }

var logFile string

// The kit folder: app/ is the code exactly as released, which ./kit update replaces and which can be deleted any time
// for a new version's; downloads/ is everything sync downloads; data/ is the person's: their kit.json, logs, map pins
// and notes, and the kit's own records in data/.kit. A git checkout's kit folder, kit/ in the repository, is its own
// app folder, with downloads/ and data/ inside it. Item destinations ("models/Tiny") and state.json's paths are within
// downloads/.

func appDir(root string) string {
	if checkout(root) {
		return root
	}
	return filepath.Join(root, "app")
}

// checkout says whether root is a git checkout's kit folder: the repository's kit/ (or a folder with a .git of its
// own). Only one called kit counts, so a kit in a folder that git tracks, like a home folder, is still a kit.
func checkout(root string) bool {
	return exists(filepath.Join(root, ".git")) ||
		strings.EqualFold(filepath.Base(root), "kit") && exists(filepath.Join(filepath.Dir(root), ".git"))
}

func dlDir(root string) string   { return filepath.Join(root, "downloads") }
func dataDir(root string) string { return filepath.Join(root, "data") }

// metaDir holds the kit's own records: state.json, the access code, caches, the built page, kit.json's last
// standard list.
func metaDir(root string) string { return filepath.Join(root, "data", ".kit") }

// hasCode says whether the kit's code is in this folder: in its app folder, or at its top (a git checkout, or a kit
// from before the app folder).
func hasCode(folder string) bool {
	for _, c := range []string{filepath.Join(folder, "app"), folder} {
		if isFile(filepath.Join(c, "kit")) && isDir(filepath.Join(c, "tools")) {
			return true
		}
	}
	return false
}

// isKit says whether this is a kit folder: with its code, or with its records and its app folder deleted for a new
// one.
func isKit(folder string) bool {
	return hasCode(folder) || isFile(filepath.Join(metaDir(folder), "state.json"))
}

var junk = []string{".DS_Store", "desktop.ini", "Thumbs.db", ".kit-write-test"} // what computers leave in any folder

// alone says whether the kit folder holds just the kit (its three folders, and the launchers and Read me first.txt
// beside them), so it can be moved or deleted whole. An app folder put somewhere on its own, like the Desktop, has
// other things beside it, which are none of the kit's business.
func alone(root string) bool {
	entries, err := os.ReadDir(root)
	if err != nil {
		return false
	}
	for _, e := range entries {
		n := e.Name()
		if n != "app" && n != "downloads" && n != "data" && !isTopFile(n) && !contains(junk, n) && !strings.HasPrefix(n, "._") {
			return false
		}
	}
	return true
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

// lexists is whether anything is at p, even a link to nothing.
func lexists(p string) bool {
	_, err := os.Lstat(p)
	return err == nil
}

func contains[T comparable](l []T, x T) bool {
	for _, e := range l {
		if e == x {
			return true
		}
	}
	return false
}

func fileSize(p string) int64 {
	st, err := os.Stat(p)
	if err != nil {
		return 0
	}
	return st.Size()
}

// ----------------------------------------------------------------------------- output

// log prints a line, and adds it to this sync's log file. A reader that stopped reading (| head) ends the kit quietly.
func log(msg string) { logEnd(msg, "\n") }

func logEnd(msg, end string) {
	if _, err := io.WriteString(os.Stdout, msg+end); err != nil && errors.Is(err, syscall.EPIPE) {
		os.Exit(1)
	}
	if logFile != "" {
		if f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			f.WriteString(msg + end)
			f.Close()
		}
	}
}

// out prints without the log file, as print() did.
func out(s string) {
	if _, err := io.WriteString(os.Stdout, s); err != nil && errors.Is(err, syscall.EPIPE) {
		os.Exit(1)
	}
}

func fmtSize(n float64) string {
	for _, u := range []struct {
		unit string
		div  float64
	}{{"TB", 1e12}, {"GB", 1e9}, {"MB", 1e6}, {"KB", 1e3}} {
		if n >= u.div {
			return strconv.FormatFloat(n/u.div, 'f', 1, 64) + " " + u.unit
		}
	}
	return strconv.FormatInt(int64(n), 10) + " B"
}

func fmtBytes(n int64) string { return fmtSize(float64(n)) }

// fmtSizeOr is fmt_size of a size that may not be known (0), which it shows as "?".
func fmtSizeOr(n int64) string {
	if n == 0 {
		return "?"
	}
	return fmtBytes(n)
}

func pyRound(f float64) float64 { return math.RoundToEven(f) }

func fmtTime(seconds float64) string {
	m := seconds / 60
	if m < 1.5 {
		return "about a minute"
	}
	if m < 55 {
		n := pyRound(m)
		if m > 12 {
			n = pyRound(m/5) * 5
		}
		return fmt.Sprintf("about %d minutes", int64(n))
	}
	h := m / 60
	if h < 1.25 {
		return "about an hour"
	}
	if h < 36 {
		return "about " + pyG(pyRound(h*2)/2) + " hours"
	}
	return "about " + pyG(pyRound(h/12)/2) + " days"
}

// pyG is Python's format(f, "g") for the numbers the kit shows.
func pyG(f float64) string { return strconv.FormatFloat(f, 'g', -1, 64) }

// speed is this run's downloads, for the time estimates.
var speed struct {
	sync.Mutex
	bytes   int64
	seconds float64
}

func addSpeed(n int64, secs float64) {
	speed.Lock()
	speed.bytes += n
	speed.seconds += secs
	speed.Unlock()
}

// noteSpeed keeps how fast this run's downloads came in (bytes a second), once there's enough of them to tell.
func noteSpeed(state *obj) {
	speed.Lock()
	defer speed.Unlock()
	if speed.bytes >= 100e6 && speed.seconds > 0 {
		state.set("download_speed", int64(pyRound(float64(speed.bytes)/speed.seconds)))
	}
}

// eta is how long nbytes take to download at the speed this kit's last sync measured ("" before there's one).
func eta(root string, nbytes float64) string {
	v := loadState(root).get("download_speed")
	if _, ok := v.(string); ok || v == nil {
		return ""
	}
	bps, ok := asNumber(v)
	if !ok || bps <= 0 {
		return ""
	}
	return fmtTime(nbytes/bps) + " at this connection's speed (" + fmtSize(bps) + "/s)"
}

// tier is just the try-it kit, just the essentials: this run's --starter or --essentials, else kit.json's setting.
func tier(cfg *obj, essentials, starter bool) (bool, bool) {
	s := cfg.child("settings")
	if essentials {
		return false, true
	}
	st := starter || isTrue(s.get("starter_only"))
	return st, !st && isTrue(s.get("essentials_only"))
}

func nowISO() string { return time.Now().Format("2006-01-02T15:04:05") }

// exitCode, panicked with, ends the kit with this code once deferred clean-ups have run.
type exitCode int

// interrupted is Ctrl-C, which stops the kit where it is, keeping what it has.
type interrupted struct{}

func die(msg string, code ...int) {
	log("ERROR: " + msg)
	c := 1
	if len(code) > 0 {
		c = code[0]
	}
	panic(exitCode(c))
}

func exit(code int) { panic(exitCode(code)) }

var (
	stopping = make(chan struct{})
	stopOnce sync.Once
)

// watchCtrlC turns Ctrl-C into a stop the kit's long steps notice: they end their programs, keep what arrived, and
// the kit says "Stopped." A broken pipe becomes an error to notice too, rather than the end of the program.
func watchCtrlC() {
	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, os.Interrupt)
	pipe := make(chan os.Signal, 1)
	signal.Notify(pipe, brokenPipe...)
	go func() {
		<-sigs
		stopOnce.Do(func() { close(stopping) })
	}()
}

func stopped() bool {
	select {
	case <-stopping:
		return true
	default:
		return false
	}
}

func checkStop() {
	if stopped() {
		panic(interrupted{})
	}
}

func sleep(d time.Duration) {
	select {
	case <-time.After(d):
	case <-stopping:
		panic(interrupted{})
	}
}

// run runs a program to its end, or until Ctrl-C, which ends it too.
func run(cmd *exec.Cmd) error {
	if err := cmd.Start(); err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		return err
	case <-stopping:
		cmd.Process.Kill()
		<-done
		panic(interrupted{})
	}
}

// output runs a program and returns what it printed, and its exit code (-1: it couldn't start).
func output(name string, args ...string) (stdout, stderr []byte, rc int) {
	var o, e bytes.Buffer
	cmd := exec.Command(name, args...)
	cmd.Stdout, cmd.Stderr = &o, &e
	rc = exitOf(run(cmd))
	return o.Bytes(), e.Bytes(), rc
}

func exitOf(err error) int {
	if err == nil {
		return 0
	}
	var ee *exec.ExitError
	if errors.As(err, &ee) {
		if ee.ExitCode() < 0 {
			return 128 // ended by a signal
		}
		return ee.ExitCode()
	}
	return -1
}

func which(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

// ----------------------------------------------------------------------------- http (via curl)

type httpError struct {
	url, msg string
	status   int
	busy     bool // a publisher still busy after the kit waited
}

func (e *httpError) Error() string {
	if e.busy {
		return fmt.Sprintf("%s says %s. Nothing's wrong with this computer: try again later (%s)", urlHost(e.url),
			busyWhy[e.status], e.url)
	}
	return e.msg + " (" + e.url + ")"
}

// A server that's busy says so (429, 503), and may say how long to wait (Retry-After). The kit waits and asks again,
// for up to five minutes in all, rather than give up or ask again at once: curl's own --retry asks again too soon,
// waits out a Retry-After without a word, and skips a 429 altogether when a Mac's curl reports it as exit 56.
var (
	busyWhy    = map[int]string{429: "it's had too many requests", 503: "it's busy, or down for maintenance"}
	busyWaits  = []time.Duration{15 * time.Second, 30 * time.Second, time.Minute, 2 * time.Minute}
	busyMost   = 5 * time.Minute // the most the kit waits for one answer
	retryWaits = []time.Duration{2 * time.Second, 2 * time.Second, 2 * time.Second}
	busyUntil  = map[string]time.Time{} // a host still busy after all of busyWaits: asked once a time, without waiting
	busyMu     sync.Mutex
)

// retryAfter is how long a server's answer, the last header block in a curl -D file, asks to wait: 0 when it doesn't.
func retryAfter(headerFile string) time.Duration {
	data, err := os.ReadFile(headerFile)
	if err != nil {
		return 0
	}
	blocks := headerBlocks(latin1(data))
	if len(blocks) == 0 {
		return 0
	}
	for _, line := range pyLines(blocks[len(blocks)-1]) {
		k, v, ok := strings.Cut(line, ":")
		if !ok || !strings.EqualFold(strings.TrimSpace(k), "retry-after") {
			continue
		}
		v = strings.TrimSpace(v)
		if n, err := strconv.Atoi(v); err == nil && n > 0 {
			return time.Duration(n) * time.Second
		}
		if t, err := http.ParseTime(v); err == nil && time.Until(t) > 0 {
			return time.Until(t).Round(time.Second)
		}
	}
	return 0
}

// fmtWait is a wait in words: "a second", "15 seconds", "2 minutes".
func fmtWait(d time.Duration) string {
	switch s := int(d.Round(time.Second) / time.Second); {
	case s <= 1:
		return "a second"
	case s < 90:
		return fmt.Sprintf("%d seconds", s)
	}
	return fmt.Sprintf("%d minutes", int(d.Round(time.Minute)/time.Minute))
}

// retries is whether curl failing this way is a hiccup worth asking again after: what curl's --retry asked again
// after (a timeout, a name that didn't look up, a server error), and a connection that dropped.
func retries(rc, status int) bool {
	switch status {
	case 0:
		return slices.Contains([]int{5, 6, 18, 28, 52, 55, 56}, rc)
	case 408, 500, 502, 504:
		return true
	}
	return false
}

var (
	curlHelp     string
	curlHelpOnce sync.Once
)

func curlSupports(flag string) bool {
	curlHelpOnce.Do(func() {
		o, _, _ := output("curl", "--help", "all")
		curlHelp = string(o)
	})
	return strings.Contains(curlHelp, flag)
}

func urlHost(u string) string {
	rest := u
	if i := strings.Index(rest, "://"); i >= 0 {
		rest = rest[i+3:]
	} else {
		return ""
	}
	if i := strings.IndexAny(rest, "/?#"); i >= 0 {
		rest = rest[:i]
	}
	if i := strings.LastIndexByte(rest, '@'); i >= 0 {
		rest = rest[i+1:]
	}
	if strings.HasPrefix(rest, "[") {
		if i := strings.IndexByte(rest, ']'); i >= 0 {
			return strings.ToLower(rest[1:i])
		}
	}
	if i := strings.IndexByte(rest, ':'); i >= 0 {
		rest = rest[:i]
	}
	return strings.ToLower(rest)
}

// urlPath is a URL's path, as urllib's urlparse has it.
func urlPath(u string) string {
	rest := u
	if i := strings.Index(rest, "://"); i >= 0 {
		rest = rest[i+3:]
		if j := strings.IndexByte(rest, '/'); j >= 0 {
			rest = rest[j:]
		} else {
			return ""
		}
	}
	if i := strings.IndexAny(rest, "?#"); i >= 0 {
		rest = rest[:i]
	}
	return rest
}

func authHeaders(url string) [][2]string {
	host := urlHost(url)
	if strings.HasSuffix(host, "huggingface.co") && os.Getenv("HF_TOKEN") != "" {
		return [][2]string{{"Authorization", "Bearer " + os.Getenv("HF_TOKEN")}}
	}
	if host == "api.github.com" || strings.HasPrefix(url, githubAPI) {
		h := [][2]string{{"Accept", "application/vnd.github+json"}}
		if os.Getenv("GITHUB_TOKEN") != "" {
			h = append(h, [2]string{"Authorization", "Bearer " + os.Getenv("GITHUB_TOKEN")})
		}
		return h
	}
	return nil
}

var curlStatus = regexp.MustCompile(`error: (\d{3})`)

// curlGet fetches url with curl once (args can have curl ask again itself), with curl's exit code and what failed.
func curlGet(url string, timeout int, args []string, headers [][2]string) ([]byte, int, *httpError) {
	if timeout == 0 {
		timeout = 120
	}
	args = append([]string{"-fsSL", "--connect-timeout", "20", "--max-time", strconv.Itoa(timeout), "-A", userAgent},
		args...)
	for _, h := range mergeHeaders(authHeaders(url), headers) {
		args = append(args, "-H", h[0]+": "+h[1])
	}
	stdout, stderr, rc := output("curl", append(args, url)...)
	if rc == 0 {
		return stdout, 0, nil
	}
	msg := strings.TrimSpace(strings.ToValidUTF8(string(stderr), "�"))
	status := 0
	if m := curlStatus.FindStringSubmatch(msg); m != nil {
		status, _ = strconv.Atoi(m[1])
	}
	if msg == "" {
		msg = fmt.Sprintf("curl exit %d", rc)
	}
	return nil, rc, &httpError{url: url, msg: msg, status: status}
}

// httpGet fetches a file or an answer from a publisher. After a hiccup it asks again a few times, and a server that
// says it's busy gets the wait it asks for (busyWaits).
func httpGet(url string, timeout int, saveHeaders string, headers ...[2]string) ([]byte, error) {
	if saveHeaders == "" {
		if f, err := os.CreateTemp("", "kit-headers-"); err == nil {
			saveHeaders = f.Name()
			f.Close()
			defer os.Remove(saveHeaders)
		}
	}
	var args []string
	if saveHeaders != "" {
		args = []string{"-D", saveHeaders}
	}
	host := urlHost(url)
	var waited time.Duration
	for blips, waits := 0, 0; ; {
		data, rc, err := curlGet(url, timeout, args, headers)
		busyMu.Lock()
		if err == nil {
			delete(busyUntil, host)
		}
		gaveUp := time.Now().Before(busyUntil[host])
		busyMu.Unlock()
		if err == nil {
			return data, nil
		}
		var wait time.Duration
		switch why := busyWhy[err.status]; {
		case why != "":
			wait = busyWaits[min(waits, len(busyWaits)-1)]
			if after := retryAfter(saveHeaders); after > 0 {
				wait = after
			}
			if gaveUp || waits == len(busyWaits) || waited+wait > busyMost {
				busyMu.Lock()
				busyUntil[host] = time.Now().Add(10 * time.Minute)
				busyMu.Unlock()
				err.busy = true
				return nil, err
			}
			waited += wait
			waits++
			if isTerminal(os.Stdout) { // over a plan's progress line
				out("\r" + strings.Repeat(" ", 78) + "\r")
			}
			log(fmt.Sprintf("  %s says %s. Asking again in %s...", host, why, fmtWait(wait)))
		case retries(rc, err.status) && blips < len(retryWaits):
			wait = retryWaits[blips]
			blips++
		default:
			return nil, err
		}
		sleep(wait)
	}
}

// localGet asks one of the kit's own servers, as ./kit test does. One that's still starting answers 503 for a while,
// and the test asks again itself, so this asks only after a hiccup, as curl does, and never waits long.
func localGet(url string, timeout int) ([]byte, error) {
	data, _, err := curlGet(url, timeout, []string{"--retry", "3", "--retry-delay", "2"}, nil)
	if err != nil {
		return nil, err
	}
	return data, nil
}

func localJSON(url string) (any, error) {
	data, err := localGet(url, 60)
	if err != nil {
		return nil, err
	}
	return parseJSON(data)
}

// mergeHeaders is {**a, **b}: b's replace a's, in a's order.
func mergeHeaders(a, b [][2]string) [][2]string {
	out := append([][2]string(nil), a...)
	for _, h := range b {
		found := false
		for i := range out {
			if out[i][0] == h[0] {
				out[i][1], found = h[1], true
			}
		}
		if !found {
			out = append(out, h)
		}
	}
	return out
}

func httpJSON(url string, timeout int) (any, error) {
	if timeout == 0 {
		timeout = 60
	}
	data, err := httpGet(url, timeout, "")
	if err != nil {
		return nil, err
	}
	return parseJSON(data)
}

// pyLines is Python's universal newlines and str.splitlines, for curl's text output.
func pyLines(s string) []string {
	s = strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\r", "\n")
	if s == "" {
		return nil
	}
	return strings.Split(strings.TrimSuffix(s, "\n"), "\n")
}

var blankLine = regexp.MustCompile(`\r?\n\r?\n`)

// headerBlocks are the header blocks curl printed (one per redirect), without empty ones.
func headerBlocks(text string) []string {
	var blocks []string
	for _, b := range blankLine.Split(strings.TrimSpace(text), -1) {
		if strings.TrimSpace(b) != "" {
			blocks = append(blocks, b)
		}
	}
	return blocks
}

func httpHead(url string) (map[string]string, error) {
	stdout, stderr, rc := output("curl", "-fsSIL", "--connect-timeout", "20", "--max-time", "60", "-A", userAgent, url)
	if rc != 0 {
		msg := strings.TrimSpace(string(stderr))
		status := 0
		if m := curlStatus.FindStringSubmatch(msg); m != nil {
			status, _ = strconv.Atoi(m[1])
		}
		if msg == "" {
			msg = "HEAD failed"
		}
		return nil, &httpError{url: url, msg: msg, status: status}
	}
	text := strings.ReplaceAll(strings.ReplaceAll(string(stdout), "\r\n", "\n"), "\r", "\n")
	blocks := headerBlocks(text)
	headers := map[string]string{}
	if len(blocks) > 0 {
		lines := pyLines(blocks[len(blocks)-1])
		for _, line := range lines[1:] {
			if k, v, ok := strings.Cut(line, ":"); ok {
				headers[strings.ToLower(strings.TrimSpace(k))] = strings.TrimSpace(v)
			}
		}
	}
	return headers, nil
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

func contentLength(h map[string]string) int64 {
	v := h["content-length"]
	if !allDigits(v) {
		return 0
	}
	n, _ := strconv.ParseInt(v, 10, 64)
	return n
}

// headSize is a remote file's size, or 0 when the server won't say.
func headSize(url string) int64 {
	h, err := httpHead(url)
	if err != nil {
		return 0
	}
	return contentLength(h)
}

var meta4SHA = regexp.MustCompile(`type="sha-256">\s*([0-9a-fA-F]{64})`)

// fetchSHA256Sidecar: Kiwix publishes <file>.sha256 next to every download; .meta4 is the fallback.
func fetchSHA256Sidecar(url string) string {
	for _, s := range []struct {
		suffix string
		re     *regexp.Regexp
	}{{".sha256", hex64}, {".meta4", meta4SHA}} {
		data, err := httpGet(url+s.suffix, 60, "")
		if err != nil {
			continue
		}
		if m := s.re.FindStringSubmatch(strings.ToValidUTF8(string(data), "�")); m != nil {
			return strings.ToLower(m[1])
		}
	}
	return ""
}

// ----------------------------------------------------------------------------- config & state

// saveText replaces a file in one step, so that a crash leaves the old one or the new one, never half of it.
func saveText(path, text string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, []byte(text), 0o644); err != nil {
		return err
	}
	return replace(tmp, path)
}

// mustSave is saveText for the kit's records, which the kit can't go on without.
func mustSave(path, text string) {
	if err := saveText(path, text); err != nil {
		die(fmt.Sprintf("couldn't save %s: %s", path, oserr(err)))
	}
}

// replace is os.replace: a rename that also replaces a file already there, on Windows too.
func replace(src, dst string) error { return os.Rename(src, dst) }

// oserr is an error as Python's OSError shows it: "[Errno 2] No such file or directory: 'x'" is too much, so
// just the reason and the file.
func oserr(err error) string {
	var pe *os.PathError
	if errors.As(err, &pe) {
		return fmt.Sprintf("%s: '%s'", strerror(pe.Err), pe.Path)
	}
	var le *os.LinkError
	if errors.As(err, &le) {
		return fmt.Sprintf("%s: '%s' -> '%s'", strerror(le.Err), le.Old, le.New)
	}
	return err.Error()
}

// strerror is an OS error's own words, capitalized as the system's strerror has them.
func strerror(err error) string {
	s := err.Error()
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// ensureConfig: data/kit.json is the person's list of what goes in the kit, a copy of the standard list
// (app/kit.json) to start with. When app/ is a newer version (./kit update, or a new app folder put in by hand), the
// standard list's changes go into it and the person's own stay: data/.kit/kit.base.json, the standard list it last
// took in, shows which those are. Every command does this first. Returns a line on what happened, or "" if nothing
// did.
func ensureConfig(root string) string {
	std, mine, baseFile := filepath.Join(appDir(root), "kit.json"), filepath.Join(dataDir(root), "kit.json"),
		filepath.Join(metaDir(root), "kit.base.json")
	data, err := os.ReadFile(std)
	var theirs any
	if err == nil {
		theirs, err = parseJSON(data)
	}
	if err != nil {
		die(std + " is missing or broken. Put the app folder of a new download of the kit (tinfoilkit.com) in place " +
			"of this one: your downloads and settings stay as they are")
	}
	theirsText := string(data)
	var base any = missing
	if b, err := os.ReadFile(baseFile); err == nil {
		if v, err := parseJSON(b); err == nil {
			base = v
		}
	}
	note := ""
	if !exists(mine) {
		mustSave(mine, theirsText)
	} else if pyEqual(base, theirs) {
		return ""
	} else if base == missing {
		note = "kit.json stays exactly as it was (there's no copy of the old version's to compare with)."
	} else {
		b, err := os.ReadFile(mine)
		if err != nil {
			die(oserr(err))
		}
		ours, err := parseJSON(b)
		if err != nil {
			return "" // loadConfig says what's wrong with it, and the merge waits until it's fixed
		}
		merged := merge3(base, ours, theirs)
		text := theirsText
		if !pyEqual(merged, theirs) {
			text = dumps(merged, jsonStyle{indent: 2}) + "\n"
		}
		mustSave(mine, text)
		note = "kit.json is the new version's."
		if !pyEqual(ours, base) {
			note = "kit.json is the new version's, with your changes kept."
		}
	}
	mustSave(baseFile, theirsText)
	return note
}

func loadConfig(root string) *obj {
	path := filepath.Join(dataDir(root), "kit.json")
	data, err := os.ReadFile(path)
	if err != nil {
		die(oserr(err))
	}
	v, err := parseJSON(data)
	var je *jsonError
	if errors.As(err, &je) {
		die(fmt.Sprintf("kit.json has a syntax error on line %d, column %d: %s", je.line, je.col, je.msg))
	}
	cfg, ok := v.(*obj)
	if !ok {
		die("kit.json has a syntax error on line 1, column 1: it isn't a list of settings in { }")
	}
	if !cfg.has("settings") {
		cfg.set("settings", newObj())
	}
	if cfg.child("settings") == nil {
		cfg.set("settings", newObj()) // (Python would stop on it)
	}
	for _, s := range sections {
		if !cfg.has(s) {
			cfg.set(s, []any{})
		}
	}
	return cfg
}

// Programs, as opposed to the books, models and map data they serve: the kinds of source tools/pins.json can pin.
var pinnedTypes = []string{"github", "kiwix_release", "adoptium", "maven", "npm", "github_archive"}

const pinGone = "the build this version of the kit names (tools/pins.json). Run SETUP to update the kit, " +
	"or set \"pin_programs\": false in kit.json"

// loadPins is tools/pins.json: the exact build of each program this version of the kit installs, and its SHA-256.
// Every release brings its own copy, signed with the rest, so a drive gets a new build of a program only with a new
// version of the kit, and a file swapped upstream under the same version is refused. ./kit pins writes it.
// "pin_programs": false in kit.json's settings takes the newest builds instead.
func loadPins(root string, cfg *obj) map[string]*obj {
	pins := map[string]*obj{}
	if v, ok := cfg.child("settings").lookup("pin_programs"); ok && v == false {
		return pins
	}
	data, err := os.ReadFile(filepath.Join(appDir(root), "tools", "pins.json"))
	if err != nil {
		return pins
	}
	all, err := parseObj(data)
	if err != nil {
		return pins
	}
	for _, k := range all.Keys() {
		if v, ok := all.get(k).(*obj); ok {
			if _, ok := v.get("version").(string); ok {
				pins[k] = v
			}
		}
	}
	return pins
}

var regionsCache *obj

// regions is tools/regions.json: the places "Where do you live?" offers and Wikipedia's languages, made by
// site/build_regions.py from Geofabrik, Photon, Kiwix and GeoNames.
func regions() *obj {
	if regionsCache == nil {
		regionsCache = newObj()
		if data, err := os.ReadFile(regionsFile()); err == nil {
			if o, err := parseObj(data); err == nil {
				regionsCache = o
			}
		}
		if !regionsCache.has("regions") {
			regionsCache.set("regions", []any{})
		}
		if !regionsCache.has("languages") {
			regionsCache.set("languages", newObj())
		}
	}
	return regionsCache
}

func regionByID(ident any) *obj {
	if !truthy(ident) {
		return nil
	}
	for _, r := range regions().objs("regions") {
		if pyEqual(r.get("id"), ident) {
			return r
		}
	}
	return nil
}

// regionsOf is the places kit.json's region names, one id or a list of them as ./kit region sets it, and the first
// id the kit doesn't know, if any.
func regionsOf(v any) ([]*obj, string) {
	ids, ok := v.([]any)
	if !ok {
		ids = []any{v}
	}
	var rs []*obj
	for _, id := range ids {
		r := regionByID(id)
		if r == nil {
			return nil, pyStr(id)
		}
		if !slices.Contains(rs, r) {
			rs = append(rs, r)
		}
	}
	return rs, ""
}

var pbfPath = regexp.MustCompile(`^[a-z0-9][a-z0-9/_-]*-latest\.osm\.pbf$`)

// regionMaps is the map settings for places, as kit.json's maps would spell them: street detail and directions for
// all of them (several places have a list of map areas and of road data, which can only come from Geofabrik), and
// the first place's home, units, language and address search.
func regionMaps(rs ...*obj) (*obj, error) {
	var called []string
	var boxes, roads []any
	for _, r := range rs {
		pbf := r.str("pbf")
		if strings.Contains(pbf, "..") || !pbfPath.MatchString(pbf) {
			return nil, fmt.Errorf("tools/regions.json has a bad road data path for %s", pyStr(r.get("id")))
		}
		called, boxes = append(called, r.str("name")), append(boxes, r.get("bbox"))
		roads = append(roads, strings.TrimRight(geofabrik, "/")+"/"+pbf)
	}
	first := rs[0]
	country := ""
	if truthy(first.get("photon")) { // Photon publishes none for a few places
		country = first.str("country")
	}
	lang := any("en")
	if l := first.list("langs"); len(l) > 0 {
		lang = l[0]
	}
	m := newObj("label", names(called), "home", with(first.child("home"), "zoom", 10), "detail_bbox", boxes[0],
		"routing_osm_pbf", roads[0],
		"geocoder_country", country,
		// a place with no address database of its own gets its whole region of the world's (most of Europe)
		"geocoder_wide", truthy(first.get("addresses_wide")),
		"units", first.get("units"), "lang", lang)
	if len(rs) > 1 {
		m.set("detail_bbox", boxes)
		m.set("routing_osm_pbf", roads)
	}
	return m, nil
}

// mapAreas is the map's areas, [west, south, east, north] each: detail_bbox is one, or a list of them.
func mapAreas(m *obj) ([][]float64, error) {
	v := m.get("detail_bbox")
	l, _ := v.([]any)
	if len(l) == 0 {
		return nil, fmt.Errorf("detail_bbox in kit.json's maps isn't a map area: %s", pyRepr(v))
	}
	if _, nested := l[0].([]any); !nested {
		l = []any{v}
	}
	var out [][]float64
	for _, b := range l {
		box, err := floats(b)
		if err != nil {
			return nil, err
		}
		if len(box) != 4 {
			return nil, fmt.Errorf("expected 4 values in detail_bbox, got %d", len(box))
		}
		out = append(out, box)
	}
	return out, nil
}

// numbers is a map area's numbers, as the map programs take them.
func numbers(box []float64) []string {
	var out []string
	for _, x := range box {
		out = append(out, strconv.FormatFloat(x, 'f', -1, 64))
	}
	return out
}

func mapsSettings(cfg *obj) *obj {
	user := cfg.child("maps")
	if user == nil {
		user = newObj()
	}
	preset := newObj()
	if truthy(user.get("region")) {
		if rs, unknown := regionsOf(user.get("region")); unknown != "" {
			preset = newObj("region_error", "kit.json's region '"+unknown+"' isn't one the kit "+
				"knows; ./kit region --find WORDS lists them")
		} else if p, err := regionMaps(rs...); err != nil {
			preset = newObj("region_error", err.Error())
		} else {
			preset = p
		}
	}
	m := mapsDefaults()
	for _, src := range []*obj{preset, user} {
		for _, k := range src.Keys() {
			m.set(k, src.get(k))
		}
	}
	home := mapsDefaults().child("home")
	for _, src := range []*obj{preset.child("home"), user.child("home")} {
		for _, k := range src.Keys() {
			home.set(k, src.get(k))
		}
	}
	m.set("home", home)
	if user.has("geocoder_country") && !user.has("geocoder_wide") {
		m.set("geocoder_wide", false)
	}
	return m
}

func mapsItems(cfg *obj) []*obj {
	m := mapsSettings(cfg)
	if !truthy(m.get("enabled")) {
		return nil
	}
	items := []*obj{
		newObj("id", "maplibre-gl", "type", "npm", "package", "maplibre-gl", "version_prefix", "5.", "priority", 1,
			"note", "Map display engine (MapLibre)"),
		newObj("id", "protomaps-basemaps", "type", "npm", "package", "@protomaps/basemaps", "version_prefix", "5.",
			"priority", 1, "note", "Map style (Protomaps)"),
		newObj("id", "basemaps-assets", "type", "github_archive", "repo", "protomaps/basemaps-assets", "branch", "main",
			"priority", 1, "note", "Map fonts and icons"),
		newObj("id", "routing", "type", "routing", "url", m.get("routing_osm_pbf"), "priority", 2,
			"note", "Road network for directions (GraphHopper)"),
		newObj("id", "basemap", "type", "protomaps", "priority", 2, // after routing: its size estimate uses the road data's
			"note", "Offline map: "+pyStr(m.get("label"))+" in street detail, plus a world overview"),
	}
	if truthy(m.get("geocoder_country")) {
		items = append(items, newObj("id", "geocoder", "type", "photon_db", "country", m.get("geocoder_country"),
			"priority", 3, "wide", truthy(m.get("geocoder_wide")), "note", "Address and place search database (Photon)"))
	}
	return items
}

func itemsFromConfig(cfg *obj) []*item {
	var items []*item
	mapsOn := truthy(mapsSettings(cfg).get("enabled"))
	for _, section := range sections {
		var entries []*obj
		if section == "maps" {
			entries = mapsItems(cfg)
		} else {
			for _, e := range cfg.list(section) {
				if o, ok := e.(*obj); ok {
					entries = append(entries, o)
				} else {
					log(fmt.Sprintf("WARNING: an entry in '%s' has no id/zim, skipped: %s", section, pyRepr(e)))
				}
			}
		}
		for _, entry := range entries {
			if pyEqual(entry.get("requires"), "maps") && !mapsOn {
				entry = with(entry, "enabled", false)
			}
			var ident any
			if section == "library" {
				entry = with(newObj("type", "zim"), kvs(entry)...)
				ident = entry.get("zim")
			} else {
				ident = entry.get("id")
			}
			if !truthy(ident) {
				log(fmt.Sprintf("WARNING: an entry in '%s' has no id/zim, skipped: %s", section, pyRepr(entry)))
				continue
			}
			items = append(items, newItem(section, pyStr(ident), entry))
		}
	}
	return items
}

// kvs is an object's keys and values, for with().
func kvs(o *obj) []any {
	var l []any
	for _, k := range o.Keys() {
		l = append(l, k, o.get(k))
	}
	return l
}

func statePath(root string) string { return filepath.Join(metaDir(root), "state.json") }

func loadState(root string) *obj {
	p := statePath(root)
	if data, err := os.ReadFile(p); err == nil {
		v, err := parseJSON(data)
		if err == nil {
			if o, ok := v.(*obj); ok {
				if o.child("items") == nil {
					o.set("items", newObj()) // (Python would stop on it)
				}
				return o
			}
		}
		backup := strings.TrimSuffix(p, ".json") + ".corrupt.json"
		copyFile(p, backup)
		log(fmt.Sprintf("WARNING: state file was unreadable; saved a copy to %s and starting fresh "+
			"(existing files will be re-verified, not re-downloaded).", backup))
	}
	return newObj("version", 1, "items", newObj())
}

func saveState(root string, state *obj) {
	p := statePath(root)
	os.MkdirAll(filepath.Dir(p), 0o755)
	tmp := strings.TrimSuffix(p, ".json") + ".tmp"
	if err := os.WriteFile(tmp, []byte(dumps(state, jsonStyle{indent: 2, sortKeys: true, ascii: true})), 0o644); err != nil {
		die(fmt.Sprintf("couldn't save %s: %s", p, oserr(err)))
	}
	if err := replace(tmp, p); err != nil {
		die(fmt.Sprintf("couldn't save %s: %s", p, oserr(err)))
	}
}

// stateItems is state.json's items, by key.
func stateItems(state *obj) *obj {
	it := state.child("items")
	if it == nil {
		it = newObj()
		state.set("items", it)
	}
	return it
}

func copyFile(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	st, err := in.Stat()
	if err != nil {
		return err
	}
	o, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, st.Mode().Perm()|0o200)
	if err != nil {
		return err
	}
	if _, err := io.Copy(o, in); err != nil {
		o.Close()
		return err
	}
	if err := o.Close(); err != nil {
		return err
	}
	return os.Chtimes(dst, st.ModTime(), st.ModTime())
}

// ----------------------------------------------------------------------------- kit.json's three-way merge

// missing stands for a key or item that isn't there.
var missing = &struct{ name string }{"missing"}

func itemKeyOf(x any) any {
	if o, ok := x.(*obj); ok {
		if v := o.get("id"); truthy(v) {
			return v
		}
		return o.get("zim")
	}
	return nil
}

// hashKey is a value as a Python dict key: 1, 1.0 and True are the same key.
func hashKey(v any) string {
	if s, ok := v.(string); ok {
		return "s" + s
	}
	if f, ok := asNumber(v); ok {
		return "n" + pyFloat(f)
	}
	return "j" + dumpsLine(v)
}

// keyed is a kit.json list of items (models, books...): these merge item by item.
func keyed(x any) bool {
	l, ok := x.([]any)
	if !ok || len(l) == 0 {
		return false
	}
	for _, i := range l {
		if !truthy(itemKeyOf(i)) {
			return false
		}
	}
	return true
}

type keyedItems struct {
	order []string
	byKey map[string]any
	key   map[string]any
}

func byItemKey(l any) keyedItems {
	k := keyedItems{byKey: map[string]any{}, key: map[string]any{}}
	list, _ := l.([]any)
	for _, i := range list {
		h := hashKey(itemKeyOf(i))
		if _, ok := k.byKey[h]; !ok {
			k.order = append(k.order, h)
		}
		k.byKey[h] = i
	}
	return k
}

func (k keyedItems) get(h string) any {
	if v, ok := k.byKey[h]; ok {
		return v
	}
	return missing
}

// merge3 is a three-way merge of kit.json values: this kit's changes (base to ours) win, and the new version's (base
// to theirs) apply everywhere else.
func merge3(base, ours, theirs any) any {
	if pyEqual(ours, base) {
		return theirs
	}
	if pyEqual(theirs, base) || pyEqual(theirs, ours) {
		return ours
	}
	o, oOK := ours.(*obj)
	t, tOK := theirs.(*obj)
	if oOK && tOK {
		b, _ := base.(*obj)
		merged := newObj()
		keys := t.Keys()
		for _, k := range o.Keys() {
			if !t.has(k) {
				keys = append(keys, k)
			}
		}
		for _, k := range keys {
			v := merge3(b.getOr(k, missing), o.getOr(k, missing), t.getOr(k, missing))
			if v != missing {
				merged.set(k, v)
			}
		}
		return merged
	}
	if keyed(ours) && keyed(theirs) {
		b := keyedItems{byKey: map[string]any{}}
		if keyed(base) {
			b = byItemKey(base)
		}
		ok, tk := byItemKey(ours), byItemKey(theirs)
		keys := append([]string(nil), tk.order...)
		for _, k := range ok.order {
			if _, in := tk.byKey[k]; !in {
				keys = append(keys, k)
			}
		}
		items := []any{}
		for _, k := range keys {
			_, inT := tk.byKey[k]
			bv, inB := b.byKey[k]
			ov, inO := ok.byKey[k]
			if !inT && inB && inO {
				bo, _ := bv.(*obj)
				oo, _ := ov.(*obj)
				if pyEqual(with(oo, "enabled", 0), with(bo, "enabled", 0)) {
					continue // the new version dropped it (gone from its source): being switched on or off doesn't keep it
				}
			}
			v := merge3(b.get(k), ok.get(k), tk.get(k))
			if v != missing {
				items = append(items, v)
			}
		}
		return items
	}
	return ours
}

// ----------------------------------------------------------------------------- the command line

// A command and its options, which parse and print help the way Python's argparse does, as ./kit always has.
type cliArg struct {
	names   []string // "-y", "--yes"; none for a positional
	dest    string
	kind    string // "flag", "value", "list" (nargs *); positionals: "one", "?", "*", "+"
	metavar string
	help    string
	choices []string
}

type cliCmd struct {
	name, help string
	args       []cliArg
	run        func(root string, a *cliArgs)
}

type cliArgs struct {
	cmd   string
	vals  map[string]string
	lists map[string][]string
	given map[string]bool
}

func (a *cliArgs) flag(dest string) bool     { return a.given[dest] }
func (a *cliArgs) has(dest string) bool      { return a.given[dest] }
func (a *cliArgs) str(dest string) string    { return a.vals[dest] }
func (a *cliArgs) list(dest string) []string { return a.lists[dest] }
func flagArg(names, help string) cliArg {
	return cliArg{names: strings.Fields(names), kind: "flag", help: help}
}
func valueArg(names, meta, help string) cliArg {
	return cliArg{names: strings.Fields(names), kind: "value", metavar: meta, help: help}
}
func listArg(names, meta, help string) cliArg {
	return cliArg{names: strings.Fields(names), kind: "list", metavar: meta, help: help}
}
func posArg(dest, kind, help string, choices ...string) cliArg {
	return cliArg{dest: dest, kind: kind, help: help, choices: choices}
}

func (c *cliArg) destName() string {
	if c.dest != "" {
		return c.dest
	}
	for _, n := range c.names {
		if strings.HasPrefix(n, "--") {
			return strings.ReplaceAll(n[2:], "-", "_")
		}
	}
	return strings.TrimLeft(c.names[0], "-")
}

func (c *cliArg) meta() string {
	if c.metavar != "" {
		return c.metavar
	}
	if len(c.choices) > 0 {
		return "{" + strings.Join(c.choices, ",") + "}"
	}
	if c.names == nil {
		return c.destName()
	}
	return strings.ToUpper(c.destName())
}

func (c *cliArg) usage() string {
	m := c.meta()
	switch c.kind {
	case "flag":
		return "[" + c.names[0] + "]"
	case "value":
		return "[" + c.names[0] + " " + m + "]"
	case "list":
		return "[" + c.names[0] + " [" + m + " ...]]"
	case "?":
		return "[" + m + "]"
	case "*":
		return "[" + m + " ...]"
	case "+":
		return m + " [" + m + " ...]"
	}
	return m
}

func (c *cliArg) invocation() string {
	if c.names == nil {
		return c.meta()
	}
	switch c.kind {
	case "value":
		return strings.Join(c.names, " "+c.meta()+", ") + " " + c.meta()
	case "list":
		return strings.Join(c.names, " ["+c.meta()+" ...], ") + " [" + c.meta() + " ...]"
	}
	return strings.Join(c.names, ", ")
}

var helpArg = cliArg{names: []string{"-h", "--help"}, kind: "flag", help: "show this help message and exit"}

var rootArg = cliArg{names: []string{"--root"}, kind: "value", help: "kit folder (default: the folder containing ./kit)"}

// helpWidth is argparse's: the terminal's width (80 when it isn't one), less 2.
func helpWidth() int {
	if n, err := strconv.Atoi(os.Getenv("COLUMNS")); err == nil && n > 0 {
		return n - 2
	}
	if w := terminalWidth(); w > 0 {
		return w - 2
	}
	return 78
}

// wrapText is textwrap.wrap: words on lines of at most width.
func wrapText(text string, width int) []string {
	var lines []string
	line := ""
	for _, w := range strings.Fields(text) {
		switch {
		case line == "":
			line = w
		case len(line)+1+len(w) <= width:
			line += " " + w
		default:
			lines = append(lines, line)
			line = w
		}
	}
	if line != "" {
		lines = append(lines, line)
	}
	return lines
}

// usageText is argparse's usage line, wrapped the way argparse wraps it.
func usageText(prog string, opts, pos []string) string {
	width := helpWidth()
	prefix := "usage: "
	all := append(append([]string{}, opts...), pos...)
	one := prog
	if len(all) > 0 {
		one += " " + strings.Join(all, " ")
	}
	if len(prefix)+len(one) <= width {
		return prefix + one
	}
	getLines := func(parts []string, indent string, first bool) []string {
		var lines []string
		var line []string
		lineLen := len(indent) - 1
		if first {
			lineLen = len(prefix) - 1
		}
		for _, p := range parts {
			if lineLen+1+len(p) > width && len(line) > 0 {
				lines = append(lines, indent+strings.Join(line, " "))
				line, lineLen = nil, len(indent)-1
			}
			line = append(line, p)
			lineLen += len(p) + 1
		}
		if len(line) > 0 {
			lines = append(lines, indent+strings.Join(line, " "))
		}
		if first && len(lines) > 0 {
			lines[0] = lines[0][len(indent):]
		}
		return lines
	}
	var lines []string
	if float64(len(prefix)+len(prog)) <= 0.75*float64(width) {
		indent := strings.Repeat(" ", len(prefix)+len(prog)+1)
		if len(opts) > 0 {
			lines = getLines(append([]string{prog}, opts...), indent, true)
			lines = append(lines, getLines(pos, indent, false)...)
		} else if len(pos) > 0 {
			lines = getLines(append([]string{prog}, pos...), indent, true)
		} else {
			lines = []string{prog}
		}
	} else {
		indent := strings.Repeat(" ", len(prefix))
		lines = getLines(append(append([]string{}, opts...), pos...), indent, false)
		lines = append([]string{prog}, lines...)
	}
	return prefix + strings.Join(lines, "\n")
}

type helpRow struct {
	indent     int
	invocation string
	help       string
}

// helpPos is the column help starts in, as argparse works it out from every row.
func helpPos(rows []helpRow) int {
	most := 0
	for _, r := range rows {
		if n := r.indent + len(r.invocation); n > most {
			most = n
		}
	}
	return min(most+2, 24)
}

func formatRows(rows []helpRow, pos int) string {
	hw := max(helpWidth()-pos, 11)
	var b strings.Builder
	for _, r := range rows {
		head := strings.Repeat(" ", r.indent) + r.invocation
		aw := pos - r.indent - 2
		lines := wrapText(r.help, hw)
		switch {
		case len(lines) == 0:
			b.WriteString(head + "\n")
			continue
		case len(r.invocation) <= aw:
			b.WriteString(head + strings.Repeat(" ", aw-len(r.invocation)+2) + lines[0] + "\n")
		default:
			b.WriteString(head + "\n" + strings.Repeat(" ", pos) + lines[0] + "\n")
		}
		for _, l := range lines[1:] {
			b.WriteString(strings.Repeat(" ", pos) + l + "\n")
		}
	}
	return b.String()
}

func commandHelp(c *cliCmd) string {
	args := append([]cliArg{helpArg}, c.args...)
	var opts, pos []string
	var optRows, posRows []helpRow
	for i := range args {
		a := &args[i]
		if a.names == nil {
			pos = append(pos, a.usage())
			posRows = append(posRows, helpRow{2, a.invocation(), a.help})
		} else {
			opts = append(opts, a.usage())
			optRows = append(optRows, helpRow{2, a.invocation(), a.help})
		}
	}
	at := helpPos(append(append([]helpRow{}, posRows...), optRows...))
	text := usageText("kit "+c.name, opts, pos) + "\n"
	if len(posRows) > 0 {
		text += "\npositional arguments:\n" + formatRows(posRows, at)
	}
	return text + "\noptions:\n" + formatRows(optRows, at)
}

func commandNames() []string {
	var names []string
	for _, c := range commands {
		names = append(names, c.name)
	}
	return names
}

func topHelp() string {
	choice := "{" + strings.Join(commandNames(), ",") + "}"
	rows := []helpRow{{2, choice, ""}}
	for _, c := range commands {
		rows = append(rows, helpRow{4, c.name, c.help})
	}
	opts := []helpRow{{2, helpArg.invocation(), helpArg.help}, {2, rootArg.invocation(), rootArg.help}}
	at := helpPos(append(append([]helpRow{}, rows...), opts...))
	return topUsage() + "\n\n" + kitDoc + "\npositional arguments:\n" + formatRows(rows, at) + "\noptions:\n" + formatRows(opts, at)
}

func usageError(prog, usage, msg string) {
	fmt.Fprint(os.Stderr, usage+"\n"+prog+": error: "+msg+"\n")
	os.Exit(2)
}

func cmdUsage(c *cliCmd) string {
	args := append([]cliArg{helpArg}, c.args...)
	var opts, pos []string
	for i := range args {
		if args[i].names == nil {
			pos = append(pos, args[i].usage())
		} else {
			opts = append(opts, args[i].usage())
		}
	}
	return usageText("kit "+c.name, opts, pos)
}

func topUsage() string {
	return usageText("kit", []string{"[-h]", "[--root ROOT]"}, []string{"{" + strings.Join(commandNames(), ",") + "} ..."})
}

// matchOption finds an option by its name, or a unique start of its long name (argparse allows those).
func matchOption(args []cliArg, word string) (*cliArg, string, bool) {
	name, value, hasValue := strings.Cut(word, "=")
	if !strings.HasPrefix(word, "--") {
		name, value, hasValue = word, "", false
		if len(word) > 2 {
			name, value, hasValue = word[:2], word[2:], true
		}
	}
	var found []*cliArg
	for i := range args {
		for _, n := range args[i].names {
			if n == name {
				return &args[i], value, hasValue
			}
		}
	}
	if strings.HasPrefix(name, "--") {
		for i := range args {
			for _, n := range args[i].names {
				if strings.HasPrefix(n, name) {
					found = append(found, &args[i])
				}
			}
		}
	}
	if len(found) == 1 {
		return found[0], value, hasValue
	}
	return nil, "", false
}

func looksLikeOption(s string) bool {
	if !strings.HasPrefix(s, "-") || s == "-" {
		return false
	}
	_, err := strconv.ParseFloat(s, 64)
	return err != nil
}

// parseArgs reads a command's options and positionals.
func parseArgs(c *cliCmd, words []string) *cliArgs {
	a := &cliArgs{cmd: c.name, vals: map[string]string{}, lists: map[string][]string{}, given: map[string]bool{}}
	prog, usage := "kit "+c.name, cmdUsage(c)
	var positional, extra []string
	all := append([]cliArg{helpArg}, c.args...)
	for i := 0; i < len(words); i++ {
		w := words[i]
		if w == "--" {
			positional = append(positional, words[i+1:]...)
			break
		}
		if !looksLikeOption(w) {
			positional = append(positional, w)
			continue
		}
		o, value, hasValue := matchOption(all, w)
		if o == nil {
			extra = append(extra, w)
			continue
		}
		d := o.destName()
		switch o.kind {
		case "flag":
			if d == "help" {
				out(commandHelp(c))
				os.Exit(0)
			}
			if hasValue {
				usageError(prog, usage, fmt.Sprintf("argument %s: ignored explicit argument '%s'", strings.Join(o.names, "/"), value))
			}
			a.given[d] = true
		case "value":
			if !hasValue {
				if i+1 >= len(words) || looksLikeOption(words[i+1]) {
					usageError(prog, usage, fmt.Sprintf("argument %s: expected one argument", strings.Join(o.names, "/")))
				}
				i++
				value = words[i]
			}
			a.vals[d], a.given[d] = value, true
		case "list":
			l := []string{}
			if hasValue {
				l = append(l, value)
			}
			for i+1 < len(words) && !looksLikeOption(words[i+1]) && words[i+1] != "--" && !hasValue {
				i++
				l = append(l, words[i])
			}
			a.lists[d], a.given[d] = l, true
		}
	}
	for i := range c.args {
		p := &c.args[i]
		if p.names != nil {
			continue
		}
		d := p.destName()
		switch p.kind {
		case "one":
			if len(positional) == 0 {
				usageError(prog, usage, "the following arguments are required: "+d)
			}
			a.vals[d], a.given[d], positional = positional[0], true, positional[1:]
		case "?":
			if len(positional) > 0 {
				a.vals[d], a.given[d], positional = positional[0], true, positional[1:]
			}
		case "*", "+":
			if p.kind == "+" && len(positional) == 0 {
				usageError(prog, usage, "the following arguments are required: "+d)
			}
			a.lists[d], a.given[d], positional = positional, len(positional) > 0, nil
		}
		if v, ok := a.vals[d]; ok && len(p.choices) > 0 && !contains(p.choices, v) {
			usageError(prog, usage, fmt.Sprintf("argument %s: invalid choice: '%s' (choose from %s)", d, v, quoteList(p.choices)))
		}
	}
	extra = append(extra, positional...)
	if len(extra) > 0 {
		usageError("kit", topUsage(), "unrecognized arguments: "+strings.Join(extra, " "))
	}
	return a
}

func quoteList(l []string) string {
	q := make([]string, len(l))
	for i, s := range l {
		q[i] = "'" + s + "'"
	}
	return strings.Join(q, ", ")
}

var commands []*cliCmd

func isKitCommand(name string) bool {
	for _, c := range commands {
		if c.name == name {
			return true
		}
	}
	return false
}

func init() {
	only := listArg("--only", "", "limit to items whose section/id contains these words")
	onOff := posArg("action", "?", "", "on", "off")
	commands = []*cliCmd{
		{name: "plan", help: "preview what sync would do", run: cmdPlan, args: []cliArg{only,
			flagArg("--json", "print every item's size as JSON, disabled ones too"),
			flagArg("--essentials", "only what the kit can't do without"),
			flagArg("--starter", "only the try-it kit")}},
		{name: "sync", help: "download and update everything", run: cmdSync, args: []cliArg{
			flagArg("-y --yes", "don't ask for confirmation"),
			flagArg("--force", "ignore the free space the kit keeps (keep_free_gb)"),
			only,
			flagArg("--essentials", "only the programs, the map, the most important books and the AI this computer runs plus the smallest"),
			flagArg("--starter", "only the try-it kit: a few GB to try the kit with")}},
		{name: "verify", help: "re-check files against their checksums", run: cmdVerify, args: []cliArg{
			flagArg("--quick", "check sizes only (fast)"),
			flagArg("--fix", "delete corrupt files so the next sync replaces them")}},
		{name: "status", help: "show what's installed", run: cmdStatus},
		{name: "search", help: "search the Kiwix catalog for more content", run: cmdSearch, args: []cliArg{posArg("words", "+", "")}},
		{name: "test", help: "check that the offline servers start and answer", run: cmdTest, args: []cliArg{
			valueArg("--model", "", "model folder name to test (default: the smallest)")}},
		{name: "open", help: "start the kit's servers and open its page, as Open Tinfoil Kit does", args: []cliArg{
			flagArg("--share", "let phones and laptops on your home network in too, with the access code"),
			valueArg("--model", "NAME", "the AI to load first: a folder in downloads/models"),
			flagArg("--no-browser", "don't open the page in a browser"),
			flagArg("--no-maps", "don't start the map's servers, which saves about 5 GB of memory")}},
		{name: "update", help: "install the newest version of the kit's own code, keeping kit.json changes", run: cmdUpdate, args: []cliArg{
			flagArg("--force", "reinstall even if this is the newest version"),
			flagArg("-y --yes", "don't ask before installing")}},
		{name: "pins", help: "pin the newest build of every program, with its checksum, in tools/pins.json (before a release)", run: cmdPins},
		{name: "estimate", help: "about how many GB this kit.json needs (no internet needed)", run: cmdEstimate, args: []cliArg{
			flagArg("--essentials", "just the essentials"),
			flagArg("--starter", "just the try-it kit"),
			flagArg("--rest", "GB still to download for everything switched on, and how long that takes (tab-separated)"),
			flagArg("--json", "the GB, and the items it counts (not the programs), as JSON")}},
		{name: "drives", help: "the plugged-in drives the kit could go on", run: cmdDrives, args: []cliArg{
			flagArg("--json", "with this computer's free space and what the kit needs")}},
		{name: "kits", help: "kits set up before, in the home folder or on a drive plugged in", run: cmdKits},
		{name: "place", help: "put the kit at DEST, a TinfoilKit folder on a drive or in the home folder", run: cmdPlace,
			args: []cliArg{posArg("dest", "one", "")}},
		{name: "space", help: "whether the kit, or just its essentials, fits at PATH with room to spare", run: cmdSpace, args: []cliArg{
			posArg("path", "one", ""), flagArg("--json", "print it all as JSON")}},
		{name: "essentials", help: "get just the essentials from now on (on), or everything again (off)", run: cmdEssentials,
			args: []cliArg{onOff}},
		{name: "starter", help: "get just the try-it kit from now on (on), or everything (off)", run: cmdStarter, args: []cliArg{onOff}},
		{name: "pick", help: "what goes in the kit, as the website's kit builder picks it: a preset, where you live, then what's different", run: cmdPick, args: []cliArg{
			flagArg("--ask", "ask the kit builder's questions: a preset, or each part"),
			flagArg("--recommended", "start over from the recommended kit: what we'd take"),
			flagArg("--essentials", "start over from just the essentials: the programs, the map, the most important books, Wikipedia's best articles, and the AI this computer runs plus the smallest"),
			flagArg("--everything", "start over from everything: every AI model and book, the biggest collections too"),
			valueArg("--region", "PLACES", "where you live, and places nearby after commas, as ./kit region takes them"),
			valueArg("--wikipedia", "CODES", "Wikipedia's languages, comma-separated (en, es, de...)"),
			valueArg("--wikipedia-size", "SIZE", "how much of Wikipedia: all, all-text, top, top-text or top-intros (./kit region -h)"),
			flagArg("--no-ai", "no AI models"),
			valueArg("--models", "IDS", "only these AI models (ids, comma-separated)"),
			valueArg("--skip", "IDS", "leave these out: AI models, books (a name, or its start up to an underscore, like wikipedia), maps, or a whole part (models, library, extras)"),
			valueArg("--add", "IDS", "add these, like the books that are off by default")}},
		{name: "remove", help: "delete what these downloaded, for the space, and switch them off", run: cmdRemove, args: []cliArg{
			{dest: "names", kind: "+", metavar: "NAME", help: "an AI model, a book (or its name up to an underscore, like wikipedia), maps, or a whole part (models, library, extras)"},
			flagArg("-y --yes", "don't ask first")}},
		{name: "fit", help: "which AI model this computer runs, and the ones too big for its memory", run: cmdFit, args: []cliArg{
			flagArg("--ask", "ask whether to download the models it can't run (SETUP)"),
			flagArg("--skip-too-big", "switch off the models it can't run, in kit.json"),
			flagArg("--restore", "switch back on the ones skipped for a smaller computer"),
			flagArg("--json", "print it all as JSON")}},
		{name: "share", help: "let phones and laptops on your home network use the kit, with an access code", run: cmdShare, args: []cliArg{
			posArg("action", "?", "", "on", "off", "new-code"),
			valueArg("--code", "", "the access code to use (6 to 64 letters or digits) instead of a random one"),
			flagArg("--qr", "draw the QR code even when not printing to a terminal")}},
		{name: "autostart", help: "start the kit whenever this computer starts, for a home server", run: cmdAutostart, args: []cliArg{onOff}},
		{name: "region", help: "where you live, and places nearby: sets the map areas, directions, address search, home and Wikipedia's language; and how much of Wikipedia",
			run: cmdRegion, args: []cliArg{
				posArg("place", "*", "a US state or a country (a name, or an id from --find); several with commas, where you live first"),
				listArg("--find", "WORDS", "list the places matching WORDS: id, name, group"),
				flagArg("--languages", "the Wikipedia languages to offer for the place: codes, name, GB"),
				valueArg("--wikipedia", "CODES", "Wikipedia's languages, comma-separated (en, es, de...)"),
				valueArg("--wikipedia-size", "SIZE", "how much of Wikipedia: all (with pictures), all-text, top (the best 50,000 articles, with pictures), top-text or top-intros (their opening paragraphs)"),
				flagArg("--sizes", "the sizes of Wikipedia to offer in its languages: name, what it is, GB")}},
		{name: "layout", help: "move a kit from before its app, downloads and data folders into them (SETUP does)", run: cmdLayout},
	}
}

// runKit is the kit's command line: tinfoilkit [--root KIT] COMMAND [OPTIONS].
func runKit(words []string) (code int) {
	root := ""
	var cmd *cliCmd
	var rest []string
	for i := 0; i < len(words); i++ {
		w := words[i]
		switch {
		case w == "-h" || w == "--help":
			out(topHelp())
			return 0
		case w == "--root" || strings.HasPrefix(w, "--root=") || (strings.HasPrefix(w, "--r") && strings.HasPrefix("--root", strings.SplitN(w, "=", 2)[0])):
			if v, ok := strings.CutPrefix(w, strings.SplitN(w, "=", 2)[0]+"="); ok && strings.Contains(w, "=") {
				root = v
			} else if i+1 < len(words) {
				i++
				root = words[i]
			} else {
				usageError("kit", topUsage(), "argument --root: expected one argument")
			}
		case looksLikeOption(w):
			usageError("kit", topUsage(), "unrecognized arguments: "+w)
		default:
			for _, c := range commands {
				if c.name == w {
					cmd = c
				}
			}
			if cmd == nil {
				usageError("kit", topUsage(), fmt.Sprintf("argument cmd: invalid choice: '%s' (choose from %s)", w, quoteList(commandNames())))
			}
			rest = words[i+1:]
			i = len(words)
		}
	}
	if cmd == nil {
		out(topHelp())
		return 0
	}
	a := parseArgs(cmd, rest)
	if cmd.name == "open" { // the launcher stops its servers on Ctrl-C itself, and opens a kit as it is
		return openKit(root, a)
	}
	ready := false
	defer func() {
		if r := recover(); r != nil {
			switch v := r.(type) {
			case exitCode:
				code = int(v)
			case interrupted:
				log("\nStopped.")
				code = 130
				return
			default:
				panic(r)
			}
		}
		if ready { // after the command, which may be the sync that set the kit up here
			ensureTop(root)
		}
	}()
	watchCtrlC()
	if root == "" {
		root = kitOfCode(codeRoot)
	}
	root = resolvePath(root)
	if home, err := os.UserHomeDir(); err == nil && root == resolvePath(home) || filepath.Dir(root) == root {
		die(fmt.Sprintf("The kit can't use %s as its folder. Make a folder called %s there, put the app folder in "+
			"it, and run SETUP again", root, kitFolder))
	}
	if !contains([]string{"share", "autostart", "layout"}, cmd.name) && !which("curl") {
		die("curl is required")
	}
	if ensureLayout(root) && !isDir(filepath.Join(codeRoot, "tools")) { // this code just moved into app/
		codeRoot = appDir(root)
		regionsCache = nil
	}
	ensureConfig(root)
	ready = true
	cmd.run(root, a)
	return 0
}

// kitOfCode is the kit folder a code folder belongs to: app/'s parent, or a git checkout's kit folder itself.
func kitOfCode(code string) string {
	if strings.EqualFold(filepath.Base(code), "app") && !checkout(code) {
		return filepath.Dir(code)
	}
	return code
}

// resolvePath is Path.resolve(): absolute, with links followed as far as they go.
func resolvePath(p string) string {
	abs, err := filepath.Abs(p)
	if err != nil {
		return p
	}
	if r, err := filepath.EvalSymlinks(abs); err == nil {
		return r
	}
	// as much of it as there is
	dir, rest := abs, ""
	for {
		parent := filepath.Dir(dir)
		rest = filepath.Join(filepath.Base(dir), rest)
		if parent == dir {
			return abs
		}
		dir = parent
		if r, err := filepath.EvalSymlinks(dir); err == nil {
			return filepath.Join(r, rest)
		}
	}
}

// sortedKeys is an object's keys, sorted.
func sortedKeys(o *obj) []string {
	k := o.Keys()
	sort.Strings(k)
	return k
}

const kitFolder = "TinfoilKit" // at the top of a drive, or in the home folder

// this is what the kit calls this computer, and returnKey the key that ends an answer.
var this, returnKey = func() (string, string) {
	switch {
	case mac:
		return "this Mac", "Return"
	case windows:
		return "this PC", "Enter"
	}
	return "this computer", "Return"
}()
