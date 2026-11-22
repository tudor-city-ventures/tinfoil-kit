package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto/ed25519"
	"crypto/md5"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"io/fs"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
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

// Codes checked against Project Nayuki's QR Code generator (the same modules for every mask, and the same mask
// chosen) and read back with the jsQR decoder. A change that alters them needs that check again.
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
		t.Errorf("the access code is kept in data/.kit, as the kit always has: %s", data)
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

// The AI server's list of models names each model's weights and vision projector, from the kit folder, and never the
// speculative decoding draft beside them: left to scan the folder, llama-server took Gemma 4's, and aborted.
func TestAIServer(t *testing.T) {
	kit := t.TempDir()
	dl := filepath.Join(kit, "downloads")
	in := func(name string) string { return filepath.Join("downloads", "models", filepath.FromSlash(name)) }
	for name, size := range map[string]int64{
		"Gemma-4-E4B/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf": 5e9, "Gemma-4-E4B/mmproj-F16.gguf": 9e8,
		"Gemma-4-E4B/mtp-gemma-4-E4B-it.gguf": 3e8, "Gemma-4-E4B/._gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf": 4096,
		"Big/Big-Q4_K_M-00002-of-00002.gguf": 9e9, "Big/Big-Q4_K_M-00001-of-00002.gguf": 9e9,
		"Own #1/own.gguf": 1e9, "Drafts/dflash-x.gguf": 1e8,
	} {
		os.MkdirAll(filepath.Join(kit, filepath.Dir(in(name))), 0o755)
		f, _ := os.Create(filepath.Join(kit, in(name)))
		f.Truncate(size) // sparse, so it takes no space
		f.Close()
	}
	models := modelFolders(filepath.Join(dl, "models"))
	if strings.Join(models, " ") != "Big Gemma-4-E4B" {
		t.Fatalf("models: %v", models)
	}
	preset := filepath.Join(kit, "data", "presets.ini")
	os.MkdirAll(filepath.Dir(preset), 0o755)
	args := strings.Join(aiServer(kit, dl, preset, models, "Gemma-4-E4B", "4096", 8080, "http://127.0.0.1:8888"), " ")
	got, _ := os.ReadFile(preset)
	want := "version = 1\n\n[Big]\nmodel = " + in("Big/Big-Q4_K_M-00001-of-00002.gguf") + "\n\n[Gemma-4-E4B]\nmodel = " +
		in("Gemma-4-E4B/gemma-4-E4B-it-qat-UD-Q4_K_XL.gguf") + "\nmmproj = " + in("Gemma-4-E4B/mmproj-F16.gguf") +
		"\nload-on-startup = true\n"
	if string(got) != want {
		t.Errorf("presets.ini:\n%s\nwant:\n%s", got, want)
	}
	if args != "--models-preset "+preset+" --models-max 1 -c 4096 --host 127.0.0.1 --port 8080 --cors-origins http://127.0.0.1:8888" {
		t.Errorf("args: %s", args)
	}
	if n := modelBytes(filepath.Join(dl, "models", "Gemma-4-E4B")); n != 5e9+9e8 {
		t.Errorf("Gemma-4-E4B loads %d bytes", n)
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

// sshSign signs data the way ssh-keygen -Y sign does, with key, saying it's claim's key (its own when claim is nil).
func sshSign(key ed25519.PrivateKey, data []byte, namespace string, claim []byte) []byte {
	str := func(parts ...[]byte) []byte {
		var b []byte
		for _, p := range parts {
			b = append(binary.BigEndian.AppendUint32(b, uint32(len(p))), p...)
		}
		return b
	}
	if claim == nil {
		claim = key.Public().(ed25519.PublicKey)
	}
	digest := sha512.Sum512(data)
	sig := ed25519.Sign(key, append([]byte("SSHSIG"), str([]byte(namespace), nil, []byte("sha512"), digest[:])...))
	blob := append([]byte("SSHSIG\x00\x00\x00\x01"), str(str([]byte("ssh-ed25519"), claim), []byte(namespace), nil,
		[]byte("sha512"), str([]byte("ssh-ed25519"), sig))...)
	b64 := base64.StdEncoding.EncodeToString(blob)
	lines := []string{"-----BEGIN SSH SIGNATURE-----"}
	for len(b64) > 70 {
		lines, b64 = append(lines, b64[:70]), b64[70:]
	}
	return []byte(strings.Join(append(lines, b64, "-----END SSH SIGNATURE-----", ""), "\n"))
}

// A release installs only if a key in the kit's tools/release-signers signed it, for the kit's namespace.
func TestReleaseSignature(t *testing.T) {
	kit := t.TempDir()
	os.MkdirAll(filepath.Join(kit, "app", "tools"), 0o755)
	key := ed25519.NewKeyFromSeed(bytes.Repeat([]byte("k"), 32))
	other := ed25519.NewKeyFromSeed(bytes.Repeat([]byte("o"), 32))
	pub := key.Public().(ed25519.PublicKey)
	blob := binary.BigEndian.AppendUint32(nil, 11)
	blob = binary.BigEndian.AppendUint32(append(blob, "ssh-ed25519"...), 32)
	line := `tinfoilkit-release namespaces="tinfoilkit-release" ssh-ed25519 ` + base64.StdEncoding.EncodeToString(append(blob, pub...)) + " test\n"
	os.WriteFile(filepath.Join(kit, "app", "tools", "release-signers"), []byte("# comment\n"+line), 0o644)
	if keys := releaseKeys(filepath.Join(kit, "app", "tools", "release-signers")); len(keys) != 1 || !bytes.Equal(keys[0], pub) {
		t.Fatalf("release-signers: %x", keys)
	}
	good := sshSign(key, []byte("release"), releaseNamespace, nil)
	if err := verifyRelease(kit, []byte("release"), good); err != nil {
		t.Fatal("the kit's key: ", err)
	}
	for what, c := range map[string]struct {
		data, sig []byte
		says      string
	}{
		"another file":              {[]byte("release!"), good, "isn't signed with the kit's release key"},
		"another key":               {[]byte("release"), sshSign(other, []byte("release"), releaseNamespace, nil), "isn't signed"},
		"another key, as the kit's": {[]byte("release"), sshSign(other, []byte("release"), releaseNamespace, pub), "isn't signed"},
		"another namespace":         {[]byte("release"), sshSign(key, []byte("release"), "file", nil), "isn't signed"},
		"a damaged signature":       {[]byte("release"), good[:len(good)-60], "damaged"},
		"no signature":              {[]byte("release"), nil, "damaged"},
	} {
		if err := verifyRelease(kit, c.data, c.sig); err == nil || !strings.Contains(err.Error(), c.says) {
			t.Errorf("%s: %v", what, err)
		}
	}
}

// Photon's address database, as pbzip2 and lbzip2 make it: a tar in two bzip2 streams.
const twoStreamTar = "QlpoOTFBWSZTWRxOUlMAACtfiNiAQAH9AABAAAD2Yd5AAAIICCAAVDKQHqAAB6NR6g01BqaNNDQAaBrAMCR4USfAqhAOMjFzSgcQgwYgnO56yMxarUHGc2sRzvj5Ova0JbYvvTQZGcgO5JO0CB+LuSKcKEgOJykpgEJaaDkxQVkmU1m6NhsrAABT34LJkEAB9YAAAIAA9GHeQAIACAggAHUMih6mgAADTagkomg0A0DQaB9Kv1kyS3nSEQlB5C19IIYDCMcXCcwRq1DdYZLZs0ydpoOuOXj7GlUzk6u1snh8QHqJJYgBCH4u5IpwoSF0bDZW"

func makeZip(t *testing.T, path string, files map[string]struct {
	mode fs.FileMode
	data string
}) {
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	z := zip.NewWriter(f)
	for name, m := range files {
		h := &zip.FileHeader{Name: name, Method: zip.Deflate}
		h.SetMode(m.mode)
		w, _ := z.CreateHeader(h)
		w.Write([]byte(m.data))
	}
	z.Close()
	f.Close()
}

// The kit unpacks every archive itself: programs stay runnable, links become copies (exFAT can't hold links), and
// nothing lands outside the folder.
func TestUnpack(t *testing.T) {
	ex := t.TempDir()
	type file = struct {
		mode fs.FileMode
		data string
	}
	makeZip(t, filepath.Join(ex, "a.zip"), map[string]file{"prog-1/bin/prog.exe": {0o644, "MZ"}, "prog-1/bin/tool": {0o755, "#!"}})
	if err := unzipTo(filepath.Join(ex, "a.zip"), filepath.Join(ex, "z")); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(filepath.Join(ex, "z/prog-1/bin/prog.exe")); string(b) != "MZ" {
		t.Error("unzip: files land in place")
	}
	if st, err := os.Stat(filepath.Join(ex, "z/prog-1/bin/tool")); !windows && (err != nil || st.Mode()&0o111 == 0) {
		t.Error("unzip: programs stay runnable")
	}
	tb, _ := base64.StdEncoding.DecodeString(twoStreamTar)
	os.WriteFile(filepath.Join(ex, "db.tar.bz2"), tb, 0o644)
	if err := untarTo(filepath.Join(ex, "db.tar.bz2"), filepath.Join(ex, "t"), "bz2"); err != nil {
		t.Fatal(err)
	}
	if st, err := os.Stat(filepath.Join(ex, "t/photon_data/node_1/a.bin")); err != nil || st.Size() != 5000 {
		t.Error("untar: a bzip2 database in two streams unpacks whole")
	}
	if b, _ := os.ReadFile(filepath.Join(ex, "t/photon_data/b.txt")); string(b) != "hi" {
		t.Error("untar: the second stream's file is there")
	}
	for _, bad := range []string{"../escape.txt", "/abs.txt", "C:/win.txt", "ok/../../escape.txt"} {
		makeZip(t, filepath.Join(ex, "bad.zip"), map[string]file{bad: {0o644, "no"}})
		if err := unzipTo(filepath.Join(ex, "bad.zip"), filepath.Join(ex, "bad")); err == nil || exists(filepath.Join(filepath.Dir(ex), "escape.txt")) {
			t.Errorf("unzip: a path outside the folder, %s, is refused", bad)
		}
	}
	// A Mac's or Linux PC's programs come with links: set up from Windows onto a drive, they're copies.
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for _, m := range []struct {
		name string
		kind byte
		link string
	}{{"lib/libfoo.dylib", tar.TypeSymlink, "libfoo.1.dylib"}, {"lib/libfoo.1.dylib", tar.TypeSymlink, "libfoo.1.2.dylib"},
		{"lib/libfoo.1.2.dylib", tar.TypeReg, ""}, {"lib/hard.dylib", tar.TypeLink, "lib/libfoo.1.2.dylib"},
		{"legal", tar.TypeSymlink, "lib"}, {"out", tar.TypeSymlink, "../../outside.txt"}, {"abs", tar.TypeSymlink, "/etc/passwd"},
		{"loop", tar.TypeSymlink, "."}} {
		h := &tar.Header{Name: m.name, Typeflag: m.kind, Linkname: m.link, Mode: 0o644}
		if m.kind == tar.TypeReg {
			h.Size = 3
		}
		tw.WriteHeader(h)
		if m.kind == tar.TypeReg {
			tw.Write([]byte("lib"))
		}
	}
	tw.Close()
	gz.Close()
	os.WriteFile(filepath.Join(ex, "links.tar.gz"), buf.Bytes(), 0o644)
	if err := untarTo(filepath.Join(ex, "links.tar.gz"), filepath.Join(ex, "l"), "gz"); err != nil {
		t.Fatal(err)
	}
	for _, n := range []string{"lib/libfoo.dylib", "lib/libfoo.1.dylib", "lib/hard.dylib", "legal/libfoo.dylib"} {
		st, err := os.Lstat(filepath.Join(ex, "l", n))
		if b, _ := os.ReadFile(filepath.Join(ex, "l", n)); err != nil || st.Mode()&fs.ModeSymlink != 0 || string(b) != "lib" {
			t.Errorf("untar: %s is a copy", n)
		}
	}
	for _, n := range []string{"out", "abs", "loop"} {
		if _, err := os.Lstat(filepath.Join(ex, "l", n)); err == nil {
			t.Errorf("untar: %s, a link outside the archive or to itself, is left out", n)
		}
	}
	makeZip(t, filepath.Join(ex, "links.zip"), map[string]file{"bin/llama-server": {0o755, "prog"}, "bin/llama": {fs.ModeSymlink | 0o777, "llama-server"}})
	if err := unzipTo(filepath.Join(ex, "links.zip"), filepath.Join(ex, "lz")); err != nil {
		t.Fatal(err)
	}
	if st, err := os.Lstat(filepath.Join(ex, "lz/bin/llama")); err != nil || st.Mode()&fs.ModeSymlink != 0 {
		t.Error("unzip: a link becomes a copy")
	} else if b, _ := os.ReadFile(filepath.Join(ex, "lz/bin/llama")); string(b) != "prog" {
		t.Error("unzip: the copy has the file's contents")
	}
	if err := extractArchive(filepath.Join(ex, "a.zip"), "a.zip", filepath.Join(ex, "prog")); err != nil || !exists(filepath.Join(ex, "prog/prog-1/bin/prog.exe")) {
		t.Error("extractArchive: ", err)
	}
}

// Building the directions network: memory for it sized to the computer, and built again on disk if it runs out.
func TestRouting(t *testing.T) {
	m := mapsDefaults()
	for mb, want := range map[string]string{"8192": "4g", "16384": "9g", "65536": "12g", "0": "12g"} {
		t.Setenv("KIT_MEMORY_MB", mb)
		if got := importHeap(m); got != want {
			t.Errorf("%s MB: %s, not %s", mb, got, want)
		}
	}
	if m.set("routing_import_heap", "20g"); importHeap(m) != "20g" {
		t.Error("kit.json's routing_import_heap wins")
	}
	if windows {
		return
	}
	m = mapsDefaults()
	dir := t.TempDir()
	java := filepath.Join(dir, "java")
	os.WriteFile(java, []byte("#!/bin/bash\necho \"$@\" >> calls.log\n"+
		"grep -q \"default_type: RAM_STORE\" gh-import.yml && [ -n \"$OOM_ALWAYS$OOM_IN_MEMORY\" ] && exit 3\n"+
		"[ -n \"$OOM_ALWAYS\" ] && exit 3\n[ -n \"$CRASH\" ] && exit 1\n"+
		"mkdir -p graph-cache.new && echo graph > graph-cache.new/properties\n"), 0o755)
	build := func(env string) (error, []string) {
		os.Remove(filepath.Join(dir, "calls.log"))
		for _, k := range []string{"OOM_IN_MEMORY", "OOM_ALWAYS", "CRASH"} {
			t.Setenv(k, "")
		}
		if env != "" {
			t.Setenv(env, "1")
		}
		var err error
		captured(t, func() { err = buildRouting(java, filepath.Join(dir, "graphhopper-web.jar"), m, dir) })
		calls, _ := os.ReadFile(filepath.Join(dir, "calls.log"))
		return err, strings.Split(strings.TrimSpace(string(calls)), "\n")
	}
	if err, calls := build(""); err != nil || len(calls) != 1 || !strings.Contains(calls[0], "-XX:+ExitOnOutOfMemoryError") {
		t.Error("in memory the first time, stopping if Java runs out: ", err, calls)
	}
	yml, _ := os.ReadFile(filepath.Join(dir, "gh-import.yml"))
	if err, calls := build("OOM_IN_MEMORY"); err != nil || len(calls) != 2 || !strings.Contains(string(yml), "default_type: RAM_STORE") {
		t.Error("out of memory in memory: built again on disk: ", err, calls)
	}
	if yml, _ = os.ReadFile(filepath.Join(dir, "gh-import.yml")); !strings.Contains(string(yml), "default_type: MMAP") {
		t.Error("the second build keeps the graph on disk")
	}
	if err, calls := build("OOM_ALWAYS"); err == nil || !strings.Contains(err.Error(), "Close other apps") || len(calls) != 2 {
		t.Error("out of memory on disk too: says what to do: ", err, calls)
	}
	if err, calls := build("CRASH"); err == nil || !strings.Contains(err.Error(), "failed (exit 1)") || len(calls) != 1 {
		t.Error("any other failure isn't retried: ", err, calls)
	}
}

// What SETUP gets first: the programs, the map, the most important books, the AI this computer runs and the smallest,
// and whatever someone asked for by name.
func TestEssential(t *testing.T) {
	cfg, err := parseObj([]byte(`{"models": [{"id": "Runs"}, {"id": "Small"}, {"id": "Big"}, {"id": "Asked", "essential": true}],
		"library": [{"zim": "a_en", "priority": 1}, {"zim": "b_en", "priority": 2}, {"zim": "c_en", "priority": 3, "essential": true}]}`))
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]bool{"models/Runs": true, "models/Small": true, "models/Big": false, "models/Asked": true,
		"library/a_en": true, "library/b_en": false, "library/c_en": true}
	fit := newObj("runs", "Runs", "smallest", "Small")
	for _, it := range itemsFromConfig(cfg) {
		if w, ok := want[it.key()]; ok && essential(it, fit) != w {
			t.Errorf("%s: essential %v", it.key(), !w)
		}
	}
}

// Whether the kit, or just its essentials, fits on a disk and leaves 10% of the computer's (5% of a drive's) free.
// A 1000 GB disk, a kit of 300 GB and essentials of 40 GB.
func TestRoom(t *testing.T) {
	cfg := newObj("settings", newObj())
	for _, c := range []struct {
		computer  bool
		free      int64
		full, ess string
	}{{true, 500, "fits", "fits"}, {true, 380, "tight", "fits"}, {true, 320, "no", "fits"}, {true, 130, "no", "tight"},
		{true, 80, "no", "no"}, {false, 340, "tight", "fits"}, {false, 360, "fits", "fits"}} {
		keep, leave := keepFreeOn(c.computer, cfg), leaveFreeOn(c.computer, 1000*GB, cfg)
		if full, ess := room(c.free*GB, 300*GB, keep, leave), room(c.free*GB, 40*GB, keep, leave); full != c.full || ess != c.ess {
			t.Errorf("%d GB free, this computer %v: kit %s, essentials %s", c.free, c.computer, full, ess)
		}
	}
}

func TestFinderFiles(t *testing.T) {
	kit := t.TempDir()
	junk := filepath.Join(kit, ".git", "objects", "pack", "._pack-1.idx")
	os.MkdirAll(filepath.Dir(junk), 0o755)
	os.WriteFile(junk, []byte{0, 5, 22, 7}, 0o644)
	if dropFinderFiles(kit); exists(junk) {
		t.Error("macOS's ._ files go from a checkout's .git too")
	}
}

// pins.yml's commit job holds a new tools/pins.json to the note the kit writes, and to the programs it knows.
func TestPinsFile(t *testing.T) {
	data, err := os.ReadFile(filepath.Join("..", "pins.json"))
	if err != nil {
		t.Skip("no tools/pins.json")
	}
	pins, _ := parseObj(data)
	if fmt.Sprint(pins.get("_readme")) != fmt.Sprint(pinsReadme) {
		t.Error("tools/pins.json's note isn't the one ./kit pins writes")
	}
	yml, _ := os.ReadFile(filepath.Join("..", "..", ".github", "workflows", "pins.yml"))
	viewer := 0
	for _, m := range mapsItems(newObj("maps", newObj("enabled", true))) {
		if contains(pinnedTypes, pyStr(m.get("type"))) {
			if viewer++; !strings.Contains(string(yml), `"`+pyStr(m.get("id"))+`"`) {
				t.Errorf("pins.yml doesn't know %s, a map program the kit pins", m.get("id"))
			}
		}
	}
	if viewer == 0 {
		t.Error("the kit pins no map viewer program")
	}
}

// withRegions runs the test on the repo's own tools/regions.json, the places "Where do you live?" offers.
func withRegions(t *testing.T) *obj {
	saved := codeRoot
	codeRoot, regionsCache = filepath.Join("..", ".."), nil
	t.Cleanup(func() { codeRoot, regionsCache = saved, nil })
	if len(regions().objs("regions")) < 200 {
		t.Fatal("tools/regions.json lists fewer than 200 places")
	}
	return regions()
}

// captured is what f prints, and what the programs it runs do.
func captured(t *testing.T, f func()) string {
	tmp, err := os.CreateTemp(t.TempDir(), "out")
	if err != nil {
		t.Fatal(err)
	}
	stdout, stderr := os.Stdout, os.Stderr
	os.Stdout, os.Stderr = tmp, tmp
	defer func() { os.Stdout, os.Stderr = stdout, stderr }()
	f()
	data, _ := os.ReadFile(tmp.Name())
	return string(data)
}

// dies says whether f stopped the command (die), with what it printed.
func dies(t *testing.T, f func()) (died bool, said string) {
	said = captured(t, func() {
		defer func() {
			if r := recover(); r != nil {
				if _, ok := r.(exitCode); !ok {
					panic(r)
				}
				died = true
			}
		}()
		f()
	})
	return
}

// A second sync on a kit stops while one holds its lock, and goes once that lets go. (Windows' lock, LockFileEx, needs
// the file open for reading or writing: one opened to append always failed, as if another sync had it.)
func TestLockKit(t *testing.T) {
	root := t.TempDir()
	unlock := lockKit(root)
	if died, said := dies(t, func() { lockKit(root)() }); !died || !strings.Contains(said, "another ./kit sync is already running") {
		t.Errorf("a second sync didn't stop while the first held the lock: %q", said)
	}
	unlock()
	if died, said := dies(t, func() { lockKit(root)() }); died {
		t.Errorf("a sync stopped after the first let go: %q", said)
	}
}

// The code's folder is the one above the program's (app, above app/tools), or KIT_CODE's for a copy run from elsewhere.
func TestCodeRoot(t *testing.T) {
	t.Setenv("KIT_CODE", "")
	exe, _ := os.Executable()
	exe, _ = filepath.EvalSymlinks(exe)
	if got := findCodeRoot(); got != filepath.Dir(filepath.Dir(exe)) {
		t.Errorf("the code's folder is %s, not the one above the program's", got)
	}
	dir := t.TempDir()
	t.Setenv("KIT_CODE", dir)
	if got := findCodeRoot(); got != dir {
		t.Errorf("with KIT_CODE=%s the code's folder is %s", dir, got)
	}
}

func firstRegion(t *testing.T, ok func(*obj) bool) *obj {
	for _, r := range regions().objs("regions") {
		if ok(r) {
			return r
		}
	}
	t.Fatal("tools/regions.json has no such place")
	return nil
}

// Where you live: every place's road data comes from Geofabrik, and its home is inside its map.
func TestRegions(t *testing.T) {
	rs := withRegions(t)
	if f := findRegions("New York"); len(f) == 0 || f[0].str("id") != "us/new-york" {
		t.Error("findRegions: a state's name")
	}
	langs := rs.child("languages")
	for _, r := range rs.objs("regions") {
		m, err := regionMaps(r)
		var box []float64
		for _, v := range r.list("bbox") {
			f, _ := asNumber(v)
			box = append(box, f)
		}
		lon, _ := asNumber(r.child("home").get("lon"))
		lat, _ := asNumber(r.child("home").get("lat"))
		ok := err == nil && strings.HasPrefix(m.str("routing_osm_pbf"), geofabrik) && len(box) == 4 &&
			box[0] <= lon && lon <= box[2] && box[1] <= lat && lat <= box[3]
		for _, c := range r.list("langs") {
			ok = ok && langs.has(pyStr(c))
		}
		if !ok {
			t.Errorf("%s: road data from Geofabrik, home inside the map, languages Wikipedia has", r.get("id"))
		}
	}
}

// The map settings a place gives, what kit.json can still change by hand, and ./kit test after just the essentials,
// as SETUP's first run does: an address search that isn't coming, or comes later, isn't a failure.
func TestMapsSettings(t *testing.T) {
	withRegions(t)
	m := mapsSettings(newObj("maps", newObj("enabled", true, "region", "us/texas")))
	if m.str("label") != "Texas" || !strings.HasSuffix(m.str("routing_osm_pbf"), "/north-america/us/texas/texas-latest.osm.pbf") ||
		m.str("geocoder_country") != "us" || truthy(m.get("geocoder_wide")) || m.child("home").str("label") != "Houston, TX" ||
		m.str("units") != "imperial" || m.str("lang") != "en" {
		t.Error("a place's map, directions, address search and home: ", m)
	}
	m = mapsSettings(newObj("maps", newObj("enabled", true, "region", "us/texas", "detail_maxzoom", 14,
		"home", newObj("label", "Mine", "lat", 1, "lon", 2))))
	if !pyEqual(m.get("detail_maxzoom"), 14) || m.child("home").str("label") != "Mine" || !pyEqual(m.child("home").get("zoom"), 10) ||
		m.str("label") != "Texas" {
		t.Error("kit.json's own keys win: ", m)
	}
	wide := firstRegion(t, func(r *obj) bool { return truthy(r.get("addresses_wide")) })
	m = mapsSettings(newObj("maps", newObj("enabled", true, "region", wide.get("id"), "geocoder_country", "de")))
	if m.str("geocoder_country") != "de" || truthy(m.get("geocoder_wide")) {
		t.Error("an address search set by hand isn't a continent's")
	}
	if !mapsSettings(newObj("maps", newObj("region", "atlantis"))).has("region_error") {
		t.Error("a place the kit doesn't know")
	}
	bare := firstRegion(t, func(r *obj) bool { return !r.has("photon") })
	for _, i := range mapsItems(newObj("maps", newObj("enabled", true, "region", bare.get("id")))) {
		if i.str("id") == "geocoder" {
			t.Error("no address search item where nobody publishes one: ", bare.get("id"))
		}
	}
	noMap := t.TempDir()
	checks := func(place any) ([]string, string) {
		var seen []string
		var servers []*server
		said := captured(t, func() {
			testMaps(noMap, mapsSettings(newObj("maps", newObj("enabled", true, "region", place))),
				func(name string, ok bool, detail string) { seen = append(seen, name) }, &servers, noMap, false)
		})
		return seen, said
	}
	if seen, said := checks(bare.get("id")); contains(seen, "address search installed") || !strings.Contains(said, "SKIP  address search: nobody publishes one") {
		t.Error("test: no address search check where nobody publishes one: ", said)
	}
	if seen, said := checks(wide.get("id")); contains(seen, "address search installed") || !strings.Contains(said, "SKIP  address search: not here yet") {
		t.Error("test: a continent's address search, which comes after the essentials, isn't missing yet: ", said)
	}
	if seen, _ := checks("us/texas"); !contains(seen, "address search installed") {
		t.Error("test: a place's own address search must be there")
	}
	// Just the essentials leave out a continent's address search (tens of GB).
	data, err := os.ReadFile(filepath.Join("..", "..", "kit.json"))
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := parseObj(data)
	cfg.child("maps").set("region", wide.get("id"))
	for _, i := range itemsFromConfig(cfg) {
		if i.id == "geocoder" && (!truthy(i.cfg.get("wide")) || essential(i, newObj("runs", "", "smallest", ""))) {
			t.Error("a continent's address search isn't one of the essentials")
		}
	}
	root, yes := t.TempDir(), true
	without := estimateGB(root, cfg, &yes, nil, false)
	wide.set("addresses_wide", false)
	with := estimateGB(root, cfg, &yes, nil, false)
	wide.set("addresses_wide", true)
	if mb, _ := asNumber(wide.child("mb").get("addresses")); math.Abs(float64(with-without)-mb/1000) > 1 {
		t.Errorf("the essentials' estimate leaves it out: %d GB without, %d with, %v MB", without, with, mb)
	}
}

// Wikipedia's sizes: the edition nearest to the one asked for, the sizes every language comes in, what stands in for
// one that isn't in the kit yet, and which goes once the one kit.json asks for is in.
func TestWikipediaSizes(t *testing.T) {
	langs := withRegions(t).child("languages")
	saved := cloneObj(langs.child("de"))
	langs.child("de").set("sizes", newObj("top_mini", 100, "top_nopic", 1000, "all_maxi", 50000))
	var got []string
	for _, e := range []string{"top_nopic", "all_nopic", "all_maxi"} {
		got = append(got, wikiEdition("de", e))
	}
	if fmt.Sprint(got) != "[top_nopic top_nopic all_maxi]" || wikiEdition("xx", "all_maxi") != "" {
		t.Error("wikiEdition: the one asked for, else the biggest smaller one, else the smallest: ", got)
	}
	var names []string
	for _, s := range sizeChoices([]string{"de", "en"}) {
		names = append(names, s.name)
	}
	if c := sizeChoices([]string{"de"}); fmt.Sprint(names) != "[all top-text top-intros]" || len(c) < 2 ||
		c[1] != (sizeChoice{"top-text", "The best 50,000 articles, text only", 1000}) {
		t.Error("sizeChoices: only the sizes every language comes in, biggest first: ", names, c)
	}
	langs.set("de", saved)
	zims := func(zs []*obj) string {
		var out []string
		for _, z := range zs {
			out = append(out, z.str("zim"))
		}
		return strings.Join(out, ", ")
	}
	lib := func(entries ...*obj) *obj {
		l := []any{}
		for _, e := range entries {
			l = append(l, e)
		}
		return newObj("library", l)
	}
	empty := newObj("items", newObj())
	cfg := lib(newObj("zim", "wikipedia_en_all_maxi", "priority", 2, "refresh_days", 365), newObj("zim", "testmed_en_all_maxi"))
	ess := wikiStandIns(cfg, empty, "essentials")
	if s := zims(wikiStandIns(cfg, empty, "starter")); s != "wikipedia_en_top_mini" || zims(ess) != "wikipedia_en_top_nopic" ||
		!pyEqual(ess[0].get("refresh_days"), 365) {
		t.Error("wikiStandIns: the try-it kit gets the best articles' opening paragraphs, the essentials their text, with "+
			"Wikipedia's settings: ", s, "; ", zims(ess))
	}
	in := newObj("items", newObj("library/wikipedia_en_all_maxi", newObj("files", newObj())))
	if len(wikiStandIns(cfg, in, "essentials")) > 0 ||
		len(wikiStandIns(lib(newObj("zim", "wikipedia_en_all_maxi", "enabled", false)), empty, "starter")) > 0 ||
		len(wikiStandIns(lib(newObj("zim", "wikipedia_en_all_maxi", "essential", true)), empty, "essentials")) > 0 ||
		len(wikiStandIns(lib(newObj("zim", "wikipedia_en_all_maxi", "starter", true)), empty, "starter")) > 0 {
		t.Error("wikiStandIns: none once it's in the kit, switched off, or coming whole anyway")
	}
	small := lib(newObj("zim", "wikipedia_en_top_mini"))
	if s := zims(append(wikiStandIns(small, empty, "starter"), wikiStandIns(small, empty, "essentials")...)); s != "wikipedia_en_top_mini, wikipedia_en_top_mini" {
		t.Error("wikiStandIns: a Wikipedia that small comes itself: ", s)
	}

	// A Wikipedia in the old language goes once the new one is in.
	root := t.TempDir()
	old := filepath.Join(root, "downloads", "zim", "wikipedia_en_all_maxi_2026-01.zim")
	os.MkdirAll(filepath.Dir(old), 0o755)
	os.WriteFile(old, []byte("en"), 0o644)
	state := func(keys ...string) *obj {
		items := newObj()
		for _, k := range keys {
			files := newObj()
			if k == "library/wikipedia_en_all_maxi" {
				files.set("wikipedia_en_all_maxi_2026-01.zim", newObj())
			}
			items.set(k, newObj("dest", "zim", "files", files))
		}
		return newObj("items", items)
	}
	keys := func(st *obj) string { return fmt.Sprint(st.child("items").Keys()) }
	st := state("library/wikipedia_en_all_maxi", "library/testmed_en_all_maxi")
	cfg = lib(newObj("zim", "wikipedia_de_all_maxi"), newObj("zim", "testmed_en_all_maxi"))
	quiet := func(f func()) { captured(t, f) }
	quiet(func() { dropReplacedWikipedias(root, st, itemsFromConfig(cfg), cfg) })
	if !st.child("items").has("library/wikipedia_en_all_maxi") || !exists(old) {
		t.Error("Wikipedia swap: the old one stays until the new one is in")
	}
	st.child("items").set("library/wikipedia_de_all_maxi", newObj("dest", "zim", "files", newObj("wikipedia_de_all_maxi_2026-01.zim", newObj())))
	quiet(func() { dropReplacedWikipedias(root, st, itemsFromConfig(cfg), cfg) })
	if st.child("items").has("library/wikipedia_en_all_maxi") || exists(old) || !st.child("items").has("library/testmed_en_all_maxi") {
		t.Error("Wikipedia swap: then the old one goes, and nothing else: ", keys(st))
	}
	// A plan of just the essentials, with a smaller Wikipedia standing in, leaves kit.json's own alone; that one's
	// being in is what lets the smaller one go.
	st = state("library/wikipedia_en_all_maxi", "library/wikipedia_en_top_nopic")
	quiet(func() {
		dropReplacedWikipedias(root, st, itemsFromConfig(lib(newObj("zim", "wikipedia_en_top_nopic"))), lib(newObj("zim", "wikipedia_en_top_maxi")))
	})
	if keys(st) != "[library/wikipedia_en_all_maxi library/wikipedia_en_top_nopic]" {
		t.Error("Wikipedia sizes: nothing goes while kit.json's size isn't in: ", keys(st))
	}
	mine := lib(newObj("zim", "wikipedia_en_all_maxi"))
	quiet(func() { dropReplacedWikipedias(root, st, nil, mine) })
	if keys(st) != "[library/wikipedia_en_all_maxi]" {
		t.Error("Wikipedia sizes: once it's in, the one standing in for it goes, even in a plan without either: ", keys(st))
	}
	st = newObj("items", newObj("library/wikipedia_en_top_mini", newObj("dest", "zim", "files", newObj(), "sample", true)))
	quiet(func() { dropSamples(root, st, mine, itemsFromConfig(lib(newObj("zim", "wikipedia_en_top_mini")))) })
	kept := st.child("items").has("library/wikipedia_en_top_mini")
	quiet(func() { dropSamples(root, st, mine, nil) })
	if !kept || st.child("items").has("library/wikipedia_en_top_mini") {
		t.Error("dropSamples: a try-it kit's Wikipedia stays while it stands in for kit.json's, then goes")
	}
}

// Geofabrik's -latest can point at a file that isn't up yet: then the newest dated one.
func TestGeofabrikFallback(t *testing.T) {
	var asked []string
	var none bool
	web := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		asked = append(asked, r.URL.Path)
		if none || strings.HasSuffix(r.URL.Path, "-latest.osm.pbf") || len(asked) < 3 {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Length", "5")
	}))
	defer web.Close()
	url, h, err := geofabrikHead(web.URL + "/europe/romania/romania-latest.osm.pbf")
	day := time.Now().AddDate(0, 0, -2).Format("060102")
	if err != nil || url != web.URL+"/europe/romania/romania-"+day+".osm.pbf" || h["content-length"] != "5" {
		t.Error("a missing latest file falls back to the newest dated one: ", url, h, err, asked)
	}
	none = true
	if _, _, err := geofabrikHead(web.URL + "/x/y-latest.osm.pbf"); err == nil {
		t.Error("no file at all is an error")
	}
}

// Kiwix's catalog rounds sizes up to a whole KiB: given that, download takes a file a hair short of it once the
// server has nothing more (its checksum decides), whether it starts from nothing or from the whole file.
func TestDownloadRoundedSize(t *testing.T) {
	book := bytes.Repeat([]byte("zim!"), 17500) // 70,000 bytes
	web := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.ServeContent(w, r, "book.zim", time.Time{}, bytes.NewReader(book))
	}))
	defer web.Close()
	part := filepath.Join(t.TempDir(), "book.zim.partial")
	for i := 0; i < 2; i++ {
		var err error
		captured(t, func() { err = download(web.URL+"/book.zim", part, (70000+1023)/1024*1024, "curl") })
		if got, _ := os.ReadFile(part); err != nil || !bytes.Equal(got, book) {
			t.Errorf("run %d: %v", i+1, err)
		}
	}
}

// measureSpeed: about the speed a server sends at, over as many connections as sync uses, in a few seconds; 0 when it
// can't download at all.
func TestMeasureSpeed(t *testing.T) {
	saved := partMin
	defer func() { partMin = saved }()
	partMin = 64 * 1024 // so each connection asks for more than it gets in the time
	var conns atomic.Int32
	web := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/big.gguf" {
			http.NotFound(w, r)
			return
		}
		conns.Add(1)
		for range 1024 { // 8 KB a second
			if _, err := w.Write(make([]byte, 1024)); err != nil {
				return
			}
			w.(http.Flusher).Flush()
			time.Sleep(125 * time.Millisecond)
		}
	}))
	defer web.Close()
	t0 := time.Now()
	bps, took := measureSpeed(web.URL+"/big.gguf", 1<<30), time.Since(t0)
	if want := 8.0 * 1024 * connections; bps < 0.6*want || bps > 1.4*want || took > 10*time.Second || conns.Load() != connections {
		t.Errorf("%.0f bytes a second (want about %.0f) in %s, over %d connections", bps, want, took, conns.Load())
	}
	if bps := measureSpeed(web.URL+"/gone.gguf", 1<<30); bps != 0 {
		t.Errorf("a download that fails: %.0f bytes a second", bps)
	}
}

// The line a download shows as it goes: with the time left for everything after it too, when that fits.
func TestProgressLine(t *testing.T) {
	for _, c := range []struct {
		got, after int64
		rate       float64
		cols       int
		want       string
	}{
		{1.2e9, 0, 12e6, 80, "    1.2 GB of 7.1 GB, 12.0 MB/s, about 8 minutes left"},
		{1.2e9, 280e9, 12e6, 80, "    1.2 GB of 7.1 GB, 12.0 MB/s, about 8 minutes left (6.5 hours in all)"},
		{1.2e9, 280e9, 12e6, 70, "    1.2 GB of 7.1 GB, 12.0 MB/s, about 8 minutes left"},
		{1.2e9, 280e9, 12e6, 0, "    1.2 GB of 7.1 GB, 12.0 MB/s, about 8 minutes left (6.5 hours in all)"},
		{1.2e9, 280e9, 0, 80, "    1.2 GB of 7.1 GB"},
	} {
		if got := progressLine(c.got, 7.1e9, c.after, c.rate, c.cols); got != c.want {
			t.Errorf("progressLine(%d, %d, %.0f, %d) = %q, want %q", c.got, c.after, c.rate, c.cols, got, c.want)
		}
	}
	// The time left in all counts the item's own files still to come: a model's mmproj after its weights.
	weights, mmproj, mtp := &remoteFile{size: 900}, &remoteFile{estimate: 90}, &remoteFile{size: 9}
	it := &item{need: []*remoteFile{weights, mmproj, mtp}}
	if a, b, c, d := it.after(weights), it.after(mmproj), it.after(mtp), it.after(&remoteFile{size: 5}); a != 99 || b != 9 ||
		c != 0 || d != 0 {
		t.Errorf("after = %d, %d, %d, %d; want 99, 9, 0, 0", a, b, c, d)
	}
}

// What ./kit autostart writes to Windows' Startup folder and reads back. The drive test runs the real thing on Windows.
func TestAutostartWindows(t *testing.T) {
	savedWindows, savedStart := windows, startNow
	defer func() { windows, startNow = savedWindows, savedStart }()
	windows = true
	var started []string
	startNow = func(p string) error { started = append(started, p); return nil }
	tmp := t.TempDir()
	t.Setenv("APPDATA", filepath.Join(tmp, "Roaming"))
	kit, elsewhere := filepath.Join(tmp, "Tinfoil Kit 100% café"), filepath.Join(tmp, "elsewhere")
	os.MkdirAll(filepath.Join(kit, "app", "tools"), 0o755)
	var said strings.Builder
	if rc := autostart(kit, "on", &said); rc != 0 {
		t.Fatalf("./kit autostart on: %d %s", rc, said.String())
	}
	entry := startupFile()
	data, _ := os.ReadFile(entry)
	text := string(data)
	bat := strings.ReplaceAll(filepath.Join(kit, "app", "Open Tinfoil Kit for Windows.bat"), "%", "%%")
	if !strings.Contains(text, `if exist "`+bat+`" start "Tinfoil Kit" /min "`+bat+`" --no-browser`+"\r\n") {
		t.Errorf("the Startup entry starts Open Tinfoil Kit for Windows.bat, minimized, with no browser:\n%s", text)
	}
	if strings.Count(text, "\n") != strings.Count(text, "\r\n") || !strings.Contains(text, "chcp 65001") ||
		!strings.Contains(text, "café") || !strings.Contains(text, `.\kit.cmd autostart off`) {
		t.Errorf("the Startup entry is CRLF and UTF-8, for a folder named in any language, and says how to remove it:\n%q", text)
	}
	if len(started) != 1 || started[0] != entry || !strings.Contains(said.String(), "whenever you sign in") {
		t.Errorf("./kit autostart on starts the kit now too, and says it starts as you sign in: %v %s", started, said.String())
	}
	upper := strings.ToUpper(kit)
	if autostartState(kit, "") != "on" || autostartState(upper, filepath.Join(upper, "APP")) != "on" {
		t.Error("the entry reads back, % and all, in any case")
	}
	if autostartState(elsewhere, "") != "other" {
		t.Error("another kit folder's entry is another's")
	}
	if restartIfAutostarted(kit) {
		t.Error("a sharing change doesn't restart the kit: which window Windows started can't be told")
	}
	if localName() != "" {
		t.Error("phones can't find a Windows PC by name")
	}
	autostart(elsewhere, "off", io.Discard)
	kept := exists(entry)
	autostart(kit, "off", io.Discard)
	if !kept || exists(entry) {
		t.Error("./kit autostart off removes this kit's entry, and only this kit's")
	}
}

func TestSystemdUnit(t *testing.T) {
	if windows {
		t.Skip("systemd is Linux's")
	}
	odd := filepath.Join(t.TempDir(), "a kit 100% $HOME")
	os.MkdirAll(filepath.Join(odd, "app", "tools"), 0o755)
	want := `ExecStart=/bin/bash "` + strings.NewReplacer("%", "%%", "$", "$$").Replace(odd) + `/app/Open Tinfoil Kit.command" --no-browser`
	if unit := systemdUnit(odd); !strings.Contains(unit, want+"\n") {
		t.Errorf("a folder with spaces, %% and $ survives systemd's quoting:\n%s", unit)
	}
}

// readPBF is every thing in a road data file, in order.
func readPBF(t *testing.T, path string) []osmThing {
	t.Helper()
	p, err := openPBF(path)
	if err != nil {
		t.Fatal(err)
	}
	defer p.f.Close()
	var all []osmThing
	for {
		th, err := p.peek()
		if err != nil {
			t.Fatal(err)
		}
		if th == nil {
			return all
		}
		all = append(all, *th)
		p.skip()
	}
}

func writePBF(t *testing.T, path string, stamp int64, things ...osmThing) {
	t.Helper()
	o, err := createPBF(path, stamp)
	if err != nil {
		t.Fatal(err)
	}
	for _, th := range things {
		o.add(th)
	}
	if err := o.close(); err != nil {
		t.Fatal(err)
	}
}

// Directions across several places: their road data merged into one file, everything once, nodes, then ways, then
// relations, as GraphHopper reads them.
func TestMergeRoads(t *testing.T) {
	dir := t.TempDir()
	tags := func(kv ...string) [][]byte {
		var out [][]byte
		for _, s := range kv {
			out = append(out, []byte(s))
		}
		return out
	}
	node := func(id int64) osmThing {
		return osmThing{kind: 0, id: id, lat: 42_500_000_000 + id*100, lon: -1_500_000_000 - id*300}
	}
	var a, b []osmThing
	for id := int64(1); id <= 8100; id++ { // more than a block's worth
		n := node(id)
		if id == 2 {
			n.tags = tags("amenity", "hospital", "name", "Hospital de Meritxell")
		}
		a = append(a, n)
	}
	for id := int64(8050); id <= 8200; id++ { // the border: 8050 to 8100 are in both
		b = append(b, node(id))
	}
	road := osmThing{kind: 1, id: 10, refs: []int64{1, 2, 8100}, tags: tags("highway", "residential")}
	a = append(a, road, osmThing{kind: 2, id: 100, refs: []int64{10, 1}, types: []uint64{1, 0}, roles: tags("outer", ""),
		tags: tags("type", "multipolygon")})
	b = append(b, road, osmThing{kind: 1, id: 11, refs: []int64{8100, 8200}, tags: tags("highway", "primary", "ref", "CG-1")},
		osmThing{kind: 2, id: 101, refs: []int64{11}, types: []uint64{1}, roles: tags("")})
	writePBF(t, filepath.Join(dir, "a.osm.pbf"), 1_700_000_000, a...)
	writePBF(t, filepath.Join(dir, "b.osm.pbf"), 1_700_086_400, b...)
	out := filepath.Join(dir, "region.osm.pbf")
	if err := mergePBF(out, []string{filepath.Join(dir, "a.osm.pbf"), filepath.Join(dir, "b.osm.pbf")}); err != nil {
		t.Fatal(err)
	}
	got := readPBF(t, out)
	var ids []int64
	byID := map[[2]int64]osmThing{}
	for _, th := range got {
		ids = append(ids, th.id)
		byID[[2]int64{int64(th.kind), th.id}] = th
	}
	if len(got) != 8200+2+2 || ids[0] != 1 || ids[8199] != 8200 || got[8200].kind != 1 || got[8202].kind != 2 {
		t.Fatalf("every node, way and relation once, in order: %d things", len(got))
	}
	for i := 1; i < len(got); i++ {
		if got[i].kind < got[i-1].kind || got[i].kind == got[i-1].kind && got[i].id <= got[i-1].id {
			t.Fatalf("out of order at %d", i)
		}
	}
	h := byID[[2]int64{0, 2}]
	if string(bytes.Join(h.tags, []byte("="))) != "amenity=hospital=name=Hospital de Meritxell" || h.lat != node(2).lat || h.lon != node(2).lon {
		t.Error("a node keeps its place and tags: ", h)
	}
	w := byID[[2]int64{1, 11}]
	if fmt.Sprint(w.refs) != "[8100 8200]" || string(w.tags[3]) != "CG-1" {
		t.Error("a way keeps its nodes and tags: ", w)
	}
	r := byID[[2]int64{2, 100}]
	if fmt.Sprint(r.refs, r.types) != "[10 1] [1 0]" || string(r.roles[0]) != "outer" || string(r.roles[1]) != "" {
		t.Error("a relation keeps its members and their roles: ", r)
	}
	if p, _ := openPBF(out); p == nil || p.stamp != 1_700_086_400 {
		t.Error("the merged data is as new as the newest file's")
	} else {
		p.f.Close()
	}
	writePBF(t, filepath.Join(dir, "unsorted.osm.pbf"), 0, node(5), node(4))
	if err := mergePBF(out, []string{filepath.Join(dir, "a.osm.pbf"), filepath.Join(dir, "unsorted.osm.pbf")}); err == nil ||
		!strings.Contains(err.Error(), "unsorted.osm.pbf isn't sorted") {
		t.Error("data out of order can't be merged: ", err)
	}
	os.WriteFile(filepath.Join(dir, "page.osm.pbf"), []byte("<html>Not found</html>"), 0o644)
	if err := mergePBF(out, []string{filepath.Join(dir, "a.osm.pbf"), filepath.Join(dir, "page.osm.pbf")}); err == nil ||
		!strings.Contains(err.Error(), "page.osm.pbf isn't road data") {
		t.Error("a file that isn't road data: ", err)
	}
	if len(readPBF(t, out)) != 8204 {
		t.Error("a failed merge leaves the last one as it was")
	}
	if _, err := os.Stat(out + ".partial"); err == nil {
		t.Error("a failed merge leaves nothing half written")
	}
}

// Several places: street detail and directions for each, and home and address search from the first.
func TestSeveralPlaces(t *testing.T) {
	withRegions(t)
	both := []any{"us/new-york", "us/new-jersey"}
	m := mapsSettings(newObj("maps", newObj("enabled", true, "region", both)))
	areas, err := mapAreas(m)
	roads, _ := m.get("routing_osm_pbf").([]any)
	if err != nil || len(areas) != 2 || len(roads) != 2 || m.str("label") != "New York and New Jersey" ||
		!strings.HasSuffix(pyStr(roads[1]), "/new-jersey-latest.osm.pbf") || m.str("geocoder_country") != "us" ||
		m.child("home").str("label") != regionByID("us/new-york").child("home").str("label") {
		t.Error("two places' maps: ", m)
	}
	one := mapsSettings(newObj("maps", newObj("enabled", true, "region", "us/new-york")))
	if a, _ := mapAreas(one); len(a) != 1 || one.str("routing_osm_pbf") == "" || one.str("label") != "New York" {
		t.Error("one place: one area and one road data file, as before")
	}
	for _, i := range mapsItems(newObj("maps", newObj("enabled", true, "region", both))) {
		if l, _ := i.get("url").([]any); i.str("id") == "routing" && len(l) != 2 {
			t.Error("directions get both places' road data: ", i)
		}
	}
	if !mapsSettings(newObj("maps", newObj("region", []any{"us/new-york", "atlantis"}))).has("region_error") {
		t.Error("a place the kit doesn't know, among several")
	}
	if _, err := mapAreas(newObj("detail_bbox", []any{1, 2, 3})); err == nil {
		t.Error("a map area needs four numbers")
	}
	if got, want := tilesEstimate(areas, 15, nil), tilesEstimate(areas[:1], 15, nil)+tilesEstimate(areas[1:], 15, nil)-GB; got < want-2 || got > want+2 {
		t.Errorf("tiles: one world overview, and each place's street detail: %d, not %d", got, want)
	}
	data, err := os.ReadFile(filepath.Join("..", "..", "kit.json"))
	if err != nil {
		t.Fatal(err)
	}
	cfg, _ := parseObj(data)
	root := t.TempDir()
	cfg.child("maps").set("region", "us/new-york")
	alone := estimateBytes(root, cfg, nil, nil, false)
	cfg.child("maps").set("region", both)
	nj := regionByID("us/new-jersey").child("mb")
	tiles, _ := asNumber(nj.get("tiles"))
	road, _ := asNumber(nj.get("roads"))
	if got := estimateBytes(root, cfg, nil, nil, false) - alone; math.Abs(got-(tiles-1000+road)*1e6) > 1e6 {
		t.Errorf("the estimate adds New Jersey's street detail and road data, and no second world or address search: %.0f MB", got/1e6)
	}
}

// Adding a place, or going back to one, reuses the road data the kit has under another name.
func TestRoadsFromBefore(t *testing.T) {
	dest := t.TempDir()
	os.WriteFile(filepath.Join(dest, "region.osm.pbf"), []byte("new york's roads"), 0o644)
	os.WriteFile(filepath.Join(dest, "new-jersey-latest.osm.pbf"), []byte("new jersey's roads"), 0o644)
	sum := func(s string) [][2]string { return [][2]string{{"md5", fmt.Sprintf("%x", md5.Sum([]byte(s)))}} }
	old := newObj("files", newObj("region.osm.pbf", newObj(), "new-jersey-latest.osm.pbf", newObj()))
	ny := &remoteFile{name: "new-york-latest.osm.pbf", size: 16}
	nj := &remoteFile{name: "new-jersey-latest.osm.pbf", size: 18}
	pa := &remoteFile{name: "pennsylvania-latest.osm.pbf", size: 16}
	it := &item{files: []*remoteFile{ny, nj, pa}}
	if sha := roadsFromBefore(dest, old, it, pa, sum("pennsylvania")); sha != "" {
		t.Errorf("another place's road data passed as Pennsylvania's: %s", sha)
	}
	want := fmt.Sprintf("%x", sha256.Sum256([]byte("new york's roads")))
	if sha := roadsFromBefore(dest, old, it, ny, sum("new york's roads")); sha != want ||
		!exists(filepath.Join(dest, "new-york-latest.osm.pbf")) || exists(filepath.Join(dest, "region.osm.pbf")) {
		t.Errorf("one place's road data wasn't moved to its name for several places: %q", sha)
	}
	one := &item{files: []*remoteFile{{name: "region.osm.pbf", size: 18}}}
	old = newObj("files", newObj("new-york-latest.osm.pbf", newObj(), "new-jersey-latest.osm.pbf", newObj()))
	if sha := roadsFromBefore(dest, old, one, one.files[0], sum("new jersey's roads")); sha == "" ||
		!exists(filepath.Join(dest, "region.osm.pbf")) || !exists(filepath.Join(dest, "new-york-latest.osm.pbf")) {
		t.Errorf("going back to one place didn't reuse its road data: %q", sha)
	}
}
