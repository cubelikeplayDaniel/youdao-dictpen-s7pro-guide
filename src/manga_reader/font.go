package main

import (
	"image"
	"image/color"
	"os"

	"golang.org/x/image/font"
	"golang.org/x/image/font/basicfont"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

type FontRenderer struct {
	face font.Face
}

func NewFontRenderer(size float64) *FontRenderer {
	fontPaths := []string{
		"/etc/miniapp/resources/fonts/HarmonyOS_Sans_SC_Medium.ttf",
		"/etc/miniapp/resources/fonts/Alibaba-PuHuiTi-Regular.otf",
		"/oem/secondary/etc/miniapp/resources/fonts/NotoSansSC-Regular.otf",
	}

	for _, p := range fontPaths {
		data, err := os.ReadFile(p)
		if err != nil {
			continue
		}
		ttf, err := opentype.Parse(data)
		if err != nil {
			continue
		}
		face, err := opentype.NewFace(ttf, &opentype.FaceOptions{
			Size:    size,
			DPI:     72,
			Hinting: font.HintingFull,
		})
		if err == nil {
			return &FontRenderer{face: face}
		}
	}

	return &FontRenderer{face: basicfont.Face7x13}
}

// CanvasImage adapts Canvas into a draw.Image target for font.Drawer
type CanvasImage struct {
	c *Canvas
}

func (ci *CanvasImage) ColorModel() color.Model {
	return color.RGBAModel
}

func (ci *CanvasImage) Bounds() image.Rectangle {
	return image.Rect(0, 0, ci.c.W, ci.c.H)
}

func (ci *CanvasImage) At(x, y int) color.Color {
	if x < 0 || x >= ci.c.W || y < 0 || y >= ci.c.H {
		return color.Transparent
	}
	val := ci.c.Pixels[y*ci.c.W+x]
	return color.RGBA{
		A: uint8(val >> 24),
		R: uint8(val >> 16),
		G: uint8(val >> 8),
		B: uint8(val),
	}
}

func (ci *CanvasImage) Set(x, y int, col color.Color) {
	if x < 0 || x >= ci.c.W || y < 0 || y >= ci.c.H {
		return
	}
	r, g, b, a := col.RGBA()
	if a == 0 {
		return
	}
	if a == 0xFFFF {
		ci.c.Pixels[y*ci.c.W+x] = 0xFF000000 | (uint32(r>>8) << 16) | (uint32(g>>8) << 8) | uint32(b>>8)
	} else {
		orig := ci.c.Pixels[y*ci.c.W+x]
		dstR := (orig >> 16) & 0xFF
		dstG := (orig >> 8) & 0xFF
		dstB := orig & 0xFF
		alpha := uint32(a >> 8)
		invAlpha := 255 - alpha
		newR := (uint32(r>>8)*alpha + dstR*invAlpha) / 255
		newG := (uint32(g>>8)*alpha + dstG*invAlpha) / 255
		newB := (uint32(b>>8)*alpha + dstB*invAlpha) / 255
		ci.c.Pixels[y*ci.c.W+x] = 0xFF000000 | (newR << 16) | (newG << 8) | newB
	}
}

func (c *Canvas) DrawString(x, y int, text string, col uint32, fr *FontRenderer) {
	if fr == nil || fr.face == nil {
		return
	}
	r := uint8((col >> 16) & 0xFF)
	g := uint8((col >> 8) & 0xFF)
	b := uint8(col & 0xFF)
	a := uint8((col >> 24) & 0xFF)
	if a == 0 {
		a = 255
	}

	dst := &CanvasImage{c: c}
	d := &font.Drawer{
		Dst:  dst,
		Src:  image.NewUniform(color.RGBA{R: r, G: g, B: b, A: a}),
		Face: fr.face,
		Dot:  fixed.P(x, y),
	}
	d.DrawString(text)
}
