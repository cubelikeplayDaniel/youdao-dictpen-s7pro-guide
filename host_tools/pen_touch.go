package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"strconv"
	"time"
)

const (
	EV_SYN = 0
	EV_KEY = 1
	EV_ABS = 3

	SYN_REPORT      = 0
	BTN_TOUCH       = 330
	BTN_TOOL_FINGER = 325

	ABS_X              = 0
	ABS_Y              = 1
	ABS_MT_SLOT        = 47
	ABS_MT_TOUCH_MAJOR = 48
	ABS_MT_POSITION_X  = 53
	ABS_MT_POSITION_Y  = 54
	ABS_MT_TRACKING_ID = 57
	ABS_MT_PRESSURE    = 58
)

// Exactly 16 bytes for 32-bit Linux ARM struct input_event
func packEvent(evType uint16, evCode uint16, evVal int32) []byte {
	now := time.Now()
	sec := uint32(now.Unix())
	usec := uint32(now.Nanosecond() / 1000)

	buf := make([]byte, 16)
	binary.LittleEndian.PutUint32(buf[0:4], sec)
	binary.LittleEndian.PutUint32(buf[4:8], usec)
	binary.LittleEndian.PutUint16(buf[8:10], evType)
	binary.LittleEndian.PutUint16(buf[10:12], evCode)
	binary.LittleEndian.PutUint32(buf[12:16], uint32(evVal))
	return buf
}

// Convert Logical Display (1020x240 landscape) to Raw Hardware Coordinates (240x1020 portrait rotated 270)
// As reverse-engineered directly from greenui::winInputLoop (0x227bcc):
// logical_X = 1019 - raw_Y ==> raw_Y = 1019 - logical_X
// logical_Y = raw_X        ==> raw_X = logical_Y
func logicalToSensor(logX, logY int) (int, int) {
	if logX < 0 {
		logX = 0
	} else if logX > 1019 {
		logX = 1019
	}
	if logY < 0 {
		logY = 0
	} else if logY > 239 {
		logY = 239
	}

	rawX := logY
	rawY := 1019 - logX
	return rawX, rawY
}

func sendTap(dev *os.File, logX, logY int, durationMs int) error {
	sx, sy := logicalToSensor(logX, logY)
	trackingID := int32((time.Now().UnixNano()/1000000)%60000 + 100)
	fmt.Printf("[pen_touch] Tap logical (%d, %d) -> sensor (%d, %d), tid %d, hold %dms\n", logX, logY, sx, sy, trackingID, durationMs)

	eventsDown := [][]byte{
		packEvent(EV_ABS, ABS_MT_SLOT, 0),
		packEvent(EV_ABS, ABS_MT_TRACKING_ID, trackingID),
		packEvent(EV_ABS, ABS_MT_POSITION_X, int32(sx)),
		packEvent(EV_ABS, ABS_MT_POSITION_Y, int32(sy)),
		packEvent(EV_ABS, ABS_MT_PRESSURE, 80),
		packEvent(EV_ABS, ABS_MT_TOUCH_MAJOR, 12),
		packEvent(EV_ABS, ABS_X, int32(sx)),
		packEvent(EV_ABS, ABS_Y, int32(sy)),
		packEvent(EV_KEY, BTN_TOUCH, 1),
		packEvent(EV_KEY, BTN_TOOL_FINGER, 1),
		packEvent(EV_SYN, SYN_REPORT, 0),
	}

	for _, ev := range eventsDown {
		if _, err := dev.Write(ev); err != nil {
			return fmt.Errorf("write error down: %w", err)
		}
	}

	time.Sleep(time.Duration(durationMs) * time.Millisecond)

	eventsUp := [][]byte{
		packEvent(EV_ABS, ABS_MT_SLOT, 0),
		packEvent(EV_ABS, ABS_MT_TRACKING_ID, -1),
		packEvent(EV_ABS, ABS_MT_PRESSURE, 0),
		packEvent(EV_KEY, BTN_TOUCH, 0),
		packEvent(EV_KEY, BTN_TOOL_FINGER, 0),
		packEvent(EV_SYN, SYN_REPORT, 0),
	}

	for _, ev := range eventsUp {
		if _, err := dev.Write(ev); err != nil {
			return fmt.Errorf("write error up: %w", err)
		}
	}

	fmt.Println("[pen_touch] Tap successfully dispatched!")
	return nil
}

func sendSwipe(dev *os.File, sx, sy, ex, ey int, steps int, durationMs int) error {
	startSx, startSy := logicalToSensor(sx, sy)
	endSx, endSy := logicalToSensor(ex, ey)
	trackingID := int32((time.Now().UnixNano()/1000000)%60000 + 100)
	fmt.Printf("[pen_touch] Fling swipe logical (%d, %d) -> (%d, %d), sensor (%d, %d) -> (%d, %d), tid %d, %d steps, %dms\n",
		sx, sy, ex, ey, startSx, startSy, endSx, endSy, trackingID, steps, durationMs)

	stepDelay := time.Duration(durationMs/steps) * time.Millisecond

	// Down
	eventsDown := [][]byte{
		packEvent(EV_ABS, ABS_MT_SLOT, 0),
		packEvent(EV_ABS, ABS_MT_TRACKING_ID, trackingID),
		packEvent(EV_ABS, ABS_MT_POSITION_X, int32(startSx)),
		packEvent(EV_ABS, ABS_MT_POSITION_Y, int32(startSy)),
		packEvent(EV_ABS, ABS_MT_PRESSURE, 90),
		packEvent(EV_ABS, ABS_MT_TOUCH_MAJOR, 14),
		packEvent(EV_ABS, ABS_X, int32(startSx)),
		packEvent(EV_ABS, ABS_Y, int32(startSy)),
		packEvent(EV_KEY, BTN_TOUCH, 1),
		packEvent(EV_KEY, BTN_TOOL_FINGER, 1),
		packEvent(EV_SYN, SYN_REPORT, 0),
	}
	for _, ev := range eventsDown {
		if _, err := dev.Write(ev); err != nil {
			return err
		}
	}
	time.Sleep(stepDelay)

	// Steps with strictly linear motion to preserve high fling velocity at release
	for i := 1; i <= steps; i++ {
		t := float64(i) / float64(steps)
		curLogX := int(float64(sx) + float64(ex-sx)*t + 0.5)
		curLogY := int(float64(sy) + float64(ey-sy)*t + 0.5)
		curSx, curSy := logicalToSensor(curLogX, curLogY)

		eventsMove := [][]byte{
			packEvent(EV_ABS, ABS_MT_SLOT, 0),
			packEvent(EV_ABS, ABS_MT_POSITION_X, int32(curSx)),
			packEvent(EV_ABS, ABS_MT_POSITION_Y, int32(curSy)),
			packEvent(EV_ABS, ABS_MT_PRESSURE, 90),
			packEvent(EV_ABS, ABS_X, int32(curSx)),
			packEvent(EV_ABS, ABS_Y, int32(curSy)),
			packEvent(EV_SYN, SYN_REPORT, 0),
		}
		for _, ev := range eventsMove {
			if _, err := dev.Write(ev); err != nil {
				return err
			}
		}
		time.Sleep(stepDelay)
	}

	// Immediate UP to capture peak velocity without deceleration
	time.Sleep(5 * time.Millisecond)
	eventsUp := [][]byte{
		packEvent(EV_ABS, ABS_MT_SLOT, 0),
		packEvent(EV_ABS, ABS_MT_TRACKING_ID, -1),
		packEvent(EV_ABS, ABS_MT_PRESSURE, 0),
		packEvent(EV_KEY, BTN_TOUCH, 0),
		packEvent(EV_KEY, BTN_TOOL_FINGER, 0),
		packEvent(EV_SYN, SYN_REPORT, 0),
	}
	for _, ev := range eventsUp {
		if _, err := dev.Write(ev); err != nil {
			return err
		}
	}
	fmt.Println("[pen_touch] Fling swipe successfully dispatched!")
	return nil
}

func main() {
	if len(os.Args) < 3 {
		fmt.Println("Usage:")
		fmt.Println("  pen_touch tap <logical_x> <logical_y> [duration_ms]")
		fmt.Println("  pen_touch swipe <start_x> <start_y> <end_x> <end_y> [steps] [duration_ms]")
		os.Exit(1)
	}

	dev, err := os.OpenFile("/dev/input/event3", os.O_WRONLY, 0666)
	if err != nil {
		fmt.Printf("Error opening /dev/input/event3: %v\n", err)
		os.Exit(1)
	}
	defer dev.Close()

	cmd := os.Args[1]
	if cmd == "tap" {
		x, _ := strconv.Atoi(os.Args[2])
		y, _ := strconv.Atoi(os.Args[3])
		dur := 80
		if len(os.Args) > 4 {
			dur, _ = strconv.Atoi(os.Args[4])
		}
		if err := sendTap(dev, x, y, dur); err != nil {
			fmt.Printf("Tap error: %v\n", err)
			os.Exit(1)
		}
	} else if cmd == "swipe" {
		if len(os.Args) < 6 {
			fmt.Println("Invalid swipe arguments")
			os.Exit(1)
		}
		sx, _ := strconv.Atoi(os.Args[2])
		sy, _ := strconv.Atoi(os.Args[3])
		ex, _ := strconv.Atoi(os.Args[4])
		ey, _ := strconv.Atoi(os.Args[5])
		steps := 20
		dur := 220
		if len(os.Args) > 6 {
			steps, _ = strconv.Atoi(os.Args[6])
		}
		if len(os.Args) > 7 {
			dur, _ = strconv.Atoi(os.Args[7])
		}
		if err := sendSwipe(dev, sx, sy, ex, ey, steps, dur); err != nil {
			fmt.Printf("Swipe error: %v\n", err)
			os.Exit(1)
		}
	} else {
		fmt.Printf("Unknown command: %s\n", cmd)
		os.Exit(1)
	}
}
