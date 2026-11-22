//go:build windows

package main

import (
	"os"
	"runtime"
	"syscall"
	"unsafe"
)

var (
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	shell32  = syscall.NewLazyDLL("shell32.dll")
)

// memoryMB is this PC's memory, or 0 if it can't tell.
func memoryMB() int {
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
	return int(m.TotalPhys / 1048576)
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
// a while with nobody at the keyboard, and the kit with it. The request lasts as long as the thread that made it.
func stayAwake() {
	go func() {
		runtime.LockOSThread()
		const continuous, systemRequired = 0x80000000, 0x00000001
		kernel32.NewProc("SetThreadExecutionState").Call(uintptr(continuous | systemRequired))
		select {}
	}()
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

// Closing the window arrives as SIGTERM, Ctrl-C as an interrupt.
func stopSignals() []os.Signal { return []os.Signal{os.Interrupt, syscall.SIGTERM} }
