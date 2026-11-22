package main

// What goes in the kit and where each part of it comes from: kit.json's items, the newest version of each (looked up
// online, read-only), and what a sync would download.

import (
	"bytes"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/mail"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

type remoteFile struct {
	name, url     string
	size          int64 // 0: not known
	sha256        string
	sha256Sidecar bool        // fetch <url>.sha256 at download time (Kiwix)
	md5Sidecar    bool        // fetch <url>.md5 at download time (Geofabrik, Photon dumps)
	checks        [][2]string // other published digests: {"sha1", hex}, {"sha512", hex}
	estimate      int64       // rough size, when the exact one is only known later (map tiles, Kiwix's books)
}

type item struct {
	section, id string
	cfg         *obj
	kind        string // "files" (kept as-is), "archive" (extracted) or "custom" (own installer)
	dest        string
	version     string
	files       []*remoteFile
	err         string
	status      string // ok | new | update | later (refresh_days) | error
	need        []*remoteFile
	extra       *obj
}

func newItem(section, id string, cfg *obj) *item {
	return &item{section: section, id: id, cfg: cfg, kind: "files", extra: newObj()}
}

func (i *item) key() string   { return i.section + "/" + i.id }
func (i *item) enabled() bool { return truthy(i.cfg.getOr("enabled", true)) }
func (i *item) typ() string   { return pyStr(i.cfg.get("type")) }

func (i *item) priority() int64 {
	if i.section == "runtimes" {
		return 0
	}
	return intOr(i.cfg.getOr("priority", 2), 2)
}

func (i *item) note() any { return i.cfg.getOr("note", "") }

func (i *item) needs(f *remoteFile) bool {
	for _, n := range i.need {
		if n == f {
			return true
		}
	}
	return false
}

// partial is where f is downloaded to; an interrupted download resumes from here.
func (i *item) partial(root string, f *remoteFile) string {
	if i.kind == "archive" || i.typ() == "photon_db" {
		return filepath.Join(dlDir(root), ".partial", f.name+".partial")
	}
	return filepath.Join(dlDir(root), filepath.FromSlash(i.dest), f.name+".partial")
}

func (i *item) needBytes(root string) int64 {
	var total int64
	for _, f := range i.need {
		size := f.size
		if size == 0 {
			size = f.estimate
		}
		if size > 0 {
			total += max(0, size-fileSize(i.partial(root, f)))
		}
	}
	return total
}

// ----------------------------------------------------------------------------- resolvers

// resolver looks up the latest available version of each item (network, read-only).
type resolver struct {
	root       string
	cfg        *obj
	catalogs   map[string]*obj
	catalogErr error
	releases   map[string][]any
	listings   map[string]string
	resolved   map[string]*item
	pins       map[string]*obj
	maxAge     time.Duration // how old a saved Kiwix catalog may be
}

func newResolver(root string, cfg *obj) *resolver {
	return &resolver{root: root, cfg: cfg, releases: map[string][]any{}, listings: map[string]string{},
		resolved: map[string]*item{}, pins: loadPins(root, cfg), maxAge: 12 * time.Hour}
}

// catalog is the Kiwix catalog: each book's file prefix (wikipedia_en_all_maxi) and its newest edition.
func (r *resolver) catalog() (map[string]*obj, error) {
	if r.catalogs != nil {
		return r.catalogs, nil
	}
	if r.catalogErr != nil { // every book asks; fetch it once
		return nil, r.catalogErr
	}
	cache := filepath.Join(metaDir(r.root), "cache", "kiwix-catalog.xml")
	os.MkdirAll(filepath.Dir(cache), 0o755)
	if st, err := os.Stat(cache); err == nil && time.Since(st.ModTime()) < r.maxAge {
		if data, err := os.ReadFile(cache); err == nil {
			if c, err := parseKiwixCatalog(data); err == nil && len(c) > 0 {
				r.catalogs = c
			}
		}
	}
	if r.catalogs == nil {
		log("Fetching the Kiwix catalog (all available libraries)...")
		data, err := httpGet(kiwixCatalog, 600, "")
		if err != nil {
			r.catalogErr = fmt.Errorf("couldn't reach the Kiwix catalog (%s). Is this computer online?", err)
			return nil, r.catalogErr
		}
		// parse before caching: a Wi-Fi sign-in page answers every URL with HTML
		c, err := parseKiwixCatalog(data)
		if err != nil {
			why := "it's garbled: " + err.Error()
			if bytes.Contains(bytes.ToLower(data[:min(len(data), 4000)]), []byte("<html")) {
				why = "got a web page instead; does this Wi-Fi want you to sign in?"
			}
			r.catalogErr = fmt.Errorf("couldn't read the Kiwix catalog (%s)", why)
			return nil, r.catalogErr
		}
		if len(c) == 0 {
			r.catalogErr = errors.New("the Kiwix catalog came back empty; try again later")
			return nil, r.catalogErr
		}
		r.catalogs = c
		os.WriteFile(cache+".tmp", data, 0o644)
		replace(cache+".tmp", cache)
	}
	return r.catalogs, nil
}

func (r *resolver) resolve(it *item) {
	t := it.typ()
	handlers := map[string]func(*item) error{"zim": r.zim, "hf": r.hf, "github": r.github, "kiwix_release": r.kiwixRelease,
		"url": r.url, "adoptium": r.adoptium, "maven": r.maven, "npm": r.npm, "github_archive": r.githubArchive,
		"protomaps": r.protomaps, "routing": r.routing, "photon_db": r.photonDB}
	err := func() (err error) {
		defer func() { // a publisher's answer that isn't what it should be is that item's error, as in kit.py
			if p := recover(); p != nil {
				if bad, ok := p.(badAnswer); ok {
					err = bad
					return
				}
				panic(p)
			}
		}()
		h, ok := handlers[t]
		if !ok {
			return fmt.Errorf("unknown type '%s'", pyStr(it.cfg.get("type")))
		}
		if err := h(it); err != nil {
			return err
		}
		if pin := r.pins[it.id]; pin != nil && contains(pinnedTypes, t) && truthy(pin.get("sha256")) && len(it.files) > 0 {
			f := it.files[0]
			want := strings.ToLower(pyStr(pin.get("sha256")))
			if f.sha256 != "" && strings.ToLower(f.sha256) != want {
				return fmt.Errorf("the file published as %s changed after this version of the kit pinned it "+
					"(tools/pins.json), so it's left alone. Please report it at %s", it.version, report)
			}
			f.sha256 = want
		}
		return nil
	}()
	if err != nil {
		it.err = err.Error()
	}
	r.resolved[it.id] = it
}

// badAnswer is a publisher's answer missing what it should have, which ends that item's lookup (Python's KeyError).
type badAnswer struct{ msg string }

func (b badAnswer) Error() string { return b.msg }

// need is a key that must be in a publisher's answer.
func need(o any, key string) any {
	m, ok := o.(*obj)
	if !ok {
		panic(badAnswer{fmt.Sprintf("'%s' object is not subscriptable", pyType(o))})
	}
	v, ok := m.lookup(key)
	if !ok {
		panic(badAnswer{"'" + key + "'"})
	}
	return v
}

func needStr(o any, key string) string {
	v := need(o, key)
	s, ok := v.(string)
	if !ok {
		panic(badAnswer{fmt.Sprintf("expected a string for '%s', got %s", key, pyType(v))})
	}
	return s
}

func needObj(o any, key string) *obj {
	v, ok := need(o, key).(*obj)
	if !ok {
		panic(badAnswer{fmt.Sprintf("expected an object for '%s'", key)})
	}
	return v
}

func first(l any) any {
	list, ok := l.([]any)
	if !ok || len(list) == 0 {
		panic(badAnswer{"list index out of range"})
	}
	return list[0]
}

func (r *resolver) zim(it *item) error {
	c, err := r.catalog()
	if err != nil {
		return err
	}
	e := c[it.id]
	if e == nil {
		return fmt.Errorf("not found in the Kiwix catalog (try: ./kit search %s)", strings.Split(it.id, "_")[0])
	}
	it.dest = "library"
	it.version = e.str("date")
	// The catalog rounds each size up to a whole KiB, so it's only a rough one: fetch asks the download server for the
	// exact size just before downloading (asking for every book here would slow every plan down).
	it.files = []*remoteFile{{name: e.str("file"), url: e.str("url"), estimate: intOr(e.get("size"), 0), sha256Sidecar: true}}
	return nil
}

func (r *resolver) hf(it *item) error {
	repo := pyStr(need(it.cfg, "repo"))
	v, err := httpJSON(hfURL+"/api/models/"+repo, 0)
	if err != nil {
		var he *httpError
		if errors.As(err, &he) && (he.status == 401 || he.status == 403) {
			return fmt.Errorf("%s is gated or private: accept its license on huggingface.co and set HF_TOKEN", repo)
		}
		if errors.As(err, &he) && he.status == 404 {
			return fmt.Errorf("Hugging Face repo %s not found (renamed or removed?)", repo)
		}
		return err
	}
	info, _ := v.(*obj)
	sha := "main"
	if s := pyStr(info.get("sha")); truthy(info.get("sha")) {
		sha = s
	}
	tree, err := hfTree(repo, sha)
	if err != nil {
		return err
	}
	var patterns []string
	for _, p := range it.cfg.list("files") {
		patterns = append(patterns, pyStr(p))
	}
	chosen, err := selectHFFiles(tree, patterns, repo)
	if err != nil {
		return err
	}
	it.dest = "models/" + it.id
	it.version = clip(sha, 12)
	it.files = nil
	for _, f := range chosen {
		lfs := f.child("lfs")
		path := needStr(f, "path")
		size := intOr(lfs.get("size"), 0)
		if size == 0 {
			size = intOr(f.get("size"), 0)
		}
		it.files = append(it.files, &remoteFile{name: path[strings.LastIndexByte(path, '/')+1:],
			url: hfURL + "/" + repo + "/resolve/" + sha + "/" + quote(path, "/"), size: size,
			sha256: strings.ToLower(pyStr(orEmpty(lfs.get("oid"))))})
	}
	return nil
}

func orEmpty(v any) any {
	if !truthy(v) {
		return ""
	}
	return v
}

// pinGitHub re-resolves a GitHub runtime to the newest release whose version starts with prefix, even past its pin in
// tools/pins.json: a program that can't open its data is no use.
func (r *resolver) pinGitHub(it *item, prefix string) bool {
	old, pins := it.cfg, r.pins
	it.cfg, r.pins = with(it.cfg, "version_prefix", prefix), map[string]*obj{}
	defer func() { r.pins = pins }()
	if err := r.github(it); err != nil {
		it.cfg = old
		return false
	}
	return true
}

func (r *resolver) pinned(it *item) string {
	if p := r.pins[it.id]; p != nil && truthy(p.get("version")) {
		return pyStr(p.get("version"))
	}
	return ""
}

func (r *resolver) github(it *item) error {
	repo, pattern, pin := pyStr(need(it.cfg, "repo")), pyStr(need(it.cfg, "asset")), r.pinned(it)
	repoKey := repo
	if pin != "" { // llama.cpp publishes several builds a day, so a pinned one is soon past the first page
		repoKey = repo + "@" + pin
		if _, ok := r.releases[repoKey]; !ok {
			rel, err := httpJSON(githubAPI+"/repos/"+repo+"/releases/tags/"+quote(pin, "/"), 0)
			if err != nil {
				var he *httpError
				if errors.As(err, &he) && he.status == 404 {
					return fmt.Errorf("%s no longer publishes %s, %s", repo, pin, pinGone)
				}
				return err
			}
			r.releases[repoKey] = []any{rel}
		}
	} else if _, ok := r.releases[repo]; !ok {
		v, err := httpJSON(githubAPI+"/repos/"+repo+"/releases?per_page=30", 0)
		if err != nil {
			return err
		}
		l, ok := v.([]any)
		if !ok {
			return badAnswer{"string indices must be integers"}
		}
		r.releases[repo] = l
	}
	var candidates []*obj
	for _, rel := range r.releases[repoKey] {
		if o, ok := rel.(*obj); ok && !truthy(o.get("draft")) {
			candidates = append(candidates, o)
		}
	}
	// llama.cpp's builds are its nightly prereleases. Every other program takes a full release while it has one.
	nightly := strings.HasSuffix(repo, "/llama.cpp") && !pyEqual(r.cfg.child("settings").getOr("llama_cpp_channel", "nightly"), "stable")
	if !nightly {
		sort.SliceStable(candidates, func(a, b int) bool { // each kind stays newest first
			return !truthy(candidates[a].get("prerelease")) && truthy(candidates[b].get("prerelease"))
		})
	}
	prefix := pyStr(it.cfg.getOr("version_prefix", ""))
	for _, rel := range candidates {
		tag := needStr(rel, "tag_name")
		if prefix != "" && !strings.HasPrefix(strings.TrimLeft(tag, "v"), prefix) {
			continue
		}
		for _, a := range rel.objs("assets") {
			name := needStr(a, "name")
			if !fnmatch(name, pattern) {
				continue
			}
			digest := pyStr(orEmpty(a.get("digest")))
			it.kind = "files"
			if isArchive(name) {
				it.kind = "archive"
			}
			it.dest, it.version = "bin/"+it.id, tag
			f := &remoteFile{name: name, url: needStr(a, "browser_download_url"), size: intOr(a.get("size"), 0)}
			if s, ok := strings.CutPrefix(digest, "sha256:"); ok {
				f.sha256 = s
			}
			it.files = []*remoteFile{f}
			return nil
		}
	}
	return fmt.Errorf("no release of %s has an asset matching '%s'", repo, pattern)
}

var (
	hrefRE     = regexp.MustCompile(`href="([^"?#]+)"`)
	versionSep = regexp.MustCompile(`[.-]`)
)

func (r *resolver) kiwixRelease(it *item) error {
	product, pattern := pyStr(need(it.cfg, "product")), pyStr(need(it.cfg, "pattern"))
	base := strings.ReplaceAll(kiwixReleases, "{product}", product)
	if _, ok := r.listings[base]; !ok {
		data, err := httpGet(base, 0, "")
		if err != nil {
			return err
		}
		r.listings[base] = strings.ToValidUTF8(string(data), "�")
	}
	rx := regexp.MustCompile("^" + strings.ReplaceAll(regexp.QuoteMeta(pattern), regexp.QuoteMeta("{version}"),
		`(\d+(?:\.\d+)*(?:-\d+)?)`) + "$")
	type hit struct{ version, name string }
	var found []hit
	seen := map[string]bool{}
	pin := r.pinned(it)
	for _, m := range hrefRE.FindAllStringSubmatch(r.listings[base], -1) {
		if seen[m[1]] {
			continue
		}
		seen[m[1]] = true
		name := unquote(m[1][strings.LastIndexByte(m[1], '/')+1:])
		if v := rx.FindStringSubmatch(name); v != nil && (pin == "" || v[1] == pin) {
			found = append(found, hit{v[1], name})
		}
	}
	if len(found) == 0 {
		forPin := ""
		if pin != "" {
			forPin = " for version " + pin
		}
		return fmt.Errorf("no file matching '%s'%s in %s", pattern, forPin, base)
	}
	best := found[0]
	for _, h := range found[1:] { // the newest: by its numbers, then its spelling
		c := compareInts(versionSep.Split(h.version, -1), versionSep.Split(best.version, -1))
		if c > 0 || c == 0 && (h.version > best.version || h.version == best.version && h.name > best.name) {
			best = h
		}
	}
	url := base + best.name
	it.kind, it.dest = "files", "installers"
	if isArchive(best.name) {
		it.kind, it.dest = "archive", "bin/"+it.id
	}
	it.version = best.version
	it.files = []*remoteFile{{name: best.name, url: url, size: headSize(url), sha256Sidecar: true}}
	return nil
}

func (r *resolver) url(it *item) error {
	url := pyStr(need(it.cfg, "url"))
	name := pyStr(it.cfg.get("filename"))
	if !truthy(it.cfg.get("filename")) {
		p := urlPath(url)
		name = p[strings.LastIndexByte(p, '/')+1:]
	}
	h, err := httpHead(url)
	if err != nil {
		return err
	}
	size := contentLength(h)
	it.dest = pyStr(it.cfg.getOr("dest", "installers"))
	switch {
	case h["etag"] != "":
		it.version = h["etag"]
	case h["last-modified"] != "":
		it.version = h["last-modified"]
	case size > 0:
		it.version = strconv.FormatInt(size, 10)
	default:
		it.version = "unknown"
	}
	it.files = []*remoteFile{{name: name, url: url, size: size, sha256: pyStr(orEmpty(it.cfg.get("sha256")))}}
	return nil
}

// --- maps: runtimes, viewer assets and data

func (r *resolver) adoptium(it *item) error {
	c := it.cfg
	arch, image, osName := pyStr(c.getOr("arch", "aarch64")), pyStr(c.getOr("image_type", "jre")), pyStr(c.getOr("os", "mac"))
	query := "architecture=" + arch + "&image_type=" + image + "&os=" + osName
	var rel, pkg *obj
	if pin := r.pinned(it); pin != "" { // by its release name: a lookup by version must match Adoptium's own spelling, "-LTS" and all
		v, err := httpJSON(adoptiumAPI+"/v3/assets/release_name/eclipse/"+quote(pin, "")+"?"+query+
			"&heap_size=normal&jvm_impl=hotspot&project=jdk", 0)
		if err != nil {
			var he *httpError
			if !errors.As(err, &he) || he.status != 404 {
				return err
			}
			v = []any{}
		}
		rels, ok := v.([]any)
		if !ok {
			rels = []any{v}
		}
		rel = newObj()
		for _, x := range rels {
			if o, ok := x.(*obj); ok && pyEqual(o.get("release_name"), pin) {
				rel = o
				break
			}
		}
		for _, b := range rel.objs("binaries") {
			if truthy(b.get("package")) && pyEqual(b.get("image_type"), image) && pyEqual(b.get("os"), osName) &&
				pyEqual(b.get("architecture"), arch) {
				pkg = needObj(b, "package")
				break
			}
		}
		if pkg == nil {
			return fmt.Errorf("Adoptium no longer publishes Java %s for %s %s, %s", pin, osName, arch, pinGone)
		}
	} else {
		v, err := httpJSON(adoptiumAPI+"/v3/assets/latest/"+pyStr(c.getOr("feature_version", 21))+"/hotspot?"+query+"&vendor=eclipse", 0)
		if err != nil {
			return err
		}
		if !truthy(v) {
			return errors.New("no Java runtime published for this platform")
		}
		rel, _ = first(v).(*obj)
		pkg = needObj(needObj(rel, "binary"), "package")
	}
	it.kind, it.dest = "archive", "bin/"+it.id
	it.version = pyStr(rel.get("release_name"))
	if !truthy(rel.get("release_name")) {
		it.version = pyStr(need(needObj(rel, "version"), "semver"))
	}
	it.files = []*remoteFile{{name: needStr(pkg, "name"), url: needStr(pkg, "link"), size: intOr(pkg.get("size"), 0),
		sha256: pyStr(orEmpty(pkg.get("checksum")))}}
	return nil
}

var (
	mavenVersion = regexp.MustCompile(`<version>([^<]+)</version>`)
	dotted       = regexp.MustCompile(`^\d+(\.\d+)*$`)
	semver       = regexp.MustCompile(`^\d+\.\d+\.\d+$`)
	sha1RE       = regexp.MustCompile(`\b[0-9a-f]{40}\b`)
)

func (r *resolver) maven(it *item) error {
	c := it.cfg
	artifact := pyStr(need(c, "artifact"))
	base := mavenURL + "/" + strings.ReplaceAll(pyStr(need(c, "group")), ".", "/") + "/" + artifact + "/"
	data, err := httpGet(base+"maven-metadata.xml", 0, "")
	if err != nil {
		return err
	}
	prefix, pin := pyStr(c.getOr("version_prefix", "")), r.pinned(it)
	var versions []string
	for _, m := range mavenVersion.FindAllStringSubmatch(strings.ToValidUTF8(string(data), "�"), -1) {
		if v := m[1]; strings.HasPrefix(v, prefix) && dotted.MatchString(v) && (pin == "" || v == pin) {
			versions = append(versions, v)
		}
	}
	if len(versions) == 0 {
		want := pin
		if want == "" {
			want = prefix + "*"
		}
		return fmt.Errorf("no release of %s matching '%s'", artifact, want)
	}
	v := newestVersion(versions)
	jar := artifact + "-" + v + ".jar"
	url := base + v + "/" + jar
	var checks [][2]string
	if sum, err := httpGet(url+".sha1", 0, ""); err == nil {
		if m := sha1RE.FindString(strings.ToValidUTF8(string(sum), "�")); m != "" {
			checks = append(checks, [2]string{"sha1", m})
		}
	}
	it.kind, it.dest, it.version = "files", "bin/"+it.id, v
	it.files = []*remoteFile{{name: jar, url: url, size: headSize(url), checks: checks}}
	return nil
}

func (r *resolver) npm(it *item) error {
	pkg, prefix := pyStr(need(it.cfg, "package")), pyStr(it.cfg.getOr("version_prefix", ""))
	v, err := httpJSON(npmURL+"/"+pkg, 180)
	if err != nil {
		return err
	}
	doc, _ := v.(*obj)
	pin := r.pinned(it)
	var versions []string
	for _, ver := range doc.child("versions").Keys() {
		if strings.HasPrefix(ver, prefix) && semver.MatchString(ver) && (pin == "" || ver == pin) {
			versions = append(versions, ver)
		}
	}
	if len(versions) == 0 {
		want := pin
		if want == "" {
			want = prefix + "*"
		}
		return fmt.Errorf("no version of %s matching '%s'", pkg, want)
	}
	ver := newestVersion(versions)
	dist := needObj(needObj(needObj(doc, "versions"), ver), "dist")
	var checks [][2]string
	if integrity := pyStr(dist.getOr("integrity", "")); strings.HasPrefix(integrity, "sha512-") {
		raw, err := base64.StdEncoding.DecodeString(integrity[7:])
		if err != nil {
			return fmt.Errorf("Incorrect padding")
		}
		checks = append(checks, [2]string{"sha512", hex.EncodeToString(raw)})
	} else if truthy(dist.get("shasum")) {
		checks = append(checks, [2]string{"sha1", pyStr(dist.get("shasum"))})
	}
	tarball := needStr(dist, "tarball")
	it.kind, it.dest, it.version = "archive", "maps/viewer/"+it.id, ver
	it.files = []*remoteFile{{name: it.id + "-" + ver + ".tgz", url: tarball, size: headSize(tarball), checks: checks}}
	return nil
}

func (r *resolver) githubArchive(it *item) error {
	repo, branch := pyStr(need(it.cfg, "repo")), pyStr(it.cfg.getOr("branch", "main"))
	sha := r.pinned(it)
	if sha == "" {
		v, err := httpJSON(githubAPI+"/repos/"+repo+"/commits/"+branch, 0)
		if err != nil {
			return err
		}
		sha = needStr(v, "sha")
	}
	it.kind, it.dest, it.version = "archive", "maps/viewer/"+it.id, clip(sha, 12)
	it.files = []*remoteFile{{name: it.id + "-" + clip(sha, 12) + ".tar.gz", url: githubWeb + "/" + repo + "/archive/" + sha + ".tar.gz"}}
	return nil
}

func (r *resolver) mapArea() (*obj, error) {
	m := mapsSettings(r.cfg)
	if truthy(m.get("region_error")) {
		return nil, errors.New(pyStr(m.get("region_error")))
	}
	return m, nil
}

func (r *resolver) protomaps(it *item) error {
	m, err := r.mapArea()
	if err != nil {
		return err
	}
	v, err := httpJSON(protomapsBuilds, 0)
	if err != nil {
		return err
	}
	all, _ := v.([]any)
	var builds []*obj
	for _, b := range all {
		if o, ok := b.(*obj); ok && strings.HasSuffix(pyStr(o.getOr("key", "")), ".pmtiles") {
			builds = append(builds, o)
		}
	}
	major := pyStr(it.cfg.getOr("tiles_major", "4")) + "."
	var usable []*obj
	for _, b := range builds {
		if strings.HasPrefix(pyStr(b.getOr("version", major)), major) {
			usable = append(usable, b)
		}
	}
	if len(usable) == 0 {
		usable = builds
	}
	if len(usable) == 0 {
		return errors.New("no Protomaps map build listed")
	}
	latest := usable[0]
	for _, b := range usable[1:] {
		if needStr(b, "key") > needStr(latest, "key") {
			latest = b
		}
	}
	key := needStr(latest, "key")
	var roadBytes int64
	if roads := r.resolved["routing"]; roads != nil && len(roads.files) > 0 {
		roadBytes = roads.files[0].size
	}
	bbox, err := floats(m.get("detail_bbox"))
	if err != nil {
		return err
	}
	est := tilesEstimate(bbox, intOr(m.get("detail_maxzoom"), 15), roadBytes)
	it.kind, it.dest = "custom", "maps/tiles"
	it.version = strings.ReplaceAll(key, ".pmtiles", "") + " " + pyStr(m.get("label"))
	// a different area is a new map, even from the same build
	area := make([]any, len(bbox))
	for i, x := range bbox {
		area[i] = x
	}
	it.extra.set("area", []any{area, intOr(m.get("world_maxzoom"), 7), intOr(m.get("detail_maxzoom"), 15)})
	it.files = []*remoteFile{{name: "basemap.pmtiles", url: protomapsBuildBase + "/" + key, estimate: est}}
	return nil
}

func floats(v any) ([]float64, error) {
	l, ok := v.([]any)
	if !ok {
		return nil, fmt.Errorf("'%s' object is not iterable", pyType(v))
	}
	out := make([]float64, len(l))
	for i, x := range l {
		f, ok := asNumber(x)
		if s, isStr := x.(string); isStr {
			var err error
			if f, err = strconv.ParseFloat(strings.TrimSpace(s), 64); err != nil {
				return nil, fmt.Errorf("could not convert string to float: '%s'", s)
			}
			ok = true
		}
		if !ok {
			return nil, fmt.Errorf("float() argument must be a string or a number, not '%s'", pyType(x))
		}
		out[i] = f
	}
	return out, nil
}

func (r *resolver) routing(it *item) error {
	if _, err := r.mapArea(); err != nil {
		return err
	}
	latest := pyStr(need(it.cfg, "url"))
	url, h, err := geofabrikHead(latest)
	if err != nil {
		return err
	}
	size := contentLength(h)
	it.kind, it.dest = "custom", "maps/routing"
	// which extract it is, then its date: another place's road data is new even on the same day
	day := httpDay(h)
	if day == "" {
		day = sizeOrNone(size)
	}
	it.version = strings.ReplaceAll(latest[strings.LastIndexByte(latest, '/')+1:], "-latest.osm.pbf", "") + " " + day
	gh := r.resolved["graphhopper"]
	if gh != nil && gh.err == "" {
		it.extra.set("gh_version", gh.version)
	} else {
		it.extra.set("gh_version", "")
	}
	it.files = []*remoteFile{{name: "region.osm.pbf", url: url, size: size, md5Sidecar: true}}
	return nil
}

// sizeOrNone is a size as Python showed one that might be None.
func sizeOrNone(n int64) string {
	if n == 0 {
		return "None"
	}
	return strconv.FormatInt(n, 10)
}

func (r *resolver) photonDB(it *item) error {
	if _, err := r.mapArea(); err != nil {
		return err
	}
	cc := strings.ToLower(pyStr(it.cfg.getOr("country", "us")))
	base := strings.TrimRight(photonDumps, "/") + "/"
	page, err := httpGet(base, 0, "")
	if err != nil {
		return err
	}
	var top []photonRow
	for _, row := range photonRegions(strings.ToValidUTF8(string(page), "�")) {
		if contains(row.codes, cc) {
			top = append(top, row)
		}
	}
	if len(top) == 0 {
		return fmt.Errorf("no Photon download covers country code '%s'", cc)
	}
	row := top[0]
	path, hasDB := []string{row.slug}, row.db
	if !(len(row.codes) == 1 && row.codes[0] == cc) { // a continent: look for the country inside it
		sub, err := httpGet(base+row.slug+"/", 0, "")
		if err != nil {
			return err
		}
		for _, in := range photonRegions(strings.ToValidUTF8(string(sub), "�")) {
			if contains(in.codes, cc) {
				if in.db {
					path, hasDB = []string{row.slug, in.slug}, true
				}
				break
			}
		}
	}
	if !hasDB {
		return fmt.Errorf("no ready-made Photon database for '%s' (only a JSON dump); see the Photon docs", cc)
	}
	folder := base + strings.Join(path, "/") + "/"
	last := path[len(path)-1]
	var wanted []string
	if photon := r.resolved["photon"]; photon != nil && photon.version != "" && photon.err == "" {
		parts := strings.Split(strings.TrimLeft(photon.version, "v"), ".")
		wanted = append(wanted, strings.Join(parts[:min(2, len(parts))], "."))
	}
	if listing, err := httpGet(folder, 0, ""); err == nil { // versions the folder actually offers, newest first
		re := regexp.MustCompile(`photon-db-` + regexp.QuoteMeta(last) + `-(\d+\.\d+)-latest\.tar\.bz2`)
		var found []string
		for _, m := range re.FindAllStringSubmatch(strings.ToValidUTF8(string(listing), "�"), -1) {
			if !contains(found, m[1]) {
				found = append(found, m[1])
			}
		}
		sort.SliceStable(found, func(a, b int) bool { return compareVersions(found[a], found[b]) > 0 })
		for _, v := range found {
			if !contains(wanted, v) {
				wanted = append(wanted, v)
			}
		}
	}
	for _, v := range []string{"1.0", "0.7"} {
		if !contains(wanted, v) {
			wanted = append(wanted, v)
		}
	}
	for _, ver := range wanted {
		url := folder + "photon-db-" + last + "-" + ver + "-latest.tar.bz2"
		h, err := httpHead(url)
		if err != nil {
			continue
		}
		size := contentLength(h)
		day := httpDay(h)
		if day == "" {
			day = sizeOrNone(size)
		}
		it.kind, it.dest = "custom", "maps/geocoder"
		it.version = last + " " + ver + "/" + day
		it.extra.set("db_version", ver)
		it.files = []*remoteFile{{name: url[strings.LastIndexByte(url, '/')+1:], url: url, size: size, md5Sidecar: true}}
		return nil
	}
	return fmt.Errorf("couldn't find a Photon database file in %s for version(s) %s", folder, strings.Join(wanted, ", "))
}

// geofabrikHead is a road data file's address and headers. Geofabrik's -latest sends you on to the day's file
// (name-YYMMDD), which can be missing while they publish it: then the newest of the week before.
func geofabrikHead(url string) (string, map[string]string, error) {
	h, first := httpHead(url)
	if first == nil {
		return url, h, nil
	}
	if !strings.HasSuffix(url, "-latest.osm.pbf") {
		return "", nil, first
	}
	for days := 1; days < 8; days++ {
		dated := strings.TrimSuffix(url, "-latest.osm.pbf") + time.Now().AddDate(0, 0, -days).Format("-060102.osm.pbf")
		if h, err := httpHead(dated); err == nil {
			return dated, h, nil
		}
	}
	return "", nil, first
}

// tilesEstimate is the rough size of the map tiles: about 1 GB of world overview, plus street detail at about 40 MB
// per square degree where streets are dense. A big, mostly empty area (a desert state's box) is capped at twice its
// road data.
func tilesEstimate(bbox []float64, maxzoom int64, roadBytes int64) int64 {
	if len(bbox) != 4 {
		panic(badAnswer{fmt.Sprintf("expected 4 values in detail_bbox, got %d", len(bbox))})
	}
	w, s, e, n := bbox[0], bbox[1], bbox[2], bbox[3]
	detail := math.Abs(e-w) * math.Abs(n-s) * math.Cos((n+s)/2*(math.Pi/180)) * 40e6
	if roadBytes > 0 {
		detail = math.Min(detail, 2*float64(roadBytes))
	}
	return int64(GB + detail*math.Pow(0.4, float64(max(0, 15-maxzoom))))
}

// httpDay is the date a remote file was last changed (from HTTP headers), for use as its version.
func httpDay(h map[string]string) string {
	if lm := h["last-modified"]; lm != "" {
		if t, err := http.ParseTime(lm); err == nil {
			return t.Format("2006-01-02")
		}
		if t, err := mail.ParseDate(lm); err == nil {
			return t.Format("2006-01-02")
		}
		return lm
	}
	return h["etag"]
}

var digitRuns = regexp.MustCompile(`\d+`)

// compareInts compares two lists of whole numbers, as Python compares tuples of them.
func compareInts(a, b []string) int {
	for i := 0; i < len(a) && i < len(b); i++ {
		x, y := strings.TrimLeft(a[i], "0"), strings.TrimLeft(b[i], "0")
		if len(x) != len(y) {
			if len(x) < len(y) {
				return -1
			}
			return 1
		}
		if x != y {
			if x < y {
				return -1
			}
			return 1
		}
	}
	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	}
	return 0
}

// compareVersions compares versions by their numbers (version_key).
func compareVersions(a, b string) int {
	return compareInts(digitRuns.FindAllString(a, -1), digitRuns.FindAllString(b, -1))
}

// newestVersion is max(versions, key=version_key): the first of the newest.
func newestVersion(versions []string) string {
	best := versions[0]
	for _, v := range versions[1:] {
		if compareVersions(v, best) > 0 {
			best = v
		}
	}
	return best
}

type photonRow struct {
	slug  string
	db    bool
	codes []string
}

var (
	trRE   = regexp.MustCompile(`(?is)<tr[^>]*>(.*?)</tr>`)
	cellRE = regexp.MustCompile(`(?is)<t[dh][^>]*>(.*?)</t[dh]>`)
	tagRE  = regexp.MustCompile(`<[^>]+>`)
	linkRE = regexp.MustCompile(`href="([^"]+)"`)
)

// photonRegions are the rows of the region table on Photon's download pages: region, has a DB dump, ISO country codes.
func photonRegions(html string) []photonRow {
	var rows []photonRow
	for _, tr := range trRE.FindAllStringSubmatch(html, -1) {
		var cells []string
		for _, c := range cellRE.FindAllStringSubmatch(tr[1], -1) {
			cells = append(cells, c[1])
		}
		if len(cells) < 3 {
			continue
		}
		text := strings.TrimSpace(tagRE.ReplaceAllString(cells[0], ""))
		slug := ""
		if m := linkRE.FindStringSubmatch(cells[0]); m != nil {
			parts := strings.Split(strings.Trim(strings.ReplaceAll(m[1], "index.html", ""), "/"), "/")
			slug = parts[len(parts)-1]
		}
		if slug == "" {
			slug = text
		}
		slug = strings.ReplaceAll(strings.ToLower(slug), " ", "-")
		if slug == "" || slug == "region" {
			continue
		}
		var codes []string
		for _, c := range strings.Split(tagRE.ReplaceAllString(cells[2], ""), ",") {
			if c = strings.TrimSpace(c); c != "" {
				codes = append(codes, strings.ToLower(c))
			}
		}
		rows = append(rows, photonRow{slug, strings.Contains(cells[1], "✓") || strings.Contains(cells[1], "&#10003;"), codes})
	}
	return rows
}

// selectHFFiles picks the files matching each pattern; each must match exactly one file (or one split model).
func selectHFFiles(tree []*obj, patterns []string, repo string) ([]*obj, error) {
	var chosen, files []*obj
	for _, f := range tree {
		if pyEqual(f.get("type"), "file") {
			files = append(files, f)
		}
	}
	base := func(p string) string { return p[strings.LastIndexByte(p, '/')+1:] }
	for _, pattern := range patterns {
		var hits []*obj
		if strings.Contains(pattern, "/") {
			for _, f := range files {
				if fnmatch(needStr(f, "path"), pattern) {
					hits = append(hits, f)
				}
			}
		} else { // top-level files first; look in subfolders (e.g. split models) only if nothing matches
			for _, f := range files {
				if p := needStr(f, "path"); !strings.Contains(p, "/") && fnmatch(p, pattern) {
					hits = append(hits, f)
				}
			}
			if len(hits) == 0 {
				for _, f := range files {
					if fnmatch(base(needStr(f, "path")), pattern) {
						hits = append(hits, f)
					}
				}
			}
		}
		if len(hits) == 0 {
			var ggufs []string
			for _, f := range files {
				if p := needStr(f, "path"); strings.HasSuffix(p, ".gguf") {
					ggufs = append(ggufs, p)
				}
			}
			sort.Strings(ggufs)
			return nil, fmt.Errorf("pattern '%s' matched no file in %s. Available: %s", pattern, repo, strings.Join(ggufs, ", "))
		}
		if len(hits) > 1 {
			shards := true
			var names []string
			for _, h := range hits {
				names = append(names, needStr(h, "path"))
				shards = shards && shardRE.MatchString(needStr(h, "path"))
			}
			if !shards {
				return nil, fmt.Errorf("pattern '%s' is ambiguous in %s: %s", pattern, repo, strings.Join(names, ", "))
			}
		}
		chosen = append(chosen, hits...)
	}
	return chosen, nil
}

var nextLink = regexp.MustCompile(`<([^>]+)>;\s*rel="next"`)

func hfTree(repo, rev string) ([]*obj, error) {
	var out []*obj
	url := hfURL + "/api/models/" + repo + "/tree/" + rev + "?recursive=True&expand=False"
	tmp, err := os.MkdirTemp("", "tinfoilkit-")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(tmp)
	headers := filepath.Join(tmp, "headers")
	for url != "" { // a long list comes in pages, each naming the next in its Link header
		data, err := httpGet(url, 0, headers)
		if err != nil {
			return nil, err
		}
		v, err := parseJSON(data)
		if err != nil {
			return nil, err
		}
		l, ok := v.([]any)
		if !ok {
			return nil, badAnswer{"can only concatenate list (not \"dict\") to list"}
		}
		for _, e := range l {
			if o, ok := e.(*obj); ok {
				out = append(out, o)
			}
		}
		h, _ := os.ReadFile(headers)
		url = ""
		if m := nextLink.FindStringSubmatch(strings.ToValidUTF8(string(h), "�")); m != nil {
			url = m[1]
		}
	}
	return out, nil
}

// parseKiwixCatalog reads the Kiwix catalog (OPDS, Atom): each book's file prefix (wikipedia_en_all_maxi) and its
// newest entry.
func parseKiwixCatalog(data []byte) (map[string]*obj, error) {
	best := map[string]*obj{}
	d := xml.NewDecoder(bytes.NewReader(data))
	depth := 0
	var info *obj
	var tag string
	var text strings.Builder
	textOpen := false
	for {
		tok, err := d.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		switch t := tok.(type) {
		case xml.StartElement:
			depth++
			textOpen = false
			switch depth {
			case 2:
				info = nil
				if strings.HasSuffix(t.Name.Local, "entry") {
					info = newObj()
				}
			case 3:
				if info == nil {
					break
				}
				tag = t.Name.Local
				attr := func(name string) (string, bool) {
					for _, a := range t.Attr {
						if a.Name.Space == "" && a.Name.Local == name {
							return a.Value, true
						}
					}
					return "", false
				}
				if typ, _ := attr("type"); tag == "link" && typ == "application/x-zim" {
					href, _ := attr("href")
					info.set("url", strings.SplitN(href, ".meta4", 2)[0])
					length, _ := attr("length")
					if n, err := strconv.ParseInt(strings.TrimSpace(length), 10, 64); err == nil && n != 0 {
						info.set("size", n)
					} else {
						info.set("size", nil)
					}
				} else if contains([]string{"title", "summary", "language", "category", "name", "flavour"}, tag) {
					text.Reset()
					textOpen = true
				}
			}
		case xml.CharData:
			if textOpen && depth == 3 {
				text.Write(t)
			}
		case xml.EndElement:
			if depth == 3 && info != nil && contains([]string{"title", "summary", "language", "category", "name", "flavour"}, tag) {
				info.set(tag, strings.TrimSpace(text.String()))
				tag = ""
			}
			if depth == 2 && info != nil {
				addCatalogEntry(best, info)
				info = nil
			}
			textOpen = false
			depth--
		}
	}
	return best, nil
}

func addCatalogEntry(best map[string]*obj, info *obj) {
	url := info.str("url")
	if url == "" {
		return
	}
	trimmed := strings.TrimRight(url, "/")
	fname := unquote(trimmed[strings.LastIndexByte(trimmed, '/')+1:])
	m := zimRE.FindStringSubmatch(fname)
	if m == nil {
		return
	}
	info.set("file", fname)
	info.set("prefix", m[1])
	info.set("date", m[2])
	// order: where the book first came in the catalog, which ./kit search lists in for books of one size
	if cur := best[m[1]]; cur == nil {
		info.set("order", len(best))
		best[m[1]] = info
	} else if m[2] > cur.str("date") {
		info.set("order", cur.get("order"))
		best[m[1]] = info
	}
}

// ----------------------------------------------------------------------------- names and addresses

// fnmatch is Python's fnmatch.fnmatch: * and ? match anything (/ too), [abc] and [!abc] a character. Windows
// ignores case.
func fnmatch(name, pattern string) bool {
	if windows {
		name, pattern = strings.ToLower(strings.ReplaceAll(name, "/", `\`)), strings.ToLower(strings.ReplaceAll(pattern, "/", `\`))
	}
	return fnmatchRE(pattern).MatchString(name)
}

var fnmatchCache = map[string]*regexp.Regexp{}

func fnmatchRE(pat string) *regexp.Regexp {
	if re, ok := fnmatchCache[pat]; ok {
		return re
	}
	var b strings.Builder
	b.WriteString(`(?s)^`)
	runes := []rune(pat)
	for i := 0; i < len(runes); i++ {
		c := runes[i]
		switch c {
		case '*':
			b.WriteString(`.*`)
		case '?':
			b.WriteString(`.`)
		case '[':
			j := i + 1
			if j < len(runes) && runes[j] == '!' {
				j++
			}
			if j < len(runes) && runes[j] == ']' {
				j++
			}
			for j < len(runes) && runes[j] != ']' {
				j++
			}
			if j >= len(runes) {
				b.WriteString(`\[`)
				continue
			}
			stuff := string(runes[i+1 : j])
			i = j
			if strings.HasPrefix(stuff, "!") {
				stuff = "^" + stuff[1:]
			} else if strings.HasPrefix(stuff, "^") {
				stuff = `\` + stuff
			}
			stuff = strings.ReplaceAll(stuff, `\`, `\\`)
			if strings.HasPrefix(stuff, `\\^`) {
				stuff = `\^` + stuff[3:]
			}
			b.WriteString("[" + strings.ReplaceAll(stuff, "[", `\[`) + "]")
		default:
			b.WriteString(regexp.QuoteMeta(string(c)))
		}
	}
	b.WriteString(`$`)
	re, err := regexp.Compile(b.String())
	if err != nil {
		re = regexp.MustCompile(`^` + regexp.QuoteMeta(pat) + `$`)
	}
	fnmatchCache[pat] = re
	return re
}

// quote is urllib.parse.quote: everything but letters, digits, _.-~ and the safe characters as %XX.
func quote(s, safe string) string {
	var b strings.Builder
	for _, c := range []byte(s) {
		if c < 0x80 && (c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || strings.IndexByte("_.-~", c) >= 0 ||
			strings.IndexByte(safe, c) >= 0) {
			b.WriteByte(c)
		} else {
			fmt.Fprintf(&b, "%%%02X", c)
		}
	}
	return b.String()
}

// unquote is urllib.parse.unquote: %XX sequences decoded as UTF-8.
func unquote(s string) string {
	if !strings.Contains(s, "%") {
		return s
	}
	var raw []byte
	for i := 0; i < len(s); i++ {
		if s[i] == '%' && i+2 < len(s) {
			if b, err := hex.DecodeString(s[i+1 : i+3]); err == nil {
				raw = append(raw, b[0])
				i += 2
				continue
			}
		}
		raw = append(raw, s[i])
	}
	if utf8.Valid(raw) {
		return string(raw)
	}
	return strings.ToValidUTF8(string(raw), "�")
}

// ----------------------------------------------------------------------------- planning

func evaluate(it *item, state *obj, root string) {
	if it.err != "" {
		it.status = "error"
		return
	}
	st := stateItems(state).child(it.key())
	if it.kind == "custom" {
		d := filepath.Join(dlDir(root), filepath.FromSlash(it.dest))
		ok := st != nil && pyEqual(st.get("version"), it.version)
		switch it.typ() {
		case "routing":
			ok = ok && exists(filepath.Join(d, "graph-cache", "properties")) &&
				(!truthy(it.extra.get("gh_version")) || pyEqual(st.get("gh_version"), it.extra.get("gh_version")))
		case "photon_db":
			ok = ok && isDir(filepath.Join(d, "photon_data"))
		default:
			for _, f := range it.files {
				ok = ok && exists(filepath.Join(d, f.name))
			}
		}
		if it.extra.has("area") {
			ok = ok && pyEqual(st.get("area"), it.extra.get("area"))
		}
		it.need = nil
		if !ok {
			it.need = append(it.need, it.files...)
		}
		it.status = "ok"
		if !ok {
			it.status = map[bool]string{true: "update", false: "new"}[st != nil]
		}
		return
	}
	if it.kind == "archive" {
		cur := st.get("current")
		target := filepath.Join(dlDir(root), filepath.FromSlash(it.dest), safeName(pyStrOr(cur)))
		binary := pyStr(orEmpty(it.cfg.get("binary")))
		ok := pyEqual(cur, it.version) && isDir(target) && !emptyDir(target) && (binary == "" || findBinary(target, binary) != "")
		it.need = nil
		if !ok {
			it.need = append(it.need, it.files...)
		}
	} else {
		filesState := st.child("files")
		it.need = nil
		if it.typ() == "url" && st != nil && !pyEqual(st.get("version"), it.version) {
			filesState = nil // plain URL with no checksum: a changed ETag/date means a new file
		}
		for _, f := range it.files {
			fs, have := filesState.lookup(f.name)
			fso, _ := fs.(*obj)
			path := filepath.Join(dlDir(root), filepath.FromSlash(it.dest), f.name)
			sameHash := have && fs != nil && (f.sha256 == "" || pyEqual(fso.get("sha256"), f.sha256))
			size := f.size // a book's exact size is known once it's downloaded
			if size == 0 {
				size = intOr(fso.get("size"), 0)
			}
			sameSize := exists(path) && (size == 0 || fileSize(path) == size)
			if !(sameHash && sameSize) {
				it.need = append(it.need, f)
			}
		}
	}
	it.status = "ok"
	if len(it.need) > 0 {
		it.status = map[bool]string{true: "update", false: "new"}[st != nil]
	}
}

// pyStrOr is a value as a string, or "" for None.
func pyStrOr(v any) string {
	if v == nil {
		return ""
	}
	return pyStr(v)
}

func emptyDir(p string) bool {
	f, err := os.Open(p)
	if err != nil {
		return true
	}
	defer f.Close()
	names, _ := f.Readdirnames(1)
	return len(names) == 0
}

// naive is a time as Python's naive datetimes have it: the clock's reading, with no time zone to shift it.
func naive(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC)
}

// parseISO reads a time the kit wrote (datetime.isoformat), as a naive time.
func parseISO(s string) (time.Time, error) {
	for _, layout := range []string{"2006-01-02T15:04:05", "2006-01-02T15:04:05.999999", "2006-01-02 15:04:05",
		"2006-01-02T15:04", "2006-01-02"} {
		if t, err := time.Parse(layout, s); err == nil {
			return t, nil
		}
	}
	return time.Time{}, fmt.Errorf("Invalid isoformat string: '%s'", s)
}

// hold: a book with refresh_days in kit.json keeps the edition it has until that one is so many days old: a new
// Wikipedia every few weeks isn't worth 115 GB each time. Naming it in --only gets the new edition now.
func hold(it *item, state *obj, root string, only []string) {
	days, isInt := it.cfg.get("refresh_days").(json.Number)
	st := stateItems(state).child(it.key())
	if st == nil {
		st = newObj()
	}
	if it.section != "library" || it.status != "update" || !isInt || strings.ContainsAny(string(days), ".eE") || len(only) > 0 {
		return
	}
	updated, ok := st.get("updated").(string)
	if !ok {
		return
	}
	t, err := parseISO(updated)
	if err != nil {
		return
	}
	n, _ := strconv.Atoi(string(days))
	due := t.AddDate(0, 0, n)
	if !due.After(naive(time.Now())) || !truthy(st.get("files")) {
		return
	}
	dest := pyStr(st.getOr("dest", it.dest))
	for _, name := range st.child("files").Keys() {
		if !isFile(filepath.Join(dlDir(root), filepath.FromSlash(dest), name)) {
			return
		}
	}
	it.status, it.need = "later", nil
	it.extra.set("due", due.Format("2006-01-02"))
}

var unsafeChars = regexp.MustCompile(`[^A-Za-z0-9._-]+`)

func safeName(s string) string {
	if s == "" {
		s = "unknown"
	}
	return unsafeChars.ReplaceAllString(s, "_")
}

// findBinary is the first file with this name in base or a folder in it, by path.
func findBinary(base, name string) string {
	if name == "" || !exists(base) {
		return ""
	}
	var hits []string
	filepath.WalkDir(base, func(p string, d os.DirEntry, err error) error {
		if err == nil && p != base && sameName(d.Name(), name) {
			hits = append(hits, p)
		}
		return nil
	})
	sortPaths(hits)
	for _, p := range hits {
		if isFile(p) {
			return p
		}
	}
	return ""
}

func sameName(a, b string) bool {
	if windows {
		return strings.EqualFold(a, b)
	}
	return a == b
}

// sortPaths sorts paths part by part, as Python sorts Path objects.
func sortPaths(paths []string) {
	key := func(p string) []string {
		if windows {
			p = strings.ToLower(p)
		}
		return strings.FieldsFunc(p, func(r rune) bool { return r == '/' || r == filepath.Separator })
	}
	sort.SliceStable(paths, func(a, b int) bool {
		ka, kb := key(paths[a]), key(paths[b])
		for i := 0; i < len(ka) && i < len(kb); i++ {
			if ka[i] != kb[i] {
				return ka[i] < kb[i]
			}
		}
		return len(ka) < len(kb)
	})
}

// essential is what the kit can't do without: the programs, the map, the most important books, and the AI model
// this computer runs plus the smallest one. SETUP's first run downloads and checks these first, so the kit works
// hours sooner. Anything marked "essential": true counts too: ./kit pick marks what someone asks for by name (SETUP
// --add).
func essential(it *item, fit *obj) bool {
	if isTrue(it.cfg.get("essential")) {
		return true
	}
	if it.section == "models" {
		return pyEqual(fit.get("runs"), it.id) || pyEqual(fit.get("smallest"), it.id)
	}
	if truthy(it.cfg.get("wide")) { // address search for a whole region of the world, tens of GB
		return false
	}
	return it.section == "runtimes" || it.section == "maps" || (it.section == "library" && it.priority() <= 1)
}

var starterMaps = []string{"maplibre-gl", "protomaps-basemaps", "basemaps-assets", "basemap"}

// starterPart is the try-it kit, a few GB that SETUP gets first so the kit can be tried within minutes: this
// computer's programs (not Java, which only the map's address search and directions use), the AI and books marked
// "starter": true in kit.json, and the area's map without address search or directions. What it gets that kit.json
// doesn't switch on is a sample, and goes once a full sync has the rest (dropSamples).
func starterPart(it *item) bool {
	switch it.section {
	case "runtimes":
		return strings.HasSuffix(it.id, "-"+platformTag()) && it.cfg.get("starter") != false
	case "maps":
		return contains(starterMaps, it.id)
	}
	return isTrue(it.cfg.get("starter"))
}

// starterItems are the try-it kit's items, its samples switched on. A part kit.json switches off entirely (no AI,
// no books) stays out of it too.
func starterItems(items []*item) []*item {
	some := map[string]bool{}
	for _, i := range items {
		if (i.section == "models" || i.section == "library") && i.enabled() {
			some[i.section] = true
		}
	}
	var out []*item
	for _, i := range items {
		if starterPart(i) && (i.section != "models" && i.section != "library" || some[i.section]) {
			if !i.enabled() && isTrue(i.cfg.get("starter")) {
				i.cfg = with(i.cfg, "enabled", true)
			}
			out = append(out, i)
		}
	}
	return out
}

// dropSamples: once a full sync has everything, the try-it kit's samples go: what a try-it sync downloaded (marked
// "sample" in state.json) that kit.json doesn't switch on. What it does switch on stays for good, and a Wikipedia
// standing in for kit.json's (wikiStandIns) stays while it does.
func dropSamples(root string, state, cfg *obj, items []*item) {
	on, planned := map[string]bool{}, map[string]bool{}
	for _, i := range itemsFromConfig(cfg) {
		if i.enabled() {
			on[i.key()] = true
		}
	}
	for _, i := range items {
		if i.enabled() {
			planned[i.key()] = true
		}
	}
	all := stateItems(state)
	for _, key := range all.Keys() {
		v := all.child(key)
		if v == nil || !truthy(v.get("sample")) || (planned[key] && !on[key]) {
			continue
		}
		if on[key] || !v.has("files") {
			v.del("sample")
			continue
		}
		ident := strings.SplitN(key, "/", 2)[1]
		dest := filepath.Join(dlDir(root), filepath.FromSlash(pyStr(v.get("dest"))))
		var failed error
		for _, name := range v.child("files").Keys() {
			if err := os.Remove(filepath.Join(dest, name)); err != nil && !errors.Is(err, os.ErrNotExist) {
				failed = err
				break
			}
		}
		if failed != nil { // open in the kit, on Windows: the next sync tries again
			log(fmt.Sprintf("Couldn't remove %s from the try-it kit yet (%s). The next sync will.", ident, strerror(failed)))
			continue
		}
		os.Remove(dest) // a model's own folder, once it's empty
		all.del(key)
		log(fmt.Sprintf("Removed %s: the try-it kit had it, and it isn't in your picks.", ident))
	}
}

func buildPlan(root string, cfg, state *obj, only []string, essentials, starter bool) []*item {
	items := itemsFromConfig(cfg)
	if len(only) > 0 {
		var some []*item
		for _, i := range items {
			for _, o := range only {
				if strings.Contains(strings.ToLower(i.key()), strings.ToLower(o)) {
					some = append(some, i)
					break
				}
			}
		}
		items = some
	}
	if starter {
		items = starterItems(items)
	} else if essentials {
		fit := fitReport(root, cfg, state)
		var some []*item
		for _, i := range items {
			if essential(i, fit) {
				some = append(some, i)
			}
		}
		items = some
	}
	if (starter || essentials) && len(only) == 0 {
		have := map[string]bool{}
		for _, i := range items {
			have[i.key()] = true
		}
		t := "essentials"
		if starter {
			t = "starter"
		}
		for _, e := range wikiStandIns(cfg, state, t) {
			if zim := e.str("zim"); !have["library/"+zim] {
				items = append(items, newItem("library", zim, with(newObj("type", "zim"), kvs(e)...)))
			}
		}
	}
	r := newResolver(root, cfg)
	var active []*item
	for _, i := range items {
		if i.enabled() {
			active = append(active, i)
		}
	}
	log(fmt.Sprintf("Checking %d items for updates...", len(active)))
	tty := isTerminal(os.Stdout)
	for n, it := range active {
		if tty {
			out(clip(padRight(fmt.Sprintf("  [%d/%d] %s", n+1, len(active), it.key()), 78), 78) + "\r")
		}
		r.resolve(it)
		evaluate(it, state, root)
		hold(it, state, root, only)
	}
	// Photon only opens address databases made for its own version: use the release that matches the database
	var geo *item
	for _, i := range active {
		if i.typ() == "photon_db" && i.err == "" {
			geo = i
			break
		}
	}
	photon := r.resolved["photon"]
	if geo != nil && truthy(geo.extra.get("db_version")) && photon != nil && photon.err == "" {
		want := pyStr(geo.extra.get("db_version"))
		if !strings.HasPrefix(strings.TrimLeft(photon.version, "v"), want+".") {
			if r.pinGitHub(photon, want+".") {
				evaluate(photon, state, root)
			} else {
				log("WARNING: no Photon release matches the address database version " + want + "; address search may not start")
			}
		}
	}
	if tty {
		out(strings.Repeat(" ", 78) + "\r")
	}
	return items
}

// padRight pads s with spaces to n characters, as Python's ljust and :<n do.
func padRight(s string, n int) string {
	if c := utf8.RuneCountInString(s); c < n {
		return s + strings.Repeat(" ", n-c)
	}
	return s
}

func padLeft(s string, n int) string {
	if c := utf8.RuneCountInString(s); c < n {
		return strings.Repeat(" ", n-c) + s
	}
	return s
}

// offline: every lookup failed: no internet, or a Wi-Fi sign-in page answering instead.
func offline(items []*item) bool {
	n := 0
	for _, i := range items {
		if i.enabled() {
			if i.status != "error" {
				return false
			}
			n++
		}
	}
	return n > 1
}

func printPlan(root string, items []*item, state, cfg *obj) {
	free, _ := diskUsage(root)
	var total int64
	labels := map[string]string{"ok": "ok      ", "new": "NEW     ", "update": "UPDATE  ", "later": "later   ", "error": "ERROR   "}
	for _, section := range sections {
		var group []*item
		for _, i := range items {
			if i.section == section && i.enabled() {
				group = append(group, i)
			}
		}
		if len(group) == 0 {
			continue
		}
		log("\n[" + section + "]")
		sort.SliceStable(group, func(a, b int) bool {
			if group[a].priority() != group[b].priority() {
				return group[a].priority() < group[b].priority()
			}
			return pyLower(group[a].id) < pyLower(group[b].id)
		})
		for _, i := range group {
			need := i.needBytes(root)
			total += need
			var detail string
			old := stateItems(state).child(i.key()).get("version")
			switch i.status {
			case "error":
				detail = i.err
			case "ok":
				detail = i.version
			case "later":
				detail = fmt.Sprintf("%s   (%s waits until %s)", pyStr(old), i.version, pyStr(i.extra.get("due")))
			default:
				arrow := i.version
				if truthy(old) && !pyEqual(old, i.version) {
					arrow = pyStr(old) + " -> " + i.version
				}
				size := fmtBytes(need)
				for _, f := range i.need {
					if f.size == 0 { // some sizes are only known after downloading
						size = "?"
						if need > 0 {
							size = "~" + fmtBytes(need)
						}
						break
					}
				}
				detail = padLeft(size, 9) + "   " + arrow
			}
			label, ok := labels[i.status]
			if !ok {
				label = i.status
			}
			log("  " + label + padRight(clip(i.id, 44), 46) + detail)
		}
	}
	later := false
	var disabled, kept []string
	var keptBytes int64
	for _, i := range items {
		if i.enabled() && i.status == "later" {
			later = true
		}
		if !i.enabled() {
			disabled = append(disabled, i.id)
			if rec := stateItems(state).child(i.key()); rec != nil {
				kept = append(kept, i.id)
				keptBytes += driveBytes(rec)
			}
		}
	}
	if later {
		log("\n  later: a big book keeps the edition it has until its refresh_days in kit.json pass. " +
			"To get the new one now:  ./kit sync --only NAME")
	}
	if len(disabled) > 0 {
		log(fmt.Sprintf("\n  (%d disabled in kit.json: %s)", len(disabled), strings.Join(disabled, ", ")))
	}
	if len(kept) > 0 {
		log(fmt.Sprintf("  Still in the kit, switched off: %s (%s). To free the space: ./kit remove NAME",
			strings.Join(kept, ", "), fmtSize(float64(keptBytes))))
	}
	if offline(items) {
		log("\nNothing could be looked up. Check that this computer is online (on hotel or cafe Wi-Fi, " +
			"open any web page and sign in first), then try again.")
		return
	}
	keep, leave := keepFree(root, cfg), leaveFree(root, cfg)
	log(fmt.Sprintf("\nTo download: %s   Free space: %s   Free afterwards: ~%s (before old versions are removed)",
		fmtBytes(total), fmtBytes(free), fmtBytes(max(0, free-total))))
	if total > 0 {
		if took := eta(root, float64(total)); took != "" {
			log("That takes " + took + ".")
		}
	}
	if isTrue(cfg.child("settings").get("essentials_only")) {
		log("Just the essentials, as chosen at setup. To get everything else too: ./kit essentials off")
	}
	if float64(free-total) < keep {
		log("WARNING: that leaves less than the " + fmtSize(keep) + " the kit keeps free. Items that don't fit " +
			"are skipped, the most important ones download first. Switch some off in kit.json, ./kit essentials on " +
			"for just the essentials, or make room.")
	} else if float64(free-total) < leave {
		pct := 5
		if onThisComputer(root) {
			pct = 10
		}
		log(fmt.Sprintf("Note: that leaves less than %s free, the %d%% of the disk worth keeping free. Switch some "+
			"off in kit.json, or ./kit essentials on for just the essentials.", fmtSize(leave), pct))
	}
}

// pyLower is str.lower() for sorting by.
func pyLower(s string) string { return strings.ToLower(s) }

// onThisComputer is true when the kit is on the computer's own disk (the one with the home folder), not on a drive.
func onThisComputer(root string) bool {
	home, err := os.UserHomeDir()
	if err != nil {
		return false
	}
	return sameDevice(root, home)
}

// keepFree is the bytes to leave free. The computer's own disk keeps more, so it still has room for system updates.
func keepFree(root string, cfg *obj) float64 { return keepFreeOn(onThisComputer(root), cfg) }

func keepFreeOn(computer bool, cfg *obj) float64 {
	s := cfg.child("settings")
	gb := floatOr(s.getOr("keep_free_gb", 25), 25)
	if computer {
		gb = math.Max(gb, floatOr(s.getOr("keep_free_gb_this_computer", 50), 50))
	}
	return gb * GB
}

// leaveFree is the bytes a comfortable install leaves free: 10% of the computer's own disk, 5% of a drive, or what
// the kit keeps free if that's more. SETUP steers people away from going below it; sync itself stops only at
// keepFree.
func leaveFree(root string, cfg *obj) float64 {
	_, total := diskUsage(root)
	return leaveFreeOn(onThisComputer(root), total, cfg)
}

func leaveFreeOn(computer bool, total int64, cfg *obj) float64 {
	share := 0.05
	if computer {
		share = 0.10
	}
	return math.Max(keepFreeOn(computer, cfg), float64(total)*share)
}

// room is how need bytes fit in free ones: "fits" (leaving leave), "tight" (fits, but leaves less) or "no" (it
// would leave less than keep).
func room(free, need int64, keep, leave float64) string {
	switch {
	case float64(free-need) >= leave:
		return "fits"
	case float64(free-need) >= keep:
		return "tight"
	}
	return "no"
}

func ensureSpace(root string, need int64, cfg *obj) bool {
	free, _ := diskUsage(root)
	return float64(free-need) >= keepFree(root, cfg)
}
