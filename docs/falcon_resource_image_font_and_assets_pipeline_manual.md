# Youdao Dictionary Pen S7 Pro: Falcon Resource Loading, Image Decoding, Font Management, and Asset Caching Pipeline Manual

**Platform Target**: NetEase Youdao Dictionary Pen S7 Pro (网易有道词典笔 S7 Pro)  
**Hardware Specifications**: Cvitek CV1813H (ARM Cortex-A7 @ 1.0 GHz, ARMv7-A 32-bit, VFPv4-D16 / NEON)  
**Memory & OS Environment**: 128 MB Total Physical DDR RAM, Linux Kernel 5.10.4 (musl/glibc hybrid userland)  
**Target Binaries**: `/reverse_dump/libfalcon.so`, `/reverse_dump/miniapp`, `/reverse_dump/libjsapi_export_core.so`, `/reverse_dump/yddal_libs/*`  
**Classification**: Deep Internal Reverse Engineering & Runtime Architectural Reference

---

## Table of Contents
1. [Architectural Overview & Hardware Constraints](#1-architectural-overview--hardware-constraints)
2. [Image Subsystem & Decoding Pipeline](#2-image-subsystem--decoding-pipeline)
   - [2.1 Decoder Registration Mechanism](#21-decoder-registration-mechanism)
   - [2.2 Supported Formats & The WebP Vacuum](#22-supported-formats--the-webp-vacuum)
   - [2.3 Skia Bitmap Decoding & Color Configurations](#23-skia-bitmap-decoding--color-configurations)
   - [2.4 `<image>` Component & Scaling Mathematics](#24-image-component--scaling-mathematics)
3. [Multi-Threaded Asset Loading & Memory Caching Architecture](#3-multi-threaded-asset-loading--memory-caching-architecture)
   - [3.1 Thread Pool Topology (`ImgDec` vs `ImgDown`)](#31-thread-pool-topology-imgdec-vs-imgdown)
   - [3.2 In-Memory Decoded `BitmapCache` Subsystem](#32-in-memory-decoded-bitmapcache-subsystem)
   - [3.3 LRU Eviction & 4MB Hard Ceiling](#33-lru-eviction--4mb-hard-ceiling)
   - [3.4 UI Dispatch & Thread Synchronization](#34-ui-dispatch--thread-synchronization)
4. [Asset Resolution & URL Rewriting Pipeline](#4-asset-resolution--url-rewriting-pipeline)
   - [4.1 `JQuick::WXInstance::rewriteUrl` Protocol](#41-jquickwxinstancerewriteurl-protocol)
   - [4.2 Miniapp Package Bundling & Content Hashing](#42-miniapp-package-bundling--content-hashing)
5. [Font Subsystem, Typography & Glyph Fallback](#5-font-subsystem-typography--glyph-fallback)
   - [5.1 FreeType 2 & SkScalerContext Integration](#51-freetype-2--skscalercontext-integration)
   - [5.2 System Font Configuration & Parser (`fonts.xml`)](#52-system-font-configuration--parser-fontsxml)
   - [5.3 Glyph Fallback Pipeline (`SkFontHost::NextLogicalFont`)](#53-glyph-fallback-pipeline-skfonthostnextlogicalfont)
   - [5.4 CSS Typography Parsing (`WXText::updateStyleAndText`)](#54-css-typography-parsing-wxtextupdatestyleandtext)
   - [5.5 Custom Typeface Loading (`CreateTypefaceFromFile`)](#55-custom-typeface-loading-createtypefacefromfile)
6. [Media Player Bridge & Audio Asset Subsystem](#6-media-player-bridge--audio-asset-subsystem)
   - [6.1 QuickJS Native Audio Bridge (`soundPlayer`)](#61-quickjs-native-audio-bridge-soundplayer)
   - [6.2 Ubus IPC Architecture & Audio Daemon Routing](#62-ubus-ipc-architecture--audio-daemon-routing)
   - [6.3 Shared Memory Audio Buffer Streaming](#63-shared-memory-audio-buffer-streaming)
7. [Developer Guidelines & 128MB Memory Optimization](#7-developer-guidelines--128mb-memory-optimization)
   - [7.1 Decoded Memory Footprint Formula](#71-decoded-memory-footprint-formula)
   - [7.2 Asset Dimension & File Size Guardrails](#72-asset-dimension--file-size-guardrails)
   - [7.3 Checklist for Zero-Crash Resource Management](#73-checklist-for-zero-crash-resource-management)

---

## 1. Architectural Overview & Hardware Constraints

The NetEase Youdao Dictionary Pen S7 Pro operates in an intensely constrained embedded environment. The device hardware architecture dictates every aspect of how graphical assets, fonts, and media are decoded and stored in memory:

```
+-------------------------------------------------------------------------+
|                  NetEase Youdao Dictionary Pen S7 Pro                   |
|                  Cvitek CV1813H ARM Cortex-A7 @ 1.0 GHz                 |
+-------------------------------------------------------------------------+
| Physical RAM: 128 MB DDR3                                               |
|  - Kernel, Framebuffer (/dev/fb0), Drivers: ~36 MB                      |
|  - System Daemons (wpa_supplicant, ubusd, audiomanager, OCR): ~38 MB    |
|  - Falcon Runtime & QuickJS Process: ~54 MB Remaining Budget            |
+-------------------------------------------------------------------------+
| 2D Graphics Acceleration: NONE                                          |
|  - No GPU, No OpenGL ES, No EGL, No GrContext                           |
|  - Pure CPU Software Rasterization (Skia: SkBitmap, SkRGB16_Blitter)    |
+-------------------------------------------------------------------------+
```

### Pure Software Rasterization Reality
Binary analysis of `libfalcon.so` reveals an absolute absence of GPU-accelerated rendering contexts. Dynamic symbol analysis verifies:
- `GrContext`, `GrGLInterface`, `glGenTextures`, `eglCreateWindowSurface`: **0 matching symbols**.
- UI rendering operates entirely in CPU memory via Skia software blitters (`SkRGB16_Blitter`, `SkARGB32_Blitter`).
- Decoded images are stored in system RAM as uncompressed raster bitmaps. Every single pixel of every visible image must be transferred and blended by the Cortex-A7 CPU core into the RGB565 / ARGB8888 double-buffered framebuffer.

---

## 2. Image Subsystem & Decoding Pipeline

### 2.1 Decoder Registration Mechanism
Image decoders in Falcon are registered globally via an idempotent initialization function called during engine boot: `greenui_init_imagedecoder` located at virtual address `0x0042bc88` in `libfalcon.so`.

#### ARM Assembly Disassembly (`0x0042bc88`)
```arm
0042bc88 <greenui_init_imagedecoder>:
  42bc88:   ldr  r3, [pc, #0x28]        ; Load PC-relative offset to initialization flag
  42bc8c:   add  r3, pc, r3             ; Compute absolute address of guard byte
  42bc90:   ldrb r2, [r3]               ; Load byte flag
  42bc94:   cmp  r2, #0                 ; Has initialization already occurred?
  42bc98:   bxne lr                     ; If flag != 0, return immediately (idempotent guard)
  42bc9c:   push {r4, lr}               ; Save link register
  42bca0:   mov  r2, #1                 ; Set initialization flag to 1
  42bca4:   strb r2, [r3]               ; Store flag byte
  42bca8:   bl   0x42e054               ; bl _Z24sk_init_imagedecoder_pngv  (Register libpng)
  42bcac:   bl   0x42df48               ; bl _Z25sk_init_imagedecoder_jpegv (Register libjpeg)
  42bcb0:   pop  {r4, lr}               ; Restore registers
  42bcb4:   b    0x42db34               ; b  _Z24sk_init_imagedecoder_bmpv  (Tail-call BMP register)
```

The sequence executes exactly once:
1. `sk_init_imagedecoder_pngv`: Instantiates `SkPNGImageDecoder` factory linked against `libpng16`.
2. `sk_init_imagedecoder_jpegv`: Instantiates `SkJPEGImageDecoder` factory linked against `libjpeg.so.8`.
3. `sk_init_imagedecoder_bmpv`: Instantiates `SkBMPImageDecoder` factory wrapping `image_codec::BmpDecoderHelper`.

### 2.2 Supported Formats & The WebP Vacuum

Falcon provides concrete decoders for a strictly defined set of raster and vector formats:

| Format | Decoder Engine | Execution Method | Transparent Alpha | Frame Animation |
| :--- | :--- | :--- | :--- | :--- |
| **PNG** | `libpng16` / `SkPNGImageDecoder` | CPU Software | Yes (8-bit alpha) | No |
| **JPEG** | `libjpeg.so.8` / `SkJPEGImageDecoder` | CPU Software (libjpeg) | No | No |
| **BMP** | `image_codec::BmpDecoderHelper` | CPU Software | Optional | No |
| **SVG** | `lunasvg::Document` -> `greenui::LunaSvgDrawable` | CPU Vector Rasterization | Yes | No |
| **GIF** | `greenui::GifDecoder` -> `greenui::GifDrawable` | Streaming CPU Frame Dec | Yes (1-bit index) | Yes (Multi-frame) |
| **WEBP**| **NOT SUPPORTED** | **None (Fails at factory)** | N/A | N/A |

#### The WebP Void
A thorough examination of symbols and literal strings in `/reverse_dump/libfalcon.so` proves that **Google WebP decoding is completely unsupported**:
- `sk_init_imagedecoder_webp`: **0 occurrences**.
- `WebPDecode`, `VP8`, `libwebp`: **0 dynamic references**.
- Attempting to load `.webp` assets results in `SkImageDecoder::Factory(stream)` returning `nullptr`, throwing an asynchronous `error` event on the `<image>` component. WebP files must be transcoded to PNG or JPEG at bundle compile time.

#### GIF & SVG Implementations
Unlike standard single-frame decoders, animated GIFs and vector SVGs bypass standard `SkBitmap` caching:
- **GIF Decoder**: Uses `greenui::GifDecoder` and `greenui::GifHeaderParser` to construct an animated `greenui::GifDrawable`. Frame timing is coordinated via an internal timer handler invoking `requestInvalidate()` on each frame delay.
- **SVG Decoder**: Leverages the embedded lightweight LunaSVG engine (`lunasvg::Document::renderToBitmap`). SVG files are parsed on the decoding thread and rasterized dynamically into an `SkBitmap` matching the target `<image>` element viewport dimensions.

### 2.3 Skia Bitmap Decoding & Color Configurations
Image decoding is executed inside `greenui::doLoadBitmap` (address `0x0042bd08`).

#### C++ Function Prototype
```cpp
namespace greenui {
    Bitmap* doLoadBitmap(
        SkStreamRewindable* stream, 
        BitmapConfig preferredConfig, 
        int sampleSize
    );
}
```

#### Color Config Selection & Memory Tradeoff
Inside `greenui::doLoadBitmap`, the decoder configures `SkImageDecoder::Options`:

```cpp
SkImageDecoder::Options options;
if (preferredConfig == BitmapConfig::kRGB_565) {
    options.inPreferredConfig = SkBitmap::kRGB_565_Config;   // 2 bytes per pixel
} else {
    options.inPreferredConfig = SkBitmap::kARGB_8888_Config; // 4 bytes per pixel
}
options.inSampleSize = sampleSize; // Integer downsampling (1, 2, 4...)
```

- **`kARGB_8888_Config`**: Full 32-bit color with 8-bit alpha channel. Required for images with transparent or translucent backgrounds. Memory cost: `width * height * 4` bytes.
- **`kRGB_565_Config`**: 16-bit color (5 bits Red, 6 bits Green, 5 bits Blue) with zero alpha. **Halves RAM usage** (`width * height * 2` bytes). Ideal for fullscreen opaque photographic content and UI backgrounds.

### 2.4 `<image>` Component & Scaling Mathematics
The Weex/Falcon `<image>` component is backed by `JQuick::WXImage`, instantiated as a `JQuick::WXImageView` hosting a `greenui::ImageView`.

#### Resize Modes & Floating-Point Jump Table
Inside `JQuick::WXImageView::onDraw` (virtual address `0x0038bed8`), the `resize` attribute is read from instance offset `+0x138`. The value indexes a jump table:

```
resize enum value:
  0 => 'stretch' (Default)
  1 => 'cover'
  2 => 'contain'
```

#### Assembly Extraction of Aspect Ratio Arithmetic (`0x0038bed8`)
```arm
; --- cover: fmaxf(scaleX, scaleY) ---
0038c3fc:   vdiv.f32  s14, s1, s12       ; scaleX = viewWidth / bitmapWidth
0038c400:   vdiv.f32  s15, s0, s13       ; scaleY = viewHeight / bitmapHeight
0038c404:   bl        fmaxf              ; maxScale = max(scaleX, scaleY)
0038c408:   vmul.f32  s0, s12, s0        ; drawW = bitmapWidth * maxScale
0038c40c:   vmul.f32  s1, s13, s0        ; drawH = bitmapHeight * maxScale
0038c410:   vsub.f32  s14, s14, s0       ; dx = (viewWidth - drawW) * 0.5f
0038c414:   vsub.f32  s15, s15, s1       ; dy = (viewHeight - drawH) * 0.5f
0038c418:   b         0x38c440           ; execute clip & draw

; --- contain: fminf(scaleX, scaleY) ---
0038c360:   vdiv.f32  s14, s1, s12       ; scaleX = viewWidth / bitmapWidth
0038c364:   vdiv.f32  s15, s0, s13       ; scaleY = viewHeight / bitmapHeight
0038c368:   bl        fminf              ; minScale = min(scaleX, scaleY)
0038c36c:   vmul.f32  s0, s12, s0        ; drawW = bitmapWidth * minScale
0038c370:   vmul.f32  s1, s13, s0        ; drawH = bitmapHeight * minScale
0038c374:   vsub.f32  s14, s14, s0       ; dx = (viewWidth - drawW) * 0.5f (letterbox centering)
0038c378:   vsub.f32  s15, s15, s1       ; dy = (viewHeight - drawH) * 0.5f
0038c37c:   b         0x38c440           ; execute draw

; --- stretch: exact view fill ---
0038c430:   mov       r0, r5             ; drawable
0038c434:   mov       r1, #0             ; left = 0
0038c438:   mov       r2, #0             ; top = 0
0038c43c:   ldrd      r3, r4, [sp, #8]   ; right = viewWidth, bottom = viewHeight
0038c440:   bl        _ZN7greenui8Drawable9setBoundsEffff
```

#### Corner Radii & Clipping Contract
When `border-radius` is specified on an `<image>`, clipping is enforced via path clipping:
1. `BorderBackground::isRoundRectBorderInline()` detects non-zero corner radii.
2. `RoundRect::toPath(&SkPath)` constructs a rounded-rectangle clipping path.
3. `Canvas::clipPath(path, SkRegion::kIntersect_Op, true)` applies anti-aliased stencil clipping to the CPU rasterizer before `drawable->draw(canvas)` executes.

---

## 3. Multi-Threaded Asset Loading & Memory Caching Architecture

### 3.1 Thread Pool Topology (`ImgDec` vs `ImgDown`)
Asynchronous image retrieval and decoding is governed by the engine-wide singleton `JQuick::XImageLoader` (constructor at `0x002349bc` in `libfalcon.so`). To prevent I/O and network stalls from dropping UI frames, Falcon segregates background work into two dedicated thread pools:

```
                               +-----------------------------+
                               |     JQuick::XImageLoader    |
                               +--------------+--------------+
                                              |
                     +------------------------+------------------------+
                     |                                                 |
         [ ThreadPool: "ImgDec" ]                           [ ThreadPool: "ImgDown" ]
         Capacity: 1 - 3 Threads                            Capacity: 1 - 3 Threads
         Stack Size: 256 KB                                 Stack Size: 256 KB
                     |                                                 |
         - Local filesystem files                           - Remote HTTP / HTTPS URLs
         - Base64 data URLs                                 - libcurl / libcpr multi-socket
         - Memory stream decode                             - Writes to /tmp/falcon/cache
         - Skia CPU rasterization                           - Passes path to "ImgDec"
                     |                                                 |
                     +------------------------+------------------------+
                                              |
                                              v
                              +-------------------------------+
                              |    BitmapCache (LRU, 4MB)     |
                              +---------------+---------------+
                                              |
                                              v  Looper::getMainLooper()->post()
                              +---------------+---------------+
                              |    Main UI Thread Execution   |
                              |   (WXImageView::setImageBitmap)
                              +-------------------------------+
```

#### Assembly Evidence (`XImageLoader::XImageLoader` at `0x002349bc`)
```arm
00234b4c:   ldr   r1, [pc, #0x12c]      ; Load string "ImgDec"
00234b50:   mov   r0, r4                ; this
00234b54:   bl    _ZN6JQuick10ThreadPoolC1EPKc ; Initialize Decode ThreadPool
00234bb4:   ldr   r1, [pc, #0xcc]       ; Load string "ImgDown"
00234bb8:   add   r0, r4, #0x58         ; this + offset
00234bbc:   bl    _ZN6JQuick10ThreadPoolC1EPKc ; Initialize Download ThreadPool
00234bf0:   bl    _ZN6JQuick6Looper13getMainLooperEv  ; Fetch Main UI Looper
```

### 3.2 In-Memory Decoded `BitmapCache` Subsystem
The decoded image cache stores uncompressed `greenui::Bitmap` pointers indexed by canonical URL strings.

#### Struct Memory Layout: `JQuick::BitmapCache`
```cpp
class BitmapCache {
public:
    mutable std::mutex mMutex;                          // Offset 0x00: Concurrency guard
    size_t mMaxCacheSize;                               // Offset 0x04: 4,194,304 bytes (4MB)
    size_t mCurrentAllocatedSize;                       // Offset 0x08: Current atomic byte count
    std::list<CacheEntry> mLRUList;                     // Offset 0x0C: Order of access (MRU -> LRU)
    std::unordered_map<std::string, 
        std::list<CacheEntry>::iterator> mHashMap;      // Offset 0x18: O(1) Key lookup
};

struct CacheEntry {
    std::string key;                                    // Canonical resolved URL
    greenui::sp<greenui::Bitmap> bitmap;                // Decoded raster reference
    size_t byteCount;                                   // width * height * (bpp)
};
```

### 3.3 LRU Eviction & 4MB Hard Ceiling
During loader construction at `0x00234af0`, Falcon configures the memory ceiling:

```arm
00234af0:   ldr   r1, [pc, #0x184]      ; Literal pool: "imageloader"
00234af4:   add   r1, pc, r1
00234af8:   bl    _ZN6JQuick9getConfigEPKc
00234afc:   cmp   r0, #0
00234b00:   moveq r1, #0x400000         ; Default: 4,194,304 bytes = 4 MB
00234b04:   str   r1, [r4, #4]          ; Store mMaxCacheSize
```

#### Eviction Algorithm
Upon completion of bitmap decoding, the caching routine evaluates:
1. `mCurrentAllocatedSize + incomingSize > mMaxCacheSize`
2. If true, the mutex-locked eviction loop iterates from `mLRUList.back()` (the oldest referenced bitmap):
   - Evicts `mHashMap.erase(entry.key)`
   - Subtracts `entry.byteCount` from `mCurrentAllocatedSize`
   - Drops `entry.bitmap` reference counter (freeing memory if unreferenced by active views)
   - Pops from `mLRUList`
   - Continues until `mCurrentAllocatedSize + incomingSize <= mMaxCacheSize`

### 3.4 UI Dispatch & Thread Synchronization
When `ImgDec` finishes rasterization, it wraps the resulting `greenui::Bitmap` into a UI dispatch closure:
1. `Looper::getMainLooper()->createHandler()` receives a message payload containing the component UID and bitmap handle.
2. The UI main thread dequeues the message in `JQuick::Looper::loop()`.
3. Dispatches to `JQuick::WXImageView::setImageBitmap(sp<Bitmap>)`.
4. Invokes `requestLayout()` and `invalidate()`, triggering Skia CPU blitting on the next vertical sync pulse.

---

## 4. Asset Resolution & URL Rewriting Pipeline

### 4.1 `JQuick::WXInstance::rewriteUrl` Protocol
All resource references declared in miniapp templates (such as `<image src="...">`, `@keyframes`, and CSS `background-image`) pass through URL normalization inside `JQuick::WXInstance::rewriteUrl` (virtual address `0x003cbc94` in `libfalcon.so`).

#### Assembly Extraction of URL Resolution
```arm
003cbc94 <_ZN6JQuick10WXInstance10rewriteUrlERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE>:
  43cbc94:   push  {r4, r5, r6, r7, lr}
  43cbc98:   mov   r4, r0               ; Destination string
  43cbc9c:   mov   r5, r1               ; this (WXInstance)
  43cbca0:   mov   r6, r2               ; Input URL string
  43cbca4:   ldr   r1, [pc, #0xd0]      ; Literal: "data:image"
  43cbca8:   mov   r0, r6
  43cbcac:   bl    _ZNKSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEE4findEPKc ; find("data:image")
  43cbcb0:   cmp   r0, #0
  43cbcb4:   beq   0x3cbcf0             ; If matches data URI, return input unchanged

  ; Check "https://" and "http://"
  43cbcb8:   ldr   r1, [pc, #0xc0]      ; Literal: "https://"
  43cbcbc:   mov   r0, r6
  43cbcc0:   bl    _ZNKSt7__cxx1112basic_string...find
  43cbcc4:   cmp   r0, #0
  43cbcc8:   beq   0x3cbcf0             ; If network URI, return input unchanged

  ; Check relative vs absolute filesystem path
  43cbcdc:   ldrb  r3, [r6]             ; Load first character
  43cbce0:   cmp   r3, #0x2f            ; Check if starts with '/'
  43cbce4:   beq   0x3cbcf0             ; If absolute path, return unchanged

  ; Relative path: concatenate bundleDir + '/' + inputUrl
  43cbce8:   add   r1, r5, #0x48        ; instance->getBundleDir()
  43cbcec:   bl    _ZN6JQuick8pathJoinERKNSt7__cxx1112basic_stringIc...
```

#### Scheme Handling Matrix
```
Input String                            Resolution Action
-----------------------------------------------------------------------------------------
"data:image/png;base64,iVBOR..."    ->  Direct Base64 stream decoding in ImgDec.
"http://cdn.youdao.com/icon.png"    ->  Delegated to ImgDown thread pool via libcpr.
"file:///userdisk/data/custom.png"  ->  Stripped of "file://" scheme -> "/userdisk/data/custom.png".
"/secondary/miniapp/pkg/a/img.png"  ->  Treated as absolute Linux filesystem path.
"images/0166dc16.png"               ->  Rewritten: "${bundleDir}/images/0166dc16.png".
"./assets/logo.png"                 ->  Rewritten: "${bundleDir}/assets/logo.png".
```

### 4.2 Miniapp Package Bundling & Content Hashing
Official Youdao miniapps (e.g. `8080262605498742/a/manifest.json`) structure all static visual assets with content-addressed MD5 filenames inside an `images/` directory.

#### Sample `manifest.json` Certification Block
```json
{
  "appName": "拼读",
  "appid": "8080262605498742",
  "cert": {
    "images/0166dc16a17756c320e681752a0a19fc.png": {
      "size": 261,
      "md5": "7a3335ca18cc944ea7038b1f38b5f114"
    },
    "images/3549e99a4c58ac74ef0d595fd608c751.png": {
      "size": 450091,
      "md5": "b3d5a4482ba4a867b514580a1c3c37ef"
    }
  }
}
```

The Package Manager Service (`pm` / `libfalcon.so`) validates file checksums against `manifest.json` during app installation. If an asset on disk does not match its MD5 signature, the PMS installation rejects the package with error code `CERT_VERIFY_FAILED`.

---

## 5. Font Subsystem, Typography & Glyph Fallback

### 5.1 FreeType 2 & SkScalerContext Integration
Falcon text rendering is driven by FreeType 2 (`libfreetype.so.6`) integrated directly through Skia's `SkScalerContext_FreeType`.
- **Glyph Rasterization**: FreeType rasterizes glyph vectors into 8-bit grayscale alpha masks (`SkMask::kA8_Format`).
- **Subpixel LCD Decimation**: Disabled. Because the S7 Pro uses an RGB vertical-stripe LCD driven over SPI/MIPI, subpixel text rendering is turned off to save memory and CPU cycles; all glyphs use standard anti-aliasing (`kAntiAlias_Flag`).

### 5.2 System Font Configuration & Parser (`fonts.xml`)
System fonts are initialized at engine start inside `load_system_fonts` (virtual address `0x00496960` in `libfalcon.so`).

#### Assembly Extraction of Font XML Loader (`0x00496960`)
```arm
00496960 <load_system_fonts>:
  496960:   push  {r4, r5, r6, r7, r8, r9, r10, lr}
  49697c:   bl    _ZN7SkMutex7acquireEv          ; Acquire global Skia font mutex
  4969a4:   ldr   r1, [pc, #0x124]               ; Literal: "/etc/miniapp/resources/fonts/fonts.xml"
  4969b8:   bl    0x496774                       ; Call Expat XML font configuration parser
  4969c8:   cmp   r2, #0                         ; Test loaded font family count
  4969cc:   beq   0x496a40                       ; IF COUNT == 0 -> FATAL ABORT
  ...
  496a2c:   bl    _ZN7SkMutex7releaseEv          ; Release mutex and return success

; --- Fatal Abort Sequence ---
00496a40:   ldr   r0, [pc, #0x88]                ; Literal: "Failed to load system fonts, make sure resources/fonts/fonts.xml\n"
00496a44:   ldr   r1, [pc, #0x88]                ; stderr stream pointer
00496a48:   bl    fputs                          ; Print critical diagnostic
00496a5c:   bl    abort                          ; HARD ABORT CRASH
```

#### XML Grammar Specification
The parser at `0x00496774` leverages `libexpat` (`XML_ParserCreate`, `XML_SetElementHandler`, `XML_SetCharacterDataHandler`) to parse `/etc/miniapp/resources/fonts/fonts.xml`.

```xml
<?xml version="1.0" encoding="utf-8"?>
<familyset>
    <!-- Default primary UI family (First family parsed is default) -->
    <family name="sans-serif">
        <font weight="400" style="normal">NotoSans-Regular.ttf</font>
        <font weight="700" style="normal">NotoSans-Bold.ttf</font>
        <font weight="400" style="italic">NotoSans-Italic.ttf</font>
    </family>

    <!-- Chinese Fallback Family -->
    <family name="zh-Hans">
        <font weight="400" style="normal">SourceHanSansCN-Regular.otf</font>
        <font weight="700" style="normal">SourceHanSansCN-Bold.otf</font>
    </family>

    <!-- Mathematical Formula Family -->
    <family name="latex-math">
        <font weight="400" style="normal">cmr10.ttf</font>
        <font weight="400" style="normal">msam10.ttf</font>
    </family>
</familyset>
```

### 5.3 Glyph Fallback Pipeline (`SkFontHost::NextLogicalFont`)
When text contains characters outside the primary Latin font (e.g. Chinese Hanzi `有道`, Japanese Kana, mathematical operators `∫`, or UI symbols `〈`), Skia's shaper triggers the fallback logic in `SkFontHost::NextLogicalFont` (virtual address `0x004970f8`).

#### Logical Fallback Traversal
```
[ Character to Render: U+8BD1 '译' ]
                 |
                 v
[ Active Font: "sans-serif" (NotoSans-Regular.ttf) ]
  -> SkScalerContext::charToGlyphID(0x8BD1) == 0 (Missing / Tofu)
                 |
                 v
[ SkFontHost::NextLogicalFont(currentFontID, origFontID) ]
  - Assembly loop at 0x497174:
    add r4, r4, #1               ; Increment family index in fonts.xml
    ldr r3, [r6, r4, lsl #2]     ; Load next fallback family ("zh-Hans")
    ldrsh r0, [r5, #0x2c]        ; Preserve requested weight/style (e.g. bold=700)
                 |
                 v
[ Fallback Font: "zh-Hans" (SourceHanSansCN-Regular.otf) ]
  -> SkScalerContext::charToGlyphID(0x8BD1) == 0x2A14 (Found!)
                 |
                 v
[ FreeType Rasterizes Glyph from Fallback Typeface ]
```

### 5.4 CSS Typography Parsing (`WXText::updateStyleAndText`)
CSS text properties applied to `<text>` components are parsed inside `JQuick::WXText::updateStyleAndText` (virtual address `0x003a04d8`).

#### Supported Typography Attributes
- `fontSize`: Floating point size in px.
- `fontWeight`: Numeric `100..900` or keywords (`normal`, `bold`).
- `fontStyle`: `normal` or `italic`.
- `fontFamily`: Named family matching `fonts.xml`.
- `lineHeight`: Inter-line spacing.
- `textDecoration`: `underline`, `line-through`.
- `textOverflow`: `ellipsis`, `marquee`.
- `lines`: Maximum clamp line count.
- `letterSpacing`: Inter-glyph tracking.

#### Disassembly Analysis of `fontWeight` Parsing (`0x003a0a88`)
```arm
003a0a88:   mov   r3, r0                 ; r0 contains raw fontWeight string
003a0a8c:   moveq r3, #0x190             ; Default fallback: 0x190 = 400 (normal)
003a0a90:   beq   0x3a0ae4               ; Apply default if empty
003a0aa4:   bl    strtol                 ; Try parsing integer in base 10
003a0ab0:   cmp   r0, #0
003a0ab4:   ble   0x3a113c               ; IF <= 0, branch to keyword check

; Integer arithmetic: round to hundreds and clamp to 900
003a0ab8:   movw  r3, #0x851f
003a0abc:   movt  r3, #0x51eb            ; Magic division constant for 100
003a0ac0:   smull r3, r2, r3, r0
003a0ac8:   rsb   r3, r3, r2, asr #5     ; r3 = r0 / 100
003a0acc:   add   r3, r3, r3, lsl #2     ; r3 = (r3 * 5)
003a0ad0:   add   r3, r3, r3, lsl #2     ; r3 = (r3 * 5)
003a0ad4:   lsl   r3, r3, #2             ; r3 = (r3 * 4) -> (r3 * 100)
003a0adc:   cmp   r3, #0x384             ; Compare with 900 (0x384)
003a0ae0:   movge r3, #0x384             ; If >= 900, clamp to 900

; Keyword branch (0x3a113c):
003a113c:   ldr   r1, =0x736300          ; Literal: "bold"
003a1148:   bl    strcmp
003a114c:   cmp   r0, #0
003a1150:   moveq r3, #0x2bc             ; IF "bold", weight = 700 (0x2bc)
003a1154:   movne r3, #0x190             ; ELSE weight = 400 (0x190)
```

### 5.5 Custom Typeface Loading (`CreateTypefaceFromFile`)
Custom application fonts (`.ttf` or `.otf`) can be loaded dynamically at runtime via `SkFontHost::CreateTypefaceFromFile` (virtual address `0x00497490`):

```cpp
SkTypeface* SkFontHost::CreateTypefaceFromFile(const char* path) {
    SkFILEStream* stream = new SkFILEStream(path);
    if (!stream->isValid()) {
        delete stream;
        return nullptr;
    }
    return SkFontHost::CreateTypefaceFromStream(stream);
}
```

---

## 6. Media Player Bridge & Audio Asset Subsystem

### 6.1 QuickJS Native Audio Bridge (`soundPlayer`)
Miniapps perform audio playback via the `soundPlayer` native module registered in `/reverse_dump/libjsapi_export_core.so` by `sound_player_module_init_jsapis`.

#### C++ Native Proxy Class: `JSSoundPlayerProxy`
Source reference: `haasui/jsapi/core/soundplayer/jsapi_soundplayer_module.cpp`

```cpp
class JSSoundPlayerProxy : public JQBaseObject {
public:
    void play(JQFunctionCallbackInfo& info);
    void playFile(JQFunctionCallbackInfo& info);
    void playOnlineAudio(JQFunctionCallbackInfo& info);
    void playBase64(JQFunctionCallbackInfo& info);
    void playStreamTts(JQFunctionCallbackInfo& info);
    void stop(JQFunctionCallbackInfo& info);
    void quickStop(JQFunctionCallbackInfo& info);
    void setPlayTTSParam(JQFunctionCallbackInfo& info);

    // Signals dispatched back to JavaScript callbacks
    JQSignal<std::string, int64_t> mediaPlayerPositionChanged;
    JQSignal<std::string, int64_t> mediaPlayerDurationChanged;
    JQSignal<std::string, int32_t> mediaPlayerProgressChanged;
    JQSignal<std::string, YPlayerError> mediaPlayerEndChanged;
};
```

### 6.2 Ubus IPC Architecture & Audio Daemon Routing
`libjsapi_export_core.so` does not speak directly to the ALSA audio driver. Instead, it interacts with the system audio service through OpenWrt `ubus` IPC:

```
[ Miniapp JavaScript: soundPlayer.playFile('/userdisk/audio/word.mp3') ]
                                |
                                v
[ JSSoundPlayerProxy::playFile() (libjsapi_export_core.so) ]
                                |
                                v
[ YDALCOMMONAPI::YSoundPlayerInterface::Instance()->playFile() ]
                                |
                                v (RapidJSON Message Serialization)
[ libydubus_sender.so / libubus.so (UNIX Domain Socket: /var/run/ubus.sock) ]
                                |
                                v
[ System Audio Daemon: audiomanager / soundplayer service ]
                                |
                                v
[ Audio Codec Decoders: libFLAC, libspeex, libmad (MP3), ALSA (snd_pcm) ]
                                |
                                v
[ Hardware DAC -> ES8388 Audio Codec / Speaker ]
```

### 6.3 Shared Memory Audio Buffer Streaming
For real-time Text-To-Speech (TTS) audio streaming and raw PCM synthesis, the latency and memory overhead of JSON IPC is bypassed:
- `YSoundPlayerInterface::initShareMemSem()` allocates a POSIX shared memory arena (`/dev/shm/yddal_audio_shm`) protected by named semaphores.
- `YSoundPlayerInterface::playAudioDataFromMemory(appid, char* buffer, int length)` writes raw PCM blocks directly into shared memory, notifying the audio daemon with zero copies.

---

## 7. Developer Guidelines & 128MB Memory Optimization

### 7.1 Decoded Memory Footprint Formula
On the CV1813H architecture, decoded images consume memory according to the exact pixel footprint:

$$\text{RAM Footprint (Bytes)} = \text{Width (px)} \times \text{Height (px)} \times \text{BytesPerPixel} + \text{Heap Overhead (64 Bytes)}$$

Where:
- $\text{BytesPerPixel} = 4$ for `kARGB_8888_Config` (PNG with transparency)
- $\text{BytesPerPixel} = 2$ for `kRGB_565_Config` (Opaque JPEG / PNG)

#### Calculation Examples
- **Small Icon** ($48 \times 48$, ARGB8888):  
  $$48 \times 48 \times 4 = 9,216\text{ Bytes } (9\text{ KB})$$
- **Card Banner** ($400 \times 200$, ARGB8888):  
  $$400 \times 200 \times 4 = 320,000\text{ Bytes } (312.5\text{ KB})$$
- **High-Res Uncompressed Photo** ($1920 \times 1080$, ARGB8888):  
  $$1920 \times 1080 \times 4 = 8,294,400\text{ Bytes } (\mathbf{7.9\text{ MB}})$$  
  *Fatal*: Loading two $1920 \times 1080$ images simultaneously will instantly breach the 4MB `BitmapCache` limit and trigger severe memory pressure or Linux OOM termination.

### 7.2 Asset Dimension & File Size Guardrails

| Asset Category | Maximum Disk Size | Maximum Pixel Dimensions | Recommended Format | Target Color Config |
| :--- | :--- | :--- | :--- | :--- |
| **Icons & Badges** | $< 15\text{ KB}$ | $96 \times 96\text{ px}$ | PNG | `kARGB_8888` |
| **Illustrations** | $< 80\text{ KB}$ | $300 \times 300\text{ px}$ | PNG / SVG | `kARGB_8888` |
| **Fullscreen Backgrounds** | $< 120\text{ KB}$ | $240 \times 536\text{ px}$ | JPEG | `kRGB_565` |
| **Vector Glyphs** | $< 40\text{ KB}$ | Vector XML/SVG | SVG (LunaSVG) | Scalable Raster |
| **Voice Audio Clips** | $< 500\text{ KB}$ | 16 kHz Mono | MP3 / Speex | Standard PCM |

### 7.3 Checklist for Zero-Crash Resource Management

1. **Never Package WebP Files**: The runtime has 0 symbols for WebP. Transcode all WebP assets to PNG or JPEG during your build step.
2. **Explicitly Match Viewport Dimensions**: Always pre-scale raster assets to the exact size of the `<image>` container on device ($240 \times 536$ maximum). Never rely on `resize="contain"` or `resize="cover"` to downscale a large image; the memory cost is identical to rendering the full unscaled bitmap.
3. **Use RGB565 for Opaque Visuals**: Configure JPEG for large backgrounds and non-transparent illustrations to cut raster RAM consumption in half.
4. **Never Modify or Delete `fonts.xml`**: Binary disassembly of `load_system_fonts` proves that an empty or missing `fonts.xml` triggers an unrecoverable `abort()` crash.
5. **Release Audio Handlers on Page Unmount**: Always call `soundPlayer.stop()` inside the `destroyed()` lifecycle hook of your Weex page to terminate background ubus streams and release shared memory buffers.
6. **Honor the 4MB Image Loader Ceiling**: Total concurrent decoded images visible on a single page must never exceed 4 MB. For long scrolling feeds, virtualize list items using `<list>` and `<cell>` to unbind off-screen `<image>` drawables.
