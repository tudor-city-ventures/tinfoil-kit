// Command tinfoilkit is Tinfoil Kit's own program. It starts the kit's servers and opens its page (open), and
// shares the kit on the home network behind the access code (gate, banner). Standard library only, so anyone can
// build it and get the same bytes: tools/tinfoilkit/build.sh.
//
//	tinfoilkit open [--share] [--model=NAME] [--no-browser] [--no-maps] [--root KIT]
//	tinfoilkit gate --root KIT --port 8000 --library 8888 --ai 8080 [--tiles N --geocoder N --routing N]
//	tinfoilkit banner --root KIT --port 8000 [--qr]
//	tinfoilkit compare A B     whether two copies of the program are the same (build.sh verify asks)
//	tinfoilkit version
package main

import (
	"bytes"
	"encoding/binary"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

var (
	windows = runtime.GOOS == "windows"
	mac     = runtime.GOOS == "darwin"
)

func main() {
	args := os.Args[1:]
	cmd := "open"
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		cmd, args = args[0], args[1:]
	}
	switch cmd {
	case "open":
		os.Exit(runOpen(args))
	case "gate":
		os.Exit(runGate(args))
	case "banner":
		os.Exit(runBanner(args))
	case "compare":
		os.Exit(runCompare(args))
	case "version":
		fmt.Printf("Tinfoil Kit's program for %s (%s)\n", plat(), runtime.Version())
	default:
		fmt.Fprintln(os.Stderr, "usage: tinfoilkit open | gate | banner | compare | version (tools/tinfoilkit/main.go says more)")
		os.Exit(2)
	}
}

// The kit folder holds three: app (the code, with this program in app/tools), downloads (what sync gets) and data
// (the person's own: kit.json, logs, and the kit's records in data/.kit). A git checkout is its own app folder, with
// downloads/ and data/ inside it. A kit from before those folders keeps everything at its top until its next SETUP
// moves it.
type layout struct {
	app, kit, dl, data, conf string
}

// kitLayout finds the kit's folders: from --root, the kit folder, or else from where this program is.
func kitLayout(root string) layout {
	var l layout
	if root != "" {
		l.kit = root
		if abs, err := filepath.Abs(root); err == nil {
			l.kit = abs
		}
		l.app = l.kit
		if isDir(filepath.Join(l.kit, "app", "tools")) {
			l.app = filepath.Join(l.kit, "app")
		}
	} else {
		exe, err := os.Executable()
		if err == nil {
			if r, err := filepath.EvalSymlinks(exe); err == nil {
				exe = r
			}
			l.app = filepath.Dir(filepath.Dir(exe))
		} else {
			l.app, _ = os.Getwd()
		}
		l.kit = kitOf(l.app)
	}
	l.dl, l.data = filepath.Join(l.kit, "downloads"), filepath.Join(l.kit, "data")
	if !isDir(l.dl) && isDir(filepath.Join(l.kit, "bin")) {
		l.dl, l.data = l.kit, l.kit
	}
	l.conf = filepath.Join(l.data, "kit.json")
	if !isFile(l.conf) {
		l.conf = filepath.Join(l.app, "kit.json") // kit.py makes the person's copy the first time it runs
	}
	return l
}

// kitOf is the kit folder an app folder belongs to: its parent, or a git checkout itself (even one called app).
func kitOf(app string) string {
	if _, err := os.Stat(filepath.Join(app, ".git")); err != nil && strings.EqualFold(filepath.Base(app), "app") {
		return filepath.Dir(app)
	}
	return app
}

// setting is a simple "key": value from a kit.json, the first line that has it, read the way the scripts before this
// program read it, so a kit.json that doesn't parse still opens.
func setting(conf, key, def string) string {
	data, _ := os.ReadFile(conf)
	re := regexp.MustCompile(`"` + regexp.QuoteMeta(key) + `"\s*:\s*"?([^",}]*)"?`)
	for _, line := range strings.Split(string(data), "\n") {
		if m := re.FindStringSubmatch(line); m != nil {
			if v := strings.TrimSpace(m[1]); v != "" {
				return v
			}
			return def
		}
	}
	return def
}

// plat names this computer the way bin/ does: macos-arm64, linux-x64, windows-x64...
func plat() string {
	osName := map[string]string{"darwin": "macos", "linux": "linux", "windows": "windows"}[runtime.GOOS]
	arch := map[string]string{"amd64": "x64", "arm64": "arm64"}[runtime.GOARCH]
	if osName == "" || arch == "" {
		return "unknown"
	}
	return osName + "-" + arch
}

func say(lines ...string) {
	for _, l := range lines {
		fmt.Println(l)
	}
}

// kitCmd is a kit command as this computer runs it.
func kitCmd(args string) string {
	if windows {
		return `.\kit.cmd ` + args
	}
	return "./kit " + args
}

func isDir(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}

func isFile(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.Mode().IsRegular()
}

func newFlags(name string) *flag.FlagSet {
	fs := flag.NewFlagSet(name, flag.ContinueOnError)
	fs.SetOutput(os.Stderr)
	return fs
}

// runCompare says whether two copies of the program are the same: byte for byte, or for a Mac's, apart from its code
// signature, which the Mac app's signing for Apple replaces. The signature covers everything before it, so that
// must match.
func runCompare(args []string) int {
	if len(args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: tinfoilkit compare A B")
		return 2
	}
	a, err := os.ReadFile(args[0])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	b, err := os.ReadFile(args[1])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	switch {
	case bytes.Equal(a, b):
		fmt.Println("the same")
	case sameUnsigned(a, b):
		fmt.Println("the same apart from the code signature")
	default:
		fmt.Println("different")
		return 1
	}
	return 0
}

func sameUnsigned(a, b []byte) bool {
	ua, okA := unsigned(a)
	ub, okB := unsigned(b)
	return okA && okB && bytes.Equal(ua, ub)
}

// unsigned is a Mac program up to its code signature, with the numbers signing changes set to 0: the signature's size,
// and the size of the segment it ends (__LINKEDIT), in the file and in memory.
func unsigned(data []byte) ([]byte, bool) {
	le := binary.LittleEndian
	if len(data) < 32 || le.Uint32(data) != 0xfeedfacf { // a 64-bit Mach-O
		return nil, false
	}
	out := append([]byte(nil), data...)
	sig, linkedit := -1, -1
	off := 32
	for i := uint32(0); i < le.Uint32(data[16:]); i++ {
		if off+8 > len(data) {
			return nil, false
		}
		cmd, size := le.Uint32(data[off:]), int(le.Uint32(data[off+4:]))
		if size < 8 || off+size > len(data) {
			return nil, false
		}
		switch {
		case cmd == 0x19 && size >= 72 && string(bytes.TrimRight(data[off+8:off+24], "\x00")) == "__LINKEDIT": // LC_SEGMENT_64
			linkedit = off
		case cmd == 0x1d && size >= 16: // LC_CODE_SIGNATURE
			sig = int(le.Uint32(data[off+8:]))
			le.PutUint32(out[off+12:], 0)
		}
		off += size
	}
	if sig < off || sig > len(data) || linkedit < 0 {
		return nil, false
	}
	le.PutUint64(out[linkedit+32:], 0)
	le.PutUint64(out[linkedit+48:], 0)
	return out[:sig], true
}
