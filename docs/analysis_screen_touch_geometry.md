# 有道词典笔 S7 Pro 屏幕物理几何与触控渲染全链路深度逆向报告

---

## 一、 系统架构与四层空间映射模型

有道词典笔 S7 Pro 物理屏幕采用了一块 **240 × 1020** 像素的超长条形竖屏面板，但在终端交互形态中，用户横向握持词典笔，上层业务（MiniApp / Vue）运行在 **1020 × 240** 的逻辑横屏空间。

系统跨越硬件、Linux 内核、Falcon C++ GUI 引擎以及 QuickJS/Vue 应用层，构建了完整的正向渲染旋转与逆向触控变换闭环：

```
+-----------------------------------------------------------------------------------+
| 1. Vue 应用层 (MiniApp Layer)                                                      |
|    - 逻辑横向视口: 1020 × 240                                                     |
|    - Facebook Yoga Flexbox 布局 (直接使用 width: 1020px, height: 240px)            |
|    - 触控事件对象: e.touches[0].pageX ∈ [0, 1020), pageY ∈ [0, 240)               |
+-----------------------------------------^-----------------------------------------+
                                          | (JQuick::WXGesture 派发)
+-----------------------------------------v-----------------------------------------+
| 2. Falcon C++ 引擎层 (libfalcon.so / greenui)                                      |
|    - 根窗口创建 (NativeWindow::create): 识别 direction=270, 尺寸翻转为 1020×240     |
|    - 离屏主画布: SkBitmap (1020 × 240, 32bpp ARGB8888)                            |
|    - 脏矩形旋转 Blit (greenui::rotate_fb):                                         |
|        调用 ARM NEON SIMD 汇编 yd_l_rotate90_S32 (CCW 90° / CW 270°)              |
|    - 触控逆变换 (winInputLoop):                                                   |
|        X_log = clamp(1019 - Y_raw, 0, 1019)                                      |
|        Y_log = X_raw                                                              |
+-----------------------------------------^-----------------------------------------+
                                          | (tslib / ioctl FBIOPAN_DISPLAY)
+-----------------------------------------v-----------------------------------------+
| 3. Linux 内核驱动层 (Linux Kernel & Drivers)                                      |
|    - 帧缓冲 /dev/fb0: 物理 240×1020, 虚拟 240×2040 (双缓冲 Double Buffering)       |
|    - 触控驱动 axs_ts.ko (/dev/input/event3): I2C AXS15205 直报物理坐标 (240×1020)   |
+-----------------------------------------------------------------------------------+
| 4. 物理硬件层 (Physical Hardware)                                                  |
|    - 物理面板: 240 列 × 1020 行 (竖屏硬件发光矩阵)                                  |
|    - 电容触控传感器: 240 × 1020 物理电极阵列                                       |
+-----------------------------------------------------------------------------------+
```

---

## 二、 核心攻关问题逐一深度解答

### 1. `/etc/miniapp/resources/cfg.json` 与根窗口几何初始化

#### 配置文件关键参数
`/etc/miniapp/resources/cfg.json` 中的显示与输入配置如下：
```json
{
    "screen": {
        "width": 240,
        "height": 1020,
        "xoffset": 0,
        "yoffset": 0,
        "dbuffer": true,
        "direction": 270,
        "tp_direction": 270,
        "tp_xoffset": 0,
        "tp_yoffset": 0,
        "fps_max": 60
    },
    "device": {
        "fb": "/dev/fb0",
        "tp": "/dev/input/by-path/platform-4010000.i2c-event",
        "mouse": "/dev/input/mouse0"
    }
}
```

#### 汇编反编译证据 (`libfalcon.so`)
在 Falcon 启动时，由 `greenui::NativeWindow::create(void*)`（地址 `0x00225950`）解析配置。在 `0x0022648c` 处：
```arm
0x0022648c: ldr  r3, [sp, #0xb8]   ; 取出 direction 参数指针
0x00226490: movw r2, #0x10e       ; 0x10e = 270 (度)
0x00226498: ldr  r3, [r3]         ; 加载 direction 值
0x0022649c: cmp  r3, r2           ; 比较 direction 是否等于 270
0x002264a0: cmpne r3, #0x5a       ; 若不等于 270，再比较是否等于 90 (0x5a)
0x002264ac: bne  #0x226648        ; 若非 90/270，跳转到不交换分支

; === 当 direction 为 270 或 90 时的尺寸交换分支 ===
0x002264b0: mov  r0, #0xb0        ; sizeof(FBNativeWindow)
0x002264c0: bl   operator new
0x002264c4: ldr  r3, [sp, #0xa8]   ; r3 = cfg.width (240)
0x002264cc: ldr  r2, [sp, #0xac]   ; r2 = cfg.height (1020)
0x002264d0: mov  r4, r0
; 调用构造函数: FBNativeWindow::FBNativeWindow(title, width=r2, height=r3)
0x002264d4: bl   greenui::FBNativeWindow::FBNativeWindow(char const*, int, int)
```

**影响分析**：
- 只要 `screen.direction` 为 270（或 90），底层引擎在分配 `FBNativeWindow`、`NativeWindow`、`WRoot` 及 `RootView` 时，便将物理高（1020）赋给逻辑宽，将物理宽（240）赋给逻辑高。
- 最终根窗口属性确定为：`mWidth = 1020`，`mHeight = 240`。
- 上层所有的视图度量、脏矩形、CSS 排版以及离屏画布全以 1020×240 为基础尺寸展开。

---

### 2. 原生组件布局坐标系与 `<scroller>` 滑动方向

#### Flexbox 样式与坐标系
- **1:1 绝对映射**：Falcon 集成了 Facebook Yoga 排版引擎。根节点固定设置为 `width: 1020px; height: 240px`。
- 开发者编写 `<div style="width: 1020px; height: 240px">`，其 `left`, `top`, `width`, `height`, `margin`, `padding` 均 100% 对应 **1020×240 的横向逻辑视口**。
- 逻辑原点 $(0, 0)$ 位于横向握持状态下的屏幕**左上角**。

#### 原生 `<scroller>` 的 `scroll-direction="vertical"` 滑动方向
在 `greenui::ScrollView::onTouchEvent`（地址 `0x0043b7e8`）中：
- `scroll-direction="horizontal"`：响应逻辑 $X$ 轴手势（$\Delta X_{log}$），在 1020px 维度上左右滑动翻页；
- `scroll-direction="vertical"`：响应逻辑 $Y$ 轴手势（$\Delta Y_{log}$），在 240px 维度上滑动。

**物理手势映射**：
- 逻辑横屏下的“垂直滚动”，在握持词典笔的物理形态上对应的是**沿笔身短边（窄边宽度，跨度 240px）上下滑动**。
- 由于短边物理行程极短（仅 240px，正常仅容纳 4~5 行文字），上下滑动手势行程短、阻尼感强。
- **最佳实践**：词典笔横向排版的大多数列表（词条列表、横屏卡片、瀑布流）建议采用 `scroll-direction="horizontal"` 以充分利用 1020px 的长轴滑动行程。

---

### 3. 触控事件派发流水线与坐标转换

#### 物理驱动与 Evdev 节点 (`axs_ts.ko` & `/dev/input/event3`)
- 触控 IC 为 AXS15205，驱动通过 I2C 读取 12 位原始坐标：
  `raw_x = ((buf[0] & 0x0F) << 8) | buf[1]`  
  `raw_y = ((buf[2] & 0x0F) << 8) | buf[3]`
- 设备实测 `/sys/class/input/event3/device/device/axs_tp_dir` 为 `0`。在驱动汇编 `0x00000da2` 处判定 `g_axs_tp_dir == 0`，因此直接向 Linux input 子系统上报物理绝对坐标：
  `ABS_MT_POSITION_X = raw_x` ($0 \sim 239$)  
  `ABS_MT_POSITION_Y = raw_y` ($0 \sim 1019$)

#### Falcon 输入线程逆变换 (`greenui::winInputLoop` 地址 `0x002275d4`)
Falcon 使用 `tslib` 读取多点触控样本后，在 `0x002278ac` 检查 `_tp_direction == 270` 并执行逆变换：
```arm
0x00227bd0: vmov r2, s17          ; r2 = raw_y - tp_yoffset
0x00227bd4: ldr  r3, [sp, #0x40]  ; r3 = mWidth (1020)
0x00227bdc: vmov.f32 s17, s16     ; [NEW Y] = raw_x - tp_xoffset
0x00227be0: sub  ip, r3, r2       ; ip = 1020 - y
0x00227be4: sub  r2, ip, #1       ; r2 = 1019 - y
0x00227bf0: bl   fmax             ; clamp 下界: max(0.0, 1019 - y)
0x00227aac: bl   fmin             ; clamp 上界: min(1019.0, max(0.0, 1019 - y))
0x00227ab4: vcvt.s32.f64 s16, d0  ; [NEW X] = clamp(1019 - y, 0, 1019)
```

**数学变换公式**：
$$\begin{cases} X_{log} = \text{clamp}(1019 - Y_{raw}, 0, 1019) \\ Y_{log} = X_{raw} \end{cases}$$

#### 派发到 Vue 的调用链
1. `winInputLoop` 计算出 $(X_{log}, Y_{log})$；
2. 构造 `greenui::MotionEvent`；
3. `greenui::FBNativeWindow::inputTouchEvent`；
4. `greenui::WindowManager::dispatchTouchEvent`；
5. `greenui::ViewGroup::dispatchTouchEvent`（在 1020×240 空间进行子组件命中测试）；
6. `JQuick::WXGesture::onTouch`（地址 `0x003bafd4`）转换为 QuickJS Touch 事件：
   - `e.touches[0].pageX = X_{log}`
   - `e.touches[0].pageY = Y_{log}`
7. 若为短促点击，触发派发 `click` 事件。
开发者在 Vue 的 `@touchstart` / `@click` 中接收到的已经是完美的 1020×240 逻辑坐标。

---

### 4. 原生 `<canvas>` 绘图坐标系与 Skia 渲染

#### 绘图上下文实现 (`JQuick::CanvasContext` 地址 `0x00376dbc`)
反编译 `CanvasContext::fillRect(x, y, w, h)`：
```arm
0x00376dc4: mov  r7, r1           ; r7 = x
0x00376dd4: mov  sl, r2           ; sl = y
0x00376ddc: mov  r5, r3           ; r5 = w
0x00376e04: ldr  r3, [sp, #0x88]  ; r3 = h
0x00376e10: add  r3, sl, r3       ; r3 = y + h (bottom)
0x00376e20: add  r3, r7, r5       ; r3 = x + w (right)
0x00376e38: bl   SkCanvas::drawRect ; 直接构造 SkRect 并提交绘制
```

**结论**：
- `<canvas width="1020" height="240">` 的 Skia 2D 上下文直接工作在 1020×240 坐标系下。
- 组件原点 $(0, 0)$ 即左上角，调用 `ctx.fillRect(0, 0, 1020, 240)` 即可完全覆盖整块画布。
- **严禁在 JavaScript 中调用 `ctx.rotate` 做旋转补正**。旋转完全由底层的 Framebuffer 提交线程自动完成。

---

## 三、 Linux Framebuffer 硬件旋转 Blit 引擎（SIMD NEON）

### 1. 硬件帧缓冲状态
- 物理设备：`/dev/fb0`
- 色彩格式：32 bpp (ARGB8888, 每像素 4 字节)
- 物理模式：`240x1020p-0`，行跨度 960 字节
- 虚拟尺寸：`240, 2040`（通过两倍高度实现双缓冲机制）

### 2. 旋转 Blit 核心汇编分析
在 `greenui::post_fb` (`0x00224b80`) 和 `greenui::rotate_fb` (`0x00223c5c`) 中：
- 检测到 `_direction == 270`（`0x10e`）且 `bpp == 32`；
- 跳转至 `0x00224798`，调用 `yd_l_rotate90_S32`（`_Z17yd_l_rotate90_S32PKhiiPhiiiiiiii`，地址 `0x002289f0`）；
- 该函数采用 ARMv7-A NEON 矢量指令（`vld4.32` / `vst4.32`）进行 $4 \times 4$ 或 $8 \times 8$ 块转置，实现逆时针 90° 旋转（几何上等价于顺时针 270°）。

### 3. 显示旋转矩阵与显存映射公式

$$\begin{bmatrix} X_{fb} \\ Y_{fb} \end{bmatrix} = \begin{bmatrix} 0 & 1 \\ -1 & 0 \end{bmatrix} \begin{bmatrix} X_{log} \\ Y_{log} \end{bmatrix} + \begin{bmatrix} 0 \\ 1019 \end{bmatrix} = \begin{bmatrix} Y_{log} \\ 1019 - X_{log} \end{bmatrix}$$

显存字节偏移计算公式：
$$\text{Offset}_{fb} = \Big((1019 - X_{log}) \times 240 + Y_{log}\Big) \times 4$$

每次渲染完成后，通过双缓冲平移与垂直同步刷新显示：
- `ioctl(fb_fd, FBIOPAN_DISPLAY, &vinfo)`（平移 `yoffset` 为 0 或 1020）；
- `ioctl(fb_fd, FBIO_WAITFORVSYNC, 0)`（等待垂直消隐，杜绝画面撕裂）。

---

## 四、 几何映射闭环数学证明与速查表

### 1. 双向互逆性数学证明
设用户点击屏幕上某个由逻辑坐标 $(X_{log}, Y_{log})$ 绘制的按钮：
1. **渲染显示位置**：
   $$X_{fb} = Y_{log}, \quad Y_{fb} = 1019 - X_{log}$$
2. **触控传感器物理接收**：
   因为触摸屏物理覆盖在显示屏上方，手指触摸点的物理硬件坐标为 $(X_{raw}, Y_{raw}) = (X_{fb}, Y_{fb})$；
3. **输入线程逆变换**：
   $$X_{event} = 1019 - Y_{raw} = 1019 - (1019 - X_{log}) = X_{log}$$
   $$Y_{event} = X_{raw} = Y_{log}$$
**结果恒等证明**：$(X_{event}, Y_{event}) \equiv (X_{log}, Y_{log})$。显示渲染与触控输入构成理想的互逆仿射变换闭环，误差为 0。

### 2. 全链路坐标系速查表

| 层级 | 坐标系名称 | 宽度/X跨度 | 高度/Y跨度 | 坐标原点 $(0, 0)$ 对应物理方位 |
| :--- | :--- | :--- | :--- | :--- |
| **物理硬件显示屏** | 物理面板矩阵 | 240 列 | 1020 行 | 笔身顶端左侧角落 |
| **Linux Framebuffer** | 显存空间 (`/dev/fb0`) | 240 像素 | 2040 像素 (双缓冲) | 显存首地址 (对应竖屏顶端) |
| **触控驱动 (`axs_ts.ko`)** | Evdev 绝对坐标 (`event3`)| $0 \sim 239$ | $0 \sim 1019$ | 物理面板左上角 |
| **Falcon 根窗口 (`NativeWindow`)** | 逻辑视口空间 | **1020 px** | **240 px** | 横屏视角左上角 |
| **Vue / MiniApp 布局** | CSS 逻辑像素 | **1020 px** | **240 px** | 横屏视角左上角 |
| **Canvas 2D 上下文** | Skia 绘图矩阵 | **1020 px** | **240 px** | 画布组件左上角 |

---

## 五、 原生 UI 与交互开发避坑指南

1. **容器根尺寸规范**：
   始终以 `width: 1020px; height: 240px;` 作为 App 主页面根容器。绝对定位与 Flex 布局均按此尺寸设计。
2. **Canvas 绘图严禁二次旋转**：
   在 `<canvas width="1020" height="240">` 上绘图时，原点即为左上角，直接调用 `fillRect` / `drawImage`。严禁手动调用 `ctx.rotate(270 * Math.PI / 180)`。
3. **`<scroller>` 滚动方向选择**：
   - 绝大多数应用优先选择 `scroll-direction="horizontal"`（横向滚动，1020px 充裕滑动行程）；
   - 若设置 `scroll-direction="vertical"`，手指滑动动作是**沿词典笔机身宽度方向横向滑擦**，行程极短（240px），务必调小行高并限制列表条目数。
4. **触摸手势交互**：
   `e.touches[0].pageX` 范围为 $0 \sim 1019$，`pageY` 范围为 $0 \sim 239$。可以直接用于拖拽、滑动距离计算和几何碰撞检测，无需做任何平台特定补正。
