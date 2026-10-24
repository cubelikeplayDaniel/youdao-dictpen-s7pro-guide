package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"strconv"
	"syscall"
	"time"
)

const (
	DEV_PATH = "/dev/input/event3"

	EV_SYN = 0x0000
	EV_KEY = 0x0001
	EV_ABS = 0x0003

	SYN_REPORT      = 0x0000
	BTN_TOUCH       = 0x014a
	BTN_TOOL_FINGER = 0x0145

	ABS_X              = 0x0000
	ABS_Y              = 0x0001
	ABS_MT_SLOT        = 0x002f
	ABS_MT_TOUCH_MAJOR = 0x0030
	ABS_MT_POSITION_X  = 0x0035
	ABS_MT_POSITION_Y  = 0x0036
	ABS_MT_TRACKING_ID = 0x0039
	ABS_MT_PRESSURE    = 0x003a

	RAW_MAX_X = 239
	RAW_MAX_Y = 1019
)

func logicalToRaw(logX, logY int) (int, int) {
	if logX < 0 {
		logX = 0
	}
	if logX > 1019 {
		logX = 1019
	}
	if logY < 0 {
		logY = 0
	}
	if logY > 239 {
		logY = 239
	}
	rawX := logY
	rawY := 1019 - logX
	return rawX, rawY
}

func emit(f *os.File, evType, evCode uint16, evValue int32) {
	var tv syscall.Timeval
	syscall.Gettimeofday(&tv)

	buf := make([]byte, 16)
	binary.LittleEndian.PutUint32(buf[0:4], uint32(tv.Sec))
	binary.LittleEndian.PutUint32(buf[4:8], uint32(tv.Usec))
	binary.LittleEndian.PutUint16(buf[8:10], evType)
	binary.LittleEndian.PutUint16(buf[10:12], evCode)
	binary.LittleEndian.PutUint32(buf[12:16], uint32(evValue))

	f.Write(buf)
}

func sendTap(f *os.File, logX, logY, durationMs int) {
	rawX, rawY := logicalToRaw(logX, logY)
	fmt.Printf("[s7pro_touch] TAP logical (%d,%d) -> raw (%d,%d), hold %d ms\n", logX, logY, rawX, rawY, durationMs)

	// DOWN
	emit(f, EV_ABS, ABS_MT_SLOT, 0)
	emit(f, EV_ABS, ABS_MT_TRACKING_ID, 2001)
	emit(f, EV_ABS, ABS_MT_POSITION_X, int32(rawX))
	emit(f, EV_ABS, ABS_MT_POSITION_Y, int32(rawY))
	emit(f, EV_ABS, ABS_MT_PRESSURE, 100)
	emit(f, EV_ABS, ABS_MT_TOUCH_MAJOR, 12)
	emit(f, EV_ABS, ABS_X, int32(rawX))
	emit(f, EV_ABS, ABS_Y, int32(rawY))
	emit(f, EV_KEY, BTN_TOUCH, 1)
	emit(f, EV_KEY, BTN_TOOL_FINGER, 1)
	emit(f, EV_SYN, SYN_REPORT, 0)

	time.Sleep(time.Duration(durationMs) * time.Millisecond)

	// UP
	emit(f, EV_ABS, ABS_MT_TRACKING_ID, -1)
	emit(f, EV_KEY, BTN_TOUCH, 0)
	emit(f, EV_KEY, BTN_TOOL_FINGER, 0)
	emit(f, EV_SYN, SYN_REPORT, 0)
}

func sendSwipe(f *os.File, sx, sy, ex, ey, durationMs, steps int) {
	sRawX, sRawY := logicalToRaw(sx, sy)
	eRawX, eRawY := logicalToRaw(ex, ey)
	stepDelay := time.Duration(durationMs*1000/steps) * time.Microsecond

	fmt.Printf("[s7pro_touch] SWIPE logical (%d,%d)->(%d,%d) | raw (%d,%d)->(%d,%d), steps=%d\n",
		sx, sy, ex, ey, sRawX, sRawY, eRawX, eRawY, steps)

	// DOWN
	emit(f, EV_ABS, ABS_MT_SLOT, 0)
	emit(f, EV_ABS, ABS_MT_TRACKING_ID, 2002)
	emit(f, EV_ABS, ABS_MT_POSITION_X, int32(sRawX))
	emit(f, EV_ABS, ABS_MT_POSITION_Y, int32(sRawY))
	emit(f, EV_ABS, ABS_MT_PRESSURE, 120)
	emit(f, EV_ABS, ABS_MT_TOUCH_MAJOR, 14)
	emit(f, EV_ABS, ABS_X, int32(sRawX))
	emit(f, EV_ABS, ABS_Y, int32(sRawY))
	emit(f, EV_KEY, BTN_TOUCH, 1)
	emit(f, EV_KEY, BTN_TOOL_FINGER, 1)
	emit(f, EV_SYN, SYN_REPORT, 0)

	time.Sleep(stepDelay)

	for i := 1; i <= steps; i++ {
		r := float64(i) / float64(steps)
		curX := sRawX + int(float64(eRawX-sRawX)*r)
		curY := sRawY + int(float64(eRawY-sRawY)*r)

		emit(f, EV_ABS, ABS_MT_POSITION_X, int32(curX))
		emit(f, EV_ABS, ABS_MT_POSITION_Y, int32(curY))
		emit(f, EV_ABS, ABS_X, int32(curX))
		emit(f, EV_ABS, ABS_Y, int32(curY))
		emit(f, EV_SYN, SYN_REPORT, 0)
		time.Sleep(stepDelay)
	}

	// UP
	emit(f, EV_ABS, ABS_MT_TRACKING_ID, -1)
	emit(f, EV_KEY, BTN_TOUCH, 0)
	emit(f, EV_KEY, BTN_TOOL_FINGER, 0)
	emit(f, EV_SYN, SYN_REPORT, 0)
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("Usage: s7pro_touch tap <x> <y> [dur_ms]")
		fmt.Println("       s7pro_touch swipe <sx> <sy> <ex> <ey> [dur_ms] [steps]")
		os.Exit(1)
	}

	f, err := os.OpenFile(DEV_PATH, os.O_WRONLY, 0666)
	if err != nil {
		fmt.Printf("Error opening %s: %v\n", DEV_PATH, err)
		os.Exit(1)
	}
	defer f.Close()

	cmd := os.Args[1]
	if cmd == "tap" && len(os.Args) >= 4 {
		x, _ := strconv.Atoi(os.Args[2])
		y, _ := strconv.Atoi(os.Args[3])
		dur := 80
		if len(os.Args) > 4 {
			dur, _ = strconv.Atoi(os.Args[4])
		}
		sendTap(f, x, y, dur)
	} else if cmd == "swipe" && len(os.Args) >= 6 {
		sx, _ := strconv.Atoi(os.Args[2])
		sy, _ := strconv.Atoi(os.Args[3])
		ex, _ := strconv.Atoi(os.Args[4])
		ey, _ := strconv.Atoi(os.Args[5])
		dur := 250
		steps := 20
		if len(os.Args) > 6 {
			dur, _ = strconv.Atoi(os.Args[6])
		}
		if len(os.Args) > 7 {
			steps, _ = strconv.Atoi(os.Args[7])
		}
		sendSwipe(f, sx, sy, ex, ey, dur, steps)
	} else {
		fmt.Println("Invalid arguments")
		os.Exit(1)
	}
	fmt.Println("[+] Done")
}
