//go:build !windows

package main

import (
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
)

// memoryMB is this computer's memory, or 0 if it can't tell.
func memoryMB() int {
	if mac {
		out, _ := exec.Command("sysctl", "-n", "hw.memsize").Output()
		n, _ := strconv.ParseInt(strings.TrimSpace(string(out)), 10, 64)
		return int(n / 1048576)
	}
	data, _ := os.ReadFile("/proc/meminfo")
	for _, line := range strings.Split(string(data), "\n") {
		if f := strings.Fields(line); len(f) >= 2 && f[0] == "MemTotal:" {
			kb, _ := strconv.Atoi(f[1])
			return kb / 1024
		}
	}
	return 0
}

func colorsOn() bool { return true }

// stayAwake is for Windows; the launcher keeps a Mac or Linux PC awake with the system's own tool.
func stayAwake() {}

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
