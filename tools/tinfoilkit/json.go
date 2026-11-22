package main

// kit.json and the kit's records in data/.kit are JSON that people read and edit. They're written the way Python's
// json module writes them, with keys in the order they came, so a file looks the same whichever program wrote it.

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// obj is a JSON object that keeps its keys in order.
type obj struct {
	keys []string
	vals map[string]any
}

func newObj(kv ...any) *obj {
	o := &obj{vals: map[string]any{}}
	for i := 0; i+1 < len(kv); i += 2 {
		o.set(kv[i].(string), kv[i+1])
	}
	return o
}

func (o *obj) get(k string) any {
	if o == nil {
		return nil
	}
	return o.vals[k]
}

func (o *obj) lookup(k string) (any, bool) {
	if o == nil {
		return nil, false
	}
	v, ok := o.vals[k]
	return v, ok
}

func (o *obj) has(k string) bool {
	_, ok := o.lookup(k)
	return ok
}

// getOr is Python's dict.get(k, def).
func (o *obj) getOr(k string, def any) any {
	if v, ok := o.lookup(k); ok {
		return v
	}
	return def
}

func (o *obj) set(k string, v any) {
	if _, ok := o.vals[k]; !ok {
		o.keys = append(o.keys, k)
	}
	o.vals[k] = v
}

func (o *obj) del(k string) {
	if o == nil {
		return
	}
	if _, ok := o.vals[k]; !ok {
		return
	}
	delete(o.vals, k)
	for i, x := range o.keys {
		if x == k {
			o.keys = append(o.keys[:i:i], o.keys[i+1:]...)
			break
		}
	}
}

func (o *obj) size() int {
	if o == nil {
		return 0
	}
	return len(o.keys)
}

func (o *obj) Keys() []string {
	if o == nil {
		return nil
	}
	return append([]string(nil), o.keys...)
}

// str is a string value, or "" for anything else.
func (o *obj) str(k string) string {
	s, _ := o.get(k).(string)
	return s
}

// child is an object value, or nil.
func (o *obj) child(k string) *obj {
	c, _ := o.get(k).(*obj)
	return c
}

// list is a list value, or nil.
func (o *obj) list(k string) []any {
	l, _ := o.get(k).([]any)
	return l
}

// objs is a list value's objects (kit.json's models, books...).
func (o *obj) objs(k string) []*obj {
	var out []*obj
	for _, v := range o.list(k) {
		if e, ok := v.(*obj); ok {
			out = append(out, e)
		}
	}
	return out
}

// on is an entry's "enabled", which is true when it isn't there.
func (o *obj) on() bool { return truthy(o.getOr("enabled", true)) }

// copyOf is a deep copy of a JSON value.
func copyOf(v any) any {
	switch x := v.(type) {
	case *obj:
		c := newObj()
		for _, k := range x.keys {
			c.set(k, copyOf(x.vals[k]))
		}
		return c
	case []any:
		c := make([]any, len(x))
		for i, e := range x {
			c[i] = copyOf(e)
		}
		return c
	}
	return v
}

func cloneObj(o *obj) *obj {
	if o == nil {
		return newObj()
	}
	return copyOf(o).(*obj)
}

// with is a copy of o with these keys set, like Python's {**o, k: v}.
func with(o *obj, kv ...any) *obj {
	c := newObj()
	if o != nil {
		for _, k := range o.keys {
			c.set(k, o.vals[k])
		}
	}
	for i := 0; i+1 < len(kv); i += 2 {
		c.set(kv[i].(string), kv[i+1])
	}
	return c
}

// ----------------------------------------------------------------------------- reading

// jsonError is where a JSON file stops making sense, in the words Python's json module uses, so a typo in kit.json
// reads the same whichever program found it.
type jsonError struct {
	msg            string
	line, col, pos int
}

func (e *jsonError) Error() string {
	return fmt.Sprintf("%s: line %d column %d (char %d)", e.msg, e.line, e.col, e.pos)
}

type jsonParser struct {
	s   string
	pos int
}

func parseJSON(data []byte) (any, error) {
	p := &jsonParser{s: strings.TrimPrefix(string(data), "\ufeff")}
	v, err := p.value()
	if err == nil {
		p.space()
		if p.pos < len(p.s) {
			err = p.fail("Extra data", p.pos)
		}
	}
	return v, err
}

// fail counts in characters, as Python does.
func (p *jsonParser) fail(msg string, at int) error {
	before := p.s[:at]
	nl := strings.LastIndexByte(before, '\n')
	return &jsonError{msg, strings.Count(before, "\n") + 1, utf8.RuneCountInString(before[nl+1:]) + 1, utf8.RuneCountInString(before)}
}

func (p *jsonParser) space() {
	for p.pos < len(p.s) && strings.IndexByte(" \t\n\r", p.s[p.pos]) >= 0 {
		p.pos++
	}
}

var jsonNumber = regexp.MustCompile(`^-?(?:0|[1-9]\d*)(\.\d+)?([eE][-+]?\d+)?`)

func (p *jsonParser) value() (any, error) {
	p.space()
	if p.pos >= len(p.s) {
		return nil, p.fail("Expecting value", p.pos)
	}
	rest := p.s[p.pos:]
	switch c := rest[0]; {
	case c == '{':
		return p.object()
	case c == '[':
		return p.array()
	case c == '"':
		return p.str()
	case strings.HasPrefix(rest, "null"):
		p.pos += 4
		return nil, nil
	case strings.HasPrefix(rest, "true"):
		p.pos += 4
		return true, nil
	case strings.HasPrefix(rest, "false"):
		p.pos += 5
		return false, nil
	case strings.HasPrefix(rest, "NaN"):
		p.pos += 3
		return math.NaN(), nil
	case strings.HasPrefix(rest, "Infinity"):
		p.pos += 8
		return math.Inf(1), nil
	case strings.HasPrefix(rest, "-Infinity"):
		p.pos += 9
		return math.Inf(-1), nil
	}
	if m := jsonNumber.FindString(rest); m != "" {
		p.pos += len(m)
		return json.Number(m), nil
	}
	return nil, p.fail("Expecting value", p.pos)
}

func (p *jsonParser) object() (any, error) {
	o := newObj()
	p.pos++
	p.space()
	if p.pos < len(p.s) && p.s[p.pos] == '}' {
		p.pos++
		return o, nil
	}
	for {
		if p.pos >= len(p.s) || p.s[p.pos] != '"' {
			return nil, p.fail("Expecting property name enclosed in double quotes", p.pos)
		}
		k, err := p.str()
		if err != nil {
			return nil, err
		}
		p.space()
		if p.pos >= len(p.s) || p.s[p.pos] != ':' {
			return nil, p.fail("Expecting ':' delimiter", p.pos)
		}
		p.pos++
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		o.set(k, v)
		p.space()
		if p.pos < len(p.s) && p.s[p.pos] == '}' {
			p.pos++
			return o, nil
		}
		if p.pos >= len(p.s) || p.s[p.pos] != ',' {
			return nil, p.fail("Expecting ',' delimiter", p.pos)
		}
		p.pos++
		p.space()
	}
}

func (p *jsonParser) array() (any, error) {
	l := []any{}
	p.pos++
	p.space()
	if p.pos < len(p.s) && p.s[p.pos] == ']' {
		p.pos++
		return l, nil
	}
	for {
		v, err := p.value()
		if err != nil {
			return nil, err
		}
		l = append(l, v)
		p.space()
		if p.pos < len(p.s) && p.s[p.pos] == ']' {
			p.pos++
			return l, nil
		}
		if p.pos >= len(p.s) || p.s[p.pos] != ',' {
			return nil, p.fail("Expecting ',' delimiter", p.pos)
		}
		p.pos++
	}
}

func (p *jsonParser) str() (string, error) {
	start := p.pos
	p.pos++
	var b strings.Builder
	for {
		if p.pos >= len(p.s) {
			return "", p.fail("Unterminated string starting at", start)
		}
		c := p.s[p.pos]
		switch {
		case c == '"':
			p.pos++
			return b.String(), nil
		case c < 0x20:
			return "", p.fail("Invalid control character at", p.pos)
		case c != '\\':
			b.WriteByte(c)
			p.pos++
			continue
		}
		if p.pos+1 >= len(p.s) {
			return "", p.fail("Unterminated string starting at", start)
		}
		esc := p.s[p.pos+1]
		if r, ok := map[byte]string{'"': `"`, '\\': `\`, '/': "/", 'b': "\b", 'f': "\f", 'n': "\n", 'r': "\r", 't': "\t"}[esc]; ok {
			b.WriteString(r)
			p.pos += 2
			continue
		}
		if esc != 'u' {
			return "", p.fail("Invalid \\escape", p.pos)
		}
		r, ok := p.hex4(p.pos + 2)
		if !ok {
			return "", p.fail("Invalid \\uXXXX escape", p.pos+1)
		}
		p.pos += 6
		if r >= 0xd800 && r < 0xdc00 && strings.HasPrefix(p.s[p.pos:], "\\u") {
			if lo, ok := p.hex4(p.pos + 2); ok && lo >= 0xdc00 && lo < 0xe000 {
				r = 0x10000 + (r-0xd800)<<10 + (lo - 0xdc00)
				p.pos += 6
			}
		}
		b.WriteRune(r)
	}
}

func (p *jsonParser) hex4(at int) (rune, bool) {
	if at+4 > len(p.s) {
		return 0, false
	}
	n, err := strconv.ParseUint(p.s[at:at+4], 16, 32)
	return rune(n), err == nil && !strings.ContainsAny(p.s[at:at+4], "+-xX")
}

// parseObj is a JSON object, or an error if the data is anything else.
func parseObj(data []byte) (*obj, error) {
	v, err := parseJSON(data)
	if err != nil {
		return nil, err
	}
	o, ok := v.(*obj)
	if !ok {
		return nil, errors.New("not a JSON object")
	}
	return o, nil
}

// ----------------------------------------------------------------------------- writing

type jsonStyle struct {
	indent   int // -1: on one line, with ", " and ": " between, as Python's json.dumps has it
	sortKeys bool
	ascii    bool // escape everything but printable ASCII (Python's ensure_ascii)
}

// dumps writes v as Python's json.dumps(v, indent=..., sort_keys=..., ensure_ascii=...) does.
func dumps(v any, s jsonStyle) string {
	var b strings.Builder
	writeJSON(&b, v, s, 0)
	return b.String()
}

func dumpsLine(v any) string { return dumps(v, jsonStyle{indent: -1, ascii: true}) }

func writeJSON(b *strings.Builder, v any, s jsonStyle, depth int) {
	newline := func(d int) {
		if s.indent >= 0 {
			b.WriteByte('\n')
			b.WriteString(strings.Repeat(" ", s.indent*d))
		}
	}
	sep := ", "
	if s.indent >= 0 {
		sep = ","
	}
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		writeString(b, x, s.ascii)
	case json.Number:
		b.WriteString(pyNumber(x))
	case int:
		b.WriteString(strconv.Itoa(x))
	case int64:
		b.WriteString(strconv.FormatInt(x, 10))
	case uint64:
		b.WriteString(strconv.FormatUint(x, 10))
	case float64:
		b.WriteString(pyFloat(x))
	case []any:
		if len(x) == 0 {
			b.WriteString("[]")
			return
		}
		b.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				b.WriteString(sep)
			}
			newline(depth + 1)
			writeJSON(b, e, s, depth+1)
		}
		newline(depth)
		b.WriteByte(']')
	case []string:
		l := make([]any, len(x))
		for i, e := range x {
			l[i] = e
		}
		writeJSON(b, l, s, depth)
	case *obj:
		if x.size() == 0 {
			b.WriteString("{}")
			return
		}
		keys := x.Keys()
		if s.sortKeys {
			sort.Strings(keys)
		}
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteString(sep)
			}
			newline(depth + 1)
			writeString(b, k, s.ascii)
			b.WriteString(": ")
			writeJSON(b, x.vals[k], s, depth+1)
		}
		newline(depth)
		b.WriteByte('}')
	case map[string]any:
		o := newObj()
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			o.set(k, x[k])
		}
		writeJSON(b, o, s, depth)
	default:
		data, _ := json.Marshal(x)
		b.Write(data)
	}
}

func writeString(b *strings.Builder, s string, ascii bool) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			switch {
			case r < 0x20 || (ascii && r > 0x7e && r < 0x10000):
				fmt.Fprintf(b, `\u%04x`, r)
			case ascii && r >= 0x10000:
				r -= 0x10000
				fmt.Fprintf(b, `\u%04x\u%04x`, 0xd800+(r>>10), 0xdc00+(r&0x3ff))
			default:
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
}

// pyNumber writes a number as Python reads and writes it back: a whole number as it is, anything with a point or an
// exponent as a float.
func pyNumber(n json.Number) string {
	s := string(n)
	if !strings.ContainsAny(s, ".eE") {
		if s == "-0" {
			return "0"
		}
		return s
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return s
	}
	return pyFloat(f)
}

// pyFloat is Python's repr of a float: the shortest digits that read back the same, with ".0" on a whole number, and
// an exponent below 1e-4 or from 1e16.
func pyFloat(f float64) string {
	switch {
	case math.IsInf(f, 1):
		return "Infinity"
	case math.IsInf(f, -1):
		return "-Infinity"
	case math.IsNaN(f):
		return "NaN"
	}
	e := strconv.FormatFloat(f, 'e', -1, 64)
	exp, _ := strconv.Atoi(e[strings.IndexByte(e, 'e')+1:])
	if exp < -4 || exp >= 16 {
		return e
	}
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(s, ".") {
		s += ".0"
	}
	return s
}

// ----------------------------------------------------------------------------- Python's ideas of equal and true

// pyEqual is Python's == on JSON values: 1 == 1.0 == True, and objects are equal whatever order their keys are in.
func pyEqual(a, b any) bool {
	if fa, ok := asNumber(a); ok {
		fb, ok := asNumber(b)
		return ok && fa == fb
	}
	switch x := a.(type) {
	case nil:
		return b == nil
	case string:
		y, ok := b.(string)
		return ok && x == y
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !pyEqual(x[i], y[i]) {
				return false
			}
		}
		return true
	case *obj:
		y, ok := b.(*obj)
		if !ok || x.size() != y.size() {
			return false
		}
		for _, k := range x.keys {
			w, ok := y.lookup(k)
			if !ok || !pyEqual(x.vals[k], w) {
				return false
			}
		}
		return true
	}
	return a == b
}

// asNumber is a JSON number (or a bool, which Python counts as 0 or 1) as a float.
func asNumber(v any) (float64, bool) {
	switch x := v.(type) {
	case json.Number:
		f, err := strconv.ParseFloat(string(x), 64)
		return f, err == nil
	case int:
		return float64(x), true
	case int64:
		return float64(x), true
	case uint64:
		return float64(x), true
	case float64:
		return x, true
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	}
	return 0, false
}

func truthy(v any) bool {
	switch x := v.(type) {
	case nil:
		return false
	case bool:
		return x
	case string:
		return x != ""
	case []any:
		return len(x) > 0
	case *obj:
		return x.size() > 0
	}
	if f, ok := asNumber(v); ok {
		return f != 0
	}
	return true
}

// isTrue is Python's "v is True".
func isTrue(v any) bool {
	b, ok := v.(bool)
	return ok && b
}

// pyInt is Python's int(v) for a JSON value.
func pyInt(v any) (int64, error) {
	switch x := v.(type) {
	case string:
		n, err := strconv.ParseInt(strings.TrimSpace(x), 10, 64)
		if err != nil {
			return 0, fmt.Errorf("invalid literal for int() with base 10: '%s'", x)
		}
		return n, nil
	case json.Number:
		if n, err := strconv.ParseInt(string(x), 10, 64); err == nil {
			return n, nil
		}
	}
	f, ok := asNumber(v)
	if !ok {
		return 0, fmt.Errorf("int() argument must be a string or a number, not '%s'", pyType(v))
	}
	return int64(f), nil
}

// intOr is pyInt, or def for a value that isn't a number.
func intOr(v any, def int64) int64 {
	if n, err := pyInt(v); err == nil {
		return n
	}
	return def
}

func floatOr(v any, def float64) float64 {
	if s, ok := v.(string); ok {
		if f, err := strconv.ParseFloat(strings.TrimSpace(s), 64); err == nil {
			return f
		}
		return def
	}
	if f, ok := asNumber(v); ok {
		return f
	}
	return def
}

func pyType(v any) string {
	switch v.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case []any:
		return "list"
	case *obj:
		return "dict"
	}
	return "int"
}

// pyStr is Python's str(v), as f-strings show a value.
func pyStr(v any) string {
	switch x := v.(type) {
	case nil:
		return "None"
	case bool:
		if x {
			return "True"
		}
		return "False"
	case string:
		return x
	case json.Number:
		return pyNumber(x)
	case float64:
		return pyFloat(x)
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case []any, *obj:
		return pyRepr(v)
	}
	return fmt.Sprint(v)
}

// pyRepr is Python's repr of a JSON value: {'id': 'x', 'on': True}.
func pyRepr(v any) string {
	switch x := v.(type) {
	case string:
		q := "'"
		if strings.Contains(x, "'") && !strings.Contains(x, `"`) {
			q = `"`
		}
		var b strings.Builder
		b.WriteString(q)
		for _, r := range x {
			switch {
			case r == '\\':
				b.WriteString(`\\`)
			case string(r) == q:
				b.WriteString(`\` + q)
			case r == '\n':
				b.WriteString(`\n`)
			case r == '\r':
				b.WriteString(`\r`)
			case r == '\t':
				b.WriteString(`\t`)
			case r < 0x20 || r == 0x7f:
				fmt.Fprintf(&b, `\x%02x`, r)
			default:
				b.WriteRune(r)
			}
		}
		b.WriteString(q)
		return b.String()
	case []any:
		parts := make([]string, len(x))
		for i, e := range x {
			parts[i] = pyRepr(e)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *obj:
		parts := make([]string, 0, x.size())
		for _, k := range x.keys {
			parts = append(parts, pyRepr(k)+": "+pyRepr(x.vals[k]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return pyStr(v)
}

// clip is s cut to n characters, as Python's s[:n].
func clip(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n])
}
