//go:build !windows

package main

import (
	"errors"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"unsafe"
)

// memoryMB is this computer's memory, or 0 if it can't tell.
func memoryMB() int { return int(physMemory() / 1048576) }

// physMemory is this computer's memory in bytes, or 0 if it can't tell.
func physMemory() int64 {
	if mac {
		out, _ := exec.Command("sysctl", "-n", "hw.memsize").Output()
		n, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
		return n
	}
	data, _ := os.ReadFile("/proc/meminfo")
	for _, line := range strings.Split(string(data), "\n") {
		if f := strings.Fields(line); len(f) >= 2 && f[0] == "MemTotal:" {
			kb, _ := strconv.ParseInt(f[1], 10, 64)
			return kb * 1024
		}
	}
	return 0
}

func colorsOn() bool { return true }

// stayAwake is for Windows; the launcher keeps a Mac or Linux PC awake with the system's own tool.
func stayAwake() (release func()) { return func() {} }

func openBrowser(url string) {
	var cmd *exec.Cmd
	if mac {
		cmd = exec.Command("open", url)
	} else {
		cmd = exec.Command("xdg-open", url)
		cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true} // the browser outlives the kit's window
	}
	if cmd.Start() == nil {
		go cmd.Wait()
	}
}

func terminate(p *os.Process) { _ = p.Signal(syscall.SIGTERM) }

func stopSignals() []os.Signal { return []os.Signal{os.Interrupt, syscall.SIGTERM, syscall.SIGHUP} }

// brokenPipe: with SIGPIPE caught, writing to a reader that stopped reading is an error the kit can notice.
var brokenPipe = []os.Signal{syscall.SIGPIPE}

// isTerminal is whether f is a terminal, not a file, a pipe or /dev/null (which is a device too).
func isTerminal(f *os.File) bool {
	var ws struct{ rows, cols, x, y uint16 }
	_, _, e := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), uintptr(syscall.TIOCGWINSZ), uintptr(unsafe.Pointer(&ws)))
	return e == 0
}

// terminalWidth is the terminal's width in columns, or 0 when stdout isn't one.
func terminalWidth() int {
	var ws struct{ rows, cols, x, y uint16 }
	if _, _, e := syscall.Syscall(syscall.SYS_IOCTL, os.Stdout.Fd(), uintptr(syscall.TIOCGWINSZ), uintptr(unsafe.Pointer(&ws))); e != 0 {
		return 0
	}
	return int(ws.cols)
}

// diskSpace is the free and total bytes of the disk a folder is on, as Python's shutil.disk_usage says them.
func diskSpace(p string) (free, total int64, err error) {
	var st syscall.Statfs_t
	if err := syscall.Statfs(p, &st); err != nil {
		return 0, 0, err
	}
	return int64(st.Bavail) * int64(st.Bsize), int64(st.Blocks) * int64(st.Bsize), nil
}

// sameDevice is whether two folders are on the same disk.
func sameDevice(a, b string) bool {
	var sa, sb syscall.Stat_t
	if syscall.Stat(a, &sa) != nil || syscall.Stat(b, &sb) != nil {
		return false
	}
	return sa.Dev == sb.Dev
}

// lockFile takes the kit's lock, errLocked if another kit command has it. A drive format without locks is no error.
func lockFile(f *os.File) error {
	err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB)
	if errors.Is(err, syscall.EWOULDBLOCK) {
		return errLocked
	}
	return nil
}

// winVolume and winDrives are Windows' drive letters; elsewhere drives are folders in /Volumes or /media.
func winVolume(string) (label, fs string) { return "", "" }
func winDrives() []string                 { return nil }

// startFile opens a file the way double-clicking it would, which only Windows' Startup folder needs.
func startFile(string) error { return errors.ErrUnsupported }

// writable is whether this user may save in a folder.
func writable(p string) bool { return syscall.Access(p, 2) == nil }

// noCache keeps what's written to f out of the computer's memory: a Mac's F_NOCACHE (an argument that isn't 0 turns
// caching off). Linux has no such switch: dropCache has it forget the file once it's saved.
func noCache(f *os.File) {
	if mac {
		syscall.FcntlFlock(f.Fd(), 48, &syscall.Flock_t{})
	}
}

// dropCache saves what's been written to f on the drive itself, and has the computer forget it, so that reading it
// back reads the drive.
func dropCache(f *os.File) error {
	if err := f.Sync(); err != nil { // on a Mac, F_FULLFSYNC: past the drive's own cache too
		return err
	}
	forget(f)
	return nil
}

// openFresh opens a file to read straight from its drive, not from what the computer remembers of it.
func openFresh(p string) (*os.File, error) {
	f, err := os.Open(p)
	if err == nil {
		noCache(f)
		forget(f)
	}
	return f, err
}

// forget has Linux drop what it remembers of a file (posix_fadvise POSIX_FADV_DONTNEED), which it does at once for
// what's saved.
func forget(f *os.File) {
	nr := map[string]uintptr{"amd64": 221, "arm64": 223}[runtime.GOARCH]
	if runtime.GOOS == "linux" && nr != 0 {
		syscall.Syscall6(nr, f.Fd(), 0, 0, 4, 0, 0)
	}
}
