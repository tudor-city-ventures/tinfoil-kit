//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"unsafe"
)

var (
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
)

// memoryMB is this PC's memory, or 0 if it can't tell.
func memoryMB() int { return int(physMemory() / 1048576) }

// physMemory is this PC's memory in bytes, or 0 if it can't tell.
func physMemory() int64 {
	var m struct {
		Length, MemoryLoad                        uint32
		TotalPhys, AvailPhys, TotalPageFile       uint64
		AvailPageFile, TotalVirtual, AvailVirtual uint64
		AvailExtendedVirtual                      uint64
	}
	m.Length = uint32(unsafe.Sizeof(m))
	if r, _, _ := kernel32.NewProc("GlobalMemoryStatusEx").Call(uintptr(unsafe.Pointer(&m))); r == 0 {
		return 0
	}
	return int64(m.TotalPhys)
}

// colorsOn says whether the console draws the QR code's colors, which it does once a program asks it to.
func colorsOn() bool {
	out, err := syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE)
	if err != nil {
		return false
	}
	var mode uint32
	if syscall.GetConsoleMode(out, &mode) != nil {
		return false
	}
	const virtualTerminalProcessing = 4
	r, _, _ := kernel32.NewProc("SetConsoleMode").Call(uintptr(out), uintptr(mode|virtualTerminalProcessing))
	return r != 0
}

// stayAwake asks Windows not to sleep while the kit is shared (the screen can still turn off): Windows sleeps after
// a while with nobody at the keyboard, and the kit with it. The request lasts as long as the thread that made it,
// until release.
func stayAwake() (release func()) {
	done := make(chan struct{})
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		const continuous, systemRequired = 0x80000000, 0x00000001
		state := kernel32.NewProc("SetThreadExecutionState")
		state.Call(uintptr(continuous | systemRequired))
		<-done
		state.Call(uintptr(continuous))
	}()
	var once sync.Once
	return func() { once.Do(func() { close(done) }) }
}

func openBrowser(url string) {
	verb, _ := syscall.UTF16PtrFromString("open")
	target, err := syscall.UTF16PtrFromString(url)
	if err != nil {
		return
	}
	const showNormal = 1
	shell32.NewProc("ShellExecuteW").Call(0, uintptr(unsafe.Pointer(verb)), uintptr(unsafe.Pointer(target)), 0, 0, showNormal)
}

func terminate(p *os.Process) { _ = p.Kill() }

// pidAlive says whether a program with this process id is running.
func pidAlive(pid int) bool {
	h, err := syscall.OpenProcess(0x1000, false, uint32(pid)) // PROCESS_QUERY_LIMITED_INFORMATION
	if err != nil {
		return false
	}
	defer syscall.CloseHandle(h)
	var code uint32
	return syscall.GetExitCodeProcess(h, &code) == nil && code == 259 // STILL_ACTIVE
}

// Closing the window arrives as SIGTERM, Ctrl-C as an interrupt.
func stopSignals() []os.Signal { return []os.Signal{os.Interrupt, syscall.SIGTERM} }

// Windows has no SIGPIPE: a reader that stopped reading is an error on the write.
var brokenPipe []os.Signal

// isTerminal is whether f is a console window, not a file, a pipe or NUL.
func isTerminal(f *os.File) bool {
	var mode uint32
	return syscall.GetConsoleMode(syscall.Handle(f.Fd()), &mode) == nil
}

// terminalWidth is the console's width in columns, or 0 when stdout isn't one.
func terminalWidth() int {
	out, err := syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE)
	if err != nil {
		return 0
	}
	var info struct {
		size, cursor             [2]int16
		attributes               uint16
		left, top, right, bottom int16
		maxWidth, maxHeight      int16
	}
	if r, _, _ := kernel32.NewProc("GetConsoleScreenBufferInfo").Call(uintptr(out), uintptr(unsafe.Pointer(&info))); r == 0 {
		return 0
	}
	return int(info.right-info.left) + 1
}

func utf16Ptr(s string) uintptr {
	p, _ := syscall.UTF16PtrFromString(s)
	return uintptr(unsafe.Pointer(p))
}

// diskSpace is the free and total bytes of the disk a folder is on, as Python's shutil.disk_usage says them.
func diskSpace(p string) (free, total int64, err error) {
	var avail, all, totalFree uint64
	r, _, e := kernel32.NewProc("GetDiskFreeSpaceExW").Call(utf16Ptr(p), uintptr(unsafe.Pointer(&avail)),
		uintptr(unsafe.Pointer(&all)), uintptr(unsafe.Pointer(&totalFree)))
	if r == 0 {
		return 0, 0, e
	}
	return int64(avail), int64(all), nil
}

// sameDevice is whether two folders are on the same disk: here, the same drive letter.
func sameDevice(a, b string) bool {
	if _, err := os.Stat(a); err != nil {
		return false
	}
	if _, err := os.Stat(b); err != nil {
		return false
	}
	va, _ := filepath.Abs(a)
	vb, _ := filepath.Abs(b)
	return strings.EqualFold(filepath.VolumeName(va), filepath.VolumeName(vb))
}

// lockFile takes the kit's lock, errLocked if another kit command has it. A drive format without locks is no error.
func lockFile(f *os.File) error {
	const exclusive, failImmediately = 2, 1
	var ol syscall.Overlapped
	r, _, e := kernel32.NewProc("LockFileEx").Call(f.Fd(), exclusive|failImmediately, 0, 1, 0, uintptr(unsafe.Pointer(&ol)))
	if r == 0 && errors.Is(e, syscall.Errno(33)) { // ERROR_LOCK_VIOLATION
		return errLocked
	}
	return nil
}

// winVolume is a drive's label and format ("exFAT", "NTFS", "FAT32"), or "" for what can't be read.
func winVolume(p string) (label, fs string) {
	abs, _ := filepath.Abs(p)
	var l, f [261]uint16
	r, _, _ := kernel32.NewProc("GetVolumeInformationW").Call(utf16Ptr(filepath.VolumeName(abs)+`\`),
		uintptr(unsafe.Pointer(&l[0])), 261, 0, 0, 0, uintptr(unsafe.Pointer(&f[0])), 261)
	if r == 0 {
		return "", ""
	}
	return syscall.UTF16ToString(l[:]), syscall.UTF16ToString(f[:])
}

// winDrives is the drive letters of the disks plugged into this PC, internal or USB, but not the one with the home
// folder. No network drives or CD drives, nor disks Windows can't read (locked by BitLocker, or empty card readers).
func winDrives() []string {
	home, _ := os.UserHomeDir()
	mine := strings.ToUpper(filepath.VolumeName(home))
	mask, _, _ := kernel32.NewProc("GetLogicalDrives").Call()
	var found []string
	for i := 0; i < 26; i++ {
		letter := fmt.Sprintf("%c:", 'A'+i)
		if mask>>i&1 == 0 || letter == mine {
			continue
		}
		t, _, _ := kernel32.NewProc("GetDriveTypeW").Call(utf16Ptr(letter + `\`))
		if _, fs := winVolume(letter + `\`); (t == 2 || t == 3) && fs != "" { // removable, fixed
			found = append(found, letter+`\`)
		}
	}
	return found
}

// startFile opens a file the way double-clicking it would.
func startFile(p string) error {
	r, _, _ := shell32.NewProc("ShellExecuteW").Call(0, utf16Ptr("open"), utf16Ptr(p), 0, 0, 1)
	if r <= 32 {
		return fmt.Errorf("Windows wouldn't open %s (error %d)", p, r)
	}
	return nil
}

// writable is whether this user may save in a folder. Windows' read-only mark means nothing on a folder, so any
// folder there is is one (as Python's os.access says too).
func writable(p string) bool { return isDir(p) }

// noCache is for a Mac: Windows can't write past its memory without writing whole sectors.
func noCache(*os.File) {}

// dropCache saves what's been written to f on the drive itself.
func dropCache(f *os.File) error { return f.Sync() }

// openFresh opens a file to read straight from its drive, not from what Windows remembers of it
// (FILE_FLAG_NO_BUFFERING), which reads only whole sectors into memory aligned to them: copier's buffer is.
func openFresh(p string) (*os.File, error) {
	name, err := syscall.UTF16PtrFromString(p)
	if err != nil {
		return nil, err
	}
	h, err := syscall.CreateFile(name, syscall.GENERIC_READ,
		syscall.FILE_SHARE_READ|syscall.FILE_SHARE_WRITE|syscall.FILE_SHARE_DELETE, nil, syscall.OPEN_EXISTING,
		syscall.FILE_ATTRIBUTE_NORMAL|0x20000000|0x08000000, 0) // FILE_FLAG_NO_BUFFERING, FILE_FLAG_SEQUENTIAL_SCAN
	if err != nil {
		return nil, &os.PathError{Op: "open", Path: p, Err: err}
	}
	return os.NewFile(uintptr(h), p), nil
}
