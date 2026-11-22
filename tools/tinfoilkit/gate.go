package main

// Sharing the kit with the phones and laptops on a home network. The kit's servers only ever listen on 127.0.0.1.
// With sharing on, this gate listens on the network instead: it asks for the access code, then hands each request
// to a server by its path (/ai, /tiles, /geocoder and /routing; everything else is the library and the kit page).

import (
	"bufio"
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
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
	"syscall"
	"time"
	"unicode"
)

// ----------------------------------------------------------------------------- the access code and the address

type access struct {
	Code string `json:"code"`
	Key  string `json:"key"`
}

// shareData is the folder with the kit's records (.kit), as tools/share.py finds it: the top of a kit from before the
// three folders, which keeps .kit there, else its data folder.
func shareData(kit string) string {
	if isDir(filepath.Join(kit, ".kit")) {
		return kit
	}
	return filepath.Join(kit, "data")
}

func accessFile(kit string) string { return filepath.Join(shareData(kit), ".kit", "share.json") }

func saveAccess(kit string, a access) error {
	p := accessFile(kit)
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	tmp := strings.TrimSuffix(p, ".json") + ".tmp"
	data := fmt.Sprintf("{\"code\": %s, \"key\": %s}\n", jsonString(a.Code), jsonString(a.Key))
	if err := os.WriteFile(tmp, []byte(data), 0o600); err != nil {
		return err
	}
	_ = os.Chmod(tmp, 0o600) // exFAT keeps no permissions
	return os.Rename(tmp, p)
}

// loadAccess gives the access code, and the key that signs the cookie a device gets once it has typed the code.
// They live in data/.kit/, never kit.json: people share kit.json files.
func loadAccess(kit string, create bool) (access, error) {
	var a access
	if data, err := os.ReadFile(accessFile(kit)); err == nil && json.Unmarshal(data, &a) == nil && a.Code != "" && a.Key != "" {
		return a, nil
	}
	if !create {
		return access{}, nil
	}
	a = access{Code: newCode(), Key: randomHex(32)}
	return a, saveAccess(kit, a)
}

func newCode() string {
	var b strings.Builder
	for i := 0; i < 8; i++ {
		n, _ := rand.Int(rand.Reader, big.NewInt(10))
		b.WriteString(n.String())
	}
	return b.String()
}

func randomHex(n int) string {
	b := make([]byte, n)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

func cleanCode(s string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) || r == '-' {
			return -1
		}
		return r
	}, s)
}

var codePattern = regexp.MustCompile(`^[A-Za-z0-9]{6,64}$`)

func validCode(s string) bool { return codePattern.MatchString(cleanCode(s)) }

// prettyCode reads 8 digits as two groups: 4821 7736.
func prettyCode(code string) string {
	for _, r := range code {
		if r < '0' || r > '9' {
			return code
		}
	}
	var parts []string
	for i := 0; i < len(code); i += 4 {
		parts = append(parts, code[i:min(i+4, len(code))])
	}
	return strings.Join(parts, " ")
}

var homeNetworks = func() []*net.IPNet {
	var nets []*net.IPNet
	for _, s := range []string{
		"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", // home networks
		"127.0.0.0/8", "169.254.0.0/16", // this computer, and networks with no router
		"100.64.0.0/10", // carrier-grade NAT and Tailscale
	} {
		_, n, _ := net.ParseCIDR(s)
		nets = append(nets, n)
	}
	return nets
}()

func onHomeNetwork(s string) bool {
	ip := net.ParseIP(strings.SplitN(s, "%", 2)[0])
	if ip == nil || ip.To4() == nil {
		return false
	}
	for _, n := range homeNetworks {
		if n.Contains(ip.To4()) {
			return true
		}
	}
	return false
}

// Names only a home network hands out. A website elsewhere can't point one of these at this computer.
var localSuffixes = []string{".local", ".lan", ".home", ".internal", ".localdomain", ".home.arpa", ".fritz.box", ".ts.net"}

// localHost says whether a Host header names this computer the way a home network does: an address, a bare name
// like homeserver, or a name like homeserver.local. A web page elsewhere can point a name it owns at this computer
// and reach the gate as its own site (DNS rebinding), so other names are turned away.
func localHost(host string) bool {
	name := strings.ToLower(strings.TrimSpace(host))
	if strings.HasPrefix(name, "[") {
		name = strings.SplitN(name[1:], "]", 2)[0]
	} else if i := strings.LastIndex(name, ":"); i >= 0 {
		name = name[:i]
	}
	name = strings.TrimRight(name, ".")
	if net.ParseIP(name) != nil || !strings.Contains(name, ".") {
		return true
	}
	for _, s := range localSuffixes {
		if strings.HasSuffix(name, s) {
			return true
		}
	}
	return false
}

// lanIPs lists this computer's IPv4 addresses on its network, the likeliest first. KIT_LAN_IP picks one by hand.
// Nothing here sends anything or looks up a name: on a Mac, either would ask to "find devices on local networks".
func lanIPs() []string {
	if v := os.Getenv("KIT_LAN_IP"); v != "" {
		return []string{v}
	}
	var found []string
	add := func(ip string) {
		ip = strings.TrimSpace(ip)
		for _, f := range found {
			if f == ip {
				return
			}
		}
		if ip != "" && onHomeNetwork(ip) && !strings.HasPrefix(ip, "127.") && !strings.HasPrefix(ip, "169.254.") {
			found = append(found, ip)
		}
	}
	addInterface := func(ifc net.Interface) {
		if ifc.Flags&net.FlagUp == 0 || ifc.Flags&net.FlagLoopback != 0 {
			return
		}
		addrs, _ := ifc.Addrs()
		for _, a := range addrs {
			if n, ok := a.(*net.IPNet); ok && n.IP.To4() != nil {
				add(n.IP.String())
			}
		}
	}
	ifaces, _ := net.Interfaces()
	if mac {
		// The network the default route goes through first: the routing table says, with nothing sent.
		out, _ := exec.Command("route", "-n", "get", "default").Output()
		if m := regexp.MustCompile(`(?m)^\s*interface:\s*(\S+)`).FindSubmatch(out); m != nil {
			for _, ifc := range ifaces {
				if ifc.Name == string(m[1]) {
					addInterface(ifc)
				}
			}
		}
	} else {
		// Which address a route to the router would use: connecting a UDP socket sends nothing, and works offline.
		for _, probe := range []string{"192.168.0.1:9", "10.0.0.1:9", "172.16.0.1:9"} {
			if c, err := net.Dial("udp4", probe); err == nil {
				if a, ok := c.LocalAddr().(*net.UDPAddr); ok {
					add(a.IP.String())
				}
				c.Close()
			}
		}
	}
	for _, ifc := range ifaces {
		addInterface(ifc)
	}
	return found
}

// localName is name.local, when other devices can find this computer by name (Bonjour on a Mac, Avahi on Linux).
// Phones can't find a Windows PC by name.
func localName() string {
	name := ""
	switch {
	case windows:
		return ""
	case mac:
		out, _ := exec.Command("scutil", "--get", "LocalHostName").Output()
		name = strings.TrimSpace(string(out))
	default:
		if _, err := os.Stat("/run/avahi-daemon/pid"); err == nil {
			h, _ := os.Hostname()
			name = strings.SplitN(h, ".", 2)[0]
		}
	}
	if regexp.MustCompile(`^[A-Za-z0-9-]+$`).MatchString(name) {
		return name + ".local"
	}
	return ""
}

// joinURL is the link in the QR code: it opens the kit and lets the device in.
func joinURL(host, code string) string { return "http://" + host + "/?code=" + url.QueryEscape(code) }

// gatePort is the port the gate answers on: share_port, or the next free one the launcher took because another
// program had it. 0 when the kit isn't shared right now.
func gatePort(port int) int {
	client := &http.Client{Timeout: time.Second, Transport: &http.Transport{Proxy: nil, DisableKeepAlives: true}}
	for p := port; p < port+10; p++ {
		resp, err := client.Head(fmt.Sprintf("http://127.0.0.1:%d/", p))
		if err == nil {
			resp.Body.Close()
			if resp.Header.Get("Server") == "TinfoilKit" {
				return p
			}
		}
	}
	return 0
}

func banner(kit string, port int, qr bool) string {
	a, _ := loadAccess(kit, true)
	ips := lanIPs()
	if len(ips) == 0 {
		return fmt.Sprintf("  Sharing is on (access code %s), but this computer isn't on a home network.\n"+
			"  Connect it to your Wi-Fi or router (no internet needed), then run %s to see its\n  address.",
			prettyCode(a.Code), kitCmd("share"))
	}
	lines := []string{
		fmt.Sprintf("  On your home network: open http://%s:%d on a phone or laptop", ips[0], port),
		"  Access code: " + prettyCode(a.Code),
	}
	if name := localName(); name != "" {
		lines = append(lines, fmt.Sprintf("  Laptops can also use http://%s:%d", name, port))
	}
	if qr && colorsOn() {
		if g, err := qrCode(joinURL(fmt.Sprintf("%s:%d", ips[0], port), a.Code), -1); err == nil {
			lines = append(lines, "  Or scan this with a phone's camera:", "", qrText(g), "")
		}
	}
	return strings.Join(lines, "\n")
}

func runBanner(args []string) int {
	fs := newFlags("banner")
	root := fs.String("root", "", "the kit folder")
	port := fs.Int("port", 8000, "share_port")
	qr := fs.Bool("qr", false, "draw the QR code even when not printing to a terminal")
	if fs.Parse(args) != nil {
		return 2
	}
	kit := kitLayout(*root).kit
	p := gatePort(*port)
	if p == 0 {
		p = *port
	}
	say(banner(kit, p, *qr || isTerminal(os.Stdout)))
	return 0
}

// ----------------------------------------------------------------------------- the gate

const (
	cookieName  = "tinfoilkit"
	maxBody     = 64 * 1000 * 1000 // a photo for the AI goes up as base64
	tries       = 10               // wrong codes allowed from one address in triesWindow
	triesWindow = 10 * time.Minute
	textPlain   = "text/plain; charset=utf-8"
)

var routes = []string{"ai", "tiles", "geocoder", "routing"}

// llama-server's own chat page may ask for its API at the root; the library has nothing at these paths.
var aiPaths = []string{"/v1/", "/props", "/models", "/slots", "/health", "/completion", "/tokenize", "/detokenize",
	"/apply-template", "/infill", "/embedding", "/rerank", "/lora-adapters", "/metrics"}

// llama-server features that run things on this computer (tools, a web proxy). The kit leaves them off; if someone
// turns them on for themselves, they still stay off for the network. Same answer llama-server gives when they're off.
var aiOffPaths = map[string]bool{"/tools": true, "/cors-proxy": true}

const aiOffAnswer = `{"error": {"message": "this feature is disabled", "type": "feature_disabled"}}`

var dropRequest = words("connection keep-alive proxy-authorization proxy-connection te trailer transfer-encoding " +
	"upgrade host cookie authorization origin referer content-length expect")
var dropResponse = words("connection keep-alive transfer-encoding server date trailer upgrade")
var serverNames = map[string]string{"library": "The library", "ai": "The AI", "tiles": "The map",
	"geocoder": "Address search", "routing": "Directions"}

func words(s string) map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(s) {
		m[w] = true
	}
	return m
}

type verdict int

const (
	refused verdict = iota
	allowed
	tooMany
)

type gate struct {
	kit   string
	port  int
	ports map[string]int
	ln    net.Listener

	mu       sync.Mutex
	failures map[string][]time.Time
	accSeen  bool
	accMtime time.Time
	code     string
	cookie   string
}

func newGate(kit string, port int, ports map[string]int) (*gate, error) {
	if _, err := loadAccess(kit, true); err != nil {
		return nil, err
	}
	// Every interface, IPv4 only. Go looks up no names here (a Mac would ask about local network devices).
	ln, err := net.Listen("tcp4", fmt.Sprintf("0.0.0.0:%d", port))
	if err != nil {
		return nil, err
	}
	return &gate{kit: kit, port: ln.Addr().(*net.TCPAddr).Port, ports: ports, ln: ln, failures: map[string][]time.Time{}}, nil
}

func (g *gate) serve(errs io.Writer) error {
	srv := &http.Server{Handler: g, ErrorLog: log.New(errs, "", log.LstdFlags), ReadHeaderTimeout: time.Minute}
	return srv.Serve(g.ln)
}

// access gives the access code and the cookie that proves it, read again whenever ./kit share changes the code.
func (g *gate) access() (string, string) {
	var mtime time.Time
	if st, err := os.Stat(accessFile(g.kit)); err == nil {
		mtime = st.ModTime()
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	if !g.accSeen || !mtime.Equal(g.accMtime) {
		a, _ := loadAccess(g.kit, true)
		key, err := hex.DecodeString(a.Key)
		if err != nil {
			key = []byte(a.Key)
		}
		m := hmac.New(sha256.New, key)
		m.Write([]byte(a.Code))
		g.code, g.cookie, g.accMtime, g.accSeen = a.Code, hex.EncodeToString(m.Sum(nil)), mtime, true
	}
	return g.code, g.cookie
}

func (g *gate) tooMany(ip string) bool {
	now := time.Now()
	g.mu.Lock()
	defer g.mu.Unlock()
	var recent []time.Time
	for _, t := range g.failures[ip] {
		if now.Sub(t) < triesWindow {
			recent = append(recent, t)
		}
	}
	g.failures[ip] = recent
	return len(recent) >= tries
}

func (g *gate) failed(ip string) {
	now := time.Now()
	g.mu.Lock()
	defer g.mu.Unlock()
	for k, v := range g.failures {
		if len(v) == 0 || now.Sub(v[len(v)-1]) >= triesWindow {
			delete(g.failures, k)
		}
	}
	g.failures[ip] = append(g.failures[ip], now)
}

func (g *gate) codeOK(ip, given, code string) verdict {
	if g.tooMany(ip) {
		return tooMany
	}
	if subtle.ConstantTimeCompare([]byte(cleanCode(given)), []byte(code)) == 1 {
		return allowed
	}
	g.failed(ip)
	return refused
}

func (g *gate) signedIn(r *http.Request, ip, code, cookie string) verdict {
	for _, line := range r.Header.Values("Cookie") {
		for _, part := range strings.Split(line, ";") {
			k, v, _ := strings.Cut(strings.TrimSpace(part), "=")
			if k == cookieName && subtle.ConstantTimeCompare([]byte(v), []byte(cookie)) == 1 {
				return allowed
			}
		}
	}
	if auth := r.Header.Get("Authorization"); len(auth) >= 7 && strings.EqualFold(auth[:7], "bearer ") {
		return g.codeOK(ip, auth[7:], code) // for programs: the access code as the API key
	}
	return refused
}

func (g *gate) send(w http.ResponseWriter, r *http.Request, status int, ctype, body string, close bool, extra ...string) {
	h := w.Header()
	h.Set("Content-Type", ctype)
	h.Set("Content-Length", strconv.Itoa(len(body)))
	h.Set("Cache-Control", "no-store")
	for i := 0; i+1 < len(extra); i += 2 {
		h.Add(extra[i], extra[i+1])
	}
	if close {
		h.Set("Connection", "close")
	}
	w.WriteHeader(status)
	if r.Method != "HEAD" {
		io.WriteString(w, body)
	}
}

func (g *gate) redirect(w http.ResponseWriter, r *http.Request, where, cookie string) {
	extra := []string{"Location", where}
	if cookie != "" {
		extra = append(extra, "Set-Cookie", cookieName+"="+cookie+"; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
	}
	g.send(w, r, http.StatusSeeOther, textPlain, "", false, extra...)
}

func (g *gate) loginPage(w http.ResponseWriter, r *http.Request, status int, next, problem string) {
	e := ""
	if problem != "" {
		e = `<p class="err" role="alert">` + htmlEscape(problem) + `</p>`
	}
	body := strings.Replace(loginHTML, "@@ERROR@@", e, 1)
	body = strings.Replace(body, "@@NEXT@@", htmlEscape(next), 1)
	g.send(w, r, status, "text/html; charset=utf-8", body, false)
}

// publicHost is the address other devices can reach the kit at: the one this device used, unless that was this
// computer.
func (g *gate) publicHost(r *http.Request) string {
	host := r.Host
	name := host
	if i := strings.LastIndex(name, ":"); i >= 0 {
		name = name[:i]
	}
	name = strings.Trim(name, "[]")
	if name == "" || name == "localhost" || name == "::1" || strings.HasPrefix(name, "127.") {
		if ips := lanIPs(); len(ips) > 0 {
			return fmt.Sprintf("%s:%d", ips[0], g.port)
		}
	}
	return host
}

func (g *gate) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Server", "TinfoilKit")
	ip, _, _ := net.SplitHostPort(r.RemoteAddr)
	if !onHomeNetwork(ip) {
		g.send(w, r, 403, textPlain, "Tinfoil Kit only answers devices on its home network.\n", true)
		return
	}
	if !localHost(r.Host) {
		where := ""
		if ips := lanIPs(); len(ips) > 0 {
			where = fmt.Sprintf(" Open http://%s:%d instead.", ips[0], g.port)
		}
		g.send(w, r, 403, textPlain, "Tinfoil Kit doesn't answer to that name."+where+"\n", true)
		return
	}
	target := r.RequestURI // as sent: the servers behind decode it themselves
	if !strings.HasPrefix(target, "/") {
		target = r.URL.RequestURI()
	}
	upath, query, _ := strings.Cut(strings.SplitN(target, "#", 2)[0], "?")
	code, cookie := g.access()

	if upath == "/_kit/login" && r.Method == "POST" {
		body, err := readBody(w, r)
		if err != nil {
			g.send(w, r, 413, textPlain, "Too big.\n", true)
			return
		}
		form, _ := url.ParseQuery(string(body[:min(len(body), 4096)]))
		next := form.Get("next")
		if !strings.HasPrefix(next, "/") || strings.HasPrefix(next, "//") || strings.Contains(next, `\`) {
			next = "/"
		}
		switch g.codeOK(ip, form.Get("code"), code) {
		case allowed:
			g.redirect(w, r, next, cookie)
		case tooMany:
			g.loginPage(w, r, 429, next, "Too many tries. Wait a few minutes, then try again.")
		default:
			g.loginPage(w, r, 401, next, "That code didn't work. Check it and try again.")
		}
		return
	}

	// The QR code's link: let the device in, then tidy the address.
	var given []string
	var rest []string
	for _, kv := range parseQuery(query) {
		if kv[0] == "code" {
			given = append(given, kv[1])
		} else {
			rest = append(rest, url.QueryEscape(kv[0])+"="+url.QueryEscape(kv[1]))
		}
	}
	if len(given) > 0 && (r.Method == "GET" || r.Method == "HEAD") {
		where := upath
		if len(rest) > 0 {
			where += "?" + strings.Join(rest, "&")
		}
		switch g.codeOK(ip, given[0], code) {
		case allowed:
			g.redirect(w, r, where, cookie)
		case tooMany:
			g.loginPage(w, r, 429, where, "Too many tries. Wait a few minutes, then try again.")
		default:
			g.loginPage(w, r, 401, where, "That link's access code is out of date. Ask for the new one.")
		}
		return
	}

	switch g.signedIn(r, ip, code, cookie) {
	case tooMany:
		g.send(w, r, 429, "application/json", `{"error": "too many wrong access codes, wait a few minutes"}`, false)
		return
	case refused:
		if r.Method == "GET" && (upath == "/" || strings.Contains(r.Header.Get("Accept"), "text/html")) {
			g.loginPage(w, r, 401, target, "")
		} else {
			g.send(w, r, 401, "application/json", `{"error": "this needs the kit's access code"}`, false)
		}
		return
	}
	if upath == "/_kit/qr.svg" {
		if q, err := qrCode(joinURL(g.publicHost(r), code), -1); err == nil {
			g.send(w, r, 200, "image/svg+xml", qrSVG(q), false)
			return
		}
	}
	if upath == "/ai" {
		g.redirect(w, r, "/ai/", "")
		return
	}
	name, to := "library", target
	routed := false
	for _, rt := range routes {
		if strings.HasPrefix(upath, "/"+rt+"/") {
			name, to, routed = rt, target[len(rt)+1:], true
			break
		}
	}
	if !routed {
		for _, p := range aiPaths {
			if strings.HasPrefix(upath, p) {
				name = "ai"
				break
			}
		}
	}
	if name == "ai" && aiOff(to) {
		g.send(w, r, 403, "application/json", aiOffAnswer, false)
		return
	}
	g.proxy(w, r, name, to, name == "library" && upath == "/" && r.Method == "GET", code)
}

func readBody(w http.ResponseWriter, r *http.Request) ([]byte, error) {
	return io.ReadAll(http.MaxBytesReader(w, r.Body, maxBody))
}

// idleConn gives up on a server that says nothing for 15 minutes; a model can think for minutes.
type idleConn struct{ net.Conn }

func (c idleConn) Read(b []byte) (int, error) {
	_ = c.SetReadDeadline(time.Now().Add(15 * time.Minute))
	return c.Conn.Read(b)
}

func (g *gate) proxy(w http.ResponseWriter, r *http.Request, name, to string, inject bool, code string) {
	port, what := g.ports[name], serverNames[name]
	body, err := readBody(w, r)
	if err != nil {
		g.send(w, r, 413, textPlain, "Too big.\n", true)
		return
	}
	if port == 0 {
		g.send(w, r, 502, textPlain, what+" isn't part of this kit.\n", false)
		return
	}
	notRunning := func() {
		g.send(w, r, 502, textPlain, what+" isn't running yet. It can take a minute to start: try again soon.\n", false)
	}
	conn, err := net.DialTimeout("tcp", fmt.Sprintf("127.0.0.1:%d", port), 10*time.Second)
	if err != nil {
		notRunning()
		return
	}
	defer conn.Close()
	var req bytes.Buffer
	fmt.Fprintf(&req, "%s %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n", r.Method, to, port)
	keys := make([]string, 0, len(r.Header))
	for k := range r.Header {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		low := strings.ToLower(k)
		if dropRequest[low] || (inject && (low == "accept-encoding" || low == "if-none-match" || low == "if-modified-since")) {
			continue
		}
		for _, v := range r.Header[k] {
			fmt.Fprintf(&req, "%s: %s\r\n", k, v)
		}
	}
	if r.ContentLength != 0 || len(r.TransferEncoding) > 0 {
		fmt.Fprintf(&req, "Content-Length: %d\r\n", len(body))
	}
	req.WriteString("\r\n")
	req.Write(body)
	_ = conn.SetWriteDeadline(time.Now().Add(15 * time.Minute))
	if _, err := conn.Write(req.Bytes()); err != nil {
		notRunning()
		return
	}
	br := bufio.NewReader(idleConn{conn})
	resp, err := http.ReadResponse(br, &http.Request{Method: r.Method})
	for err == nil && resp.StatusCode >= 100 && resp.StatusCode < 200 && resp.StatusCode != 101 {
		resp, err = http.ReadResponse(br, &http.Request{Method: r.Method})
	}
	if err != nil {
		notRunning()
		return
	}
	defer resp.Body.Close()
	g.relay(w, r, resp, inject, code)
}

func (g *gate) relay(w http.ResponseWriter, r *http.Request, resp *http.Response, inject bool, code string) {
	h := w.Header()
	h["Content-Type"] = nil // only the server's own: no guessing
	for k, vs := range resp.Header {
		low := strings.ToLower(k)
		if dropResponse[low] || strings.HasPrefix(low, "access-control-") {
			continue
		}
		for _, v := range vs {
			h.Add(k, v)
		}
	}
	if inject && resp.StatusCode == 200 && strings.Contains(resp.Header.Get("Content-Type"), "text/html") {
		// The kit page: tell it that it came through the gate, so it asks the gate for the AI and the map.
		info := fmt.Sprintf(`{"address": %s, "code": %s}`, jsonString("http://"+g.publicHost(r)), jsonString(prettyCode(code)))
		tag := []byte("<script>window.KIT_GATE = " + strings.ReplaceAll(info, "</", `<\/`) + ";</script>")
		data, err := io.ReadAll(resp.Body)
		if err != nil {
			return
		}
		if i := bytes.Index(data, []byte("<head>")); i >= 0 {
			data = append(data[:i+6:i+6], append(tag, data[i+6:]...)...)
		} else {
			data = append(tag, data...)
		}
		for _, k := range []string{"Content-Length", "Etag", "Last-Modified", "Cache-Control"} {
			h.Del(k)
		}
		h.Set("Content-Length", strconv.Itoa(len(data)))
		h.Set("Cache-Control", "no-store")
		w.WriteHeader(resp.StatusCode)
		w.Write(data)
		return
	}
	empty := r.Method == "HEAD" || resp.StatusCode == 204 || resp.StatusCode == 304 || resp.StatusCode < 200
	stream := !empty && resp.Header.Get("Content-Length") == "" // an answer the AI writes as it goes
	w.WriteHeader(resp.StatusCode)
	if empty {
		return
	}
	flusher, _ := w.(http.Flusher)
	buf := make([]byte, 65536)
	for {
		n, err := resp.Body.Read(buf)
		if n > 0 {
			if _, werr := w.Write(buf[:n]); werr != nil {
				return
			}
			if stream && flusher != nil {
				flusher.Flush()
			}
		}
		if err != nil {
			return
		}
	}
}

// aiOff says whether a path is one of aiOffPaths, however it's spelled: llama-server decodes %74ools as /tools.
func aiOff(p string) bool {
	p = strings.SplitN(strings.SplitN(p, "?", 2)[0], "#", 2)[0]
	p = regexp.MustCompile(`/+`).ReplaceAllString("/"+percentDecode(p), "/")
	return aiOffPaths[path.Clean(p)]
}

// percentDecode decodes each %XX it can and leaves the rest, as Python's unquote does.
func percentDecode(s string) string {
	unhex := func(c byte) int {
		switch {
		case c >= '0' && c <= '9':
			return int(c - '0')
		case c >= 'a' && c <= 'f':
			return int(c-'a') + 10
		case c >= 'A' && c <= 'F':
			return int(c-'A') + 10
		}
		return -1
	}
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '%' && i+2 < len(s) && unhex(s[i+1]) >= 0 && unhex(s[i+2]) >= 0 {
			b.WriteByte(byte(unhex(s[i+1])<<4 | unhex(s[i+2])))
			i += 2
			continue
		}
		b.WriteByte(s[i])
	}
	return b.String()
}

// parseQuery splits a query into its pairs, in order, blank values kept.
func parseQuery(q string) [][2]string {
	var out [][2]string
	for _, part := range strings.Split(q, "&") {
		if part == "" {
			continue
		}
		k, v, _ := strings.Cut(part, "=")
		k = percentDecode(strings.ReplaceAll(k, "+", " "))
		v = percentDecode(strings.ReplaceAll(v, "+", " "))
		out = append(out, [2]string{k, v})
	}
	return out
}

func jsonString(s string) string {
	b, _ := json.Marshal(s)
	return string(b)
}

// htmlEscape escapes as Python's html.escape does.
func htmlEscape(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&#x27;").Replace(s)
}

// startGate starts the gate on port, in this program, logging to logPath.
func startGate(kit, logPath string, port int, ports map[string]int) (*gate, error) {
	logf, _ := os.Create(logPath)
	var out io.Writer = io.Discard
	if logf != nil {
		out = logf
	}
	g, err := newGate(kit, port, ports)
	if err != nil {
		fmt.Fprintf(out, "Can't share on port %d: %s\n", port, errText(err))
		if logf != nil {
			logf.Close()
		}
		return nil, err
	}
	fmt.Fprintf(out, "Sharing on port %d: %s\n", g.port, describePorts(ports))
	stayAwake()
	go g.serve(out)
	return g, nil
}

func describePorts(ports map[string]int) string {
	var parts []string
	for _, k := range append([]string{"library"}, routes...) {
		if ports[k] != 0 {
			parts = append(parts, fmt.Sprintf("%s %d", k, ports[k]))
		}
	}
	return strings.Join(parts, ", ")
}

// errText is what went wrong, without Go's wrapping: "Address already in use".
func errText(err error) string {
	var errno syscall.Errno
	s := err.Error()
	if errors.As(err, &errno) {
		s = errno.Error()
	}
	if s != "" {
		s = strings.ToUpper(s[:1]) + s[1:]
	}
	return s
}

func runGate(args []string) int {
	fs := newFlags("gate")
	root := fs.String("root", "", "the kit folder")
	port := fs.Int("port", 8000, "the port to share on")
	ports := map[string]*int{"library": fs.Int("library", 8888, "the library's port")}
	for _, r := range routes {
		ports[r] = fs.Int(r, 0, "the "+r+" server's port")
	}
	if fs.Parse(args) != nil {
		return 2
	}
	kit := kitLayout(*root).kit
	want := map[string]int{}
	for k, v := range ports {
		if *v != 0 {
			want[k] = *v
		}
	}
	g, err := newGate(kit, *port, want)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Can't share on port %d: %s\n", *port, errText(err))
		return 1
	}
	fmt.Printf("Sharing on port %d: %s\n", g.port, describePorts(want))
	stayAwake()
	if err := g.serve(os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}

const loginHTML = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Tinfoil Kit</title><link rel="icon" href="data:,">
<style>
/* the website's look, like the kit's own page: paper, ink and signal orange */
:root { --bg:#f3f0e6; --panel:#eae6d8; --ink:#1c1f1a; --ink2:#3a3e36; --olive:#4a5a2a; --signal:#d9531e; --bad:#9a3a10;
  --line:#1c1f1a; --btn-line:#1c1f1a; color-scheme:light dark;
  --sans:"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
@media (prefers-color-scheme: dark) { :root { --bg:#1c1f1a; --panel:#262a23; --ink:#f3f0e6; --ink2:#cfcbbe; --olive:#a9b87a;
  --signal:#e4672f; --bad:#e0884f; --line:#cfcbbe; --btn-line:#e4672f; } }
* { box-sizing:border-box; }
body { margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; background:var(--bg); color:var(--ink);
  font:16px/1.5 var(--sans); -webkit-font-smoothing:antialiased; }
main { width:100%; max-width:26rem; border:2px solid var(--line); }
h1 { margin:0; padding:12px 20px; border-bottom:2px solid var(--line); background:var(--panel);
  font:600 16px var(--mono); letter-spacing:.04em; text-transform:uppercase; }
form { padding:20px; }
p { margin:0 0 18px; color:var(--ink2); }
label { display:block; margin-bottom:6px; font:600 13px var(--mono); letter-spacing:.06em; text-transform:uppercase;
  color:var(--olive); }
input { width:100%; min-height:52px; padding:0 14px; font:500 22px var(--mono); letter-spacing:.12em; color:var(--ink);
  background:var(--bg); border:2px solid var(--line); border-radius:4px; }
button { width:100%; min-height:52px; margin-top:14px; font:600 17px var(--sans); color:#1c1f1a; background:#e4672f;
  border:2px solid var(--btn-line); border-radius:4px; cursor:pointer; }
button:hover { background:#ea7038; }
:focus-visible { outline:3px solid var(--signal); outline-offset:2px; }
.err { color:var(--bad); font-weight:600; }
</style></head>
<body><main>
<h1>Tinfoil Kit</h1>
<form method="post" action="/_kit/login">
<p>This kit is shared on your home network. Enter the access code shown on the computer it runs on.</p>
@@ERROR@@
<label for="code">Access code</label>
<input id="code" name="code" inputmode="numeric" autocomplete="off" autocapitalize="off" spellcheck="false" required autofocus>
<input type="hidden" name="next" value="@@NEXT@@">
<button type="submit">Open the kit</button>
</form>
</main></body></html>
`
