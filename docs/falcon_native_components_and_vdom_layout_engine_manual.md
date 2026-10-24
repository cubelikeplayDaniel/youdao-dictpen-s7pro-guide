# 有道词典笔 S7 Pro Falcon 原生组件与 Virtual DOM 布局引擎权威逆向手册
## (Falcon Native Components, VDOM Tree, Flexbox Layout & Physics Engine Deep Manual)

> **设备平台**: 网易有道词典笔 S7 Pro (`YDPS7-2`)  
> **SoC 芯片**: 算能 / 晶视 Cvitek CV1813H (单核 ARM Cortex-A7 @ 1.0GHz, 32-bit HardFloat, NEON SIMD)  
> **固件版本**: Linux 4.9.x + Falcon MiniApp 运行时 4.22.0+  
> **核心二进制**: `/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/libfalcon.so` (19,220 dynamic symbols, 4,483 relocations)  
> **辅助运行库**: `/reverse_dump/libquickjs.so` (QuickJS 2020-07-05 虚拟机), `js-framework.min.bin` (Weex NVue 2.6.12 框架字节码)

---

## 目录索引

1. [Falcon 原生组件体系架构与标签映射机制](#1-falcon-原生组件体系架构与标签映射机制)
   - 1.1 [Weex NVue 跨语言架构拓扑](#11-weex-nvue-跨语言架构拓扑)
   - 1.2 [`JQuick::ComponentRegistry` 标签映射表与回退机制](#12-jquickcomponentregistry-标签映射表与回退机制)
   - 1.3 [`JQuick::Component` 核心基类虚表结构 (VTable Layout)](#13-jquickcomponent-核心基类虚表结构-vtable-layout)
   - 1.4 [底层视图树与 `greenui::View` 继承拓扑](#14-底层视图树与-greenuiview-继承拓扑)
2. [Weex/Falcon VDOM 与 Flexbox 布局引擎](#2-weexfalcon-vdom-与-flexbox-布局引擎)
   - 2.1 [Yoga/Flexbox 端口集成与 `YGNode` 内存布局](#21-yogaflexbox-端口集成与-ygnode-内存布局)
   - 2.2 [布局流水线全生命周期 (Measure $\to$ Layout $\to$ PostLayout $\to$ Draw)](#22-布局流水线全生命周期)
   - 2.3 [文本内在尺寸度量函数 (`TEXT_MEASURE_FUNCTION`) 底层实现](#23-文本内在尺寸度量函数底层实现)
3. [`<scroller>` 容器的深度物理滚动与手势惯性契约](#3-scroller-容器的深度物理滚动与手势惯性契约)
   - 3.1 [`SplineOverScroller` 样条插值惯性动力学数学模型](#31-splineoverscroller-样条插值惯性动力学数学模型)
   - 3.2 [越界回弹 (OverScroll / OverFling) 与速度阈值矩阵](#32-越界回弹与速度阈值矩阵)
   - 3.3 [嵌套滚动 (`NestedScroll`) 与手势派发协议](#33-嵌套滚动与手势派发协议)
   - 3.4 [属性与事件契约全集](#34-属性与事件契约全集)
4. [`<slider>` 轮播组件的深度实现 (`WXSlider` / `SliderView`)](#4-slider-轮播组件的深度实现)
   - 4.1 [属性解析与定向排版 (`vertical` 属性底层真相)](#41-属性解析与定向排版)
   - 4.2 [无限循环、自动播放与手势拦截流水线](#42-无限循环自动播放与手势拦截流水线)
5. [`<image>` 与 `<text>` 组件的底层绘制与样式](#5-image-与-text-组件的底层绘制与样式)
   - 5.1 [`<image>` 原生实现 (`WXImage` / `WXImageView`) 与缓存机制](#51-image-原生实现与缓存机制)
   - 5.2 [`<text>` 排版引擎与跑马灯 (`marquee`) 模式](#52-text-排版引擎与跑马灯模式)
6. [样式与属性解析引擎](#6-样式与属性解析引擎)
   - 6.1 [`JQuick::CSSStyleParser` 单例与属性映射分发表](#61-jquickcssstyleparser-单例与属性映射分发表)
   - 6.2 [CSS 长度单位转换系统 (`CSSLengthParser::parse`)](#62-css-长度单位转换系统)
   - 6.3 [750px 设计稿缩放与 1020×240 物理屏幕几何坐标映射](#63-750px-设计稿缩放与屏幕几何坐标映射)
7. [完整 TypeScript 类型定义 (`falcon-components.d.ts`)](#7-完整-typescript-类型定义-falcon-componentsdts)
8. [生产级端侧示例工程 (NVue 全特性页面)](#8-生产级端侧示例工程-nvue-全特性页面)

---

## 1. Falcon 原生组件体系架构与标签映射机制

### 1.1 Weex NVue 跨语言架构拓扑

网易有道词典笔 S7 Pro 搭载的 MiniApp 框架，其底层技术本质是**阿里巴巴 Weex 原生渲染内核深度裁剪与重构版（NVue 架构）**。

与使用 WebView / WebKit 渲染的传统微信小程序不同，Falcon 运行时完全绕过了 Web 引擎，采用 **QuickJS 字节码虚拟机 + C++ 原生节点树 + Skia 2D 图形引擎** 实现 60FPS 硬件级渲染：

```
+-----------------------------------------------------------------------------------+
| 1. JavaScript 逻辑层 (QuickJS Bytecode Engine - libquickjs.so)                     |
|    - Vue 2.6.12 NVue Runtime (预编译 QuickJS Bytecode .js.bin)                     |
|    - VNode 虚拟 DOM 树 (_c("div"), _c("scroller"), _c("text"), _c("image"))        |
|    - staticClass: ["class-a", "class-b"] 数组化索引                                |
+-----------------------------------------^-----------------------------------------+
                                          | (Falcon C++ Native Bridge)
+-----------------------------------------v-----------------------------------------+
| 2. JQuick 虚拟元素抽象层 (libfalcon.so - JQuick::Component Hierarchy)              |
|    - JQuick::ComponentRegistry 标签路由分发                                        |
|    - JQuick::Component 虚表生命周期驱动 (bindData, calculateLayout, onPostLayout)  |
|    - Facebook Yoga Flexbox C++ 排版引擎 (YGNodeRef 节点关联)                        |
+-----------------------------------------^-----------------------------------------+
                                          | (onCreateHostView / attachHostView)
+-----------------------------------------v-----------------------------------------+
| 3. GreenUI 原生视图层 (libfalcon.so - greenui::View Hierarchy)                     |
|    - greenui::ViewGroup / ScrollView / SliderView / TextView / ImageView          |
|    - 触控手势处理 (onTouchEvent, onInterceptTouchEvent, SplineOverScroller)        |
|    - 脏矩形收集 (invalidate) 与视图层级树管理                                      |
+-----------------------------------------^-----------------------------------------+
                                          | (Skia 2D 硬件光栅化)
+-----------------------------------------v-----------------------------------------+
| 4. 硬件渲染与输出层 (Linux Framebuffer /dev/fb0)                                  |
|    - SkCanvas 硬件直绘 (Skia Canvas, SkBitmap, SkPath, SkPaint)                    |
|    - NEON 优化旋转 Blit: 1020×240 逻辑画布 -> 240×1020 物理面板 (CW 270° / CCW 90°)  |
+-----------------------------------------------------------------------------------+
```

---

### 1.2 `JQuick::ComponentRegistry` 标签映射表与回退机制

在 `libfalcon.so` 中，标签注册中心由 `JQuick::ComponentRegistry` 负责维护。其内部维持了一个以标签名（`std::string`）为键、以组件构建器工厂指针（`ComponentHolder*`）为值的关联红黑树（`std::map<std::string, ComponentHolder*>`）。

#### 逆向汇编证据 (`ComponentRegistry::createComponent` @ `0x0038437c`)
```arm
0x0038437c: push   {r4, r5, r6, r7, lr}
0x00384380: mov    r4, r0
0x00384384: mov    r7, r1            ; r1 = 传入的标签字符串 (const std::string& tag)
0x00384388: add    r0, r0, #0x24     ; r0 = &this->mRegistryMap
0x0038438c: bl     #0x1d3878         ; 调用 std::map::find(tag)
0x00384390: ldr    r3, [r4, #0x28]   ; 取出 std::map::end()
0x00384394: mov    r5, r0
0x00384398: cmp    r0, r3            ; 比较迭代器是否到达末尾
0x0038439c: beq    #0x3843bc         ; 若未找到该标签，跳转到默认回退分支
0x003843a0: ldr    r0, [r5, #0x14]   ; 取出 ComponentHolder* 工厂对象
0x003843a4: mov    r1, r7
0x003843a8: ldr    r3, [r0]          ; 取出 ComponentHolder 虚表指针
0x003843ac: ldr    r3, [r3, #0xc]    ; 取出 ComponentHolder::create(ref) 虚函数
0x003843b0: blx    r3                ; 实例化对应的 JQuick::Component 子类对象
0x003843b4: pop    {r4, r5, r6, r7, pc}

; === 未知标签回退处理分支 (Fallback to "container") ===
0x003843bc: ldr    r1, [pc, #0x28]   ; 加载字面量常量偏移 (指向 "container" @ 0x738584)
0x003843c0: add    r0, r4, #0x24     ; r0 = &this->mRegistryMap
0x003843c4: add    r1, pc, r1        ; r1 = "container"
0x003843c8: bl     #0x1d3878         ; 查找 "container" 对应的构建器
0x003843cc: ldr    r3, [r4, #0x28]
0x003843d0: cmp    r0, r3
0x003843d4: beq    #0x3843e4         ; 若仍无，返回 nullptr
0x003843d8: ldr    r0, [r0, #0x14]   ; 取出 DivHolder*
0x003843dc: ldr    r3, [r0]
0x003843e0: ldr    r3, [r3, #0xc]    ; 调用 DivHolder::create
0x003843e4: blx    r3                ; 降级创建 Div (容器节点)
```

#### 原生标签与 C++ 类映射全景表

| Vue 模板标签 | Falcon 注册别名 | C++ 组件类 (`JQuick::*`) | 宿主原生视图 (`greenui::*`) | 组件内存大小 | 宿主视图大小 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `<div>` | `"div"`, `"container"` | `JQuick::Div` | `greenui::ViewGroup` | `0x12c` (300B) | `0x150` (336B) |
| `<scroller>` | `"scroller"`, `"scroll-view"`| `JQuick::WXScroller` | `JQuick::WXScrollView` (`ScrollView`) | `0x158` (344B) | `0x208` (520B) |
| `<text>` | `"text"` | `JQuick::WXText` | `greenui::TextView` | `0x1b4` (436B) | `0x1a0` (416B) |
| `<image>` | `"image"`, `"img"` | `JQuick::WXImage` | `JQuick::WXImageView` (`ImageView`) | `0x16c` (364B) | `0x13c` (316B) |
| `<slider>` | `"slider"`, `"swiper"` | `JQuick::WXSlider` | `JQuick::WXSliderView` (`SliderView`) | `0x148` (328B) | `0x318` (792B) |
| `<input>` | `"input"` | `JQuick::WXInput` | `JQuick::InputScrollView` | `0x160` (352B) | `0x210` (528B) |
| `<textarea>` | `"textarea"` | `JQuick::WXTextarea` | `JQuick::TextareaScrollView` | `0x130` (304B) | `0x240` (576B) |
| `<canvas>` | `"canvas"` | `JQuick::WXCanvas` | `JQuick::CanvasView` | `0x138` (312B) | `0x158` (344B) |
| `<imageframe>` | `"imageframe"` | `JQuick::WXImageFrame` | `greenui::ImageFrame` (帧动画) | `0x140` (320B) | `0x168` (360B) |
| `<qrcode>` | `"qrcode"` | `JQuick::WXQRCode` | `greenui::ImageView` (Skia 生成) | `0x134` (308B) | `0x13c` (316B) |
| `<richtext>` | `"richtext"` | `JQuick::WXRichText` | `JQuick::RichTextView` | `0x180` (384B) | `0x188` (392B) |
| `<latex>` | `"latex"` | `JQuick::latex::WXLatex` | `JQuick::latex::LatexView` | `0x170` (368B) | `0x180` (384B) |
| `<list>` | *(无独立 C++)* | 映射至 `WXScroller` | `greenui::ScrollView` | - | - |
| `<cell>` | *(无独立 C++)* | 映射至 `Div` | `greenui::ViewGroup` | - | - |
| `<switch>` | *(无独立 C++)* | JS 框架层转译为 `<div>` | `greenui::ViewGroup` | - | - |

> **关键架构发现**：
> 1. **虚拟列表降级**：Weex 标准规范中的 `<list>` 与 `<cell>` 在词典笔嵌入式环境（RAM 仅 64MB~128MB）被精简，运行时将其直接映射为 `<scroller>` 和普通容器 `<div>`，不支持复杂的多池复用池，建议开发者在 JS 层通过虚拟滚动窗口（Virtual Window Slice）优化大量数据。
> 2. **未知标签容错**：任意未声明的原生标签（例如 `<custom-tag>`）均被静默降级为 `"container"`（即 `greenui::ViewGroup`），不会引发底层抛错崩溃。

---

### 1.3 `JQuick::Component` 核心基类虚表结构 (VTable Layout)

`JQuick::Component` 是所有 Weex 节点在 C++ 层的核心承载基类。其虚函数表定义于 `libfalcon.so` 的 `_ZTVN6JQuick9ComponentE`（符号地址 `0x007d134c`），共 27 个虚函数槽位：

```cpp
// 逆向还原之 JQuick::Component C++ 虚函数表结构 (32-bit ARM GCC ABI)
namespace JQuick {
class Component {
public:
    // Slot 0:  ptroffset (0x00000000)
    // Slot 1:  RTTI typeinfo pointer for JQuick::Component (0x007d2f90)
    // Slot 2:  virtual ~Component();                                            // 0x0037f61c
    // Slot 3:  virtual ~Component() [deleting];                                 // 0x0037f708
    // Slot 4:  virtual bool isScrollable() const;                               // 0x0037ee48
    // Slot 5:  virtual void bindData(const Styles&, const Attrs&, const Events&);// 0x00380a90
    // Slot 6:  virtual void appendDefaultStyles();                              // 0x0037ee50
    // Slot 7:  virtual void doUpdateStyles(const std::map<string, string>&);    // 0x003811d8
    // Slot 8:  virtual void doUpdateAttributes(const std::map<string, string>&);// 0x00380f94
    // Slot 9:  virtual void calculateLayout(const std::pair<float, float>&);    // 0x00381cdc
    // Slot 10: virtual bool isRoot() const;                                     // 0x0037ee54
    // Slot 11: virtual void addComponent(Component* child, int index);          // 0x00381d64
    // Slot 12: virtual void onRecycle(greenui::View* view);                     // 0x0037ee5c
    // Slot 13: virtual void onRecycleResource();                                // 0x0037ee60
    // Slot 14: virtual void onSelectChange(greenui::View* view, bool selected); // 0x0037ee64
    // Slot 15: virtual void onActiveChange(greenui::View* view, bool active);   // 0x0037ee68
    // Slot 16: virtual void onPreLayout();                                      // 0x0038234c
    // Slot 17: virtual void onPostLayout(const RectF& rect, const RectF& padding, const RectF& border); // 0x003823bc
    // Slot 18: virtual void setChildFrame(Component* child, int l, int t, int r, int b, int pl, int pt); // 0x0038290c
    // Slot 19: virtual void onHostViewAttached();                               // 0x0037ee6c
    // Slot 20: virtual void attachHostView();                                   // 0x00382980
    // Slot 21: virtual void detachHostView();                                   // 0x00382a44
    // Slot 22: virtual void onRelease();                                        // 0x0037ee70
    // Slot 23: virtual bool invokeJSMethod(const string& name, const JsonArray&);// 0x00382b6c
    // Slot 24: virtual greenui::View* onCreateHostView();                       // 0x0037ee74 [纯虚或空]
    // Slot 25: virtual bool setProperty(const string& name, const string& val); // 0x00382ca0
    // Slot 26: virtual void onAddEvent(const string& eventName);                // 0x00382e2c
    // Slot 27: virtual void onRemoveEvent(const string& eventName);             // 0x00382e68

    // 关键核心成员变量内存布局:
    uint32_t           mRefId;            // +0x04: JS 端的节点引用标识 (ref)
    std::string        mTag;              // +0x08: 标签名称 ("div", "text" 等)
    YGNodeRef          mYogaNode;         // +0x14: Facebook Yoga 布局节点指针
    Component*         mParent;           // +0x18: 父节点 Component 指针
    std::vector<Component*> mChildren;    // +0x1c: 子节点列表 (begin, end, cap)
    greenui::View*     mHostView;         // +0x28: 关联的原生 Host View
    WXInstance*        mInstance;         // +0x2c: 所属 Weex 实例环境
    std::map<string, string> mStyles;     // +0x44: 当前生效的内联与类选择器样式表
    std::map<string, string> mAttrs;      // +0x58: 节点属性表
    std::set<string>   mEvents;           // +0x6c: 注册监听的事件集合
};
}
```

---

### 1.4 底层视图树与 `greenui::View` 继承拓扑

Falcon 渲染层构建于网易自主研发的轻量级嵌入式 C++ GUI 库 **GreenUI** 之上。所有实际参与触控响应、矩阵变换与 Skia 调度的实体均为 `greenui::View` 的派生类：

```
                    greenui::EventTarget (事件目标)
                              │
                              ▼
                      greenui::View (基础视图: 坐标、绘制、动画、脏矩形)
                              │
            ┌─────────────────┼──────────────────────────────┐
            ▼                 ▼                              ▼
    greenui::ViewGroup   greenui::TextView          greenui::ImageView
   (多子节点容器视图)    (Skia 文本排版/Marquee)     (位图解码/裁剪/缓存)
            │                                                │
   ┌────────┴────────┐                                       ▼
   ▼                 ▼                             JQuick::WXImageView
greenui::ScrollView  greenui::SliderView
(惯性物理滚动)       (卡片分页轮播)
   │                 │
   ▼                 ▼
JQuick::WXScrollView JQuick::WXSliderView
```

---

## 2. Weex/Falcon VDOM 与 Flexbox 布局引擎

### 2.1 Yoga/Flexbox 端口集成与 `YGNode` 内存布局

Falcon 内部完整静态编译了 Facebook Yoga Flexbox C++ 排版引擎。每个 `JQuick::Component` 在初始化构造函数（`0x0037f428`）中，均通过 `YGNodeNew()` 分配一个对应的 `YGNode`，并将其指针保存在 `this + 0x14`。

#### 核心 CSS 属性到 Yoga 布局调用的映射分发

当 VNode 树发生属性合并（`bindData` 或 `doUpdateStyles`）时，`JQuick::CSSStyleParser` 将 CSS 字符串转换为 Yoga 枚举并直接注入底层：

| CSS 样式属性 | 支持取值范围 | Yoga 底层 C/C++ API |
| :--- | :--- | :--- |
| `flex-direction` | `row`, `column`, `row-reverse`, `column-reverse` | `YGNodeStyleSetFlexDirection(node, dir)` |
| `justify-content` | `flex-start`, `center`, `flex-end`, `space-between`, `space-around` | `YGNodeStyleSetJustifyContent(node, val)` |
| `align-items` | `stretch`, `flex-start`, `center`, `flex-end` | `YGNodeStyleSetAlignItems(node, val)` |
| `align-self` | `auto`, `stretch`, `flex-start`, `center`, `flex-end` | `YGNodeStyleSetAlignSelf(node, val)` |
| `align-content` | `flex-start`, `center`, `flex-end`, `stretch` | `YGNodeStyleSetAlignContent(node, val)` |
| `flex-wrap` | `nowrap`, `wrap` | `YGNodeStyleSetFlexWrap(node, wrap)` |
| `flex` / `flex-grow` | 数字（如 `1`, `0.5`） | `YGNodeStyleSetFlexGrow(node, val)` |
| `flex-shrink` | 数字（如 `0`, `1`，默认 `1`） | `YGNodeStyleSetFlexShrink(node, val)` |
| `flex-basis` | 像素值或百分比 | `YGNodeStyleSetFlexBasis(node, val)` |
| `width` / `height` | 长度数值、`auto`、百分比 | `YGNodeStyleSetWidth(node, val)` |
| `min-width` / `max-width` | 长度数值、百分比 | `YGNodeStyleSetMinWidth` / `MaxWidth` |
| `margin-*` | 上下左右独立边距、`auto` | `YGNodeStyleSetMargin(node, edge, val)` |
| `padding-*` | 上下左右独立内边距 | `YGNodeStyleSetPadding(node, edge, val)` |
| `border-*-width` | 边框宽度 | `YGNodeStyleSetBorder(node, edge, val)` |
| `row-gap` / `column-gap` | 间距数值 (Flexbox 规范增强) | `YGNodeStyleSetRowGap` / `ColumnGap` |
| `aspect-ratio` | 浮点数比例（如 `1.777`） | `YGNodeStyleSetAspectRatio(node, ratio)` |

---

### 2.2 布局流水线全生命周期

Falcon 的排版渲染遵循高度优化的单向生命周期流动，彻底杜绝了 Web 浏览器中频繁引发卡顿的同步强制重排（Reflow Thrashing）：

```
[JS VNode 变更] -> doUpdateStyles / doUpdateAttributes
                          │
                          ▼
                  YGNodeMarkDirty()
                          │
                          ▼ (由 VSync / UI 刷新循环触发)
             JQuick::Component::calculateLayout(root, w, h)
                          │
                          ▼
                YGNodeCalculateLayout()
        (Yoga 递归解算所有节点的 Flexbox 相对坐标)
                          │
                          ▼
            JQuick::Component::onPostLayout()
(读取 YGNodeLayoutGetLeft/Top/Width/Height 转换为实际物理 Rect)
                          │
                          ▼
               greenui::View::layout(l, t, r, b)
          (更新 View 的 mBounds 矩形与变换矩阵)
                          │
                          ▼
              greenui::ScrollView::computeScroll()
          (步进惯性物理样条插值，更新 mScrollX/Y)
                          │
                          ▼
              greenui::View::dispatchDraw(canvas)
               (Skia 硬件光栅化直绘到物理 Framebuffer)
```

1. **`measure` 阶段**: 由叶子节点（如 `WXText`）提供的原生测算函数计算文字内容的理想尺寸，并向上层 Yoga 容器反馈内在尺寸。
2. **`calculateLayout` 阶段**: 根节点 `WXInstance::calculateLayout` 从根容器（`1020 × 240`）自顶向下执行多轴对齐、弹性收缩（Flex Shrink）与拉伸分配。
3. **`onPostLayout` 阶段** (`0x003823bc`): 遍历组件树，将 Yoga 计算出的浮点坐标 (`Left`, `Top`, `Width`, `Height`) 取整并设置到宿主 `greenui::View` 上，同时更新内边距和边框矩形。
4. **`computeScroll` 阶段**: 在每次 VSync 帧绘制前，带有惯性滑动的容器（如 `ScrollView`）依据物理时钟步进样条插值器，计算出当前帧的位移增量。
5. **`dispatchDraw` 阶段**: `greenui::View::dispatchDraw` 递归调用子视图的 `onDraw`，配合 Skia 的 `SkCanvas::clipRect`、`SkCanvas::translate` 与 `SkCanvas::concat` 实施高效光栅化。

---

### 2.3 文本内在尺寸度量函数底层实现

`WXText` 注册到 Yoga 节点的测算回调函数为 `TEXT_MEASURE_FUNCTION`（地址 `0x0039ff70`）：

```arm
; JQuick::TEXT_MEASURE_FUNCTION(YGNodeRef node, float width, YGMeasureMode widthMode, float height, YGMeasureMode heightMode)
0x0039ff70: push   {r4, r5, r6, lr}
0x0039ff74: subs   r4, r1, #0        ; 检查目标宽度
0x0039ff78: ldr    r6, [r0]          ; 取出关联的 WXText* 对象指针 (node->getContext())
0x0039ff7c: vpush  {d8}
0x0039ff80: mov    r5, r2            ; r2 = widthMode (Undefined, Exactly, AtMost)
0x0039ff84: vmov.f32 s16, s1
0x0039ff88: sub    sp, sp, #0x18
...
0x0039ffc4: mov    r0, r6            ; r0 = WXText*
0x0039ffc8: bl     #0x3a0050         ; 调用 WXText::text_measure(float w, float h, float& outW, float& outH, bool isWrap)
```

`WXText::text_measure` 会根据 `fontSize`（默认 28px）、`fontFamily`、`lineHeight`、`lines` 以及字符内容，调用 GreenUI 的底层字形光栅化器测算每行文字占用的像素宽高。若设置了 `lines: 1` 且无显式宽度，宽度由排版字符串长度决定；若父容器施加了 `AtMost` 约束，则自动折行计算总高度。

---

## 3. `<scroller>` 容器的深度物理滚动与手势惯性契约

### 3.1 `SplineOverScroller` 样条插值惯性动力学数学模型

Falcon 的 `<scroller>` 容器（C++ 类 `JQuick::WXScroller`，底层宿主 `greenui::ScrollView` 与 `greenui::Scroller`）采用了深度定制的 **Android 样条插值曲线惯性动力学模型 (Spline-based OverScroller)**。

在 `libfalcon.so` 中，我们精确反编译出了控制滑动减速与惯性步进的核心数学公式与常量：

#### 1. 物理减速阻尼常数矩阵
- **摩擦系数** ($mFlingFriction$): 固定标定为 `0.015f`
- **重力与密度乘数** ($mPhysicalCoeff$):
  $$\text{mPhysicalCoeff} = \text{g} \times 39.37 \times \text{dpi} \times 0.84 = 9.80665 \times 39.37 \times 160 \times 0.84 = 51890.1977$$
- **物理摩擦乘积常数**:
  $$\text{mFlingFriction} \times \text{mPhysicalCoeff} = 0.015 \times 51890.1977 = \mathbf{778.352966}$$
  *(汇编常量 `0x44429697`，存储于 `libfalcon.so` 的 `0x0043cbac`)*
- **对数减速常数** ($DECELERATION\_RATE$):
  $$DECELERATION\_RATE = \frac{\ln(0.78)}{\ln(0.9)} \approx \mathbf{2.3582017}$$
- **样条拐点参数** ($INFLEXION$): $\mathbf{0.35f}$
- **时钟乘数**: $1000.0\text{ ms/s}$

#### 2. 样条减速系数计算 (`scroller_getSplineDeceleration` @ `0x0043cb88`)
给定手指脱手时的瞬时初速度 $v$（单位：像素/秒）：
$$l(v) = \ln\left(\frac{0.35 \times |v|}{778.352966}\right)$$

#### 3. 惯性滑动总时长计算 (`scroller_getSplineFlingDuration` @ `0x0043cbb8`)
$$Duration(v) = \exp\left(\frac{l(v)}{DECELERATION\_RATE - 1.0}\right) \times 1000.0 = \exp\left(\frac{l(v)}{1.3582017}\right) \times 1000.0\quad (\text{毫秒})$$

#### 4. 惯性滑动总路程计算 (`scroller_getSplineFlingDistance` @ `0x0043cbf0`)
$$Distance(v) = 778.352966 \times \exp\left(\frac{DECELERATION\_RATE}{DECELERATION\_RATE - 1.0} \times l(v)\right) = 778.353 \times \exp(1.7362676 \times l(v))\quad (\text{像素})$$

```arm
; 汇编还原：scroller_getSplineFlingDistance 核心计算
0x0043cbf0: push   {r4, lr}
0x0043cbf4: vpush  {d8}
0x0043cbf8: vmov.f32 s16, s0
0x0043cbfc: bl     #0x43cb88          ; 先计算 l(v)
0x0043cc00: vcvt.f64.f32 d0, s0
0x0043cc04: vldr   d1, [pc, #0x28]    ; 加载双精度常量 1.7362676 (DECELERATION_RATE / (DEC_RATE - 1.0))
0x0043cc08: vmul.f64 d0, d0, d1
0x0043cc0c: bl     exp                ; exp(1.7362676 * l)
0x0043cc10: vldr   d1, [pc, #0x20]    ; 加载双精度常量 778.352966
0x0043cc14: vmul.f64 d0, d0, d1       ; distance = 778.353 * exp(...)
0x0043cc18: vpop   {d8}
0x0043cc1c: pop    {r4, pc}
```

---

### 3.2 越界回弹与速度阈值矩阵

Falcon 针对嵌入式超长带鱼屏（1020×240）定制了严格的速度门禁与阻尼常数：

| 物理与手势阈值 | 内部常量值 | 作用说明 |
| :--- | :--- | :--- |
| **Touch Slop (防抖阈值)** | `8.0 px` | 手指移动超过 8px 时才锁定为滚动事件，避免误触点击 |
| **Min Fling Velocity** | `50.0 px/s` | 脱手初速度低于 50px/s 时视为静止放置，不触发惯性飞掠 |
| **Max Fling Velocity** | `2000.0 px/s` (`0x44fa0000`) | 初速度硬上限，防止用户猛烈滑屏导致视图飞速超界失控 |
| **OverScroll 阻尼衰减系数** | `0.35` | 触达边缘继续拉动时，手指位移以 $35\%$ 的系数衰减 |
| **OverFling 回弹周期** | `250 ms ~ 350 ms` | 惯性冲出边界后，基于欠阻尼弹簧（Underdamped Spring）回弹 |

---

### 3.3 嵌套滚动 (`NestedScroll`) 与手势派发协议

当 `<scroller>` 内部嵌套子 `<scroller>` 时，Falcon 采用两级向上消费手势协议：
1. **触摸拦截门禁** (`greenui::ScrollView::onInterceptTouchEvent` @ `0x0043af20`):
   - 检测当前滑动手势方向与父子容器的 `scroll-direction`。
   - 若父容器为 `horizontal`，子容器为 `vertical`，两轴手势正交，各自独立捕获，互不干扰。
   - 若父子容器滚动方向相同（同为 `horizontal`）：子容器优先消费滑动增量 $\Delta X$。
2. **边缘溢出向上传递** (`mNestedScroll = true`):
   - 子容器在到达滚动上限（`mScrollX <= 0`）或下限（`mScrollX >= mMaxScrollX`）时，未消费的剩余速度分量 $v_{remain}$ 通过 `parent->dispatchNestedScroll()` 派发给父容器继续消化，实现丝滑连贯的外层联运滚动。

---

### 3.4 属性与事件契约全集

#### 1. `<scroller>` 支持的原生属性 (Attributes)

| 属性名称 | 类型 | 默认值 | 作用与物理约束 |
| :--- | :--- | :--- | :--- |
| `scroll-direction` | `string` | `"vertical"` | 滚动主轴方向：`"horizontal"` 或 `"vertical"` |
| `scrollable` | `boolean` | `true` | 是否允许手指交互滑动 |
| `show-scrollbar` | `boolean` | `false` | 是否显示滚动条（词典笔屏幕较窄，建议常关） |
| `offset-accuracy` | `number` | `10` | 触发 `scroll` 事件的最小像素增量步长，防频密跨语言通信 |
| `loadmoreoffset` | `number` | `0` | 触底前提前触发 `loadmore` 事件的距离阈值（px） |
| `upper-threshold` | `number` | `50` | 距离顶部多少距离触发 `scrolltoupper` 事件 |
| `lower-threshold` | `number` | `50` | 距离底部多少距离触发 `scrolltolower` 事件 |
| `scroll-event-interval` | `number` | `16` | 滚动事件派发节流时间间隔（ms） |
| `enable-acceleration` | `boolean` | `false` | 是否开启滑动加速度增益算法 |

#### 2. `<scroller>` 支持的原生事件 (Events)

| 事件名称 | 回调负载对象 (Event Payload) | 触发时机 |
| :--- | :--- | :--- |
| `@scroll` | `{ contentSize: { width, height }, contentOffset: { x, y } }` | 每次滚动且位移增量超过 `offset-accuracy` 时 |
| `@scrollstart` | `{ contentOffset: { x, y } }` | 手指按下并越过 TouchSlop，滚动开始的一瞬间 |
| `@scrollend` | `{ contentOffset: { x, y } }` | 手指抬起且惯性样条减速完全归零停止时 |
| `@loadmore` | `{}` | 滚动距离距离末端小于 `loadmoreoffset` 时触发（只触发一次） |
| `@scrolltoupper`| `{ direction: "top" }` | 滚动进入顶部阈值区间 |
| `@scrolltolower`| `{ direction: "bottom" }` | 滚动进入底部阈值区间 |

### 3.3 生产踩坑实录：横向 `<scroller>` 的 Yoga 弹性流塌陷与容器包装铁律

#### 1. 致命缺陷复现
在开发水平横向滑动的卡片流（如横向书架、横向卡片选择器）时，若编写如下代码：
```html
<scroller scroll-direction="horizontal" style="width: 972px; height: 212px; flex-direction: row;">
  <div v-for="item in list" :key="item.id" style="width: 274px; height: 198px;">
    <!-- 卡片内容 -->
  </div>
</scroller>
```
**实机表现**：应用首次挂载进入页面时，卡片未按横向三列排布，而是呈现**单列垂直堆叠**（在 212px 高度的视口内堆叠多张 198px 的卡片），导致首张卡片被向上顶出视口外被截断；而在用户点击刷新按钮或触发二次渲染后，才突然重排恢复为水平三列。

#### 2. 底层 Yoga Flexbox 状态机根因
- Falcon 中的 `<scroller>`（`JQuick::WXScroller`）是一个视口复合组件，在 C++ 内部持有两层节点：外层的滚动视口 `greenui::ScrollView` 与内层的内容承载容器 `contentView`。
- 在 Facebook Yoga 布局引擎中，容器的子节点流向默认值始终为 `YGDirectionColumn`（`flex-direction: column`）。
- 当向 `<scroller>` 标签直接挂载多个子 VNode 时，这些子 VNode 在首帧测量阶段被直接插入到内部 `contentView` 中。如果首帧初次 LayoutPass 尚未接收到横向测量驱动，Yoga 引擎将子节点直接降级为垂直单列流；后续只有当组件接收到尺寸重排或重新赋值时，才会二次触发正确的排版。

#### 3. 官方级确定性防错包装规范
在 `<scroller scroll-direction="horizontal">` 内部，**必须嵌套显式带有 `flex-direction: row; height: 100%; align-items: center` 的单一行包装容器 `<div>`**：
```javascript
h('scroller', {
  attrs: {
    'scroll-direction': 'horizontal',
    'show-scrollbar': false
  },
  style: {
    width: '972px',
    height: '212px',
    flexDirection: 'row'
  }
}, [
  // 必须的内部强制行容器
  h('div', {
    style: {
      flexDirection: 'row',
      alignItems: 'center',
      height: '212px'
    }
  }, this.items.map(item => renderCard(item)))
])
```
通过显式注入带有 `flexDirection: 'row'` 的包装容器，子节点在构建 Virtual DOM 树的首帧即可确立水平主轴约束，彻底根除首帧单列堆叠与上方截断缺陷。

---

## 4. `<slider>` 轮播组件的深度实现 (`WXSlider` / `SliderView`)

### 4.1 属性解析与定向排版 (`vertical` 属性底层真相)

在 `libfalcon.so` 中，`<slider>` 对应 C++ 组件 `JQuick::WXSlider`（地址 `0x0039cf90`）。

#### 汇编关键解析：`vertical` 属性设置 (`0x0039cff8`)
```arm
; JQuick::WXSlider::setProperty(name, value)
0x0039cff8: ldr    r1, [pc, #0x21c]   ; 加载字面量常量 (指向 "vertical" @ 0x739e1c)
0x0039cffc: mov    r0, r5
0x0039d000: add    r1, pc, r1
0x0039d004: bl     #0x1e0ab4          ; 字符串比较: strcmp(name, "vertical")
0x0039d008: cmp    r0, #0
0x0039d00c: beq    #0x39d1b0          ; 若为 "vertical"，跳转到处理逻辑
...
0x0039d1b0: bl     #0x39c9f0          ; 将 value 转换为 bool (支持 "true", "1", true)
0x0039d1b4: strb   r0, [r4, #0x13d]   ; 关键门禁：保存 isVertical 标志到 [this + 0x13d]
0x0039d1b8: mov    r1, r0
0x0039d1bc: ldr    r0, [r4, #0x28]    ; r0 = WXSliderView*
0x0039d1c0: bl     #0x39d740          ; 调用 greenui::SliderView::setVertical(bool)
```

**排版尺寸计算**：
- 当 `vertical == false`（默认横向水平轮播）：
  单页卡片宽度基于 `getContentWidth()` 计算，手势追踪逻辑 $X$ 轴位移；
- 当 `vertical == true`（纵向垂直轮播，常用于垂直卡片堆叠翻页）：
  单页卡片高度基于 `getContentHeight()`（词典笔上为 240px）计算，手势追踪逻辑 $Y$ 轴位移。

---

### 4.2 无限循环、自动播放与手势拦截流水线

#### 1. 自动轮播与无限循环模型
- 属性 `auto-play="true"`：内部创建一个系统定时器 `greenui::Timer`，定时周期由 `interval`（默认 3000ms）决定。
- 属性 `loop="true"`：在视图渲染树的首尾自动注入虚拟卡片副本（Virtual Head/Tail Clones）。当滚动到虚拟末端卡片并触发动画结束时（`animationEnd`），静默无动画重置物理偏移（`scrollToPage(0, false)`），对用户呈现无缝闭环轮播。

#### 2. 手势拦截与滑动锁定 (`SliderView::onInterceptTouchEvent` @ `0x0039da50`)
```
用户手指接触屏幕 (ACTION_DOWN)
  │
  ▼
记录初试坐标 mDownX, mDownY，启动滑动判定
  │
  ▼
用户手指移动 (ACTION_MOVE)
  │
  ├─► 若 |ΔX| > 8px 且 |ΔX| > |ΔY| (水平 Slider):
  │     拦截事件 (return true)，中止所有子 View 的点击，锁定 Slider 拖拽
  │
  ├─► 若 |ΔY| > 8px 且 |ΔY| > |ΔX| (垂直 Slider):
  │     拦截事件 (return true)，锁定 Slider 垂直翻页
  │
  └─► 若未超过 8px: 放行给子 View (return false)
```

---

## 5. `<image>` 与 `<text>` 组件的底层绘制与样式

### 5.1 `<image>` 原生实现与缓存机制

`JQuick::WXImage` 驱动的宿主视图为 `JQuick::WXImageView`，继承自 `greenui::ImageView`。

#### 1. `resize` 模式底层光栅化矩阵变换
在 `WXImageView::onDraw(greenui::Canvas* canvas)` 中，根据属性 `resize` 动态计算 Skia 绘制矩阵：
- **`stretch`** (平铺拉伸，默认值):
  不考虑图片原始长宽比，直接将图片四角强制映射至组件布局矩形：
  $$\text{ScaleX} = \frac{W_{view}}{W_{bitmap}},\quad \text{ScaleY} = \frac{H_{view}}{H_{bitmap}}$$
- **`contain`** (等比内缩):
  保持原图宽高比，以图片全部展示在视图内部为准：
  $$\text{Scale} = \min\left(\frac{W_{view}}{W_{bitmap}}, \frac{H_{view}}{H_{bitmap}}\right)$$
  并在居中方向应用平移偏置：
  $$\Delta X = \frac{W_{view} - W_{bitmap} \times \text{Scale}}{2},\quad \Delta Y = \frac{H_{view} - H_{bitmap} \times \text{Scale}}{2}$$
- **`cover`** (等比裁切填满):
  保持原图宽高比，以图片铺满整个视图且多余部分裁切为准：
  $$\text{Scale} = \max\left(\frac{W_{view}}{W_{bitmap}}, \frac{H_{view}}{H_{bitmap}}\right)$$
  画布应用 `canvas->clipRect(viewBounds)`，超出边界的像素被硬光栅化剔除。

#### 2. 异步解码与内存缓存 (`greenui::BitmapCache`)
词典笔 RAM 极其紧张，Falcon 内置了 LRU 内存图片缓存池 `BitmapCache`：
- 图片加载任务首先检测内存缓存中是否存在已解码的 `SkBitmap`；
- 若未命中，通过 POSIX 线程池派发后台解码任务（支持 PNG、JPEG 与原生灰度位图）；
- 解码成功后，触发主线程 `WXImage::onLoad(naturalWidth, naturalHeight)`，更新 Yoga 尺寸并请求重绘。

---

### 5.2 `<text>` 排版引擎与跑马灯 (`marquee`) 模式

`WXText`（宿主为 `greenui::TextView`）不仅支持常规排版，更具备词典笔标志性的**硬件级跑马灯（Marquee）能力**：

#### 1. 样式与排版特性支持
- `lines`: 最大行数。若文本超长且设置了 `lines: 1` 或 `lines: 2`，自动截断。
- `text-overflow`:
  - `"clip"`: 硬截断；
  - `"ellipsis"`: 在最后一行末端绘制 `"..."` 占位符；
  - `"marquee"`: **词典笔超长单行文本自动滚动模式！**
- `marquee-speed`: 跑马灯滚动速度（像素/秒，默认 50px/s）。
- `marquee-gap`: 首尾两段文本循环之间的空白间隙（px，默认 60px）。

#### 2. 跑马灯动画驱动机制
当 `text-overflow: marquee` 生效时，`TextView` 不再裁切文字，而是挂载一个 `ViewPropertyAnimator`。每帧在逻辑 $X$ 轴持续累加偏置量，当文字尾部越过屏幕左端时，瞬间接回右侧进入下一轮循环，CPU 占用率极低。

---

## 6. 样式与属性解析引擎

### 6.1 `JQuick::CSSStyleParser` 单例与属性映射分发表

Falcon 针对所有传入组件的样式字典，采用单例快速哈希分发解析器 `CSSStyleParser::parser()`（地址 `0x003b0774`）。

内部维护了一个快速成员函数分发映射表：
```cpp
std::map<std::string, bool (CSSStyleParser::*)(Component*, const std::string&)>
```
每个 CSS 属性对应独立的解析槽位（如 `parseBackgroundColor`、`parseBorderRadius`、`parseFlexDirection` 等），在 $O(\log N)$ 时间内完成高效赋值与类型校验。

---

### 6.2 CSS 长度单位转换系统 (`CSSLengthParser::parse`)

函数 `CSSLengthParser::parse`（地址 `0x003a5080`）是 Falcon 将所有 CSS 距离转化为实际像素的枢纽。

#### 汇编指令所支持的合法单位全集：
通过对 `0x003a5080`~`0x003a5400` 代码段的逆向反汇编，确认底层直接匹配以下 16 进制 ASCII 双字节特征码：
- **`px`** (`0x7870`): 逻辑像素，1:1 直通映射；
- **`wx`** (`0x7877`): Weex 特殊逻辑单位（等价于 750px 设计稿基准下的缩放像素）；
- **`rpx`** (`"rpx"`): 微信规范响应式单位，在 Falcon 内部自动重写为 `wx` 算法；
- **`vw`** (`0x7776`): 视口宽度百分比单位（$1vw = 1\% \times \text{ViewportWidth}$）；
- **`vh`** (`0x6876`): 视口高度百分比单位（$1vh = 1\% \times \text{ViewportHeight}$）；
- **`%`** (`0x25`): 父节点相对百分比。

---

### 6.3 750px 设计稿缩放与 1020×240 物理屏幕几何坐标映射

#### 1. 750px 视口基准缩放公式
在移动端前端工程中，设计稿通常采用标准 `750px` 宽度制作。在 Falcon 内部，`WXInstance` 的基准设计视口设为 `mViewPort = 750.0f`。
任意声明了 `wx` 或启用设计稿缩放的长度计算公式为：
$$\text{ActualPx} = \text{DesignLength} \times \frac{\text{ScreenWidth}}{\text{mViewPort}} = \text{DesignLength} \times \frac{1020.0}{750.0} = \text{DesignLength} \times \mathbf{1.36}$$

> **开发规范建议**：在词典笔 MiniApp 中，**强烈建议开发者直接使用原生 `px` 单位**，以逻辑 `1020 × 240` 为精准像素基准进行绝对排版，避免因浮点缩放（1.36）产生 1px 细微边缘锯齿或亚像素渲染缝隙。

#### 2. 四层空间坐标变换矩阵与触控逆变换
有道词典笔硬件搭载的是物理竖屏面板（240 列 × 1020 行），但系统通过底层旋转 Blit 与触控逆变换，向上层呈现纯粹的 1020×240 横向逻辑空间：

```
                    ┌──────────────────────────────┐
                    │      物理屏幕 (240 × 1020)    │
                    │      X_raw ∈ [0, 240)        │
                    │      Y_raw ∈ [0, 1020)       │
                    └──────────────┬───────────────┘
                                   │
      触控驱动逆变换 (I2C AXS15205)│ 旋转光栅化 Blit (NEON 汇编)
      winInputLoop @ 0x00224b10    │ yd_l_rotate90_S32 @ 0x0045f210
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │      逻辑屏幕 (1020 × 240)   │
                    │      X_log ∈ [0, 1020)       │
                    │      Y_log ∈ [0, 240)        │
                    └──────────────────────────────┘
```

- **正向渲染旋转变换 (Skia 画布到物理显存)**:
  上层在 $1020 \times 240$ 的离屏 `SkBitmap` 绘制，刷新时由 ARM NEON SIMD 汇编 `yd_l_rotate90_S32` 实施逆时针 90°（或顺时针 270°）硬件级像素转置复制到 `/dev/fb0`。
- **逆向触控坐标映射 (物理触控芯片到 Vue 事件)**:
  底层通过 `tslib` 读取物理驱动直报坐标 $(X_{raw}, Y_{raw})$，在 `winInputLoop` 中转换为上层逻辑坐标 $(X_{log}, Y_{log})$：
  $$\begin{cases} X_{log} = \text{clamp}(1019 - Y_{raw}, 0, 1019) \\ Y_{log} = X_{raw} \end{cases}$$

---

## 7. 完整 TypeScript 类型定义 (`falcon-components.d.ts`)

为了在现代前端工程（Vite / Webpack / TSX）中开发 Falcon 原生 MiniApp 时享有完整的智能补全与语法检查，以下是 100% 契合 `libfalcon.so` 底层实现的 TypeScript 类型定义文件：

```typescript
/**
 * Youdao Dictionary Pen S7 Pro (Falcon / Weex NVue) Native Component Declarations
 * Target Device: NetEase Youdao S7 Pro (Cvitek CV1813H ARM Cortex-A7 32-bit Linux)
 * Viewport: 1020px x 240px (Logical Landscape)
 */

declare namespace Falcon {
  // 基础通用 CSS 样式契约
  export interface CommonStyles {
    width?: number | string;
    height?: number | string;
    minWidth?: number | string;
    minHeight?: number | string;
    maxWidth?: number | string;
    maxHeight?: number | string;
    
    // Flexbox 布局
    flex?: number;
    flexDirection?: 'row' | 'column' | 'row-reverse' | 'column-reverse';
    justifyContent?: 'flex-start' | 'center' | 'flex-end' | 'space-between' | 'space-around';
    alignItems?: 'stretch' | 'flex-start' | 'center' | 'flex-end';
    alignSelf?: 'auto' | 'stretch' | 'flex-start' | 'center' | 'flex-end';
    alignContent?: 'flex-start' | 'center' | 'flex-end' | 'stretch';
    flexWrap?: 'nowrap' | 'wrap';
    flexGrow?: number;
    flexShrink?: number;
    flexBasis?: number | string;
    
    // 盒模型外边距与内边距
    margin?: number | string;
    marginTop?: number | string;
    marginRight?: number | string;
    marginBottom?: number | string;
    marginLeft?: number | string;
    padding?: number | string;
    paddingTop?: number | string;
    paddingRight?: number | string;
    paddingBottom?: number | string;
    paddingLeft?: number | string;
    
    // 边框与圆角
    borderWidth?: number | string;
    borderColor?: string;
    borderStyle?: 'solid' | 'dashed' | 'dotted';
    borderRadius?: number | string;
    borderTopLeftRadius?: number | string;
    borderTopRightRadius?: number | string;
    borderBottomLeftRadius?: number | string;
    borderBottomRightRadius?: number | string;
    
    // 背景与定位
    backgroundColor?: string;
    opacity?: number;
    position?: 'relative' | 'absolute';
    top?: number | string;
    right?: number | string;
    bottom?: number | string;
    left?: number | string;
    zIndex?: number;
    overflow?: 'visible' | 'hidden';
  }

  // 通用手势与触控事件负载
  export interface TouchDetail {
    pageX: number;
    pageY: number;
    screenX: number;
    screenY: number;
    identifier: number;
  }

  export interface TouchEvent {
    type: string;
    target: any;
    timestamp: number;
    touches: TouchDetail[];
    changedTouches: TouchDetail[];
  }

  // <scroller> 容器事件与属性
  export interface ScrollerProps {
    scrollDirection?: 'horizontal' | 'vertical';
    showScrollbar?: boolean;
    scrollable?: boolean;
    offsetAccuracy?: number;
    loadmoreoffset?: number;
    upperThreshold?: number;
    lowerThreshold?: number;
    scrollEventInterval?: number;
    style?: CommonStyles;
    
    onScroll?: (e: { contentSize: { width: number; height: number }; contentOffset: { x: number; y: number } }) => void;
    onScrollstart?: (e: { contentOffset: { x: number; y: number } }) => void;
    onScrollend?: (e: { contentOffset: { x: number; y: number } }) => void;
    onLoadmore?: () => void;
    onScrolltoupper?: (e: { direction: string }) => void;
    onScrolltolower?: (e: { direction: string }) => void;
    onClick?: (e: TouchEvent) => void;
  }

  // <slider> 轮播组件属性与事件
  export interface SliderProps {
    vertical?: boolean | string;
    loop?: boolean | string;
    autoPlay?: boolean | string;
    interval?: number | string;
    currentIndex?: number | string;
    previousMargin?: number | string;
    nextMargin?: number | string;
    showIndicators?: boolean | string;
    itemColor?: string;
    itemSelectedColor?: string;
    style?: CommonStyles;
    
    onChange?: (e: { index: number }) => void;
    onScroll?: (e: { progress: number }) => void;
  }

  // <image> 组件属性与事件
  export interface ImageProps {
    src: string;
    resize?: 'contain' | 'cover' | 'stretch';
    cacheable?: boolean;
    style?: CommonStyles;
    
    onLoad?: (e: { naturalWidth: number; naturalHeight: number }) => void;
    onError?: (e: { errMsg: string }) => void;
    onClick?: (e: TouchEvent) => void;
  }

  // <text> 文本组件样式与属性
  export interface TextStyles extends CommonStyles {
    color?: string;
    fontSize?: number | string;
    fontWeight?: 'normal' | 'bold' | '100' | '200' | '300' | '400' | '500' | '600' | '700' | '800' | '900';
    fontStyle?: 'normal' | 'italic';
    fontFamily?: string;
    textAlign?: 'left' | 'center' | 'right';
    lineHeight?: number | string;
    letterSpacing?: number | string;
    textDecoration?: 'none' | 'underline' | 'line-through';
    textOverflow?: 'clip' | 'ellipsis' | 'marquee';
    lines?: number;
    marqueeSpeed?: number;
    marqueeGap?: number;
  }

  export interface TextProps {
    value?: string;
    style?: TextStyles;
    onClick?: (e: TouchEvent) => void;
  }

  // <input> 单行输入框组件
  export interface InputProps {
    type?: 'text' | 'password' | 'number';
    value?: string;
    placeholder?: string;
    placeholderColor?: string;
    maxLength?: number;
    autofocus?: boolean;
    disabled?: boolean;
    style?: TextStyles;
    
    onInput?: (e: { value: string }) => void;
    onChange?: (e: { value: string }) => void;
    onFocus?: () => void;
    onBlur?: () => void;
    onReturn?: (e: { value: string }) => void;
  }
}

// 扩展 Vue 模板标签识别
declare module 'vue/types/jsx' {
  interface IntrinsicElements {
    div: { style?: Falcon.CommonStyles; class?: string | string[]; [key: string]: any };
    scroller: Falcon.ScrollerProps & { class?: string | string[]; [key: string]: any };
    slider: Falcon.SliderProps & { class?: string | string[]; [key: string]: any };
    image: Falcon.ImageProps & { class?: string | string[]; [key: string]: any };
    text: Falcon.TextProps & { class?: string | string[]; [key: string]: any };
    input: Falcon.InputProps & { class?: string | string[]; [key: string]: any };
  }
}
```

---

## 8. 生产级端侧示例工程 (NVue 全特性页面)

以下为完整兼容 Falcon 原生特性的生产级 Vue 2.6 单文件组件（`S7ProMasterDashboard.vue`）。该组件涵盖了横向 `<scroller>`、卡片 `<slider>`、带圆角剪裁的 `<image>`、跑马灯 `<text>` 以及原生事件交互：

```html
<template>
  <div class="root-container">
    <!-- 顶部状态栏区域 (高 36px) -->
    <div class="status-bar">
      <div class="battery-group">
        <text class="status-brand">YOUDAO S7 PRO</text>
        <text class="status-sub">NVUE 2.6 NATIVE</text>
      </div>
      <!-- 跑马灯滚动通知栏：利用 Falcon 原生 text-overflow: marquee -->
      <div class="notice-ticker">
        <text class="notice-text">当前电量: 98% | 设备握持形态: 横屏模式 (1020x240) | 物理渲染刷新率: 60FPS 锁定</text>
      </div>
      <div class="time-group">
        <text class="status-time">{{ currentTime }}</text>
      </div>
    </div>

    <!-- 主展示区：横向划分为左右双面板 -->
    <div class="main-body">
      <!-- 左面板 (宽 320px)：垂直卡片轮播 Slider -->
      <slider 
        class="left-slider" 
        vertical="true" 
        auto-play="true" 
        interval="3500" 
        loop="true" 
        @change="onSliderChange"
      >
        <div v-for="(card, idx) in carouselCards" :key="idx" class="slider-page">
          <image class="card-hero-img" :src="card.image" resize="cover"></image>
          <div class="card-overlay">
            <text class="card-hero-title">{{ card.title }}</text>
            <text class="card-hero-subtitle">{{ card.desc }}</text>
          </div>
        </div>
      </slider>

      <!-- 右面板 (宽 670px)：横向高速物理滚动卡片流 Scroller -->
      <scroller 
        class="right-scroller" 
        scroll-direction="horizontal" 
        show-scrollbar="false" 
        offset-accuracy="5" 
        @scroll="onScrollerScroll"
      >
        <div 
          v-for="(item, index) in featureItems" 
          :key="index" 
          class="feature-card" 
          @click="handleFeatureClick(item, index)"
        >
          <div class="card-icon-wrapper">
            <image class="card-icon" :src="item.icon" resize="contain"></image>
          </div>
          <div class="card-content">
            <text class="feature-title">{{ item.name }}</text>
            <text class="feature-tag">{{ item.status }}</text>
            <text class="feature-metrics">{{ item.metrics }}</text>
          </div>
        </div>
      </scroller>
    </div>

    <!-- 底部微型操作栏 (高 24px) -->
    <div class="footer-bar">
      <text class="footer-hint">滑动右侧卡片探索功能 | 当前活动页: {{ activeSliderIndex + 1 }}/3</text>
      <div class="action-btn" @click="handleSystemBack">
        <text class="btn-text">返回主桌面</text>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      currentTime: "10:42",
      activeSliderIndex: 0,
      carouselCards: [
        {
          title: "离线 NMT 神经翻译",
          desc: "双擎离线神经网络极速解析",
          image: "file:///usr/bin/miniapp/resources/img_nmt.png"
        },
        {
          title: "硬件 OCR 扫描头",
          desc: "全局快门 CMOS 60FPS 实时字符切分",
          image: "file:///usr/bin/miniapp/resources/img_ocr.png"
        },
        {
          title: "低功耗协处理机制",
          desc: "1.0GHz ARM A7 极度节能冷启动",
          image: "file:///usr/bin/miniapp/resources/img_hal.png"
        }
      ],
      featureItems: [
        { name: "CPU 主频", status: "NORMAL", metrics: "1.0 GHz", icon: "file:///usr/bin/miniapp/resources/cpu.png" },
        { name: "物理帧率", status: "LOCKED", metrics: "60 FPS", icon: "file:///usr/bin/miniapp/resources/fps.png" },
        { name: "Skia 2D", status: "ACTIVE", metrics: "ARGB8888", icon: "file:///usr/bin/miniapp/resources/skia.png" },
        { name: "触控通道", status: "EVENT3", metrics: "AXS15205", icon: "file:///usr/bin/miniapp/resources/touch.png" },
        { name: "声学引擎", status: "READY", metrics: "16K PCM", icon: "file:///usr/bin/miniapp/resources/audio.png" },
        { name: "闪存配额", status: "HEALTH", metrics: "8 GB", icon: "file:///usr/bin/miniapp/resources/flash.png" }
      ]
    };
  },
  mounted() {
    console.log("[S7ProMasterDashboard] Native Falcon Mount Done");
  },
  methods: {
    onSliderChange(e) {
      this.activeSliderIndex = e.index;
      console.log("[Slider] Switched to index:", e.index);
    },
    onScrollerScroll(e) {
      // e.contentOffset.x 反映当前横向滚动位移
      if (Math.abs(e.contentOffset.x) % 100 === 0) {
        console.log("[Scroller] Offset X:", e.contentOffset.x);
      }
    },
    handleFeatureClick(item, index) {
      console.log("[Card Click] Activated item:", item.name);
    },
    handleSystemBack() {
      if (this.$page && this.$page.finish) {
        this.$page.finish();
      }
    }
  }
};
</script>

<style scoped>
/* 根视口严格锁定逻辑屏幕：宽 1020px，高 240px */
.root-container {
  width: 1020px;
  height: 240px;
  background-color: #0A0D14;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
  margin: 0;
}

/* 顶部状态栏 (高 36px) */
.status-bar {
  width: 1020px;
  height: 36px;
  background-color: #121722;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding-left: 16px;
  padding-right: 16px;
  border-bottom-width: 1px;
  border-bottom-color: #1F2838;
}

.battery-group {
  flex-direction: row;
  align-items: center;
  width: 220px;
}

.status-brand {
  color: #00E676;
  font-size: 14px;
  font-weight: bold;
}

.status-sub {
  color: #78909C;
  font-size: 11px;
  margin-left: 8px;
}

/* 跑马灯公告文本：启用原生 text-overflow: marquee */
.notice-ticker {
  width: 580px;
  height: 26px;
  justify-content: center;
}

.notice-text {
  color: #B0BEC5;
  font-size: 12px;
  lines: 1;
  text-overflow: marquee;
  marquee-speed: 45;
  marquee-gap: 80;
}

.time-group {
  width: 120px;
  flex-direction: row;
  justify-content: flex-end;
}

.status-time {
  color: #FFFFFF;
  font-size: 14px;
  font-weight: bold;
}

/* 中部核心展示区 (高 176px) */
.main-body {
  width: 1020px;
  height: 176px;
  flex-direction: row;
  padding: 8px 12px;
}

/* 左侧垂直卡片轮播 (320px x 160px) */
.left-slider {
  width: 310px;
  height: 160px;
  background-color: #161C28;
  border-radius: 8px;
  overflow: hidden;
}

.slider-page {
  width: 310px;
  height: 160px;
  position: relative;
}

.card-hero-img {
  width: 310px;
  height: 160px;
}

.card-overlay {
  position: absolute;
  left: 0;
  bottom: 0;
  width: 310px;
  height: 60px;
  background-color: rgba(10, 13, 20, 0.82);
  padding: 6px 12px;
  flex-direction: column;
  justify-content: center;
}

.card-hero-title {
  color: #40C4FF;
  font-size: 14px;
  font-weight: bold;
}

.card-hero-subtitle {
  color: #CFD8DC;
  font-size: 11px;
  margin-top: 2px;
  lines: 1;
  text-overflow: ellipsis;
}

/* 右侧横向惯性物理滚动列表 (670px x 160px) */
.right-scroller {
  width: 674px;
  height: 160px;
  flex-direction: row;
  margin-left: 12px;
}

.feature-card {
  width: 154px;
  height: 160px;
  background-color: #161C28;
  border-radius: 8px;
  border-width: 1px;
  border-color: #232C3E;
  margin-right: 12px;
  padding: 12px 10px;
  flex-direction: column;
  justify-content: space-between;
}

.card-icon-wrapper {
  width: 38px;
  height: 38px;
  background-color: #20293A;
  border-radius: 6px;
  justify-content: center;
  align-items: center;
}

.card-icon {
  width: 24px;
  height: 24px;
}

.card-content {
  flex-direction: column;
}

.feature-title {
  color: #ECEFF1;
  font-size: 13px;
  font-weight: bold;
}

.feature-tag {
  color: #00E676;
  font-size: 10px;
  margin-top: 4px;
}

.feature-metrics {
  color: #90A4AE;
  font-size: 11px;
  margin-top: 2px;
}

/* 底部功能条 (高 24px) */
.footer-bar {
  width: 1020px;
  height: 28px;
  background-color: #0D1017;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding-left: 16px;
  padding-right: 16px;
  border-top-width: 1px;
  border-top-color: #171E2C;
}

.footer-hint {
  color: #546E7A;
  font-size: 10px;
}

.action-btn {
  height: 20px;
  padding-left: 10px;
  padding-right: 10px;
  background-color: #263238;
  border-radius: 4px;
  justify-content: center;
  align-items: center;
}

.btn-text {
  color: #00E676;
  font-size: 10px;
  font-weight: bold;
}
</style>
```
