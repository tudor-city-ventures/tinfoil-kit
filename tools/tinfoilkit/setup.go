package main

// Where the kit lives and how it gets there (drives, place, kits, layout), its own updates, and sharing it on the
// home network (share, autostart).

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/ed25519"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"errors"
	"fmt"
	"html"
	"io"
	"math"
	"os"
	"os/exec"
	"os/user"
	"path"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// ----------------------------------------------------------------------------- where the kit lives

// driveBases is where plugged-in drives show up (KIT_DRIVES: that folder instead, for tests).
func driveBases() []string {
	if d := os.Getenv("KIT_DRIVES"); d != "" {
		return []string{d}
	}
	switch {
	case windows:
		return nil // drive letters instead: winDrives()
	case mac:
		return []string{"/Volumes"}
	}
	if u := os.Getenv("USER"); u != "" {
		return []string{filepath.Join("/media", u), filepath.Join("/run/media", u)}
	}
	return nil
}

var plistString = regexp.MustCompile(`<key>(FilesystemUserVisibleName|FilesystemName)</key>\s*<string>([^<]*)</string>`)

// driveFormat is a drive's format as the system names it ("ExFAT", "MS-DOS (FAT32)", "exfat", "vfat"...), or "" if
// unknown.
func driveFormat(p string) string {
	if windows {
		_, fs := winVolume(p)
		return fs
	}
	if mac {
		c := exec.Command("diskutil", "info", "-plist", p)
		var outBuf bytes.Buffer
		c.Stdout = &outBuf
		if c.Start() != nil {
			return ""
		}
		done := make(chan struct{})
		go func() { c.Wait(); close(done) }()
		select {
		case <-done:
		case <-time.After(30 * time.Second):
			c.Process.Kill()
			return ""
		}
		names := map[string]string{}
		for _, m := range plistString.FindAllStringSubmatch(outBuf.String(), -1) {
			names[m[1]] = html.UnescapeString(m[2])
		}
		if n := names["FilesystemUserVisibleName"]; n != "" {
			return n
		}
		return names["FilesystemName"]
	}
	data, err := os.ReadFile("/proc/mounts")
	if err != nil {
		return ""
	}
	where, best, fs := resolvePath(p), "", ""
	for _, line := range strings.Split(string(data), "\n") {
		f := strings.Fields(line)
		mnt := ""
		if len(f) > 2 {
			mnt = strings.ReplaceAll(f[1], `\040`, " ")
		}
		if mnt != "" && (where == mnt || strings.HasPrefix(where, strings.TrimRight(mnt, "/")+"/")) && len(mnt) >= len(best) {
			best, fs = mnt, f[2]
		}
	}
	return fs
}

// driveProblem is why the kit can't live on a drive of this format, or "" if it can.
func driveProblem(fs string) string {
	f := strings.ToLower(fs)
	if strings.Contains(strings.ReplaceAll(f, "exfat", ""), "fat") || strings.Contains(f, "ms-dos") || f == "msdos" {
		return "it's formatted as " + fs + ", which can't hold files over 4 GB, and the AI models and books are bigger"
	}
	if mac && (strings.Contains(f, "ntfs") || strings.Contains(f, "windows")) {
		return "it's formatted as " + fs + ", which a Mac can read but can't save to"
	}
	return ""
}

// listDrives is the drives plugged in: folder, name, format, free bytes, whether a kit is there, and why the kit can't
// go there, if it can't. Drives that can't be written to (installer disk images, backups) are left out, unless their
// format is the reason, so SETUP can say why those won't do. In /Volumes the Mac's own disk is a link to /.
func listDrives() []*obj {
	var found []*obj
	bases := driveBases()
	if len(bases) == 0 {
		bases = []string{""}
	}
	for _, base := range bases {
		var folders []string
		if base != "" {
			entries, err := os.ReadDir(base)
			if err != nil {
				continue
			}
			for _, e := range entries {
				folders = append(folders, filepath.Join(base, e.Name()))
			}
			sortPaths(folders)
		} else if windows {
			folders = winDrives()
		}
		for _, v := range folders {
			if base != "" {
				if st, err := os.Lstat(v); strings.HasPrefix(filepath.Base(v), ".") || err != nil || st.Mode()&os.ModeSymlink != 0 || !isDir(v) {
					continue
				}
			}
			fs := driveFormat(v)
			problem := driveProblem(fs)
			if problem == "" && !writable(v) {
				continue
			}
			free, _, err := diskSpace(v)
			if err != nil {
				continue
			}
			var prob any
			if problem != "" {
				prob = problem
			}
			if fs == "" {
				fs = "unknown"
			}
			found = append(found, newObj("path", v, "name", driveName(v), "format", fs, "free_bytes", free,
				"problem", prob, "has_kit", isKit(filepath.Join(v, kitFolder))))
		}
	}
	return found
}

// driveName is the name of the drive a folder is on.
func driveName(p string) string {
	if windows && os.Getenv("KIT_DRIVES") == "" {
		abs, _ := filepath.Abs(p)
		letter := filepath.VolumeName(abs)
		if label, _ := winVolume(p); label != "" {
			return label + " (" + letter + ")"
		}
		return letter
	}
	for _, base := range driveBases() {
		if rel, err := filepath.Rel(base, p); err == nil && rel != "." && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return strings.Split(rel, string(filepath.Separator))[0]
		}
	}
	for !isMount(p) && filepath.Dir(p) != p {
		p = filepath.Dir(p)
	}
	if b := filepath.Base(p); b != string(filepath.Separator) && b != "." {
		return b
	}
	return p
}

// isMount is os.path.ismount: a folder that's the top of a disk.
func isMount(p string) bool {
	parent := filepath.Dir(p)
	return parent == p || !sameDevice(p, parent)
}

func samePath(a, b string) bool {
	a, b = filepath.Clean(a), filepath.Clean(b)
	if windows {
		return strings.EqualFold(a, b)
	}
	return a == b
}

// within is whether folder is inside base (Python's "base in folder.parents").
func within(folder, base string) bool {
	for p := filepath.Dir(folder); ; p = filepath.Dir(p) {
		if samePath(p, base) {
			return true
		}
		if filepath.Dir(p) == p {
			return false
		}
	}
}

// whereIs is "this Mac" or "the drive NAME", for messages.
func whereIs(folder string) string {
	onDrive := false
	for _, b := range driveBases() {
		onDrive = onDrive || samePath(b, folder) || within(folder, b)
	}
	if !onDrive && onThisComputer(folder) {
		return this
	}
	return "the drive " + driveName(folder)
}

func cmdDrives(root string, a *cliArgs) {
	drives := listDrives()
	if !a.flag("json") {
		for _, d := range drives {
			problem := "-"
			if p, ok := d.get("problem").(string); ok {
				problem = p
			}
			out(strings.Join([]string{d.str("path"), d.str("format"), strconv.FormatInt(intOr(d.get("free_bytes"), 0)/GB, 10),
				problem, d.str("name")}, "\t") + "\n")
		}
		return
	}
	cfg := loadConfig(root)
	home, _ := os.UserHomeDir()
	free, _ := diskUsage(home)
	keep, _ := asNumber(cfg.child("settings").getOr("keep_free_gb_this_computer", 50))
	var list []any
	for _, d := range drives {
		kit := filepath.Join(d.str("path"), kitFolder)
		list = append(list, with(d, "kit_path", kit, "space", spaceAt(kit, root, cfg)))
	}
	if list == nil {
		list = []any{}
	}
	mine := filepath.Join(home, kitFolder)
	out(dumps(newObj("kit", root, "kit_on_this_computer", onThisComputer(root), "needs_gb", estimateGB(root, cfg, &no, nil, false),
		"needs_essentials_gb", estimateGB(root, cfg, &yes, nil, false),
		"this_computer", newObj("path", mine, "free_bytes", free, "keeps_free_gb", keep, "space", spaceAt(mine, root, cfg)),
		"drives", list), jsonStyle{indent: 2, ascii: true}) + "\n")
}

// devBuilds is npm's packages (the website's, and the developer tools in package.json), the website's build and
// ruff's cache.
var devBuilds = []string{"node_modules", ".next", ".ruff_cache"}

// copyCode copies files and folders with their contents and permissions, never extended attributes (no ._ files on
// exFAT, no "from the internet" marks) or timestamps, which some drive formats refuse. A developer's installed tools
// and builds (devBuilds) stay behind: nothing on a drive uses them.
func copyCode(src, dst string) error {
	if contains(devBuilds, filepath.Base(src)) {
		return nil
	}
	if isDir(src) {
		if err := os.Mkdir(dst, 0o755); err != nil {
			return err
		}
		entries, err := os.ReadDir(src)
		if err != nil {
			return err
		}
		for _, e := range entries {
			if !strings.HasPrefix(e.Name(), "._") {
				if err := copyCode(filepath.Join(src, e.Name()), filepath.Join(dst, e.Name())); err != nil {
					return err
				}
			}
		}
		return nil
	}
	return copyFileMode(src, dst)
}

// keepNames: a release never brings these, whatever it holds: a git checkout's, and the downloads, state and logs of
// a kit from before app/, downloads/ and data/.
var keepNames = []string{".git", ".kit", "bin", "installers", "library", "logs", "maps", "models", "INVENTORY.md"}

// copyApp makes a copy of this kit's code as the app folder to: what a release has (no .git, downloads or data). A
// git checkout's copy gets the checkout's commit in tools/commit, as git archive writes a release's, so ./kit update
// there can tell whether a release is newer.
func copyApp(root, to string) error {
	if err := os.Mkdir(to, 0o755); err != nil {
		return err
	}
	entries, err := os.ReadDir(appDir(root))
	if err != nil {
		return err
	}
	for _, e := range entries {
		n := e.Name()
		if !contains(keepNames, n) && n != "downloads" && n != "data" && !strings.HasPrefix(n, "._") {
			if err := copyCode(filepath.Join(appDir(root), n), filepath.Join(to, n)); err != nil {
				return err
			}
		}
	}
	if exists(filepath.Join(root, ".git")) { // (only then: on a Mac without git, running it asks to install Xcode's tools)
		if head, _, rc := output("git", "-C", root, "rev-parse", "HEAD"); rc == 0 && commitLine.Match(bytes.TrimSpace(head)) {
			return os.WriteFile(filepath.Join(to, "tools", "commit"), append(bytes.TrimSpace(head), '\n'), 0o644)
		}
	}
	return nil
}

// placeKit puts the kit at dest, ready to set up there. Returns its folder and what happened, in words. A fresh
// download is moved there, so there's one copy: renamed on the same disk, copied to another (app/ and data/, never
// downloads). A git checkout is a developer's: it stays put, or its code is copied to another disk as an app folder.
// A kit already at dest is used as it is. On Windows it's always a copy, since Windows won't rename or delete a folder
// a running program is in. The kit placed gets its downloads folder, which tells SETUP it's been set up. A kit at dest
// whose app folder was deleted gets a copy of this one.
func placeKit(root, dest string) (string, string, error) {
	git := exists(filepath.Join(root, ".git"))
	parent := filepath.Dir(dest)
	if !isDir(parent) {
		return "", "", fmt.Errorf("%s isn't there. If it's a drive, is it plugged in?", parent)
	}
	if samePath(dest, root) || samePath(parent, root) || (git && sameDevice(root, parent)) {
		os.Mkdir(dlDir(root), 0o755)
		return root, "", nil
	}
	if within(dest, root) {
		return "", "", fmt.Errorf("The kit can't go inside its own folder (%s).", dest)
	}
	where := whereIs(parent)
	why := func(err error) string {
		var pe *os.PathError
		if errors.As(err, &pe) {
			return strerror(pe.Err)
		}
		var le *os.LinkError
		if errors.As(err, &le) {
			return strerror(le.Err)
		}
		return err.Error()
	}
	if exists(dest) {
		if !isKit(dest) {
			return "", "", fmt.Errorf("There's already a folder called %s on %s (%s), and it isn't a Tinfoil Kit.\n"+
				"Rename it or move it somewhere else, then double-click SETUP again.", filepath.Base(dest), where, dest)
		}
		fresh := !hasCode(dest)
		if fresh { // its app folder was deleted, for a new version's: this one
			os.RemoveAll(filepath.Join(dest, "app.partial"))
			err := copyApp(root, filepath.Join(dest, "app.partial"))
			if err == nil {
				os.RemoveAll(filepath.Join(dest, "app"))
				err = os.Rename(filepath.Join(dest, "app.partial"), filepath.Join(dest, "app"))
			}
			if err != nil {
				return "", "", fmt.Errorf("Copying the app folder to %s stopped partway (%s). Is the drive full, or was it "+
					"unplugged?", where, why(err))
			}
		}
		// (a kit from before the app folder knows it's been set up by its .kit folder; its SETUP takes over)
		if isDir(filepath.Join(dest, "tools")) && !exists(filepath.Join(dest, ".git")) {
			os.Mkdir(filepath.Join(dest, ".kit"), 0o755)
		} else {
			os.Mkdir(dlDir(dest), 0o755)
		}
		said := fmt.Sprintf("There's already a Tinfoil Kit on %s (%s)", where, dest)
		if fresh {
			said += ", without its app folder: this version's is in it now"
		}
		return dest, said + ". Carrying on with that one.", nil
	}
	if !git && !alone(root) {
		return "", "", fmt.Errorf("This app folder isn't in a folder of its own (%s has other things in it), so it stays "+
			"where it is.\nMake a folder called %s, put the app folder in it, and double-click SETUP again.", root, kitFolder)
	}
	if !git && !windows && sameDevice(root, parent) {
		if os.Rename(root, dest) == nil { // or else copy it
			os.Mkdir(dlDir(dest), 0o755)
			return dest, fmt.Sprintf("Moved the kit to %s: %s", where, dest), nil
		}
	}
	partial := dest + ".partial"
	os.RemoveAll(partial)
	if err := os.Mkdir(partial, 0o755); err != nil {
		msg := fmt.Sprintf("Couldn't save anything on %s (%s).", where, why(err))
		if mac {
			msg += "\nIf macOS asked whether Terminal may use files there, it needs a yes. Open System Settings > " +
				"Privacy & Security > Files and Folders, turn on Removable Volumes under Terminal, then try again."
		}
		return "", "", errors.New(msg)
	}
	err := copyApp(root, filepath.Join(partial, "app"))
	if err == nil {
		// the person's choices so far (where they live, what goes in), not the kit's records or logs
		entries, _ := os.ReadDir(dataDir(root))
		for _, e := range entries {
			if n := e.Name(); n != ".kit" && n != "logs" && !strings.HasPrefix(n, "._") && err == nil {
				os.Mkdir(filepath.Join(partial, "data"), 0o755)
				err = copyCode(filepath.Join(dataDir(root), n), filepath.Join(partial, "data", n))
			}
		}
	}
	if err == nil {
		err = os.Rename(partial, dest)
	}
	if err != nil {
		os.RemoveAll(partial)
		return "", "", fmt.Errorf("Copying the kit to %s stopped partway (%s). Is the drive full, or was it unplugged?", where, why(err))
	}
	os.Mkdir(dlDir(dest), 0o755)
	home, _ := os.UserHomeDir()
	if git || samePath(root, home) || windows || exists(dlDir(root)) {
		return dest, fmt.Sprintf("Copied the kit to %s: %s. Use that copy from now on.", where, dest), nil
	}
	os.RemoveAll(root) // the download isn't needed now that the kit is in its place
	return dest, fmt.Sprintf("Moved the kit to %s: %s", where, dest), nil
}

// cmdPlace: messages go to stderr, so a script can read the kit's new folder from stdout.
func cmdPlace(root string, a *cliArgs) {
	dest, said, err := placeKit(root, absPath(a.str("dest")))
	if err != nil {
		fmt.Fprintf(os.Stderr, "\n%s\n", err)
		exit(1)
	}
	if said != "" {
		fmt.Fprintf(os.Stderr, "\n%s\n", said)
	}
	out(dest + "\n")
}

// otherKits is kits set up before, in the home folder or on a drive plugged in, other than this one: the one synced
// last first. A new download of the kit carries on with one of these rather than set up a second.
func otherKits(root string) []*obj {
	home, _ := os.UserHomeDir()
	places := []string{filepath.Join(home, kitFolder)}
	for _, d := range listDrives() {
		if truthy(d.get("has_kit")) {
			places = append(places, filepath.Join(d.str("path"), kitFolder))
		}
	}
	// the Mac app remembers the kit it opened last
	if last, err := os.ReadFile(filepath.Join(home, "Library", "Application Support", "TinfoilKit", "last-kit")); err == nil {
		if l := strings.TrimSpace(string(last)); l != "" {
			places = append([]string{l}, places...)
		}
	}
	var found []*obj
	seen := map[string]bool{resolvePath(root): true}
	for _, k := range places {
		r := resolvePath(k)
		if seen[r] {
			continue
		}
		seen[r] = true
		s := statePath(k)
		if !isFile(s) {
			s = filepath.Join(k, ".kit", "state.json")
		}
		data, err := os.ReadFile(s)
		if err != nil {
			continue
		}
		state, err := parseObj(data)
		if err != nil {
			continue
		}
		items := state.child("items")
		if isKit(k) && items.size() > 0 {
			var total int64
			for _, key := range items.Keys() {
				total += driveBytes(items.child(key))
			}
			last := ""
			if truthy(state.get("last_sync")) {
				last = pyStr(state.get("last_sync"))
			}
			found = append(found, newObj("path", k, "where", whereIs(k), "bytes", total, "last_sync", last))
		}
	}
	sort.SliceStable(found, func(i, j int) bool { return found[i].str("last_sync") > found[j].str("last_sync") })
	return found
}

func cmdKits(root string, a *cliArgs) {
	for _, k := range otherKits(root) {
		last := clip(k.str("last_sync"), 10)
		if last == "" {
			last = "-"
		}
		out(strings.Join([]string{k.str("path"), k.str("where"),
			strconv.FormatInt(int64(math.Ceil(float64(intOr(k.get("bytes"), 0))/GB)), 10), last}, "\t") + "\n")
	}
}

// ----------------------------------------------------------------------------- the kit's own updates

// A release is a tarball the maintainer built and signed on their own computer (.github/release.sh), so taking over
// the kit's GitHub account isn't enough to put code on every drive. tools/release-signers holds the keys a drive
// accepts, and each release brings the next copy of it: a new key arrives signed by the old one.
const (
	releaseNamespace = "tinfoilkit-release"
	report           = "https://github.com/tudor-city-ventures/tinfoil-kit/security"
)

// programName is this computer's copy of the kit's program, in a release's tools/.
func programName() string {
	if windows {
		return "tinfoilkit-" + plat() + ".exe"
	}
	return "tinfoilkit-" + plat()
}

// needed is what a release must have for this computer to run it. Only what every version will have: a kit refuses
// a release without one of these, for good.
func needed() []string {
	if windows {
		return []string{"kit.cmd", "kit.json", "SETUP-Windows.bat", "Open Tinfoil Kit for Windows.bat", "UNINSTALL-Windows.bat",
			"tools/portal.html", "tools/" + programName()}
	}
	return []string{"kit", "kit.json", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command",
		"tools/portal.html", "tools/" + programName()}
}

// sshStrings splits SSH wire format into its length-prefixed strings.
func sshStrings(b []byte) ([][]byte, error) {
	var out [][]byte
	for len(b) > 0 {
		if len(b) < 4 {
			return nil, errors.New("truncated")
		}
		n := binary.BigEndian.Uint32(b[:4])
		if uint64(len(b)) < 4+uint64(n) {
			return nil, errors.New("truncated")
		}
		out = append(out, b[4:4+n])
		b = b[4+n:]
	}
	return out, nil
}

var signerLine = regexp.MustCompile(`(?m)^` + releaseNamespace + `\s(?:.*?\s)?ssh-ed25519\s+([A-Za-z0-9+/]+=*)`)

// releaseKeys is the Ed25519 keys tools/release-signers lists for the kit's releases (ssh-keygen's allowed-signers
// format).
func releaseKeys(signers string) [][]byte {
	text, err := os.ReadFile(signers)
	if err != nil {
		return nil
	}
	var keys [][]byte
	for _, m := range signerLine.FindAllStringSubmatch(string(text), -1) {
		blob, err := base64.StdEncoding.DecodeString(m[1])
		if err != nil {
			continue
		}
		parts, err := sshStrings(blob)
		if err == nil && len(parts) == 2 && string(parts[0]) == "ssh-ed25519" && len(parts[1]) == 32 {
			keys = append(keys, parts[1])
		}
	}
	return keys
}

// verifyRelease refuses a release unless one of this copy's keys signed it, the way ssh-keygen -Y sign does.
func verifyRelease(root string, data, sig []byte) error {
	keys := releaseKeys(filepath.Join(appDir(root), "tools", "release-signers"))
	if len(keys) == 0 {
		return errors.New("this copy of the kit has no release key to check it with (tools/release-signers). " +
			"Download the kit again from tinfoilkit.com")
	}
	damaged := fmt.Errorf("its signature file is damaged. Please report it at %s", report)
	words := strings.Fields(string(sig))
	start, end := -1, -1
	for i, w := range words {
		if w == "SIGNATURE-----" && start < 0 {
			start = i
		}
		if w == "-----END" && end < 0 {
			end = i
		}
	}
	for _, c := range sig {
		if c >= 0x80 {
			return damaged
		}
	}
	if start < 0 || end < 0 || end < start+1 {
		return damaged
	}
	blob, err := base64.StdEncoding.DecodeString(strings.Join(words[start+1:end], ""))
	if err != nil || len(blob) < 10 || string(blob[:10]) != "SSHSIG\x00\x00\x00\x01" {
		return damaged
	}
	fields, err := sshStrings(blob[10:])
	if err != nil || len(fields) != 5 {
		return damaged
	}
	keyBlob, namespace, reserved, alg, sigBlob := fields[0], fields[1], fields[2], fields[3], fields[4]
	k, err := sshStrings(keyBlob)
	if err != nil || len(k) != 2 {
		return damaged
	}
	s, err := sshStrings(sigBlob)
	if err != nil || len(s) != 2 {
		return damaged
	}
	kind, key, sigKind, raw := k[0], k[1], s[0], s[1]
	known := false
	for _, x := range keys {
		known = known || bytes.Equal(x, key)
	}
	var digest []byte
	switch string(alg) {
	case "sha256":
		d := sha256.Sum256(data)
		digest = d[:]
	case "sha512":
		d := sha512.Sum512(data)
		digest = d[:]
	}
	signed := []byte("SSHSIG")
	for _, x := range [][]byte{namespace, reserved, alg, digest} {
		signed = binary.BigEndian.AppendUint32(signed, uint32(len(x)))
		signed = append(signed, x...)
	}
	if !(known && string(kind) == "ssh-ed25519" && string(sigKind) == "ssh-ed25519" && string(namespace) == releaseNamespace &&
		digest != nil && len(key) == ed25519.PublicKeySize && len(raw) == ed25519.SignatureSize &&
		ed25519.Verify(ed25519.PublicKey(key), signed, raw)) {
		return fmt.Errorf("it isn't signed with the kit's release key. Someone other than the kit's maintainer may have "+
			"published it: don't install it by hand, and please report it at %s", report)
	}
	return nil
}

// unpackRelease unpacks a GitHub release archive into dest without trusting it: plain files and folders only, all
// inside its one top folder, and nothing for the kit's own folders of downloads (keepNames).
func unpackRelease(data []byte, dest string) error {
	gz, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return err
	}
	tr := tar.NewReader(gz)
	var total int64
	top := ""
	for {
		h, err := tr.Next()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		if h.Typeflag == tar.TypeXGlobalHeader { // git archive's note of its commit
			continue
		}
		var parts []string
		for _, p := range strings.Split(path.Clean("/" + h.Name)[1:], "/") {
			if p != "" {
				parts = append(parts, p)
			}
		}
		bad := len(parts) == 0 || strings.HasPrefix(h.Name, "/") || strings.Contains(h.Name, `\`) || (top != "" && parts[0] != top)
		for _, p := range strings.Split(h.Name, "/") {
			bad = bad || p == ".."
		}
		if bad {
			return fmt.Errorf("the archive has an unexpected path in it: %s", h.Name)
		}
		top = parts[0]
		isFile := h.Typeflag == tar.TypeReg || h.Typeflag == tar.TypeRegA || h.Typeflag == tar.TypeCont || h.Typeflag == tar.TypeGNUSparse
		if !isFile && h.Typeflag != tar.TypeDir {
			return fmt.Errorf("the archive has a link in it (%s), which an exFAT drive can't hold", h.Name)
		}
		if len(parts) < 2 || contains(keepNames, parts[1]) {
			continue
		}
		p := filepath.Join(append([]string{dest}, parts[1:]...)...)
		if !isFile {
			if err := os.MkdirAll(p, 0o755); err != nil {
				return err
			}
			continue
		}
		if total += h.Size; total > 500*1000*1000 {
			return errors.New("the archive is far bigger than a kit release")
		}
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			return err
		}
		f, err := os.Create(p)
		if err != nil {
			return err
		}
		_, err = io.Copy(f, tr)
		if cerr := f.Close(); err == nil {
			err = cerr
		}
		if err != nil {
			return err
		}
		mode := os.FileMode(0o644)
		if h.Mode&0o111 != 0 {
			mode = 0o755
		}
		os.Chmod(p, mode) // exFAT keeps no permissions
	}
}

// checkRelease refuses a release that's incomplete or that this computer couldn't run.
func checkRelease(fresh string) error {
	var missing []string
	for _, rel := range needed() {
		if !isFile(filepath.Join(fresh, filepath.FromSlash(rel))) {
			missing = append(missing, rel)
		}
	}
	if len(missing) > 0 {
		return fmt.Errorf("the release is missing %s", strings.Join(missing, ", "))
	}
	if len(releaseKeys(filepath.Join(fresh, "tools", "release-signers"))) == 0 {
		return errors.New("it has no release key (tools/release-signers), so the kit could never update again")
	}
	// It's signed by now, so this runs the maintainer's program, as the next command would.
	if _, stderr, rc := output(filepath.Join(fresh, "tools", programName()), "version"); rc != 0 {
		why := strings.TrimSpace(string(stderr))
		if why == "" {
			why = fmt.Sprintf("it stopped with code %d", rc)
		}
		return fmt.Errorf("its program won't run on this computer (%s)", clip(why, 200))
	}
	data, err := os.ReadFile(filepath.Join(fresh, "kit.json"))
	if err == nil {
		_, err = parseJSON(data)
	}
	if err != nil {
		return fmt.Errorf("its kit.json doesn't parse (%s)", err)
	}
	for _, script := range []string{"kit", "SETUP.command", "Open Tinfoil Kit.command", "UNINSTALL.command"} {
		p := filepath.Join(fresh, filepath.FromSlash(script))
		if which("bash") && isFile(p) {
			if _, _, rc := output("bash", "-n", p); rc != 0 {
				return fmt.Errorf("its %s has a syntax error", script)
			}
		}
	}
	return nil
}

// installRelease moves the unpacked release over the kit's code in app/ (renames on the same disk, so it takes a
// moment), then removes what this version no longer has. Downloads and the person's data are in other folders, out
// of reach. This computer's program goes last: if this stops partway, the old one, which knows it's older, runs the
// retry. Windows won't replace a program that's running, but lets it be renamed, so it's renamed aside first and
// removed the next time the kit runs.
func installRelease(app, fresh string) error {
	var files []string
	filepath.WalkDir(fresh, func(p string, d os.DirEntry, err error) error {
		if err == nil && d.Type().IsRegular() {
			rel, _ := filepath.Rel(fresh, p)
			files = append(files, filepath.ToSlash(rel))
		}
		return nil
	})
	sort.Strings(files)
	me := "tools/" + programName()
	sort.SliceStable(files, func(i, j int) bool { return files[i] != me && files[j] == me })
	for _, rel := range files {
		to := filepath.Join(app, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(to), 0o755); err != nil {
			return err
		}
		if windows && rel == me && exists(to) {
			os.Remove(to + ".old")
			if err := os.Rename(to, to+".old"); err != nil {
				return err
			}
		}
		if err := os.Rename(filepath.Join(fresh, filepath.FromSlash(rel)), to); err != nil {
			return err
		}
	}
	keep := map[string]bool{}
	for _, f := range files {
		keep[f] = true
	}
	var all []string
	filepath.WalkDir(app, func(p string, d os.DirEntry, err error) error {
		if err == nil && p != app {
			all = append(all, p)
		}
		return nil
	})
	sort.Sort(sort.Reverse(sort.StringSlice(all))) // what's in a folder before the folder
	for _, p := range all {
		rel, _ := filepath.Rel(app, p)
		rel = filepath.ToSlash(rel)
		switch {
		case isDir(p):
			if emptyDir(p) {
				if err := os.Remove(p); err != nil {
					return err
				}
			}
		case !keep[rel] && !(windows && rel == me+".old"):
			if err := os.Remove(p); err != nil {
				return err
			}
		}
	}
	return nil
}

// kitGithub asks the kit's own GitHub repo. nil if GitHub has no such thing; exits if it can't be reached or makes no
// sense.
func kitGithub(p string, keys ...string) *obj {
	v, err := httpJSON(githubAPI+"/repos/"+kitRepo+"/"+p, 0)
	var he *httpError
	if errors.As(err, &he) {
		if he.status == 404 {
			return nil
		}
		log("Couldn't reach GitHub, so this version stays. (" + err.Error() + ")")
		exit(1)
	}
	if o, ok := v.(*obj); ok && err == nil {
		all := true
		for _, k := range keys {
			_, isStr := o.get(k).(string)
			all = all && isStr
		}
		if all {
			return o
		}
	}
	log("GitHub's answer made no sense (a Wi-Fi sign-in page?), so this version stays.")
	exit(1)
	return nil
}

var commitLine = regexp.MustCompile(`^[0-9a-f]{40}$`)

// kitCommit is the commit this copy of the kit was packed from: git archive (a release, or Code > Download ZIP)
// writes it into tools/commit. "" in a git checkout.
func kitCommit() string {
	data, _ := os.ReadFile(filepath.Join(codeRoot, "tools", "commit"))
	if c := strings.TrimSpace(string(data)); commitLine.MatchString(c) {
		return c
	}
	return ""
}

// cmdUpdate exits 3 after installing a new version, so SETUP knows to start over on it.
func cmdUpdate(root string, a *cliArgs) {
	if exists(filepath.Join(root, ".git")) {
		log("This kit folder is a git checkout. Update it with:  git pull")
		return
	}
	tag := func() string {
		defer lockKit(root)()
		state := loadState(root)
		log("Checking GitHub for a newer version of the kit...")
		release := kitGithub("releases/latest", "tag_name")
		if release == nil {
			log("No version of the kit is published yet, so this one stays.")
			return ""
		}
		tag := release.str("tag_name")
		if pyEqual(tag, state.get("kit_version")) && !a.flag("force") {
			log("This is the newest version (" + tag + ").")
			return ""
		}
		if commit := kitCommit(); commit != "" && !a.flag("force") {
			// A copy downloaded from the main branch can be newer than the latest release. No answer means GitHub
			// doesn't know this copy's commit, so the release is the version to have.
			switch kitGithub("compare/"+tag+"..."+commit, "status").get("status") {
			case "identical":
				state.set("kit_version", tag)
				saveState(root, state)
				log("This is the newest version (" + tag + ").")
				return ""
			case "ahead":
				log("This copy of the kit is newer than its latest release (" + tag + "), so it stays.")
				return ""
			}
		}
		name := "tinfoilkit-" + tag + ".tar.gz"
		assets := map[string]any{}
		for _, x := range release.objs("assets") {
			if n, ok := x.get("name").(string); ok {
				assets[n] = x.get("browser_download_url")
			}
		}
		stage := filepath.Join(metaDir(root), "update")
		os.RemoveAll(stage)
		err := func() error { // whatever goes wrong before the first file moves, the kit stays as it was
			url, ok1 := assets[name].(string)
			sigURL, ok2 := assets[name+".sig"].(string)
			if !ok1 || !ok2 {
				return fmt.Errorf("it isn't signed (the release has no %s and %s.sig)", name, name)
			}
			data, err := httpGet(url, 600, "")
			if err != nil {
				return err
			}
			sig, err := httpGet(sigURL, 0, "")
			if err != nil {
				return err
			}
			if err := verifyRelease(root, data, sig); err != nil {
				return err
			}
			if err := unpackRelease(data, stage); err != nil {
				return err
			}
			if err := checkRelease(stage); err != nil {
				return err
			}
			mine := filepath.Join(dataDir(root), "kit.json") // the new version's changes go into it once it's installed
			text, err := os.ReadFile(mine)
			if err != nil {
				return err
			}
			if _, err := parseJSON(text); err != nil {
				var je *jsonError
				if errors.As(err, &je) {
					return fmt.Errorf("%s has a syntax error on line %d, column %d: %s. Fix it, or delete it to start from "+
						"the standard list, then run this again", mine, je.line, je.col, je.msg)
				}
				return err
			}
			return nil
		}()
		if err != nil {
			os.RemoveAll(stage)
			die(fmt.Sprintf("couldn't install version %s, so this one stays as it was: %s", tag, err))
		}
		var news []string
		body := ""
		if truthy(release.get("body")) {
			body = pyStr(release.get("body"))
		}
		for _, line := range pyLines(body) {
			if strings.TrimSpace(line) != "" && len(news) < 12 {
				news = append(news, "  "+strings.TrimRightFunc(line, isSpace))
			}
		}
		said := "Version " + tag + " of the kit is ready, signed by its maintainer."
		if len(news) > 0 {
			said += "\nWhat's new:\n" + strings.Join(news, "\n")
		}
		log(said)
		if !a.flag("yes") && isTerminal(os.Stdin) {
			if ans := strings.ToLower(ask("Install it now? [Y/n] ")); ans != "" && ans != "y" && ans != "yes" {
				os.RemoveAll(stage)
				log("This version stays. Run SETUP again when you want " + tag + ".")
				return ""
			}
		}
		if err := installRelease(appDir(root), stage); err != nil {
			die(fmt.Sprintf("the update stopped partway (%s). Run it again to finish.", err))
		}
		state.set("kit_version", tag)
		saveState(root, state)
		os.RemoveAll(stage)
		return tag
	}()
	if tag == "" {
		return
	}
	log(strings.TrimRightFunc("Installed version "+tag+". "+ensureConfig(root), isSpace))
	exit(3)
}

// ----------------------------------------------------------------------------- the home network

const (
	serviceName = "tinfoil-kit.service"
	agentName   = "com.tinfoilkit.kit"
)

// codeDir is the kit's code: its app folder, or the kit folder itself (a git checkout, or a kit from before app/).
func codeDir(root string) string {
	if isDir(filepath.Join(root, "app", "tools")) {
		return filepath.Join(root, "app")
	}
	return root
}

func launcherFile(root, code string) string {
	if code == "" {
		code = codeDir(root)
	}
	if windows {
		return filepath.Join(code, "Open Tinfoil Kit for Windows.bat")
	}
	return filepath.Join(code, "Open Tinfoil Kit.command")
}

// systemdUnit is a systemd user service: it runs as you, without sudo, and from boot when lingering is on.
func systemdUnit(root string) string {
	arg := strings.NewReplacer(`\`, `\\`, `"`, `\"`, "%", "%%", "$", "$$").Replace(launcherFile(root, ""))
	return "[Unit]\nDescription=Tinfoil Kit: the offline AI, library and maps\n\n" +
		"[Service]\n" +
		`ExecStart=/bin/bash "` + arg + `" --no-browser` + "\n" +
		// It comes back if it stops, or finds the kit already running in a window and leaves it be.
		"Restart=always\nRestartSec=30\n\n" +
		"[Install]\nWantedBy=default.target\n"
}

func homeDir() string {
	h, _ := os.UserHomeDir()
	return h
}

func unitFile() string {
	cfg := os.Getenv("XDG_CONFIG_HOME")
	if cfg == "" {
		cfg = filepath.Join(homeDir(), ".config")
	}
	return filepath.Join(cfg, "systemd", "user", serviceName)
}

func agentFile() string {
	return filepath.Join(homeDir(), "Library", "LaunchAgents", agentName+".plist")
}

// startNow opens a file as a double-click would: startupOn starts the kit the way signing in will. Tests stand in for it.
var startNow = startFile

// startupFile: Windows runs what's in this folder when you sign in.
func startupFile() string {
	roaming := os.Getenv("APPDATA")
	if roaming == "" {
		roaming = filepath.Join(homeDir(), "AppData", "Roaming")
	}
	return filepath.Join(roaming, "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "Tinfoil Kit.cmd")
}

// startupScript runs Open Tinfoil Kit for Windows.bat, minimized, if the kit is still there (a drive can be
// unplugged). In UTF-8 (chcp 65001) for a folder named in any language, with % doubled since cmd reads it as its own.
func startupScript(root string) string {
	bat := strings.ReplaceAll(launcherFile(root, ""), "%", "%%")
	return "@echo off\r\nchcp 65001 >nul\r\n" +
		"rem Starts Tinfoil Kit when you sign in to Windows. " + kitCmd("autostart off") + " removes this.\r\n" +
		`if exist "` + bat + `" start "Tinfoil Kit" /min "` + bat + `" --no-browser` + "\r\n"
}

func autostartFile() string {
	switch {
	case windows:
		return startupFile()
	case mac:
		return agentFile()
	}
	return unitFile()
}

type ran struct {
	rc             int
	stdout, stderr string
}

func runFor(env []string, name string, args ...string) ran {
	c := exec.Command(name, args...)
	c.Env = env
	var o, e bytes.Buffer
	c.Stdout, c.Stderr = &o, &e
	if err := c.Start(); err != nil {
		return ran{127, "", err.Error()}
	}
	done := make(chan error, 1)
	go func() { done <- c.Wait() }()
	select {
	case err := <-done:
		return ran{exitOf(err), o.String(), e.String()}
	case <-time.After(60 * time.Second):
		c.Process.Kill()
		<-done
		return ran{127, o.String(), "timed out"}
	}
}

// userEnv: systemctl --user finds your systemd through XDG_RUNTIME_DIR, which su and some SSH setups leave unset.
func userEnv() []string {
	env := os.Environ()
	runDir := fmt.Sprintf("/run/user/%d", os.Getuid())
	if os.Getenv("XDG_RUNTIME_DIR") == "" && isDir(runDir) {
		env = append(env, "XDG_RUNTIME_DIR="+runDir)
	}
	return env
}

func systemctl(args ...string) ran {
	return runFor(userEnv(), "systemctl", append([]string{"--user"}, args...)...)
}

func userName() string {
	for _, k := range []string{"LOGNAME", "USER", "LNAME", "USERNAME"} {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	if u, err := user.Current(); err == nil {
		return u.Username
	}
	return ""
}

func lingering() bool {
	return strings.Contains(runFor(nil, "loginctl", "show-user", userName(), "--property=Linger").stdout, "Linger=yes")
}

// linger lets your services run from boot, before anyone logs in. Without sudo where systemd allows it.
func linger() bool {
	for _, cmd := range [][]string{{"loginctl", "enable-linger"}, {"sudo", "-n", "loginctl", "enable-linger", userName()}} {
		if runFor(nil, cmd[0], cmd[1:]...).rc == 0 {
			for i := 0; i < 20; i++ { // systemd starts your services; wait for it to answer
				if exists(fmt.Sprintf("/run/user/%d/systemd/private", os.Getuid())) {
					break
				}
				time.Sleep(500 * time.Millisecond)
			}
			return true
		}
	}
	return false
}

// ours says whether an autostart entry starts this kit: with its launcher, or on a Mac or Linux with tools/launch.sh,
// the launcher kits had before this program (so moving a kit from before the three folders rewrites its entry).
func ours(text, root, code string) bool {
	if windows { // where names are the same in any case
		return strings.Contains(strings.ToLower(text), strings.ToLower(launcherFile(root, code)))
	}
	if code == "" {
		code = codeDir(root)
	}
	return strings.Contains(text, launcherFile(root, code)) || strings.Contains(text, filepath.Join(code, "tools", "launch.sh"))
}

// autostartState is "on", "off" or "other" (set up for a different kit folder, or for this one's code where it was
// before).
func autostartState(root, code string) string {
	data, err := os.ReadFile(autostartFile())
	if err != nil {
		return "off"
	}
	text := string(data)
	switch {
	case windows:
		text = strings.ReplaceAll(text, "%%", "%")
	case mac:
		text = html.UnescapeString(text) // a plist's &amp;
	default:
		text = strings.NewReplacer("%%", "%", "$$", "$", `\"`, `"`, `\\`, `\`).Replace(text)
	}
	if ours(text, root, code) {
		return "on"
	}
	return "other"
}

// autostart is ./kit autostart on|off|status, saying what it did to w. Returns the exit code.
func autostart(root, action string, w io.Writer) int {
	say := func(s string) { fmt.Fprintln(w, s) }
	if action == "status" {
		switch autostartState(root, "") {
		case "on":
			switch {
			case windows:
				say("The kit starts when you sign in to this PC.")
			case mac:
				say("The kit starts when this computer starts (once you log in).")
			case lingering():
				say("The kit starts when this computer starts.")
			default:
				say("The kit starts when this computer starts, once you log in (see " + kitCmd("autostart on") + " to start it before).")
			}
		case "other":
			say("Another kit folder starts with this computer (see " + autostartFile() + ").")
		default:
			say("The kit doesn't start by itself. " + kitCmd("autostart on") + " makes it start with this computer.")
		}
		return 0
	}
	if action == "off" {
		switch autostartState(root, "") {
		case "other":
			say("Starting with the computer is set up for another kit folder, so it's left as it is.")
			return 0
		case "off":
			say("The kit already doesn't start by itself.")
			return 0
		}
		switch {
		case windows: // which window is the one it started can't be told
			os.Remove(startupFile())
			say("The kit no longer starts when you sign in. If it's running, close its window to stop it.")
			return 0
		case mac:
			runFor(nil, "launchctl", "bootout", fmt.Sprintf("gui/%d/%s", os.Getuid(), agentName))
			os.Remove(agentFile())
		default:
			systemctl("disable", "--now", serviceName)
			os.Remove(unitFile())
			systemctl("daemon-reload")
		}
		say("The kit no longer starts by itself, and the copy it started has stopped.")
		return 0
	}
	os.MkdirAll(filepath.Join(shareData(root), "logs"), 0o755)
	switch {
	case windows:
		return startupOn(root, say)
	case mac:
		return launchdOn(root, say)
	}
	return systemdOn(root, say)
}

func systemdOn(root string, say func(string)) int {
	if !which("systemctl") {
		say("This computer has no systemd, so ./kit autostart can't set this up. Start the kit from your own\n" +
			"startup script instead:  bash " + launcherFile(root, "") + " --no-browser")
		return 1
	}
	f := unitFile()
	os.MkdirAll(filepath.Dir(f), 0o755)
	if err := os.WriteFile(f, []byte(systemdUnit(root)), 0o644); err != nil {
		say("Couldn't set up starting the kit with this computer: " + err.Error())
		return 1
	}
	lingers := lingering() || linger()
	if systemctl("daemon-reload").rc != 0 {
		say("Couldn't reach systemd for your user. That happens after su or sudo -i: log in as yourself (over\n" +
			"SSH is fine), or run  sudo loginctl enable-linger " + userName() + "  once, then try ./kit autostart on again.")
		return 1
	}
	r := systemctl("enable", serviceName)
	if r.rc == 0 {
		r = systemctl("restart", serviceName) // restart, so a changed kit folder or setting takes effect
	}
	if r.rc != 0 {
		why := strings.TrimSpace(r.stderr)
		if why == "" {
			why = strings.TrimSpace(r.stdout)
		}
		say("systemd wouldn't start the kit: " + why)
		return 1
	}
	say("The kit is starting now, and will start whenever this computer does.")
	if !lingers {
		say("For now it starts only once you log in. To start it at boot without logging in, run this once:\n" +
			"  sudo loginctl enable-linger " + userName())
	}
	say("Check on it: systemctl --user status " + strings.SplitN(serviceName, ".", 2)[0] + "   Logs: data/logs in the kit.")
	return 0
}

// plistEscape is how Python's plistlib writes a string.
func plistEscape(s string) string {
	s = strings.NewReplacer("\r\n", "\n", "\r", "\n").Replace(s)
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;").Replace(s)
}

func launchdOn(root string, say func(string)) int {
	f := agentFile()
	os.MkdirAll(filepath.Dir(f), 0o755)
	logPath := plistEscape(filepath.Join(shareData(root), "logs", "autostart.log"))
	plist := `<?xml version="1.0" encoding="UTF-8"?>` + "\n" +
		`<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">` + "\n" +
		`<plist version="1.0">` + "\n<dict>\n" +
		"\t<key>KeepAlive</key>\n\t<true/>\n" +
		"\t<key>Label</key>\n\t<string>" + agentName + "</string>\n" +
		"\t<key>ProgramArguments</key>\n\t<array>\n\t\t<string>/bin/bash</string>\n" +
		"\t\t<string>" + plistEscape(launcherFile(root, "")) + "</string>\n\t\t<string>--no-browser</string>\n\t</array>\n" +
		"\t<key>RunAtLoad</key>\n\t<true/>\n" +
		"\t<key>StandardErrorPath</key>\n\t<string>" + logPath + "</string>\n" +
		"\t<key>StandardOutPath</key>\n\t<string>" + logPath + "</string>\n" +
		"\t<key>ThrottleInterval</key>\n\t<integer>30</integer>\n" +
		"</dict>\n</plist>\n"
	if err := os.WriteFile(f, []byte(plist), 0o644); err != nil {
		say("Couldn't set up starting the kit with this computer: " + err.Error())
		return 1
	}
	domain := fmt.Sprintf("gui/%d", os.Getuid())
	runFor(nil, "launchctl", "bootout", domain+"/"+agentName) // a previous copy, so the new settings take effect
	if r := runFor(nil, "launchctl", "bootstrap", domain, f); r.rc != 0 {
		why := strings.TrimSpace(r.stderr)
		if why == "" {
			why = strings.TrimSpace(r.stdout)
		}
		say("macOS wouldn't start the kit: " + why + "\nLog in to this Mac's desktop (not just over SSH), then run ./kit " +
			"autostart on again.")
		return 1
	}
	say("The kit is starting now, and will start whenever you log in to this Mac.\n" +
		"For a Mac that's a home server, turn on automatic login: System Settings > Users & Groups.")
	if strings.HasPrefix(root, "/Volumes/") {
		say("The kit is on an external drive, and macOS may not let it start by itself from there. If it\n" +
			"doesn't, keep the kit on this Mac instead (SETUP's \"This Mac\").")
	}
	return 0
}

func startupOn(root string, say func(string)) int {
	f := startupFile()
	err := os.MkdirAll(filepath.Dir(f), 0o755)
	if err == nil {
		err = os.WriteFile(f, []byte(startupScript(root)), 0o644)
	}
	if err == nil {
		err = startNow(f)
	}
	if err != nil {
		say("Couldn't set up starting the kit when you sign in: " + err.Error())
		return 1
	}
	say("The kit is starting now, in a minimized window, and will start whenever you sign in to this PC.\n" +
		"For a home server, keep this PC plugged in and signed in (locking it is fine), and sign in again after a\n" +
		"restart.")
	return 0
}

// restartIfAutostarted restarts the kit when the computer started it, so a sharing change takes effect. True if it
// did. Not on Windows, where the window it started can't be told from one you opened.
func restartIfAutostarted(root string) bool {
	if windows || autostartState(root, "") != "on" {
		return false
	}
	if mac {
		return runFor(nil, "launchctl", "kickstart", "-k", fmt.Sprintf("gui/%d/%s", os.Getuid(), agentName)).rc == 0
	}
	return systemctl("try-restart", serviceName).rc == 0
}

func cmdShare(root string, a *cliArgs) {
	s := loadConfig(root).child("settings")
	port := int(intOr(s.getOr("share_port", 8000), 8000))
	on := isTrue(s.get("share_on_network"))
	action, code := a.str("action"), a.str("code")
	if a.has("code") && !validCode(code) {
		die("An access code needs 6 to 64 letters or digits.")
	}
	if action == "on" || action == "new-code" {
		acc, _ := loadAccess(root, true)
		if action == "new-code" || code != "" {
			acc.Code = newCode()
			if code != "" {
				acc.Code = cleanCode(code)
			}
			if err := saveAccess(root, acc); err != nil {
				die(oserr(err))
			}
		}
	}
	switch {
	case action == "off":
		setSetting(root, "share_on_network", false)
		log("Sharing is off: only this computer can open the kit.")
		if restartIfAutostarted(root) {
			log("The kit restarted without it.")
		} else {
			log("If the kit is running, close its window and start it again.")
		}
		return
	case action == "on" && on:
		log("Sharing is already on.")
	case action == "on":
		setSetting(root, "share_on_network", true)
		on = true
		log("Sharing is on: phones and laptops on your home network need the access code.")
		start := "Open Tinfoil Kit.command"
		if windows {
			start = "Open Tinfoil Kit for Windows.bat"
		}
		if restartIfAutostarted(root) {
			log("The kit restarted with sharing on.")
		} else {
			log("Start the kit to share it (" + start + "), or restart it if it's running.")
		}
	case action == "new-code":
		log("New access code. Phones and laptops that used the old one need this one now.")
	}
	if !on {
		log("Sharing is off: only this computer can open the kit. " + kitCmd("share on") + " lets phones and\n" +
			"laptops on your home network open it too, once they type an access code.")
		return
	}
	log("")
	if p := gatePort(port); p != 0 {
		port = p
	}
	log(banner(root, port, a.flag("qr") || isTerminal(os.Stdout)))
	if action == "" {
		log("")
		autostart(root, "status", os.Stdout)
	}
}

func cmdAutostart(root string, a *cliArgs) {
	action := a.str("action")
	if action == "" {
		action = "status"
	}
	rc := autostart(root, action, os.Stdout)
	if rc == 0 && action == "on" {
		if !isTrue(loadConfig(root).child("settings").get("share_on_network")) {
			log("Sharing is off, so only this computer can use the kit. " + kitCmd("share on") + " lets your phones and laptops in.")
		} else if windows { // the first time the program listens on the network
			me, _ := os.Executable()
			log("If Windows asks whether " + filepath.Base(me) + " may use the network, allow it, or phones and laptops can't\n" +
				"reach the kit.")
		}
	}
	exit(rc)
}

// ----------------------------------------------------------------------------- the kit's three folders

// oldCode: a kit from before app/, downloads/ and data/ had all of it at its top. Its code is these, and what
// ./kit update put there (state.json's kit_files); a copy of a git checkout has the rest of the repository too.
var oldCode = []string{"kit", "kit.cmd", "SETUP.command", "SETUP-Windows.bat", "UNINSTALL.command", "UNINSTALL-Windows.bat",
	"Open Tinfoil Kit.command", "Open Tinfoil Kit for Windows.bat", "GUIDE.md", "README.md", "THIRD-PARTY.md",
	"LICENSE", ".gitattributes", ".gitignore", ".claude", "tools", "site", "tests", "docs", "mac", ".github", "AGENTS.md",
	"CLAUDE.md", "package.json", "package-lock.json", "eslint.config.mjs"}

var downloaded = []string{"bin", "models", "library", "maps", "installers", "INVENTORY.md"}

// moveInto renames src to dst. A folder goes into the one already there, if there is one.
func moveInto(src, dst string) error {
	if isDir(src) && isDir(dst) {
		entries, err := os.ReadDir(src)
		if err != nil {
			return err
		}
		for _, e := range entries {
			if strings.HasPrefix(e.Name(), "._") { // a Mac's notes on a file on exFAT, which go with the file
				os.Remove(filepath.Join(src, e.Name()))
			} else if err := moveInto(filepath.Join(src, e.Name()), filepath.Join(dst, e.Name())); err != nil {
				return err
			}
		}
		os.Remove(src)
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	return os.Rename(src, dst)
}

// ensureLayout moves a kit from before the three folders into them, by renaming, so nothing downloads again: its code
// into app/ (a git checkout's stays where it is), what sync downloaded into downloads/, and its kit.json, logs and
// records into data/. A new app folder put into an old kit takes the old code's place. Only a kit that was set up (it
// has .kit) has downloads to move: in a fresh download, just the code moves, so folders of the person's beside it,
// like models, stay. Does nothing to a kit already laid out, and every command runs it first. Returns whether the code
// moved.
func ensureLayout(root string) bool {
	git, app, meta := exists(filepath.Join(root, ".git")), filepath.Join(root, "app"), metaDir(root)
	// its code at the top
	old := !git && isFile(filepath.Join(root, "kit")) && isDir(filepath.Join(root, "tools"))
	placed := isDir(filepath.Join(root, ".kit")) // (it moves last: while it's at the top, the move isn't finished)
	if !old && !placed {
		return false
	}
	if old && !isDir(app) && !samePath(codeRoot, root) {
		die("The kit at " + root + " is from an older version. Run its SETUP to update it first")
	}
	oldState := newObj()
	if data, err := os.ReadFile(filepath.Join(root, ".kit", "state.json")); err == nil {
		if o, err := parseObj(data); err == nil {
			oldState = o
		}
	}
	autostarted := old && autostartState(root, root) == "on"
	var got []string
	err := func() error {
		if old {
			std := filepath.Join(root, "site", "kit.json") // the standard list the top kit.json last took in
			if isFile(std) && !exists(filepath.Join(meta, "kit.base.json")) {
				text, err := os.ReadFile(std)
				if err != nil {
					return err
				}
				if err := saveText(filepath.Join(meta, "kit.base.json"), string(text)); err != nil {
					return err
				}
			}
			if isFile(filepath.Join(root, "kit.json")) && !exists(filepath.Join(dataDir(root), "kit.json")) {
				if err := moveInto(filepath.Join(root, "kit.json"), filepath.Join(dataDir(root), "kit.json")); err != nil {
					return err
				}
			}
			candidates := append([]string{}, oldCode...)
			for _, f := range oldState.list("kit_files") {
				if s, ok := f.(string); ok {
					candidates = append(candidates, strings.SplitN(s, "/", 2)[0])
				}
			}
			var names []string
			for _, n := range uniqueSorted(candidates) {
				if !contains(keepNames, n) && !contains([]string{"", "kit.json", "app", "downloads", "data"}, n) && exists(filepath.Join(root, n)) {
					names = append(names, n)
				}
			}
			var fresh, done []string
			for _, n := range names {
				if !exists(filepath.Join(app, n)) {
					fresh = append(fresh, n)
				}
			}
			made := !exists(app)
			os.Mkdir(app, 0o755)
			for _, n := range fresh {
				if err := os.Rename(filepath.Join(root, n), filepath.Join(app, n)); err != nil {
					for i := len(done) - 1; i >= 0; i-- { // all or nothing: the code keeps working where it is until this works
						os.Rename(filepath.Join(app, done[i]), filepath.Join(root, done[i]))
					}
					if made {
						os.Remove(app)
					}
					return err
				}
				done = append(done, n)
			}
			for _, n := range names { // older than the new version's own, in app/
				if !contains(fresh, n) {
					if err := os.RemoveAll(filepath.Join(root, n)); err != nil {
						return err
					}
				}
			}
			if !exists(filepath.Join(app, "kit.json")) { // the standard list, as in a release
				std := filepath.Join(app, "site", "kit.json")
				if !isFile(std) {
					std = filepath.Join(dataDir(root), "kit.json")
				}
				text, err := os.ReadFile(std)
				if err == nil {
					err = os.WriteFile(filepath.Join(app, "kit.json"), text, 0o644)
				}
				if err != nil {
					return err
				}
			}
		}
		dl := dlDir(root)
		for _, n := range downloaded {
			if placed && exists(filepath.Join(root, n)) {
				got = append(got, n)
			}
		}
		for _, n := range got {
			if err := moveInto(filepath.Join(root, n), filepath.Join(dl, n)); err != nil {
				return err
			}
		}
		if isDir(filepath.Join(root, ".kit", "downloads")) { // archives that were downloading
			if err := moveInto(filepath.Join(root, ".kit", "downloads"), filepath.Join(dl, ".partial")); err != nil {
				return err
			}
		}
		os.RemoveAll(filepath.Join(root, ".kit", "update"))
		for _, m := range [][2]string{{"logs", filepath.Join(dataDir(root), "logs")}, {".kit", meta}} {
			if placed && exists(filepath.Join(root, m[0])) {
				if err := moveInto(filepath.Join(root, m[0]), m[1]); err != nil {
					return err
				}
			}
		}
		if placed {
			os.MkdirAll(dl, 0o755) // what tells SETUP the kit has been set up
		}
		return nil
	}()
	if err != nil {
		die("Moving the kit into its app, downloads and data folders stopped partway (" + err.Error() + "). Nothing is lost. " +
			"Close the kit, and any window showing its files, then run SETUP again to finish")
	}
	if data, err := os.ReadFile(statePath(root)); err == nil {
		if state, err := parseObj(data); err == nil {
			parts := state.child("partials")
			stale := state.has("kit_files")
			for _, k := range parts.Keys() {
				stale = stale || strings.HasPrefix(k, ".kit/downloads/")
			}
			if stale {
				state.del("kit_files") // ./kit update replaces all of app/ now
				fresh := newObj()
				for _, k := range parts.Keys() {
					nk := k
					if strings.HasPrefix(k, ".kit/downloads/") {
						nk = ".partial/" + strings.TrimPrefix(k, ".kit/downloads/")
					}
					fresh.set(nk, parts.get(k))
				}
				state.set("partials", fresh)
				saveState(root, state)
			}
		}
	}
	if placed {
		var moved []string
		if old {
			moved = append(moved, "the kit's code into its app folder")
		}
		if len(got) > 0 {
			moved = append(moved, "what it downloaded into downloads")
		}
		if old {
			moved = append(moved, "your settings and its records into data")
		} else {
			moved = append(moved, "its records into data")
		}
		said := "Moved " + strings.Join(moved[:len(moved)-1], ", ")
		if len(moved) > 1 {
			said += " and "
		}
		said += moved[len(moved)-1] + "."
		if len(got) > 0 {
			said += " Nothing downloads again."
		}
		log(said)
	}
	if autostarted {
		if windows { // rewritten, not started: SETUP stopped the kit to move it, and goes on
			os.WriteFile(startupFile(), []byte(startupScript(root)), 0o644)
		} else {
			autostart(root, "on", io.Discard)
		}
		log("Starting with the computer runs it from the app folder now.")
	}
	return old
}

// cmdLayout: runKit has done it by now: this is SETUP's way to have it done, and nothing else.
func cmdLayout(root string, a *cliArgs) {}

// topFiles are what the kit keeps at the top of its folder, beside app, downloads and data: what a person opens
// first. No one file starts on a Mac, Windows and Linux alike (each goes by the file's ending to choose what a
// double-click does), so there's a launcher for each, which starts the one in app/, and Read me first.txt, which all
// of them open. cmd and Notepad get CRLF, and all of it is plain ASCII.
var topFiles = []struct{ name, text string }{
	{"Open Tinfoil Kit.command", `#!/bin/bash
# Double-click me (Mac) to start Tinfoil Kit. Linux: bash "Open Tinfoil Kit.command". Read me first.txt says more.
# The kit's program writes this file. It starts app/Open Tinfoil Kit.command, with the same options (--share...).
cd "$(dirname "$0")" || exit 1
if [ ! -f "app/Open Tinfoil Kit.command" ]; then
  echo "This kit has no app folder, so it can't start. Put the app folder of a new download of the kit"
  echo "(tinfoilkit.com) here, beside downloads and data."
  exit 1
fi
exec bash "app/Open Tinfoil Kit.command" "$@"
`},
	{"Open Tinfoil Kit for Windows.bat", crlf(`@echo off
rem Double-click me to start Tinfoil Kit. Read me first.txt says more. The kit's program writes this file. It
rem starts app\Open Tinfoil Kit for Windows.bat, with the same options (--share...).
if not exist "%~dp0app\Open Tinfoil Kit for Windows.bat" (
  echo This kit has no app folder, so it can't start. Put the app folder of a new download of the kit
  echo ^(tinfoilkit.com^) here, beside downloads and data.
  echo(
  set /p "_=Press Enter to close this window. "
  exit /b 1
)
"%~dp0app\Open Tinfoil Kit for Windows.bat" %*
`)},
	{"Read me first.txt", crlf(`Tinfoil Kit
===========

An AI, a library and maps that work without the internet, all in this
folder.


Start it
--------

Mac:      Double-click "Open Tinfoil Kit.command". If your Mac asks
          whether Terminal may use files on a removable volume, click
          Allow.
Windows:  Double-click "Open Tinfoil Kit for Windows".
Linux:    Open a terminal in this folder and type
          bash "Open Tinfoil Kit.command"

A window opens, then the kit's page in your web browser: Ask, AI chat,
Library, Map and Notes. No internet needed. Keep the window open while you
use the kit: closing it stops the kit. If the page doesn't open by itself,
type the address the window shows after "Open:" into your browser.

Windows and Linux are experimental for now: tested less than the Mac, so
expect rough edges.


What's in this folder
---------------------

app        The kit's programs. Don't change anything in it: a new version
           of the kit replaces it.
downloads  The AI, the books and the maps: most of the kit. Don't move or
           rename anything in it.
data       Your own: your notes, your map pins and your settings. Copy it
           somewhere safe to keep a spare.

Keep these three folders together, with their names. To move the kit, move
this whole folder.


Update it, or remove it
-----------------------

To get the newest AI, books and maps, or to change what's in the kit, while
you have internet: open app and double-click SETUP.command (SETUP-Windows
on Windows).

To remove the kit and everything it downloaded: open app and double-click
UNINSTALL.command (UNINSTALL-Windows on Windows).


If something doesn't work
-------------------------

The full guide is GUIDE.md, in the app folder. It opens in any text editor.
Print it while you have power, and keep it with the kit.
`)},
}

func crlf(s string) string { return strings.ReplaceAll(s, "\n", "\r\n") }

func isTopFile(name string) bool {
	for _, f := range topFiles {
		if f.name == name {
			return true
		}
	}
	return false
}

// ensureTop puts topFiles at the top of the kit folder once the kit is set up there (it has downloads/), and keeps
// them current. Only in a folder of the kit's own (alone, or called TinfoilKit) with the code in app/: a git checkout
// has its launchers at its top already, and a kit from before the three folders has its code there, which
// ensureLayout moves into app/, launchers and all. A file someone changed is theirs: data/.kit/top.json has the
// SHA-256 of what the kit last wrote, and only that is replaced. Every command but open runs it, when it's done.
func ensureTop(root string) {
	if samePath(appDir(root), root) || !isDir(appDir(root)) || !isDir(dlDir(root)) ||
		isFile(filepath.Join(root, "kit")) || isDir(filepath.Join(root, ".kit")) ||
		!(alone(root) || strings.EqualFold(filepath.Base(root), kitFolder)) {
		return
	}
	record := filepath.Join(metaDir(root), "top.json")
	wrote := newObj()
	if data, err := os.ReadFile(record); err == nil {
		if o, err := parseObj(data); err == nil {
			wrote = o
		}
	}
	hash := func(b []byte) string {
		sum := sha256.Sum256(b)
		return hex.EncodeToString(sum[:])
	}
	changed := false
	for _, f := range topFiles {
		p, want := filepath.Join(root, f.name), hash([]byte(f.text))
		if have, err := os.ReadFile(p); err == nil && hash(have) != wrote.str(f.name) {
			if hash(have) == want { // the kit's, from before this record
				wrote.set(f.name, want)
				changed = true
			}
			continue
		}
		if wrote.str(f.name) == want && isFile(p) {
			continue
		}
		mode := os.FileMode(0o644)
		if strings.HasSuffix(f.name, ".command") {
			mode = 0o755
		}
		tmp := filepath.Join(metaDir(root), "top.tmp") // (a write cut off leaves it there, not at the kit's top)
		os.MkdirAll(metaDir(root), 0o755)
		if os.WriteFile(tmp, []byte(f.text), mode) != nil {
			return // a drive that's read-only, or full: the kit works without these
		}
		os.Chmod(tmp, mode) // (exFAT has no modes: everything on it runs)
		if replace(tmp, p) != nil {
			os.Remove(tmp)
			return
		}
		wrote.set(f.name, want)
		changed = true
	}
	if changed {
		saveText(record, dumps(wrote, jsonStyle{indent: 2, sortKeys: true, ascii: true}))
	}
}

// diskUsage is diskSpace without the error: a disk that can't be read has no space.
func diskUsage(p string) (free, total int64) {
	free, total, _ = diskSpace(p)
	return free, total
}
