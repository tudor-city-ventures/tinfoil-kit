// Command tinfoilkit is Tinfoil Kit's own program: every ./kit command, among them starting the kit's servers and
// opening its page (open), keeping the page's notes and pins in the data folder (data), and sharing the kit on the
// home network behind the access code (gate, banner). Standard library only, so anyone can build it and get the same
// bytes: tools/tinfoilkit/build.sh.
//
//	tinfoilkit [kit] [--root KIT] open|sync|plan|status|...   ./kit's commands (tinfoilkit kit --help lists them)
//	tinfoilkit     on its own, as a double-click starts it: open
//	tinfoilkit data --data KIT/data --port 8095 --library 8888
//	tinfoilkit gate --root KIT --port 8000 --library 8888 --ai 8080 [--data N --tiles N --geocoder N --routing N]
//	tinfoilkit banner --root KIT --port 8000 [--qr]
//	tinfoilkit compare A B     whether two copies of the program are the same (build.sh verify asks)
//	tinfoilkit list FILE [TAIL]  SETUP-Windows.bat's numbered choices
//	tinfoilkit version
//
// Where things are:
//
//	main.go      which command to run, and on which kit folder
//	kit.go       the kit's folders, output and logs, the command line, and the list of ./kit's commands
//	plan.go      each item's newest version and files, from its publisher (plan)
//	sync.go      downloading, several connections to a big file, checking and installing (sync)
//	cmds.go      pick, remove, fit, plan, pins, sync, verify, status, search and test
//	pick.go      where you live and Wikipedia's languages (region), what fits (estimate, space), essentials, starter
//	setup.go     drives, place, kits, layout, update (signed releases), share and autostart
//	copy.go      a copy of the kit on another drive, as much as fits (copy), and its card to print
//	open.go      starting the servers and opening the page (open)
//	gate.go      sharing on the home network behind the access code (gate, banner), with qr.go's QR code
//	data.go      the page's notes and the map's home and pins (data)
//	pbf.go       merging places nearby's road data into one file for directions
//	json.go      kit.json and the kit's records, read and written in the layout people see
//	sys_*.go     what Windows does differently: memory, disk space, processes, locks, reading straight from a drive
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

const usage = "usage: tinfoilkit [kit] COMMAND | data | gate | banner | compare | list | version " +
	"(tinfoilkit kit --help lists the commands; tools/tinfoilkit/main.go says more)"

func main() {
	if windows { // the copy of this program an update replaced while it ran (installRelease)
		if me, err := os.Executable(); err == nil {
			os.Remove(me + ".old")
		}
	}
	args := os.Args[1:]
	if len(args) == 0 {
		args = []string{"open"}
	}
	if args[0] == "--root" || strings.HasPrefix(args[0], "--root=") || isKitCommand(args[0]) {
		os.Exit(runKit(args))
	}
	cmd, args := args[0], args[1:]
	switch cmd {
	case "kit":
		os.Exit(runKit(args))
	case "data":
		os.Exit(runData(args))
	case "gate":
		os.Exit(runGate(args))
	case "banner":
		os.Exit(runBanner(args))
	case "compare":
		os.Exit(runCompare(args))
	case "list":
		os.Exit(runList(args))
	case "version":
		fmt.Printf("Tinfoil Kit's program for %s (%s)\n", plat(), runtime.Version())
	case "-h", "--help":
		fmt.Println(usage)
	default:
		fmt.Fprintln(os.Stderr, usage)
		os.Exit(2)
	}
}

// The kit folder holds three: app (the code, with this program in app/tools), downloads (what sync gets) and data
// (the person's own: kit.json, logs, and the kit's records in data/.kit). A git checkout's kit folder, kit/ in the
// repository, is its own app folder, with downloads/ and data/ inside it. A kit from before those folders keeps
// everything at its top until its next SETUP moves it.
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
		l.conf = filepath.Join(l.app, "kit.json") // ./kit makes the person's copy the first time it runs
	}
	return l
}

// kitOf is the kit folder an app folder belongs to: its parent, or a git checkout's kit folder itself.
func kitOf(app string) string {
	if !checkout(app) && strings.EqualFold(filepath.Base(app), "app") {
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

// runList prints the lines ./kit region wrote to FILE (id, name and group, tab-separated), numbered, as
// "  1  NAME (GROUP)" with TAIL after GROUP: SETUP-Windows.bat's choices, which cmd would garble (letters with accents).
func runList(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: tinfoilkit list FILE [TAIL]")
		return 2
	}
	tail := ""
	if len(args) > 1 {
		tail = args[1]
	}
	data, err := os.ReadFile(args[0])
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	for i, line := range pyLines(string(data)) {
		f := append(strings.Split(line, "\t"), "", "")
		fmt.Printf("  %d  %s (%s%s)\n", i+1, f[1], f[2], tail)
	}
	return 0
}
