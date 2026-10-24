# Falcon 原生 19 核心组件与 CSS/Yoga 引擎规范全量手册
## (Falcon Native Components, Yoga Flexbox Specification & Visual Styling Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **底层引擎**: Falcon GUI Runtime (`/usr/lib/libfalcon.so`) + Facebook Yoga C Flexbox + GreenUI / Skia 2D  
> **反编译基准**: `JQuick::Component` (VTable `0x7d134c`), `JQuick::CSSStyleParser` (73 核心属性), `greenui::View` (VTable `0x7bf6e4`)

---

## 目录索引

1. [Falcon GUI 双层解耦渲染架构](#1-falcon-gui-双层解耦渲染架构)
2. [19 大原生组件完整属性、方法与事件字典](#2-19-大原生组件完整属性方法与事件字典)
   - [2.1 容器与布局组件 (`<div>` / `<container>`)](#21-容器与布局组件-div--container)
   - [2.2 文本排版组件 (`<text>`)](#22-文本排版组件-text)
   - [2.3 图像渲染组件 (`<image>` / `<img>`)](#23-图像渲染组件-image--img)
   - [2.4 高性能逐帧精灵组件 (`<image-frame>`)](#24-高性能逐帧精灵组件-image-frame)
   - [2.5 动图渲染组件 (`<gif>`)](#25-动图渲染组件-gif)
   - [2.6 单行输入框 (`<input>`)](#26-单行输入框-input)
   - [2.7 多行文本域 (`<textarea>`)](#27-多行文本域-textarea)
   - [2.8 高性能触控滚动容器 (`<scroller>`)](#28-高性能触控滚动容器-scroller)
   - [2.9 轮播滑块容器 (`<slider>`)](#29-轮播滑块容器-slider)
   - [2.10 硬件级拖动进度滑块 (`<external-slider>` / `<seekbar>`)](#210-硬件级拖动进度滑块-external-slider--seekbar)
   - [2.11 原生 2D 画布引擎 (`<canvas>`)](#211-原生-2d-画布引擎-canvas)
   - [2.12 富文本排版引擎 (`<richtext>`)](#212-富文本排版引擎-richtext)
   - [2.13 硬件二维码生成器 (`<qrcode>`)](#213-硬件二维码生成器-qrcode)
   - [2.14 矢量动效引擎 (`<lottie>`)](#214-矢量动效引擎-lottie)
   - [2.15 硬件视频直通层 (`<surface>`)](#215-硬件视频直通层-surface)
   - [2.16 聚焦镂空遮罩组件 (`<hole>`)](#216-聚焦镂空遮罩组件-hole)
   - [2.17 系统级模态弹窗 (`<modal>`)](#217-系统级模态弹窗-modal)
   - [2.18 笔尖扫读摄像头直通预览 (`<ocr-preview>`)](#218-笔尖扫读摄像头直通预览-ocr-preview)
   - [2.19 科学公式排版引擎 (`<latex>`)](#219-科学公式排版引擎-latex)
3. [CSS 引擎 73 项白名单与解析器机制](#3-css-引擎-73-项白名单与解析器机制)
4. [Yoga Flexbox 布局模型与带鱼屏几何计算规范](#4-yoga-flexbox-布局模型与带鱼屏几何计算规范)
5. [伪类状态机与样式动态响应 (`:active` & `:focus`)](#5-伪类状态机与样式动态响应-active--focus)
6. [严禁使用的 Web CSS 危险属性与崩溃陷阱](#6-严禁使用的-web-css-危险属性与崩溃陷阱)

---

## 1. Falcon GUI 双层解耦渲染架构

Falcon GUI 运行时在 CV1813H SoC（128MB 物理 RAM）上实现了类似 Android 的两层解耦视图树架构：

```
+-------------------------------------------------------------------------------+
|                    JavaScript / Vue SFC / Weex DOM Layer                      |
|                  (QuickJS Runtime, VNode Tree, BindingX)                     |
+---------------------------------------+---------------------------------------+
                                        | JS ElmApi 指令 / 虚拟 DOM 差分
                                        v
+-------------------------------------------------------------------------------+
|                 JQuick 逻辑组件层 (DOM Abstraction & Management)              |
|       基类: JQuick::Component (VTable: 0x7d134c, 43 个虚函数方法)             |
|  - 生命周期: onCreateHostView, appendDefaultStyles, setProperty, onRelease    |
|  - 几何度量: Yoga Flexbox 布局绑定, onMeasure, onPostLayout                    |
|  - 事件通道: onAddEvent, onRemoveEvent, fireEvent (PLT: 0x1d8318)            |
+---------------------------------------+---------------------------------------+
                                        | 原生 View 绑定与委托
                                        v
+-------------------------------------------------------------------------------+
|                    greenui 原生渲染层 (Native Display Subsystem)              |
|       基类: greenui::View (VTable: 0x7bf6e4, 38 个虚函数方法)                 |
|  - 2D 绘图: Skia 2D 图形引擎 (greenui::Canvas, SkCanvas, SkPaint, SkPath)     |
|  - 脏矩形流水线: NativeWindow::requestRender -> DisplayListCanvas -> post_fb  |
|  - 物理触控与按键: winInputLoop, ViewGroup::dispatchTouchEvent (touchSlop=8)  |
+-------------------------------------------------------------------------------+
```

### 1.1 标签解析与回退机制 (Fallback Rule)
在 `JQuick::ComponentRegistry::createComponent`（地址 `0x38437c`）中，当遇到未注册的扩展标签时，运行时执行强制回退：
```assembly
0x3843cc: ldr r1, =0x73959c  ; "container" (alias of <div> -> JQuick::DivHolder)
0x3843d4: bl  JQuick::ComponentRegistry::getComponentHolder
```
因此，标准 Weex 中的 `<list>`、`<cell>`、`<header>`、`<refresh>`、`<loading>` 在 Falcon 中全部回退为标准 flexbox `container` (`<div>`)。

---

## 2. 19 大原生组件完整属性、方法与事件字典

---

### 2.1 容器与布局组件 (`<div>` / `<container>`)
* **C++ DOM 类**: `JQuick::Component` (Holder: `JQuick::DivHolder` at `0x384a20`)
* **原生 View 类**: `greenui::ViewGroup`
* **VTable 地址**: `0x7d134c`
* **说明**: 基础通用容器与 Yoga 布局节点，默认 `box-sizing: border-box`。

#### 属性与样式
| 属性名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `flexDirection` | String | `"column"` | **注意: Yoga 默认主轴方向为 column，与浏览器不同！** |
| `justifyContent`| String | `"flex-start"` | `"flex-start"`, `"center"`, `"flex-end"`, `"space-between"`, `"space-around"`, `"space-evenly"` |
| `alignItems` | String | `"stretch"` | 交叉轴对齐: `"stretch"`, `"flex-start"`, `"center"`, `"flex-end"`, `"baseline"` |
| `flexWrap` | String | `"nowrap"` | `"nowrap"`, `"wrap"` (不支持 wrap-reverse) |
| `flex` | Number | `0` | 伸缩比例 |
| `position` | String | `"relative"` | 定位模式: `"relative"`, `"absolute"` |
| `overflow` | String | `"visible"` | 裁剪模式: `"visible"`, `"hidden"` |
| `opacity` | Number | `1.0` | 透明度: `0.0` ~ `1.0` |
| `zIndex` | Number | `0` | 层叠上下文索引 (内部调用 `greenui::View::setLayer`) |

#### 事件列表
- `click`: 点击事件
- `touchstart`, `touchmove`, `touchend`, `touchcancel`: 多点触控原始流
- `longpress`: 500ms 长按触发

---

### 2.2 文本排版组件 (`<text>`)
* **C++ DOM 类**: `JQuick::WXText` (Holder: `JQuick::TextHolder` at `0x384a70`)
* **原生 View 类**: `greenui::TextView` (基于 `greenui::TextLayout`)
* **VTable 地址**: `0x7d28c8`
* **说明**: Skia 矢量文字排版引擎，支持多行自适应、跑马灯与末尾省略。

#### 专有属性
| 属性名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `value` | String | `""` | 要渲染的纯文本内容 |
| `lines` | Number | `0` | 最大限制行数 (`0` 为无限制；设为 `1` 即单行模式) |
| `lineHeight` | Number | 字体默认 | 行高 (单位: `px`, `rpx`) |
| `fontSize` | Number | `28.0` | 字体大小 (默认 28px) |
| `color` | Color | `"#000000"` | 文字前景色 (Hex, RGB, RGBA, 命名颜色) |
| `fontWeight` | String | `"normal"` | `"normal"`, `"bold"`, `"100"` ~ `"900"` (`>= 600` 即加粗) |
| `fontStyle` | String | `"normal"` | `"normal"`, `"italic"` (开启 Skia 倾斜变换) |
| `fontFamily` | String | `"sans-serif"` | 字体家族名称 |
| `textAlign` | String | `"left"` | 对齐方式: `"left"`, `"center"`, `"right"` |
| `textDecoration`| String | `"none"` | 修饰线: `"none"`, `"underline"`, `"line-through"` |
| `textOverflow` | String | `"clip"` | 溢出截断: `"clip"`, `"ellipsis"` (**与 `lines: 1` 配合生效**) |
| `letterSpacing` | Number | `0.0` | 字间距 |
| `marquee` | Boolean | `false` | **是否开启跑马灯横向平滑滚动** |
| `marqueeSpeed` | Number | `1.0` | 跑马灯滚动速度乘数 |
| `marqueeGap` | Number | `50.0` | 跑马灯循环端点间距 (px) |

#### JS ElmApi 方法
- `setText(text)`: 绕过 VDOM 快速替换文本内容。

---

### 2.3 图像渲染组件 (`<image>` / `<img>`)
* **C++ DOM 类**: `JQuick::WXImage`
* **原生 View 类**: `greenui::ImageView`
* **说明**: Skia 硬件位图解码器，支持内存缓存与图片裁剪。

#### 专有属性
| 属性名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `src` | String | `""` | 资源地址 (支持 `file://`, 本地绝对路径, 相对路径, HTTP) |
| `resize` / `resizeMode` | String | `"stretch"` | 缩放算法: `"stretch"`, `"contain"`, `"cover"`, `"center"` |
| `blurRadius` | Number | `0.0` | Skia 高斯模糊半径 |
| `placeholder` | String | `""` | 加载完成前的占位底图 |

#### 事件列表
- `load`: `{ success: true, size: { naturalWidth, naturalHeight } }`
- `error`: `{ success: false, errorMsg: "..." }`

---

### 2.4 高性能逐帧精灵组件 (`<image-frame>`)
* **C++ DOM 类**: `JQuick::WXImageFrame` (地址 `0x7d26b8`)
* **原生 View 类**: `greenui::ImageFrame`
* **说明**: 专为词典笔 128MB 低内存微动效设计的逐帧动画播放器。

#### 专有属性与方法
- `interval`: 每帧间隔毫秒 (默认 40ms = 25 FPS)。
- `repeatCount`: 循环次数 (0 为无限循环)。
- `autoPlay`: 是否自启动。
- ElmApi: `play()`, `pause()`, `stop()`, `setIndex(idx)`.

---

### 2.5 动图渲染组件 (`<gif>`)
* **C++ DOM 类**: `JQuick::WXGif` (地址 `0x7d27c0`)
* **说明**: 硬件编解码器直通驱动，绑定 Choreographer 刷新循环。
- 属性: `src`, `autoPlay`, `repeatCount`.
- 事件: `animationEnd`.

---

### 2.6 单行输入框 (`<input>`)
* **C++ DOM 类**: `JQuick::WXInput`
* **原生 View 类**: `greenui::EditText`
* **说明**: 挂载系统软键盘面板（IMPanel 10200 层），支持光标渲染与 IME 缓冲。

#### 专有属性
| 属性名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `type` | String | `"text"`, `"password"`, `"number"`, `"tel"`, `"url"` |
| `value` | String | 输入框文字内容 |
| `placeholder` | String | 水印占位符 |
| `placeholderColor` | Color | 占位符颜色 |
| `disabled` | Boolean | 是否禁用输入 |
| `autofocus` | Boolean | 挂载后自动请求输入焦点 |
| `maxLength` | Number | 最大允许字数限制 |
| `cursorColor` | Color | 闪烁光标颜色 |
| `softInputEnable` | Boolean | 是否在获焦时自动呼出系统键盘 |

#### ElmApi 方法
- `focus()`: 激活键盘并聚焦
- `blur()`: 隐藏键盘并失焦
- `setValue(val)`: 直接更新值
- `setSelectionRange(start, end)`: 选中文本区间

#### 事件列表
- `input`: `{ value, cursor }` (实时按键输入)
- `change`: `{ value }` (失焦后提交)
- `confirm` / `return`: 点击键盘“完成”键触发

---

### 2.7 多行文本域 (`<textarea>`)
* **C++ DOM 类**: `JQuick::WXTextarea`
* **原生 View 类**: `greenui::Textarea` (带内置滚动条)
* 属性: `rows` (行数), `maxLength`, `placeholder`.
* 事件: `reachUpperLimit` (达到字数上限告警).

---

### 2.8 高性能触控滚动容器 (`<scroller>`)
* **C++ DOM 类**: `JQuick::WXScroller`
* **原生 View 类**: `greenui::ScrollView`
* **说明**: 词典笔横滑桌面与纵向长文本的核心承载组件。

#### 专有属性与动力学参数
| 属性名 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `scrollDirection` | String | `"vertical"` | 滚动主轴: `"vertical"`, `"horizontal"` |
| `showScrollbar` | Boolean | `true` | 是否展示边缘淡入淡出滚动指示条 |
| `scrollWithAnimation` | Boolean | `true` | 编程式滚动是否启用惯性缓动插值 |
| `scrollAnimationDuration` | Number | `250` | 编程式滚动时长 (ms) |
| `offsetAccuracy` | Number | `10.0` | 派发 `scroll` 事件的最小像素位移步长阈值 |
| `scrollEventInterval` | Number | `16` | 滚动事件节流时限 (ms) |
| `loadmoreoffset` | Number | `0.0` | 触底派发 `loadmore` 的距离阈值 |
| `touchSlop` | Number | `8.0` | 锁定滚动滑动手势的最小判定距离 (8px) |

#### ElmApi 方法
- `scrollTo(x, y, animated)`: 滚动至指定坐标。
- `scrollToElement(ref, animated)`: 自动寻找子节点并将其滚入可视区域。
- `resetLoadmore()`: 重置防抖标记，允许下次触底事件触发。

#### 事件列表
- `scroll`: `{ contentSize: { width, height }, contentOffset: { x, y } }`
- `scrollstart`, `scrollend`
- `scrolltoupper`, `scrolltolower`
- `loadmore`

---

### 2.9 轮播滑块容器 (`<slider>`)
* **C++ DOM 类**: `JQuick::WXSlider`
* **原生 View 类**: `greenui::SliderView`
* 属性: `index` (当前页码), `autoPlay`, `interval`, `showIndicators`, `itemColor`, `itemSelectedColor`.
* 事件: `change: { index }`.

---

### 2.10 硬件级拖动进度滑块 (`<external-slider>` / `<seekbar>`)
* **C++ DOM 类**: `JQuick::WXExternalSlider`
* **原生 View 类**: `greenui::ExternalSlider`
* **说明**: 用于屏幕亮度、系统音量、媒体音频播放进度的拖动条。
- 属性: `value`, `min`, `max`, `step`, `activeColor`, `trackColor`, `handleSize`.
- 事件:
  - `changing: { value, lvalue }` (手指拖动中连续高频触发)
  - `change: { value, lvalue }` (手指松开确认时触发)

---

### 2.11 原生 2D 画布引擎 (`<canvas>`)
* **C++ DOM 类**: `JQuick::WXCanvas`
* **原生 View 类**: `greenui::Canvas` / `SkCanvas`
* **调用接口**: `const ctx = this.$refs.canvas.createCanvasContext();`
* **方法**: `fillRect`, `strokeRect`, `clearRect`, `beginPath`, `moveTo`, `lineTo`, `arc`, `quadraticCurveTo`, `bezierCurveTo`, `fill`, `stroke`, `scale`, `rotate`, `translate`, `fillText`, `draw(reserve)`.

---

### 2.12 富文本排版引擎 (`<richtext>`)
* **C++ DOM 类**: `JQuick::WXRichText`
* **原生 View 类**: `JQuick::RichTextView`
* **支持内嵌标签**: `<span>`, `<p>`, `<h1>` ~ `<h6>`, `<img>`, `<sub>`, `<sup>`, `<del>`, `<latex>`.
* **事件**: `itemclick: { href, refId }`.

---

### 2.13 硬件二维码生成器 (`<qrcode>`)
* **C++ DOM 类**: `JQuick::WXQRCode`
* 属性: `value` (字符内容), `level` (`"L"`, `"M"`, `"Q"`, `"H"`), `color`, `backgroundColor`.
* 事件: `load: { success: true }`.

---

### 2.14 矢量动效引擎 (`<lottie>`)
* **C++ DOM 类**: `JQuick::WXLottie`
* **原生 View 类**: `lottie::LottieAnimationView`
* 属性: `lottieFile` (JSON 动画文件路径), `assetsFolder`, `speed`, `repeatCount`, `autoPlay`.
* ElmApi: `play()`, `pause()`, `stop()`, `setProgress(ratio)`.
* 事件: `animationEnd`.

---

### 2.15 硬件视频直通层 (`<surface>`)
* **C++ DOM 类**: `JQuick::WXSurface`
* **原生 View 类**: `greenui::SurfaceView`
* **说明**: 硬件 DMA 零拷贝层，直连摄像头或 V4L2 视频帧缓冲区。
- 属性: `surfaceId`, `format` (`"NV21"`, `"NV12"`, `"RGB565"`).
- ElmApi: `getSurfaceHandle()`.

---

### 2.16 聚焦镂空遮罩组件 (`<hole>`)
* **C++ DOM 类**: `JQuick::Hole`
* **原生 View 类**: `greenui::HoleView`
* **说明**: 用于新手指引的透明镂空聚焦层，清除底层像素 Alpha。
- 属性: `radius`, `shape` (`"rect"`, `"circle"`).

---

### 2.17 系统级模态弹窗 (`<modal>`)
* **C++ DOM 类**: `JQuick::ModalWindow` (地址 `0x7cb8a4`)
* **原生 View 类**: `greenui::ModalRootView` (Z-Order: `100`)
- 属性: `cancelable` (点击空白处或 Back 键是否退出), `focusable`, `touchPenetration`.
- 事件: `viewappear`, `viewdisappear`, `windowAttachState`.

---

### 2.18 笔尖扫读摄像头直通预览 (`<ocr-preview>`)
* **C++ DOM 类**: `falcon::OCRCameraPreview` (地址 `0x7e8574`)
* **说明**: 硬件 V4L2 摄像头直接映射，支持 60~120 FPS 高速取景。
- 属性: `frameRate`, `autoExposure`, `contrast`.

---

### 2.19 科学公式排版引擎 (`<latex>`)
* **C++ DOM 类**: `JQuick::latex::WXLatex` (地址 `0x7e9c50`)
* **原生 View 类**: `JQuick::latex::LatexView`
* **说明**: 内嵌 `clatexmath` 引擎，将 LaTeX 字符串直接渲染为 Skia 矢量符号。
- 属性: `value` / `tex` (LaTeX 表达式源码), `fontSize`, `color`.

---

## 3. CSS 引擎 73 项白名单与解析器机制

在 `JQuick::CSSStyleParser::CSSStyleParser()`（地址 `0x3ae3e8`）中，系统仅注册了 **73 个样式属性**，其余任何 Web CSS 属性均会被无声丢弃！

### 完整 73 属性白名单分类索引

#### 1. 布局与定位 (Flexbox & Layout) - 24 项
`flexDirection`, `justifyContent`, `alignItems`, `alignSelf`, `alignContent`, `flexWrap`, `flex`, `flexGrow`, `flexShrink`, `flexBasis`, `aspectRatio`, `gap`, `rowGap`, `columnGap`, `width`, `height`, `minWidth`, `maxWidth`, `minHeight`, `maxHeight`, `top`, `bottom`, `left`, `right`.

#### 2. 外边距与内边距 (Margins & Paddings) - 10 项
`margin`, `marginTop`, `marginBottom`, `marginLeft`, `marginRight`, `padding`, `paddingTop`, `paddingBottom`, `paddingLeft`, `paddingRight`.

#### 3. 边框与圆角 (Borders & Corner Radii) - 25 项
`border`, `borderWidth`, `borderStyle`, `borderColor`,  
`borderTop`, `borderTopWidth`, `borderTopStyle`, `borderTopColor`,  
`borderBottom`, `borderBottomWidth`, `borderBottomStyle`, `borderBottomColor`,  
`borderLeft`, `borderLeftWidth`, `borderLeftStyle`, `borderLeftColor`,  
`borderRight`, `borderRightWidth`, `borderRightStyle`, `borderRightColor`,  
`borderRadius`, `borderTopLeftRadius`, `borderTopRightRadius`, `borderBottomLeftRadius`, `borderBottomRightRadius`.

#### 4. 背景与视觉效果 (Backgrounds & Visuals) - 8 项
`backgroundColor`, `backgroundImage`, `backgroundRepeat`, `backgroundPosition`, `backgroundSize`, `opacity`, `visibility`, `boxShadow`.

#### 5. 图层控制与矩阵变换 (Layering & Transforms) - 6 项
`display`, `position`, `overflow`, `zIndex`, `transform`, `transformOrigin`.

---

## 4. Yoga Flexbox 布局模型与带鱼屏几何计算规范

### 4.1 屏幕物理分辨率与逻辑视口映射
- **硬件 LCD 物理规格**: `240` (宽) × `1020` (高) 竖屏，硬件旋转 270°。
- **Falcon 逻辑渲染画布**: **严格必须声明为 `1020px` (宽) × `240px` (高)**。
- **单位缩放关系**:
  - `px`: 物理像素直接映射。
  - `rpx`: 相对像素，缩放基准为 $value \times (\text{viewport\_width} / 750.0) = value \times (1020 / 750) = 1.36 \times value$。

### 4.2 容器与文本防坍塌铁律
1. **Yoga 默认主轴方向为纵向**:
   若要水平排列卡片，父容器必须显式声明：
   ```css
   flex-direction: row;
   ```
2. **绝对定位容器必须声明宽高**:
   在 `position: absolute` 下，如果未指定 `width` 和 `height`，Yoga 计算结果将坍塌为 `0px × 0px`。
3. **文本单行省略黄金三件套**:
   ```css
   lines: 1;
   text-overflow: ellipsis;
   width: 200px; /* 必须给限制宽度，否则不会触发省略 */
   ```

---

## 5. 伪类状态机与样式动态响应 (`:active` & `:focus`)

Falcon 原生引擎仅支持两个伪类：
1. **`:active`**:
   手指触碰屏幕时触发（`ACTION_DOWN`），松开或滑出时还原（`ACTION_UP` / `ACTION_CANCEL`）。
2. **`:focus`**:
   输入框获焦时触发，失焦时还原。

```css
/* 生产级点击反馈示例 */
.action-button {
  width: 140px;
  height: 48px;
  background-color: #007AFF;
  border-radius: 8px;
}

.action-button:active {
  background-color: #0056B3;
  transform: scale(0.96); /* 缩放反馈 */
}
```

---

## 6. 严禁使用的 Web CSS 危险属性与崩溃陷阱

| 危险/不支持属性 | 替代解决方案 / 正确用法 | 违规后果 |
| :--- | :--- | :--- |
| `calc()` 动态计算 | 在 JS 计算属性（Computed）中计算完毕后传入数字 | 解析失败，样式静默丢失 |
| `display: grid` | 使用嵌套 `flex-direction: row` + `flex-direction: column` | 回退为 Flexbox，布局错乱 |
| `white-space: nowrap` | 使用 `<text>` 的 `lines: 1;` 属性 | 属性完全被忽略，文字继续换行 |
| `box-sizing: content-box` | Falcon 强制为 `border-box`，布局请按边框盒计算 | 属性被忽略 |
| `filter: blur(...)` | 使用 `<image>` 的 `blurRadius` 属性 | 属性完全被忽略 |
| `aspectRatio: 0` 或负数 | 必须为正数浮点数（如 `aspectRatio: 1.5;`） | **触发浮点除以零，UI 整体坍塌白屏！** |
| 标签后代选择器 (`div > span`) | 严格使用单一平铺类选择器（如 `.title-text`） | 解析器无法匹配，样式不生效 |
| `em`, `rem`, `pt` 单位 | 仅限使用 `px` 或 `rpx` | 解析失败，尺寸回退为 0 |
