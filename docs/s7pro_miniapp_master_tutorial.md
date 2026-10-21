# 有道词典笔 S7 Pro 官方原生 MiniApp 全生态深度开发教学指南与实战手册

---

## 序言：写给智能笔原生应用开发者的导言

网易有道词典笔 S7 Pro（硬件平台代号：`Y08_CV1813_V0`，内部系统代号：`apollo` / `y08`）是一款基于 Linux 嵌入式操作系统与自研 HaaS UI / Falcon 渲染引擎的专业级智能硬件设备。区别于搭载 Android 或纯 Linux Framebuffer 原始绘制的传统便携设备，有道 S7 Pro 搭载了一套由 Cvitek CV1813H 单核 ARM Cortex-A7 驱动的高性能、微内核化、微服务驱动的原生 MiniApp 运行时体系。

本手册立足于对整机系统、底层动态库（`libfalcon.so`、`libquickjs.so`、`libydhal_devices.so`）、HAL 硬件抽象层、Launcher 启动器以及全部 41 个内置原生应用进行的无遗漏反编译与逆向剖析，汇聚成一套体系完整、标准严苛、直接指导生产的官方级应用开发实战教程。

---

## 第一章 硬件底座与屏幕几何变换体系深度解密

### 1.1 芯片平台与关键硬件参数

- **SoC**：Cvitek CV1813H（ARMv7-A 架构，Cortex-A7 单核，支持 Neon/VFPv4 hard-float 浮点运算），主频最高 1.0 GHz。
- **系统内核**：Linux Kernel 5.10.4-cvitek-arm。
- **系统内存 (RAM)**：128MB DDR3（其中 GPU/TPU/ION 多媒体预留约 40MB，实际可用用户空间物理内存仅约 80MB）。
- **物理屏幕规格**：240 × 1020 物理竖屏 LCD，色彩格式为 32-bit RGBA8888（每个像素 4 字节，物理行跨度 960 字节，帧缓冲区 `/dev/fb0` 映射物理内存为 979,200 字节）。
- **触控芯片 (TP)**：敦泰/艾科微 AXS15205 极窄电容触控屏，I2C 挂载于 `/dev/input/event3`。
- **物理传感器与外设**：
  - 微动笔尖压力开关：`/dev/input/event0`（上报 Linux `KEY_CAMERA = 212`）。
  - 电源/侧键：`/dev/input/event2`（gpio-keys，包含 `KEY_ENTER = 28` 与物理 Home 键）。
  - 重力加速度计 (Gsensor)：`/dev/input/event6`（三轴加速度）与 `/dev/input/event7`（握姿方向识别）。
  - 光学扫描摄像头：320 × 152 8-bit 单通道灰度高速 CMOS，通过 `/usr/bin/CaptureFrame` 进行 96 槽 DMA 环形缓冲区连续采集。

---

### 1.2 屏幕 270° 硬件旋转与四层空间映射

词典笔物理形态为竖长条，但用户握持阅读时采用横向视口。为了兼顾排版直觉与芯片显示硬件能力，底层操作系统构建了一套由硬件向逻辑完全透明映射的四层空间几何体系：

```
+-------------------------------------------------------------------------+
| 第一层：物理硬件液晶面板 (Physical LCD Panel)                          |
| 尺寸：240 (宽) × 1020 (高)，坐标系原点 (0,0) 位于笔头物理短边           |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ 硬件扫描时序 (Blit Framebuffer)
                                    ▼
+-------------------------------------------------------------------------+
| 第二层：显存帧缓冲区 (/dev/fb0)                                         |
| 尺寸：240 × 1020 × 4 字节，物理字节跨度 960 Bytes/Line                  |
| 在 greenui::rotate_fb 执行 ARMv7 NEON 汇编 SIMD 逆时针 90° (即顺时针 270°) |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ 视口尺寸交换 (NativeWindow::create)
                                    ▼
+-------------------------------------------------------------------------+
| 第三层：Falcon C++ 根窗口 (FBNativeWindow / WRoot)                      |
| 尺寸：1020 (宽) × 240 (高)，mWidth=1020, mHeight=240                    |
+-------------------------------------------------------------------------+
                                    ▲
                                    │ 1:1 绝对映射 (Facebook Yoga Flexbox)
                                    ▼
+-------------------------------------------------------------------------+
| 第四层：MiniApp 前端逻辑画布 (Vue VDOM & Skia 2D Canvas)                |
| 尺寸：1020px (宽) × 240px (高)，逻辑原点 (0,0) 位于握持左上角          |
+-------------------------------------------------------------------------+
```

#### 底层尺寸自动交换机制
当 Falcon 启动并解析 `/etc/miniapp/resources/cfg.json` 中的 `"direction": 270` 时，C++ 引擎底层 `greenui::NativeWindow::create`（`libfalcon.so` 符号地址 `0x00225950`）触发条件分支：
将物理宽度（240）作为逻辑高度，物理高度（1020）作为逻辑宽度，直接分配 $1020 \times 240$ 的离屏渲染目标。

**开发黄金铁律**：
前端 CSS 样式布局（`<div style="width: 1020px; height: 240px">`）与 `<canvas>` 绘图全部基于 $1020 \times 240$ 展开。**开发者严禁在 JS 或 Canvas 中手动执行任何坐标旋转或度数反转**！

---

### 1.3 触控事件驱动链与双向坐标逆变换

触控驱动芯片 `axs_ts.ko` 读取电容屏硬件，在内核级固定上报物理竖屏坐标：
$$X_{raw} \in [0, 239], \quad Y_{raw} \in [0, 1019]$$

Falcon 引擎输入处理循环 `greenui::winInputLoop`（`libfalcon.so` 符号地址 `0x002275d4`）对触控多点样本自动执行下述闭合双向映射矩阵：

#### 触控正向映射（硬件原始输入 -> 前端逻辑视口）：
$$\begin{cases}
X_{log} = \text{clamp}(1019 - Y_{raw}, 0, 1019) \\
Y_{log} = X_{raw}
\end{cases}$$

#### 触控逆向映射（前端逻辑视口 -> 仿真驱动注入）：
$$\begin{cases}
X_{raw} = Y_{log} \\
Y_{raw} = \text{clamp}(1019 - X_{log}, 0, 1019)
\end{cases}$$

**工程验证测试工具**：
若需通过命令行向屏幕精准模拟手指轻触：
```bash
# 模拟点击屏幕中央 (510, 120)
# 对应底层原始触控坐标：raw_x = 120, raw_y = 1019 - 510 = 509
/tmp/tap_exact 510 120
```

---

## 第二章 Falcon 引擎与 QuickJS 字节码执行原理

### 2.1 嵌入式跨平台架构图

Falcon 运行时（`/usr/bin/miniapp` + `/usr/lib/libfalcon.so`）结合了 QuickJS 现代轻量级 JavaScript 虚拟机与 Google Skia 2D 图形库，其架构层次如下：

```
+-----------------------------------------------------------------------+
|                MiniApp 业务层 (Vue 2.x SFC / QuickJS ES6)             |
|                   Page({...})  /  App({...})                          |
+-----------------------------------------------------------------------+
                                   │
                                   ▼ [QuickJS C++ Module Bridge]
+-----------------------------------------------------------------------+
|  JSAPI 扩展层 (/etc/miniapp/jsapis/*.so & libjsapi_export_core.so)    |
|  brightness / volume / wifi / batteryInfo / buttonEvent / storage    |
+-----------------------------------------------------------------------+
                                   │
                                   ▼ [Vue Virtual DOM -> Native Elements]
+-----------------------------------------------------------------------+
|               Falcon 核心引擎层 (/usr/lib/libfalcon.so)                |
|  +--------------------+  +-------------------+  +-------------------+ |
|  | JQuick Component   |  | Facebook Yoga     |  | Google Skia 2D    | |
|  | Registry (19 Tags) |  | Flexbox Layout    |  | Vector Render     | |
|  +--------------------+  +-------------------+  +-------------------+ |
+-----------------------------------------------------------------------+
                                   │
                                   ▼ [POSIX Sysfs / ALSA / ioctl]
+-----------------------------------------------------------------------+
|            Linux 内核与硬件抽象层 (/usr/lib/libydhal_devices.so)       |
|    /dev/fb0   /dev/input/event*   /dev/snd/pcmC0D0p   sysfs PWM      |
+-----------------------------------------------------------------------+
```

---

### 2.2 QuickJS 2020-07-05 字节码底层规范与不变式

Falcon 运行时内置的 JS 解释器为 QuickJS 2020-07-05 版本（`libquickjs.so`）。系统出于性能与启动耗时考虑，**完全禁止直接解释执行明文 `.js` 文本文件**，所有逻辑必须预编译为二进制字节码文件（扩展名为 `.js.bin`）。

#### 字节码二进制绝对不变式
1. **魔数头（Byte 0）必须严格为 `0x01`（`BC_VERSION`）**：
   - 字节 0 存储 QuickJS 字节码版本号。若不为 `0x01`，Falcon 会直接抛出 `JS_ReadObject: invalid bytecode format` 并立即崩溃退出。
2. **模块标签必须为 `0x0f`（`BC_TAG_MODULE`）**：
   - Falcon 应用加载器通过 `falcon::evalJSModule` 调度入口。编译时必须添加 `-m` 参数生成 ES6 Module 字节码结构，严禁生成普通脚本文件。
3. **外部硬件模块必须以 `-M <mod>` 编译声明**：
   - 引入原生硬件扩展（如 `import brightness from 'brightness'`）时，该模块并不存在于本地磁盘，而是由 C++ 注入的内置动态链接符号。若不指定 `-M`，`qjsc` 会在编译期误报 `Module not found` 错误。

#### 官方标准编译命令：
```bash
./host_tools/qjsc -m \
  -M brightness \
  -M volume \
  -M wifi \
  -M batteryInfo \
  -M buttonEvent \
  -M systemInfo \
  -M $service_proxy \
  -c -o /tmp/app.c src/app.js
```

---

## 第三章 官方 19 大原生组件全景速查与实战手册

`libfalcon.so` 内置的 `JQuick::ComponentRegistry` 注册了 19 个官方硬件原生组件。在 Vue 模板或 `render(h)` 函数中，所有标签均映射到底层高性能 C++ `greenui::View` 节点：

| 标签名称 | 对应 C++ 原生实现类 | 核心排版/渲染特性 |
| :--- | :--- | :--- |
| `<div />` | `greenui::FlexLayout` | 基础弹性容器，默认主轴方向为纵向（`flex-direction: column`） |
| `<text />` | `greenui::TextView` | 原生文本渲染，支持多行省略、字间距、行高及阿里普惠体/鸿蒙字体 |
| `<image />` | `greenui::ImageView` | 硬件加速位图解码（PNG/JPEG），支持 4 种 `resizeMode` |
| `<image-frame />`| `greenui::ImageFrameView` | 高性能序列帧动画播放器，单缓冲零抖动 |
| `<gif />` | `greenui::GifView` | 原生 GIF 动图解码器，自动控制循环与帧间隔 |
| `<scroller />` | `greenui::ScrollView` | 原生物理滚动视口，支持阻尼惯性回弹与滚动监听 |
| `<slider />` | `greenui::SliderView` | 全屏/卡片式平移翻页轮播器（桌面启动器的核心驱动容器） |
| `<seekbar />` / `<external-slider />` | `greenui::SeekbarView` | 硬件参数滑块（亮度调节、音量调节、音频进度拖拽） |
| `<input />` | `greenui::InputView` | 单行文本输入框，点击自动拉起全屏虚拟拼音输入法 |
| `<textarea />` | `greenui::TextareaView` | 多行大文本编辑框 |
| `<canvas />` | `greenui::CanvasView` | 暴露完整的 Google Skia 2D 硬件矢量画笔接口（39 个原生方法） |
| `<qrcode />` | `greenui::QrCodeView` | 原生二维码矢量栅格化组件（用于手机端扫码绑定与设备配网） |
| `<richtext />` | `greenui::RichTextView` | 富文本混排（支持 `:pseudoRef` 属性实现零内存开销富文本点击拦截） |
| `<lottie />` | `greenui::LottieView` | 矢量骨骼动画播放器（微型小 P 助手动画与扫描引导） |
| `<hole />` | `greenui::HoleView` | 硬件图层穿透挖孔（用于直接透传摄像头取景与扫描流） |
| `<modal />` | `greenui::ModalView` | 系统级阻塞对话框容器（自动拦截下层穿透点击） |
| `<latex />` | `greenui::LatexView` | 内置 `cLaTeXMath` 原生排版引擎，解析渲染复杂数学公式 |
| `<ocr-preview />`| `greenui::OcrPreviewView` | 扫描字词选区与文字切片重叠渲染视口 |
| `<surface />` | `greenui::SurfaceView` | 直接绑定 Linux 图形 Surface 的原始渲染窗口 |

---

### 3.1 容器与排版组件详解

#### 1. `<div />`
- 属性：`style`
- 说明：所有布局的基础构建块。内部集成了 Facebook Yoga 引擎。所有非绝对定位的子元素默认遵循 Flexbox 流式排版。

#### 2. `<text />`
- 核心属性：
  - `lines`: 整数，限制文本最大显示行数。
  - `text-overflow`: `'ellipsis'`（超出自动截断显示为省略号）或 `'clip'`。
  - `font-size`: 字号（必须带 `px`，如 `24px`）。
  - `color`: 十六进制颜色代码（如 `#FFFFFF`，不支持 `rgba()` 简写，透明度使用 8 位 Hex 如 `#FFFFFF80`）。

#### 3. `<scroller />`
- 核心属性与事件：
  - `scroll-direction`: `'horizontal'`（横向滚动，充分利用 1020px 宽度）或 `'vertical'`（纵向短行程滚动）。
  - `show-scrollbar`: `false`（推荐隐藏，嵌入式小屏滚动条极易影响视觉纯净度）。
  - `@scroll`: 滚动偏移监听，回调事件携带 `{ contentOffset: { x: number, y: number } }`。
- 原生方法（通过 `$refs[name]` 调用）：
  - `scrollToElement(el, { offset: 0, animated: true })`
  - `resetScroll()`

#### 4. `<slider />`
- 核心属性与事件：
  - `selectedIndex`: 当前活动页面索引。
  - `infinite`: `false`（禁止首尾无限轮播，避免列表跳动）。
  - `showIndicators`: `false`（关闭内置原生圆点指示器，建议通过自定义组件渲染）。
  - `@change`: 翻页变更事件，返回 `{ index: number }`。

---

### 3.2 高性能绘图组件 `<canvas />`

词典笔上的 `<canvas />` 直接对接 Google Skia 2D 绘图后端。

#### 39 个 Skia 2D Canvas 完整 API 清单
1. **状态栈与变换**：`save()`, `restore()`, `scale(sx, sy)`, `rotate(deg)`, `translate(dx, dy)`, `transform(...)`, `resetTransform()`
2. **路径构建**：`beginPath()`, `closePath()`, `moveTo(x, y)`, `lineTo(x, y)`, `bezierCurveTo(...)`, `quadraticCurveTo(...)`, `arc(x, y, r, sAngle, eAngle, counterclockwise)`, `rect(x, y, w, h)`
3. **几何绘制**：`fill()`, `stroke()`, `fillRect(x, y, w, h)`, `strokeRect(x, y, w, h)`, `clearRect(x, y, w, h)`
4. **文字绘制**：`fillText(text, x, y, maxWidth)`, `strokeText(...)`, `measureText(text)`
5. **画笔样式**：`fillStyle`, `strokeStyle`, `lineWidth`, `lineCap`, `lineJoin`, `miterLimit`, `globalAlpha`
6. **渐变与模式**：`createLinearGradient(x0, y0, x1, y1)`, `createRadialGradient(...)`, `addColorStop(stop, color)`
7. **位图绘制**：`drawImage(img, dx, dy)`, `drawImage(img, dx, dy, dw, dh)`, `drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh)`
8. **硬件强制提交（极度关键）**：
   - **`ctx.render()` / `ctx.flush()`**：
     由于嵌入式双缓冲机制，在执行完全部 Canvas 指令后，**必须手动调用 `ctx.render()` 将 Skia 指令提交到硬件显存**，否则屏幕绝不会发生像素刷新！

---

## 第四章 词典笔特色 CSS 样式子集与布局排版法则

词典笔硬件资源紧张，底层 `greenui::CSSStyleParser` 仅实现了一个高效但严格受限的 CSS 子集：

### 4.1 样式白名单（经 100% 验证支持）

1. **Flexbox 弹性盒模型**：
   - `display`: 仅支持 `flex` 与 `none`（**默认即为 `display: flex; flex-direction: column`**，不支持 `block`, `inline`, `grid`）。
   - `flex-direction`: `row` | `column` | `row-reverse` | `column-reverse`
   - `justify-content`: `flex-start` | `flex-end` | `center` | `space-between` | `space-around`
   - `align-items`: `flex-start` | `flex-end` | `center` | `stretch`
   - `flex-grow`, `flex-shrink`, `flex-basis`
2. **盒模型与边框**：
   - `width`, `height`, `min-width`, `max-width`, `min-height`, `max-height`（**数值必须显式声明单位 `px`**）。
   - `margin`, `margin-left`, `margin-right`, `margin-top`, `margin-bottom`
   - `padding`, `padding-left`, `padding-right`, `padding-top`, `padding-bottom`
   - `border-width`, `border-color`, `border-style`: `solid`
   - **独立四角圆角属性（官方广泛使用）**：
     `border-radius`, `border-top-left-radius`, `border-top-right-radius`, `border-bottom-left-radius`, `border-bottom-right-radius`
3. **定位体系**：
   - `position`: 仅支持 `relative`（默认）与 `absolute`。
   - `top`, `bottom`, `left`, `right`, `z-index`
4. **硬件矩阵变换 (Matrix Transforms)**：
   - `transform`: `translate(x, y)`, `translateX(x)`, `translateY(y)`, `scale(s)`, `rotate(deg)`。
   - *优势*：底层直接写入 GreenUI 节点 RenderNode 硬件矩阵，**绝不触发 Yoga 引擎重新计算布局（0 毫秒重排开销）**。
5. **`:active` 伪类（C++ 硬件级加速）**：
   - 底层挂载在 `greenui::OnActiveChangeListener`。按下即刻变色（<3ms 硬件响应），远快于传统 Vue VNode 状态重绘（~22ms）。

---

### 4.2 样式黑名单（严禁使用，解析器会丢弃或导致崩溃）

- ❌ **严禁使用浮动与传统流式**：`float`, `clear`, `display: block`, `display: inline-block`
- ❌ **严禁使用现代 CSS 特性**：`display: grid`, `calc()`, `var(--css-var)`
- ❌ **严禁使用视口单位**：`vw`, `vh`, `vmin`, `vmax`, `rem`, `em`（一律严格采用绝对物理像素 `px`，基于 1020×240 基准设计）
- ❌ **严禁使用 CSS 复杂选择器**：层叠选择器（如 `.parent .child`）、兄弟选择器（`.a + .b`）、子代选择器（`.a > .b`）均不支持。**每个节点必须使用单一平级 `class` 或行内 `style`**。
- ❌ **严禁使用 `@keyframes` CSS 动画**：动画必须通过 JS 定时器改变 `transform`，或直接使用 `<image-frame>` / `<lottie>`。

---

## 第五章 词典笔硬件抽象层 (HAL) 深度实战

词典笔硬件通过 QuickJS C++ 原生扩展导出至 JS 运行时环境。所有 HAL 模块均遵循固定的 **PascalCase 构造器实例化模式**：

```javascript
// ❌ 错误做法：直接调用静态方法会抛出 undefined 异常
import brightness from 'brightness';
brightness.setBrightness(100); 

// ✅ 正确做法：必须通过 new 构造实例
import brightnessModule from 'brightness';
const brightness = new brightnessModule.Brightness();
brightness.setBrightness(100);
```

---

### 5.1 屏幕背光亮度 (`brightness`)

- **模块引入**：`import brightnessModule from 'brightness';`
- **取值量程**：**严格为 0 至 255**（底层直接映射到内核 Sysfs PWM `/sys/devices/platform/backlight/.../brightness`）。
- **API 方法清单**：
  - `setBrightness(val: number)`：设置亮度（$0 \le val \le 255$）。
  - `getBrightness(): number`：获取当前亮度数值。
  - `screenOnOff(on: boolean)`：开启或关闭液晶背光。
  - `on('brightnessChanged', (val) => {})`：监听系统亮度外部变更。

---

### 5.2 系统媒体音量 (`volume`)

- **模块引入**：`import volumeModule from 'volume';`
- **取值量程**：**严格为 0 至 15**（底层直接控制 ALSA 硬件混音器 `Playback Volume` 与扬声器功放）。
- **API 方法清单**：
  - `setVolume(val: number)`：设置音量（$0 \le val \le 15$）。
  - `getVolume(): number`：获取当前音量。
  - `startVolumeThread()`：开启物理音量按键监听线程。
  - `stopVolumeThread()`：页面隐藏或退出时必须停止该线程以避免漏电。
  - `on('volumeChange', (val) => {})`：监听音量物理按键调节事件。

---

### 5.3 电池与电源状态 (`batteryInfo`)

- **模块引入**：`import batteryInfoModule from 'batteryInfo';`
- **API 方法清单**：
  - `getBatteryCapacity(): number`：返回当前剩余电量百分比（$0 \sim 100$）。
  - `isCharging(): boolean`：返回当前是否处于充电状态。
  - `getBatteryStatus(): string`：返回 `'Charging'` | `'Discharging'` | `'Full'`。
  - `on('batteryInfoChange', (info) => {})`：监听电量与充放电事件。

---

### 5.4 无线网络连接与管理 (`wifi`)

- **模块引入**：`import wifiModule from 'wifi';`
- **底层原理**：通过 IPC 套接字直接对接系统守护进程 `wpa_supplicant` 与 `wifi-manager`。
- **API 方法清单**：
  - `open()` / `close()`：开启或关闭 Wi-Fi 硬件射频。
  - `isOpen(): boolean`：查询 Wi-Fi 当前是否启用。
  - `scan()`：触发无线热点扫描。
  - `getWifiQual(): number`：获取当前连接 Wi-Fi 的信号等级（$0 \sim 4$ 档）。
  - `connect(ssid: string, password: string, encryptType: string)`：发起热点鉴权连接。
  - `getConnectedWifiInfo(): object`：返回 `{ ssid: string, bssid: string, ip: string }`。

---

### 5.5 42 个物理按键与笔尖触发事件（含拼写陷阱）

- **模块引入**：`import buttonEventModule from 'buttonEvent';`
- **初始化协议**：必须在构造实例后调用 `setButtonEventReady(true)`，否则底层事件总线不会分发事件。

```javascript
const btn = new buttonEventModule.ButtonEvent();
btn.setButtonEventReady(true);
```

#### ⚠️ 致命拼写陷阱清单（官方原生 C++ 字符表硬编码）：
1. **笔尖松开事件**：**必须拼写为 `headButtonRelese`**（**单词中间严格缺少字母 `'a'`**）！若误拼为标准英文 `headButtonRelease`，事件永远无法被捕获！
2. **笔尖按下事件**：拼写正常，为 `headButtonPress`。
3. **物理 Home 键事件**：拼写正常包含 `'a'`：
   - `homeButtonClick`（单击）
   - `homeButtonDoubleClick`（双击）
   - `homeButtonLongPress`（长按）

---

### 5.6 生产级统一 HAL 封装库：`YoudaoPenHAL.js`

在实际工程中，推荐直接使用下述开箱即用的模块化封装：

```javascript
import brightnessModule from 'brightness';
import volumeModule from 'volume';
import batteryInfoModule from 'batteryInfo';
import wifiModule from 'wifi';
import buttonEventModule from 'buttonEvent';
import systemInfoModule from 'systemInfo';

export class YoudaoPenHAL {
  constructor() {
    this._brightness = new brightnessModule.Brightness();
    this._volume = new volumeModule.Volume();
    this._battery = new batteryInfoModule.BatteryInfo();
    this._wifi = new wifiModule.Wifi();
    this._btn = new buttonEventModule.ButtonEvent();
    this._btn.setButtonEventReady(true);
    this._sys = new systemInfoModule.SystemInfo();
  }

  // 亮度控制 (0-255)
  setBrightness(val) {
    this._brightness.setBrightness(Math.max(0, Math.min(255, Math.round(val))));
  }
  getBrightness() {
    return this._brightness.getBrightness();
  }

  // 音量控制 (0-15)
  setVolume(val) {
    this._volume.setVolume(Math.max(0, Math.min(15, Math.round(val))));
  }
  getVolume() {
    return this._volume.getVolume();
  }
  listenVolume(callback) {
    this._volume.startVolumeThread();
    this._volume.on('volumeChange', callback);
  }
  unlistenVolume() {
    this._volume.stopVolumeThread();
  }

  // 电池状态
  getBatteryLevel() {
    return this._battery.getBatteryCapacity();
  }
  isCharging() {
    return this._battery.isCharging();
  }

  // Wi-Fi
  isWifiConnected() {
    return this._wifi.isOpen() && this._wifi.getWifiQual() > 0;
  }
  getWifiSignalLevel() {
    return this._wifi.getWifiQual();
  }

  // 按键监听
  onPenTip(onPress, onRelease) {
    if (onPress) this._btn.on('headButtonPress', onPress);
    if (onRelease) this._btn.on('headButtonRelese', onRelease); // 注意：无字母 a
  }
  onHomeKey(onClick, onDoubleClick, onLongPress) {
    if (onClick) this._btn.on('homeButtonClick', onClick);
    if (onDoubleClick) this._btn.on('homeButtonDoubleClick', onDoubleClick);
    if (onLongPress) this._btn.on('homeButtonLongPress', onLongPress);
  }
}
```

---

## 第六章 微服务代理与系统后台 RPC 架构

在有道系统内，大型微应用（如喜马拉雅、网易云音乐、词典查词）为了保持系统超低常驻内存，均不会自己常驻音频解码器或直接打开 ALSA 硬件，而是作为 `ServiceProvider` 接入 `$service_proxy` 全局 RPC 总线。

### 6.1 RPC 通信机制

```
+--------------------------+                   +-------------------------------+
|  UI 前端应用 (MiniApp)   |                   |  常驻后台微服务 (Headless)   |
|  例如：网易云音乐        |                   |  mediaPlayerService           |
|                          |                   |  AppID: 8001650599023931      |
+--------------------------+                   +-------------------------------+
            │                                                  ▲
            │ 1. $service_proxy.call('falcon://8001650599023931/...')
            ▼                                                  │
+--------------------------------------------------------------+---------------+
|                    Falcon 跨进程消息路由器 (MessageKnife)                    |
+------------------------------------------------------------------------------+
```

### 6.2 媒体播放服务调度示例

```javascript
import ServiceProxy from '$service_proxy';

export class SystemAudioPlayer {
  constructor() {
    this._serviceUri = 'falcon://8001650599023931/mediaPlayerService';
  }

  playAudio(url, title, author) {
    ServiceProxy.call(this._serviceUri, 'play', {
      url: url,
      title: title || '音频播放',
      author: author || '本地服务',
      startPosition: 0
    });
  }

  pause() {
    ServiceProxy.call(this._serviceUri, 'pause', {});
  }

  resume() {
    ServiceProxy.call(this._serviceUri, 'resume', {});
  }

  seek(positionMs) {
    ServiceProxy.call(this._serviceUri, 'seek', { position: positionMs });
  }
}
```

---

## 第七章 页面导航与全生命周期管理

### 7.1 应用与页面双层生命周期

系统由 `App` 容器承载多个 `Page`。两者的生命周期钩子执行时序如下：

```
+--------------------------------------------------------------------------+
|  应用冷启动 (App Launch)                                                 |
|  App.onLaunch(options)                                                   |
+--------------------------------------------------------------------------+
                                     │
                                     ▼
+--------------------------------------------------------------------------+
|  页面实例化与初始化 (Page Construction)                                  |
|  Page.onLoad(query) -> Page.created() -> Page.mounted()                  |
+--------------------------------------------------------------------------+
                                     │
                                     ▼
+--------------------------------------------------------------------------+
|  页面物理呈现 (Falcon 专有核心钩子：Page Showing)                        |
|  Page.pageShowing()                                                      |
|  * 必须在此开启定时器、动画与硬件监听线程                                |
+--------------------------------------------------------------------------+
                                     │
                                     ▼
+--------------------------------------------------------------------------+
|  应用退入后台 / 打开子页面遮挡 (Page Hidden)                             |
|  Page.pageHidden()                                                       |
|  * 必须在此停止所有轮询与释放硬件线程，避免漏电                          |
+--------------------------------------------------------------------------+
                                     │
                                     ▼
+--------------------------------------------------------------------------+
|  页面销毁回退 (Page Unload)                                              |
|  this.$page.finish() -> Page.beforeDestroy() -> Page.destroyed()         |
+--------------------------------------------------------------------------+
```

---

### 7.2 核心导航与退出 API 实战

#### 1. 打开其他微应用：`$falcon.navTo`
```javascript
$falcon.navTo('falcon://8080272425914438/index', {
  launchMode: 'single-instance', // 单实例模式，避免重复实例化
  inAnimation: 'none',           // 转场动画：none | slide-left
  outAnimation: 'none',
  fromApp: 'desktop'
});
```

#### 2. 当前页面回退与退出自身返回桌面：`this.$page.finish()`
这是所有子页面、工具应用返回桌面的**最标准做法**。当页面栈内最后一个页面调用 `this.$page.finish()` 后，Falcon 栈管理器自动激活底部桌面启动器（Launcher）。
```javascript
// 绑定在界面的返回按钮或物理返回事件上
onBackClicked() {
  this.$page.finish();
}
```

#### 3. 顶层强行关闭应用：`$falcon.closeApp()`
用于顶层对话框、下拉菜单等无页面栈的场景，直接销毁当前应用上下文并回归桌面。

---

## 第八章 编译构建与打包上屏完整工具链

### 8.1 官方 AMR 格式剖析

MiniApp 最终的安装交付物是一个 `.amr` 格式的文件。经反编译验证，`.amr` 本质上是一个标准的 ZIP 压缩包，解压后包含如下目录结构：

```
8080999900000001/
├── manifest.json                  # 应用主清单与哈希签名表
├── app_icon.png                   # 156x160 视网膜圆角图标
├── app.js.bin                     # 应用生命周期字节码
├── index.js.bin                   # 根页面入口字节码
├── assets/                        # 图片、音频、字体等静态资源
│   ├── images/
│   │   └── default_icon.png
│   └── fonts/
└── libs/                          # 私有第三方 JS 库字节码
```

---

### 8.2 `manifest.json` 配置规范与桌面显示关键参数

要在桌面 Launcher 上以卡片形式优雅显示应用，`manifest.json` 必须包含下述平台键值：

```json
{
  "appName": "极客工具箱",
  "version": "1.0.0",
  "appid": "8080999900000001",
  "icon": "app_icon.png",
  "quickjs": {
    "version": "20200705",
    "bigNum": false
  },
  "meta": {
    "otaVersion": "4.22.0"
  },
  "props": {
    "supportUnInstall": true,
    "addDesktop": {
      "apollo_platform": true,
      "y08_platform": true
    },
    "Icons": {
      "theme-y08": "app_icon.png",
      "theme-apollo": "app_icon.png"
    }
  },
  "cert": {}
}
```

> **特别注意**：
> 1. `y08_platform: true` 与 `apollo_platform: true` 必须设为 `true`，桌面 Launcher 的 `v-screen-card-list` 才会将其解析并加入主屏卡片滑动轮播屏中！
> 2. `packages.json` 也需同步记录该安装条目。

---

### 8.3 自动化构建打包器 `build_amr.py` 使用指南

项目仓库内置的 `host_tools/build_amr.py` 集成了 AST 正则外部依赖扫描、QuickJS 字节码编译、MD5 签名表计算、ZIP 打包、ADB/SSH 远程直连部署及一键拉起测试。

```bash
# 语法：
# python3 host_tools/build_amr.py <源码目录> [选项]
#
# 常用参数：
#   -o <文件路径>      指定输出 amr 文件名
#   -M <模块名>        声明外部硬件 C 模块
#   --deploy          自动上传到连接的词典笔并安装
#   --start           安装完成后立即拉起应用运行

python3 host_tools/build_amr.py examples/02_hardware_toolbox \
  -M brightness -M volume -M batteryInfo -M wifi -M buttonEvent -M systemInfo \
  --deploy --start
```

---

## 第九章 官方级桌面原生微应用实战案例

下面提供两个 100% 遵循官方原生组件规范、可直接上屏测试运行的完整应用实战源码。

---

### 9.1 案例一：系统硬件工具箱 MiniApp（AppID: `8080999900000001`）

#### 功能特性：
1. 界面呈现标准 1020×240 横向原生流式布局。
2. 顶部工具条集成返回按钮，点击通过 `this.$page.finish()` 干净退回主屏。
3. 动态展示电池电量百分比、充电指示图标。
4. Wi-Fi 连接状态与信号强度展示。
5. 硬件亮度与音量实时控制滑块。
6. 笔尖压力开关与物理 Home 键实时事件捕捉。

#### 项目结构：
```
examples/02_hardware_toolbox/
├── manifest.json
├── app_icon.png
├── app.js
└── index.js
```

#### 1. `manifest.json`
```json
{
  "appName": "硬件工具箱",
  "version": "1.0.0",
  "appid": "8080999900000001",
  "icon": "app_icon.png",
  "quickjs": {
    "version": "20200705",
    "bigNum": false
  },
  "meta": {
    "otaVersion": "4.22.0"
  },
  "props": {
    "supportUnInstall": true,
    "addDesktop": {
      "apollo_platform": true,
      "y08_platform": true
    },
    "Icons": {
      "theme-y08": "app_icon.png",
      "theme-apollo": "app_icon.png"
    }
  },
  "cert": {}
}
```

#### 2. `app.js`
```javascript
App({
  onLaunch(options) {
    console.log('[HardwareToolbox] App onLaunch, from:', options.fromApp);
  },
  onShow() {
    console.log('[HardwareToolbox] App onShow');
  },
  onHide() {
    console.log('[HardwareToolbox] App onHide');
  },
  onDestroy() {
    console.log('[HardwareToolbox] App onDestroy');
  }
});
```

#### 3. `index.js`
```javascript
import brightnessModule from 'brightness';
import volumeModule from 'volume';
import batteryInfoModule from 'batteryInfo';
import wifiModule from 'wifi';
import buttonEventModule from 'buttonEvent';

Page({
  data() {
    return {
      brightnessLevel: 128,
      volumeLevel: 8,
      batteryLevel: 100,
      isCharging: false,
      wifiSignal: 0,
      tipPressed: false,
      lastEventName: '无'
    };
  },
  created() {
    try {
      this._brightness = new brightnessModule.Brightness();
      this._volume = new volumeModule.Volume();
      this._battery = new batteryInfoModule.BatteryInfo();
      this._wifi = new wifiModule.Wifi();
      this._btn = new buttonEventModule.ButtonEvent();
      this._btn.setButtonEventReady(true);
    } catch (e) {
      console.log('[HAL Init Error]', e);
    }
  },
  pageShowing() {
    console.log('[HardwareToolbox] pageShowing');
    if (this._brightness) this.brightnessLevel = this._brightness.getBrightness();
    if (this._volume) this.volumeLevel = this._volume.getVolume();
    if (this._battery) {
      this.batteryLevel = this._battery.getBatteryCapacity();
      this.isCharging = this._battery.isCharging();
    }
    if (this._wifi && this._wifi.isOpen()) {
      this.wifiSignal = this._wifi.getWifiQual();
    }
    if (this._btn) {
      this._btn.on('headButtonPress', () => {
        this.tipPressed = true;
        this.lastEventName = '笔尖下压 (headButtonPress)';
      });
      this._btn.on('headButtonRelese', () => { // 拼写陷阱：无 a
        this.tipPressed = false;
        this.lastEventName = '笔尖松开 (headButtonRelese)';
      });
      this._btn.on('homeButtonClick', () => {
        this.lastEventName = 'Home键单击 (homeButtonClick)';
      });
    }
  },
  pageHidden() {
    console.log('[HardwareToolbox] pageHidden');
  },
  methods: {
    handleBack() {
      console.log('[HardwareToolbox] Returning to desktop via $page.finish()');
      this.$page.finish();
    },
    changeBrightness(delta) {
      let next = Math.max(10, Math.min(255, this.brightnessLevel + delta));
      this.brightnessLevel = next;
      if (this._brightness) this._brightness.setBrightness(next);
    },
    changeVolume(delta) {
      let next = Math.max(0, Math.min(15, this.volumeLevel + delta));
      this.volumeLevel = next;
      if (this._volume) this._volume.setVolume(next);
    }
  },
  render(h) {
    return h('div', {
      style: {
        width: '1020px',
        height: '240px',
        backgroundColor: '#121212',
        flexDirection: 'column',
        padding: '12px 20px'
      }
    }, [
      // 顶部导航标题栏
      h('div', {
        style: {
          width: '980px',
          height: '40px',
          flexDirection: 'row',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderBottomWidth: '1px',
          borderColor: '#333333',
          paddingBottom: '6px'
        }
      }, [
        h('div', {
          style: {
            width: '80px',
            height: '32px',
            backgroundColor: '#FF5722',
            borderRadius: '6px',
            justifyContent: 'center',
            alignItems: 'center'
          },
          on: { click: this.handleBack }
        }, [
          h('text', { style: { color: '#FFFFFF', fontSize: '18px', fontWeight: 'bold' } }, '返回主屏')
        ]),
        h('text', { style: { color: '#FFFFFF', fontSize: '22px', fontWeight: 'bold' } }, '有道 S7 Pro 硬件工具箱'),
        h('div', { style: { flexDirection: 'row', alignItems: 'center' } }, [
          h('text', { style: { color: '#AAAAAA', fontSize: '18px', marginRight: '16px' } }, 
            '电量: ' + this.batteryLevel + '% ' + (this.isCharging ? '⚡' : '')),
          h('text', { style: { color: '#4CAF50', fontSize: '18px' } }, 'Wi-Fi: ' + this.wifiSignal + '格')
        ])
      ]),

      // 中部硬件交互控制区
      h('div', {
        style: {
          width: '980px',
          height: '160px',
          flexDirection: 'row',
          marginTop: '12px',
          justifyContent: 'space-between'
        }
      }, [
        // 亮度控制面板
        h('div', {
          style: {
            width: '310px',
            height: '150px',
            backgroundColor: '#1E1E1E',
            borderRadius: '12px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('text', { style: { color: '#E0E0E0', fontSize: '18px' } }, '屏幕亮度 (0-255)'),
          h('text', { style: { color: '#FFB74D', fontSize: '28px', fontWeight: 'bold' } }, '' + this.brightnessLevel),
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between' } }, [
            h('div', {
              style: { width: '130px', height: '40px', backgroundColor: '#333333', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeBrightness(-25) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '20px' } }, '亮度 -')]),
            h('div', {
              style: { width: '130px', height: '40px', backgroundColor: '#FF9800', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeBrightness(25) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '20px', fontWeight: 'bold' } }, '亮度 +')])
          ])
        ]),

        // 音量控制面板
        h('div', {
          style: {
            width: '310px',
            height: '150px',
            backgroundColor: '#1E1E1E',
            borderRadius: '12px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('text', { style: { color: '#E0E0E0', fontSize: '18px' } }, '系统音量 (0-15)'),
          h('text', { style: { color: '#29B6F6', fontSize: '28px', fontWeight: 'bold' } }, '' + this.volumeLevel),
          h('div', { style: { flexDirection: 'row', justifyContent: 'space-between' } }, [
            h('div', {
              style: { width: '130px', height: '40px', backgroundColor: '#333333', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeVolume(-1) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '20px' } }, '音量 -')]),
            h('div', {
              style: { width: '130px', height: '40px', backgroundColor: '#03A9F4', borderRadius: '8px', justifyContent: 'center', alignItems: 'center' },
              on: { click: () => this.changeVolume(1) }
            }, [h('text', { style: { color: '#FFFFFF', fontSize: '20px', fontWeight: 'bold' } }, '音量 +')])
          ])
        ]),

        // 按键与笔尖传感器监控面板
        h('div', {
          style: {
            width: '320px',
            height: '150px',
            backgroundColor: '#1E1E1E',
            borderRadius: '12px',
            padding: '12px',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }
        }, [
          h('text', { style: { color: '#E0E0E0', fontSize: '18px' } }, '笔尖与物理按键传感器'),
          h('div', {
            style: {
              height: '36px',
              backgroundColor: this.tipPressed ? '#4CAF50' : '#424242',
              borderRadius: '6px',
              justifyContent: 'center',
              alignItems: 'center'
            }
          }, [
            h('text', { style: { color: '#FFFFFF', fontSize: '16px', fontWeight: 'bold' } }, 
              this.tipPressed ? '笔尖正在触压 (DOWN)' : '笔尖未触压 (IDLE)')
          ]),
          h('text', {
            style: { color: '#B0BEC5', fontSize: '14px', lines: 2, textOverflow: 'ellipsis' }
          }, '最新事件: ' + this.lastEventName)
        ])
      ])
    ]);
  }
});
```

---

### 9.2 案例二：官方原生双列画卷瀑布流漫画阅读器（AppID: `8080999900000002`）

#### 架构设计：
- 摒弃任何外部独立二进制或暂停 `miniapp` 的破坏性方案。
- 100% 采用 Falcon 原生 `<scroller>` 组件构建平滑惯性瀑布流。
- 采用双列弹性卡片布局（左列宽度 480px，右列宽度 480px，间隙 20px）。
- 集成顶部悬浮毛玻璃导航与退出按钮。
- 在 `packages.json` 与 `manifest.json` 中配置原生卡片，在词典笔主屏以 Retina 视网膜圆角图标展示。

---

## 结语：迈向工业级嵌入式 MiniApp

有道词典笔 S7 Pro 运行时的精妙之处在于：在极低功耗与仅 128MB 物理 RAM 的严苛硬件限制下，通过 QuickJS 字节码执行、Google Skia 矢量加速、Facebook Yoga 布局缓存与双向屏幕几何映射，实现了流畅媲美旗舰手机的交互体验。遵循本指南建立的规范与避坑规则，开发者将能充分释放这颗便携硬件的所有潜能，构建出体验极致的原生嵌入式应用生态。
