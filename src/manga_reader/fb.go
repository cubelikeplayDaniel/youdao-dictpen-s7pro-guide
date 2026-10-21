package main

import (
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

const (
	ScreenWidth  = 1020
	ScreenHeight = 240
	FbWidth      = 240
	FbHeight     = 1020
	FbStride     = 240
	FbSize       = FbWidth * FbHeight * 4 // 979200 bytes
)

type Framebuffer struct {
	file *os.File
	raw  []byte
	mem  []uint32
}

func OpenFramebuffer(device string) (*Framebuffer, error) {
	f, err := os.OpenFile(device, os.O_RDWR, 0)
	if err != nil {
		return nil, fmt.Errorf("open fb device %s: %w", device, err)
	}

	data, err := syscall.Mmap(int(f.Fd()), 0, FbSize, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_SHARED)
	if err != nil {
		f.Close()
		return nil, fmt.Errorf("mmap fb: %w", err)
	}

	mem := (*[FbSize / 4]uint32)(unsafe.Pointer(&data[0]))[:]

	return &Framebuffer{
		file: f,
		raw:  data,
		mem:  mem,
	}, nil
}

func (fb *Framebuffer) Close() {
	if fb.raw != nil {
		_ = syscall.Munmap(fb.raw)
	}
	if fb.file != nil {
		_ = fb.file.Close()
	}
}

// Present transfers the logical 1020x240 canvas buffer to the physical 240x1020 rotated framebuffer
// Rotation: rx = 239 - ly, ry = lx
func (fb *Framebuffer) Present(canvas []uint32) {
	for ly := 0; ly < ScreenHeight; ly++ {
		rx := 239 - ly
		srcRow := ly * ScreenWidth
		for lx := 0; lx < ScreenWidth; lx++ {
			ry := lx
			fb.mem[ry*FbStride+rx] = canvas[srcRow+lx]
		}
	}
}

// Canvas represents the 1020x240 logical drawing surface
type Canvas struct {
	Pixels []uint32
	W      int
	H      int
}

func NewCanvas(w, h int) *Canvas {
	return &Canvas{
		Pixels: make([]uint32, w*h),
		W:      w,
		H:      h,
	}
}

func (c *Canvas) Clear(color uint32) {
	for i := range c.Pixels {
		c.Pixels[i] = color
	}
}

func (c *Canvas) SetPixel(x, y int, color uint32) {
	if x >= 0 && x < c.W && y >= 0 && y < c.H {
		c.Pixels[y*c.W+x] = color
	}
}

func (c *Canvas) FillRect(x, y, w, h int, color uint32) {
	x0 := max(0, x)
	y0 := max(0, y)
	x1 := min(c.W, x+w)
	y1 := min(c.H, y+h)
	for cy := y0; cy < y1; cy++ {
		row := cy * c.W
		for cx := x0; cx < x1; cx++ {
			c.Pixels[row+cx] = color
		}
	}
}

func (c *Canvas) DrawRect(x, y, w, h int, color uint32, border int) {
	c.FillRect(x, y, w, border, color)
	c.FillRect(x, y+h-border, w, border, color)
	c.FillRect(x, y, border, h, color)
	c.FillRect(x+w-border, y, border, h, color)
}

func (c *Canvas) DrawRoundedRect(x, y, w, h, radius int, color uint32) {
	c.FillRect(x+radius, y, w-2*radius, h, color)
	c.FillRect(x, y+radius, radius, h-2*radius, color)
	c.FillRect(x+w-radius, y+radius, radius, h-2*radius, color)
}

// BlitImage copies a region of a decoded page buffer to canvas within clipping bounds
func (c *Canvas) BlitImage(dstX, dstY int, img []uint32, imgW, imgH int, clipX, clipY, clipW, clipH int) {
	if len(img) == 0 {
		return
	}

	xStart := max(0, clipX-dstX)
	yStart := max(0, clipY-dstY)
	xEnd := min(imgW, (clipX+clipW)-dstX)
	yEnd := min(imgH, (clipY+clipH)-dstY)

	for iy := yStart; iy < yEnd; iy++ {
		screenY := dstY + iy
		if screenY < clipY || screenY >= clipY+clipH || screenY >= c.H {
			continue
		}
		imgRow := iy * imgW
		canvasRow := screenY * c.W

		for ix := xStart; ix < xEnd; ix++ {
			screenX := dstX + ix
			if screenX >= clipX && screenX < clipX+clipW && screenX < c.W {
				c.Pixels[canvasRow+screenX] = img[imgRow+ix]
			}
		}
	}
}

// BlitImageZoomed renders an image with scaling and panning within a viewport clipping area
func (c *Canvas) BlitImageZoomed(dstX, dstY int, img []uint32, imgW, imgH int, zoom float32, panX, panY int, clipX, clipY, clipW, clipH int) {
	if len(img) == 0 {
		return
	}
	invZoom := 1.0 / zoom

	for cy := clipY; cy < clipY+clipH && cy < c.H; cy++ {
		canvasRow := cy * c.W
		relY := float32(cy - dstY - panY)
		srcY := int(relY * invZoom)
		if srcY < 0 || srcY >= imgH {
			continue
		}
		imgRow := srcY * imgW

		for cx := clipX; cx < clipX+clipW && cx < c.W; cx++ {
			relX := float32(cx - dstX - panX)
			srcX := int(relX * invZoom)
			if srcX >= 0 && srcX < imgW {
				c.Pixels[canvasRow+cx] = img[imgRow+srcX]
			}
		}
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
