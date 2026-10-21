package main

import (
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// UI Color Palette (ARGB8888)
const (
	ColorBgDark     = 0xFF121214
	ColorBgSidebar  = 0xFF1A1A1E
	ColorSidebarBdr = 0xFF2D2D35
	ColorBtnBg      = 0xFF2A2A32
	ColorBtnActive  = 0xFF2563EB // Modern Royal Blue
	ColorBtnExit    = 0xFFDC2626 // Crimson Red
	ColorTextWhite  = 0xFFFFFFFF
	ColorTextGray   = 0xFF9CA3AF
	ColorDivider    = 0xFF2E2E34
	ColorHighlight  = 0xFF10B981 // Emerald Green
)

type MangaApp struct {
	fb          *Framebuffer
	canvas      *Canvas
	input       *InputManager
	manga       *MangaManager

	// Font renderers
	fontRegular *FontRenderer
	fontSmall   *FontRenderer

	// Sidebar state
	sidebarExpanded bool
	sidebarWidth    int

	// Viewport layout
	leftColX  int
	leftColW  int
	rightColX int
	rightColW int

	// Scrolling & Dynamics
	scrollY        float32
	scrollVelocity float32
	damping        float32

	// Zoom & Pan
	zoom     float32
	panX     float32
	panY     float32
	isZoomed bool

	// Touch tracking
	touchActive    bool
	lastTouchX     int
	lastTouchY     int
	touchStartX    int
	touchStartY    int
	touchStartTime time.Time

	// Double-tap tracking
	lastTapTime time.Time
	lastTapX    int
	lastTapY    int

	// Pinch tracking
	initialPinchDist float32
	startPinchZoom   float32

	// Hardware brightness
	brightness int

	// Lifecycle
	running bool
}

func NewMangaApp() (*MangaApp, error) {
	fb, err := OpenFramebuffer("/dev/fb0")
	if err != nil {
		return nil, fmt.Errorf("open fb: %w", err)
	}

	input, err := OpenInputManager()
	if err != nil {
		fb.Close()
		return nil, fmt.Errorf("open input: %w", err)
	}

	manga, err := NewMangaManager("/userdisk/manga", 479)
	if err != nil {
		fb.Close()
		input.Close()
		return nil, fmt.Errorf("open manga: %w", err)
	}

	app := &MangaApp{
		fb:              fb,
		canvas:          NewCanvas(ScreenWidth, ScreenHeight),
		input:           input,
		manga:           manga,
		fontRegular:     NewFontRenderer(13),
		fontSmall:       NewFontRenderer(11),
		sidebarExpanded: true,
		sidebarWidth:    60,
		zoom:            1.0,
		damping:         0.92,
		brightness:      readHardwareBrightness(),
		running:         true,
	}

	app.updateLayout()
	return app, nil
}

func (app *MangaApp) updateLayout() {
	if app.sidebarExpanded {
		app.sidebarWidth = 60
		app.leftColX = 60
		app.leftColW = 478
		app.rightColX = 540
		app.rightColW = 478
	} else {
		app.sidebarWidth = 16
		app.leftColX = 16
		app.leftColW = 500
		app.rightColX = 518
		app.rightColW = 500
	}
	app.manga.SetColWidth(app.leftColW)
}

func readHardwareBrightness() int {
	data, err := os.ReadFile("/sys/class/backlight/backlight/brightness")
	if err != nil {
		return 120
	}
	val, err := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil {
		return 120
	}
	return val
}

func setHardwareBrightness(b int) {
	if b < 10 {
		b = 10
	}
	if b > 255 {
		b = 255
	}
	_ = os.WriteFile("/sys/class/backlight/backlight/brightness", []byte(strconv.Itoa(b)), 0644)
}

func (app *MangaApp) Run() {
	// 1. Suspend official miniapp to gain exclusive hardware control
	pauseOfficialMiniapp()

	// 2. Setup termination signals
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	// 3. Start local HTTP API server for programmatic control and testing
	go app.startHTTPControlServer()

	ticker := time.NewTicker(16 * time.Millisecond) // ~60 FPS
	defer ticker.Stop()

	// Initial sliding window load
	app.manga.UpdateSlidingWindow(int(app.scrollY))

	for app.running {
		select {
		case <-sigCh:
			app.running = false
		case <-ticker.C:
			if app.input.HomeKeyPressed() {
				app.running = false
				break
			}
			app.handleInput()
			app.updatePhysics()
			app.render()
			app.fb.Present(app.canvas.Pixels)
		}
	}

	// Clean teardown and restore official launcher
	app.cleanup()
}

func (app *MangaApp) cleanup() {
	app.input.Close()
	app.fb.Close()
	_ = os.Remove("/tmp/manga_cmd")

	// Resume miniapp and restore launcher
	resumeOfficialMiniapp()
	_ = exec.Command("/usr/bin/miniapp_cli", "start", "8080222437664451").Run()
}

func pauseOfficialMiniapp() {
	_ = exec.Command("killall", "-STOP", "miniapp").Run()
}

func resumeOfficialMiniapp() {
	_ = exec.Command("killall", "-CONT", "miniapp").Run()
}

func (app *MangaApp) startHTTPControlServer() {
	mux := http.NewServeMux()
	mux.HandleFunc("/cmd", func(w http.ResponseWriter, r *http.Request) {
		cmd := r.URL.Query().Get("action")
		log.Printf("[HTTP Control] Received command: %s", cmd)
		app.handleExternalCmd(cmd)
		w.Header().Set("Content-Type", "text/plain")
		fmt.Fprintf(w, "OK: %s\n", cmd)
	})

	server := &http.Server{
		Addr:    "127.0.0.1:9999",
		Handler: mux,
	}
	_ = server.ListenAndServe()
}

func (app *MangaApp) handleExternalCmd(cmd string) {
	parts := strings.Fields(cmd)
	if len(parts) == 0 {
		return
	}

	switch parts[0] {
	case "scroll":
		if len(parts) >= 2 {
			dy, _ := strconv.Atoi(parts[1])
			app.scrollY += float32(dy)
			app.scrollVelocity = 0
			app.manga.UpdateSlidingWindow(int(app.scrollY))
		}
	case "doubletap":
		x := 300
		y := 120
		if len(parts) >= 3 {
			x, _ = strconv.Atoi(parts[1])
			y, _ = strconv.Atoi(parts[2])
		}
		app.triggerDoubleTap(x, y)
	case "zoom":
		if len(parts) >= 2 {
			z, _ := strconv.ParseFloat(parts[1], 32)
			app.zoom = float32(z)
			if app.zoom > 1.05 {
				app.isZoomed = true
			} else {
				app.isZoomed = false
				app.panX = 0
				app.panY = 0
			}
		}
	case "pan":
		if len(parts) >= 3 {
			dx, _ := strconv.Atoi(parts[1])
			dy, _ := strconv.Atoi(parts[2])
			app.panX += float32(dx)
			app.panY += float32(dy)
		}
	case "sidebar":
		app.sidebarExpanded = !app.sidebarExpanded
		app.updateLayout()
		app.manga.UpdateSlidingWindow(int(app.scrollY))
	case "chapter":
		if len(parts) >= 2 {
			idx, _ := strconv.Atoi(parts[1])
			app.manga.SwitchChapter(idx)
			app.scrollY = 0
			app.scrollVelocity = 0
			app.manga.UpdateSlidingWindow(0)
		}
	case "orientation":
		app.manga.ToggleOrientation()
		app.manga.UpdateSlidingWindow(int(app.scrollY))
	case "brightness":
		if len(parts) >= 2 {
			if parts[1] == "+" {
				app.brightness += 25
			} else if parts[1] == "-" {
				app.brightness -= 25
			} else {
				b, _ := strconv.Atoi(parts[1])
				app.brightness = b
			}
			setHardwareBrightness(app.brightness)
		}
	case "exit":
		app.running = false
	}
}

func (app *MangaApp) handleInput() {
	ts := app.input.GetState()

	if ts.ActiveCnt == 0 {
		if app.touchActive {
			app.touchActive = false
			duration := time.Since(app.touchStartTime)
			distX := float32(app.lastTouchX - app.touchStartX)
			distY := float32(app.lastTouchY - app.touchStartY)
			dist := float32(math.Hypot(float64(distX), float64(distY)))

			if duration < 300*time.Millisecond && dist < 15 {
				app.onTap(app.lastTouchX, app.lastTouchY)
			}
		}
		app.initialPinchDist = 0
		return
	}

	// 1. Dual-finger Pinch to Zoom
	if ts.ActiveCnt == 2 && ts.Slots[0].Active && ts.Slots[1].Active {
		p0 := ts.Slots[0]
		p1 := ts.Slots[1]
		dist := float32(math.Hypot(float64(p1.ScreenX-p0.ScreenX), float64(p1.ScreenY-p0.ScreenY)))

		if app.initialPinchDist == 0 {
			app.initialPinchDist = dist
			app.startPinchZoom = app.zoom
		} else if app.initialPinchDist > 5 {
			ratio := dist / app.initialPinchDist
			newZoom := app.startPinchZoom * ratio
			if newZoom < 1.0 {
				newZoom = 1.0
			}
			if newZoom > 3.0 {
				newZoom = 3.0
			}
			app.zoom = newZoom
			if app.zoom > 1.05 {
				app.isZoomed = true
			} else {
				app.isZoomed = false
				app.panX = 0
				app.panY = 0
			}
		}
		return
	}

	// 2. Single finger drag / fling
	if ts.ActiveCnt == 1 && ts.Slots[0].Active {
		p := ts.Slots[0]
		if !app.touchActive {
			app.touchActive = true
			app.touchStartX = p.ScreenX
			app.touchStartY = p.ScreenY
			app.lastTouchX = p.ScreenX
			app.lastTouchY = p.ScreenY
			app.touchStartTime = time.Now()
			app.scrollVelocity = 0
		} else {
			dx := p.ScreenX - app.lastTouchX
			dy := p.ScreenY - app.lastTouchY

			if app.touchStartX < app.sidebarWidth {
				// Touch originated inside sidebar
			} else {
				if app.isZoomed && app.zoom > 1.05 {
					app.panX += float32(dx)
					app.panY += float32(dy)
				} else {
					app.scrollY -= float32(dy)
					app.scrollVelocity = -float32(dy)
					app.manga.UpdateSlidingWindow(int(app.scrollY))
				}
			}

			app.lastTouchX = p.ScreenX
			app.lastTouchY = p.ScreenY
		}
	}
}

func (app *MangaApp) onTap(x, y int) {
	if x < app.sidebarWidth {
		app.handleSidebarClick(x, y)
		return
	}

	now := time.Now()
	if now.Sub(app.lastTapTime) < 300*time.Millisecond {
		dist := math.Hypot(float64(x-app.lastTapX), float64(y-app.lastTapY))
		if dist < 40 {
			app.triggerDoubleTap(x, y)
			app.lastTapTime = time.Time{}
			return
		}
	}

	app.lastTapTime = now
	app.lastTapX = x
	app.lastTapY = y
}

func (app *MangaApp) triggerDoubleTap(x, y int) {
	if app.isZoomed {
		app.isZoomed = false
		app.zoom = 1.0
		app.panX = 0
		app.panY = 0
	} else {
		app.isZoomed = true
		app.zoom = 2.0
		app.panX = float32(ScreenWidth/2 - x)
		app.panY = float32(ScreenHeight/2 - y)
	}
}

func (app *MangaApp) handleSidebarClick(x, y int) {
	if !app.sidebarExpanded {
		app.sidebarExpanded = true
		app.updateLayout()
		app.manga.UpdateSlidingWindow(int(app.scrollY))
		return
	}

	// Button 1: Collapse Handle (Y: 6..28)
	if y >= 6 && y <= 28 {
		app.sidebarExpanded = false
		app.updateLayout()
		app.manga.UpdateSlidingWindow(int(app.scrollY))
		return
	}

	// Button 2: Chapter Toggle (Y: 34..62)
	if y >= 34 && y <= 62 {
		nextChap := (app.manga.CurChapterIdx + 1) % len(app.manga.Chapters)
		app.manga.SwitchChapter(nextChap)
		app.scrollY = 0
		app.scrollVelocity = 0
		app.manga.UpdateSlidingWindow(0)
		return
	}

	// Button 3: Orientation Toggle LTR / RTL (Y: 68..96)
	if y >= 68 && y <= 96 {
		app.manga.ToggleOrientation()
		app.manga.UpdateSlidingWindow(int(app.scrollY))
		return
	}

	// Button 4: Brightness Down (X: 6..28, Y: 126..148)
	if x >= 6 && x <= 28 && y >= 126 && y <= 148 {
		app.brightness -= 25
		if app.brightness < 10 {
			app.brightness = 10
		}
		setHardwareBrightness(app.brightness)
		return
	}

	// Button 5: Brightness Up (X: 32..54, Y: 126..148)
	if x >= 32 && x <= 54 && y >= 126 && y <= 148 {
		app.brightness += 25
		if app.brightness > 255 {
			app.brightness = 255
		}
		setHardwareBrightness(app.brightness)
		return
	}

	// Button 6: Exit Button ("退出") (Y: 196..234)
	if y >= 196 && y <= 234 {
		app.running = false
		return
	}
}

func (app *MangaApp) updatePhysics() {
	if !app.touchActive {
		if math.Abs(float64(app.scrollVelocity)) > 0.5 {
			app.scrollY += app.scrollVelocity
			app.scrollVelocity *= app.damping
			app.manga.UpdateSlidingWindow(int(app.scrollY))
		} else {
			app.scrollVelocity = 0
		}

		chap := app.manga.CurrentChapter()
		if chap != nil {
			if app.scrollY < 0 {
				app.scrollY += (0 - app.scrollY) * 0.2
			} else if app.scrollY > float32(chap.MaxScrollY) {
				app.scrollY += (float32(chap.MaxScrollY) - app.scrollY) * 0.2
			}
		}
	}
}

func (app *MangaApp) render() {
	app.canvas.Clear(ColorBgDark)

	chap := app.manga.CurrentChapter()
	if chap != nil {
		curScroll := int(app.scrollY)

		// 1. Render Left Column (Odd pages: 1, 3, 5...)
		for _, p := range chap.LeftPages {
			screenY := p.YOffset - curScroll
			if screenY+p.ScaledH < 0 || screenY > ScreenHeight {
				continue
			}
			if p.Pixels != nil {
				if app.isZoomed {
					app.canvas.BlitImageZoomed(app.leftColX, screenY, p.Pixels, p.ScaledW, p.ScaledH,
						app.zoom, int(app.panX), int(app.panY),
						app.leftColX, 0, app.leftColW, ScreenHeight)
				} else {
					app.canvas.BlitImage(app.leftColX, screenY, p.Pixels, p.ScaledW, p.ScaledH,
						app.leftColX, 0, app.leftColW, ScreenHeight)
				}
			}
		}

		// Subtle Divider between Left and Right columns
		dividerX := app.leftColX + app.leftColW
		app.canvas.FillRect(dividerX, 0, 2, ScreenHeight, ColorDivider)

		// 2. Render Right Column (Even pages: 2, 4, 6...)
		for _, p := range chap.RightPages {
			screenY := p.YOffset - curScroll
			if screenY+p.ScaledH < 0 || screenY > ScreenHeight {
				continue
			}
			if p.Pixels != nil {
				if app.isZoomed {
					app.canvas.BlitImageZoomed(app.rightColX, screenY, p.Pixels, p.ScaledW, p.ScaledH,
						app.zoom, int(app.panX), int(app.panY),
						app.rightColX, 0, app.rightColW, ScreenHeight)
				} else {
					app.canvas.BlitImage(app.rightColX, screenY, p.Pixels, p.ScaledW, p.ScaledH,
						app.rightColX, 0, app.rightColW, ScreenHeight)
				}
			}
		}
	}

	// 3. Render Sidebar UI
	app.renderSidebar()
}

func (app *MangaApp) renderSidebar() {
	if !app.sidebarExpanded {
		// Slim 16px floating tab handle
		app.canvas.FillRect(0, 0, 16, ScreenHeight, ColorBgSidebar)
		app.canvas.FillRect(15, 0, 1, ScreenHeight, ColorSidebarBdr)
		app.canvas.DrawString(4, ScreenHeight/2+6, ">", ColorHighlight, app.fontRegular)
		return
	}

	// Expanded 60px sidebar
	app.canvas.FillRect(0, 0, 60, ScreenHeight, ColorBgSidebar)
	app.canvas.FillRect(59, 0, 1, ScreenHeight, ColorSidebarBdr)

	// Button 1: Collapse Handle (Y: 6..28)
	app.canvas.DrawRoundedRect(4, 6, 52, 22, 3, ColorBtnBg)
	app.canvas.DrawString(12, 22, "< 收起", ColorHighlight, app.fontSmall)

	// Button 2: Chapter Selector (Y: 34..62)
	chap := app.manga.CurrentChapter()
	chapLabel := fmt.Sprintf("第 %d 话", app.manga.CurChapterIdx+1)
	app.canvas.DrawRoundedRect(4, 34, 52, 28, 4, ColorBtnActive)
	app.canvas.DrawString(12, 53, chapLabel, ColorTextWhite, app.fontRegular)

	// Button 3: Orientation Mode (Y: 68..96)
	app.canvas.DrawRoundedRect(4, 68, 52, 28, 4, ColorBtnBg)
	if !app.manga.OrientationRTL {
		app.canvas.DrawString(8, 87, "左 -> 右", ColorTextWhite, app.fontSmall)
	} else {
		app.canvas.DrawString(8, 87, "右 -> 左", ColorTextWhite, app.fontSmall)
	}

	// Button 4 & 5: Brightness Adjustment (Y: 102..164)
	app.canvas.DrawRoundedRect(4, 102, 52, 62, 4, ColorBtnBg)
	app.canvas.DrawString(18, 119, "亮度", ColorTextGray, app.fontSmall)

	// [-] and [+]
	app.canvas.DrawRoundedRect(6, 126, 22, 22, 3, ColorSidebarBdr)
	app.canvas.DrawString(13, 142, "-", ColorTextWhite, app.fontRegular)

	app.canvas.DrawRoundedRect(32, 126, 22, 22, 3, ColorSidebarBdr)
	app.canvas.DrawString(38, 142, "+", ColorTextWhite, app.fontRegular)

	// Progress indicator
	if chap != nil && chap.MaxScrollY > 0 {
		pct := int((app.scrollY / float32(chap.MaxScrollY)) * 100)
		if pct < 0 {
			pct = 0
		}
		if pct > 100 {
			pct = 100
		}
		pctStr := fmt.Sprintf("%d%%", pct)
		app.canvas.DrawString(18, 185, pctStr, ColorHighlight, app.fontSmall)
	}

	// Button 6: Exit Button ("退出") (Y: 196..234)
	app.canvas.DrawRoundedRect(4, 196, 52, 38, 5, ColorBtnExit)
	app.canvas.DrawString(16, 221, "退出", ColorTextWhite, app.fontRegular)
}

func main() {
	app, err := NewMangaApp()
	if err != nil {
		fmt.Printf("Error starting Manga App: %v\n", err)
		os.Exit(1)
	}
	app.Run()
}
