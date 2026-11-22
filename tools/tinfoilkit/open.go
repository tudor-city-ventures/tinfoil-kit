package main

// Opening the kit: start the library server (kiwix-serve), the AI server (llama-server) and the map servers on
// 127.0.0.1, keep the page's notes and pins (in this program), share them on the home network if asked, then open the
// kit's page in the browser. Closing the window,
// Ctrl-C or the Mac app's Quit stops them all. What it prints matches tools/launch.sh (the Mac app reads it) and
// Open Tinfoil Kit for Windows.bat.

import (
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type proc struct {
	cmd  *exec.Cmd
	done chan struct{}
}

func (p *proc) alive() bool {
	if p == nil {
		return false
	}
	select {
	case <-p.done:
		return false
	default:
		return true
	}
}

type launcher struct {
	layout
	mu       sync.Mutex
	procs    []*proc
	stopping bool
}

type openOptions struct {
	share, noBrowser, noMaps, chosen bool
	model, root                      string
}

func runOpen(args []string) int {
	var o openOptions
	for i := 0; i < len(args); i++ {
		a := args[i]
		switch {
		case a == "--share":
			o.share = true
		case a == "--no-browser":
			o.noBrowser = true
		case a == "--no-maps":
			o.noMaps = true
		case strings.HasPrefix(a, "--model="):
			o.model, o.chosen = a[len("--model="):], true
		case a == "--root" && i+1 < len(args):
			o.root = args[i+1]
			i++
		case strings.HasPrefix(a, "--root="):
			o.root = a[len("--root="):]
		}
	}
	l := &launcher{layout: kitLayout(o.root)}
	return l.open(o)
}

// onThis picks what to say: tools/launch.sh's words on a Mac or Linux, Open Tinfoil Kit for Windows.bat's on Windows.
func onThis(unix, win string) string {
	if windows {
		return win
	}
	return unix
}

func (l *launcher) open(o openOptions) int {
	if err := os.Chdir(l.kit); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	os.MkdirAll(filepath.Join(l.data, "logs"), 0o755)
	os.MkdirAll(filepath.Join(l.data, ".kit"), 0o755)
	port := func(key string, def int) int {
		n, err := strconv.Atoi(setting(l.conf, key, strconv.Itoa(def)))
		if err != nil || n <= 0 || n > 65535 {
			return def
		}
		return n
	}
	libPort, aiPort, sharePort := port("library_port", 8888), port("ai_port", 8080), port("share_port", 8000)
	dataPort := port("data_port", 8095)
	tilesPort, geoPort, routePort := port("tiles_port", 8090), port("geocoder_port", 2322), port("routing_port", 8989)
	ctxSize := setting(l.conf, "context_size", "16384")
	geoHeap, routeHeap := setting(l.conf, "geocoder_heap", "3g"), setting(l.conf, "routing_heap", "2g")
	model := o.model
	if model == "" {
		model = setting(l.conf, "default_model", "")
	}
	if strings.EqualFold(setting(l.conf, "share_on_network", "false"), "true") {
		o.share = true
	}

	kiwix := os.Getenv("KIT_KIWIX_TOOLS_BIN")
	if kiwix == "" {
		kiwix = l.pickBin("kiwix-tools", "kiwix-serve")
	}
	llama := os.Getenv("KIT_LLAMACPP_BIN")
	if llama == "" {
		llama = l.pickBin("llama.cpp", "llama-server")
	}
	// macOS keeps Finder metadata for files on exFAT drives in "._name" files beside them. The servers scan library/
	// and models/ and could take ._name.zim or ._name.gguf for a book or a model.
	for _, dir := range []string{"library", "models"} {
		filepath.WalkDir(filepath.Join(l.dl, dir), func(p string, d os.DirEntry, err error) error {
			if err == nil && d.Type().IsRegular() && strings.HasPrefix(d.Name(), "._") {
				os.Remove(p)
			}
			return nil
		})
	}
	zims := filesWithSuffix(filepath.Join(l.dl, "library"), ".zim")
	models := modelFolders(filepath.Join(l.dl, "models"))

	say("", "  TINFOIL KIT", "  ===========")
	if kiwix == "" {
		l.missing("Library server", "kiwix-tools", "kiwix-serve")
	}
	if llama == "" {
		l.missing("AI server", "llama.cpp", "llama-server")
	}
	if len(zims) == 0 {
		say(onThis("  ! No library files in downloads/library. Run ./kit sync while online.",
			`  - No books in downloads\library. Run SETUP-Windows.bat while online.`))
	}
	if len(models) == 0 {
		say(onThis("  No AI models in downloads/models, so the AI stays off. If kit.json lists some, run ./kit sync while online.",
			`  No AI models in downloads\models, so the AI stays off. If data\kit.json lists some, run SETUP-Windows.bat while online.`))
	}
	model = l.pickModel(model, models, o.chosen)

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, stopSignals()...)
	go func() {
		<-sigs
		l.stop()
	}()

	// --- library
	// kiwix-serve checks the address it's given against this computer's network interfaces, but keeps only the last
	// IPv4 address of each: with a second one on the loopback, 127.0.0.1 "is not available on this system". It skips
	// link-local IPv6 addresses, so it does find ::1. Then the library listens there, and this program listens on
	// 127.0.0.1, where the page and every server's CORS rule expect the library, and passes each connection on.
	var libProc *proc
	var kargs []string
	libHost, libAt := "", "127.0.0.1"
	kiwixLog := filepath.Join(l.data, "logs", "kiwix-serve.log")
	startLibrary := func(address string) {
		libHost = address
		libProc = l.start(l.logFile("kiwix-serve.log", true), l.kit, nil, kiwix,
			append(append(append([]string{}, kargs...), "--address", address), zims...)...)
	}
	libraryOnIPv6 := func() bool { // kiwix-serve quit: if it was over 127.0.0.1, start it on ::1
		if b, _ := os.ReadFile(kiwixLog); libHost != "127.0.0.1" || !strings.Contains(string(b), "not available on this system") {
			return false
		}
		startLibrary("::1")
		if err := forward(libPort, "::1", libProc); err != nil {
			libAt = "::1"
			say("  ! The library server won't use 127.0.0.1 on this computer, so it listens on ::1. Ask and the map can't reach it",
				"    there: "+errText(err))
		} else {
			say("  The library server won't use 127.0.0.1 on this computer, so it listens on ::1 and the kit forwards 127.0.0.1 to it.")
		}
		return true
	}
	if ourLibrary(libPort) {
		say(fmt.Sprintf("  Library already running on port %d.", libPort))
	} else if kiwix != "" && len(zims) > 0 {
		if taken(libPort) {
			p := freePort(libPort)
			say(fmt.Sprintf("  Another program is using port %d, so the library uses %d.", libPort, p))
			libPort = p
		}
		// The page ./kit sync builds has the map inside; the bare template has no map. A newer template (kit code
		// updated, no sync since) shows up after the next sync, which rebuilds the page.
		portal := filepath.Join(l.data, ".kit", "portal.html")
		if !isFile(portal) {
			portal = filepath.Join(l.app, "tools", "portal.html")
		}
		kargs = []string{"--port", strconv.Itoa(libPort), "--customIndex", portal, "--threads", "4"}
		if helpSays(kiwix, "--skipInvalid") {
			kargs = append(kargs, "--skipInvalid")
		}
		os.WriteFile(kiwixLog, nil, 0o644)
		startLibrary("127.0.0.1")
		say(fmt.Sprintf("  Starting library (%d books)...", len(zims)))
	}

	// --- AI
	// Browsers accept exactly one allowed origin (llama-server would echo a list verbatim): the page at 127.0.0.1,
	// so other web pages can't read the AI's or the map's answers. Through the sharing gate, the page and the servers
	// share one address, so that needs none.
	cors := fmt.Sprintf("http://127.0.0.1:%d", libPort)
	var aiProc *proc
	if ourAI(aiPort) {
		say(fmt.Sprintf("  AI already running on port %d.", aiPort))
	} else if llama != "" && len(models) > 0 {
		if taken(aiPort) {
			p := freePort(aiPort)
			say(fmt.Sprintf("  Another program is using port %d, so the AI uses %d.", aiPort, p))
			aiPort = p
		}
		preset := filepath.Join(l.data, ".kit", "presets.ini")
		os.WriteFile(preset, []byte(fmt.Sprintf("version = 1\n\n[%s]\nload-on-startup = true\n", model)), 0o644)
		// AI chat is llama-server's own page, so it gets Ask's safety rules as its default system message. An
		// environment variable, not a flag: a llama-server too old to know it ignores it instead of refusing to start.
		var env []string
		if chat := filepath.Join(l.app, "tools", "ai-chat.json"); isFile(chat) {
			env = append(env, "LLAMA_ARG_UI_CONFIG_FILE="+chat)
		}
		aiProc = l.start(l.logFile("llama-server.log", false), l.kit, env, llama, "--models-dir", filepath.Join(l.dl, "models"),
			"--models-preset", preset, "--models-max", "1", "-c", ctxSize, "--host", "127.0.0.1",
			"--port", strconv.Itoa(aiPort), "--cors-origins", cors)
		say(fmt.Sprintf("  Starting AI (loading %s)...", model))
	}

	// --- notes and pins: the page keeps them in the data folder through this program, which a new version leaves
	var notes *notesServer
	if !ourNotes(dataPort) {
		if taken(dataPort) {
			p := freePort(dataPort)
			say(fmt.Sprintf("  Another program is using port %d, so the notes and pins server uses %d.", dataPort, p))
			dataPort = p
		}
		var w io.Writer = io.Discard
		if f := l.logFile("data.log", true); f != nil {
			w = f
		}
		if n, err := startNotes(l.data, w, dataPort, libPort); err == nil {
			notes, dataPort = n, n.port
		}
	}

	// --- maps: tiles, address search, directions
	var mapsStarted []string
	maps := filepath.Join(l.dl, "maps")
	withMaps := !o.noMaps && isDir(maps)
	if withMaps {
		pmtiles := l.pickBin("pmtiles", "pmtiles")
		java := l.pickBin("java", "java")
		photonJar := newest(filepath.Join(l.dl, "bin", "photon"), "photon-", ".jar")
		ghJar := newest(filepath.Join(l.dl, "bin", "graphhopper"), "graphhopper-web-", ".jar")
		var jopts []string
		if java != "" && mac {
			// Java looks up this computer's name as it starts (the address search's logging does). On a Mac, looking
			// up name.local asks to "find devices on local networks" unless the kit started from Terminal, so Java
			// gets a hosts file of its own that answers that name, and needs no other: every map server listens on
			// 127.0.0.1.
			n, _ := os.Hostname()
			line := fmt.Sprintf("127.0.0.1 localhost %s %s", n, strings.SplitN(n, ".", 2)[0])
			if out, _ := exec.Command("scutil", "--get", "LocalHostName").Output(); strings.TrimSpace(string(out)) != "" {
				line += " " + strings.TrimSpace(string(out)) + ".local"
			}
			hosts := filepath.Join(l.data, ".kit", "java-hosts")
			os.WriteFile(hosts, []byte(line+"\n::1 localhost\n"), 0o644)
			jopts = []string{"-Djdk.net.hosts.file=" + hosts}
		}
		// pmtiles answers /basemap.json, the TileJSON that says it is up, only when it has a --public-url
		if pmtiles != "" && isFile(filepath.Join(maps, "tiles", "basemap.pmtiles")) && !up(tilesPort, "/basemap.json") {
			tp := strconv.Itoa(tilesPort)
			l.start(l.logFile("tiles.log", false), l.kit, nil, pmtiles, "serve", filepath.Join(maps, "tiles"), "--port", tp,
				"--interface", "127.0.0.1", "--cors", cors, "--public-url", "http://127.0.0.1:"+tp)
			mapsStarted = append(mapsStarted, "map")
		}
		if java != "" && photonJar != "" && isDir(filepath.Join(maps, "geocoder", "photon_data")) && !up(geoPort, "/status") {
			jargs := append(append([]string{}, jopts...), "-Xmx"+geoHeap, "-jar", photonJar, "serve", "-data-dir",
				filepath.Join(maps, "geocoder"), "-listen-ip", "127.0.0.1", "-listen-port", strconv.Itoa(geoPort), "-cors-origin", cors)
			l.start(l.logFile("geocoder.log", false), l.kit, nil, java, jargs...)
			mapsStarted = append(mapsStarted, "address-search")
		}
		if java != "" && ghJar != "" && isFile(filepath.Join(maps, "routing", "graph-cache", "properties")) && !up(routePort, "/health") {
			jargs := append(append([]string{}, jopts...), "-Xmx"+routeHeap,
				"-Ddw.server.application_connectors[0].bind_host=127.0.0.1",
				"-Ddw.server.application_connectors[0].port="+strconv.Itoa(routePort), "-jar", ghJar, "server", "gh-serve.yml")
			l.start(l.logFile("routing.log", false), filepath.Join(maps, "routing"), nil, java, jargs...)
			mapsStarted = append(mapsStarted, "directions")
		}
		if len(mapsStarted) > 0 {
			say("  Starting maps: " + strings.Join(mapsStarted, " ") + " (address search and directions take up to a minute)...")
		}
	}

	// --- sharing on the home network: the gate asks for the access code, then passes requests on
	var g *gate
	shareOK, gateFailed := false, false
	if o.share {
		if ourGate(sharePort) {
			say(fmt.Sprintf("  Sharing already on, on port %d.", sharePort))
			shareOK = true
		} else {
			if taken(sharePort) {
				p := freePort(sharePort)
				if windows {
					say(fmt.Sprintf("  Another program is using port %d, so sharing uses %d.", sharePort, p),
						`  For an address that stays the same, set share_port in data\kit.json to a free port.`)
				} else {
					say(fmt.Sprintf("  Another program is using port %d, so sharing uses %d. For an address that stays the same, set", sharePort, p),
						"  share_port in kit.json to a free port.")
				}
				sharePort = p
			}
			ports := map[string]int{"library": libPort, "ai": aiPort, "data": dataPort}
			if withMaps {
				ports["tiles"], ports["geocoder"], ports["routing"] = tilesPort, geoPort, routePort
			}
			if windows {
				say("  Starting sharing on the home network...")
			}
			var err error
			if g, err = startGate(l.kit, filepath.Join(l.data, "logs", "share.log"), sharePort, ports); err != nil {
				gateFailed = true
			} else {
				sharePort, shareOK = g.port, true
				if windows {
					exe, _ := os.Executable()
					say(fmt.Sprintf("  If Windows asks whether %s may use the network, allow it, or phones and laptops can't reach the kit.", filepath.Base(exe)))
				}
			}
		}
	}

	// Keep the computer awake while the kit runs (the screen may still sleep). Windows: the gate does, when shared.
	pid := strconv.Itoa(os.Getpid())
	if mac {
		if c, err := exec.LookPath("caffeinate"); err == nil {
			l.start(nil, l.kit, nil, c, "-i", "-w", pid)
		}
	} else if !windows {
		if c, err := exec.LookPath("systemd-inhibit"); err == nil {
			// (tail --pid ends with this program, even if systemd-inhibit is stopped first)
			l.start(nil, l.kit, nil, c, "--what=sleep", "--who=Tinfoil Kit", "--why=The kit is running", "tail", "--pid="+pid, "-f", "/dev/null")
		}
	}

	// Wait for each server to answer, unless this window didn't start it or it has already quit.
	libOK, aiOK := false, false
	for i := 0; i < 60; i++ {
		if libOK = ourLibraryAt(libAt, libPort); libOK || libProc == nil || !libProc.alive() && !libraryOnIPv6() {
			break
		}
		time.Sleep(time.Second)
	}
	for i := 0; i < 30; i++ {
		if aiOK = ourAI(aiPort); aiOK || !aiProc.alive() {
			break
		}
		time.Sleep(time.Second)
	}

	url := fmt.Sprintf("http://%s/?model=%s&ai=%d&data=%d", net.JoinHostPort(libAt, strconv.Itoa(libPort)), model, aiPort, dataPort)
	logs := onThis("data/logs/", `data\logs\`)
	say("")
	if libOK {
		say("  Library:  ready")
	} else {
		say("  Library:  NOT running" + lastError(kiwixLog) + " (see " + logs + "kiwix-serve.log)")
	}
	switch {
	case aiOK:
		say("  AI:       ready (the first answer takes longer while the model loads)")
	case len(models) == 0:
		say("  AI:       off (no models). The library still works.")
	default:
		say("  AI:       NOT running (see " + logs + "llama-server.log). The library still works.")
	}
	say("", "  Open:     "+url, fmt.Sprintf("  AI chat:  http://127.0.0.1:%d/", aiPort))
	if len(mapsStarted) > 0 {
		say("  Maps:     on the Map tab of the page above")
	}
	say("")
	if shareOK {
		say(banner(l.kit, sharePort, isTerminal(os.Stdout)), "")
	} else if gateFailed {
		say("  Sharing:  NOT running (see "+logs+"share.log)", "")
	}
	if windows {
		say("  Keep this window open. Close it to stop everything.")
	} else {
		say("  Keep this window open. Close it or press Ctrl-C to stop everything.")
	}
	if !o.noBrowser && libOK {
		openBrowser(url)
	}

	l.mu.Lock()
	running := append([]*proc{}, l.procs...)
	l.mu.Unlock()
	if windows {
		os.Chdir(os.TempDir()) // out of the kit folder, so nothing here holds it open (UNINSTALL can delete it)
	}
	if len(running) == 0 && g == nil && notes == nil {
		say("  (Nothing was started by this window.)")
		if !windows { // a window Windows opened for this closes when it ends: leave it for the person to read
			l.stop()
		}
	}
	if g != nil || notes != nil || windows {
		select {} // until the window closes
	}
	for _, p := range running {
		<-p.done
	}
	l.stop()
	return 0
}

// logFile opens a log in data/logs, emptied first or added to (keep).
func (l *launcher) logFile(name string, keep bool) *os.File {
	how := os.O_CREATE | os.O_WRONLY | os.O_TRUNC
	if keep {
		how = os.O_CREATE | os.O_WRONLY | os.O_APPEND
	}
	f, err := os.OpenFile(filepath.Join(l.data, "logs", name), how, 0o644)
	if err != nil {
		return nil
	}
	return f
}

// lastError is the last error a log has, as ": what it says", or "".
func lastError(log string) string {
	b, _ := os.ReadFile(log)
	why := ""
	for _, line := range strings.Split(string(b), "\n") {
		if strings.Contains(line, "ERROR") {
			why = strings.TrimRight(line, "\r")
		}
	}
	if i := strings.Index(why, "ERROR: "); i >= 0 {
		why = why[i+len("ERROR: "):]
	}
	if why == "" {
		return ""
	}
	return ": " + why
}

// start runs a server in the background, its output in out (or nowhere), and remembers it to stop it later.
func (l *launcher) start(out *os.File, dir string, env []string, prog string, args ...string) *proc {
	cmd := exec.Command(prog, args...)
	cmd.Dir = dir
	if len(env) > 0 {
		cmd.Env = append(os.Environ(), env...)
	}
	if out != nil {
		cmd.Stdout, cmd.Stderr = out, out
	}
	p := &proc{cmd: cmd, done: make(chan struct{})}
	l.mu.Lock()
	defer l.mu.Unlock()
	err := fmt.Errorf("stopping")
	if !l.stopping {
		err = cmd.Start()
	}
	if out != nil {
		if err != nil {
			fmt.Fprintf(out, "Couldn't start %s: %v\n", prog, err)
		}
		out.Close()
	}
	if err != nil {
		close(p.done)
		return p
	}
	l.procs = append(l.procs, p)
	go func() {
		cmd.Wait()
		close(p.done)
	}()
	return p
}

// stop stops everything this window started, then this program.
func (l *launcher) stop() {
	l.mu.Lock()
	l.stopping = true
	procs := append([]*proc{}, l.procs...)
	l.mu.Unlock()
	for _, p := range procs {
		if p.alive() {
			terminate(p.cmd.Process)
		}
	}
	deadline := time.Now().Add(3 * time.Second)
	for _, p := range procs {
		select {
		case <-p.done:
		case <-time.After(time.Until(deadline)):
		}
	}
	say("", "  Stopped.")
	os.Exit(0)
}

// pickBin finds a runnable copy of a program: the current version first, then any older one kept as a fallback.
func (l *launcher) pickBin(product, binary string) string {
	if windows {
		binary += ".exe"
	}
	base := filepath.Join(l.dl, "bin", product+"-"+plat())
	if !isDir(base) {
		return ""
	}
	var cands []string
	cur := ""
	if b, err := os.ReadFile(filepath.Join(base, "CURRENT")); err == nil {
		cur = strings.TrimSpace(string(b))
		if cur != "" && isDir(filepath.Join(base, cur)) {
			cands = append(cands, filepath.Join(base, cur))
		}
	}
	entries, _ := os.ReadDir(base)
	for _, e := range entries {
		if e.IsDir() && e.Name() != cur && !strings.HasPrefix(e.Name(), ".") {
			cands = append(cands, filepath.Join(base, e.Name()))
		}
	}
	for _, d := range cands {
		p := findFile(d, binary)
		if p == "" {
			continue
		}
		if windows {
			return p
		}
		if st, err := os.Stat(p); err == nil {
			os.Chmod(p, st.Mode()|0o111)
		}
		if mac {
			exec.Command("xattr", "-dr", "com.apple.quarantine", d).Run()
		}
		if works(p) {
			return p
		}
		if mac { // an unsigned build: sign it here (ad hoc) and try again
			entries, _ := os.ReadDir(filepath.Dir(p))
			for _, e := range entries {
				if e.Type().IsRegular() {
					exec.Command("codesign", "--force", "--sign", "-", filepath.Join(filepath.Dir(p), e.Name())).Run()
				}
			}
			if works(p) {
				return p
			}
		}
	}
	return ""
}

// missing says why a program is missing, or why the copy on the drive won't run here (such as a library Linux lacks).
func (l *launcher) missing(name, product, binary string) {
	dir := product + "-" + plat()
	exe := binary
	if windows {
		exe += ".exe"
	}
	p := findFile(filepath.Join(l.dl, "bin", dir), exe)
	if p == "" {
		say(onThis(fmt.Sprintf("  ! %s not found for %s (downloads/bin/%s). Run ./kit sync while online.", name, plat(), dir),
			fmt.Sprintf(`  - %s not found (downloads\bin\%s). Run SETUP-Windows.bat while online.`, name, dir)))
		return
	}
	out, err := runQuietly(p, "--version")
	why := ""
	for _, line := range strings.Split(out, "\n") {
		low := strings.ToLower(line)
		if strings.Contains(low, "error") || strings.Contains(low, "not found") || strings.Contains(low, "cannot") {
			why = line
			if i := strings.Index(why, binary+": "); i >= 0 {
				why = why[i+len(binary)+2:]
			}
			break
		}
	}
	if why == "" {
		code := 0
		if e, ok := err.(*exec.ExitError); ok {
			code = e.ExitCode()
		}
		why = fmt.Sprintf("it stops with code %d", code)
	}
	say(fmt.Sprintf("  ! %s won't start on this computer: %s", name, why))
}

// pickModel: a model has to fit in memory with room for everything else. On a computer with less memory than the
// first model needs, or without that model, start with the biggest one that fits (./kit fit picks the same way);
// the Ask page still lists them all.
func (l *launcher) pickModel(model string, models []string, chosen bool) string {
	if len(models) == 0 {
		return model
	}
	memMB := 0
	if v := os.Getenv("KIT_MEMORY_MB"); v != "" {
		memMB, _ = strconv.Atoi(v)
	} else {
		memMB = memoryMB()
	}
	room := memMB * 6 / 10
	have := false
	for _, m := range models {
		have = have || m == model
	}
	size := func(m string) int { return modelMB(filepath.Join(l.dl, "models", m)) }
	if have && (chosen || room == 0 || size(model) <= room) {
		return model
	}
	fit, fitMB, small, smallMB := "", 0, "", -1
	for _, m := range models {
		mb := size(m)
		if mb <= 0 {
			continue
		}
		if (room == 0 || mb <= room) && mb > fitMB {
			fit, fitMB = m, mb
		}
		if smallMB < 0 || mb < smallMB {
			small, smallMB = m, mb
		}
	}
	if fit == "" {
		fit = small
	}
	if fit == "" {
		fit = models[0]
	}
	if fit != model && have {
		say(fmt.Sprintf("  This computer has %d GB of memory, too little for %s. Starting with %s.", memMB/1024, model, fit))
	}
	return fit
}

// modelMB is the size of a model's files in MB (1,048,576 bytes, as memory is counted).
func modelMB(dir string) int {
	var total int64
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".gguf") && !strings.HasPrefix(e.Name(), ".") {
			if info, err := e.Info(); err == nil {
				total += info.Size()
			}
		}
	}
	return int(total / 1048576)
}

// modelFolders are the folders in models/ with a model in them.
func modelFolders(dir string) []string {
	var out []string
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if e.IsDir() && !strings.HasPrefix(e.Name(), ".") && len(filesWithSuffix(filepath.Join(dir, e.Name()), ".gguf")) > 0 {
			out = append(out, e.Name())
		}
	}
	return out
}

// filesWithSuffix lists the files in dir ending in suffix, by name, without hidden ones (like macOS's ._name).
func filesWithSuffix(dir, suffix string) []string {
	var out []string
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if !e.IsDir() && strings.HasSuffix(e.Name(), suffix) && !strings.HasPrefix(e.Name(), ".") {
			out = append(out, filepath.Join(dir, e.Name()))
		}
	}
	return out
}

// newest is the last file in dir named prefix*suffix: sync keeps one copy.
func newest(dir, prefix, suffix string) string {
	var names []string
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if !e.IsDir() && strings.HasPrefix(e.Name(), prefix) && strings.HasSuffix(e.Name(), suffix) {
			names = append(names, e.Name())
		}
	}
	if len(names) == 0 {
		return ""
	}
	sort.Strings(names)
	return filepath.Join(dir, names[len(names)-1])
}

// findFile is the first file called name in dir or below it.
func findFile(dir, name string) string {
	found := ""
	filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err == nil && found == "" && !d.IsDir() && d.Name() == name {
			found = p
			return filepath.SkipAll
		}
		return nil
	})
	return found
}

// runQuietly runs a program for its output, giving up after a minute.
func runQuietly(prog string, args ...string) (string, error) {
	cmd := exec.Command(prog, args...)
	var out strings.Builder
	cmd.Stdout, cmd.Stderr = &out, &out
	if err := cmd.Start(); err != nil {
		return err.Error(), err
	}
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		return out.String(), err
	case <-time.After(time.Minute):
		cmd.Process.Kill()
		return out.String(), fmt.Errorf("timed out")
	}
}

func works(p string) bool {
	if _, err := runQuietly(p, "--version"); err == nil {
		return true
	}
	_, err := runQuietly(p, "version")
	return err == nil
}

func helpSays(prog, text string) bool {
	out, _ := runQuietly(prog, "--help")
	return strings.Contains(out, text)
}

// Windows takes about 2 seconds to give up on a free port on this computer; a server here answers in
// milliseconds.
var dialTimeout = func() time.Duration {
	if windows {
		return 500 * time.Millisecond
	}
	return 2 * time.Second
}()

// taken says whether anything is listening on this port, ours or not.
func taken(port int) bool { return listening("127.0.0.1", port) }

func listening(host string, port int) bool {
	c, err := net.DialTimeout("tcp", net.JoinHostPort(host, strconv.Itoa(port)), dialTimeout)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

// freePort: another program can hold a port (Jupyter takes 8888, many developer tools 8080): use the next free one.
func freePort(start int) int {
	p := start
	for taken(p) && p < start+9 {
		p++
	}
	return p
}

var local = &http.Client{Timeout: 2 * time.Second, Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true}}

func fetch(port int, path string) (string, int, bool) { return fetchAt("127.0.0.1", port, path) }

func fetchAt(host string, port int, path string) (string, int, bool) {
	if !listening(host, port) {
		return "", 0, false
	}
	resp, err := local.Get("http://" + net.JoinHostPort(host, strconv.Itoa(port)) + path)
	if err != nil {
		return "", 0, false
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	return string(data), resp.StatusCode, true
}

func ourLibrary(port int) bool { return ourLibraryAt("127.0.0.1", port) }
func ourLibraryAt(host string, port int) bool {
	b, _, ok := fetchAt(host, port, "/")
	return ok && strings.Contains(b, "Tinfoil Kit")
}
func ourAI(port int) bool {
	b, _, ok := fetch(port, "/v1/models")
	return ok && strings.Contains(b, `"data"`)
}
func ourGate(port int) bool { return ourLibrary(port) }
func up(port int, path string) bool {
	_, status, ok := fetch(port, path)
	return ok && status < 400
}

// forward listens on 127.0.0.1:port and passes each connection to the library at host (::1), on the same port, until
// the library stops.
func forward(port int, host string, lib *proc) error {
	ln, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return err
	}
	go func() {
		<-lib.done
		ln.Close()
	}()
	go func() {
		for {
			c, err := ln.Accept()
			if errors.Is(err, net.ErrClosed) {
				return
			}
			if err != nil {
				time.Sleep(100 * time.Millisecond)
				continue
			}
			go pipeTo(c, net.JoinHostPort(host, strconv.Itoa(port)))
		}
	}()
	return nil
}

// pipeTo passes a connection's bytes to addr and back, until both sides are done.
func pipeTo(client net.Conn, addr string) {
	defer client.Close()
	server, err := net.DialTimeout("tcp", addr, 5*time.Second)
	if err != nil {
		return
	}
	defer server.Close()
	done := make(chan struct{})
	go func() {
		io.Copy(server, client)
		closeWrite(server)
		close(done)
	}()
	io.Copy(client, server)
	closeWrite(client)
	<-done
}

func closeWrite(c net.Conn) {
	if tc, ok := c.(*net.TCPConn); ok {
		tc.CloseWrite()
	}
}
