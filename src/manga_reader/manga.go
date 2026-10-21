package main

import (
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"os"
	"path/filepath"
	"runtime"
	"runtime/debug"
	"sort"
	"strings"
	"sync"
)

type MangaPage struct {
	Index    int    // 0-indexed page number
	FilePath string // full path to image file
	OrigW    int
	OrigH    int
	ScaledW  int
	ScaledH  int
	Pixels   []uint32 // ARGB8888 downsampled pixels, nil when evicted
	YOffset  int      // Top Y position in the column scroll space
}

type Chapter struct {
	Name      string
	DirPath   string
	LeftPages []*MangaPage
	RightPages []*MangaPage
	AllPages  []*MangaPage
	LeftTotalH int
	RightTotalH int
	MaxScrollY int
}

type MangaManager struct {
	BaseDir      string
	Chapters     []*Chapter
	CurChapterIdx int
	OrientationRTL bool // true: right-to-left, false: left-to-right
	ColWidth     int    // 480 (sidebar open) or 510 (sidebar closed)
	mu           sync.Mutex
}

func NewMangaManager(baseDir string, colWidth int) (*MangaManager, error) {
	mm := &MangaManager{
		BaseDir:  baseDir,
		ColWidth: colWidth,
	}

	if err := mm.ReloadChapters(); err != nil {
		return nil, err
	}

	return mm, nil
}

func (mm *MangaManager) ReloadChapters() error {
	mm.mu.Lock()
	defer mm.mu.Unlock()

	entries, err := os.ReadDir(mm.BaseDir)
	if err != nil {
		return fmt.Errorf("read manga dir %s: %w", mm.BaseDir, err)
	}

	var chapters []*Chapter
	for _, entry := range entries {
		if entry.IsDir() {
			cPath := filepath.Join(mm.BaseDir, entry.Name())
			chap := mm.loadChapterMetadata(entry.Name(), cPath)
			if len(chap.AllPages) > 0 {
				chapters = append(chapters, chap)
			}
		}
	}

	// Sort chapters naturally
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].Name < chapters[j].Name
	})

	if len(chapters) == 0 {
		return fmt.Errorf("no chapters found in %s", mm.BaseDir)
	}

	mm.Chapters = chapters
	if mm.CurChapterIdx >= len(mm.Chapters) {
		mm.CurChapterIdx = 0
	}

	mm.partitionPages(mm.Chapters[mm.CurChapterIdx])
	return nil
}

func (mm *MangaManager) loadChapterMetadata(name, dirPath string) *Chapter {
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		return &Chapter{Name: name, DirPath: dirPath}
	}

	var pageFiles []string
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		ext := strings.ToLower(filepath.Ext(e.Name()))
		if ext == ".png" || ext == ".jpg" || ext == ".jpeg" {
			pageFiles = append(pageFiles, filepath.Join(dirPath, e.Name()))
		}
	}
	sort.Strings(pageFiles)

	chap := &Chapter{
		Name:    name,
		DirPath: dirPath,
	}

	for idx, pf := range pageFiles {
		w, h := getImageDimensions(pf)
		if w <= 0 || h <= 0 {
			w, h = 960, 1440 // fallback
		}

		scaledW := mm.ColWidth
		scaledH := int(float32(h) * float32(scaledW) / float32(w))

		p := &MangaPage{
			Index:    idx,
			FilePath: pf,
			OrigW:    w,
			OrigH:    h,
			ScaledW:  scaledW,
			ScaledH:  scaledH,
			Pixels:   nil,
		}
		chap.AllPages = append(chap.AllPages, p)
	}

	return chap
}

func getImageDimensions(filePath string) (int, int) {
	f, err := os.Open(filePath)
	if err != nil {
		return 0, 0
	}
	defer f.Close()

	cfg, _, err := image.DecodeConfig(f)
	if err != nil {
		return 0, 0
	}
	return cfg.Width, cfg.Height
}

func (mm *MangaManager) partitionPages(chap *Chapter) {
	chap.LeftPages = nil
	chap.RightPages = nil

	// Odd pages (1, 3, 5... index 0, 2, 4...) -> Left
	// Even pages (2, 4, 6... index 1, 3, 5...) -> Right
	for idx, p := range chap.AllPages {
		p.ScaledW = mm.ColWidth
		p.ScaledH = int(float32(p.OrigH) * float32(p.ScaledW) / float32(p.OrigW))

		if !mm.OrientationRTL {
			// Normal LTR: Page 1 Left, Page 2 Right
			if idx%2 == 0 {
				chap.LeftPages = append(chap.LeftPages, p)
			} else {
				chap.RightPages = append(chap.RightPages, p)
			}
		} else {
			// RTL: Page 1 Right, Page 2 Left
			if idx%2 == 0 {
				chap.RightPages = append(chap.RightPages, p)
			} else {
				chap.LeftPages = append(chap.LeftPages, p)
			}
		}
	}

	// Calculate cumulative Y offsets for left column
	leftY := 0
	for _, p := range chap.LeftPages {
		p.YOffset = leftY
		leftY += p.ScaledH + 4 // 4px gutter between stacked pages
	}
	chap.LeftTotalH = leftY

	// Calculate cumulative Y offsets for right column
	rightY := 0
	for _, p := range chap.RightPages {
		p.YOffset = rightY
		rightY += p.ScaledH + 4
	}
	chap.RightTotalH = rightY

	maxH := chap.LeftTotalH
	if chap.RightTotalH > maxH {
		maxH = chap.RightTotalH
	}
	chap.MaxScrollY = max(0, maxH-ScreenHeight)
}

func (mm *MangaManager) SetColWidth(colW int) {
	mm.mu.Lock()
	defer mm.mu.Unlock()
	if mm.ColWidth != colW {
		mm.ColWidth = colW
		// Evict all loaded buffers so they re-scale on demand
		for _, chap := range mm.Chapters {
			for _, p := range chap.AllPages {
				p.Pixels = nil
			}
			mm.partitionPages(chap)
		}
		debug.FreeOSMemory()
	}
}

func (mm *MangaManager) ToggleOrientation() {
	mm.mu.Lock()
	defer mm.mu.Unlock()
	mm.OrientationRTL = !mm.OrientationRTL
	if len(mm.Chapters) > 0 {
		mm.partitionPages(mm.Chapters[mm.CurChapterIdx])
	}
}

func (mm *MangaManager) CurrentChapter() *Chapter {
	mm.mu.Lock()
	defer mm.mu.Unlock()
	if len(mm.Chapters) == 0 {
		return nil
	}
	return mm.Chapters[mm.CurChapterIdx]
}

func (mm *MangaManager) SwitchChapter(idx int) {
	mm.mu.Lock()
	defer mm.mu.Unlock()
	if idx < 0 || idx >= len(mm.Chapters) {
		return
	}
	// Evict current chapter pixels
	for _, p := range mm.Chapters[mm.CurChapterIdx].AllPages {
		p.Pixels = nil
	}
	runtime.GC()

	mm.CurChapterIdx = idx
	mm.partitionPages(mm.Chapters[mm.CurChapterIdx])
}

// UpdateSlidingWindow implements the strict two-stage sliding window caching
// Only keeps visible pair + immediately preloaded pair in memory.
// Evicts any off-screen pages to prevent OOM on 128MB RAM embedded device.
func (mm *MangaManager) UpdateSlidingWindow(scrollY int) {
	mm.mu.Lock()
	defer mm.mu.Unlock()

	chap := mm.Chapters[mm.CurChapterIdx]
	viewportBottom := scrollY + ScreenHeight

	// Track which pages are needed: visible or preloaded within 1 viewport ahead
	needed := make(map[*MangaPage]bool)

	markNeeded := func(pages []*MangaPage) {
		for _, p := range pages {
			pTop := p.YOffset
			pBottom := p.YOffset + p.ScaledH

			// Visible: intersects [scrollY, viewportBottom]
			// Preload: intersects [viewportBottom, viewportBottom + ScreenHeight]
			if pBottom >= scrollY && pTop <= viewportBottom+ScreenHeight {
				needed[p] = true
			}
		}
	}

	markNeeded(chap.LeftPages)
	markNeeded(chap.RightPages)

	// Free memory of pages not in the needed set
	evicted := false
	for _, p := range chap.AllPages {
		if !needed[p] && p.Pixels != nil {
			p.Pixels = nil
			evicted = true
		}
	}

	if evicted {
		// Return OS memory to satisfy strict anti-OOM rule
		debug.FreeOSMemory()
	}

	// Load needed pages that don't have pixels loaded yet
	for p := range needed {
		if p.Pixels == nil {
			p.Pixels = loadAndDownsampleImage(p.FilePath, p.ScaledW, p.ScaledH)
		}
	}
}

// loadAndDownsampleImage decodes an image and performs nearest-neighbor or bilinear downsampling
// directly into an ARGB8888 []uint32 buffer.
func loadAndDownsampleImage(filePath string, targetW, targetH int) []uint32 {
	f, err := os.Open(filePath)
	if err != nil {
		return nil
	}
	defer f.Close()

	img, _, err := image.Decode(f)
	if err != nil {
		return nil
	}

	bounds := img.Bounds()
	origW := bounds.Dx()
	origH := bounds.Dy()
	if origW <= 0 || origH <= 0 || targetW <= 0 || targetH <= 0 {
		return nil
	}

	pixels := make([]uint32, targetW*targetH)

	// High speed downsampling directly to ARGB8888
	scaleX := float32(origW) / float32(targetW)
	scaleY := float32(origH) / float32(targetH)

	for dy := 0; dy < targetH; dy++ {
		sy := int(float32(dy) * scaleY)
		if sy >= origH {
			sy = origH - 1
		}
		rowOffset := dy * targetW

		for dx := 0; dx < targetW; dx++ {
			sx := int(float32(dx) * scaleX)
			if sx >= origW {
				sx = origW - 1
			}

			r, g, b, a := img.At(bounds.Min.X+sx, bounds.Min.Y+sy).RGBA()
			// Convert 16-bit color components to 8-bit ARGB8888
			argb := ((a >> 8) << 24) | ((r >> 8) << 16) | ((g >> 8) << 8) | (b >> 8)
			pixels[rowOffset+dx] = argb
		}
	}

	// Drop reference to original decoded image and return downsampled buffer
	img = nil
	return pixels
}
