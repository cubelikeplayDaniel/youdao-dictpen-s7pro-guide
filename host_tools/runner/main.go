package main

import (
	"fmt"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func getMiniappPID() int {
	out, err := exec.Command("pidof", "miniapp").Output()
	if err != nil {
		return 0
	}
	pidStr := strings.TrimSpace(string(out))
	if idx := strings.Index(pidStr, " "); idx != -1 {
		pidStr = pidStr[:idx]
	}
	pid, _ := strconv.Atoi(pidStr)
	return pid
}

func pauseMiniapp(pid int) {
	if pid > 0 {
		_ = syscall.Kill(pid, syscall.SIGSTOP)
	}
}

func resumeMiniapp(pid int) {
	if pid > 0 {
		_ = syscall.Kill(pid, syscall.SIGCONT)
	}
}

func main() {
	log.Println("[s7pro_runner] Starting Native App Runner...")

	pid := getMiniappPID()
	if pid > 0 {
		log.Printf("[s7pro_runner] Pausing official miniapp (PID %d)\n", pid)
		pauseMiniapp(pid)
	}

	// 退出清理函数
	cleanup := func() {
		if pid > 0 {
			log.Printf("[s7pro_runner] Restoring official miniapp (PID %d)\n", pid)
			resumeMiniapp(pid)
		}
	}
	defer cleanup()

	// 捕获系统退出信号
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// 渲染测试图像到屏幕
	imgPath := "/userdata/test.png"
	if len(os.Args) > 1 {
		imgPath = os.Args[1]
	}
	if _, err := os.Stat(imgPath); err == nil {
		log.Printf("[s7pro_runner] Displaying %s on /dev/fb0\n", imgPath)
		_ = exec.Command("/usr/bin/fbshow", imgPath, "/dev/fb0", "0").Run()
	}

	// 退出信号管道
	exitChan := make(chan string, 2)

	// 1. 监听物理按键：任何按键输入即触发退出
	go func() {
		f, err := os.Open("/dev/input/by-path/gpio-keys")
		if err != nil {
			return
		}
		defer f.Close()
		buf := make([]byte, 128)
		for {
			n, err := f.Read(buf)
			if err != nil {
				return
			}
			if n > 0 {
				exitChan <- "Physical Button Pressed"
				return
			}
		}
	}()

	// 2. 监听屏幕触摸：任何触控输入即触发退出
	// 给一个 500ms 的冷启动延迟，防止点击“极客工具箱”时残留的抬手动作被误判为退出
	go func() {
		time.Sleep(600 * time.Millisecond)
		f, err := os.Open("/dev/input/by-path/axs_ts")
		if err != nil {
			return
		}
		defer f.Close()
		buf := make([]byte, 128)
		for {
			n, err := f.Read(buf)
			if err != nil {
				return
			}
			if n > 0 {
				exitChan <- "Screen Touch Detected"
				return
			}
		}
	}()

	log.Println("[s7pro_runner] Waiting for user exit (Tap screen or press Home key)...")

	select {
	case reason := <-exitChan:
		log.Printf("[s7pro_runner] Exit triggered by: %s\n", reason)
	case sig := <-sigChan:
		log.Printf("[s7pro_runner] Received signal: %v\n", sig)
	case <-time.After(15 * time.Second): // 15秒无操作自动退出，保障绝不卡死
		log.Println("[s7pro_runner] 15-second safety timeout reached, exiting.")
	}

	fmt.Println("[s7pro_runner] Done. Restoring official UI now.")
}
