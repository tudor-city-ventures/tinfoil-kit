package main

// Directions across several places. GraphHopper builds its road network from one file of OpenStreetMap data, and
// Geofabrik publishes one per place, so the kit merges them: every node, then every way, then every relation, the
// order GraphHopper reads them in, each once (places that meet share the roads at their border, and GraphHopper stops
// at an id it has seen). The files are OSM's PBF format (https://wiki.openstreetmap.org/wiki/PBF_Format): blocks of
// zlib-compressed protocol buffers, sorted by type, then id. The merged file keeps what directions need, and leaves
// out each thing's history (versions, dates, authors).

import (
	"bufio"
	"bytes"
	"compress/zlib"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

var errPBF = errors.New("isn't road data the kit can read")

// osmThing is a node (kind 0), a way (1) or a relation (2).
type osmThing struct {
	kind     int
	id       int64
	lat, lon int64    // a node's, in billionths of a degree
	tags     [][]byte // key, value, key, value...
	refs     []int64  // a way's nodes, or a relation's members
	types    []uint64 // a relation's members' kinds
	roles    [][]byte // and their roles
}

// pbuf reads a protocol buffer message, a field at a time.
type pbuf struct {
	b   []byte
	bad bool
}

func (p *pbuf) uvarint() uint64 {
	v, n := binary.Uvarint(p.b)
	if n <= 0 {
		p.b, p.bad = nil, true
		return 0
	}
	p.b = p.b[n:]
	return v
}

// next is the next field's number and wire type, with its value (a varint) or its bytes (length-delimited).
func (p *pbuf) next() (field, wire int, v uint64, data []byte, ok bool) {
	if len(p.b) == 0 || p.bad {
		return 0, 0, 0, nil, false
	}
	key := p.uvarint()
	field, wire = int(key>>3), int(key&7)
	switch wire {
	case 0:
		v = p.uvarint()
	case 1, 5: // fixed-size numbers: nothing here uses them
		n := 8
		if wire == 5 {
			n = 4
		}
		if len(p.b) < n {
			p.bad = true
		} else {
			p.b = p.b[n:]
		}
	case 2:
		n := p.uvarint()
		if p.bad || n > uint64(len(p.b)) {
			p.bad = true
		} else {
			data, p.b = p.b[:n], p.b[n:]
		}
	default:
		p.bad = true
	}
	return field, wire, v, data, !p.bad
}

// ints adds a repeated number field's values, packed (data) or one at a time (v).
func ints(dst []uint64, wire int, v uint64, data []byte) ([]uint64, bool) {
	if wire == 0 {
		return append(dst, v), true
	}
	for len(data) > 0 {
		x, n := binary.Uvarint(data)
		if n <= 0 {
			return dst, false
		}
		dst, data = append(dst, x), data[n:]
	}
	return dst, true
}

func unzigzag(v uint64) int64 { return int64(v>>1) ^ -int64(v&1) }
func zigzag(v int64) uint64   { return uint64(v<<1) ^ uint64(v>>63) }

// pbfIn reads one file's things in order, a block at a time.
type pbfIn struct {
	name     string
	f        *os.File
	r        *bufio.Reader
	things   []osmThing
	at       int
	lastKind int
	lastID   int64
	stamp    int64 // when its data is from (osmosis_replication_timestamp)
}

func openPBF(path string) (*pbfIn, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	p := &pbfIn{name: filepath.Base(path), f: f, r: bufio.NewReaderSize(f, 1<<20), lastKind: -1}
	typ, data, err := p.blob()
	if err != nil || typ != "OSMHeader" {
		f.Close()
		return nil, fmt.Errorf("%s %w", p.name, errPBF)
	}
	h := &pbuf{b: data}
	for {
		field, wire, v, _, ok := h.next()
		if !ok {
			break
		}
		if field == 32 && wire == 0 {
			p.stamp = int64(v)
		}
	}
	return p, nil
}

// blob is the next block's type and its data, uncompressed: io.EOF at the end of the file.
func (p *pbfIn) blob() (string, []byte, error) {
	var size [4]byte
	if _, err := io.ReadFull(p.r, size[:]); err != nil {
		if err == io.EOF {
			return "", nil, err
		}
		return "", nil, errPBF
	}
	n := binary.BigEndian.Uint32(size[:])
	if n == 0 || n > 64<<10 { // the format's limits: 64 KiB for a block's header, 32 MiB for a block
		return "", nil, errPBF
	}
	head := make([]byte, n)
	if _, err := io.ReadFull(p.r, head); err != nil {
		return "", nil, errPBF
	}
	typ, length := "", uint64(0)
	h := &pbuf{b: head}
	for {
		field, wire, v, data, ok := h.next()
		if !ok {
			break
		}
		if field == 1 && wire == 2 {
			typ = string(data)
		} else if field == 3 && wire == 0 {
			length = v
		}
	}
	if h.bad || length == 0 || length > 32<<20 {
		return "", nil, errPBF
	}
	blob := make([]byte, length)
	if _, err := io.ReadFull(p.r, blob); err != nil {
		return "", nil, errPBF
	}
	var raw, packed []byte
	b := &pbuf{b: blob}
	for {
		field, wire, _, data, ok := b.next()
		if !ok {
			break
		}
		switch {
		case field == 1 && wire == 2:
			raw = data
		case field == 3 && wire == 2:
			packed = data
		case field >= 4: // lzma, bzip2, lz4 or zstd, which Geofabrik doesn't use
			return "", nil, fmt.Errorf("is compressed in a way the kit can't read (%d)", field)
		}
	}
	if b.bad || raw == nil && packed == nil {
		return "", nil, errPBF
	}
	if raw != nil {
		return typ, raw, nil
	}
	z, err := zlib.NewReader(bytes.NewReader(packed))
	if err != nil {
		return "", nil, errPBF
	}
	var out bytes.Buffer
	if _, err := io.Copy(&out, io.LimitReader(z, 32<<20+1)); err != nil || out.Len() > 32<<20 {
		return "", nil, errPBF
	}
	return typ, out.Bytes(), nil
}

// peek is the thing it's at: nil at the end of the file.
func (p *pbfIn) peek() (*osmThing, error) {
	for p.at >= len(p.things) {
		typ, data, err := p.blob()
		if err == io.EOF {
			return nil, nil
		}
		if err == nil && typ == "OSMData" {
			p.things, err = decodeBlock(data)
			p.at = 0
		}
		if err != nil {
			return nil, fmt.Errorf("%s %w", p.name, err)
		}
	}
	t := &p.things[p.at]
	if t.kind < p.lastKind || t.kind == p.lastKind && t.id <= p.lastID {
		return nil, fmt.Errorf("%s isn't sorted by type and id, so it can't be merged", p.name)
	}
	return t, nil
}

func (p *pbfIn) skip() {
	p.lastKind, p.lastID = p.things[p.at].kind, p.things[p.at].id
	p.at++
}

type strTable [][]byte

func (s strTable) tags(keys, vals []uint64) ([][]byte, bool) {
	if len(keys) != len(vals) {
		return nil, false
	}
	var tags [][]byte
	for i := range keys {
		if keys[i] >= uint64(len(s)) || vals[i] >= uint64(len(s)) {
			return nil, false
		}
		tags = append(tags, s[keys[i]], s[vals[i]])
	}
	return tags, true
}

// decodeBlock is a block's things (a PrimitiveBlock's).
func decodeBlock(data []byte) ([]osmThing, error) {
	var strs strTable
	var groups [][]byte
	gran, latOff, lonOff := int64(100), int64(0), int64(0)
	p := &pbuf{b: data}
	for {
		field, wire, v, d, ok := p.next()
		if !ok {
			break
		}
		switch {
		case field == 1 && wire == 2:
			s := &pbuf{b: d}
			for {
				f, w, _, str, ok := s.next()
				if !ok {
					break
				}
				if f == 1 && w == 2 {
					strs = append(strs, str)
				}
			}
			if s.bad {
				return nil, errPBF
			}
		case field == 2 && wire == 2:
			groups = append(groups, d)
		case field == 17 && wire == 0:
			gran = int64(v)
		case field == 19 && wire == 0:
			latOff = int64(v)
		case field == 20 && wire == 0:
			lonOff = int64(v)
		}
	}
	if p.bad {
		return nil, errPBF
	}
	var out []osmThing
	for _, g := range groups {
		q := &pbuf{b: g}
		for {
			field, wire, _, d, ok := q.next()
			if !ok {
				break
			}
			if wire != 2 {
				continue
			}
			var err error
			switch field {
			case 1:
				out, err = decodeNode(out, d, strs, gran, latOff, lonOff)
			case 2:
				out, err = decodeDense(out, d, strs, gran, latOff, lonOff)
			case 3, 4:
				out, err = decodeWay(out, field-2, d, strs)
			}
			if err != nil {
				return nil, err
			}
		}
		if q.bad {
			return nil, errPBF
		}
	}
	return out, nil
}

func decodeNode(out []osmThing, d []byte, strs strTable, gran, latOff, lonOff int64) ([]osmThing, error) {
	t := osmThing{kind: 0}
	var keys, vals []uint64
	ok := true
	p := &pbuf{b: d}
	for ok {
		field, wire, v, data, more := p.next()
		if !more {
			break
		}
		switch field {
		case 1:
			t.id = unzigzag(v)
		case 2:
			keys, ok = ints(keys, wire, v, data)
		case 3:
			vals, ok = ints(vals, wire, v, data)
		case 8:
			t.lat = latOff + gran*unzigzag(v)
		case 9:
			t.lon = lonOff + gran*unzigzag(v)
		}
	}
	if !ok || p.bad {
		return nil, errPBF
	}
	if t.tags, ok = strs.tags(keys, vals); !ok {
		return nil, errPBF
	}
	return append(out, t), nil
}

func decodeDense(out []osmThing, d []byte, strs strTable, gran, latOff, lonOff int64) ([]osmThing, error) {
	var ids, lats, lons, kv []uint64
	ok := true
	p := &pbuf{b: d}
	for ok {
		field, wire, v, data, more := p.next()
		if !more {
			break
		}
		switch field {
		case 1:
			ids, ok = ints(ids, wire, v, data)
		case 8:
			lats, ok = ints(lats, wire, v, data)
		case 9:
			lons, ok = ints(lons, wire, v, data)
		case 10:
			kv, ok = ints(kv, wire, v, data)
		}
	}
	if !ok || p.bad || len(lats) != len(ids) || len(lons) != len(ids) {
		return nil, errPBF
	}
	var id, lat, lon int64
	j := 0
	for i := range ids {
		id, lat, lon = id+unzigzag(ids[i]), lat+unzigzag(lats[i]), lon+unzigzag(lons[i])
		t := osmThing{kind: 0, id: id, lat: latOff + gran*lat, lon: lonOff + gran*lon}
		for ; j < len(kv) && kv[j] != 0; j += 2 { // each node's keys and values, then a 0
			if j+1 >= len(kv) || kv[j] >= uint64(len(strs)) || kv[j+1] >= uint64(len(strs)) {
				return nil, errPBF
			}
			t.tags = append(t.tags, strs[kv[j]], strs[kv[j+1]])
		}
		j++
		out = append(out, t)
	}
	return out, nil
}

// decodeWay is a way (kind 1) or a relation (2): their ids, tags and references are alike.
func decodeWay(out []osmThing, kind int, d []byte, strs strTable) ([]osmThing, error) {
	t := osmThing{kind: kind}
	var keys, vals, refs, roles []uint64
	ok := true
	p := &pbuf{b: d}
	for ok {
		field, wire, v, data, more := p.next()
		if !more {
			break
		}
		switch {
		case field == 1:
			t.id = int64(v)
		case field == 2:
			keys, ok = ints(keys, wire, v, data)
		case field == 3:
			vals, ok = ints(vals, wire, v, data)
		case field == 8 && kind == 1, field == 9 && kind == 2:
			refs, ok = ints(refs, wire, v, data)
		case field == 8 && kind == 2:
			roles, ok = ints(roles, wire, v, data)
		case field == 10 && kind == 2:
			t.types, ok = ints(t.types, wire, v, data)
		}
	}
	if !ok || p.bad {
		return nil, errPBF
	}
	if t.tags, ok = strs.tags(keys, vals); !ok {
		return nil, errPBF
	}
	var ref int64
	for _, r := range refs {
		ref += unzigzag(r)
		t.refs = append(t.refs, ref)
	}
	if kind == 2 {
		if len(roles) != len(refs) || len(t.types) != len(refs) {
			return nil, errPBF
		}
		for _, r := range roles {
			if r >= uint64(len(strs)) {
				return nil, errPBF
			}
			t.roles = append(t.roles, strs[r])
		}
	}
	return append(out, t), nil
}

func pbKey(b []byte, field, wire int) []byte {
	return binary.AppendUvarint(b, uint64(field)<<3|uint64(wire))
}
func pbUint(b []byte, field int, v uint64) []byte {
	return binary.AppendUvarint(pbKey(b, field, 0), v)
}
func pbBytes(b []byte, field int, data []byte) []byte {
	return append(binary.AppendUvarint(pbKey(b, field, 2), uint64(len(data))), data...)
}

// pbPacked is a packed repeated field, left out when it has no values.
func pbPacked(b []byte, field int, data []byte) []byte {
	if len(data) == 0 {
		return b
	}
	return pbBytes(b, field, data)
}

// encodeBlock is a block of things of one kind with its own string table: nodes as dense nodes, at the format's
// usual hundred billionths of a degree.
func encodeBlock(things []osmThing) []byte {
	index := map[string]uint64{"": 0}
	table := [][]byte{nil}
	sid := func(s []byte) uint64 {
		if i, ok := index[string(s)]; ok {
			return i
		}
		index[string(s)] = uint64(len(table))
		table = append(table, s)
		return uint64(len(table) - 1)
	}
	var group []byte
	if things[0].kind == 0 {
		var ids, lats, lons, kv []byte
		var id, lat, lon int64
		for _, t := range things {
			la, lo := t.lat/100, t.lon/100
			ids = binary.AppendUvarint(ids, zigzag(t.id-id))
			lats = binary.AppendUvarint(lats, zigzag(la-lat))
			lons = binary.AppendUvarint(lons, zigzag(lo-lon))
			id, lat, lon = t.id, la, lo
			for _, s := range t.tags {
				kv = binary.AppendUvarint(kv, sid(s))
			}
			kv = binary.AppendUvarint(kv, 0)
		}
		dense := pbPacked(pbPacked(pbPacked(pbPacked(nil, 1, ids), 8, lats), 9, lons), 10, kv)
		group = pbBytes(nil, 2, dense)
	} else {
		for _, t := range things {
			var keys, vals, refs, roles, types []byte
			for i := 0; i+1 < len(t.tags); i += 2 {
				keys = binary.AppendUvarint(keys, sid(t.tags[i]))
				vals = binary.AppendUvarint(vals, sid(t.tags[i+1]))
			}
			var prev int64
			for _, r := range t.refs {
				refs, prev = binary.AppendUvarint(refs, zigzag(r-prev)), r
			}
			m := pbPacked(pbPacked(pbUint(nil, 1, uint64(t.id)), 2, keys), 3, vals)
			if t.kind == 1 {
				group = pbBytes(group, 3, pbPacked(m, 8, refs))
				continue
			}
			for i := range t.refs {
				roles = binary.AppendUvarint(roles, sid(t.roles[i]))
				types = binary.AppendUvarint(types, t.types[i])
			}
			group = pbBytes(group, 4, pbPacked(pbPacked(pbPacked(m, 8, roles), 9, refs), 10, types))
		}
	}
	var st []byte
	for _, s := range table {
		st = pbBytes(st, 1, s)
	}
	return pbBytes(pbBytes(nil, 1, st), 2, group)
}

// pbfOut writes things to a file in blocks of one kind.
type pbfOut struct {
	f     *os.File
	w     *bufio.Writer
	block []osmThing
	size  int
	err   error
}

func createPBF(path string, stamp int64) (*pbfOut, error) {
	f, err := os.Create(path)
	if err != nil {
		return nil, err
	}
	o := &pbfOut{f: f, w: bufio.NewWriterSize(f, 1<<20)}
	h := pbBytes(pbBytes(nil, 4, []byte("OsmSchema-V0.6")), 4, []byte("DenseNodes"))
	h = pbBytes(h, 16, []byte("Tinfoil Kit"))
	if stamp > 0 {
		h = pbUint(h, 32, uint64(stamp))
	}
	o.write("OSMHeader", h)
	return o, o.err
}

func (o *pbfOut) add(t osmThing) {
	if len(o.block) > 0 && (o.block[0].kind != t.kind || len(o.block) == 8000 || o.size > 8<<20) {
		o.flush()
	}
	o.block = append(o.block, t)
	o.size += 24 + 6*len(t.refs)
	for _, s := range t.tags {
		o.size += len(s)
	}
	for _, s := range t.roles {
		o.size += len(s)
	}
}

func (o *pbfOut) flush() {
	if len(o.block) > 0 {
		o.write("OSMData", encodeBlock(o.block))
		o.block, o.size = o.block[:0], 0
	}
}

func (o *pbfOut) write(typ string, raw []byte) {
	if o.err != nil {
		return
	}
	var z bytes.Buffer
	zw, _ := zlib.NewWriterLevel(&z, zlib.BestSpeed)
	zw.Write(raw)
	zw.Close()
	blob := pbBytes(pbUint(nil, 2, uint64(len(raw))), 3, z.Bytes())
	head := pbUint(pbBytes(nil, 1, []byte(typ)), 3, uint64(len(blob)))
	var size [4]byte
	binary.BigEndian.PutUint32(size[:], uint32(len(head)))
	for _, b := range [][]byte{size[:], head, blob} {
		if _, err := o.w.Write(b); err != nil {
			o.err = err
			return
		}
	}
}

func (o *pbfOut) close() error {
	o.flush()
	if o.err == nil {
		o.err = o.w.Flush()
	}
	if err := o.f.Close(); o.err == nil {
		o.err = err
	}
	return o.err
}

// mergePBF writes the road data in files to out: every node, way and relation once, in order.
func mergePBF(out string, files []string) error {
	var ins []*pbfIn
	defer func() {
		for _, p := range ins {
			p.f.Close()
		}
	}()
	var stamp int64
	for _, f := range files {
		p, err := openPBF(f)
		if err != nil {
			return err
		}
		ins = append(ins, p)
		stamp = max(stamp, p.stamp)
	}
	tmp := out + ".partial"
	o, err := createPBF(tmp, stamp)
	if err == nil {
		err = mergeInto(o, ins)
		if cerr := o.close(); err == nil {
			err = cerr
		}
	}
	if err == nil {
		err = replace(tmp, out)
	}
	if err != nil {
		os.Remove(tmp)
	}
	return err
}

func mergeInto(o *pbfOut, ins []*pbfIn) error {
	for o.err == nil {
		var next *osmThing
		for _, p := range ins {
			t, err := p.peek()
			if err != nil {
				return err
			}
			if t != nil && (next == nil || t.kind < next.kind || t.kind == next.kind && t.id < next.id) {
				next = t
			}
		}
		if next == nil {
			return nil
		}
		t := *next
		o.add(t)
		for _, p := range ins {
			if at, _ := p.peek(); at != nil && at.kind == t.kind && at.id == t.id {
				p.skip()
			}
		}
	}
	return o.err
}
