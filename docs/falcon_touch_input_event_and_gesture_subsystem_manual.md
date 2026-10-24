# NetEase Youdao Dictionary Pen S7 Pro (CV1813H)
# Native Touch Input, Event Dispatch, and Gesture Recognition Subsystem
## Technical Reference Manual & Binary Reverse Engineering Report

---

## 1. Executive Summary & Hardware/Architecture Overview

### 1.1 Architecture & Hardware Specifications
The NetEase Youdao Dictionary Pen S7 Pro is driven by the Sophgo CV1813H SoC featuring a 32-bit ARM Cortex-A7 core (ARMv7-A architecture with Thumb-2 and NEON VFPv4 vector floating point). The device runs an embedded GNU/Linux platform powering **GreenUI** (a lightweight native C++ UI framework) and the **NetEase Falcon MiniApp Runtime** (an optimized hybrid framework hosting Weex/Vue 2.6 applications compiled to QuickJS bytecode).

| Parameter | Specification | Details / Binary Verification |
| :--- | :--- | :--- |
| **SoC / CPU** | Sophgo CV1813H (ARM Cortex-A7) | 32-bit little-endian ARMv7-A (`elf32-littlearm`) |
| **Touchscreen IC & Kernel Driver** | FocalTech / AXS Touch IC (`axs_ts.ko`) | Kernel input evdev node `/dev/input/event3` |
| **Physical Display & Touch Sensor** | 240 (Width) × 1020 (Height) portrait | Native hardware panel resolution |
| **Logical UI Canvas** | 1020 (Width) × 240 (Height) landscape | 270° counter-clockwise rotation |
| **Touch Event Abstraction** | Linux Input Subsystem (Evdev Type B MT) | Multi-Touch Protocol Type B (Slots & Tracking ID) |
| **Input Pipeline Stack** | Kernel `axs_ts` $\to$ `libts.so` / `ts_input.so` $\to$ `libfalcon.so` (`greenui::winInputLoop`) | Event thread `greenui_input` |
| **UI State Machine & Framework** | `greenui::View` / `greenui::ViewGroup` | 8.0 px touch slop, 800 ms long-press timer |
| **High-level Runtime** | Falcon / QuickJS VM (`libquickjs.so`) | Vue 2 SFCs compiled to `.js.bin` bytecode |

```
               [AXS / FocalTech Touch Sensor (240x1020)]
                                  │
                                  ▼
                     [Kernel Driver: axs_ts.ko]
                                  │  /dev/input/event3
                                  ▼
                [tslib Multi-Touch: ts_input.so / libts.so]
                                  │  ts_read_mt()
                                  ▼
      [libfalcon.so: greenui::winInputLoop (0x2275d4 - 0x227ce0)]
      ├── Coordinate Mapping: raw(240x1020) -> logical(1020x240)
      ├── Axis Swapping: logX = 1019 - rawY, logY = rawX
      └── Dispatches greenui::MotionEvent to FBNativeWindow
                                  │
         ┌────────────────────────┴────────────────────────┐
         ▼                                                 ▼
[greenui::GlobalGestureHelper]                    [greenui::Window / View Hierarchy]
 ├── TopSwipeGesture (0x588930)                    ├── ScrollView (0x43b444)
 │    └─ Suppressed by FLAG_NO_TOP_PANEL           │    └─ Intercepts when Δ > 8.0px
 └── LeftSwipeBackGesture (0x588308)               └── View::onTouchEvent (0x448b88)
      └─ Suppressed by mDisableLeftSwipeBack            ├── Slop check: pointInView(8.0px)
                                                        ├── Timer: 800ms Long-Press
                                                        └── OnClick -> performClick()
                                                                   │
                                                                   ▼
                                                   [JQuick::Component (0x37a6bc)]
                                                        ├── click / longpress
                                                        └── WXGesture::onTouch (0x3bafd4)
                                                             └─ touchstart/move/end
                                                                   │
                                                                   ▼
                                                    [Falcon MiniApp / VDOM VM]
                                                    (QuickJS Bytecode: indexPage.js.bin)
```

---

## 2. Evdev Input Protocol & 32-bit ARM Linux ABI

### 2.1 Struct Input Event Memory Layout
On 32-bit ARM Linux (EABI, little-endian), `struct input_event` defined in `<linux/input.h>` has a strictly packed size of **16 bytes**.

```c
struct input_event {
    struct timeval time; // 8 bytes (tv_sec: 4 bytes, tv_usec: 4 bytes)
    __u16 type;          // 2 bytes (EV_SYN=0, EV_KEY=1, EV_ABS=3)
    __u16 code;          // 2 bytes (ABS_MT_*, BTN_TOUCH, etc.)
    __s32 value;         // 4 bytes (coordinate, pressure, slot, status)
};
```

#### Binary Memory Representation:
```
+--------------------+--------------------+--------+--------+--------------------+
| tv_sec (uint32)    | tv_usec (uint32)   | type   | code   | value (int32)      |
| Offset 0x00 - 0x03 | Offset 0x04 - 0x07 | 0x08-09| 0x0A-0B| Offset 0x0C - 0x0F |
+--------------------+--------------------+--------+--------+--------------------+
| 4 Bytes            | 4 Bytes            | 2 Bytes| 2 Bytes| 4 Bytes            |
+--------------------+--------------------+--------+--------+--------------------+
```
- **Python Struct Format**: `'IIHHi'` (Little-Endian: `<IIHHi`).
- **Go binary.LittleEndian Encoding**: 4 bytes sec, 4 bytes usec, 2 bytes type, 2 bytes code, 4 bytes value.

### 2.2 Evdev Multi-Touch Protocol Type B Specification
The S7 Pro touch driver (`axs_ts.ko`) emits Multi-Touch Protocol Type B packets. The tslib plugin `reverse_dump/ts_input.so` decodes these packets in `input_read_mt` (`0x850` - `0x14a0`).

| Event Type (`type`) | Event Code (`code`) | Value Semantics (`value`) | Purpose in S7 Pro Stack |
| :--- | :--- | :--- | :--- |
| `EV_ABS` (`0x0003`) | `ABS_MT_SLOT` (`0x002f` = 47) | Slot index ($0 \le \text{slot} \le 4$) | Multi-touch contact slot selection |
| `EV_ABS` (`0x0003`) | `ABS_MT_TRACKING_ID` (`0x0039` = 57) | ID $\ge 0$ (down/move) or `-1` (up) | Contact lifecycle tracker |
| `EV_ABS` (`0x0003`) | `ABS_MT_POSITION_X` (`0x0035` = 53) | Raw sensor X coordinate ($0 \le X \le 239$) | Raw horizontal touch position |
| `EV_ABS` (`0x0003`) | `ABS_MT_POSITION_Y` (`0x0036` = 54) | Raw sensor Y coordinate ($0 \le Y \le 1019$)| Raw vertical touch position |
| `EV_ABS` (`0x0003`) | `ABS_MT_PRESSURE` (`0x003a` = 58) | Contact pressure (e.g., $50 \sim 200$) | Touch force / contact weight |
| `EV_ABS` (`0x0003`) | `ABS_MT_TOUCH_MAJOR` (`0x0030` = 48)| Touch contact ellipse major diameter | Finger contact surface size |
| `EV_ABS` (`0x0003`) | `ABS_X` (`0x0000` = 0) | Single-touch legacy X coordinate | Legacy single-touch fallback |
| `EV_ABS` (`0x0003`) | `ABS_Y` (`0x0001` = 1) | Single-touch legacy Y coordinate | Legacy single-touch fallback |
| `EV_KEY` (`0x0001`) | `BTN_TOUCH` (`0x014a` = 330) | `1` (Finger Down), `0` (Finger Up) | Global touch state toggle |
| `EV_KEY` (`0x0001`) | `BTN_TOOL_FINGER` (`0x0145` = 325)| `1` (Finger active), `0` (Inactive) | Tool type classification |
| `EV_SYN` (`0x0000`) | `SYN_REPORT` (`0x0000` = 0) | `0` | Atomic packet delimiter |

---

## 3. Disassembly & Coordinate Transformation Analysis

### 3.1 greenui::winInputLoop Disassembly (`libfalcon.so`)
The input loop thread is initialized in `greenui::FBNativeWindow` and calls `greenui::winInputLoop` located between `0x2275d4` and `0x227ce0`. The input loop reads from tslib (`ts_read_mt`) and transforms the coordinates before calling `greenui::FBNativeWindow::inputTouchEvent`.

```arm
; ==============================================================================
; Function: greenui::winInputLoop(void*)
; Target Address Range: 0x00227bcc - 0x00227cb8
; Architecture: 32-bit ARM (ARMv7-A / Thumb-2, little-endian)
; Register State:
;   r4  = struct ts_sample_mt* (72-byte sample buffer)
;   r6  = Loop index / slot index
;   r7  = struct FBNativeWindow*
;   r8  = raw_y coordinate from tslib sample
;   r10 = raw_x coordinate from tslib sample
;   [sp, #0x40] = Native Window Width  = 1020
;   [sp, #0x3c] = Native Window Height = 240
; ==============================================================================

00227bcc <_ZN7greenui12winInputLoopEPv+0x5f8>:
  227bcc: e59f2128     ldr  r2, [pc, #0x128]        ; Load offset to greenui::_tp_xoffset
  227bd0: e59f3128     ldr  r3, [pc, #0x128]        ; Load offset to greenui::_tp_yoffset
  227bd4: e08f2002     add  r2, pc, r2              ; r2 = &_tp_xoffset
  227bd8: e08f3003     add  r3, pc, r3              ; r3 = &_tp_yoffset
  227bdc: e5922000     ldr  r2, [r2]                ; r2 = _tp_xoffset
  227be0: e5933000     ldr  r3, [r3]                ; r3 = _tp_yoffset
  227be4: e062a00a     rsb  r10, r2, r10            ; r10 = raw_x - _tp_xoffset
  227be8: e0638008     rsb  r8, r3, r8              ; r8  = raw_y - _tp_yoffset
  227bec: e35a0000     cmp  r10, #0                 ; Clamping x' < 0
  227bf0: b3a0a000     movlt r10, #0                ; if (x' < 0) x' = 0
  227bf4: e3580000     cmp  r8, #0                  ; Clamping y' < 0
  227bf8: b3a08000     movlt r8, #0                 ; if (y' < 0) y' = 0

; --- Rotation Mode Switch: _tp_direction ---
  227bfc: e59f2100     ldr  r2, [pc, #0x100]        ; Load offset to greenui::_tp_direction
  227c00: e08f2002     add  r2, pc, r2              ; r2 = &_tp_direction
  227c04: e5922000     ldr  r2, [r2]                ; r2 = _tp_direction
  227c08: e3520001     cmp  r2, #1                  ; Check if rotation == 1 (90 degrees)
  227c0c: 0a000004     beq  0x227c24                ; Branch to 90 deg rotation
  227c10: e3520003     cmp  r2, #3                  ; Check if rotation == 3 (270 degrees, S7 Pro Mode!)
  227c14: 0a00000c     beq  0x227c4c                ; Branch to 270 deg rotation
  227c18: e3520002     cmp  r2, #2                  ; Check if rotation == 2 (180 degrees)
  227c1c: 0a000014     beq  0x227c74                ; Branch to 180 deg rotation
  227c20: ea000020     b    0x227ca8                ; Default: 0 degrees (no rotation)

; --- 270 Degree Transformation (S7 Pro Standard) ---
00227c4c <_ZN7greenui12winInputLoopEPv+0x678>:
  227c4c: e59d2040     ldr  r2, [sp, #0x40]         ; r2 = Native Window Width = 1020
  227c50: e59d103c     ldr  r1, [sp, #0x3c]         ; r1 = Native Window Height = 240
  227c54: e2422001     sub  r2, r2, #1              ; r2 = 1020 - 1 = 1019
  227c58: e2411001     sub  r1, r1, #1              ; r1 = 240 - 1 = 239
  227c5c: e0688002     rsb  r8, r8, r2              ; r8 (log_x) = 1019 - y'
  227c60: e1580002     cmp  r8, r2                  ; Clamping log_x > 1019
  227c64: c1a08002     movgt r8, r2                 ; if (log_x > 1019) log_x = 1019
  227c68: e15a0001     cmp  r10, r1                 ; Clamping log_y > 239
  227c6c: c1a0a001     movgt r10, r1                ; if (log_y > 239) log_y = 239
  227c70: ea00000f     b    0x227cb4                ; Dispatch event with (log_x=r8, log_y=r10)

; --- Event Dispatch Call ---
00227cb4 <_ZN7greenui12winInputLoopEPv+0x6e0>:
  227cb4: e1a00007     mov  r0, r7                  ; r0 = FBNativeWindow*
  227cb8: e1a01006     mov  r1, r6                  ; r1 = slot / pointer index
  227cbc: e1a02008     mov  r2, r8                  ; r2 = logical_x
  227cc0: e1a0300a     mov  r3, r10                 ; r3 = logical_y
  227cc4: ebfcc71c     bl   0x15993c <_ZN7greenui14FBNativeWindow15inputTouchEventEiiii@plt>
```

### 3.2 Mathematical Formulation of Coordinate Transformations
Let raw coordinates reported by the touch digitizer be $(X_{\text{raw}}, Y_{\text{raw}})$, where:
$$0 \le X_{\text{raw}} \le 239, \quad 0 \le Y_{\text{raw}} \le 1019$$

Let calibration offsets be $\Delta X = \text{\_tp\_xoffset} = 0$, $\Delta Y = \text{\_tp\_yoffset} = 0$.
The pre-clamped coordinates $(x', y')$ are:
$$x' = \max(0, X_{\text{raw}} - \Delta X)$$
$$y' = \max(0, Y_{\text{raw}} - \Delta Y)$$

Given window canvas dimensions $W = 1020$ and $H = 240$:

#### Forward Transformation (Hardware Sensor $\to$ Logical Canvas):
$$\text{Logical } X = \text{clamp}(W - 1 - y', \, 0, \, W - 1) = \text{clamp}(1019 - y', \, 0, \, 1019)$$
$$\text{Logical } Y = \text{clamp}(x', \, 0, \, H - 1) = \text{clamp}(x', \, 0, \, 239)$$

#### Inverse Transformation (Logical Canvas $\to$ Raw Hardware Sensor):
To inject synthetic evdev events on `/dev/input/event3` that land on logical coordinate $(X_{\text{log}}, Y_{\text{log}})$:
$$X_{\text{raw}} = \text{clamp}(Y_{\text{log}}, \, 0, \, 239)$$
$$Y_{\text{raw}} = \text{clamp}(1019 - X_{\text{log}}, \, 0, \, 1019)$$

#### Canonical Coordinate Mapping Table:
| Screen Region | Logical Canvas $(X_{\text{log}}, Y_{\text{log}})$ | Raw Sensor $(X_{\text{raw}}, Y_{\text{raw}})$ | Physical Orientation |
| :--- | :--- | :--- | :--- |
| **Top-Left (Origin)** | $(0, 0)$ | $(0, 1019)$ | Near pen scanner tip, left edge |
| **Top-Right** | $(1019, 0)$ | $(0, 0)$ | Near pen tail/USB port, left edge |
| **Bottom-Left** | $(0, 239)$ | $(239, 1019)$ | Near pen scanner tip, right edge |
| **Bottom-Right** | $(1019, 239)$ | $(239, 0)$ | Near pen tail/USB port, right edge |
| **Screen Center** | $(510, 120)$ | $(120, 509)$ | Physical screen center |
| **Top Pull Panel Start** | $(510, 5)$ | $(5, 509)$ | Top edge center |
| **Left Swipe Back Start**| $(5, 120)$ | $(120, 1014)$ | Left edge center |

---

## 4. Touch Event State Machine & Dispatch Mechanics

### 4.1 Numerical Slop & Timing Thresholds
Through full binary disassembly of `greenui::View::onTouchEvent` (`0x448b88`), `greenui::ScrollView::onInterceptTouchEvent` (`0x43b444`), and `greenui::ScrollView::ScrollView` (`0x43a254`), the numerical thresholds are definitively verified:

```
+-----------------------------------+-----------------------------------+
| Parametric Threshold              | Exact Value (Binary Disassembly)  |
+-----------------------------------+-----------------------------------+
| Touch Slop Threshold (Click/Drag) | 8.0 Pixels                        |
| Disassembly Reference             | 0x448d30: vmov.f32 s2, #8.0f      |
| ScrollView Slop Storage           | 0x43a280: mov r2, #8; str [r4,#384]|
| Long-Press Duration Threshold     | 800 Milliseconds                  |
| Disassembly Reference             | 0x448d74: mov r2, #800            |
| Recommended Tap Pulse Duration    | 50 ms - 120 ms (Ideal: 80 ms)     |
| Double-Tap Detection Window       | 300 Milliseconds (in IME/Editor)  |
+-----------------------------------+-----------------------------------+
```

### 4.2 State Machine Disassembly: greenui::View::onTouchEvent
Located at `0x448b88` in `libfalcon.so`:

```arm
; ==============================================================================
; greenui::View::onTouchEvent(greenui::MotionEvent&)
; Addresses: 0x00448d28 - 0x00448da0
; ==============================================================================
00448d28: e1a00004     mov   r0, r4                 ; r0 = View* this
00448d2c: e1a01007     mov   r1, r7                 ; r1 = cur_x
00448d30: ed9f1a26     vldr  s2, [pc, #152]         ; s2 = 8.000000e+00f (TOUCH SLOP!)
00448d34: ebf6944e     bl    0x1ee474 <_ZN7greenui4View11pointInViewEfff@plt>
00448d38: e3500000     cmp   r0, #0                 ; Has touch moved outside bounds + 8px?
00448d3c: 0a000010     beq   0x448d84               ; If out of bounds: cancel click & longpress!

; --- Long-Press Timer Registration (ACTION_DOWN) ---
00448d70: e59400e4     ldr   r0, [r4, #0xe4]        ; r0 = mHandler (JQuick::Handler*)
00448d74: e3a02f32     mov   r2, #800               ; r2 = 800 ms (LONG PRESS THRESHOLD!)
00448d78: e3a01001     mov   r1, #1                 ; Message ID = 1 (MSG_LONG_CLICK)
00448d7c: ebf67446     bl    0x1e5e9c <_ZN6JQuick7Handler18sendMessageDelayedEij@plt>
```

### 4.3 Click vs Drag/Fling Decision Tree
```
                         [Touch Down (ACTION_DOWN)]
                                     │
                     ┌───────────────┴───────────────┐
                     ▼                               ▼
       [Record (mDownX, mDownY)]     [Start Long-Press Timer (800ms)]
                     │                               │
                     ├───────────────────────────────┤
                     ▼                               ▼
          [Touch Move (ACTION_MOVE)]                 │
                     │                               │
       ┌─────────────┴─────────────┐                 │
       ▼                           ▼                 │
[ΔX, ΔY ≤ 8.0px]           [ΔX or ΔY > 8.0px]       │
       │                           │                 │
(Remain in Tap State)       (Exceeds Touch Slop)     │
       │                           │                 │
       │            ┌──────────────┴──────────────┐  │
       │            ▼                             ▼  │
       │    [Child View: Cancel]        [ScrollView Intercepts]
       │    - Cancel 800ms timer        - Set mIsBeingDragged=true
       │    - Set mTouchCancelled=true  - Disallow child touch
       │            │                   - Enter Scroll/Fling Mode
       │            │                             │
       ▼            ▼                             ▼
[Touch Up (ACTION_UP)]                  [Touch Up (ACTION_UP)]
       │                                          │
 ┌─────┴───────────────────┐                      ▼
 ▼                         ▼               [Scroller::fling()]
[Within 800ms & ≤ 8.0px]  [Held > 800ms]   Compute inertia velocity
       │                         │         Scroll cards horizontally
       ▼                         ▼
[performClick()]          [performLongClick()]
 - OnClickListener::onClick - OnLongClickListener
 - Component::fireEvent     - Card Drag/Edit Mode
   ("click") to VDOM          in Launcher
```

### 4.4 VDOM Event Bridging: JQuick::Component & JQuick::WXGesture
When a Vue template contains `@click`, `@touchstart`, or `@touchmove`, the compiler emits event registrations processed by `JQuick::Component::onAddEvent` (`0x37d628`):

1. **`click` Registration**:
   `Component::onAddEvent` checks `compare("click") == 0`. It instantiates a `greenui::OnClickListener` wrapper and binds it to the host view via `greenui::View::setOnClickListener` (`0x446b44`). When `View::performClick` triggers, it forwards to `Component::fireEvent("click", JQuick::Json())`.
2. **`longpress` Registration**:
   `Component::onAddEvent` checks `compare("longpress") == 0`. It instantiates an `OnLongClickListener` and calls `greenui::View::setOnLongClickListener`.
3. **`touchstart` / `touchmove` / `touchend` / `touchcancel` Registration**:
   `Component::onAddEvent` calls `JQuick::Component::getOrCreateGesture()` (`0x1d332c`), creating a `JQuick::WXGesture` instance (`0x3bafd4`). `WXGesture::onTouch` intercepts raw `greenui::MotionEvent` instances via `View::dispatchTouchEvent` (`[this, #0xdc] = mOnTouchListener`), parses pointer coordinates, and invokes `handleMotionEvent("touchstart" / "touchmove" / "touchend")`.

---

## 5. System Gesture Recognizers & Window Interceptions

### 5.1 TopSwipeGesture Disassembly & Suppression
Located at `0x588930` in `libfalcon.so`, `greenui::TopSwipeGesture` recognizes downward swipe gestures originating from the top edge to pull down the System Control & Status Panel.

```arm
; ==============================================================================
; greenui::TopSwipeGesture::onTouchEvent(greenui::MotionEvent&)
; Address: 0x00588964 - 0x005889e4
; ==============================================================================
00588964: e1a00006     mov   r0, r6                 ; r0 = MotionEvent&
00588968: ebf1480c     bl    0x1da9a0 <getX>        ; s17 = touch X
00588974: ebf167b0     bl    0x1e283c <getY>        ; s16 = touch Y
0058897c: ed949a09     vldr  s18, [r4, #36]         ; s18 = topMargin default (5.0f)
00588980: ebf1724c     bl    0x1e52b8 <WindowManager::instance>
00588984: ebf1573e     bl    0x1de684 <WindowManager::getDeviceHeight> ; r0 = 240
0058898c: eddf0ab3     vldr  s1, [pc, #716]         ; s1 = 100.0f (literal 0x42c80000)
00588998: eec70aa0     vdiv.f32 s1, s15, s1         ; s1 = 240 / 100.0 = 2.4f
0058899c: ebf14b11     bl    0x1db5e8 <fmaxf>       ; s0 = fmaxf(5.0f, 2.4f) = 5.0f
005889b0: eeb48ac9     vcmpe.f32 s16, s18           ; Compare touch Y with 5.0f
005889b4: eef1fa10     vmrs  APSR_nzcv, fpscr
005889b8: 8a00000a     bhi   0x5889e8               ; If Y > 5.0px, NOT a top edge swipe!
```

#### Window Flag 4 (`FLAG_NO_TOP_PANEL`) Suppression:
When an app or fullscreen activity calls `setSupportTopPanel(false)`:
- `falcon::FalconAppExtend::setSupportTopPanel(false)` (`0x24c414`) invokes `greenui::Window::setFlag(4)`.
- The gesture execution callback `falcon::TopSettingPanelGesture::onHandle` (`0x2ae45c`) inspects the active window flags:

```arm
; ==============================================================================
; falcon::TopSettingPanelGesture::onHandle(float)
; Address: 0x002ae560 - 0x002ae56c
; ==============================================================================
002ae560: e1a00006     mov   r0, r6                 ; r0 = active Window*
002ae564: ebfcbcce     bl    0x1dd8a4 <greenui::Window::getFlags() const>
002ae568: e3100004     tst   r0, #4                 ; Test Bit 2 (0x04: FLAG_NO_TOP_PANEL)
002ae56c: 1a00003b     bne   0x2ae660               ; Branch to early return (SUPPRESSED!)
```

### 5.2 LeftSwipeBackGesture & mDisableLeftSwipeBack
Located at `0x588308` in `libfalcon.so`, `greenui::LeftSwipeBackGesture` manages edge swipe navigation to return to the previous page or app.

#### Binary Parameters:
1. **Activation Zone**: Left edge touch: $X_{\text{touch}} \le \max(5.0\text{px}, \frac{\text{Width}}{100.0}) = \max(5.0, 10.2) = \mathbf{10.2\text{ px}}$.
2. **Angle Invariant**:
   At `0x58857c`:
   $$\Delta X > |\Delta Y| \iff (X_{\text{cur}} - X_{\text{start}}) > |Y_{\text{cur}} - Y_{\text{start}}|$$
   If vertical movement equals or exceeds horizontal movement ($\theta \ge 45^\circ$), the gesture aborts.
3. **Trigger Distance**: $X_{\text{cur}} \ge X_{\text{start}} + 40.0\text{ px}$.

#### Suppression Mechanism (`mDisableLeftSwipeBack`):
When a page sets `disableLeftSwipeBack: true` in its configuration:
- `falcon::FalconApp::setDisableLeftSwipeBack(bool)` (`0x2f3568`) sets byte `[this, #0x168]`.
- In `LeftSwipeBackGesture::onTouchEvent` (`0x588344`):
  ```arm
  00588340: bl WindowManager::instance()
  00588344: bl WindowManager::disableLeftSwipeBack()
  00588348: subs r5, r0, #0
  0058834c: beq  0x588398 ; If disabled != 0: logs "LeftSwipeBackGesture is disabled" and exits!
  ```

---

## 6. System Launcher Reverse Engineering & App Launch Sequence

### 6.1 Package Analysis: `8080222437664451`
The System Launcher resides at `/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/`.
- `indexPage-085a554f.js.bin`: Launcher orchestrator and app launch dispatcher.
- `MovingStatusCardsList.js.bin`: Card scroll container and drag-to-reorder manager.
- `Card-66980c69.js.bin`: Visual representation of an application icon/card.

### 6.2 App Click Detection Mechanism
In `Card.vue` and `MovingStatusCardsList.vue`:
```html
<template>
  <div class="card-item" @click="onClickItem(item)" @longpress="draggerLongPressed(item)">
    <image :src="item.icon" class="app-icon" />
    <text class="app-title">{{ item.name }}</text>
  </div>
</template>
```

When an icon is tapped:
1. **Evdev Level**: Touch down and up events occur within 8.0 px of each other, duration between 50 ms and 300 ms.
2. **GreenUI Level**: `greenui::View::onTouchEvent` executes `performClick()`, calling the C++ `OnClickListener`.
3. **JQuick/VDOM Level**: `Component::fireEvent("click", ...)` fires into the QuickJS runtime.
4. **MiniApp Level**: `indexPage` invokes `getEntrancePmModule().startApp(item.appid)`.

---

## 7. Complete Working Python Evdev Injection Tool (`s7pro_touch.py`)

This standalone Python script provides complete coordinate conversion, protocol packing, and event injection for automated testing on the Youdao S7 Pro.

```python
#!/usr/bin/env python3
"""
NetEase Youdao Dictionary Pen S7 Pro - Native Evdev Injection Tool
Platform: Sophgo CV1813H ARM Cortex-A7 (Linux 4.9 / 5.10)
Device Input Node: /dev/input/event3 (axs_ts touchscreen)

Usage:
  Directly on device:
    python3 s7pro_touch.py tap <log_x> <log_y> [duration_ms]
    python3 s7pro_touch.py swipe <start_x> <start_y> <end_x> <end_y> [duration_ms] [steps]
    python3 s7pro_touch.py top_pull [duration_ms]
    python3 s7pro_touch.py swipe_back [duration_ms]

  Over SSH from host:
    python3 s7pro_touch.py --ssh 192.168.2.2 tap 510 120
"""

import sys
import time
import struct
import os
import argparse
import subprocess

# Linux Evdev Constants
EV_SYN = 0x0000
EV_KEY = 0x0001
EV_ABS = 0x0003

SYN_REPORT = 0x0000
BTN_TOUCH = 0x014a        # 330
BTN_TOOL_FINGER = 0x0145  # 325

ABS_X = 0x0000
ABS_Y = 0x0001
ABS_MT_SLOT = 0x002f        # 47
ABS_MT_TOUCH_MAJOR = 0x0030 # 48
ABS_MT_POSITION_X = 0x0035  # 53
ABS_MT_POSITION_Y = 0x0036  # 54
ABS_MT_TRACKING_ID = 0x0039 # 57
ABS_MT_PRESSURE = 0x003a    # 58

# Canvas Dimensions
CANVAS_WIDTH = 1020
CANVAS_HEIGHT = 240
RAW_MAX_X = 239
RAW_MAX_Y = 1019

def pack_event(ev_type: int, ev_code: int, ev_value: int) -> bytes:
    """Pack Linux input_event (strictly 16 bytes on 32-bit ARM Linux)."""
    now = time.time()
    tv_sec = int(now)
    tv_usec = int((now - tv_sec) * 1_000_000)
    return struct.pack("IIHHi", tv_sec, tv_usec, ev_type, ev_code, ev_value)

def logical_to_raw(log_x: int, log_y: int) -> tuple:
    """
    Apply inverse 270-degree rotation matching greenui::winInputLoop (0x227bcc):
      log_x = clamp(1019 - raw_y, 0, 1019)  ==> raw_y = 1019 - log_x
      log_y = clamp(raw_x, 0, 239)          ==> raw_x = log_y
    """
    raw_x = max(0, min(RAW_MAX_X, int(log_y)))
    raw_y = max(0, min(RAW_MAX_Y, int(1019 - log_x)))
    return raw_x, raw_y

class EvdevInjector:
    def __init__(self, dev_path="/dev/input/event3", ssh_host=None):
        self.dev_path = dev_path
        self.ssh_host = ssh_host
        self.proc = None
        self.fd = None

    def open(self):
        if self.ssh_host:
            cmd = ["ssh", "-o", "StrictHostKeyChecking=no", f"root@{self.ssh_host}", f"cat > {self.dev_path}"]
            self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        else:
            self.fd = os.open(self.dev_path, os.O_WRONLY)

    def write_events(self, packet_list):
        for packet, delay_sec in packet_list:
            if self.ssh_host:
                self.proc.stdin.write(packet)
                self.proc.stdin.flush()
            else:
                os.write(self.fd, packet)
            if delay_sec > 0:
                time.sleep(delay_sec)

    def close(self):
        if self.ssh_host and self.proc:
            self.proc.stdin.close()
            self.proc.wait()
        elif self.fd is not None:
            os.close(self.fd)

    def send_tap(self, log_x: int, log_y: int, duration_ms: int = 80):
        raw_x, raw_y = logical_to_raw(log_x, log_y)
        print(f"[*] Dispatching Tap: Logical({log_x}, {log_y}) -> Raw({raw_x}, {raw_y}), Hold={duration_ms}ms")

        # Down Sequence
        events_down = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, 100), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, raw_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, raw_y), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 100), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 12), 0),
            (pack_event(EV_ABS, ABS_X, raw_x), 0),
            (pack_event(EV_ABS, ABS_Y, raw_y), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 1), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), duration_ms / 1000.0)
        ]
        self.write_events(events_down)

        # Up Sequence
        events_up = [
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 0), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), 0.02)
        ]
        self.write_events(events_up)

    def send_swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 250, steps: int = 20):
        s_raw_x, s_raw_y = logical_to_raw(sx, sy)
        e_raw_x, e_raw_y = logical_to_raw(ex, ey)
        step_delay = (duration_ms / 1000.0) / steps
        print(f"[*] Dispatching Swipe: Logical({sx},{sy})->({ex},{ey}) | Raw({s_raw_x},{s_raw_y})->({e_raw_x},{e_raw_y})")

        # Down
        events_down = [
            (pack_event(EV_ABS, ABS_MT_SLOT, 0), 0),
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, 101), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_X, s_raw_x), 0),
            (pack_event(EV_ABS, ABS_MT_POSITION_Y, s_raw_y), 0),
            (pack_event(EV_ABS, ABS_MT_PRESSURE, 120), 0),
            (pack_event(EV_ABS, ABS_MT_TOUCH_MAJOR, 14), 0),
            (pack_event(EV_ABS, ABS_X, s_raw_x), 0),
            (pack_event(EV_ABS, ABS_Y, s_raw_y), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 1), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 1), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), step_delay)
        ]
        self.write_events(events_down)

        # Interpolated Steps
        for i in range(1, steps + 1):
            ratio = float(i) / steps
            cur_raw_x = int(s_raw_x + (e_raw_x - s_raw_x) * ratio)
            cur_raw_y = int(s_raw_y + (e_raw_y - s_raw_y) * ratio)
            step_events = [
                (pack_event(EV_ABS, ABS_MT_POSITION_X, cur_raw_x), 0),
                (pack_event(EV_ABS, ABS_MT_POSITION_Y, cur_raw_y), 0),
                (pack_event(EV_ABS, ABS_X, cur_raw_x), 0),
                (pack_event(EV_ABS, ABS_Y, cur_raw_y), 0),
                (pack_event(EV_SYN, SYN_REPORT, 0), step_delay)
            ]
            self.write_events(step_events)

        # Up
        events_up = [
            (pack_event(EV_ABS, ABS_MT_TRACKING_ID, -1), 0),
            (pack_event(EV_KEY, BTN_TOUCH, 0), 0),
            (pack_event(EV_KEY, BTN_TOOL_FINGER, 0), 0),
            (pack_event(EV_SYN, SYN_REPORT, 0), 0.02)
        ]
        self.write_events(events_up)

def main():
    parser = argparse.ArgumentParser(description="NetEase Youdao S7 Pro Evdev Injector")
    parser.add_argument("--ssh", help="SSH host IP (e.g. 192.168.2.2)")
    parser.add_argument("--dev", default="/dev/input/event3", help="Input device path")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # Tap command
    tap_p = subparsers.add_parser("tap")
    tap_p.add_argument("x", type=int, help="Logical X (0..1019)")
    tap_p.add_argument("y", type=int, help="Logical Y (0..239)")
    tap_p.add_argument("--duration", type=int, default=80, help="Press duration in ms")

    # Swipe command
    sw_p = subparsers.add_parser("swipe")
    sw_p.add_argument("sx", type=int)
    sw_p.add_argument("sy", type=int)
    sw_p.add_argument("ex", type=int)
    sw_p.add_argument("ey", type=int)
    sw_p.add_argument("--duration", type=int, default=250)
    sw_p.add_argument("--steps", type=int, default=20)

    # Top pull panel command
    subparsers.add_parser("top_pull")

    # Left swipe back command
    subparsers.add_parser("swipe_back")

    args = parser.parse_args()
    injector = EvdevInjector(dev_path=args.dev, ssh_host=args.ssh)
    injector.open()

    try:
        if args.cmd == "tap":
            injector.send_tap(args.x, args.y, args.duration)
        elif args.cmd == "swipe":
            injector.send_swipe(args.sx, args.sy, args.ex, args.ey, args.duration, args.steps)
        elif args.cmd == "top_pull":
            # Pull from Top Edge (Y=2) to Mid Screen (Y=180)
            injector.send_swipe(510, 2, 510, 180, duration_ms=280, steps=25)
        elif args.cmd == "swipe_back":
            # Swipe from Left Edge (X=4) to Right (X=250)
            injector.send_swipe(4, 120, 250, 120, duration_ms=250, steps=25)
    finally:
        injector.close()
    print("[+] Done!")

if __name__ == "__main__":
    main()
```

---

## 8. Complete Working Native C Injection Utility (`s7pro_touch.c`)

This C source code can be compiled directly on the pen (`gcc -O2 s7pro_touch.c -o s7pro_touch`) or cross-compiled with `arm-linux-gnueabihf-gcc`.

```c
/**
 * NetEase Youdao Dictionary Pen S7 Pro - Native C Touch Injector
 * Architecture: ARMv7-A (32-bit Little-Endian)
 * Device Node: /dev/input/event3
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <linux/input.h>

#define DEV_PATH "/dev/input/event3"

#define CANVAS_WIDTH  1020
#define CANVAS_HEIGHT 240
#define RAW_MAX_X     239
#define RAW_MAX_Y     1019

/* Coordinate mapping matching greenui::winInputLoop (0x227bcc) */
static void logical_to_raw(int log_x, int log_y, int *raw_x, int *raw_y) {
    if (log_x < 0) log_x = 0;
    if (log_x > 1019) log_x = 1019;
    if (log_y < 0) log_y = 0;
    if (log_y > 239) log_y = 239;

    *raw_x = log_y;
    *raw_y = 1019 - log_x;
}

static void emit_event(int fd, uint16_t type, uint16_t code, int32_t value) {
    struct input_event ev;
    memset(&ev, 0, sizeof(ev));

    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    ev.time.tv_sec = ts.tv_sec;
    ev.time.tv_usec = ts.tv_nsec / 1000;
    ev.type = type;
    ev.code = code;
    ev.value = value;

    if (write(fd, &ev, sizeof(ev)) < (ssize_t)sizeof(ev)) {
        perror("write input_event error");
    }
}

static void send_tap(int fd, int log_x, int log_y, int duration_ms) {
    int raw_x, raw_y;
    logical_to_raw(log_x, log_y, &raw_x, &raw_y);
    printf("[s7pro_touch] TAP at logical (%d, %d) -> raw (%d, %d), hold %d ms\n",
           log_x, log_y, raw_x, raw_y, duration_ms);

    // ACTION_DOWN
    emit_event(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, 1001);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_X, raw_x);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, raw_y);
    emit_event(fd, EV_ABS, ABS_MT_PRESSURE, 100);
    emit_event(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 12);
    emit_event(fd, EV_ABS, ABS_X, raw_x);
    emit_event(fd, EV_ABS, ABS_Y, raw_y);
    emit_event(fd, EV_KEY, BTN_TOUCH, 1);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 1);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);

    usleep(duration_ms * 1000);

    // ACTION_UP
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit_event(fd, EV_KEY, BTN_TOUCH, 0);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 0);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

static void send_swipe(int fd, int sx, int sy, int ex, int ey, int duration_ms, int steps) {
    int s_raw_x, s_raw_y, e_raw_x, e_raw_y;
    logical_to_raw(sx, sy, &s_raw_x, &s_raw_y);
    logical_to_raw(ex, ey, &e_raw_x, &e_raw_y);

    int step_delay_us = (duration_ms * 1000) / steps;
    printf("[s7pro_touch] SWIPE logical (%d,%d)->(%d,%d) | raw (%d,%d)->(%d,%d), steps=%d\n",
           sx, sy, ex, ey, s_raw_x, s_raw_y, e_raw_x, e_raw_y, steps);

    // Down
    emit_event(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, 1002);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_X, s_raw_x);
    emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, s_raw_y);
    emit_event(fd, EV_ABS, ABS_MT_PRESSURE, 120);
    emit_event(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 15);
    emit_event(fd, EV_ABS, ABS_X, s_raw_x);
    emit_event(fd, EV_ABS, ABS_Y, s_raw_y);
    emit_event(fd, EV_KEY, BTN_TOUCH, 1);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 1);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
    usleep(step_delay_us);

    // Steps
    for (int i = 1; i <= steps; i++) {
        float r = (float)i / (float)steps;
        int cur_x = s_raw_x + (int)((e_raw_x - s_raw_x) * r);
        int cur_y = s_raw_y + (int)((e_raw_y - s_raw_y) * r);

        emit_event(fd, EV_ABS, ABS_MT_POSITION_X, cur_x);
        emit_event(fd, EV_ABS, ABS_MT_POSITION_Y, cur_y);
        emit_event(fd, EV_ABS, ABS_X, cur_x);
        emit_event(fd, EV_ABS, ABS_Y, cur_y);
        emit_event(fd, EV_SYN, SYN_REPORT, 0);
        usleep(step_delay_us);
    }

    // Up
    emit_event(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit_event(fd, EV_KEY, BTN_TOUCH, 0);
    emit_event(fd, EV_KEY, BTN_TOOL_FINGER, 0);
    emit_event(fd, EV_SYN, SYN_REPORT, 0);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage:\n");
        fprintf(stderr, "  %s tap <log_x> <log_y> [duration_ms]\n", argv[0]);
        fprintf(stderr, "  %s swipe <sx> <sy> <ex> <ey> [duration_ms] [steps]\n", argv[0]);
        return 1;
    }

    int fd = open(DEV_PATH, O_WRONLY);
    if (fd < 0) {
        perror("Failed to open " DEV_PATH);
        return 1;
    }

    if (strcmp(argv[1], "tap") == 0 && argc >= 4) {
        int x = atoi(argv[2]);
        int y = atoi(argv[3]);
        int dur = (argc > 4) ? atoi(argv[4]) : 80;
        send_tap(fd, x, y, dur);
    } else if (strcmp(argv[1], "swipe") == 0 && argc >= 6) {
        int sx = atoi(argv[2]);
        int sy = atoi(argv[3]);
        int ex = atoi(argv[4]);
        int ey = atoi(argv[5]);
        int dur = (argc > 6) ? atoi(argv[6]) : 250;
        int steps = (argc > 7) ? atoi(argv[7]) : 20;
        send_swipe(fd, sx, sy, ex, ey, dur, steps);
    } else {
        fprintf(stderr, "Unknown or invalid command arguments.\n");
        close(fd);
        return 1;
    }

    close(fd);
    printf("[+] Event injected successfully.\n");
    return 0;
}
```

---

## 9. Hardware & Subsystem Diagnostic Verification Reference

### 9.1 Evdev Verification via ADB / SSH Shell
```bash
# Verify the touchscreen device node
getevent -p
# /dev/input/event3: axs_ts
#   events:
#     SYN (0000): 0000
#     KEY (0001): 0145  014a
#     ABS (0003): 0000  0001  002f  0030  0035  0036  0039  003a

# Monitor raw evdev packet stream during physical touch
hexdump -e '16/1 "%02x " "\n"' /dev/input/event3

# Inject a synthetic center screen tap (Logical 510, 120 -> Raw 120, 509)
python3 s7pro_touch.py tap 510 120 --duration 80
```

### 9.2 Subsystem Memory Offsets & Struct Summary Table
| Subsystem / Class | Field / Method | Offset / Address | Binary Function / Semantics |
| :--- | :--- | :--- | :--- |
| `greenui::winInputLoop` | Coordinate transform | `0x00227bcc` | Performs 270° rotation and clamping |
| `greenui::_tp_direction` | Screen orientation | GOT Variable | Set to `3` for 270° counter-clockwise rotation |
| `greenui::View` | `pointInView(x,y,slop)` | `0x00448d30` | Touch slop = **8.0f** pixels |
| `greenui::View` | `mHandler->sendMessageDelayed` | `0x00448d74` | Long-press timer = **800** ms |
| `greenui::ScrollView` | `mTouchSlop` | `[this, #0x180]` | Initialized to **8** px in constructor (`0x43a280`) |
| `greenui::ScrollView` | `onInterceptTouchEvent`| `0x0043b444` | Compares $\Delta X$ / $\Delta Y > \text{mTouchSlop}$ |
| `greenui::Window` | `mFlags` | `[this, #0x2c]` | Flag 4 = `FLAG_NO_TOP_PANEL` |
| `TopSettingPanelGesture`| Flag check | `0x002ae568` | `tst r0, #4` suppresses top pull panel |
| `falcon::FalconApp` | `mDisableLeftSwipeBack` | `[this, #0x168]` | Suppresses edge swipe back navigation |
| `LeftSwipeBackGesture` | `onTouchEvent` | `0x00588308` | Left edge trigger ($X \le 10.2\text{px}$), $\Delta X > \|\Delta Y\|$ |
| `JQuick::Component` | `onAddEvent` | `0x0037d628` | Bridges `click` $\to$ `OnClickListener`, gestures $\to$ `WXGesture` |
| `JQuick::WXGesture` | `onTouch` | `0x003bafd4` | Bridges `MotionEvent` $\to$ `touchstart/move/end` |

---

## 10. 生产实操：复杂图文场景下的多模触控消解状态机 (Multi-Gesture Disambiguation Engine)

在长篇漫画与高密度图文查看器等复杂交互应用中，前端视口通常需要同时支持三种高度冲突的手势：
1. **轻点返回**：单击视口中任意非按钮区域返回上级画卷；
2. **双击放大/复原**：以触控点为中心在 1.0× 与 2.0×（或 3.0×）之间平滑缩放，并支持双击复原；
3. **左边缘向右侧滑**：从屏幕左侧边缘快速向右滑动，逐级返回上一层级。

### 10.1 冲突根因与硬件物理限制
- **触点离散性与生理微抖动**：嵌入式电容屏在手指快速连击时，第二次点击的实际坐标常偏离第一次 30px~80px。若容差阈值设置过小，双击会被误判为两次独立的单击；若过大，则会影响拖拽判定。
- **单核 CPU 调度抖动**：在单核 Cortex-A7 @ 1.0 GHz 高负载下，若双击判定窗口小于 350ms，系统轻微的 GC 停顿便会导致双击第二击超出判定时限，从而引发灾难性的“误触单击并意外退出”。

### 10.2 三阶消解状态机确定性架构

```
   [touchstart (pageX, pageY)]
                │
                ├─────────────────────────────────────────┐
                ▼ (pageX <= 108px)                        ▼ (pageX > 108px)
     [标记 edgeSwipeActive = true]                [普通拖拽 / 点击状态初始化]
                │                                         │
    [touchend (Δx >= 36px & Δx > 1.2*Δy)]         [touchend (位移 <= 24px & 耗时 <= 500ms)]
                │                                         │
                ▼                                         ▼
   [立即拦截消费: 层级式返回上一页]           [判定是否存在活跃 singleTapTimer?]
                                                          │
                                         ┌────────────────┴────────────────┐
                                         ▼ YES (且距离 <= 95px)             ▼ NO
                           [清除 singleTapTimer 并消费事件]      [启动 480ms 延时计时器]
                                         │                                 │
                                         ▼                                 ▼ (480ms 超时未收到第2击)
                           [执行双击 2.0x 放大 / 1.0x 复原]        [执行单击返回逻辑]
```

### 10.3 生产级消解实现规范代码
```javascript
// 1. 双击与单击消解
handleSingleTouchEnd(e) {
  if (this.consumeNextTouchEnd) {
    this.consumeNextTouchEnd = false;
    this.isDragging = false;
    return;
  }
  const touch = e.changedTouches[0];
  const now = Date.now();
  const overallDx = touch.pageX - this.touchStartX;
  const overallDy = touch.pageY - this.touchStartY;
  const pressDuration = now - this.touchStartTime;

  // A. 左边缘侧滑返回最高优先级拦截 (放大状态 108px, 常规状态 160px)
  const maxEdgeX = this.zoomScale > 1.05 ? 108 : 160;
  if (this.touchStartX <= maxEdgeX && overallDx >= 36 && overallDx > Math.abs(overallDy) * 1.2) {
    this.clearSingleTapTimer();
    this.backToWaterfall();
    return;
  }

  // B. 480ms 延时定时器消解单击与双击
  if (this.totalDragDistance <= 24 && pressDuration <= 500) {
    this.clearSingleTapTimer();
    this.pendingTapX = touch.pageX;
    this.pendingTapY = touch.pageY;
    this.singleTapTimer = setTimeout(() => {
      this.singleTapTimer = null;
      // 超时无第二次点击，确认触发单击返回
      this.backToWaterfall();
    }, 480);
    return;
  }

  // C. 放大拖拽平移边界钳位 (严格贴合边界，杜绝越界穿透翻页)
  this.clampPanOffsets();
}
```
