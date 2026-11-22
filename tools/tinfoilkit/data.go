package main

// Keeping what the person writes on the kit page in the kit's data folder, which a new version never touches: the
// notes Ask hands the AI with every question (data/notes.txt) and the map's home and pins (data/places.json). Plain
// files, readable without the kit. This is tools/data.py, which a kit without this program runs: the same files,
// answers and checks, so tests/data_test.py checks both.
//
// It listens on 127.0.0.1 and answers the kit page only: another web page is turned away by its Origin, and any name
// but this computer's own (a website pointing a name of its own at 127.0.0.1) by its Host. Through the gate, the
// devices at home that have the access code reach it at /data/.

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"log"
	"math"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	maxNotes = 100000 // characters, pages of them; Ask hands the AI the first few thousand
	maxPins  = 1000
	maxSave  = 1000000 // bytes
)

var pinID = regexp.MustCompile(`^[A-Za-z0-9_-]{1,64}$`)

// turnedDown is an answer other than 200, with what to tell the page.
type turnedDown struct {
	status int
	msg    string
	extra  map[string]any
}

func (e *turnedDown) Error() string { return e.msg }

// notesStore is the two files. One lock, so two devices saving at once take turns.
type notesStore struct {
	notes, places string
	mu            sync.Mutex
}

func noteVersion(raw []byte) string {
	if len(raw) == 0 {
		return ""
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])[:16]
}

// writeWhole: all or nothing, so a crash or a pulled drive leaves the old file, never half of the new one. Into the
// data folder as it is: if it's gone (the kit was removed, the drive unplugged), the save fails instead of starting
// a new one.
func writeWhole(path string, data []byte) error {
	tmp := path + ".new"
	f, err := os.OpenFile(tmp, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return err
	}
	_, err = f.Write(data)
	if err == nil {
		err = f.Sync()
	}
	if cerr := f.Close(); err == nil {
		err = cerr
	}
	if err == nil {
		err = os.Rename(tmp, path)
	}
	if err != nil {
		os.Remove(tmp)
	}
	return err
}

// decodeJSON reads one JSON value and nothing after it, its numbers as written, so they're saved as they came.
func decodeJSON(b []byte) (any, error) {
	if !utf8.Valid(b) {
		return nil, errors.New("not UTF-8")
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var v any
	if err := d.Decode(&v); err != nil {
		return nil, err
	}
	if _, err := d.Token(); err != io.EOF {
		return nil, errors.New("more after the JSON")
	}
	return v, nil
}

func encodeJSON(v any, indent string) []byte {
	var buf bytes.Buffer
	e := json.NewEncoder(&buf)
	e.SetEscapeHTML(false)
	e.SetIndent("", indent)
	e.Encode(v)
	return buf.Bytes()
}

func number(v any, low, high float64) bool {
	n, ok := v.(json.Number)
	if !ok {
		return false
	}
	f, err := n.Float64()
	return err == nil && !math.IsNaN(f) && !math.IsInf(f, 0) && low <= f && f <= high
}

func textOK(v any, most int, needed bool) bool {
	s, ok := v.(string)
	return ok && utf8.RuneCountInString(s) <= most && (!needed || strings.TrimSpace(s) != "")
}

func spot(v any) bool {
	m, ok := v.(map[string]any)
	return ok && number(m["lat"], -90, 90) && number(m["lon"], -180, 180)
}

func pinOK(v any) bool {
	m, ok := v.(map[string]any)
	id, isText := m["id"].(string)
	return ok && spot(m) && isText && pinID.MatchString(id) && textOK(m["name"], 200, true)
}

func (s *notesStore) getNotes() (map[string]any, error) {
	raw, err := os.ReadFile(s.notes)
	if errors.Is(err, fs.ErrNotExist) {
		raw, err = nil, nil
	}
	if err != nil {
		return nil, err
	}
	text := strings.ToValidUTF8(strings.TrimPrefix(string(raw), "\ufeff"), "\ufffd") // (Notepad may add a BOM)
	return map[string]any{"text": text, "version": noteVersion(raw)}, nil
}

func (s *notesStore) putNotes(body map[string]any) (map[string]any, error) {
	since, ok := body["version"].(string)
	if !textOK(body["text"], maxNotes, false) || !ok {
		return nil, &turnedDown{400, "Notes are text, up to 100,000 characters, with the version the edit started from.", nil}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now, err := s.getNotes()
	if err != nil {
		return nil, err
	}
	if now["version"] != since {
		return nil, &turnedDown{409, "These notes changed on another device since this page loaded them.", now}
	}
	raw := []byte(body["text"].(string))
	if err := writeWhole(s.notes, raw); err != nil {
		return nil, err
	}
	return map[string]any{"text": string(raw), "version": noteVersion(raw)}, nil
}

// rawPlaces is places.json as it is, with anything else someone put in it, which a change keeps.
func (s *notesStore) rawPlaces() (map[string]any, error) {
	b, err := os.ReadFile(s.places)
	if errors.Is(err, fs.ErrNotExist) {
		return map[string]any{}, nil
	}
	if err != nil {
		return nil, err
	}
	v, _ := decodeJSON(bytes.TrimPrefix(b, []byte("\xef\xbb\xbf")))
	raw, ok := v.(map[string]any)
	if pins, has := raw["pins"]; ok && has {
		_, ok = pins.([]any)
	}
	if !ok {
		return nil, &turnedDown{500, s.places + " isn't in a shape the kit reads, so it leaves it as it is. Fix it in a " +
			"text editor, or move it out of the data folder to start again.", nil}
	}
	return raw, nil
}

func shownPlaces(raw map[string]any) map[string]any {
	var home any
	if spot(raw["home"]) {
		home = raw["home"]
	}
	pins := []any{}
	all, _ := raw["pins"].([]any)
	for _, p := range all {
		if pinOK(p) {
			pins = append(pins, p)
		}
	}
	return map[string]any{"home": home, "pins": pins}
}

func (s *notesStore) getPlaces() (map[string]any, error) {
	raw, err := s.rawPlaces()
	if err != nil {
		return nil, err
	}
	return shownPlaces(raw), nil
}

func (s *notesStore) changePlaces(change func(map[string]any) error) (map[string]any, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	raw, err := s.rawPlaces()
	if err != nil {
		return nil, err
	}
	if err := change(raw); err != nil {
		return nil, err
	}
	if err := writeWhole(s.places, encodeJSON(raw, " ")); err != nil {
		return nil, err
	}
	return shownPlaces(raw), nil
}

func (s *notesStore) putHome(body map[string]any) (map[string]any, error) {
	label, has := body["label"]
	if !has {
		label = ""
	}
	zoom, has := body["zoom"]
	if !has {
		zoom = json.Number("12")
	}
	if !spot(body) || !textOK(label, 200, false) || !number(zoom, 0, 22) {
		return nil, &turnedDown{400, "Home is a lat and lon, with a label and a zoom if you like.", nil}
	}
	home := map[string]any{"lat": body["lat"], "lon": body["lon"], "label": label, "zoom": zoom}
	return s.changePlaces(func(raw map[string]any) error {
		raw["home"] = home
		return nil
	})
}

func (s *notesStore) putPin(id string, body map[string]any) (map[string]any, error) {
	note, has := body["note"]
	if !has {
		note = ""
	}
	pin := map[string]any{"id": id, "name": body["name"], "note": note, "lat": body["lat"], "lon": body["lon"]}
	if !pinOK(pin) || !textOK(note, 5000, false) {
		return nil, &turnedDown{400, "A pin is a name (up to 200 characters), a note (up to 5,000), and a lat and lon.", nil}
	}
	return s.changePlaces(func(raw map[string]any) error {
		pins, _ := raw["pins"].([]any)
		for i, p := range pins {
			if m, ok := p.(map[string]any); ok && m["id"] == id {
				pins[i] = pin
				return nil
			}
		}
		if len(pins) >= maxPins {
			return &turnedDown{400, "That's 1,000 pins already. Delete some first.", nil}
		}
		raw["pins"] = append(pins, pin)
		return nil
	})
}

func (s *notesStore) deletePin(id string) (map[string]any, error) {
	return s.changePlaces(func(raw map[string]any) error {
		all, _ := raw["pins"].([]any)
		kept := []any{}
		for _, p := range all {
			if m, ok := p.(map[string]any); !ok || m["id"] != id {
				kept = append(kept, p)
			}
		}
		raw["pins"] = kept
		return nil
	})
}

type notesServer struct {
	store   *notesStore
	origins map[string]bool
	port    int
	ln      net.Listener
	log     *log.Logger
}

func newNotesServer(data string, port, library int, logTo io.Writer) (*notesServer, error) {
	ln, err := net.Listen("tcp4", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return nil, err
	}
	page := strconv.Itoa(library)
	return &notesServer{
		store:   &notesStore{notes: filepath.Join(data, "notes.txt"), places: filepath.Join(data, "places.json")},
		origins: map[string]bool{"http://127.0.0.1:" + page: true, "http://localhost:" + page: true},
		port:    ln.Addr().(*net.TCPAddr).Port, ln: ln, log: log.New(logTo, "", log.LstdFlags),
	}, nil
}

func (n *notesServer) serve() error {
	srv := &http.Server{Handler: n, ErrorLog: n.log, ReadHeaderTimeout: time.Minute}
	return srv.Serve(n.ln)
}

// hostOK: the name the request was sent to is this computer's own.
func hostOK(host string) bool {
	h := strings.ToLower(strings.TrimSpace(host))
	name := h
	if strings.HasPrefix(h, "[") {
		name = strings.SplitN(h[1:], "]", 2)[0]
	} else if i := strings.LastIndex(h, ":"); i >= 0 {
		name = h[:i]
	}
	return name == "127.0.0.1" || name == "localhost" || name == "::1"
}

func (n *notesServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// "" for a request with no Origin: a program on this computer, or the gate, which drops it
	origin, ok := "", true
	if o, has := r.Header["Origin"]; has && len(o) > 0 {
		origin, ok = o[0], n.origins[o[0]]
	}
	if !hostOK(r.Host) || !ok {
		n.reply(w, r, 403, map[string]any{"error": "This answers the kit's own page only."}, "")
		return
	}
	if r.Method == http.MethodOptions {
		n.reply(w, r, 204, nil, origin)
		return
	}
	status, obj, err := n.answer(r, r.URL.EscapedPath())
	var no *turnedDown
	switch {
	case errors.As(err, &no):
		if no.status >= 500 {
			n.log.Print(no.msg)
		}
		m := map[string]any{"error": no.msg}
		for k, v := range no.extra {
			m[k] = v
		}
		status, obj = no.status, m
	case err != nil:
		n.log.Printf("couldn't save: %v", err)
		status, obj = 500, map[string]any{"error": "Couldn't save in the kit's data folder: " + errText(err) +
			". Is its drive still plugged in, with room on it?"}
	}
	n.reply(w, r, status, obj, origin)
}

func (n *notesServer) answer(r *http.Request, path string) (int, any, error) {
	reading := r.Method == http.MethodGet || r.Method == http.MethodHead
	put, st := r.Method == http.MethodPut, n.store
	withBody := func(do func(map[string]any) (map[string]any, error)) (int, any, error) {
		body, err := n.body(r)
		if err != nil {
			return 0, nil, err
		}
		v, err := do(body)
		return 200, v, err
	}
	switch {
	case path == "/" && reading:
		return 200, map[string]any{"name": "Tinfoil Kit", "notes": "/notes", "places": "/places"}, nil
	case path == "/notes" && reading:
		v, err := st.getNotes()
		return 200, v, err
	case path == "/notes" && put:
		return withBody(st.putNotes)
	case path == "/places" && reading:
		v, err := st.getPlaces()
		return 200, v, err
	case path == "/places/home" && put:
		return withBody(st.putHome)
	}
	id, isPin := strings.CutPrefix(path, "/places/pins/")
	if isPin && !pinID.MatchString(id) {
		return 0, nil, &turnedDown{404, "No such pin.", nil}
	}
	switch {
	case isPin && put:
		return withBody(func(b map[string]any) (map[string]any, error) { return st.putPin(id, b) })
	case isPin && r.Method == http.MethodDelete:
		v, err := st.deletePin(id)
		return 200, v, err
	case isPin || path == "/" || path == "/notes" || path == "/places" || path == "/places/home":
		return 405, map[string]any{"error": "Not that way."}, nil
	}
	return 404, map[string]any{"error": "Nothing here."}, nil
}

// body is the JSON object a save sends. JSON only: a web page can't send that to another address without asking
// first, and this server's answer to asking is no.
func (n *notesServer) body(r *http.Request) (map[string]any, error) {
	if !strings.HasPrefix(strings.ToLower(r.Header.Get("Content-Type")), "application/json") {
		return nil, &turnedDown{415, "Send JSON.", nil}
	}
	if r.ContentLength < 0 || r.ContentLength > maxSave {
		status := 411
		if r.ContentLength > maxSave {
			status = 413
		}
		return nil, &turnedDown{status, "Send JSON, up to 1 MB, with its length.", nil}
	}
	b := make([]byte, r.ContentLength)
	if _, err := io.ReadFull(r.Body, b); err != nil {
		return nil, &turnedDown{400, "Send a JSON object.", nil}
	}
	v, _ := decodeJSON(b)
	m, ok := v.(map[string]any)
	if !ok {
		return nil, &turnedDown{400, "Send a JSON object.", nil}
	}
	return m, nil
}

func (n *notesServer) reply(w http.ResponseWriter, r *http.Request, status int, obj any, origin string) {
	h := w.Header()
	var body []byte
	if obj != nil {
		body = bytes.TrimRight(encodeJSON(obj, ""), "\n")
		h.Set("Content-Type", "application/json; charset=utf-8")
		h.Set("Content-Length", strconv.Itoa(len(body)))
	}
	h.Set("Cache-Control", "no-store")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("Server", "TinfoilKit")
	if origin != "" {
		h.Set("Access-Control-Allow-Origin", origin)
		h.Set("Vary", "Origin")
		if r.Method == http.MethodOptions { // what the page may send
			h.Set("Access-Control-Allow-Methods", "GET, PUT, DELETE")
			h.Set("Access-Control-Allow-Headers", "Content-Type")
			h.Set("Access-Control-Max-Age", "600")
		}
	}
	w.WriteHeader(status)
	if r.Method != http.MethodHead {
		w.Write(body)
	}
}

// ourNotes says whether the kit's notes and pins server answers on this port (another window started it).
func ourNotes(port int) bool {
	b, status, ok := fetch(port, "/")
	var v struct {
		Notes string `json:"notes"`
	}
	return ok && status == 200 && json.Unmarshal([]byte(b), &v) == nil && v.Notes == "/notes"
}

// startNotes starts the notes and pins server on port, in this program, logging to logTo.
func startNotes(data string, logTo io.Writer, port, library int) (*notesServer, error) {
	n, err := newNotesServer(data, port, library, logTo)
	if err != nil {
		fmt.Fprintf(logTo, "Can't keep notes and pins on port %d: %s\n", port, errText(err))
		return nil, err
	}
	fmt.Fprintf(logTo, "Notes and pins on port %d, in %s\n", n.port, data)
	go n.serve()
	return n, nil
}

func runData(args []string) int {
	fs := newFlags("data")
	data := fs.String("data", "", "the kit's data folder")
	port := fs.Int("port", -1, "the port to listen on")
	library := fs.Int("library", 0, "the library's port: the kit page's own address")
	if fs.Parse(args) != nil || *data == "" || *port < 0 || *library <= 0 {
		fmt.Fprintln(os.Stderr, "usage: tinfoilkit data --data KIT/data --port 8095 --library 8888")
		return 2
	}
	if !isDir(*data) {
		fmt.Fprintf(os.Stderr, "Can't keep notes and pins: there's no data folder at %s\n", *data)
		return 1
	}
	n, err := newNotesServer(*data, *port, *library, os.Stderr)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Can't keep notes and pins on port %d: %s\n", *port, errText(err))
		return 1
	}
	fmt.Printf("Notes and pins on port %d, in %s\n", n.port, *data)
	if err := n.serve(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	return 0
}
