package main

// Opening the kit (./kit open): start the library server (kiwix-serve), the AI server (llama-server) and the map
// servers on 127.0.0.1, keep the page's notes and pins (in this program), share them on the home network if asked,
// then open the kit's page in the browser. Closing the window, Ctrl-C or the Mac app's Quit stops them all. The Mac
// app reads what it prints: its "Open:" line says the page is up.

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
	"regexp"
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
	model                            string
}

// openKit is ./kit open: ROOT is the kit folder, or empty for the one this program is in.
func openKit(root string, a *cliArgs) int {
	o := openOptions{share: a.flag("share"), noBrowser: a.flag("no_browser"), noMaps: a.flag("no_maps"),
		model: a.str("model"), chosen: a.has("model")}
	l := &launcher{layout: kitLayout(root)}
	return l.open(o)
}

// onThis picks what to say on a Mac or Linux, and on Windows.
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
	zims := servedZims(filesWithSuffix(filepath.Join(l.dl, "library"), ".zim"))
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
		// AI chat is llama-server's own page, so it gets Ask's safety rules as its default system message. An
		// environment variable, not a flag: a llama-server too old to know it ignores it instead of refusing to start.
		var env []string
		if chat := filepath.Join(l.app, "tools", "ai-chat.json"); isFile(chat) {
			env = append(env, "LLAMA_ARG_UI_CONFIG_FILE="+chat)
		}
		aiProc = l.start(l.logFile("llama-server.log", false), l.kit, env, llama, aiServer(l.kit, l.dl,
			filepath.Join(l.data, ".kit", "presets.ini"), models, model, ctxSize, aiPort, cors)...)
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
		if n, err := startNotes(l.data, w, dataPort, libPort, l.kit, sharePort); err == nil {
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

	// --- sharing on the home network: the gate asks for the access code, then passes requests on. The kit page on
	// this computer can turn it on and off while the kit runs, through the notes server.
	ports := map[string]int{"library": libPort, "ai": aiPort, "data": dataPort}
	if withMaps {
		ports["tiles"], ports["geocoder"], ports["routing"] = tilesPort, geoPort, routePort
	}
	wanted := sharePort
	sh := &sharer{kit: l.kit, port: wanted, open: func() (*gate, error) {
		p := wanted
		if taken(p) {
			p = freePort(p)
			if windows {
				say(fmt.Sprintf("  Another program is using port %d, so sharing uses %d.", wanted, p),
					`  For an address that stays the same, set share_port in data\kit.json to a free port.`)
			} else {
				say(fmt.Sprintf("  Another program is using port %d, so sharing uses %d. For an address that stays the same, set", wanted, p),
					"  share_port in kit.json to a free port.")
			}
		}
		if windows {
			say("  Starting sharing on the home network...")
		}
		g, err := startGate(l.kit, filepath.Join(l.data, "logs", "share.log"), p, ports)
		if err == nil && windows {
			exe, _ := os.Executable()
			say(fmt.Sprintf("  If Windows asks whether %s may use the network, allow it, or phones and laptops can't reach the kit.", filepath.Base(exe)))
		}
		return g, err
	}}
	sh.told = func(on bool, port int) { // when the kit page or ./kit share turns it on or off
		if on {
			say("", "  Sharing is on now.", banner(l.kit, port, isTerminal(os.Stdout)), "")
		} else {
			say("", "  Sharing is off now: only this computer can open the kit.", "")
		}
	}
	if notes != nil {
		notes.sharing.Store(sh)
	}
	shareOK, gateFailed := false, false
	if o.share {
		if ourGate(sharePort) {
			say(fmt.Sprintf("  Sharing already on, on port %d.", sharePort))
			shareOK = true
		} else if g, _, err := sh.start(); err != nil {
			gateFailed = true
		} else {
			sharePort, shareOK = g.port, true
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
	if len(running) == 0 && sh.running() == 0 && notes == nil {
		say("  (Nothing was started by this window.)")
		if !windows { // a window Windows opened for this closes when it ends: leave it for the person to read
			l.stop()
		}
	}
	if sh.running() != 0 || notes != nil || windows {
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
	size := func(m string) int { return int(modelBytes(filepath.Join(l.dl, "models", m)) / 1048576) } // MB, as memory is counted
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

// modelBytes is the size of what a model loads.
func modelBytes(dir string) int64 {
	weights, mmproj := modelFiles(dir)
	total := fileSize(mmproj)
	for _, f := range weights {
		total += fileSize(f)
	}
	return total
}

// modelFolders are the folders in models/ with a model in them. Not one with # ; [ or ] in its name, which the AI
// server's list of models (aiServer) can't hold.
func modelFolders(dir string) []string {
	var out []string
	entries, _ := os.ReadDir(dir)
	for _, e := range entries {
		if e.IsDir() && !strings.HasPrefix(e.Name(), ".") && !strings.ContainsAny(e.Name(), "#;[]") {
			if weights, _ := modelFiles(filepath.Join(dir, e.Name())); len(weights) > 0 {
				out = append(out, e.Name())
			}
		}
	}
	return out
}

// modelFiles are what the AI server loads from a model's folder: the weights (every part, the first one first, if
// they come in parts; else the biggest file) and the vision projector, if there is one. Never a speculative decoding
// draft beside them (mtp-, dspark- or dflash-): llama-server takes one by itself when it scans a folder, and with
// Gemma 4's draft and its projector it aborts as the model loads (ggml-org/llama.cpp#30698). So the kit names each
// model's files for it instead (aiServer). A name with # or ; in it doesn't count: the list can't hold one.
func modelFiles(dir string) (weights []string, mmproj string) {
	single, size := "", int64(-1)
	for _, f := range filesWithSuffix(dir, ".gguf") {
		name := strings.ToLower(filepath.Base(f))
		switch {
		case strings.ContainsAny(name, "#;"):
		case strings.Contains(name, "mmproj"):
			mmproj = f
		case strings.HasPrefix(name, "mtp-") || strings.HasPrefix(name, "dspark-") || strings.HasPrefix(name, "dflash-"):
		case modelPart.MatchString(name):
			weights = append(weights, f)
		case fileSize(f) > size:
			single, size = f, fileSize(f)
		}
	}
	if len(weights) == 0 && single != "" {
		weights = []string{single}
	}
	return weights, mmproj
}

var modelPart = regexp.MustCompile(`-\d{5}-of-\d{5}\.gguf$`)

// aiServer writes the AI server's list of models to preset, one section for each model folder with the files it
// loads (modelFiles), first loading as the server starts, and returns the arguments that start llama-server on it:
// as a router, one model at a time, with ctx tokens of context, on 127.0.0.1 at port, answering only the page at
// origin. ./kit open and ./kit test both start it this way, from the kit folder: the list's paths start there, since
// it can't hold a # or ; and a drive's name might have one.
func aiServer(kit, dl, preset string, models []string, first, ctx string, port int, origin string) []string {
	var b strings.Builder
	b.WriteString("version = 1\n")
	rel := func(p string) string {
		if r, err := filepath.Rel(kit, p); err == nil {
			return r
		}
		return p
	}
	for _, m := range models {
		weights, mmproj := modelFiles(filepath.Join(dl, "models", m))
		if len(weights) == 0 {
			continue
		}
		fmt.Fprintf(&b, "\n[%s]\nmodel = %s\n", m, rel(weights[0]))
		if mmproj != "" {
			fmt.Fprintf(&b, "mmproj = %s\n", rel(mmproj))
		}
		if m == first {
			b.WriteString("load-on-startup = true\n")
		}
	}
	os.WriteFile(preset, []byte(b.String()), 0o644)
	return []string{"--models-preset", preset, "--models-max", "1", "-c", ctx, "--host", "127.0.0.1",
		"--port", strconv.Itoa(port), "--cors-origins", origin}
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
