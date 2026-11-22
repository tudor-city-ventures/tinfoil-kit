package main

import (
	"fmt"
	"strings"
)

// QR codes, for a phone to open the shared kit: byte mode at error correction level M, following ISO/IEC 18004.
// An address needs version 3 or 4. Per version: error correction codewords in each block, and the number of blocks.
var qrECC = [41]int{0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
	26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28}
var qrBlocks = [41]int{0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
	17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49}

var qrMasks = [8]func(x, y int) bool{
	func(x, y int) bool { return (x+y)%2 == 0 },
	func(x, y int) bool { return y%2 == 0 },
	func(x, y int) bool { return x%3 == 0 },
	func(x, y int) bool { return (x+y)%3 == 0 },
	func(x, y int) bool { return (x/3+y/2)%2 == 0 },
	func(x, y int) bool { return x*y%2+x*y%3 == 0 },
	func(x, y int) bool { return (x*y%2+x*y%3)%2 == 0 },
	func(x, y int) bool { return ((x+y)%2+x*y%3)%2 == 0 },
}

type qrGrid [][]bool

func gfMul(x, y int) int {
	z := 0
	for i := 7; i >= 0; i-- {
		z = (z << 1) ^ ((z >> 7) * 0x11D)
		z ^= ((y >> i) & 1) * x
	}
	return z
}

// qrRS is the Reed-Solomon error correction for one block.
func qrRS(data []int, degree int) []int {
	gen := make([]int, degree)
	gen[degree-1] = 1
	root := 1
	for i := 0; i < degree; i++ {
		for j := 0; j < degree; j++ {
			gen[j] = gfMul(gen[j], root)
			if j+1 < degree {
				gen[j] ^= gen[j+1]
			}
		}
		root = gfMul(root, 2)
	}
	rem := make([]int, degree)
	for _, b := range data {
		factor := b ^ rem[0]
		copy(rem, rem[1:])
		rem[degree-1] = 0
		for i, c := range gen {
			rem[i] ^= gfMul(c, factor)
		}
	}
	return rem
}

// qrRawModules counts the modules left for data and error correction once the fixed patterns are drawn.
func qrRawModules(ver int) int {
	n := (16*ver+128)*ver + 64
	if ver >= 2 {
		align := ver/7 + 2
		n -= (25*align-10)*align - 55
		if ver >= 7 {
			n -= 36
		}
	}
	return n
}

// qrCodewords picks the smallest version that holds data, and gives its codewords: data, then error correction,
// interleaved.
func qrCodewords(data []byte) (int, []int, error) {
	ver, capacity, countBits := 0, 0, 0
	for v := 1; v <= 40; v++ {
		capacity = qrRawModules(v)/8 - qrECC[v]*qrBlocks[v]
		countBits = 8
		if v >= 10 {
			countBits = 16
		}
		if 4+countBits+8*len(data) <= capacity*8 {
			ver = v
			break
		}
	}
	if ver == 0 {
		return 0, nil, fmt.Errorf("too long for a QR code")
	}
	bits := []int{0, 1, 0, 0}
	for i := countBits - 1; i >= 0; i-- {
		bits = append(bits, (len(data)>>i)&1)
	}
	for _, b := range data {
		for i := 7; i >= 0; i-- {
			bits = append(bits, int(b>>i)&1)
		}
	}
	for i := 0; i < 4 && len(bits) < capacity*8; i++ {
		bits = append(bits, 0)
	}
	for len(bits)%8 != 0 {
		bits = append(bits, 0)
	}
	var words []int
	for i := 0; i < len(bits); i += 8 {
		w := 0
		for _, b := range bits[i : i+8] {
			w = w<<1 | b
		}
		words = append(words, w)
	}
	for pad := 0xEC; len(words) < capacity; pad ^= 0xEC ^ 0x11 {
		words = append(words, pad)
	}
	nblocks, ecc := qrBlocks[ver], qrECC[ver]
	raw := qrRawModules(ver) / 8
	short := nblocks - raw%nblocks // blocks with one data codeword fewer come first
	var blocks [][]int
	k := 0
	for i := 0; i < nblocks; i++ {
		n := raw/nblocks - ecc
		if i >= short {
			n++
		}
		blocks = append(blocks, words[k:k+n])
		k += n
	}
	var out []int
	for i := 0; i < len(blocks[len(blocks)-1]); i++ {
		for _, b := range blocks {
			if i < len(b) {
				out = append(out, b[i])
			}
		}
	}
	eccs := make([][]int, len(blocks))
	for i, b := range blocks {
		eccs[i] = qrRS(b, ecc)
	}
	for i := 0; i < ecc; i++ {
		for _, e := range eccs {
			out = append(out, e[i])
		}
	}
	return ver, out, nil
}

func finderLike(h *[7]int) int {
	n := h[1]
	core := n > 0 && h[2] == n && h[4] == n && h[5] == n && h[3] == n*3
	c := 0
	if core && h[0] >= n*4 && h[6] >= n {
		c++
	}
	if core && h[6] >= n*4 && h[0] >= n {
		c++
	}
	return c
}

// qrPenalty says how hard a masked code is to scan: long runs, 2x2 blocks, finder look-alikes, dark/light balance.
func qrPenalty(g qrGrid) int {
	size, score := len(g), 0
	line := make([]bool, size)
	for pass := 0; pass < 2; pass++ {
		for a := 0; a < size; a++ {
			for b := 0; b < size; b++ {
				if pass == 0 {
					line[b] = g[a][b]
				} else {
					line[b] = g[b][a]
				}
			}
			color, run := false, 0
			var hist [7]int
			push := func(length int) {
				if hist[0] == 0 {
					length += size // the light border before the first run
				}
				copy(hist[1:], hist[:6])
				hist[0] = length
			}
			for _, v := range line {
				if v == color {
					run++
					if run == 5 {
						score += 3
					} else if run > 5 {
						score++
					}
				} else {
					push(run)
					if !color {
						score += finderLike(&hist) * 40
					}
					color, run = v, 1
				}
			}
			if color {
				push(run)
				run = 0
			}
			push(run + size) // the light border after the last run
			score += finderLike(&hist) * 40
		}
	}
	dark := 0
	for y := 0; y < size; y++ {
		for x := 0; x < size; x++ {
			if g[y][x] {
				dark++
			}
			if y < size-1 && x < size-1 && g[y][x] == g[y][x+1] && g[y][x] == g[y+1][x] && g[y][x] == g[y+1][x+1] {
				score += 3
			}
		}
	}
	total := size * size
	diff := dark*20 - total*10
	if diff < 0 {
		diff = -diff
	}
	return score + 10*((diff+total-1)/total-1)
}

// qrCode is the QR code for text, as rows of modules (true is dark), without the quiet zone around it. mask is
// 0 to 7, or -1 for the one that scans best.
func qrCode(text string, mask int) (qrGrid, error) {
	ver, words, err := qrCodewords([]byte(text))
	if err != nil {
		return nil, err
	}
	size := 4*ver + 17
	newGrid := func() qrGrid {
		g := make(qrGrid, size)
		for i := range g {
			g[i] = make([]bool, size)
		}
		return g
	}
	grid, fixed := newGrid(), newGrid()
	put := func(g qrGrid, x, y int, dark bool) {
		g[y][x] = dark
		fixed[y][x] = true
	}
	abs := func(v int) int {
		if v < 0 {
			return -v
		}
		return v
	}
	for i := 0; i < size; i++ { // timing patterns
		put(grid, 6, i, i%2 == 0)
		put(grid, i, 6, i%2 == 0)
	}
	for _, c := range [][2]int{{3, 3}, {size - 4, 3}, {3, size - 4}} { // finder patterns and their light borders
		for dy := -4; dy <= 4; dy++ {
			for dx := -4; dx <= 4; dx++ {
				x, y := c[0]+dx, c[1]+dy
				if x >= 0 && x < size && y >= 0 && y < size {
					d := max(abs(dx), abs(dy))
					put(grid, x, y, d != 2 && d != 4)
				}
			}
		}
	}
	if ver > 1 { // alignment patterns
		n := ver/7 + 2
		step := (ver*4 + n*2 + 1) / (n*2 - 2) * 2
		if ver == 32 {
			step = 26
		}
		pos := []int{6}
		for i := n - 2; i >= 0; i-- {
			pos = append(pos, size-7-i*step)
		}
		for i, ax := range pos {
			for j, ay := range pos {
				if (i == 0 && j == 0) || (i == 0 && j == n-1) || (i == n-1 && j == 0) {
					continue
				}
				for dy := -2; dy <= 2; dy++ {
					for dx := -2; dx <= 2; dx++ {
						put(grid, ax+dx, ay+dy, max(abs(dx), abs(dy)) != 1)
					}
				}
			}
		}
	}
	formatBits := func(g qrGrid, m int) { // level M (0b00) and the mask, with their own error correction
		rem := m
		for i := 0; i < 10; i++ {
			rem = (rem << 1) ^ ((rem >> 9) * 0x537)
		}
		bits := (m<<10 | rem) ^ 0x5412
		bit := func(i int) bool { return bits>>i&1 == 1 }
		for i := 0; i < 6; i++ {
			put(g, 8, i, bit(i))
		}
		put(g, 8, 7, bit(6))
		put(g, 8, 8, bit(7))
		put(g, 7, 8, bit(8))
		for i := 9; i < 15; i++ {
			put(g, 14-i, 8, bit(i))
		}
		for i := 0; i < 8; i++ {
			put(g, size-1-i, 8, bit(i))
		}
		for i := 8; i < 15; i++ {
			put(g, 8, size-15+i, bit(i))
		}
		put(g, 8, size-8, true)
	}
	formatBits(grid, 0) // reserves its modules; drawn again with the chosen mask
	if ver >= 7 {
		rem := ver
		for i := 0; i < 12; i++ {
			rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
		}
		bits := ver<<12 | rem
		for i := 0; i < 18; i++ {
			put(grid, size-11+i%3, i/3, bits>>i&1 == 1)
			put(grid, i/3, size-11+i%3, bits>>i&1 == 1)
		}
	}
	i, total := 0, len(words)*8
	for right := size - 1; right >= 1; right -= 2 { // data goes up and down two columns at a time, skipping column 6
		if right == 6 {
			right = 5
		}
		for vert := 0; vert < size; vert++ {
			for j := 0; j < 2; j++ {
				x, y := right-j, vert
				if (right+1)&2 == 0 {
					y = size - 1 - vert
				}
				if !fixed[y][x] && i < total {
					grid[y][x] = words[i>>3]>>(7-(i&7))&1 == 1
					i++
				}
			}
		}
	}
	masked := func(m int) qrGrid {
		g := newGrid()
		for y := 0; y < size; y++ {
			for x := 0; x < size; x++ {
				g[y][x] = grid[y][x] != (!fixed[y][x] && qrMasks[m](x, y))
			}
		}
		formatBits(g, m)
		return g
	}
	if mask >= 0 {
		return masked(mask), nil
	}
	var best qrGrid
	bestScore := 0
	for m := 0; m < 8; m++ {
		g := masked(m)
		if s := qrPenalty(g); best == nil || s < bestScore {
			best, bestScore = g, s
		}
	}
	return best, nil
}

// qrText draws the code for a terminal, two rows of modules to a line, black on white (ANSI colors) so it scans
// in a dark terminal too.
func qrText(g qrGrid) string {
	const border = 2
	n := len(g)
	dark := func(x, y int) bool {
		return x-border >= 0 && x-border < n && y-border >= 0 && y-border < n && g[y-border][x-border]
	}
	var lines []string
	for y := 0; y < n+2*border; y += 2 {
		var b strings.Builder
		b.WriteString("  \033[30;47m")
		for x := 0; x < n+2*border; x++ {
			top, bottom := dark(x, y), dark(x, y+1)
			switch {
			case top && bottom:
				b.WriteString("█")
			case top:
				b.WriteString("▀")
			case bottom:
				b.WriteString("▄")
			default:
				b.WriteString(" ")
			}
		}
		b.WriteString("\033[0m")
		lines = append(lines, b.String())
	}
	return strings.Join(lines, "\n")
}

func qrSVG(g qrGrid) string {
	const border = 4
	n := len(g) + 2*border
	var path strings.Builder
	for y, row := range g {
		for x, v := range row {
			if v {
				fmt.Fprintf(&path, "M%d,%dh1v1h-1z", x+border, y+border)
			}
		}
	}
	return fmt.Sprintf(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">`+
		`<rect width="%d" height="%d" fill="#fff"/><path d="%s" fill="#000"/></svg>`, n, n, n, n, path.String())
}
