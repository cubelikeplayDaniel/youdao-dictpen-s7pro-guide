package main

import (
	"encoding/binary"
	"io"
	"os"
	"sync"
)

// Linux input_event structure
type rawInputEvent struct {
	TimeSec  int32
	TimeUsec int32
	Type     uint16
	Code     uint16
	Value    int32
}

const (
	EV_SYN = 0x00
	EV_KEY = 0x01
	EV_ABS = 0x03

	SYN_REPORT = 0

	ABS_MT_SLOT        = 0x2f // 47
	ABS_MT_TOUCH_MAJOR = 0x30 // 48
	ABS_MT_POSITION_X  = 0x35 // 53
	ABS_MT_POSITION_Y  = 0x36 // 54
	ABS_MT_TRACKING_ID = 0x39 // 57
	ABS_MT_PRESSURE    = 0x3a // 58

	BTN_TOUCH       = 0x14a // 330
	BTN_TOOL_FINGER = 0x145 // 325

	SensorMaxX = 170
	SensorMaxY = 560
)

// TouchPoint represents mapped logical screen coordinates
type TouchPoint struct {
	Active     bool
	TrackingID int
	SensorX    int
	SensorY    int
	ScreenX    int
	ScreenY    int
}

type TouchState struct {
	Slots     [2]TouchPoint
	ActiveCnt int
	Timestamp int64 // microseconds
}

type InputManager struct {
	touchFile *os.File
	keyFile   *os.File
	mu        sync.Mutex
	state     TouchState
	homeKeyCh chan struct{}
}

// Map底层硬件 sensor sx(0..170), sy(0..560) 转换为逻辑像素 lx(0..1019), ly(0..239)
func SensorToScreen(sx, sy int) (lx, ly int) {
	if sx < 0 {
		sx = 0
	} else if sx > SensorMaxX {
		sx = SensorMaxX
	}
	if sy < 0 {
		sy = 0
	} else if sy > SensorMaxY {
		sy = SensorMaxY
	}
	ly = int((float32(sx) * 239.0 / 170.0) + 0.5)
	lx = int(1019.0 - (float32(sy) * 1019.0 / 560.0) + 0.5)
	return
}

func OpenInputManager() (*InputManager, error) {
	// 1. Touch device
	tPath := "/dev/input/by-path/axs_ts"
	tf, err := os.Open(tPath)
	if err != nil {
		tPath = "/dev/input/event3"
		tf, err = os.Open(tPath)
		if err != nil {
			return nil, err
		}
	}

	im := &InputManager{
		touchFile: tf,
		homeKeyCh: make(chan struct{}, 4),
	}

	// 2. Physical button device (gpio-keys)
	kPath := "/dev/input/by-path/gpio-keys"
	kf, err := os.Open(kPath)
	if err == nil {
		im.keyFile = kf
		go im.readKeyLoop()
	}

	go im.readTouchLoop()

	return im, nil
}

func (im *InputManager) Close() {
	if im.touchFile != nil {
		_ = im.touchFile.Close()
	}
	if im.keyFile != nil {
		_ = im.keyFile.Close()
	}
}

func (im *InputManager) readKeyLoop() {
	var ev rawInputEvent
	buf := make([]byte, 16)
	for {
		_, err := io.ReadFull(im.keyFile, buf)
		if err != nil {
			return
		}
		ev.Type = binary.LittleEndian.Uint16(buf[8:10])
		ev.Code = binary.LittleEndian.Uint16(buf[10:12])
		ev.Value = int32(binary.LittleEndian.Uint32(buf[12:16]))

		// When any key is pressed down (value == 1)
		if ev.Type == EV_KEY && ev.Value == 1 {
			select {
			case im.homeKeyCh <- struct{}{}:
			default:
			}
		}
	}
}

func (im *InputManager) readTouchLoop() {
	var ev rawInputEvent
	buf := make([]byte, 16)
	curSlot := 0

	// Working state before SYN_REPORT
	var tempSlots [2]TouchPoint

	for {
		_, err := io.ReadFull(im.touchFile, buf)
		if err != nil {
			return
		}
		ev.Type = binary.LittleEndian.Uint16(buf[8:10])
		ev.Code = binary.LittleEndian.Uint16(buf[10:12])
		ev.Value = int32(binary.LittleEndian.Uint32(buf[12:16]))

		switch ev.Type {
		case EV_ABS:
			switch ev.Code {
			case ABS_MT_SLOT:
				if ev.Value >= 0 && ev.Value <= 1 {
					curSlot = int(ev.Value)
				}
			case ABS_MT_TRACKING_ID:
				if ev.Value < 0 {
					tempSlots[curSlot].Active = false
					tempSlots[curSlot].TrackingID = -1
				} else {
					tempSlots[curSlot].Active = true
					tempSlots[curSlot].TrackingID = int(ev.Value)
				}
			case ABS_MT_POSITION_X:
				tempSlots[curSlot].SensorX = int(ev.Value)
			case ABS_MT_POSITION_Y:
				tempSlots[curSlot].SensorY = int(ev.Value)
			}
		case EV_SYN:
			if ev.Code == SYN_REPORT {
				im.mu.Lock()
				activeCount := 0
				for s := 0; s < 2; s++ {
					if tempSlots[s].Active {
						activeCount++
						lx, ly := SensorToScreen(tempSlots[s].SensorX, tempSlots[s].SensorY)
						tempSlots[s].ScreenX = lx
						tempSlots[s].ScreenY = ly
					}
					im.state.Slots[s] = tempSlots[s]
				}
				im.state.ActiveCnt = activeCount
				im.mu.Unlock()
			}
		}
	}
}

func (im *InputManager) GetState() TouchState {
	im.mu.Lock()
	defer im.mu.Unlock()
	return im.state
}

func (im *InputManager) HomeKeyPressed() bool {
	select {
	case <-im.homeKeyCh:
		return true
	default:
		return false
	}
}
