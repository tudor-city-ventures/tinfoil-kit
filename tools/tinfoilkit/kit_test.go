package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func fingerprint(g qrGrid) string {
	var b strings.Builder
	for _, row := range g {
		for _, v := range row {
			if v {
				b.WriteByte('1')
			} else {
				b.WriteByte('0')
			}
		}
	}
	sum := sha256.Sum256([]byte(b.String()))
	return hex.EncodeToString(sum[:])[:16]
}

// The same codes tests/share_test.py pins: checked against Project Nayuki's QR Code generator and read back with
// the jsQR decoder. A change that alters them needs that check again.
func TestQRCode(t *testing.T) {
	known := map[string]struct {
		size int
		fp   string
	}{
		"http://192.168.1.20:8000/?code=48217736":         {29, "3b09359ec7d0cf46"},
		"http://my-home-server.local:8000/?code=99887766": {33, "9be85ad5baee3e22"},
		strings.Repeat("x", 150):                          {49, "1336208e16162851"},
	}
	for text, want := range known {
		g, err := qrCode(text, -1)
		if err != nil || len(g) != want.size || fingerprint(g) != want.fp {
			t.Errorf("QR code for %d characters: %d modules, %s, %v", len(text), len(g), fingerprint(g), err)
		}
	}
	if _, err := qrCode(strings.Repeat("x", 3000), -1); err == nil {
		t.Error("a text too long for a QR code should say so")
	}
	g, _ := qrCode("http://10.0.0.5:8000/?code=12345678", -1)
	if svg := qrSVG(g); !strings.HasPrefix(svg, "<svg") || strings.Count(svg, "h1v1h-1z") != dark(g) {
		t.Error("QR code as SVG")
	}
	if text := qrText(g); !strings.Contains(text, "\033[30;47m") || len(strings.Split(text, "\n")) != (len(g)+4+1)/2 {
		t.Error("QR code for a terminal: black on white, two rows to a line")
	}
}

func dark(g qrGrid) int {
	n := 0
	for _, row := range g {
		for _, v := range row {
			if v {
				n++
			}
		}
	}
	return n
}

// QR_FINGERPRINTS (text<TAB>size<TAB>fingerprint lines, from share.py) checks many more codes against share.py.
func TestQRCodeMatchesShare(t *testing.T) {
	file := os.Getenv("QR_FINGERPRINTS")
	if file == "" {
		t.Skip("set QR_FINGERPRINTS")
	}
	data, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	n := 0
	for _, line := range strings.Split(strings.TrimSpace(string(data)), "\n") {
		f := strings.Split(line, "\t")
		g, err := qrCode(f[0], -1)
		if err != nil || fingerprint(g) != f[2] {
			t.Errorf("%q: %s, share.py %s", f[0], fingerprint(g), f[2])
		}
		n++
	}
	t.Logf("%d codes match", n)
}

func TestAccessCodes(t *testing.T) {
	if prettyCode("48217736") != "4821 7736" || prettyCode("abc123") != "abc123" || prettyCode("") != "" {
		t.Error("access codes: digits read in fours")
	}
	if cleanCode(" 4821-7736 ") != "48217736" {
		t.Error("access codes: spaces and dashes don't matter")
	}
	if !validCode("abc123") || validCode("12345") || validCode("1234567!") {
		t.Error("access codes: 6 to 64 letters or digits")
	}
	for _, ip := range []string{"192.168.1.5", "10.2.3.4", "172.20.0.9", "127.0.0.1", "100.101.1.2", "::ffff:192.168.1.5"} {
		if !onHomeNetwork(ip) {
			t.Errorf("%s is on a home network", ip)
		}
	}
	for _, ip := range []string{"8.8.8.8", "172.32.0.1", "1.1.1.1", "nonsense", "::1", ""} {
		if onHomeNetwork(ip) {
			t.Errorf("%s isn't on a home network", ip)
		}
	}
	kit := t.TempDir()
	a, err := loadAccess(kit, true)
	if err != nil || len(a.Code) != 8 || len(a.Key) != 64 {
		t.Fatalf("a new access code: %v %v", a, err)
	}
	b, _ := loadAccess(kit, true)
	data, _ := os.ReadFile(filepath.Join(kit, "data", ".kit", "share.json"))
	if b != a || !strings.HasPrefix(string(data), `{"code": "`) {
		t.Errorf("the access code is kept in data/.kit, as share.py writes it: %s", data)
	}
	old := t.TempDir() // a kit from before the three folders keeps .kit at its top
	os.MkdirAll(filepath.Join(old, ".kit"), 0o755)
	if accessFile(old) != filepath.Join(old, ".kit", "share.json") {
		t.Errorf("an older kit's access code: %s", accessFile(old))
	}
}

func TestLayout(t *testing.T) {
	top := t.TempDir()
	kit := filepath.Join(top, "TinfoilKit")
	os.MkdirAll(filepath.Join(kit, "app", "tools"), 0o755)
	os.MkdirAll(filepath.Join(kit, "downloads"), 0o755)
	os.MkdirAll(filepath.Join(kit, "data"), 0o755)
	os.WriteFile(filepath.Join(kit, "app", "kit.json"), []byte("{}"), 0o644)
	l := kitLayout(kit)
	if l.app != filepath.Join(kit, "app") || l.dl != filepath.Join(kit, "downloads") || l.data != filepath.Join(kit, "data") ||
		l.conf != filepath.Join(kit, "app", "kit.json") {
		t.Errorf("a kit's folders: %+v", l)
	}
	os.WriteFile(filepath.Join(kit, "data", "kit.json"), []byte("{}"), 0o644)
	if l = kitLayout(kit); l.conf != filepath.Join(kit, "data", "kit.json") {
		t.Errorf("the person's kit.json: %s", l.conf)
	}
	if kitOf(filepath.Join(kit, "app")) != kit || kitOf(filepath.Join(kit, "App")) != kit || kitOf(kit) != kit {
		t.Error("an app folder's kit is its parent")
	}
	checkout := filepath.Join(top, "app") // a git checkout called app is its own kit folder
	os.MkdirAll(filepath.Join(checkout, ".git"), 0o755)
	if kitOf(checkout) != checkout {
		t.Error("a git checkout is its own kit folder")
	}
	old := filepath.Join(top, "old") // from before the three folders
	os.MkdirAll(filepath.Join(old, "bin"), 0o755)
	os.MkdirAll(filepath.Join(old, "tools"), 0o755)
	if l = kitLayout(old); l.app != old || l.dl != old || l.data != old {
		t.Errorf("an older kit: %+v", l)
	}
}

// The access code page is share.py's, word for word, while both are in the kit.
func TestLoginPageMatchesShare(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "share.py"))
	if err != nil {
		t.Skip("no share.py")
	}
	s := string(src)
	i := strings.Index(s, `LOGIN = """`)
	if i < 0 {
		t.Fatal("share.py has no LOGIN")
	}
	s = s[i+len(`LOGIN = """`):]
	if s = s[:strings.Index(s, `"""`)]; s != loginHTML {
		t.Error("gate.go's loginHTML differs from share.py's LOGIN: copy it over")
	}
}

func TestNames(t *testing.T) {
	for _, h := range []string{"192.168.1.20:8000", "homeserver.local:8000", "homeserver:8000", "localhost:8000", "kit.lan",
		"[::1]:8000", "box.home.arpa", "KIT.LOCAL.", ""} {
		if !localHost(h) {
			t.Errorf("%q names this computer on a home network", h)
		}
	}
	for _, h := range []string{"evil.example.com:8000", "kit.example.com", "local.evil.com"} {
		if localHost(h) {
			t.Errorf("%q is a name a website elsewhere could point here", h)
		}
	}
	for _, p := range []string{"/tools", "/tools/", "//%74ools/", "/v1/../tools", "/cors-proxy?url=http://x/", "/./tools", "/%74ools/%zz/.."} {
		if !aiOff(p) {
			t.Errorf("%s is llama-server's tools or proxy", p)
		}
	}
	for _, p := range []string{"/v1/models", "/props", "/toolsx", "/v1/tools"} {
		if aiOff(p) {
			t.Errorf("%s isn't llama-server's tools or proxy", p)
		}
	}
	got := parseQuery("code=4821+7736&model=Tiny&empty&a%20b=c%2Fd")
	want := [][2]string{{"code", "4821 7736"}, {"model", "Tiny"}, {"empty", ""}, {"a b", "c/d"}}
	if len(got) != len(want) {
		t.Fatalf("parseQuery: %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("parseQuery: %v", got)
		}
	}
	if htmlEscape(`didn't <b>"&`) != "didn&#x27;t &lt;b&gt;&quot;&amp;" {
		t.Error("escaped as Python's html.escape")
	}
}

func TestSettings(t *testing.T) {
	conf := filepath.Join(t.TempDir(), "kit.json")
	os.WriteFile(conf, []byte("{\r\n  \"settings\": {\r\n    \"default_model\": \"Inkling-2-Mini\",\r\n"+
		"    \"library_port\": 8899,\r\n    \"share_on_network\": true\r\n  },\r\n  \"maps\": {\"tiles_port\": 9090}\r\n}\r\n"), 0o644)
	for key, want := range map[string]string{"default_model": "Inkling-2-Mini", "library_port": "8899", "share_on_network": "true",
		"tiles_port": "9090", "ai_port": "8080"} {
		if got := setting(conf, key, "8080"); got != want {
			t.Errorf("%s: %q, want %q", key, got, want)
		}
	}
}

func TestPickModel(t *testing.T) {
	dl := t.TempDir()
	for name, gb := range map[string]int64{"Big": 18, "Mid": 12, "Small": 5} {
		dir := filepath.Join(dl, "models", name)
		os.MkdirAll(dir, 0o755)
		f, _ := os.Create(filepath.Join(dir, name+"-Q4_K_M.gguf"))
		f.Truncate(gb * 1e9) // sparse, so it takes no space
		f.Close()
	}
	os.MkdirAll(filepath.Join(dl, "models", "Empty"), 0o755)
	l := &launcher{layout: layout{dl: dl}}
	models := modelFolders(filepath.Join(dl, "models"))
	if strings.Join(models, " ") != "Big Mid Small" {
		t.Fatalf("models: %v", models)
	}
	for _, c := range []struct {
		mem    string
		model  string
		chosen bool
		want   string
	}{{"32768", "Big", false, "Big"}, {"24576", "Big", false, "Mid"}, {"16384", "Big", false, "Small"},
		{"4096", "Big", false, "Small"}, {"16384", "Big", true, "Big"}, {"24576", "Gone", false, "Mid"},
		{"0", "Gone", false, "Big"}, {"0", "", false, "Big"}} {
		t.Setenv("KIT_MEMORY_MB", c.mem)
		if got := l.pickModel(c.model, models, c.chosen); got != c.want {
			t.Errorf("%s MB, %s (chosen %v): %s, want %s", c.mem, c.model, c.chosen, got, c.want)
		}
	}
}

// The library's go-between: 127.0.0.1 passed on to where the library listens (::1 in the kit; 127.0.0.2 here, which
// every computer the tests run on has), every byte both ways, until the library stops.
func TestForward(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.2:0")
	if err != nil {
		t.Skip("no 127.0.0.2 here")
	}
	page := "<title>Tinfoil Kit</title>" + strings.Repeat("x", 200000)
	go http.Serve(ln, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		io.WriteString(w, page+string(body))
	}))
	port := ln.Addr().(*net.TCPAddr).Port
	lib := &proc{done: make(chan struct{})}
	if err := forward(port, "127.0.0.2", lib); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		resp, err := http.Post(fmt.Sprintf("http://127.0.0.1:%d/", port), "text/plain", strings.NewReader("sent"))
		if err != nil {
			t.Fatal(err)
		}
		got, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if string(got) != page+"sent" {
			t.Fatalf("through the go-between: %d bytes", len(got))
		}
	}
	if !ourLibrary(port) {
		t.Error("the library answers at 127.0.0.1")
	}
	close(lib.done)
	time.Sleep(200 * time.Millisecond)
	if taken(port) {
		t.Error("the go-between stops with the library")
	}
}

// A Mac program and the same one signed again (as the Mac app's signing does) compare the same apart from the
// signature; a change anywhere before the signature doesn't.
func TestCompareSigned(t *testing.T) {
	le := binary.LittleEndian
	program := func(sig []byte, code byte) []byte {
		b := make([]byte, 4096)
		le.PutUint32(b, 0xfeedfacf)
		le.PutUint32(b[16:], 2)      // two load commands
		le.PutUint32(b[32:], 0x19)   // LC_SEGMENT_64
		le.PutUint32(b[36:], 72)     // its size
		copy(b[40:], "__LINKEDIT")   // its name
		le.PutUint64(b[64:], 0x4000) // vmsize
		le.PutUint64(b[72:], 2048)   // fileoff
		le.PutUint64(b[80:], uint64(2048+len(sig)))
		le.PutUint32(b[104:], 0x1d) // LC_CODE_SIGNATURE
		le.PutUint32(b[108:], 16)   // its size
		le.PutUint32(b[112:], 4096) // where the signature starts
		le.PutUint32(b[116:], uint32(len(sig)))
		b[3000] = code
		return append(b, sig...)
	}
	built := program(bytes.Repeat([]byte{1}, 100), 7)
	resigned := program(bytes.Repeat([]byte{2}, 900), 7)
	le.PutUint64(resigned[64:], 0x8000)
	if !sameUnsigned(built, resigned) {
		t.Error("signed again: the same apart from the signature")
	}
	if sameUnsigned(built, program(bytes.Repeat([]byte{1}, 100), 8)) {
		t.Error("a changed byte before the signature is a different program")
	}
	if sameUnsigned([]byte("MZ not a Mac program"), []byte("MZ not a Mac program")) {
		t.Error("only Mac programs have a signature to set aside")
	}
}

// /dev/null is a device, but nobody types at it: the kit mustn't wait for an answer from it.
func TestNullIsNoTerminal(t *testing.T) {
	f, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if isTerminal(f) {
		t.Error("isTerminal says /dev/null is a terminal")
	}
}
