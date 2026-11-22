package main

// Downloading, checking and installing what the plan says the kit needs, and the kit page sync builds.

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/bzip2"
	"compress/gzip"
	"crypto/md5"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"hash"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// A big file comes over several connections at once, each fetching its own part of it. Servers and long routes cap
// what one connection gets, so that's often several times faster.
const connections = 8

var (
	partMin  = envInt("KIT_PART_MIN", 16*1024*1024) // the smallest part one connection fetches
	splitMin = 2 * partMin                          // anything smaller comes in one piece
	tailMin  = partMin / 4                          // near the end, the least an idle connection takes from another's part
)

const partMax = 512 * 1024 * 1024

func envInt(key string, def int64) int64 {
	if n, err := strconv.ParseInt(os.Getenv(key), 10, 64); err == nil && n > 0 {
		return n
	}
	return def
}

// partsRecord is where a download in parts notes which parts of the file have arrived, until it's whole.
func partsRecord(partial string) string { return partial + ".parts" }

// dropPartial deletes an unfinished download, along with any record of which parts of it had arrived (ours, or
// aria2c's).
func dropPartial(partial string) {
	for _, s := range []string{"", ".parts", ".parts.tmp", ".aria2"} {
		os.Remove(partial + s)
	}
}

func diskError(partial string) error {
	free := ""
	if f, _ := diskUsage(filepath.Dir(partial)); f > 0 {
		free = " (" + fmtBytes(f) + " free)"
	}
	return fmt.Errorf("couldn't save %s%s. Is the disk full, or was the drive unplugged?", filepath.Base(partial), free)
}

var (
	contentRange = regexp.MustCompile(`(?im)^content-range:\s*bytes 0-0/(\d+)`)
	partialReply = regexp.MustCompile(`^HTTP/\S+ 206`)
)

// exactSize is a file's exact size, from asking for its first byte: 0 when the server answers but won't send parts
// of the file, -1 when it can't be reached.
func exactSize(url string) int64 {
	args := []string{"-sSL", "--fail", "--connect-timeout", "20", "--max-time", "60", "--max-filesize", "100000",
		"-A", userAgent, "-r", "0-0", "-D", "-", "-o", os.DevNull}
	for _, h := range authHeaders(url) {
		args = append(args, "-H", h[0]+": "+h[1])
	}
	stdout, _, rc := output("curl", append(args, url)...)
	if rc == 63 { // it began sending the whole file
		return 0
	}
	blocks := headerBlocks(latin1(stdout))
	if rc != 0 || len(blocks) == 0 {
		return -1
	}
	last := blocks[len(blocks)-1]
	if m := contentRange.FindStringSubmatch(last); m != nil && partialReply.MatchString(last) {
		n, _ := strconv.ParseInt(m[1], 10, 64)
		return n
	}
	return 0
}

// at is l[i], or nil past its end.
func at(l []any, i int) any {
	if i < len(l) {
		return l[i]
	}
	return nil
}

func latin1(b []byte) string {
	r := make([]rune, len(b))
	for i, c := range b {
		r[i] = rune(c)
	}
	return string(r)
}

// part is a stretch of a file that one connection fetches: pos is the next byte it needs, end the one after its last.
type part struct{ pos, end int64 }

// downloadParts downloads url into partial over several connections, each fetching its own part of the file. What
// arrives is kept, with a record of which parts it was (<file>.parts), so a download that stops carries on from there,
// on the next try or the next sync. Returns how many bytes are still missing (0 once it's whole), and false when the
// server won't send parts.
func downloadParts(url, partial string, total int64, conns int) (int64, bool, error) {
	record := partsRecord(partial)
	tmp := record + ".tmp"
	have := fileSize(partial)
	done := [][2]int64{{0, have}} // what one connection got, from the start
	changed := false
	if exists(record) {
		done = nil // a record that can't be read: fetch it all again, over what's there
		data, err := os.ReadFile(record)
		rec, perr := parseObj(data)
		if err == nil && perr == nil && rec.has("size") {
			if !pyEqual(rec.get("size"), total) {
				changed = true
			} else {
				for _, r := range rec.list("done") {
					pair, ok := r.([]any)
					a, aerr := pyInt(at(pair, 0))
					b, berr := pyInt(at(pair, 1))
					if !ok || len(pair) != 2 || aerr != nil || berr != nil {
						done = nil
						break
					}
					done = append(done, [2]int64{a, min(b, have)})
				}
			}
		}
	}
	if changed || have > total { // of a file that has changed since
		dropPartial(partial)
		done, have = nil, 0
	}
	sort.Slice(done, func(a, b int) bool {
		if done[a][0] != done[b][0] {
			return done[a][0] < done[b][0]
		}
		return done[a][1] < done[b][1]
	})
	var missing [][2]int64
	upTo := int64(0)
	for _, r := range done {
		if r[0] >= r[1] {
			continue
		}
		if r[0] > upTo {
			missing = append(missing, [2]int64{upTo, r[0]})
		}
		upTo = max(upTo, r[1])
	}
	if upTo < total {
		missing = append(missing, [2]int64{upTo, total})
	}
	// Parts go out in order, so the file grows from the start: exFAT and NTFS fill a gap with zeros before writing past it.
	size := min(max(total/int64(conns*4), partMin), partMax)
	var todo []*part
	for _, m := range missing {
		for s := m[0]; s < m[1]; s += size {
			todo = append(todo, &part{s, min(s+size, m[1])})
		}
	}
	if len(todo) == 0 {
		os.Remove(record)
		return 0, true, nil
	}

	var (
		active    []*part
		procs     = map[*exec.Cmd]bool{}
		mu        sync.Mutex
		halt      = make(chan struct{})
		haltOnce  sync.Once
		fresh     int64
		ranges    = true
		diskErr   error
		chunk     = min(1024*1024, partMin)
		stopAll   = func() { haltOnce.Do(func() { close(halt) }) }
		isHalting = func() bool {
			select {
			case <-halt:
				return true
			default:
				return false
			}
		}
	)
	if err := os.MkdirAll(filepath.Dir(partial), 0o755); err != nil {
		return 0, true, diskError(partial)
	}
	fh, err := os.OpenFile(partial, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return 0, true, diskError(partial)
	}
	left := func() int64 {
		mu.Lock()
		defer mu.Unlock()
		var n int64
		for _, p := range append(append([]*part{}, todo...), active...) {
			n += p.end - p.pos
		}
		return n
	}
	// save notes which parts have arrived. What it notes is on the disk first, so the record never claims too much.
	save := func() error {
		mu.Lock()
		var gaps [][2]int64
		for _, p := range append(append([]*part{}, todo...), active...) {
			if p.pos < p.end {
				gaps = append(gaps, [2]int64{p.pos, p.end})
			}
		}
		mu.Unlock()
		sort.Slice(gaps, func(a, b int) bool {
			if gaps[a][0] != gaps[b][0] {
				return gaps[a][0] < gaps[b][0]
			}
			return gaps[a][1] < gaps[b][1]
		})
		if err := fh.Sync(); err != nil {
			return err
		}
		got, upTo := []any{}, int64(0)
		for _, g := range gaps {
			if g[0] > upTo {
				got = append(got, []any{upTo, g[0]})
			}
			upTo = max(upTo, g[1])
		}
		if upTo < total {
			got = append(got, []any{upTo, total})
		}
		f, err := os.Create(tmp)
		if err != nil {
			return err
		}
		if _, err := f.WriteString(dumpsLine(newObj("size", total, "done", got))); err != nil {
			f.Close()
			return err
		}
		if err := f.Sync(); err != nil {
			f.Close()
			return err
		}
		f.Close()
		return replace(tmp, record)
	}
	nextPart := func() *part {
		mu.Lock()
		defer mu.Unlock()
		if isHalting() {
			return nil
		}
		var p *part
		if len(todo) > 0 {
			p, todo = todo[0], todo[1:]
		} else { // near the end: take the second half of the part with the most left
			var big *part
			for _, q := range active {
				if big == nil || q.end-q.pos > big.end-big.pos {
					big = q
				}
			}
			if big == nil || big.end-big.pos < 2*tailMin {
				return nil
			}
			p = &part{big.pos + (big.end-big.pos)/2, big.end}
			big.end = p.pos
		}
		active = append(active, p)
		return p
	}
	removeActive := func(p *part) {
		for i, q := range active {
			if q == p {
				active = append(active[:i:i], active[i+1:]...)
				return
			}
		}
	}
	// fetchPart fetches what's left of p over one connection, and returns curl's exit code.
	fetchPart := func(p *part) int {
		mu.Lock()
		args := []string{"-sL", "--fail", "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", "60",
			"-A", userAgent, "-H", fmt.Sprintf("Range: bytes=%d-%d", p.pos, p.end-1)}
		if p.pos > 0 {
			args = append(args, "-C", strconv.FormatInt(p.pos, 10)) // then curl fails (exit 33) unless the server sends the file from there
		}
		mu.Unlock()
		for _, h := range authHeaders(url) {
			args = append(args, "-H", h[0]+": "+h[1])
		}
		cmd := exec.Command("curl", append(args, url)...)
		pipe, err := cmd.StdoutPipe()
		if err != nil {
			return -1
		}
		mu.Lock()
		if isHalting() {
			mu.Unlock()
			return -1
		}
		if err := cmd.Start(); err != nil {
			mu.Unlock()
			return -1
		}
		procs[cmd] = true
		mu.Unlock()
		buf := make([]byte, chunk)
		for !isHalting() {
			mu.Lock()
			want := p.end - p.pos
			mu.Unlock()
			if want <= 0 {
				break
			}
			n, err := pipe.Read(buf[:min(int64(len(buf)), want)])
			if n > 0 {
				mu.Lock()
				data := buf[:min(int64(n), max(0, p.end-p.pos))] // (its end moves when another takes half)
				if len(data) > 0 {
					w, werr := fh.WriteAt(data, p.pos)
					p.pos += int64(w)
					fresh += int64(w)
					if werr == nil && w < len(data) {
						werr = errors.New("nothing written")
					}
					if werr != nil {
						diskErr = werr
						stopAll()
					}
				}
				mu.Unlock()
			}
			if err != nil {
				break
			}
		}
		if cmd.ProcessState == nil {
			cmd.Process.Kill()
		}
		werr := cmd.Wait()
		mu.Lock()
		delete(procs, cmd)
		mu.Unlock()
		return exitOf(werr)
	}
	worker := func() {
		var p *part
		fails := 0
		for {
			if p == nil || func() bool { mu.Lock(); defer mu.Unlock(); return p.pos >= p.end }() {
				if p != nil {
					mu.Lock()
					removeActive(p)
					mu.Unlock()
				}
				if p = nextPart(); p == nil {
					return
				}
			}
			mu.Lock()
			before := p.pos
			mu.Unlock()
			rc := fetchPart(p)
			if isHalting() {
				return
			}
			if rc == 33 { // it sent something other than the part asked for
				mu.Lock()
				ranges = false
				mu.Unlock()
				stopAll()
				return
			}
			mu.Lock()
			pos, end := p.pos, p.end
			mu.Unlock()
			if pos < end {
				if pos > before {
					fails = 0
				} else {
					fails++
				}
				if fails == 5 { // hand the part to the others, if any are still going
					mu.Lock()
					removeActive(p)
					todo = append(todo, p)
					sort.SliceStable(todo, func(a, b int) bool { return todo[a].pos < todo[b].pos })
					mu.Unlock()
					return
				}
				select {
				case <-halt:
					return
				case <-time.After(time.Duration(1<<fails) * time.Second):
				}
			}
		}
	}

	tty, t0, width := isTerminal(os.Stderr), time.Now(), 0
	var wg sync.WaitGroup
	finished := false
	defer func() {
		stopAll() // after Ctrl-C too: stop every connection, and keep what arrived
		mu.Lock()
		for c := range procs {
			c.Process.Kill()
		}
		mu.Unlock()
		wg.Wait()
		addSpeed(fresh, time.Since(t0).Seconds())
		if tty && width > 0 {
			fmt.Fprint(os.Stderr, "\r"+strings.Repeat(" ", width)+"\r")
		}
		if gone := left(); gone > 0 {
			save()
		} else if fh.Sync() == nil { // the whole file is on the disk before its record goes
			os.Remove(record)
			os.Remove(tmp)
		}
		fh.Close()
		finished = true
	}()
	if err := save(); err != nil { // before anything arrives out of order: the file's length can't say what's missing then
		return 0, true, diskError(partial)
	}
	for i := 0; i < conns; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			worker()
		}()
	}
	allDone := make(chan struct{})
	go func() {
		wg.Wait()
		close(allDone)
	}()
	saved, shown := t0, t0
	type sample struct {
		t     time.Time
		bytes int64
	}
	speeds := []sample{{t0, 0}}
	tick := time.NewTicker(500 * time.Millisecond)
	defer tick.Stop()
loop:
	for {
		select {
		case <-allDone:
			break loop
		case <-stopping:
			panic(interrupted{})
		case <-tick.C:
		}
		now := time.Now()
		if now.Sub(saved) >= 5*time.Second {
			save() // a record that's behind only means fetching a part again
			saved = now
		}
		every := 60 * time.Second
		if tty {
			every = time.Second
		}
		if now.Sub(shown) >= every {
			mu.Lock()
			speeds = append(speeds, sample{now, fresh})
			mu.Unlock()
			for len(speeds) > 2 && now.Sub(speeds[1].t) >= 20*time.Second {
				speeds = speeds[1:]
			}
			rate := float64(speeds[len(speeds)-1].bytes-speeds[0].bytes) / max(now.Sub(speeds[0].t).Seconds(), 0.001)
			gone := left()
			msg := "    " + fmtBytes(total-gone) + " of " + fmtBytes(total)
			if rate > 0 && gone > 0 {
				msg += ", " + fmtSize(rate) + "/s, " + fmtTime(float64(gone)/rate) + " left"
			}
			if tty {
				fmt.Fprint(os.Stderr, "\r"+padRight(msg, width))
				width = max(width, len([]rune(msg)))
			} else {
				log(msg)
			}
			shown = now
		}
	}
	stopAll()
	mu.Lock()
	for c := range procs {
		c.Process.Kill()
	}
	mu.Unlock()
	wg.Wait()
	_ = finished
	gone := left()
	mu.Lock()
	derr, ok := diskErr, ranges
	mu.Unlock()
	if derr != nil {
		return gone, ok, diskError(partial)
	}
	return gone, ok, nil
}

// keepPrefix turns a download in parts into one a single connection can carry on: keep what arrived from the start
// without a gap, and drop the record.
func keepPrefix(partial string) {
	record := partsRecord(partial)
	keep := int64(0)
	if data, err := os.ReadFile(record); err == nil {
		if rec, err := parseObj(data); err == nil {
			if done := rec.list("done"); len(done) > 0 {
				if pair, ok := done[0].([]any); ok && len(pair) == 2 && intOr(pair[0], -1) == 0 {
					keep = intOr(pair[1], 0)
				}
			}
		}
	}
	if exists(partial) && fileSize(partial) > keep {
		os.Truncate(partial, keep)
	}
	os.Remove(record)
}

func download(url, partial string, size int64, downloader string) error {
	os.MkdirAll(filepath.Dir(partial), 0o755)
	record, aria := partsRecord(partial), partial+".aria2"
	if size > 0 && exists(partial) && fileSize(partial) > size {
		dropPartial(partial)
	}
	// A download fetched in several places at once (ours, or aria2c's) can be full length with gaps in it. Its record
	// (<file>.parts, <file>.aria2) is there until the download is whole.
	if size > 0 && exists(partial) && fileSize(partial) == size && !exists(record) && !exists(aria) {
		return nil
	}
	useAria := downloader == "aria2c" || (downloader == "auto" && exists(aria) && which("aria2c"))
	if exists(aria) && !useAria {
		dropPartial(partial) // aria2c's, with gaps only it knows
	}
	planned := size
	if planned == 0 {
		planned = splitMin
	}
	if downloader == "auto" && !useAria && (exists(record) || planned >= splitMin) {
		tries, best := 0, int64(-1)
		for {
			total := exactSize(url)
			var where string
			if total < 0 && exists(record) { // not reachable just now: try again, keeping what arrived
				where = "can't reach the server"
			} else if total <= 0 || total < splitMin || (size > 0 && !(size-total >= 0 && size-total < 1024)) {
				break // in one piece: a small file, a server that won't send parts, or not the file we were told of
			} else { // (Kiwix lists sizes rounded up to a whole KiB)
				left, ranges, err := downloadParts(url, partial, total, connections)
				if err != nil {
					return err
				}
				if ranges && left == 0 {
					return nil
				}
				if !ranges {
					break // it won't send parts after all
				}
				if best < 0 || left < best {
					tries, best = 0, left
				}
				where = fmtBytes(total-left) + " of " + fmtBytes(total)
			}
			tries++
			if tries == 5 {
				return fmt.Errorf("download failed after 5 attempts: %s", url)
			}
			log(fmt.Sprintf("    download interrupted (%s); retrying (%d/5)...", where, tries))
			sleep(10 * time.Second)
		}
	}
	if exists(record) {
		keepPrefix(partial)
	}
	for attempt := 1; attempt <= 5; attempt++ {
		before := fileSize(partial)
		status, t0 := "", time.Now()
		var rc int
		if useAria {
			args := []string{"-c", "-x", "8", "-s", "8", "-k", "8M", "--file-allocation=none", "--auto-file-renaming=false",
				"--allow-overwrite=true", "--summary-interval=0", "--console-log-level=warn", "--max-tries=10", "--retry-wait=5",
				"--user-agent=" + userAgent, "-d", filepath.Dir(partial), "-o", filepath.Base(partial)}
			for _, h := range authHeaders(url) {
				args = append(args, "--header="+h[0]+": "+h[1])
			}
			cmd := exec.Command("aria2c", append(args, url)...)
			cmd.Stdout, cmd.Stderr = os.Stdout, os.Stderr
			rc = exitOf(run(cmd))
		} else {
			args := []string{"-L", "--fail", "--retry", "10", "--retry-delay", "5", "--connect-timeout", "30", "-A", userAgent,
				"-C", "-", "-o", partial, "-w", "%{http_code}"}
			if curlSupports("--retry-all-errors") {
				args = append(args, "--retry-all-errors")
			}
			for _, h := range authHeaders(url) {
				args = append(args, "-H", h[0]+": "+h[1])
			}
			var o bytes.Buffer
			cmd := exec.Command("curl", append(args, url)...)
			cmd.Stdout, cmd.Stderr = &o, os.Stderr // progress still shows (stderr)
			rc = exitOf(run(cmd))
			s := strings.TrimSpace(o.String())
			status = s[max(0, len(s)-3):]
		}
		got := fileSize(partial)
		if got > before {
			addSpeed(got-before, time.Since(t0).Seconds())
		}
		if rc == 0 && (size == 0 || got == size) {
			return nil
		}
		// Finished, but a hair short of the size we were given: one rounded up to a whole KiB, as Kiwix's catalog does.
		// Once asking again adds nothing (the server says it has no more), or on the last try, take it: its checksum
		// decides.
		if rc == 0 && size-got > 0 && size-got < 1024 {
			if got == before || attempt == 5 {
				return nil
			}
			continue
		}
		if (useAria && rc == 9) || (!useAria && rc == 23) { // retrying won't help
			return diskError(partial)
		}
		restart := !useAria && (rc == 33 || status == "416") // it can't carry on this partial file: start over
		if restart {
			dropPartial(partial)
		}
		log(fmt.Sprintf("    download interrupted (exit %d, %s of %s); retrying (%d/5)...", rc, fmtBytes(got), fmtSizeOr(size), attempt))
		if !restart {
			if got > before {
				sleep(10 * time.Second)
			} else {
				sleep(30 * time.Second)
			}
		}
	}
	return fmt.Errorf("download failed after 5 attempts: %s", url)
}

func newHash(algo string) hash.Hash {
	switch algo {
	case "md5":
		return md5.New()
	case "sha1":
		return sha1.New()
	case "sha512":
		return sha512.New()
	}
	return sha256.New()
}

// hashFile computes several digests in one pass over the file.
func hashFile(p string, algos []string, label string) (map[string]string, error) {
	hs := map[string]hash.Hash{"sha256": sha256.New()}
	for _, a := range algos {
		if hs[a] == nil {
			hs[a] = newHash(a)
		}
	}
	f, err := os.Open(p)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	st, _ := f.Stat()
	total := st.Size()
	if label == "" {
		label = filepath.Base(p)
	}
	tty := isTerminal(os.Stdout)
	var done int64
	last := time.Now()
	buf := make([]byte, 8*1024*1024)
	for {
		checkStop()
		n, err := f.Read(buf)
		if n > 0 {
			for _, h := range hs {
				h.Write(buf[:n])
			}
			done += int64(n)
			if total > 2*GB && time.Since(last) > 3*time.Second && tty {
				out(fmt.Sprintf("    verifying %s: %d%%\r", label, done*100/total))
				last = time.Now()
			}
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	if total > 2*GB && tty {
		out(strings.Repeat(" ", 70) + "\r")
	}
	sums := map[string]string{}
	for a, h := range hs {
		sums[a] = hex.EncodeToString(h.Sum(nil))
	}
	return sums, nil
}

func sha256File(p string) (string, error) {
	s, err := hashFile(p, []string{"sha256"}, "")
	if err != nil {
		return "", err
	}
	return s["sha256"], nil
}

var md5RE = regexp.MustCompile(`\b([0-9a-fA-F]{32})\b`)

// expectedDigests is every published checksum we can find for this file (may be empty), in the order they're checked.
func expectedDigests(f *remoteFile) [][2]string {
	var exp [][2]string
	set := func(algo, v string) {
		for i := range exp {
			if exp[i][0] == algo {
				exp[i][1] = v
				return
			}
		}
		exp = append(exp, [2]string{algo, v})
	}
	for _, c := range f.checks {
		if c[1] != "" {
			set(c[0], strings.ToLower(c[1]))
		}
	}
	if f.sha256 != "" {
		set("sha256", strings.ToLower(f.sha256))
	} else if f.sha256Sidecar {
		if got := fetchSHA256Sidecar(f.url); got != "" {
			set("sha256", got)
		}
	}
	has := func(algo string) bool {
		for _, e := range exp {
			if e[0] == algo {
				return true
			}
		}
		return false
	}
	if f.md5Sidecar && !has("md5") {
		if data, err := httpGet(f.url+".md5", 60, ""); err == nil {
			if m := md5RE.FindStringSubmatch(strings.ToValidUTF8(string(data), "�")); m != nil {
				set("md5", strings.ToLower(m[1]))
			}
		}
	}
	return exp
}

func algosOf(exp [][2]string) []string {
	var l []string
	for _, e := range exp {
		l = append(l, e[0])
	}
	return l
}

// verifyDownload checks a downloaded file against its published checksums, and returns its SHA-256.
func verifyDownload(p string, f *remoteFile, expected [][2]string) (string, error) {
	got, err := hashFile(p, algosOf(expected), f.name)
	if err != nil {
		return "", err
	}
	for _, e := range expected {
		if got[e[0]] != e[1] {
			os.Remove(p)
			return "", fmt.Errorf("%s failed its %s checksum (corrupt download); deleted it, run sync again", f.name, e[0])
		}
	}
	return got["sha256"], nil
}

// relDL is a path within downloads/, as state.json spells it.
func relDL(root, p string) string {
	rel, err := filepath.Rel(dlDir(root), p)
	if err != nil {
		return filepath.ToSlash(p)
	}
	return filepath.ToSlash(rel)
}

// fetchFile downloads f into its partial file and returns that path. An interrupted download resumes, unless it was
// of an older version under the same name. room: how many times its size must fit.
func fetchFile(root string, state *obj, it *item, f *remoteFile, cfg *obj, force bool, room int64, label string) (string, error) {
	partial := it.partial(root, f)
	rel := relDL(root, partial)
	size := f.size
	if size == 0 && f.estimate > 0 {
		size = headSize(f.url) // exactly, where the plan had a rough size
	}
	tag := f.sha256
	if tag == "" {
		n := f.size
		if n == 0 {
			n = f.estimate
		}
		tag = it.version + "|"
		if n > 0 {
			tag += strconv.FormatInt(n, 10)
		}
	}
	partials := state.child("partials")
	if partials == nil {
		partials = newObj()
		state.set("partials", partials)
	}
	if exists(partial) {
		was := tag
		if rec := partials.child(rel); rec != nil && rec.has("tag") {
			was = pyStr(rec.get("tag"))
		}
		if was != tag || (size > 0 && fileSize(partial) > size) {
			log("    discarding an unfinished download of a different version of " + f.name)
			dropPartial(partial)
		}
	}
	have := fileSize(partial)
	want := size
	if want == 0 {
		want = f.estimate
	}
	needed := max(0, want*room-have)
	if label == "" {
		label = f.name
	}
	if !force && !ensureSpace(root, needed, cfg) {
		return "", fmt.Errorf("not enough free space for %s (needs about %s more, and the kit keeps %s free); make room "+
			"or switch it off in kit.json", label, fmtBytes(needed), fmtSize(keepFree(root, cfg)))
	}
	partials.set(rel, newObj("item", it.key(), "tag", tag))
	saveState(root, state)
	resume := ""
	if have > 0 {
		resume = ", resuming at " + fmtBytes(have)
	}
	log(fmt.Sprintf("    downloading %s (%s)%s", label, fmtSizeOr(want), resume))
	return partial, download(f.url, partial, size, pyStr(cfg.child("settings").getOr("downloader", "auto")))
}

func forgetPartial(root string, state *obj, partial string) {
	state.child("partials").del(relDL(root, partial))
}

// sweepPartials deletes unfinished downloads that a newer version has made useless (they can be 100 GB). Kept: the
// ones this sync resumes, and those of items switched off or not found this time.
func sweepPartials(root string, state *obj, items []*item) {
	keep, current, known := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, i := range items {
		known[i.key()] = true
		if i.enabled() && i.err == "" {
			current[i.key()] = true
			for _, f := range i.need {
				keep[relDL(root, i.partial(root, f))] = true
			}
		}
	}
	partials := state.child("partials")
	for _, rel := range partials.Keys() {
		p := filepath.Join(dlDir(root), filepath.FromSlash(rel))
		owner := pyStr(partials.child(rel).get("item"))
		if exists(p) && !keep[rel] && (current[owner] || !known[owner]) {
			dropPartial(p)
			log("Removed an unfinished download that's out of date: " + rel)
		}
		if !exists(p) {
			partials.del(rel)
		}
	}
}

// dropReplacedWikipedias: a Wikipedia in a language or size ./kit region switched away from (up to 130 GB) goes once
// kit.json's are in, and so does a smaller one that stood in for them (wikiStandIns). items: this sync's plan.
func dropReplacedWikipedias(root string, state *obj, items []*item, cfg *obj) {
	var listed, wanted []*item
	for _, i := range itemsFromConfig(cfg) {
		if i.section == "library" && wikipediaRE.MatchString(i.id) {
			listed = append(listed, i)
			if i.enabled() {
				wanted = append(wanted, i)
			}
		}
	}
	all := stateItems(state)
	if len(wanted) == 0 {
		return
	}
	for _, i := range wanted {
		if !all.child(i.key()).has("files") {
			return
		}
	}
	keep := map[string]bool{}
	for _, i := range listed {
		keep[i.key()] = true
	}
	for _, i := range items {
		if i.enabled() {
			keep[i.key()] = true
		}
	}
	var names []string
	for _, i := range wanted {
		names = append(names, i.id)
	}
	for _, key := range all.Keys() {
		section, ident, _ := strings.Cut(key, "/")
		v := all.child(key)
		if section == "library" && wikipediaRE.MatchString(ident) && !keep[key] && v.has("files") {
			for _, name := range v.child("files").Keys() {
				os.Remove(filepath.Join(dlDir(root), filepath.FromSlash(pyStr(v.get("dest"))), name))
			}
			all.del(key)
			log(fmt.Sprintf("Removed %s: kit.json has %s instead.", ident, strings.Join(names, ", ")))
		}
	}
}

// matches is the SHA-256 of a file already in the kit if it's exactly f (same size and published checksums).
func matches(p string, f *remoteFile, expected [][2]string) string {
	if len(expected) == 0 || !isFile(p) || (f.size > 0 && fileSize(p) != f.size) {
		return ""
	}
	log("    found " + filepath.Base(p) + " already here, checking it...")
	got, err := hashFile(p, algosOf(expected), "")
	if err != nil {
		return ""
	}
	for _, e := range expected {
		if got[e[0]] != e[1] {
			return ""
		}
	}
	return got["sha256"]
}

// adopt is f, if the kit has it in another folder of the same kind, say under an item an older version of the kit
// called something else: moved here rather than downloaded again. Returns its SHA-256.
func adopt(root string, state *obj, it *item, f *remoteFile, final string, expected [][2]string, cfg *obj) string {
	top := filepath.Join(dlDir(root), strings.SplitN(it.dest, "/", 2)[0])
	if len(expected) == 0 || !isDir(top) {
		return ""
	}
	// (other items' folders, as ./kit has always listed them: the downloads folder itself)
	theirs := map[string]bool{}
	for _, i := range itemsFromConfig(cfg) {
		if i.enabled() && i.key() != it.key() {
			theirs[resolvePath(dlDir(root))] = true
		}
	}
	candidates := []string{filepath.Join(top, f.name)}
	entries, _ := os.ReadDir(top)
	var dirs []string
	for _, e := range entries {
		if isDir(filepath.Join(top, e.Name())) {
			dirs = append(dirs, filepath.Join(top, e.Name()))
		}
	}
	sortPaths(dirs)
	for _, d := range dirs {
		candidates = append(candidates, filepath.Join(d, f.name))
	}
	for _, p := range candidates {
		if p == final || !isFile(p) || theirs[resolvePath(filepath.Dir(p))] {
			continue
		}
		got := matches(p, f, expected)
		if got == "" {
			continue
		}
		if replace(p, final) != nil { // open in the kit, on Windows: download it instead
			continue
		}
		all := stateItems(state)
		for _, key := range all.Keys() {
			v := all.child(key)
			files := v.child("files")
			if filepath.Join(dlDir(root), filepath.FromSlash(pyStr(v.getOr("dest", "")))) == filepath.Dir(p) && files.has(filepath.Base(p)) {
				files.del(filepath.Base(p))
				if files.size() == 0 {
					all.del(key)
				}
			}
		}
		os.Remove(filepath.Dir(p)) // (once it's empty)
		log("    moved it here from " + relDL(root, filepath.Dir(p)) + ", rather than downloading it again")
		return got
	}
	return ""
}

func installFiles(root string, it *item, state, cfg *obj, force bool) (int64, error) {
	dest := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
	if err := os.MkdirAll(dest, 0o755); err != nil {
		return 0, err
	}
	old := stateItems(state).child(it.key())
	oldFiles := cloneObj(old.child("files"))
	newFiles := newObj()
	var downloaded int64
	for _, f := range it.files {
		final := filepath.Join(dest, f.name)
		if !it.needs(f) {
			newFiles.set(f.name, oldFiles.get(f.name))
			continue
		}
		expected := expectedDigests(f)
		// already here (copied by hand, state lost, or a sync stopped before saving), or somewhere else in the kit:
		// keep it if it checks out
		have := matches(final, f, expected)
		if have == "" {
			have = adopt(root, state, it, f, final, expected, cfg)
		}
		if have != "" {
			newFiles.set(f.name, newObj("size", fileSize(final), "sha256", have, "verified", true))
			continue
		}
		partial, err := fetchFile(root, state, it, f, cfg, force, 1, "")
		if err != nil {
			return downloaded, err
		}
		got, err := verifyDownload(partial, f, expected)
		if err != nil {
			return downloaded, err
		}
		if err := replace(partial, final); err != nil {
			return downloaded, err
		}
		forgetPartial(root, state, partial)
		downloaded += fileSize(final)
		newFiles.set(f.name, newObj("size", fileSize(final), "sha256", got, "verified", len(expected) > 0))
		note := ""
		if len(expected) == 0 {
			note = " (no published checksum to compare; recorded ours)"
		}
		log("    ok: " + f.name + note)
	}
	for _, name := range oldFiles.Keys() {
		if !newFiles.has(name) {
			os.Remove(filepath.Join(dest, name))
			log("    removed old version: " + name)
		}
	}
	stateItems(state).set(it.key(), newObj("version", it.version, "dest", it.dest, "files", newFiles,
		"updated", nowISO(), "note", it.note()))
	return downloaded, nil
}

// inside is where an archive member goes, refusing names that would land outside dest (downloads are untrusted).
func inside(dest, name string) (string, error) {
	var parts []string
	for _, p := range strings.Split(strings.ReplaceAll(name, `\`, "/"), "/") {
		if p != "" && p != "." {
			parts = append(parts, p)
		}
	}
	if len(parts) == 0 || strings.HasPrefix(name, "/") || strings.HasPrefix(name, `\`) || contains(parts, "..") ||
		strings.Contains(parts[0], ":") {
		return "", fmt.Errorf("the archive has an unexpected path in it: %s", name)
	}
	return filepath.Join(append([]string{dest}, parts...)...), nil
}

// linkTarget is where a link in an archive points, if that's inside the archive: links can't go on exFAT, so they're
// copied.
func linkTarget(dest, link, target string) string {
	if target == "" || strings.HasPrefix(target, "/") || strings.HasPrefix(target, `\`) || strings.Contains(target, ":") {
		return ""
	}
	p := filepath.Clean(filepath.Join(filepath.Dir(link), filepath.FromSlash(strings.ReplaceAll(target, `\`, "/"))))
	if p != link && (p == dest || strings.HasPrefix(p, dest+string(filepath.Separator))) {
		return p
	}
	return ""
}

type linkCopy struct{ link, target string }

// copyLinks makes each link a copy of what it points at. Links to files go first, a link to a link once that's
// copied, and links to folders last, so a copied folder has its links too.
func copyLinks(links []linkCopy) error {
	for len(links) > 0 {
		var ready []linkCopy
		for _, l := range links {
			if isFile(l.target) {
				ready = append(ready, l)
			}
		}
		if len(ready) == 0 {
			for _, l := range links {
				if isDir(l.target) {
					ready = append(ready, l)
				}
			}
		}
		if len(ready) == 0 {
			return nil // the rest point at nothing in the archive
		}
		for _, l := range ready {
			os.MkdirAll(filepath.Dir(l.link), 0o755)
			if isFile(l.target) {
				if err := copyFileMode(l.target, l.link); err != nil {
					return err
				}
			} else if !strings.HasPrefix(l.link, l.target+string(filepath.Separator)) { // a link to a folder it's in would copy itself forever
				if err := copyTree(l.target, l.link); err != nil {
					return err
				}
			}
		}
		var rest []linkCopy
		for _, l := range links {
			if !contains(ready, l) {
				rest = append(rest, l)
			}
		}
		links = rest
	}
	return nil
}

// copyFileMode copies a file's contents and permissions (shutil.copy).
func copyFileMode(src, dst string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	st, err := in.Stat()
	if err != nil {
		return err
	}
	o, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
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
	os.Chmod(dst, st.Mode().Perm())
	return nil
}

// copyTree copies a folder into dst, adding to what's there.
func copyTree(src, dst string) error {
	return filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		to := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(to, 0o755)
		}
		return copyFileMode(p, to)
	})
}

func writeMember(p string, r io.Reader, mode fs.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	f, err := os.OpenFile(p, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	buf := make([]byte, 1<<20)
	for {
		checkStop()
		n, rerr := r.Read(buf)
		if n > 0 {
			if _, err := f.Write(buf[:n]); err != nil {
				f.Close()
				return err
			}
		}
		if rerr == io.EOF {
			break
		}
		if rerr != nil {
			f.Close()
			return rerr
		}
	}
	if err := f.Close(); err != nil {
		return err
	}
	if mode&0o111 != 0 {
		os.Chmod(p, 0o755)
	}
	return nil
}

// unzipTo extracts a zip archive. Links become copies.
func unzipTo(archive, dest string) error {
	z, err := zip.OpenReader(archive)
	if err != nil {
		return err
	}
	defer z.Close()
	var links []linkCopy
	for _, f := range z.File {
		p, err := inside(dest, f.Name)
		if err != nil {
			if strings.Trim(f.Name, "./") == "" && f.FileInfo().IsDir() {
				continue
			}
			return err
		}
		mode := f.Mode()
		switch {
		case mode&fs.ModeSymlink != 0:
			r, err := f.Open()
			if err != nil {
				return err
			}
			target, _ := io.ReadAll(io.LimitReader(r, 4096))
			r.Close()
			if t := linkTarget(dest, p, strings.ToValidUTF8(string(target), "�")); t != "" {
				links = append(links, linkCopy{p, t})
			}
		case f.FileInfo().IsDir() || strings.HasSuffix(f.Name, "/"):
			if err := os.MkdirAll(p, 0o755); err != nil {
				return err
			}
		default:
			r, err := f.Open()
			if err != nil {
				return err
			}
			err = writeMember(p, r, mode)
			r.Close()
			if err != nil {
				return err
			}
		}
	}
	return copyLinks(links)
}

// untarTo extracts a tar archive, read as a stream, front to back, since the Photon database is tens of GB. Links
// become copies (a Mac's or Linux PC's programs have some, set up from Windows onto a drive).
func untarTo(archive, dest, compression string) error {
	f, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer f.Close()
	var raw io.Reader
	if compression == "bz2" {
		raw = bzip2.NewReader(f)
	} else {
		gz, err := gzip.NewReader(f)
		if err != nil {
			return err
		}
		defer gz.Close()
		raw = gz
	}
	tr := tar.NewReader(raw)
	var links []linkCopy
	for {
		h, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
		switch h.Typeflag {
		case tar.TypeDir, tar.TypeReg, tar.TypeRegA, tar.TypeSymlink, tar.TypeLink, tar.TypeGNUSparse, tar.TypeCont:
		default:
			continue // pax headers and the like, which aren't files
		}
		p, err := inside(dest, h.Name)
		if err != nil {
			if strings.Trim(h.Name, "./") == "" && h.Typeflag == tar.TypeDir {
				continue
			}
			return err
		}
		switch h.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(p, 0o755); err != nil {
				return err
			}
		case tar.TypeSymlink:
			if t := linkTarget(dest, p, h.Linkname); t != "" {
				links = append(links, linkCopy{p, t})
			}
		case tar.TypeLink:
			t, err := inside(dest, h.Linkname)
			if err != nil {
				return err
			}
			links = append(links, linkCopy{p, t})
		default:
			if err := writeMember(p, tr, fs.FileMode(h.Mode)); err != nil {
				return err
			}
		}
	}
	return copyLinks(links)
}

// extractArchive unpacks an archive into target, with links made copies: exFAT drives (readable by Windows and Linux
// too) can't store links.
func extractArchive(archive, name, target string) error {
	staging := target + ".partial"
	os.RemoveAll(staging)
	if err := os.MkdirAll(staging, 0o755); err != nil {
		return err
	}
	var err error
	if strings.HasSuffix(name, ".zip") {
		err = unzipTo(archive, staging)
	} else {
		err = untarTo(archive, staging, "gz")
	}
	if err != nil {
		os.RemoveAll(staging)
		return fmt.Errorf("could not extract %s: %s", name, errText(err))
	}
	os.RemoveAll(target)
	return replace(staging, target)
}

// pySuffix is a file name's extension as Python's Path.suffix has it ("" for a name like .hidden).
func pySuffix(name string) string {
	i := strings.LastIndexByte(name, '.')
	if i <= 0 || i == len(name)-1 {
		return ""
	}
	return name[i:]
}

func installArchive(root string, it *item, state, cfg *obj, force bool) (int64, error) {
	f := it.files[0]
	expected := expectedDigests(f)
	partial, err := fetchFile(root, state, it, f, cfg, force, 3, "")
	if err != nil {
		return 0, err
	}
	got, err := verifyDownload(partial, f, expected)
	if err != nil {
		return 0, err
	}
	base := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
	target := filepath.Join(base, safeName(it.version))
	if err := extractArchive(partial, f.name, target); err != nil {
		return 0, err
	}
	binName := pyStr(orEmpty(it.cfg.get("binary")))
	binary := findBinary(target, binName)
	if binName != "" && binary == "" {
		os.RemoveAll(target)
		return 0, fmt.Errorf("%s not found inside %s; the release layout changed", binName, f.name)
	}
	if binary != "" && !strings.HasSuffix(filepath.Base(binary), ".exe") {
		entries, _ := os.ReadDir(filepath.Dir(binary))
		for _, e := range entries {
			p := filepath.Join(filepath.Dir(binary), e.Name())
			if isFile(p) && pySuffix(e.Name()) == "" {
				if st, err := os.Stat(p); err == nil {
					os.Chmod(p, st.Mode().Perm()|0o111)
				}
			}
		}
	}
	if mac {
		output("xattr", "-dr", "com.apple.quarantine", target)
	}
	os.WriteFile(filepath.Join(base, "CURRENT"), []byte(safeName(it.version)+"\n"), 0o644)
	old := stateItems(state).child(it.key())
	var versions []any
	for _, v := range old.list("versions") {
		if !pyEqual(v, it.version) && isDir(filepath.Join(base, safeName(pyStr(v)))) {
			versions = append(versions, v)
		}
	}
	keep := int(intOr(cfg.child("settings").getOr("keep_previous_runtime_versions", 1), 1))
	keep = max(0, min(keep, len(versions)))
	for _, v := range versions[keep:] {
		os.RemoveAll(filepath.Join(base, safeName(pyStr(v))))
		log("    removed old version: " + pyStr(v))
	}
	os.Remove(partial)
	forgetPartial(root, state, partial)
	shown := target
	if binary != "" {
		shown = binary
	}
	log("    ok: " + relDL(root, shown))
	var bin any
	if binary != "" {
		bin = relDL(root, binary)
	}
	stateItems(state).set(it.key(), newObj("version", it.version, "current", it.version,
		"versions", append([]any{it.version}, versions[:keep]...), "dest", it.dest, "archive", f.name,
		"archive_sha256", got, "verified", len(expected) > 0, "binary", bin, "updated", nowISO(), "note", it.note()))
	return f.size, nil
}

// ----------------------------------------------------------------------------- maps installers

// dropFinderFiles: macOS keeps Finder metadata for files on exFAT drives in "._name" files beside them. The servers
// scan library/ and models/ and could take ._name.zim or ._name.gguf for a book or a model, and git warns about the
// ones in a checkout's .git.
func dropFinderFiles(root string) {
	dl := dlDir(root)
	if entries, err := os.ReadDir(filepath.Join(dl, "library")); err == nil {
		for _, e := range entries {
			if strings.HasPrefix(e.Name(), "._") && e.Type().IsRegular() {
				os.Remove(filepath.Join(dl, "library", e.Name()))
			}
		}
	}
	for _, top := range []string{filepath.Join(dl, "models"), filepath.Join(root, ".git")} {
		filepath.WalkDir(top, func(p string, d fs.DirEntry, err error) error {
			if err == nil && strings.HasPrefix(d.Name(), "._") && d.Type().IsRegular() {
				os.Remove(p)
			}
			return nil
		})
	}
}

// filesIn is what matches pattern in folder, sorted, without those "._name" files.
func filesIn(folder, pattern string) []string {
	hits, _ := filepath.Glob(filepath.Join(globEscape(folder), pattern))
	var out []string
	for _, h := range hits {
		if !strings.HasPrefix(filepath.Base(h), "._") {
			out = append(out, h)
		}
	}
	sortPaths(out)
	return out
}

// globEscape keeps a folder's own name from being read as a pattern.
func globEscape(p string) string {
	if windows {
		return regexp.MustCompile(`[*?\[]`).ReplaceAllString(p, "[$0]")
	}
	return regexp.MustCompile(`[*?\[\\]`).ReplaceAllString(p, `\$0`)
}

func dirBytes(p string) int64 {
	var n int64
	filepath.WalkDir(p, func(q string, d fs.DirEntry, err error) error {
		if err == nil && !d.IsDir() {
			if st, err := os.Stat(q); err == nil && st.Mode().IsRegular() {
				n += st.Size()
			}
		}
		return nil
	})
	return n
}

func newestFile(folder, pattern string) string {
	if !isDir(folder) {
		return ""
	}
	hits, _ := filepath.Glob(filepath.Join(globEscape(folder), pattern))
	best := ""
	for _, h := range hits {
		if isFile(h) && (best == "" || compareVersions(filepath.Base(h), filepath.Base(best)) > 0) {
			best = h
		}
	}
	return best
}

func runLogged(cmd []string, what, dir string, attempts int) error {
	rc := 0
	for n := 1; n <= attempts; n++ {
		c := exec.Command(cmd[0], cmd[1:]...)
		c.Dir, c.Stdin, c.Stdout, c.Stderr = dir, os.Stdin, os.Stdout, os.Stderr
		if rc = exitOf(run(c)); rc == 0 {
			return nil
		}
		if n < attempts {
			log(fmt.Sprintf("    %s failed (exit %d); retrying (%d/%d)...", what, rc, n, attempts-1))
			sleep(15 * time.Second)
		}
	}
	return fmt.Errorf("%s failed (exit %d); see the messages above", what, rc)
}

func installProtomaps(root string, it *item, state, cfg *obj, force bool) (int64, error) {
	m := mapsSettings(cfg)
	pm := runtimeBinary(root, "pmtiles", "pmtiles")
	if pm == "" {
		return 0, errors.New("the pmtiles program (runtimes) isn't installed yet; run sync again")
	}
	est := it.files[0].estimate
	if est == 0 {
		est = 15 * GB
	}
	if !force && !ensureSpace(root, 2*est, cfg) { // world + region + combined copy, briefly
		return 0, fmt.Errorf("not enough free space for the map tiles (needs about %s while building)", fmtBytes(2*est))
	}
	dest := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
	work := filepath.Join(dest, ".build")
	os.RemoveAll(work)
	if err := os.MkdirAll(work, 0o755); err != nil {
		return 0, err
	}
	src := it.files[0].url
	wmax, dmax := intOr(m.get("world_maxzoom"), 7), intOr(m.get("detail_maxzoom"), 15)
	areas, err := mapAreas(m)
	if err != nil {
		return 0, err
	}
	where := "--bbox=" + strings.Join(numbers(areas[0]), ",")
	if len(areas) > 1 { // several places: their areas, as one GeoJSON shape
		var shapes []string
		for _, b := range areas {
			w, s, e, n := numbers(b)[0], numbers(b)[1], numbers(b)[2], numbers(b)[3]
			shapes = append(shapes, fmt.Sprintf("[[[%s,%s],[%s,%s],[%s,%s],[%s,%s],[%s,%s]]]", w, s, e, s, e, n, w, n, w, s))
		}
		shape := filepath.Join(work, "areas.geojson")
		geo := `{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},"geometry":{"type":"MultiPolygon",` +
			`"coordinates":[` + strings.Join(shapes, ",") + `]}}]}`
		if err := os.WriteFile(shape, []byte(geo), 0o644); err != nil {
			return 0, err
		}
		where = "--region=" + shape
	}
	world, region, outFile := filepath.Join(work, "world.pmtiles"), filepath.Join(work, "region.pmtiles"), filepath.Join(work, "basemap.pmtiles")
	log(fmt.Sprintf("    map tiles: world overview (zoom 0-%d) from build %s...", wmax, it.version))
	if err := runLogged([]string{pm, "extract", src, world, fmt.Sprintf("--maxzoom=%d", wmax)}, "map extract (world)", "", 3); err != nil {
		return 0, err
	}
	log(fmt.Sprintf("    map tiles: %s street detail (zoom %d-%d)...", pyStr(m.get("label")), wmax+1, dmax))
	if err := runLogged([]string{pm, "extract", src, region, where, fmt.Sprintf("--minzoom=%d", wmax+1),
		fmt.Sprintf("--maxzoom=%d", dmax)}, "map extract (region)", "", 3); err != nil {
		return 0, err
	}
	log("    map tiles: combining and checking...")
	if err := runLogged([]string{pm, "merge", world, region, outFile}, "map merge", "", 1); err != nil {
		return 0, err
	}
	if err := runLogged([]string{pm, "verify", outFile}, "map verify", "", 1); err != nil {
		return 0, err
	}
	sha, err := sha256File(outFile)
	if err != nil {
		return 0, err
	}
	final := filepath.Join(dest, "basemap.pmtiles")
	if err := replace(outFile, final); err != nil {
		return 0, err
	}
	os.RemoveAll(work)
	size := fileSize(final)
	log("    ok: maps/tiles/basemap.pmtiles (" + fmtBytes(size) + ")")
	stateItems(state).set(it.key(), newObj("version", it.version, "area", it.extra.get("area"), "dest", it.dest,
		"updated", nowISO(), "note", it.note(),
		"files", newObj("basemap.pmtiles", newObj("size", size, "sha256", sha, "verified", false))))
	return size, nil
}

func routingProfiles(m *obj) []string {
	var profiles []string
	for _, p := range m.getOr("routing_profiles", []any{"car", "foot"}).([]any) {
		if s, ok := p.(string); ok && ghEncodedValues[s] != nil {
			profiles = append(profiles, s)
		}
	}
	return profiles
}

func graphhopperYAML(m *obj, graphDir, storage string) string {
	profiles := routingProfiles(m)
	if len(profiles) == 0 {
		profiles = []string{"car"}
	}
	var evs []string
	for _, p := range profiles {
		for _, e := range ghEncodedValues[p] {
			if !contains(evs, e) {
				evs = append(evs, e)
			}
		}
	}
	lines := []string{"graphhopper:", "  datareader.file: region.osm.pbf", "  graph.location: " + graphDir, "  profiles:"}
	for _, p := range profiles {
		lines = append(lines, "    - name: "+p, "      custom_model_files: ["+p+".json]")
	}
	if contains(profiles, "car") {
		lines = append(lines, "  profiles_ch:", "    - profile: car")
	} else {
		lines = append(lines, "  profiles_ch: []")
	}
	ignored := "footway,construction,cycleway,path,steps"
	for _, p := range profiles {
		if p != "car" {
			ignored = `""`
		}
	}
	lang := "en"
	if truthy(m.get("lang")) {
		lang = pyStr(m.get("lang"))
	}
	port := intOr(m.get("routing_port"), 8989)
	lines = append(lines, "  profiles_lm: []",
		"  graph.encoded_values: "+strings.Join(evs, ", "),
		"  prepare.min_network_size: 200",
		"  prepare.subnetworks.threads: 1",
		"  routing.snap_preventions_default: tunnel, bridge, ferry",
		"  routing.non_ch.max_waypoint_distance: 1000000",
		"  import.osm.ignored_highways: "+ignored,
		"  datareader.preferred_language: "+lang,
		"  graph.dataaccess.default_type: "+storage,
		"  graph.locktype: simple",
		"server:",
		"  application_connectors:",
		"  - type: http",
		fmt.Sprintf("    port: %d", port),
		"    bind_host: localhost",
		"    max_request_header_size: 50k",
		"  request_log:",
		"    appenders: []",
		"  admin_connectors:",
		"  - type: http",
		fmt.Sprintf("    port: %d", port+1),
		"    bind_host: localhost",
		"logging:",
		"  appenders:",
		"    - type: console",
		"      time_zone: UTC",
		"")
	return strings.Join(lines, "\n")
}

// importHeap is Java's memory for building the directions network: kit.json's routing_import_heap, else 12 GB or 60%
// of this computer's memory if that's less, so an 8 or 16 GB laptop doesn't run out.
func importHeap(m *obj) string {
	if !pyEqual(m.get("routing_import_heap"), "auto") {
		return pyStr(m.get("routing_import_heap"))
	}
	gb := memoryBytes() / (1 << 30) // Java's g
	if gb == 0 {
		return "12g"
	}
	return fmt.Sprintf("%dg", min(12, max(2, gb*6/10)))
}

// buildRouting is GraphHopper's import into dest/graph-cache.new: in memory, the fast way, and if that runs out of
// memory, again with the graph on disk, which needs far less.
func buildRouting(java, gh string, m *obj, dest string) error {
	heap := importHeap(m)
	built := false
	for _, storage := range []string{"RAM_STORE", "MMAP"} {
		os.WriteFile(filepath.Join(dest, "gh-import.yml"), []byte(graphhopperYAML(m, "graph-cache.new", storage)), 0o644)
		os.RemoveAll(filepath.Join(dest, "graph-cache.new"))
		if storage == "RAM_STORE" {
			log("    building the road network for directions (GraphHopper import, 10-40 minutes)...")
		} else {
			log("    that ran out of memory (" + heap + "), so building it again on disk, which takes longer...")
		}
		c := exec.Command(java, "-Xmx"+heap, "-XX:+ExitOnOutOfMemoryError", "-jar", gh, "import", "gh-import.yml")
		c.Dir, c.Stdin, c.Stdout, c.Stderr = dest, os.Stdin, os.Stdout, os.Stderr
		rc := exitOf(run(c))
		if rc == 0 {
			built = true
			break
		}
		if rc != 3 { // what -XX:+ExitOnOutOfMemoryError exits with
			return fmt.Errorf("GraphHopper import failed (exit %d); see the messages above", rc)
		}
	}
	if !built {
		return fmt.Errorf("building the directions network ran out of memory (%s) even on disk. Close other apps "+
			"and run sync again, or choose a smaller map region", heap)
	}
	if !exists(filepath.Join(dest, "graph-cache.new", "properties")) {
		return errors.New("GraphHopper import finished but produced no graph; see the messages above")
	}
	return nil
}

// roadsFromBefore is f's road data if the kit has it from before under another name, moved to f's name: one place's
// is region.osm.pbf, several places' keep their own names. Returns its SHA-256, or "".
func roadsFromBefore(dest string, old *obj, it *item, f *remoteFile, expected [][2]string) string {
	for _, name := range old.child("files").Keys() {
		if slices.ContainsFunc(it.files, func(g *remoteFile) bool { return g.name == name }) {
			continue // (another place's now)
		}
		if sha := matches(filepath.Join(dest, name), f, expected); sha != "" &&
			replace(filepath.Join(dest, name), filepath.Join(dest, f.name)) == nil {
			return sha
		}
	}
	return ""
}

func installRouting(root string, it *item, state, cfg *obj, force bool) (int64, error) {
	m := mapsSettings(cfg)
	java := runtimeBinary(root, "java", "java")
	gh := newestFile(filepath.Join(dlDir(root), "bin", "graphhopper"), "graphhopper-web-*.jar")
	if java == "" || gh == "" {
		return 0, errors.New("Java or GraphHopper (runtimes) isn't installed yet; run sync again")
	}
	dest := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
	os.MkdirAll(dest, 0o755)
	old := stateItems(state).child(it.key())
	var downloaded, total int64
	var parts []string
	files := newObj()
	for _, f := range it.files {
		pbf := filepath.Join(dest, f.name)
		var sha string
		if !pyEqual(old.get("version"), it.version) || !exists(pbf) {
			expected := expectedDigests(f)
			sha = matches(pbf, f, expected) // downloaded last time, but the import failed (e.g. out of memory)
			if sha == "" {
				sha = roadsFromBefore(dest, old, it, f, expected)
			}
			if sha == "" {
				partial, err := fetchFile(root, state, it, f, cfg, force, 3, "road data")
				if err != nil {
					return downloaded, err
				}
				if sha, err = verifyDownload(partial, f, expected); err != nil {
					return downloaded, err
				}
				if err := replace(partial, pbf); err != nil {
					return downloaded, err
				}
				forgetPartial(root, state, partial)
				downloaded += fileSize(pbf)
			}
		} else if sha = pyStr(orEmpty(old.child("files").child(f.name).get("sha256"))); sha == "" {
			var err error
			if sha, err = sha256File(pbf); err != nil {
				return downloaded, err
			}
		}
		files.set(f.name, newObj("size", fileSize(pbf), "sha256", sha, "verified", true))
		parts = append(parts, pbf)
		total += fileSize(pbf)
	}
	if len(parts) > 1 { // GraphHopper reads one file: several places' road data, merged
		if !force && !ensureSpace(root, total, cfg) {
			return downloaded, fmt.Errorf("not enough free space to merge the road data (needs about %s)", fmtBytes(total))
		}
		log(fmt.Sprintf("    merging the road data of %d places...", len(parts)))
		if err := mergePBF(filepath.Join(dest, "region.osm.pbf"), parts); err != nil {
			return downloaded, err
		}
	}
	os.WriteFile(filepath.Join(dest, "gh-serve.yml"), []byte(graphhopperYAML(m, "graph-cache", "MMAP")), 0o644)
	if err := buildRouting(java, gh, m, dest); err != nil {
		return downloaded, err
	}
	current, trash, fresh := filepath.Join(dest, "graph-cache"), filepath.Join(dest, "graph-cache.old"), filepath.Join(dest, "graph-cache.new")
	os.RemoveAll(trash)
	if exists(current) {
		if err := replace(current, trash); err != nil {
			return downloaded, err
		}
	}
	if err := replace(fresh, current); err != nil {
		return downloaded, err
	}
	os.RemoveAll(trash)
	// road data no place needs now (a place from before), and the merged copy: merging again is quick
	if found, err := filepath.Glob(filepath.Join(dest, "*.osm.pbf")); err == nil {
		for _, p := range found {
			if !files.has(filepath.Base(p)) {
				os.Remove(p)
			}
		}
	}
	log("    ok: maps/routing/graph-cache")
	ghVersion := it.extra.get("gh_version")
	if !truthy(ghVersion) {
		ghVersion = filepath.Base(gh)
	}
	stateItems(state).set(it.key(), newObj("version", it.version, "gh_version", ghVersion, "dest", it.dest,
		"updated", nowISO(), "note", it.note(), "unpacked_size", dirBytes(current), "files", files))
	return downloaded, nil
}

func installPhoton(root string, it *item, state, cfg *obj, force bool) (int64, error) {
	f := it.files[0]
	dest := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
	expected := expectedDigests(f)
	// the download plus about 3x that unpacked
	partial, err := fetchFile(root, state, it, f, cfg, force, 4, "the address database")
	if err != nil {
		return 0, err
	}
	sha, err := verifyDownload(partial, f, expected)
	if err != nil {
		return 0, err
	}
	staging := dest + ".new"
	os.RemoveAll(staging)
	if err := os.MkdirAll(staging, 0o755); err != nil {
		return 0, err
	}
	log("    unpacking it (10-40 minutes)...")
	ok, why := false, ""
	fast := ""
	for _, t := range []string{"pbzip2", "lbzip2"} {
		if which(t) {
			fast = t
			break
		}
	}
	switch {
	case windows:
	case fast != "":
		unpack := exec.Command(fast, "-dc", partial)
		untar := exec.Command("tar", "-x", "-f", "-", "-C", staging) // "-f -": BSD tar may default to a tape
		pipe, err := unpack.StdoutPipe()
		if err == nil {
			untar.Stdin, untar.Stdout, untar.Stderr, unpack.Stderr = pipe, os.Stdout, os.Stderr, os.Stderr
			if unpack.Start() == nil {
				rc := exitOf(run(untar))
				ok = exitOf(unpack.Wait()) == 0 && rc == 0
			}
		}
	default:
		c := exec.Command("tar", "-xjf", partial, "-C", staging)
		c.Stdout, c.Stderr = os.Stdout, os.Stderr
		ok = exitOf(run(c)) == 0
	}
	if !ok { // Windows, or a Linux PC without bzip2
		os.RemoveAll(staging)
		os.MkdirAll(staging, 0o755)
		if err := untarTo(partial, staging, "bz2"); err != nil {
			why = ": " + errText(err)
		} else {
			ok = true
		}
	}
	data := filepath.Join(staging, "photon_data")
	if !isDir(data) {
		if nested, _ := filepath.Glob(filepath.Join(globEscape(staging), "*", "photon_data")); len(nested) > 0 && isDir(nested[0]) {
			replace(nested[0], data)
		}
	}
	if !ok || !isDir(data) {
		os.RemoveAll(staging)
		if why == "" && ok {
			why = ": no photon_data folder in it"
		}
		return 0, errors.New("unpacking the address database failed" + why)
	}
	trash := dest + ".old"
	os.RemoveAll(trash)
	if exists(dest) {
		if err := replace(dest, trash); err != nil {
			return 0, err
		}
	}
	if err := replace(staging, dest); err != nil {
		return 0, err
	}
	os.RemoveAll(trash)
	os.Remove(partial)
	forgetPartial(root, state, partial)
	log("    ok: maps/geocoder/photon_data")
	stateItems(state).set(it.key(), newObj("version", it.version, "dest", it.dest, "archive", f.name, "archive_sha256", sha,
		"db_version", it.extra.get("db_version"), "updated", nowISO(), "note", it.note(), "unpacked_size", dirBytes(dest)))
	return f.size, nil
}

func installerFor(it *item) func(string, *item, *obj, *obj, bool) (int64, error) {
	if it.kind == "custom" {
		return map[string]func(string, *item, *obj, *obj, bool) (int64, error){"protomaps": installProtomaps,
			"routing": installRouting, "photon_db": installPhoton}[it.typ()]
	}
	if it.kind == "archive" {
		return installArchive
	}
	return installFiles
}

// ----------------------------------------------------------------------------- the kit page

func currentDir(root, rel string) string {
	base := filepath.Join(dlDir(root), filepath.FromSlash(rel))
	data, err := os.ReadFile(filepath.Join(base, "CURRENT"))
	if err != nil {
		return ""
	}
	if d := filepath.Join(base, strings.TrimSpace(string(data))); isDir(d) {
		return d
	}
	return ""
}

func b64file(p string) string {
	data, _ := os.ReadFile(p)
	return base64.StdEncoding.EncodeToString(data)
}

// buildPortal assembles the kit page kiwix-serve serves, with the map engine and map settings in it (kiwix-serve
// can only serve one page of the kit's own, so everything the map needs goes inside it).
func buildPortal(root string, cfg *obj) (string, error) {
	tplData, err := os.ReadFile(filepath.Join(appDir(root), "tools", "portal.html"))
	if err != nil {
		return "", err
	}
	tpl := string(tplData)
	m := mapsSettings(cfg)
	info := newObj("available", false)
	inject := ""
	if !truthy(m.get("enabled")) {
		info.set("reason", "Maps are turned off in kit.json.")
	} else {
		ml, bm, ba := currentDir(root, "maps/viewer/maplibre-gl"), currentDir(root, "maps/viewer/protomaps-basemaps"),
			currentDir(root, "maps/viewer/basemaps-assets")
		under := func(base string, parts ...string) string {
			if base == "" {
				return ""
			}
			return filepath.Join(append([]string{base}, parts...)...)
		}
		firstGlob := func(base, pattern string) string {
			if base == "" {
				return ""
			}
			hits, _ := filepath.Glob(filepath.Join(globEscape(base), pattern))
			if len(hits) == 0 {
				return ""
			}
			return hits[0]
		}
		names := []string{"map engine", "map engine styles", "map style", "map fonts", "map icons", "map tiles"}
		parts := map[string]string{
			"map engine":        under(ml, "package", "dist", "maplibre-gl.js"),
			"map engine styles": under(ml, "package", "dist", "maplibre-gl.css"),
			"map style":         under(bm, "package", "dist", "basemaps.js"),
			"map fonts":         firstGlob(ba, filepath.Join("*", "fonts")),
			"map icons":         firstGlob(ba, filepath.Join("*", "sprites", "v4")),
			"map tiles":         filepath.Join(dlDir(root), "maps", "tiles", "basemap.pmtiles"),
		}
		var gone []string
		for _, k := range names {
			if parts[k] == "" || !exists(parts[k]) {
				gone = append(gone, k)
			}
		}
		if len(gone) > 0 {
			info.set("reason", "Not downloaded yet: "+strings.Join(gone, ", ")+". Run ./kit sync while online.")
		} else {
			fonts, sprites := parts["map fonts"], parts["map icons"]
			glyphs := newObj()
			for _, font := range glyphFonts {
				for _, rng := range glyphRanges {
					if p := filepath.Join(fonts, font, rng+".pbf"); exists(p) {
						glyphs.set(font+"/"+rng, b64file(p))
					}
				}
			}
			spr := newObj()
			for _, name := range []string{"light", "light@2x"} {
				j, png := filepath.Join(sprites, name+".json"), filepath.Join(sprites, name+".png")
				if exists(j) && exists(png) {
					data, _ := os.ReadFile(j)
					v, err := parseJSON(data)
					if err != nil {
						return "", err
					}
					spr.set(name+".json", v)
					spr.set(name+".png", b64file(png))
				}
			}
			var profiles []any
			for _, p := range m.list("routing_profiles") {
				if s, ok := p.(string); ok && ghEncodedValues[s] != nil {
					profiles = append(profiles, s)
				}
			}
			if profiles == nil {
				profiles = []any{}
			}
			lang := any("en")
			if truthy(m.get("lang")) {
				lang = m.get("lang")
			}
			bbox := m.get("detail_bbox") // several places': the area around them all
			if areas, err := mapAreas(m); err == nil && len(areas) > 1 {
				all := slices.Clone(areas[0])
				for _, b := range areas[1:] {
					all = []float64{min(all[0], b[0]), min(all[1], b[1]), max(all[2], b[2]), max(all[3], b[3])}
				}
				bbox = []any{all[0], all[1], all[2], all[3]}
			}
			info = newObj("available", true, "label", m.get("label"), "home", m.get("home"), "bbox", bbox,
				"detailMaxzoom", intOr(m.get("detail_maxzoom"), 15), "units", m.get("units"), "lang", lang,
				"profiles", profiles,
				"ports", newObj("tiles", intOr(m.get("tiles_port"), 8090), "geocoder", intOr(m.get("geocoder_port"), 2322),
					"routing", intOr(m.get("routing_port"), 8989)),
				"tileset", "basemap", "glyphs", glyphs, "sprites", spr,
				"services", newObj("geocoder", isDir(filepath.Join(dlDir(root), "maps", "geocoder", "photon_data")),
					"routing", exists(filepath.Join(dlDir(root), "maps", "routing", "graph-cache", "properties"))))
			code := func(p string) string {
				data, _ := os.ReadFile(p)
				return strings.ReplaceAll(string(data), "</script", `<\/script`)
			}
			css, _ := os.ReadFile(parts["map engine styles"])
			inject = "<style>" + string(css) + "</style>\n<script>" + code(parts["map engine"]) + "</script>\n<script>" +
				code(parts["map style"]) + "</script>\n"
		}
	}
	inject += "<script>window.KIT_MAPS = " + strings.ReplaceAll(dumpsLine(info), "</", `<\/`) + ";</script>\n"
	inject += "<script>window.KIT_REFRESHED = " + dumpsLine(loadState(root).get("last_sync")) + ";</script>\n"
	html := strings.Replace(tpl, "<!--KIT:MAPS-->", inject, -1)
	// kiwix-serve renders this page as a Mustache template: switch the tag markers to something that appears nowhere in
	// the embedded code, so "{{" inside it is left alone.
	var o, c string
	for _, pair := range [][2]string{{"<%", "%>"}, {"[[kit:", ":kit]]"}, {"@@kit<", ">kit@@"}} {
		if !strings.Contains(html, pair[0]) && !strings.Contains(html, pair[1]) {
			o, c = pair[0], pair[1]
			break
		}
	}
	if o == "" {
		return "", errors.New("could not find safe template markers for the portal page")
	}
	html = "{{=" + o + " " + c + "=}}" + strings.ReplaceAll(html, "{{root}}", o+"root"+c)
	outFile := filepath.Join(metaDir(root), "portal.html")
	os.MkdirAll(filepath.Dir(outFile), 0o755)
	tmp := filepath.Join(metaDir(root), "portal.tmp")
	if err := os.WriteFile(tmp, []byte(html), 0o644); err != nil {
		return "", err
	}
	return outFile, replace(tmp, outFile)
}

// ----------------------------------------------------------------------------- housekeeping

func prepareFolder(root string) {
	if windows {
		// A kit unzipped from a download is marked "from the internet", and Windows warns before it runs a marked
		// script. Lift the mark from the kit's own scripts and tools (an exFAT drive can't hold it anyway).
		code := appDir(root)
		var files []string
		for _, pat := range []string{"*.bat", "*.cmd"} {
			hits, _ := filepath.Glob(filepath.Join(globEscape(code), pat))
			files = append(files, hits...)
		}
		hits, _ := filepath.Glob(filepath.Join(globEscape(filepath.Join(code, "tools")), "*"))
		for _, p := range append(files, hits...) {
			os.Remove(p + ":Zone.Identifier")
		}
		return
	}
	if !mac {
		return
	}
	// A kit downloaded as a ZIP is marked "from the internet", and macOS won't open marked scripts until they're
	// approved in System Settings. Lift the mark so Open Tinfoil Kit opens with a plain double-click in an outage.
	args := []string{"-dr", "com.apple.quarantine"}
	for _, f := range []string{"Open Tinfoil Kit.command", "SETUP.command", "UNINSTALL.command", "kit", "tools"} {
		args = append(args, filepath.Join(appDir(root), f))
	}
	output("xattr", args...)
	if onThisComputer(root) {
		// Time Machine would copy 300 GB of downloads to the backup disk at its next backup. A sticky exclusion (no
		// administrator needed) travels with the folder, and goes when the folder does. data/ (pins, notes, settings) is
		// still backed up.
		os.MkdirAll(dlDir(root), 0o755)
		output("tmutil", "addexclusion", dlDir(root))
		return
	}
	parts := strings.Split(resolvePath(root), "/")
	if len(parts) >= 3 && parts[1] == "Volumes" { // keep Spotlight from indexing 500 GB of archives
		marker := filepath.Join("/", parts[1], parts[2], ".metadata_never_index")
		if f, err := os.OpenFile(marker, os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			f.Close()
		}
	}
}

// driveBytes is what an item in state.json takes up on disk.
func driveBytes(rec *obj) int64 {
	var n int64
	files := rec.child("files")
	for _, k := range files.Keys() {
		n += intOr(files.child(k).getOr("size", 0), 0)
	}
	return n + intOr(rec.getOr("unpacked_size", 0), 0)
}

func capitalize(s string) string {
	if s == "" {
		return s
	}
	return strings.ToUpper(s[:1]) + strings.ToLower(s[1:])
}

func writeInventory(root string, state *obj) {
	lines := []string{"# What's in this kit", "", "Last updated: " + pyStr(state.getOr("last_sync", "never")) + "  ",
		"Generated by `./kit sync`. Start everything by double-clicking Open Tinfoil Kit.", ""}
	all := stateItems(state)
	keys := sortedKeys(all)
	for _, section := range sections {
		var rows []string
		for _, k := range keys {
			if strings.HasPrefix(k, section+"/") {
				rows = append(rows, k)
			}
		}
		if len(rows) == 0 {
			continue
		}
		lines = append(lines, "## "+capitalize(section), "", "| Item | Version | Size | Notes |", "|---|---|---|---|")
		for _, k := range rows {
			v := all.child(k)
			size := driveBytes(v)
			shown := ""
			if size != 0 {
				shown = fmtBytes(size)
			}
			note := ""
			if truthy(v.get("note")) {
				note = pyStr(v.get("note"))
			}
			lines = append(lines, fmt.Sprintf("| %s | %s | %s | %s |", strings.SplitN(k, "/", 2)[1], pyStr(v.getOr("version", "")),
				shown, strings.ReplaceAll(note, "|", "/")))
		}
		lines = append(lines, "")
	}
	os.MkdirAll(dlDir(root), 0o755)
	os.WriteFile(filepath.Join(dlDir(root), "INVENTORY.md"), []byte(strings.Join(lines, "\n")), 0o644)
}

// keepAwake keeps the computer from sleeping (the screen may) through hours of downloads, until the function it
// returns is called or the kit ends.
func keepAwake() func() {
	if windows {
		stayAwake()
		return func() {}
	}
	pid := strconv.Itoa(os.Getpid())
	cmd := []string{"systemd-inhibit", "--what=idle:sleep", "--who=Tinfoil Kit", "--why=Downloading the kit", "tail",
		"--pid=" + pid, "-f", os.DevNull}
	if mac {
		cmd = []string{"caffeinate", "-i", "-w", pid}
	}
	if !which(cmd[0]) {
		return func() {}
	}
	c := exec.Command(cmd[0], cmd[1:]...) // no stdin, so it can't stop to ask for a password
	if c.Start() != nil {
		return func() {}
	}
	return func() {
		terminate(c.Process)
		c.Wait()
	}
}

// lockKit keeps two syncs from working on one kit at once. It returns the function that lets go.
func lockKit(root string) func() {
	p := filepath.Join(metaDir(root), "lock")
	os.MkdirAll(filepath.Dir(p), 0o755)
	// Read and write, not append: Windows locks only a file opened for one of those (Go opens an appending one for
	// neither). Not truncated: Windows won't empty a file another sync has locked.
	f, err := os.OpenFile(p, os.O_RDWR|os.O_CREATE, 0o644)
	if err != nil {
		return func() {}
	}
	if err := lockFile(f); errors.Is(err, errLocked) {
		f.Close()
		die("another ./kit sync is already running on this kit")
	} // (a drive format without locks: carry on)
	return func() { f.Close() }
}

var errLocked = errors.New("locked")

// joinURLPath is a URL path's parts joined, for the mock-free parts of the kit that build one.
func joinURLPath(parts ...string) string { return path.Join(parts...) }
