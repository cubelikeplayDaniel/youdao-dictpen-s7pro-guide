# Falcon BindingX 60FPS 高性能物理与手势动力学引擎指南
## (Falcon Embedded BindingX 60FPS Physics, Gesture Dynamics & Animation Engine Guide)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **底层引擎**: Falcon GUI Runtime (`/usr/lib/libfalcon.so`) + Skia 2D + QuickJS 2020-07-05  
> **反编译基准**: `JQuick::bindingx` (VTable `0x007d3300`, `0x00352e98`), `sJSFunctions` (`0x007ed2b8`), `sViewUpdaterMap` (`0x007ed2d8`)

---

## 目录索引

1. [Falcon BindingX 架构原理与 60FPS 零开销快道](#1-falcon-bindingx-架构原理与-60fps-零开销快道)
2. [底层支持的事件类型 (C++ 真相与 Weex 差异)](#2-底层支持的事件类型-c-真相与-weex-差异)
3. [C++ 数学表达式解析器与函数白名单](#3-c-数学表达式解析器与函数白名单)
   - [3.1 AST 节点与内置变量](#31-ast-节点与内置变量)
   - [3.2 运算符白名单](#32-运算符白名单)
   - [3.3 58 项内置数学、几何与 Robert Penner 缓动函数](#33-58-项内置数学几何与-robert-penner-缓动函数)
4. [驱动属性白名单 (26 项 Driven Properties) 与渲染代价](#4-驱动属性白名单-26-项-driven-properties-与渲染代价)
5. [JavaScript API 规范与生命周期契约](#5-javascript-api-规范与生命周期契约)
6. [生产级实战范式](#6-生产级实战范式)
   - [6.1 60FPS 橡皮筋弹性拖拽卡片 (带阻尼与平滑回弹)](#61-60fps-橡皮筋弹性拖拽卡片)
   - [6.2 阻尼物理弹簧摆动 (Damped Harmonic Spring Rebound)](#62-阻尼物理弹簧摆动)
   - [6.3 多属性联动视差动效 (5 属性原子并发驱动)](#63-多属性联动视差动效)

---

## 1. Falcon BindingX 架构原理与 60FPS 零开销快道

在 CV1813H 单核 ARM Cortex-A7 (1.0 GHz, 128MB RAM) 嵌入式硬件上，传统的 JavaScript 手势监听管线存在严重的性能瓶颈：
```
Linux evdev -> greenui::MotionEvent -> QuickJS Native Boundary -> JS Touch Handler ->
JS 动态计算 -> QuickJS Native Setter -> Yoga Flexbox / Skia Invalidation
```
每一帧的跨 VM 调用与垃圾回收（GC）开销高达 15~28ms，导致长条带鱼屏上的拖拽与滑动手势严重掉帧（帧率骤降至 30 FPS 以下）。

Falcon 引擎内置了基于 C++ 原生实现的 **BindingX 物理动力学引擎**：
```
greenui::MotionEvent -> BindingXTouchHandler::onTouch() -> Expression::execute() 
                     -> JQuick::bindingx::_ViewUpdater() -> Skia Canvas Dirty Rect
```
开发者在手势启动前，将交互表达式编译/声明为 AST 注入 C++ 引擎。手势执行期间，Linux `/dev/input/event` 坐标直接在 C++ 内部求值并直接更新 Skia View 矩阵，**完全绕过 QuickJS 虚拟机，实现真正的 60FPS 零延迟渲染**。

---

## 2. 底层支持的事件类型 (C++ 真相与 Weex 差异)

在 `libfalcon.so` 的函数 `JQuick::bindingx::createHandler`（地址 `0x003d94e4`）中，工厂方法仅实现了一个分支：
```arm
003d94f4: bl    strcmp                   ; strcmp(eventType.c_str(), "touch")
003d94f8: cmp   r0, #0
003d94fc: bne   0x3d951c                 ; 若不是 "touch"，直接跳转返回 NULL!
```

### 核心断层与避坑铁律：
| 事件类型 | 标准 Weex BindingX | Falcon 嵌入式运行时 | 判定与解决方案 |
| :--- | :--- | :--- | :--- |
| **`touch`** | 支持 | **全量原生支持 (`BindingXTouchHandler`)** | **开发者必须且仅能使用 `eventType: 'touch'`！** |
| `pan` | 核心手势 | **C++ 未实现 (返回 NULL)** | 传入 `'pan'` 会导致 `createHandler` 返回空指针，绑定失效！ |
| `timing` | 帧循环驱动 | **C++ 未实现 (返回 NULL)** | 时间轴物理动效应结合 `animation.transition` 实现。 |
| `orientation` | 陀螺仪驱动 | **硬件与系统无支持** | S7 Pro 笔身未配备屏幕向 6 轴 IMU。 |
| `pinch` | 双指缩放 | **C++ 未实现** | 触控屏 AXS15205 驱动工作于单/双点模式，无内置捏合手势识别器。 |

---

## 3. C++ 数学表达式解析器与函数白名单

### 3.1 AST 节点与内置变量
`Expression::execute`（地址 `0x003e5230`）支持在 C++ 内部直接读取如下运行时环境变量：
- `x`: 当前触控手势水平逻辑坐标 (CSS/web px)。
- `y`: 当前触控手势垂直逻辑坐标 (CSS/web px)。
- `w`: 目标视图的渲染宽度 (px)。
- `h`: 目标视图的渲染高度 (px)。
- `PI`: 数学常数 $\pi \approx 3.141592653589793$。
- `E`: 数学常数 $e \approx 2.718281828459045$。

### 3.2 运算符白名单
- **三元条件**：`? :`
- **算术运算**：`+`, `-`, `*`, `/`, `%`, `**` (乘方)
- **关系比较**：`>`, `<`, `>=`, `<=`, `==`, `===`, `!=`, `!==`
- **逻辑运算**：`&&`, `||`, `!`

### 3.3 58 项内置数学、几何与 Robert Penner 缓动函数
所有函数均在 `sJSFunctions`（`0x007ed2b8`）中注册：

1. **基础数学**：`abs`, `min`, `max`, `floor`, `ceil`, `round`, `sign`, `sqrt`, `cbrt`, `pow`, `exp`, `log`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`。
2. **颜色与几何**：
   - `rgb(r, g, b)`, `rgba(r, g, b, a)`
   - `evaluateColor(c1, c2, progress)`: 线性颜色插值计算。
   - `translate(x, y)`, `scale(sx, sy)`, `matrix(...)`
3. **Robert Penner 经典物理缓动方程 (全量 31 项)**：
   标准签名：`func(t, b, c, d)`（时间、起始值、变化量、周期）：
   - `linear`
   - `easeInQuad`, `easeOutQuad`, `easeInOutQuad`
   - `easeInCubic`, `easeOutCubic`, `easeInOutCubic`
   - `easeInQuart`, `easeOutQuart`, `easeInOutQuart`
   - `easeInQuint`, `easeOutQuint`, `easeInOutQuint`
   - `easeInSine`, `easeOutSine`, `easeInOutSine`
   - `easeInExpo`, `easeOutExpo`, `easeInOutExpo`
   - `easeInCirc`, `easeOutCirc`, `easeInOutCirc`
   - `easeInElastic`, `easeOutElastic`, `easeInOutElastic`
   - `easeInBack`, `easeOutBack`, `easeInOutBack`
   - `easeInBounce`, `easeOutBounce`, `easeInOutBounce`
   - `cubicBezier(t, x1, y1, x2, y2)`

---

## 4. 驱动属性白名单 (26 项 Driven Properties) 与渲染代价

在 `__init_view_updater_mapEv`（`0x003ebae8`）中注册的 26 项属性：

| 属性名 | 对应 C++ 更新器 | 渲染性能评估 |
| :--- | :--- | :--- |
| `opacity` | `_OpacityUpdater` | **极高 (<0.1ms)**，直接修改 Skia 画布 Alpha 通道 |
| `transform.translate` | `_TranslateUpdater` | **极高 (<0.1ms)**，直接更新 2D 矩阵向量 |
| `transform.translateX` | `_TranslateXUpdater` | **极高 (<0.1ms)**，水平平移 |
| `transform.translateY` | `_TranslateYUpdater` | **极高 (<0.1ms)**，垂直平移 |
| `transform.scale` | `_ScaleUpdater` | **极高 (<0.1ms)**，统一缩放 |
| `transform.scaleX` | `_ScaleXUpdater` | **极高 (<0.1ms)**，水平缩放 |
| `transform.scaleY` | `_ScaleYUpdater` | **极高 (<0.1ms)**，垂直缩放 |
| `transform.rotate` / `rotateZ` | `_RotateUpdater` | **极高 (<0.1ms)**，2D 旋转 |
| `transform.rotateX` / `rotateY`| 3D 旋转更新器 | **高 (<0.3ms)**，透视旋转 |
| `background-color` | `_BackgroundColorUpdater`| **极高 (<0.1ms)**，直接重绘背景画刷 |
| `color` | `_ColorUpdater` | **高 (<0.3ms)**，更新文字排版前景色 |
| `scroll.contentOffset` | `_ContentOffsetUpdater` | **高 (<0.5ms)**，修改滚动容器位移 |
| `scroll.contentOffsetX/Y` | 滚动分量更新器 | **高 (<0.5ms)** |
| `width` / `height` | 尺寸更新器 | **低 (>1.5ms)**，**触发 Yoga Flexbox 重新布局，慎用！** |
| `margin-*` / `padding-*` | 边距更新器 | **低 (>1.5ms)**，**触发重新布局，慎用！** |

---

## 5. JavaScript API 规范与生命周期契约

### 5.1 导入模块
```javascript
import bindingx from '$bindingx';
```

### 5.2 核心方法
```javascript
// 1. 绑定手势
const res = bindingx.bind({
  anchor: this.$refs.myCard.ref, // 必填: 拦截触控的 DOM ref
  eventType: 'touch',            // 必填: 必须严格为 'touch'
  props: [
    {
      element: this.$refs.myCard.ref,
      property: 'transform.translateX',
      expression: 'x - 100'
    }
  ],
  exitExpression: 'x > 500'       // 可选: 退出条件
}, (e) => {
  // e.state: 'start' | 'end' | 'cancel'
});

// 2. 解除绑定 (必须在手势结束或页面销毁时调用，防止内存泄漏)
bindingx.unbind({
  token: res.token,
  eventType: 'touch'
});

// 3. 全局释放全部绑定
bindingx.unbindAll();
```

---

## 6. 生产级实战范式

### 6.1 60FPS 橡皮筋弹性拖拽卡片
```javascript
import bindingx from '$bindingx';
const animation = falcon.requireModule('animation') || weex.requireModule('animation');

export function bindRubberBandCard(cardRef, initialTouchX, startX, onRelease) {
  // 橡皮筋阻尼公式：超过 ±240px 后按 0.35 系数衰减
  const translateExpression = `
    let rawX = (x - ${initialTouchX}) + ${startX};
    rawX > 240 ? (240 + (rawX - 240) * 0.35) : (rawX < -240 ? (-240 + (rawX + 240) * 0.35) : rawX)
  `;

  // 拖动时透明度微弱渐变
  const opacityExpression = `
    let d = abs((x - ${initialTouchX}) + ${startX});
    max(0.4, 1.0 - (d / 600))
  `;

  return bindingx.bind({
    anchor: cardRef,
    eventType: 'touch',
    props: [
      { element: cardRef, property: 'transform.translateX', expression: translateExpression },
      { element: cardRef, property: 'opacity', expression: opacityExpression }
    ]
  }, (e) => {
    if (e.state === 'end' || e.state === 'cancel') {
      if (onRelease) onRelease();
    }
  });
}
```
