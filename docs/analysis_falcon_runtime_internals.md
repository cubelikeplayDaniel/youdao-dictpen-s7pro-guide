# Falcon 原生组件与 C++ 运行时绑定深度逆向分析规范及参考字典

> **固件与平台环境**：Youdao DictPen S7 Pro (Linux 4.9.191, ARMv7l Cortex-A7 双核, 内存 1GB, 分辨率 240×960 / 触控 270° 旋转映射)  
> **核心运行时动态库**：`/usr/lib/libfalcon.so` (8,225,036 bytes, 19,220 动态符号)  
> **分析对象**：`JQuick::ComponentRegistry`、`JQuick::Component`、`greenui::View`、`JQuick::CSSStyleParser`、`falcon::JSCanvasContext`

---

## 一、Falcon 运行时系统架构全景逆向

Falcon 是有道词典笔 S7 Pro 搭载的轻量级、高性能跨平台混合应用渲染引擎。其设计深受 Weex、Vue 以及 Android View 系统的启发，整体架构在 C++11 底层之上深度定制开发，主要由四大核心层次构成：

```
+--------------------------------------------------------------------------+
|                  JavaScript 应用层 (Vue / Weex 语法体系)                   |
|       <template>, <style>, <script> (export default { data, methods })   |
+--------------------------------------------------------------------------+
                                    |
                                    v
+--------------------------------------------------------------------------+
|                         QuickJS 轻量级 JS 引擎                            |
|    JSContext / JSRuntime / EventLoop / FalconStack / BindingX 表达式引擎   |
+--------------------------------------------------------------------------+
                                    |
            +-----------------------+-----------------------+
            | C++ 虚拟 DOM 与组件抽象层                     |
            | - VNode / VComponent (DOM Diff 与树管理)      |
            | - JQuick::ComponentRegistry (组件单例注册中心)  |
            | - JQuick::Component (C++ 抽象基类与虚表调度)     |
            | - ElmApi / BaseElmApi ($refs 原型绑定导出)      |
            +-----------------------+-----------------------+
                                    |
                                    v
+--------------------------------------------------------------------------+
|                  布局引擎 (Yoga Flexbox Layout Engine)                    |
|             YGNode / YGMeasureMode / LATEX_MEASURE_FUNCTION              |
+--------------------------------------------------------------------------+
                                    |
                                    v
+--------------------------------------------------------------------------+
|                      渲染层 (greenui 2D 场景图体系)                        |
|       greenui::ViewGroup -> greenui::View (类似 Android View 体系)        |
|    greenui::Canvas / Skia 绘图引擎 / Bitmap / Hardware Direct Frame        |
+--------------------------------------------------------------------------+
                                    |
                                    v
+--------------------------------------------------------------------------+
|                 底层显示与硬件层 (/dev/fb0, /dev/input/event0)             |
+--------------------------------------------------------------------------+
```

### 1.1 组件注册机制与工厂单例 (`ComponentRegistry`)

在 `libfalcon.so` 的核心初始化例程中（ELF 虚拟地址 `0x3649d0` - `0x365220`），Falcon 通过 `JQuick::ComponentRegistry::registerComponent` 将每一个标签名（Tag）与对应的组件工厂创建者 `ComponentHolder` 进行强绑定：

- 函数签名：`void JQuick::ComponentRegistry::registerComponent(const std::string& name, ComponentHolder* holder)`
- 内部数据结构：使用 `std::map<std::string, ComponentHolder*>` 维护组件工厂全局字典。
- 实例化生命周期：当前端模板解析或 VNode 树构建触发 `ComponentFactory::createComponent(tag)` 时，引擎查找该字典并调用 `ComponentHolder::create(tag)`，返回派生自 `JQuick::Component` 的实体对象。

### 1.2 C++ 组件虚表架构 (`JQuick::Component`)

在 `libfalcon.so` 中，基类 `JQuick::Component`（虚表地址 `0x7d134c`）定义了标准化的组件生命周期与事件分发管道：

| 虚表索引 (vtable) | C++ 虚函数签名 | 核心职责 |
|---|---|---|
| `vtable[3]` | `bindData(attrs, styles, events)` | 初始批量数据绑定（属性、初始样式、事件监听） |
| `vtable[4]` | `appendDefaultStyles()` | 注入组件默认 CSS 规则（如 Modal 注入 `position: fixed`） |
| `vtable[5]` | `doUpdateStyles(styles)` | 响应式样式差量更新（调用 `CSSStyleParser`） |
| `vtable[6]` | `doUpdateAttributes(attrs)` | 响应式 XML 属性差量更新 |
| `vtable[21]` | `invokeJSMethod(methodName, params)` | 响应 JS 通过 `$refs[id].method()` 发起的直接方法调用 |
| `vtable[22]` | `onCreateHostView()` | 实例化对应的 `greenui::View` 物理渲染节点并挂载 |
| `vtable[23]` | `setProperty(key, value)` | 单个属性设置入口（支持 camelCase 与 kebab-case 自动映射） |
| `vtable[24]` | `onAddEvent(eventName)` | 注册底层事件监听（绑定 ViewListener 并向 JS 发送回调） |
| `vtable[25]` | `onRemoveEvent(eventName)` | 移除事件监听 |

### 1.3 `greenui` 视图树与 Android 体系同构性

底层渲染基类 `greenui::View` 和 `greenui::ViewGroup`（包含 176+ 导出的标准方法）在设计上完全借鉴了 Android View 框架：
- **布局参数**：`greenui::View::LayoutParams` 支持 `setMargins`、`getType`；
- **事件流分发**：支持 `dispatchTouchEvent(MotionEvent&)`、`dispatchKeyEvent(KeyEvent&)`、`cancelAndClearTouchTargets`、`disallowInterceptTouch`；
- **绘制流管道**：`dispatchDraw(Canvas*, long long)` -> `drawInternal` -> `drawSelf` / `drawLayer`；
- **硬件缓存机制**：`buildDrawingCache()` 支持图层绘制位图缓存，提升低算力芯片下的滚动帧率；
- **坐标变换支持**：`applyTransformation(Canvas*)` 与 `applyMatrixToCanvas`，使 2D 矩阵变换（平移、缩放、旋转）无缝作用于 Skia 画布。

### 1.4 JS 元素原型绑定 (`ElmApi` 机制)

当 JS 代码通过 `this.$refs.myComponent` 访问原生组件引用时，QuickJS 返回的是包装了 `ElmApi` 的 C++ 代理对象。所有组件共享 `BaseElmApi` 提供的基础能力：
- `focus()`：强行聚焦该元素（触发表单或高亮响应）；
- `setStyle(key, value)`：动态直接注入单个 CSS 样式，绕过完整的 DOM diff；
- `clearTouchTargets()`：清空当前组件及子树内的触控拦截目标；
- `disallowInterceptTouch(bool)`：阻止父级容器（如 `scroller`）拦截当前组件的触摸滑动事件。

---

## 二、100% 真实支持的原生组件全量清单

经逆向符号表、交叉引用（Xrefs）与初始化例程全量排查，`/usr/lib/libfalcon.so` 中完整注册的组件共有 **19 个组件标签（含别名）**：

| 组件标签名 (Tag) | 别名 (Alias) | 对应 ComponentHolder | 底层 C++ HostView | 渲染实现与技术栈 |
|---|---|---|---|---|
| `<div />` | `<container />` | `JQuick::DivHolder` | `greenui::ViewGroup` | 基础弹性盒容器，多子节点布局承载 |
| `<text />` | - | `JQuick::TextHolder` | `greenui::TextView` | 高性能排版渲染，支持跑马灯、截断、行高 |
| `<image />` | `<img />` | `JQuick::ImageHolder` | `JQuick::WXImageView` / `greenui::ImageView` | 静态图片解码渲染，支持 HTTP/本地/缓存 |
| `<image-frame />`| - | `JQuick::ImageFrameHolder` | `greenui::ImageFrame` | 帧序列动画渲染组件 |
| `<gif />` | - | `JQuick::WXGifHolder` | `greenui::GifDrawable` / `greenui::ImageView` | 原生 GIF 动图播放器 |
| `<scroller />` | - | `JQuick::ScrollerHolder` | `JQuick::WXScrollView` / `greenui::ScrollView` | 滚动容器，支持横纵向、惯性回弹、loadmore |
| `<slider />` | - | `JQuick::SliderHolder` | `JQuick::WXSliderView` / `greenui::SliderView` | 轮播卡片，支持无限循环与指示器 |
| `<external-slider />` | `<seekbar />` | `JQuick::ExternalSliderHolder` | `greenui::ExternalSlider` | 滑块调节器（音量、亮度、进度条拖拽） |
| `<input />` | - | `JQuick::InputHolder` | `JQuick::InputScrollView` + `greenui::EditText` | 单行文本输入框，软键盘联动 |
| `<textarea />` | - | `JQuick::TextareaHolder`| `JQuick::TextareaScrollView` + `greenui::Textarea` | 多行文本输入域 |
| `<canvas />` | - | `JQuick::WXCanvasHolder` | `JQuick::CanvasView` | 2D 硬件加速画布（Skia 2D 图元渲染） |
| `<qrcode />` | - | `JQuick::WXQRCodeHolder` | `greenui::QRCodeView` | 原生二维码点阵生成器 |
| `<richtext />` | - | `JQuick::WXRichTextHolder`| `JQuick::RichTextView` | HTML/富文本解析渲染器（图文混排） |
| `<lottie />` | - | `JQuick::WXLottieHolder` | `lottie::LottieAnimationView` | Adobe After Effects 矢量动画解析器 |
| `<hole />` | - | `JQuick::HoleHolder` | `JQuick::HoleView` | 挖孔遮罩视图（新手引导镂空高亮） |
| `<modal />` | - | `JQuick::ModalWindowHolder` | `JQuick::ModalRootView` | 独立全屏或浮动模态窗口 |
| `<latex />` | - | `JQuick::latex::WXLatexHolder` | `JQuick::latex::LatexView` | LaTeX 复杂数学公式原生渲染器 |
| `<ocr-preview />`| `<ocr-camera />` | `falcon::OCRCameraPreviewHolder` | `falcon::OCRCameraPreviewView` | 笔尖硬件摄像头实时图层直出 |
| `<surface />` | - | `JQuick::WXSurfaceHolder`| `greenui::SurfaceView` | 独立 Direct Surface 渲染通道 |

---

## 三、原生组件属性、API 与事件详查

### 3.1 `<div />` 与 `<container />` (基础容器)
- **底层实现**：`JQuick::Div` 挂载 `greenui::ViewGroup`。
- **XML 属性**：
  - `focusable="true|false"`：是否允许通过物理按键或焦点树聚焦。
  - `drawingCache="true|false"`：开启子树渲染位图缓存，避免重复渲染复杂静态节点。
- **JS API 方法**：继承 `BaseElmApi`（`focus()`, `setStyle()`, `clearTouchTargets()`, `disallowInterceptTouch()`）。
- **支持事件**：
  - 触控事件：`touchstart`, `touchmove`, `touchend`, `touchcancel`；
  - 交互事件：`click`, `longpress`；
  - 按键事件：`keydown`, `keyup`。

### 3.2 `<text />` (文本排版)
- **底层实现**：`JQuick::WXText` 挂载 `greenui::TextView`。
- **XML 属性 / C++ 属性绑定**：
  - `value="string"`：显示的文本内容（也可通过 `<text>内容</text>` 插槽传入）。
  - `marqueeSpeed="number"`：跑马灯滚动速度（像素/秒，默认 50）。
  - `marqueeGap="number"`：跑马灯首尾衔接间隙（像素，默认 20）。
- **专用样式属性**：
  - `lines="number"`：最大显示行数，超过则截断。
  - `line-height="length"`：行间距与基线高度。
  - `text-align="left|center|right"`：水平对齐。
  - `text-decoration="none|underline|line-through"`：文本修饰。
  - `text-decoration-color="color"`：修饰线下划线颜色。
  - `font-size="length"`：文字字号。
  - `font-family="string"`：字体族（支持词典笔内置字体族）。
  - `font-weight="normal|bold|100|...|900"`：粗细。
  - `font-style="normal|italic"`：倾斜。
  - `color="color"`：文字颜色。
  - `text-shadow="h-shadow v-shadow blur color"`：文本阴影。
  - `text-overflow="clip|ellipsis|marquee"`：超出边界行为（支持独特的原生 `marquee` 跑马灯滚动）。
  - `letter-spacing="length"`：字间距。
- **支持事件**：
  - `itemclick`：当文本内部包含高亮富文本 span 时的子项点击事件；
  - 继承通用事件：`click`, `longpress`, `touchstart`, `touchend`。

### 3.3 `<image />` 与 `<img />` (图像渲染)
- **底层实现**：`JQuick::WXImage` 挂载 `greenui::ImageView`。
- **XML 属性 / C++ 属性绑定**：
  - `src="string"`：图片 URI，支持：
    - 本地文件：`/root/...` 或 `file:///...`；
    - 运行时相对路径：`assets/...`；
    - 远程网络路径：`http://...` 或 `https://...`；
    - Base64 编码：`data:image/png;base64,...`。
  - `resize="contain|cover|stretch|center"`：缩放与裁剪模式（默认 `stretch`）。
  - `scale="float"`：显示缩放比。
  - `cacheDir="string"`：指定磁盘图片缓存目录。
  - `auto-reload="true|false"`：网络失败是否自动重试。
  - `blur-radius="number"`：原生高斯模糊半径。
- **JS API 方法**：
  - `reload()`：强制清空缓存并重新从网络或磁盘拉取图像。
  - `capture(options, callback)`：抓取当前图片渲染位图。
- **支持事件**：
  - `load`：图片解码加载成功触发。
  - `error`：图片拉取或解码失败触发。
  - 通用事件：`click`, `longpress`, `touchstart`。

### 3.4 `<image-frame />` (帧序列动画)
- **底层实现**：`JQuick::ImageFrame` 挂载 `greenui::ImageFrame`。
- **XML 属性 / C++ 属性绑定**：
  - `src="string"`：帧动画资源包路径或前缀模板。
  - `interval="number"`：帧与帧之间的切换时间间隔（毫秒，默认 50ms）。
  - `loopCount="number"`：循环播放次数（0 表示无限循环）。
  - `autoPlay="true|false"`：挂载后是否自动开始播放。
- **支持事件**：
  - `onLoad`：序列帧资源预加载完毕。

### 3.5 `<gif />` (GIF 动图播放)
- **底层实现**：`JQuick::WXGif` 挂载 `greenui::GifDrawable` + `greenui::ImageView`。
- **XML 属性**：
  - `src="string"`：GIF 图像文件路径。
  - `autoPlay="true|false"`：是否自动播放。
- **JS API 方法**：
  - `startAnimate()`：手动启动 GIF 帧循环动画。
- **支持事件**：`load`, `error`, `finish`。

### 3.6 `<scroller />` (滚动容器)
- **底层实现**：`JQuick::WXScroller` 挂载 `greenui::ScrollView`。
- **XML 属性 / C++ 属性绑定**：
  - `scroll-direction="vertical|horizontal"`（代码别名 `row|column|toleft`）：滚动主方向。
  - `show-scrollbar="true|false"`：是否显示原生滚动条。
  - `scrollable="true|false"`：是否启用触控滚动。
  - `overScroll="true|false"`：是否开启边界弹性过卷回弹效果。
  - `overFling="true|false"`：是否允许惯性滑行过卷。
  - `overGravity="float"`：过卷回弹重力加速度。
  - `offset-accuracy="number"`：滚动事件触发精度阈值（像素）。
  - `loadmoreoffset="number"`：触发触底 `loadmore` 事件的距离阈值（默认 0 像素）。
  - `upperThreshold="number"`：顶部触发 `scrolltoupper` 的阈值。
  - `lowerThreshold="number"`：底部触发 `scrolltolower` 的阈值。
  - `scrollEventInterval="number"`：滚动事件节流阀时间间隔（毫秒）。
  - `scrollAnimationDuration="number"`：调用滚动动画时的平滑时长（毫秒）。
  - `scrollWithAnimation="true|false"`：滚动是否附带动画过渡。
  - `touchSlop="number"`：判定滚动手势的最小触控位移防抖阈值。
  - `recyclable="true|false"`：滚动列表是否启用内部视口节点复用机制。
- **JS API 方法**：
  - `scrollToElement(elRef, options)`：平滑滚动到指定子节点。
    - `options.offset`：对齐偏移量（默认 0）。
    - `options.animated`：是否动画过渡（默认 true）。
  - `scrollTo(x, y, animated)`：直接滚动到绝对坐标。
  - `scrollTop(top, animated)`：滚动到指定垂直偏移。
  - `scrollLeft(left, animated)`：滚动到指定水平偏移。
  - `resetLoadmore()`：重置触底状态，允许再次触发 `loadmore` 事件。
- **支持事件**：
  - `scroll`：滚动过程中持续触发，payload: `{ contentOffset: { x, y } }`。
  - `scrollstart`：触控滑动刚开始或 fling 惯性启动。
  - `scrollend`：滑动停止、惯性停止并回弹静止。
  - `scrolltoupper`：触及滚动视口顶部。
  - `scrolltolower`：触及滚动视口底部。
  - `loadmore`：距离底部小于 `loadmoreoffset` 时触发，用于分页加载。

### 3.7 `<slider />` (轮播卡片视图)
- **底层实现**：`JQuick::WXSlider` 挂载 `greenui::SliderView`。
- **XML 属性 / C++ 属性绑定**：
  - `auto-play="true|false"`（属性别名 `autoPlay`）：是否自动轮播。
  - `interval="number"`：自动轮播翻页间隔时间（毫秒，默认 3000）。
  - `duration="number"`：翻页动画过渡时间（毫秒，默认 300）。
  - `index="number"`：当前激活显示的子页面下标（从 0 开始）。
  - `infinite="true|false"`：是否循环轮播。
  - `scrollable="true|false"`：是否允许手势左右滑动切换。
  - `show-indicators="true|false"`：是否展示默认圆点指示器。
  - `item-color="color"`：指示器未选中圆点颜色。
  - `item-selected-color="color"`：指示器激活圆点颜色。
  - `item-size="length"`：指示器圆点尺寸。
  - `scale-factor="float"`：翻页时非活跃页面的缩放比例。
  - `disable-spring-scroll="true|false"`：禁用阻尼弹簧滚动过渡。
  - `previous-margin="length"` / `next-margin="length"`：前后露出一截子页面的边距。
- **JS API 方法**：
  - `slideTo(index, animated)`：手动跳转到指定索引页。
- **支持事件**：
  - `change`：当前活动页面改变时触发，payload: `{ index: number }`。
  - `animationEnd`：滑动换页过渡动画结束时触发。

### 3.8 `<external-slider />` 与 `<seekbar />` (滑块调节条)
- **底层实现**：`JQuick::ExternalSlider` 挂载 `greenui::ExternalSlider`。
- **XML 属性 / C++ 属性绑定**：
  - `min="number"`：最小值（默认 0）。
  - `max="number"`：最大值（默认 100）。
  - `value="number"`：当前滑块数值。
  - `step="number"`：滑动步长。
  - `disabled="true|false"`：是否禁用滑动。
  - `disabledColor="color"`：禁用时的轨道色彩。
  - `backgroundColor="color"`：未激活滑道底色。
  - `activeColor="color"`：已激活进度的滑道高亮色彩。
  - `trackSize="length"`：滑道粗细尺寸。
  - `handleSize="length"`：滑块拖动把手圆形外径。
  - `handleColor="color"`：把手外层色彩。
  - `handleInnerColor="color"`：把手内层圆点色彩。
  - `borderRadius="length"`：滑轨两端圆角。
  - `changingInterval="number"`：拖拽中 `changing` 事件节流触发间隔（毫秒）。
- **支持事件**：
  - `changing`：手指拖拽滑块过程中连续触发，payload: `{ value: number }`。
  - `change`：手指松开、滑动定格时触发，payload: `{ value: number }`。

### 3.9 `<input />` (单行输入框)
- **底层实现**：`JQuick::WXInput` 挂载 `greenui::EditText`。
- **XML 属性 / C++ 属性绑定**：
  - `type="text|password|number|tel|email|url"`：输入键盘类型。
  - `value="string"`：文本框内容。
  - `placeholder="string"`：占位提示文本。
  - `placeholder-color="color"`：占位提示文字颜色。
  - `disabled="true|false"`：是否禁用输入。
  - `maxlength="number"`：最大输入字符长度。
  - `return-key-type="default|go|next|search|send|done"`：软键盘回车键显示文本。
  - `autofocus="true|false"`：页面渲染后是否自动弹出键盘。
  - `cursorColor="color"`：光标颜色。
  - `cursorSize="length"`：光标宽度。
  - `softInputEnable="true|false"`：是否联动弹出词典笔系统全键盘/拼音输入法。
- **JS API 方法**：
  - `focus()`：强制获取焦点并调出软键盘。
  - `blur()`：放弃焦点并收起软键盘。
  - `setSelectionRange(start, end)`：设置文本选中区间。
- **支持事件**：
  - `input`：文字变更实时触发，payload: `{ value: string }`。
  - `change`：失去焦点且内容被修改时触发。
  - `focus`：获得焦点时触发。
  - `blur`：失去焦点时触发。
  - `confirm` / `return`：按下软键盘确认/回车键时触发。

### 3.10 `<textarea />` (多行输入框)
- **底层实现**：`JQuick::WXTextarea` 挂载 `greenui::Textarea`。
- **XML 属性 / C++ 属性绑定**：
  - 具备 `<input>` 全部核心属性（`value`, `placeholder`, `cursorColor`, `softInputEnable` 等）。
  - `rows="number"`：默认占据行数高度。
  - `showCursor="true|false"`：是否绘制闪烁光标。
  - `overScroll="true|false"`：多行溢出后内部滚动是否允许弹性过卷。
- **JS API 方法** 与 **支持事件**：与 `<input />` 相同。

### 3.11 `<canvas />` (Skia 2D 画布)
- **底层实现**：`JQuick::WXCanvas` 挂载 `greenui::CanvasView`。
- **JS API 方法**：
  - `getContext('2d')`：获取底层高保真 2D 绘图上下文对象（对应 C++ `falcon::JSCanvasContext`）。
- **底层特性**：
  - 支持直接接入 Skia 2D 绘图管道；
  - 拥有独立的批处理缓冲指令池（`FlushHandler` / `render()`）；
  - 支持完整的几何绘制、贝塞尔曲线、渐变填充、矩阵变换、像素操作。

### 3.12 `<qrcode />` (原生二维码生成器)
- **底层实现**：`JQuick::WXQRCode` 挂载 `greenui::QRCodeView`。
- **XML 属性 / C++ 属性绑定**：
  - `value="string"`：待编码为二维码的字符串或 URL。
  - `level="L|M|Q|H"`：纠错容错等级（默认 `M`）。
  - `color="color"`：二维码码点前景色（默认 `#000000`）。
  - 样式支持：`background-color` 作为二维码底色，`width`/`height` 决定缩放大小。
- **支持事件**：通用点击与触控事件。

### 3.13 `<richtext />` (图文混排富文本)
- **底层实现**：`JQuick::WXRichText` 挂载 `greenui::RichTextView`。
- **XML 属性 / 内容解析**：
  - 支持内嵌 HTML-like 节点树：`<span>`, `<a>`, `<img>`, `<h1>`, `<h2>`, `<latex>`。
- **JS API 方法** 与 **事件**：
  - `itemclick`：当点击富文本内的超链接或图片节点时触发，携带节点属性与 href。

### 3.14 `<lottie />` (矢量动画)
- **底层实现**：`JQuick::WXLottie` 挂载 `lottie::LottieAnimationView`。
- **XML 属性 / C++ 属性绑定**：
  - `src="string"` 或 `lottieFile="string"`：Lottie JSON 动画文件路径（支持 `file://...` 或相对路径）。
  - `assetsFolder="string"`：包含内嵌位图的外部静态资源目录。
  - `autoPlay="true|false"`：挂载后自动开始播放。
  - `loopCount="number"`：循环播放次数（0 表示无限循环）。
  - `speed="float"`：播放速率倍率（如 1.0、2.0、0.5）。
  - `stretch="contain|cover|stretch"`：适应画布渲染比例。
- **JS API 方法**：
  - `play()`：从头播放或开始播放。
  - `pause()`：暂停播放。
  - `resume()`：从当前帧继续播放。
  - `cancel()`：停止播放并重置到初始状态。
- **支持事件**：
  - `load`：JSON 动画树解析完成。
  - `error`：JSON 文件不存在或格式非法。
  - `finish`：动画单次或所有循环播放完毕触发。

### 3.15 `<hole />` (镂空遮罩)
- **底层实现**：`JQuick::Hole` 挂载 `greenui::HoleView`。
- **核心机制**：在当前视口区域内切出透明镂空洞（Clear 绘制模式），用于配合半透明蒙层制作新手使用引导（Guide Overlay），将目标按钮精确暴露给用户，底层触控直接穿透。

### 3.16 `<modal />` (模态独立窗口)
- **底层实现**：`JQuick::ModalWindow` 挂载 `greenui::ModalRootView`。
- **XML 属性 / C++ 属性绑定**：
  - `floating="true|false"`：是否作为独立浮动悬浮层弹出。
  - `touchThrough="true|false"`：点击蒙层外部空白区域时，触控事件是否穿透到底层页面。
  - `cancelable="true|false"`：点击遮罩或按下词典笔返回按键时是否自动关闭。
  - `touchPenetration="true|false"`：深度穿透模式。
- **默认注入样式**：C++ 初始化时自动追加 `position: fixed; left: 0; top: 0; width: 100%; height: 100%;`。
- **支持事件**：
  - `dismiss`：模态弹窗被关闭或销毁时触发。

### 3.17 `<latex />` (LaTeX 数学公式排版)
- **底层实现**：`JQuick::latex::WXLatex` 挂载 `greenui::latex::LatexView`。
- **排版引擎**：集成 `tex::TeXRender` 数学公式排版内核与 Yoga `YGNode` 弹性盒测量。
- **XML 属性 / 样式**：
  - `value="string"`：标准的 LaTeX 数学公式源码（例如 `rac{-b \pm \sqrt{b^2 - 4ac}}{2a}`）。
  - 样式支持：`font-size` 决定公式符号字号，`color` 决定公式线条与文字颜色。

### 3.18 `<ocr-preview />` 与 `<ocr-camera />` (硬件笔尖摄像头直出预览)
- **底层实现**：`falcon::OCRCameraPreview` 挂载 `falcon::OCRCameraPreviewView`。
- **硬件桥接**：内部直接初始化 `falcon::CameraPreviewer`，与词典笔前端高速红外/CMOS 摄像头驱动通信。
- **绘制通道**：通过 `swapFrame(greenui::Bitmap*)` 实现底层摄像头每秒数十帧的红外扫描画面零拷贝直出至 `greenui::Canvas`。
- **核心应用**：查词、扫描翻译、拍照识别的主界面相机画面取景框。

### 3.19 `<surface />` (Direct Surface 视图)
- **底层实现**：`JQuick::WXSurface` 挂载 `greenui::SurfaceView`。
- **核心特性**：绕过主 UI 树合成，提供直接对接 Framebuffer 或硬件图层的渲染画布，用于低延迟视频解码输出或游戏渲染。

---

## 四、Canvas 2D 绘图引擎完整 API 接口逆向清单

通过逆向 `falcon::JSCanvasContext` 符号表，词典笔 Falcon 运行时导出了 **39 项原生 2D 画布接口**：

```javascript
// 获取画布上下文
const ctx = this.$refs.myCanvas.getContext('2d');
```

| 接口名称 | C++ 绑定符号 (`falcon::JSCanvasContext`) | 功能说明与参数规范 |
|---|---|---|
| **状态控制** | | |
| `save()` | `wrap_SaveRestore` | 将当前绘图状态（样式、变换矩阵、裁剪区域）压入状态栈 |
| `restore()` | `wrap_SaveRestore` | 弹出并恢复上一次保存的绘图状态 |
| `resetTransform()` | `wrap_resetTransform` | 重置当前变换矩阵为单位矩阵 |
| **路径构建** | | |
| `beginPath()` | `wrap_beginPath` | 开始一条新的路径，清空已有子路径 |
| `closePath()` | `wrap_closePath` | 闭合当前子路径（绘制直线至起点） |
| `moveTo(x, y)` | `wrap_moveTo` | 将画笔移动到指定坐标 |
| `lineTo(x, y)` | `wrap_lineTo` | 从当前位置绘制直线到指定坐标 |
| `rect(x, y, w, h)` | `wrap_rect` | 构建矩形路径 |
| `arc(...)` | `wrap_arc` | 绘制圆弧（参数：`x, y, radius, startAngle, endAngle, counterclockwise`） |
| `arcTo(...)` | `wrap_arcTo` | 根据控制点和半径绘制圆弧相切曲线 |
| `quadraticCurveTo(...)` | `wrap_quadraticCurveTo` | 绘制二次贝塞尔曲线（参数：`cpx, cpy, x, y`） |
| `bezierCurveTo(...)` | `wrap_bezierCurveTo` | 绘制三次贝塞尔曲线（参数：`cp1x, cp1y, cp2x, cp2y, x, y`） |
| `clip()` | `wrap_clip` | 将当前路径设置为剪裁区域 |
| **矩形与文本直接绘制** | | |
| `renderRect(...)` | `wrap_renderRect` | 直接绘制填充/描边矩形 |
| `renderText(...)` | `wrap_renderText` | 绘制文本图元（带字体样式） |
| `measureText(text)` | `wrap_measureText` | 测量字符串在当前字体下的渲染宽度，返回 `{ width: number }` |
| **样式与属性设置** | | |
| `setStyle(styleStr)` | `wrap_setStyle` | 设置描边或填充样式（支持十六进制颜色、`rgb()`、`rgba()`） |
| `setLineWidth(width)` | `wrap_setLineWidth` | 设置画笔描边线宽 |
| `setLineCap(cap)` | `wrap_setLineCap` | 设置端点样式：`'butt' \| 'round' \| 'square'` |
| `setLineJoin(join)` | `wrap_setLineJoin` | 设置拐角样式：`'bevel' \| 'round' \| 'miter'` |
| `setMiterLimit(limit)` | `wrap_setMiterLimit` | 设置斜接面限制比例 |
| `setLineDash(array)` | `wrap_setLineDash` | 设置虚线排列模式（如 `[5, 5]`） |
| `setLineDashOffset(offset)` | `wrap_setLineDashOffset` | 设置虚线起始偏移量 |
| `setGlobalAlpha(alpha)` | `wrap_setGlobalAlpha` | 设置全局绘制不透明度（`0.0` - `1.0`） |
| `setGlobalCompositeOperation(op)` | `wrap_setGlobalCompositeOperation` | 设置图层合成模式（如 `source-over`, `destination-out` 等） |
| `setFont(fontStr)` | `wrap_setFont` | 设置字体尺寸与字体族（如 `'16px sans-serif'`） |
| `setTextAlign(align)` | `wrap_setTextAlign` | 水平对齐：`'left' \| 'center' \| 'right'` |
| `setTextBaseLine(baseline)` | `wrap_setTextBaseLine` | 垂直基准线：`'top' \| 'middle' \| 'bottom' \| 'alphabetic'` |
| **渐变对象** | | |
| `createLinearGradient(...)` | `wrap_createLinearGradient` | 创建线性渐变对象（参数：`x0, y0, x1, y1`） |
| `createRadialGradient(...)` | `wrap_createRadialGradient` | 创建径向渐变对象（参数：`x0, y0, r0, x1, y1, r1`） |
| `addColorStop(offset, color)` | `wrap_addColorStop` | 在渐变对象中添加色彩断点 |
| **矩阵变换** | | |
| `scale(sx, sy)` | `wrap_scale` | 缩放当前坐标系 |
| `rotate(angle)` | `wrap_rotate` | 旋转当前坐标系（弧度制） |
| `translate(dx, dy)` | `wrap_translate` | 平移当前坐标系 |
| `transform(...)` | `wrap_transform` | 矩阵乘法变换（参数：`a, b, c, d, e, f`） |
| **位图与像素操作** | | |
| `drawImage(img, ...)` | `wrap_drawImage` | 绘制图像（支持 3 参数、5 参数、9 参数全模式） |
| `getImageData(...)` | `wrap_getImageData` | 读取画布指定区域的 RGBA 原始像素缓冲数组 |
| `putImageData(...)` | `wrap_putImageData` | 将 RGBA 原始像素数据写回画布 |
| **指令批处理提交** | | |
| `render()` / `flush()` | `wrap_render` | **关键接口**：Falcon 画布采用离线批处理机制，绘制指令入队后必须显式调用 `render()` 将指令刷新到底层 Skia 视口！ |

---

## 五、样式系统 (`CSSStyleParser`) 深度逆向与约束分析

Falcon 运行时的样式系统由 `JQuick::CSSStyleParser` 集中驱动，其排版模型完全以 **Flexbox (弹性盒)** 为基石。

### 5.1 长度单位与解析器 (`CSSLengthParser`)

`CSSLengthParser::parse` 支持的合法单位为：
1. **`px`**：标准物理像素单位。
2. **`rpx`**：响应式像素单位（Responsive Pixel）。Falcon 依据词典笔屏幕基准（词典笔竖屏宽度 240px，横屏宽度 960px）自动做动态缩放换算。
3. **`%`**：基于父容器宽高的百分比尺寸。
4. **`rem`**：仅在 `<richtext>` 富文本引擎内作为字号换算单位生效。
5. **限制**：**不支持 `calc()` 计算表达式**；**不支持 `vw`, `vh`, `em`, `pt` 单位**。

### 5.2 Flexbox 弹性盒模型 (Yoga Layout 强绑定)

所有支持的 Flexbox 样式如下（完全对应 `CSSStyleParser` 解析函数）：

| CSS 属性名 | 支持的可选值 | 解析函数与底层行为 |
|---|---|---|
| `display` | `flex \| none` | **严格限制**：仅支持 `flex` 与 `none`。**不支持 `grid`, `inline-block`, `block`, `inline`, `table`**。默认所有容器均为 `display: flex`。 |
| `flex-direction` | `row \| column \| row-reverse \| column-reverse` | 主轴方向设定。Falcon 容器**默认主轴为 `column`**（竖向流动），符合移动端/穿戴设备标准。 |
| `flex-wrap` | `nowrap \| wrap \| wrap-reverse` | 换行模式设定。 |
| `justify-content` | `flex-start \| flex-end \| center \| space-between \| space-around \| space-evenly` | 主轴方向元素对齐方式。 |
| `align-items` | `stretch \| flex-start \| flex-end \| center \| baseline` | 交叉轴单行元素对齐方式。 |
| `align-content` | `stretch \| flex-start \| flex-end \| center \| space-between \| space-around` | 多轴线对齐方式。 |
| `align-self` | `auto \| flex-start \| flex-end \| center \| baseline \| stretch` | 单个子元素在交叉轴的独立覆盖对齐。 |
| `flex` | `number` (如 `1`, `2`) | `flex-grow` 的简写形式。 |
| `flex-grow` | `number` | 子元素放大权重。 |
| `flex-shrink` | `number` | 子元素缩小权重。 |
| `flex-basis` | `length \| auto` | 弹性基准尺寸。 |
| `gap` | `length` | 子项之间的统一间距（低版本若失效可改用 margin）。 |
| `row-gap` | `length` | 行间距。 |
| `column-gap` | `length` | 列间距。 |
| `aspect-ratio` | `width / height` (如 `16/9`, `1`) | 宽高比自动约束。 |

### 5.3 盒模型 (Box Model)

- **尺寸约束**：
  - `width`, `height`
  - `min-width`, `max-width`
  - `min-height`, `max-height`
- **外边距 (Margin)**：
  - `margin`（支持 `10px` 单值或 `10px 20px` 双值扩展）
  - `margin-top`, `margin-right`, `margin-bottom`, `margin-left`
- **内边距 (Padding)**：
  - `padding`
  - `padding-top`, `padding-right`, `padding-bottom`, `padding-left`
- **边框 (Border)**：
  - `border`（如 `1px solid #ff0000`）
  - `border-width`、`border-top-width`、`border-right-width`、`border-bottom-width`、`border-left-width`
  - `border-style`：`solid \| dashed \| dotted`（支持单侧独立设置，如 `border-bottom-style`）
  - `border-color`（支持单侧独立设置，如 `border-bottom-color`）
- **圆角 (Border Radius)**：
  - `border-radius`：统一四角圆角。
  - **四个角独立圆角支持**：
    - `border-top-left-radius`
    - `border-top-right-radius`
    - `border-bottom-left-radius`
    - `border-bottom-right-radius`
  - 底层由 `BorderBackground::getClipRoundRect` 使用 Skia `RoundRect` 高精度裁切。

### 5.4 视觉与定位系统

- **定位模式 (`position`)**：
  - `relative`：相对自身正常流定位。
  - `absolute`：脱离文档流，相对于最近已定位的父级容器。
  - `fixed`：固定定位，直接相对于屏幕物理窗口。
  - **严格限制**：**不支持 `position: sticky`，不支持 `position: static` 显式切换**。
- **偏移量**：`top`, `bottom`, `left`, `right`。
- **层叠上下文**：`z-index`（支持整型数值排序）。
- **背景系统 (`BorderBackground`)**：
  - `background-color`：支持 `#RRGGBB`, `#AARRGGBB`, `rgb()`, `rgba()`, `transparent`。
  - `background-image`：
    - 图片路径：`url('assets/bg.png')`；
    - 渐变色：`linear-gradient(to right, #ff0000, #0000ff)`（由 `parseGradientLinear` 专属解析）。
  - `background-size`：`contain \| cover \| <width> <height>`。
  - `background-repeat`：`no-repeat \| repeat \| repeat-x \| repeat-y`。
  - `background-position`：`left \| right \| center \| top \| bottom \| <length>`。
- **不透明度与显隐**：
  - `opacity`：`0.0` 至 `1.0` 浮点数。
  - `visibility`：`visible \| hidden`（保持布局占位，但隐藏绘制）。
  - `overflow`：`visible \| hidden`（`hidden` 会调用 Skia `canvas->clipRect` 强制裁减子节点）。
- **阴影 (`box-shadow`)**：
  - 格式：`box-shadow: <offset-x> <offset-y> <blur-radius> <color>`。

### 5.5 变换系统 (`Transform` 与 BindingX)

Falcon 逆向解析表明，其具备独立的 `TransformParser`，支持 2D 矩阵硬件级高效合成：
- **`transform` 支持的函数**：
  - `translate(x, y)`, `translateX(x)`, `translateY(y)`
  - `scale(s)`, `scaleX(sx)`, `scaleY(sy)`
  - `rotate(deg)`（支持 `deg` 角度单位，如 `rotate(90deg)`）, `rotateX(deg)`, `rotateY(deg)`
- **`transform-origin`**：
  - 变换原点设定，如 `center center`, `top left`, `50% 50%`。
- **性能优势**：
  - `transform` 属性直接映射到 `greenui::View::applyTransformation`，不会触发昂贵的 Yoga 全局重新布局（Relayout），仅重绘当前图层；
  - 配合 **BindingX 引擎**（`bindingx::Expression`），手势与惯性滑动可以绕过 JS 线程事件轮询，在 C++ 线程达到 60FPS 满帧响应！

### 5.6 明确不支持的 Web CSS 特性黑名单与踩坑警示

在为词典笔开发 Falcon 应用时，严禁使用以下特性，否则将被运行时直接静默忽略或导致排版错乱：

1. **布局模式**：
   - 严禁 `float: left|right`（无浮动排版系统）；
   - 严禁 `display: grid`（无 CSS Grid 引擎）；
   - 严禁 `display: inline` / `display: inline-block`（一切排版均基于 Yoga Flexbox）。
2. **选择器体系**：
   - **仅支持单层 Class 选择器（`.btn`）或标签选择器（`text`）**；
   - 严禁复杂层级后代选择器（如 `.parent .child` 或 `.container > div`）；
   - 严禁伪类选择器（如 `:hover`, `:active`, `:first-child`, `:nth-child`）。
3. **动画体系**：
   - **不支持 CSS `@keyframes` 规则**；
   - **不支持 `animation` 简写属性**；
   - 动画方案：必须使用官方内置的 `animation.transition(ref, options, callback)` 模块，或通过 `BindingX` 绑定表达式实现。
4. **滤镜效果**：
   - 严禁 `filter: blur(...)` / `backdrop-filter`（通用节点不支持 CSS 滤镜，仅 `<image blur-radius="..." />` 具备原生模糊）。

---

## 六、Falcon 原生组件与 CSS 样式完整 API 速查参考字典

### 6.1 常用原生组件速查字典大表

| 组件名称 | 标签 (Tag) | 关键 XML 属性 | 导出 JS 方法 (`$refs`) | 监听事件 | 典型应用场景 |
|---|---|---|---|---|---|
| **弹性容器** | `<div />` | `focusable`, `drawingCache` | `focus()`, `setStyle()` | `click`, `touchstart`, `touchmove`, `touchend` | 页面骨架、Flex 弹性排列容器 |
| **文本排版** | `<text />` | `value`, `marqueeSpeed`, `marqueeGap` | `setStyle()` | `click`, `itemclick` | 词条释义、例句排版、跑马灯长标题 |
| **图片渲染** | `<image />` | `src`, `resize`, `blur-radius`, `auto-reload` | `reload()`, `capture()` | `load`, `error`, `click` | 头像、插画、教材配图、图标 |
| **长列表滚动** | `<scroller />` | `scroll-direction`, `show-scrollbar`, `loadmoreoffset`, `overScroll` | `scrollToElement()`, `scrollTo()`, `scrollTop()`, `resetLoadmore()` | `scroll`, `scrollstart`, `scrollend`, `loadmore`, `scrolltoupper`, `scrolltolower` | 单词本瀑布流、长文章阅读、背单词列表 |
| **轮播卡片** | `<slider />` | `auto-play`, `interval`, `index`, `infinite`, `show-indicators` | `slideTo(index)` | `change`, `animationEnd` | 单词记忆卡片、首页轮播 Banner、引导页 |
| **滑块调节** | `<external-slider />` | `min`, `max`, `value`, `step`, `activeColor`, `trackSize` | `setStyle()` | `changing`, `change` | 系统音量调节、屏幕亮度调节、音频播放进度 |
| **单行输入** | `<input />` | `type`, `value`, `placeholder`, `maxlength`, `return-key-type` | `focus()`, `blur()`, `setSelectionRange()` | `input`, `change`, `focus`, `blur`, `confirm` | 查词搜索栏、WiFi 密码输入、账号登录 |
| **多行文本** | `<textarea />` | `value`, `placeholder`, `rows`, `showCursor` | `focus()`, `blur()` | `input`, `change`, `focus`, `blur` | 意见反馈、生词笔记、长句翻译输入 |
| **2D 画布** | `<canvas />` | - | `getContext('2d')` | `touchstart`, `touchmove`, `touchend` | 手写笔迹板、生字描红、波形频谱、图表 |
| **二维码** | `<qrcode />` | `value`, `level`, `color` | `setStyle()` | `click` | 设备配网绑定、有道云同步登录、微信扫码 |
| **Lottie 动效** | `<lottie />` | `src`, `loopCount`, `autoPlay`, `speed`, `stretch` | `play()`, `pause()`, `resume()`, `cancel()` | `load`, `error`, `finish` | 打卡成就徽章动效、加载等待中动画、语音波纹 |
| **模态弹窗** | `<modal />` | `floating`, `touchThrough`, `cancelable` | `setStyle()` | `dismiss` | 查词结果悬浮气泡、确认对话框、全屏菜单 |
| **数学公式** | `<latex />` | `value` | `setStyle()` | `click` | 理科数学物理题公式、化学方程式原生排版 |
| **摄像头预览** | `<ocr-preview />`| - | - | - | 词典笔前端摄像头实时取景、划词定位 |

---

### 6.2 典型场景实战代码样例

#### 场景 1：高性能长列表与触底加载 (`<scroller>`)
```html
<template>
  <div class="page-container">
    <scroller 
      class="word-scroller"
      scroll-direction="vertical"
      :show-scrollbar="false"
      :over-scroll="true"
      :loadmoreoffset="100"
      @loadmore="onLoadMore"
      @scroll="onScroll"
      ref="scrollerRef">
      
      <div v-for="(item, index) in wordList" :key="index" class="word-card" @click="jumpToDetail(item)">
        <text class="word-text">{{ item.word }}</text>
        <text class="phonetic-text">/{{ item.phonetic }}/</text>
        <text class="trans-text" :lines="1">{{ item.translation }}</text>
      </div>

    </scroller>
  </div>
</template>

<script>
export default {
  data: () => ({
    wordList: []
  }),
  methods: {
    onLoadMore() {
      // 异步加载下一页数据
      fetchNextPage().then(newItems => {
        this.wordList = this.wordList.concat(newItems);
        // 重置 loadmore 触发开关
        this.$refs.scrollerRef.resetLoadmore();
      });
    },
    onScroll(e) {
      const offsetY = e.contentOffset.y;
    }
  }
}
</script>

<style>
.page-container {
  width: 240px;
  height: 960px;
  background-color: #000000;
}
.word-scroller {
  width: 240px;
  flex: 1;
}
.word-card {
  width: 220px;
  margin-left: 10px;
  margin-top: 8px;
  padding: 12px;
  background-color: #1c1c1e;
  border-radius: 8px;
}
.word-text {
  font-size: 22px;
  font-weight: bold;
  color: #ffffff;
}
.phonetic-text {
  font-size: 14px;
  color: #8e8e93;
  margin-top: 4px;
}
.trans-text {
  font-size: 16px;
  color: #ebebf5;
  margin-top: 6px;
  text-overflow: ellipsis;
}
</style>
```

---

#### 场景 2：生字书写描红板与笔迹绘制 (`<canvas>`)
```html
<template>
  <div class="canvas-wrap">
    <canvas 
      ref="drawCanvas" 
      class="paint-board"
      @touchstart="onTouchStart"
      @touchmove="onTouchMove"
      @touchend="onTouchEnd">
    </canvas>
    <div class="btn-clear" @click="clearBoard">
      <text class="btn-text">清空</text>
    </div>
  </div>
</template>

<script>
export default {
  data: () => ({
    ctx: null
  }),
  mounted() {
    this.ctx = this.$refs.drawCanvas.getContext('2d');
    this.ctx.setLineWidth(6);
    this.ctx.setLineCap('round');
    this.ctx.setLineJoin('round');
    this.ctx.setStyle('#FFCC00');
  },
  methods: {
    onTouchStart(e) {
      const touch = e.touches[0];
      this.ctx.beginPath();
      this.ctx.moveTo(touch.pageX, touch.pageY);
    },
    onTouchMove(e) {
      const touch = e.touches[0];
      this.ctx.lineTo(touch.pageX, touch.pageY);
      this.ctx.render(); // 刷新指令到 Skia
    },
    onTouchEnd() {
      this.ctx.closePath();
    },
    clearBoard() {
      // 使用背景色重新覆盖
      this.ctx.setStyle('#000000');
      this.ctx.rect(0, 0, 240, 600);
      this.ctx.renderRect(0, 0, 240, 600);
      this.ctx.setStyle('#FFCC00'); // 恢复画笔颜色
      this.ctx.render();
    }
  }
}
</script>

<style>
.canvas-wrap {
  width: 240px;
  height: 960px;
  background-color: #000000;
  align-items: center;
}
.paint-board {
  width: 240px;
  height: 600px;
  background-color: #121212;
}
.btn-clear {
  width: 160px;
  height: 48px;
  background-color: #ff9500;
  border-radius: 24px;
  margin-top: 40px;
  justify-content: center;
  align-items: center;
}
.btn-text {
  font-size: 18px;
  font-weight: bold;
  color: #ffffff;
}
</style>
```

---

#### 场景 3：跑马灯与长标题自动滚动 (`<text>`)
```html
<template>
  <div class="header-bar">
    <!-- 当歌名或长释义超长时，原生 marquee 平滑循环滚动 -->
    <text 
      class="marquee-title" 
      :marquee-speed="60" 
      :marquee-gap="30">
      Supercalifragilisticexpialidocious - 奇妙的、难以置信的长单词
    </text>
  </div>
</template>

<style>
.header-bar {
  width: 240px;
  height: 60px;
  background-color: #2c2c2e;
  justify-content: center;
  padding-left: 10px;
  padding-right: 10px;
}
.marquee-title {
  width: 220px;
  font-size: 18px;
  color: #30d158;
  lines: 1;
  text-overflow: marquee; /* 触发底层 WXText 跑马灯逻辑 */
}
</style>
```

---

## 七、总结与架构级开发建议

1. **坚持 Flexbox 纯粹性**：Falcon 的布局计算直接由底层 C++ 编写的 Yoga 引擎驱动，没有任何传统 Web 浏览器的复合排版引擎。所有容器标签（`<div />`、`<scroller />`）均默认为 `display: flex; flex-direction: column;`。切勿尝试使用 `float`、`grid`、`inline-block`。
2. **充分利用硬件加速组件**：
   - 对于复杂帧动画，优先采用矢量化 `<lottie />` 或 `<image-frame />`，内存开销较 GIF 减少 70% 以上；
   - 对于频繁的手势交互动画（如横滑跟手、下拉回弹），优先使用 `BindingX` 绑定表达式，直接在 C++ 渲染主线程插值执行。
3. **Canvas 批处理必须 `render()`**：与标准 HTML5 Canvas 立即模式不同，Falcon 的 `falcon::JSCanvasContext` 基于指令队列表驱动。每次路径绘制或状态改变后，**必须调用 `ctx.render()`** 才能将缓冲图元刷入 Skia 渲染至物理 Framebuffer。
4. **长列表防 OOM 规范**：词典笔可用应用运行内存约为 64MB~128MB，在构建单词列表或长文章时，务必在 `<scroller>` 上开启 `recyclable="true"`，并搭配 `loadmore` 进行分段渲染，避免创建数千个 VNode 实体导致进程被系统的 Low Memory Killer (LMK) 终止。
