# 有道词典笔 S7 Pro 原生 MiniApp 全景踩坑排错与避坑防御指南
## (Falcon MiniApp Pitfalls, Edge Cases & Failure Prevention Manual)

> **目标**：本文档旨在系统化地揭露在有道词典笔 S7 Pro（硬件平台 CV1813H ARM Cortex-A7 Linux，GUI 引擎 Falcon + QuickJS 20200705 + Skia 2D + Yoga Flexbox）上开发第三方原生应用时，**一切可能导致应用加载失败、布局崩溃、白屏闪退、触控错位、硬件死锁或桌面不显示的底层陷阱与断层**，并提供经底层反汇编验证的官方级确定性解决方案与标准防错代码范式。

---

## 目录索引

1. [模块导出与入口契约陷阱 (`app.js` & `index.js`)](#1-模块导出与入口契约陷阱)
2. [长条带鱼屏物理/逻辑坐标系与画布双重旋转陷阱](#2-长条带鱼屏物理逻辑坐标系与画布双重旋转陷阱)
3. [触控数字化仪 (Digitizer) 空间逆变换与事件穿透陷阱](#3-触控数字化仪-digitizer-空间逆变换与事件穿透陷阱)
4. [双轨音频架构与 ALSA 独占声卡死锁陷阱](#4-双轨音频架构与-alsa-独占声卡死锁陷阱)
5. [跨进程 RPC 通信与 Provider 回调包装陷阱](#5-跨进程-rpc-通信与-provider-回调包装陷阱)
6. [网络通信缺失浏览器 Web API (fetch/WebSocket) 陷阱](#6-网络通信缺失浏览器-web-api-陷阱)
7. [CSS / Yoga Flexbox 不支持属性导致的布局崩溃陷阱](#7-css--yoga-flexbox-不支持属性导致的布局崩溃陷阱)
8. [Launcher 桌面卡片滑块白名单过滤与图标丢失陷阱](#8-launcher-桌面卡片滑块白名单过滤与图标丢失陷阱)
9. [内核电源管理、屏幕超时休眠与触摸挂起陷阱](#9-内核电源管理屏幕超时休眠与触摸挂起陷阱)
10. [本地持久化沙箱限制与 SQLite 文件路径陷阱](#10-本地持久化沙箱限制与-sqlite-文件路径陷阱)
11. [硬件按键与笔头微动事件大小写及拼写断层陷阱 (`buttonEvent`)](#11-硬件按键与笔头微动事件大小写及拼写断层陷阱)
12. [双指捏合手势缺失与 AXS15205 触控槽位钳位陷阱](#12-双指捏合手势缺失与-axs15205-触控槽位钳位陷阱)
13. [窗口管理器全屏强制与透明穿透陷阱 (WindowManager Stacking)](#13-窗口管理器全屏强制与透明穿透陷阱)
14. [物理马达缺失与触觉振动 API 假象陷阱](#14-物理马达缺失与触觉振动-api-假象陷阱)
15. [系统剪贴板服务缺失与跨进程数据交换陷阱](#15-系统剪贴板服务缺失与跨进程数据交换陷阱)
16. [Falcon Yoga 布局引擎 `<scroller>` 弹性方向降级与横向滚动单列崩塌陷阱](#16-falcon-yoga-布局引擎-scroller-弹性方向降级与横向滚动单列崩塌陷阱)
17. [低 DPI 屏幕浮点缩放导致的严重摩尔纹与软采样虚边陷阱](#17-低-dpi-屏幕浮点缩放导致的严重摩尔纹与软采样虚边陷阱)
18. [Cortex-A7 软解 WebP 性能瓶颈与端侧多进程转码架构陷阱](#18-cortex-a7-软解-webp-性能瓶颈与端侧多进程转码架构陷阱)
19. [高频触控滚动下的 VNode Diff 性能雪崩与滑动顿挫陷阱](#19-高频触控滚动下的-vnode-diff-性能雪崩与滑动顿挫陷阱)
20. [单双击冲突与侧滑返回多模手势状态机消解陷阱](#20-单双击冲突与侧滑返回多模手势状态机消解陷阱)
21. [USB MTP 目录沙箱可见性、目录指纹缓存与冷启动延迟陷阱](#21-usb-mtp-目录沙箱可见性目录指纹缓存与冷启动延迟陷阱)

---

## 1. 模块导出与入口契约陷阱

### 1.1 致命现象
- 执行 `miniapp_cli start <AppID>` 时，日志打印：
  ```text
  ReferenceError: 'App' is not defined at app.js:1
  TypeError: not a function at launchApp (jsfm-nvue.js:4807)
  ```
  或者在加载首页时：
  ```text
  ReferenceError: 'Page' is not defined at index.js:1
  TypeError: not a function at loadPage (jsfm-nvue.js:4920)
  ```

### 1.2 底层根因逆向剖析
在传统的微信小程序中，`App({...})` 和 `Page({...})` 是注入到全局命名空间（Global Scope）的构造函数。然而，在 Falcon 运行时中：
1. Falcon 底层的 `qjsc` 编译器使用 `-m`（ES Module 模式）将 JS 文件编译为 QuickJS 字节码（`BC_TAG_MODULE = 0x0f`）。
2. 在 ES Module 隔离作用域中，全局对象受到严格保护，Falcon **根本没有将 `App` 或 `Page` 注入全局变量**。
3. 运行时加载应用时，`jsfm-nvue.js` 的 `launchApp` 会检查模块的导出对象：
   - 方式 A：检查 `export default` 是否继承自 `$falcon.App` 或为包含生命周期的普通配置对象。
   - 方式 B：检查导出对象中的 `__AppClazz`。
   如果应用代码直接执行 `App({...})`，QuickJS 在顶层执行该未定义函数调用，立即抛出 `ReferenceError`，导致应用启动瞬间崩溃。

### 1.3 确定性防错范式

#### `app.js` 标准规范
```javascript
export default class CustomApp extends $falcon.App {
  onLaunch(options) {
    console.log('[App] onLaunch triggered, options:', JSON.stringify(options));
  }
  onShow() {
    console.log('[App] onShow triggered');
  }
  onHide() {
    console.log('[App] onHide triggered');
  }
  onDestroy() {
    console.log('[App] onDestroy triggered');
  }
}
```

#### `index.js` 标准规范
```javascript
const RootComponent = {
  data() {
    return {
      title: 'Falcon Native MiniApp'
    };
  },
  methods: {
    handleBack() {
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      } else if (typeof $falcon !== 'undefined' && $falcon.closeApp) {
        $falcon.closeApp();
      }
    }
  },
  render(h) {
    return h('div', {
      style: {
        width: '1020px',
        height: '240px',
        backgroundColor: '#000000',
        flexDirection: 'column'
      }
    }, [
      h('text', { style: { color: '#FFFFFF', fontSize: '24px' } }, this.title)
    ]);
  }
};

export default class IndexPage extends $falcon.Page {
  onLoad(query) {
    console.log('[Page] onLoad', query);
  }
  onShow() {
    console.log('[Page] onShow');
    if (typeof $falcon !== 'undefined' && $falcon.keepScreenOn) {
      $falcon.keepScreenOn(true);
    }
  }
  onHide() {
    console.log('[Page] onHide');
    if (typeof $falcon !== 'undefined' && $falcon.keepScreenOn) {
      $falcon.keepScreenOn(false);
    }
  }
  onDestroy() {
    console.log('[Page] onDestroy');
  }
}

if (typeof $falcon !== 'undefined' && $falcon.Page && typeof $falcon.Page.setRootComponent === 'function') {
  $falcon.Page.setRootComponent(RootComponent);
}
```

---

## 2. 长条带鱼屏物理/逻辑坐标系与画布双重旋转陷阱

### 2.1 致命现象
- 应用界面在词典笔上旋转了 90° 或 270°，只显示局部且上下黑边；或者应用开发者在 CSS 中加入了 `transform: rotate(270deg)` 试图修正画面，导致界面完全跑飞或触控完全对不上。

### 2.2 底层根因逆向剖析
词典笔的物理 LCD 屏为标准的 **240 (宽) × 1020 (高)** 竖屏。
在 `libfalcon.so` 的渲染合成层中：
1. Falcon 在 C++ 层通过 ARM NEON SIMD 指令集（函数 `l_rotate90_S32_neon`，地址 `0x00229468`）在将 DisplayList 栅格化提交到 `/dev/fb0` 时，**自动执行了 270° 硬件级显存旋转**！
2. 因此，JavaScript 与 CSS 的逻辑视口标准尺寸**必须严格设计为 1020px (宽) × 240px (高)**。
3. 如果开发者在 CSS 中擅自增加 `rotate(90deg)` 或 `rotate(270deg)`，就会发生**双重旋转（Double Rotation）**，画面变成倒立或竖向裁剪。

### 2.3 确定性防错范式
- **UI 布局原则**：永远以 `1020px` 宽、`240px` 高作为根容器尺寸。
- **严禁根容器旋转**：绝不要在顶层容器使用 CSS `transform: rotate(...)`。

---

## 3. 触控数字化仪 (Digitizer) 空间逆变换与事件穿透陷阱

### 3.1 致命现象
- 自动化测试时注入 `/dev/input/event` 坐标，点击完全不生效；或者手指点击屏幕左侧，按钮在右侧响应。

### 3.2 底层根因逆向剖析
在 `greenui::winInputLoop`（地址 `0x002275d4`）中，内核驱动直接上报的是触控 IC（AXS15205）的原始坐标（$X_{raw} \in [0, 239], Y_{raw} \in [0, 1019]$）。
Falcon 内部完成了空间仿射逆变换：
$$X_{log} = \text{clamp}(1019 - Y_{raw}, 0, 1019)$$
$$Y_{log} = X_{raw}$$

如果开发者编写自动化测试脚本向 Linux `/dev/input/event` 注入物理点击，必须严格使用上述逆公式：
$$X_{raw} = Y_{log}$$
$$Y_{raw} = \text{clamp}(1019 - X_{log}, 0, 1019)$$

---

## 4. 双轨音频架构与 ALSA 独占声卡死锁陷阱

### 4.1 致命现象
- 自研应用播放完一个点击音效后，背景音乐停止；或者背景音乐在播放时，按键音效引发整机系统静音，重启前无法发声。

### 4.2 底层根因逆向剖析
S7 Pro 采用双轨音频子系统，但底层 ALSA 只有一个 DAC 输出通道：
1. **长音频伴奏轨**：必须交由后台常驻微服务 `mediaPlayerService`（AppID: `8001650599023931`）。
2. **低延迟 UI 短音轨**：必须交由原生 C 模块 `'soundPlayer'`（基于 `tinyalsa` 极速输出）。
如果开发者使用 `soundPlayer` 播放几分钟的长 MP3，或者未调用 `quickStop()` 强制挂起底层 DMA 环形缓冲区，ALSA 硬件锁被独占，`mediaPlayerService` 将无法写入声卡，导致全局音频死锁。

---

## 5. 跨进程 RPC 通信与 Provider 回调包装陷阱

### 5.1 致命现象
- 自研应用向 `mediaPlayerService` 提供播放列表数据时，微服务报错：
  ```text
  [MediaPlayerService] LoadMedia failed: MediaStatus.Unknown (code: 9)
  ```

### 5.2 底层根因逆向剖析
微服务 RPC 协议要求 Provider 的 `cb` 必须传入二元数组：`cb([errCode, resultData])`，其中 `0` 表示成功。
如果直接写 `cb(data)`，系统会误将对象解释为非零错误码，判定拉取失败。

---

## 6. 网络通信缺失浏览器 Web API 陷阱

### 6.1 致命现象
- 报错 `fetch is not defined`, `XMLHttpRequest is not defined`, `WebSocket is not defined`。

### 6.2 底层根因逆向剖析
QuickJS 纯净内核不含浏览器 DOM/BOM 扩展。网络请求必须使用内建 C 模块：
- `import http from 'http';` (原生 HTTP/HTTPS 客户端)
- `import httpbridge from 'httpbridge';` (带网易有道 OpenAPI 签名的请求桥)
- `import net from 'net';` (TCP Socket 客户端)

---

## 7. CSS / Yoga Flexbox 不支持属性导致的布局崩溃陷阱

### 7.1 致命现象
- CSS 使用了 `calc()`、`display: grid`、`box-sizing: content-box`、`white-space: nowrap` 后，样式完全失效或页面整体坍塌。

### 7.2 底层根因逆向剖析
`JQuick::CSSStyleParser` 仅实现白名单 73 项属性。
1. **`calc()` 无法解析**：内部直接用 `strtof` 读取浮点，遇到 `calc` 无法匹配，回退为 `0` 或 `undefined`。
2. **`aspectRatio: 0` 崩溃**：Yoga 触发除零错误，计算结果为 `NaN`，导致整个视图树崩溃为零像素。
3. **文本换行控制**：不支持 `white-space`，必须使用 `<text>` 组件的 `lines: 1` 与 `text-overflow: ellipsis`。

---

## 8. Launcher 桌面卡片滑块白名单过滤与图标丢失陷阱

### 8.1 致命现象
- 应用安装成功，但词典笔桌面上完全找不到该应用卡片。

### 8.2 底层根因逆向剖析
桌面卡片渲染器 `LauncherPage.renderCardItem` 会严密过滤 `manifest.json`：
```json
{
  "props": {
    "addDesktop": {
      "apollo_platform": true,
      "y08_platform": true,
      "hermes_platform": true
    },
    "Icons": {
      "theme-y08": "app_icon.png",
      "theme-apollo": "app_icon.png"
    }
  }
}
```
缺少 `y08_platform: true` 的应用被判定为后台系统服务，桌面直接忽略该卡片。

---

## 9. 内核电源管理、屏幕超时休眠与触摸挂起陷阱

### 9.1 致命现象
- 用户正在阅读漫画，30 秒后屏幕自动变暗熄灭。

### 9.2 底层根因逆向剖析
系统默认无操作休眠时间为 30~60 秒。在阅读类应用中，必须在页面 `onShow` 时向系统申请常亮锁：
```javascript
if (typeof $falcon !== 'undefined' && $falcon.keepScreenOn) {
  $falcon.keepScreenOn(true);
}
```
并在 `onHide` 时释放 `keepScreenOn(false)`。

---

## 10. 本地持久化沙箱限制与 SQLite 文件路径陷阱

### 10.1 致命现象
- 写入数据库报错 `Permission Denied`。

### 10.2 底层根因逆向剖析
`/userdata/miniapp/data/mini_app/pkg/<AppID>/a/` 代码目录具有只读保护属性。
所有动态创建的 SQLite 数据库或本地缓存文件必须存放在：
- 私有数据目录：`/userdata/miniapp/data/mini_app/pkg/<AppID>/data/`
- 全局用户磁盘：`/userdisk/`

---

## 11. 硬件按键与笔头微动事件大小写及拼写断层陷阱

### 11.1 致命现象
- 监听笔尖离开纸面或电源键松开时，事件回调永远不被触发：
  ```javascript
  btn.on('headButtonRelease', () => { ... }); // 永远不响应！
  btn.on('powerButtonRelease', () => { ... }); // 永远不响应！
  ```

### 11.2 底层根因逆向剖析
在 `libjsapi_export_core.so`（地址 `0x000a014c`）的 C++ 反编译中，底层固件工程师存在**拼写遗漏历史遗留 Bug**：
1. **`headButtonRelese`**（注意：中间缺少字母 `a`）：笔头离开纸面信号名称。
2. **`powerButtonRelese`**（注意：中间缺少字母 `a`）：电源键松开信号名称。
3. **`volumeUpButtonRelese` / `volumeDownButtonRelese`**（注意：均缺少字母 `a`）。
4. 然而，在 Home 键和笔头取景键上，拼写又是正确的：
   - `homeButtonRelease`（带有字母 `a`）
   - `headCameraPreviewButtonRelease`（带有字母 `a`）

此外，**必须在页面 `mounted` 后显式调用 `btn.setButtonEventReady(true)`**！若未调用该方法，底层守护进程认为界面尚未渲染就绪，会丢弃所有的物理按键事件！

### 11.3 确定性防错范式
使用适配层同时监听规范拼写与历史底层拼写：
```javascript
import buttonEventModule from 'buttonEvent';

const btn = new buttonEventModule.ButtonEvent();
// 必须在 mounted 后通知就绪！
btn.setButtonEventReady(true);

// 笔尖下压
btn.headButtonPress.connect((name, time) => {
  console.log('笔尖触底按压');
});

// 笔尖抬起 (底层精确字段是 headButtonRelese，无 a)
const releaseSignal = btn.headButtonRelese || btn.headButtonRelease;
if (releaseSignal && releaseSignal.connect) {
  releaseSignal.connect((name, duration) => {
    console.log('笔尖松开，按压持续:', duration, 'ms');
  });
}
```

---

## 12. 双指捏合手势缺失与 AXS15205 触控槽位钳位陷阱

### 12.1 致命现象
- 在图片组件上绑定 `@pinch` 或试图用三指滑动截屏，手势完全无响应。

### 12.2 底层根因逆向剖析
反编译 `axs_ts.ko` 与 `libfalcon.so` 证实：
1. **硬件限制**：触控 IC（AXS15205）在内核驱动中仅开辟了 2 个硬件 Slot（`input_mt_init_slots(dev, 2, ...)`），三指及以上的报点被内核直接丢弃。
2. **引擎缺失**：Falcon 引擎内嵌的绿色手势探测器只有 `TapGestureDetector` 和 `FlingGestureDetector`，**原生完全没有实现任何双指捏合缩放（Pinch-to-zoom）手势识别器**。

### 12.3 确定性防错范式
如果要在图片查看器或漫画中支持双指缩放，必须在前端 `@touchstart` 与 `@touchmove` 中手动计算双指间距：
```javascript
handleTouchMove(e) {
  if (e.touches && e.touches.length === 2) {
    const dx = e.touches[0].pageX - e.touches[1].pageX;
    const dy = e.touches[0].pageY - e.touches[1].pageY;
    const distance = Math.sqrt(dx * dx + dy * dy);
    // 根据两帧 distance 差值计算缩放 scale
  }
}
```

---

## 13. 窗口管理器全屏强制与透明穿透陷阱

### 13.1 致命现象
- 开发者试图在 `manifest.json` 中配置 `"window": { "transparent": true }` 实现浮动透明小部件，安装后仍然是不透明黑屏。

### 13.2 底层根因逆向剖析
逆向 `greenui::WindowManager`（地址 `0x583d00`）与 `IotPackageManager` 证实：
1. **不支持清单透明配置**：所有第三方 MiniApp 窗口创建时强制赋予 `mLayer = 0, mFlags = 0`（全屏不透明）。
2. **下向遮挡剔除（Occlusion Culling）**：当顶层全屏应用处于活动状态时，WindowManager 在逆向遍历渲染窗口列表时，一旦遇到第一个不透明窗口，**立即中断下向遍历**。底层 Launcher 停止所有的绘制，CPU 开销与过度绘制降为零。
3. **结论**：所有弹窗、确认框或遮罩层必须作为**应用内 Vue 组件**渲染，严禁拆分为独立微应用进程。

---

## 14. 物理马达缺失与触觉振动 API 假象陷阱

### 14.1 致命现象
- 开发者试图调用 `vibrator.vibrate(100)` 实现触感反馈，抛出未定义异常。

### 14.2 底层根因逆向剖析
通过逆向固件设备树与内核符号表：
- **S7 Pro 内部根本没有配备线性马达（LRA）或转子马达（ERM）**！
- 系统所有的“触感反馈”完全是通过音频模拟的（Acoustic Feedback）。
- 每次笔尖触压或按钮点击，系统是通过 `soundPlayer` 播放一段短 PCM 音效。

### 14.3 确定性防错范式
```javascript
import soundPlayerModule from 'soundPlayer';
const sound = new soundPlayerModule.SoundPlayer();

function simulateHapticFeedback() {
  // 使用系统内置超低延迟短音效模拟按键触感
  sound.playFile('/system/media/audio/ui/click.wav', 0, 1.0, false, 0);
}
```

---

## 15. 系统剪贴板服务缺失与跨进程数据交换陷阱

### 15.1 致命现象
- 尝试使用 `clipboard.setText()` 或 `navigator.clipboard` 失败。

### 15.2 底层根因逆向剖析
S7 Pro 属于嵌入式专用 Linux 笔式设备，没有运行 X11/Wayland 或 Android `ClipboardService`，原生未提供 `clipboard` 模块。

### 15.3 确定性防错范式
使用 `storage` 键值存储构建应用间字符串交换总线：
```javascript
import { getStorage, setStorage } from 'storage';

// 写入模拟剪贴板
await setStorage('__clipboard__', copiedText);

// 读取模拟剪贴板
const text = await getStorage('__clipboard__');
```

---

## 16. Falcon Yoga 布局引擎 `<scroller>` 弹性方向降级与横向滚动单列崩塌陷阱

### 16.1 致命现象
- 当使用 `<scroller scroll-direction="horizontal">` 构建横向多列卡片时，新进入页面（首屏初次渲染）卡片呈现垂直单列排布，卡片沿 Y 轴堆叠导致上方内容超出屏幕顶端被截断；而在用户点击刷新按钮后才突然展开恢复为水平三列。

### 16.2 底层根因逆向剖析
- Falcon 的 `<scroller>` 组件底层由 C++ `greenui::ScrollView` 和 Facebook Yoga Flexbox 布局引擎驱动。
- 在 Yoga 引擎规范中，所有容器节点的内部布局主轴默认值为 `flex-direction: column`。
- 当 `<scroller scroll-direction="horizontal">` 直接挂载多个子节点且首帧测量阶段缺乏显式行级弹性容器时，Yoga 引擎将子节点直接置入垂直单列流；只有在后续触发 resize 或强制重绘时才发生二次计算。

### 16.3 确定性防错范式
在横向 `<scroller>` 内层**必须包裹显式声明了 `flex-direction: row` 的行容器 `<div>`**：
```javascript
h('scroller', {
  attrs: { 'scroll-direction': 'horizontal', 'show-scrollbar': false },
  style: { width: '972px', height: '212px', flexDirection: 'row' }
}, [
  h('div', {
    style: {
      flexDirection: 'row',
      alignItems: 'center',
      height: '212px'
    }
  }, items.map(item => h('div', { style: { width: '274px', height: '198px', marginRight: '18px' } })))
])
```

---

## 17. 低 DPI 屏幕浮点缩放导致的严重摩尔纹与软采样虚边陷阱

### 17.1 致命现象
- 图像在 1020×240 超宽带鱼屏上缩放显示时，网点严重干涉出现晃眼的波纹（摩尔纹 Moiré），漫画网点、文字边缘发虚发灰，极度影响阅读体验。

### 17.2 底层根因逆向剖析
- S7 Pro 屏幕物理点距较大（~110 DPI），底层使用 Skia 软光栅化进行绘制。
- 当高分辨率原图（如 1200×1800）被动态缩放到非整数倍或浮点列宽（如 470.5px）时，Skia 双线性下采样（Bilinear Filtering）在紧凑网点区域产生严重的走样失真与伪频信号。

### 17.3 确定性防错范式
严格执行 **474px 硬件点对点直通渲染（1:1 Pixel Mapping）**：
- 屏幕宽度 1020px，扣除左侧 48px 侧边栏与 24px 边距后，双列卡片单列锁定为严格的 **474px**。
- 图像在后台离线/端侧预处理时直接使用 NEON 加速的 `ffmpeg -vf 'scale=474:-1'` 抽样生成标准宽度图。
- 前端 `<image>` 锁定 `resize: 'cover'`，杜绝运行时任何二次缩放抗锯齿开销。

---

## 18. Cortex-A7 软解 WebP 性能瓶颈与端侧多进程转码架构陷阱

### 18.1 致命现象
- 导入 `.webp` 格式漫画或图集后，应用解析显示为 0 页，或尝试直接解码时整个应用长时间未响应（ANR）。

### 18.2 底层根因逆向剖析
- Falcon 内置的 Skia 裁剪掉了 WebP 编解码器（仅包含 PNG, JPEG, BMP），前端直接传入 `.webp` 文件路径会导致加载失败。
- 单核 Cortex-A7 @ 1.0 GHz 上纯 JS 或通用软件解码 WebP 极端缓慢（单张耗时 1.5s~3s）。

### 18.3 确定性防错范式
采用**端侧 Linux 守护进程协作 + 双转换进度条透明监控**架构：
1. 系统层运行独立守护脚本 `/userdisk/bin/webp_daemon.sh`，利用经过汇编优化的 `ffmpeg` 逐页将 `.webp` 转为 `.jpg` 并生成 474px 点对点直通缩略图。
2. 前端设立双独立进度条：**WebP 解码进度条**（青蓝色）与 **474px 点对点优化进度条**（琥珀色），通过 2 秒增量探测文件系统实现静默平滑轮询刷新。

---

## 19. 高频触控滚动下的 VNode Diff 性能雪崩与滑动顿挫陷阱

### 19.1 致命现象
- 列表包含上百张卡片或页面时，手指上下滑动出现明显的掉帧、停顿卡死，甚至滑动中触发进程崩溃（LMK 杀进程）。

### 19.2 底层根因逆向剖析
- Falcon 上的 QuickJS 为单线程解释执行。在 60Hz 触控滚动中，若在 `@scroll` 事件中高频更新响应式变量（如当前滚动绝对像素），会导致整个 VNode 树被重复比对 Diff，瞬间消耗完单核 CPU 时间片。

### 19.3 确定性防错范式
1. **$O(\log N)$ 二分查找绝对偏移**：预先计算所有行的高度的累积分布数组，滚动时使用二分法毫秒级检索可视区域首行索引。
2. **45px 步长门禁限频驱动**：仅当滚动位移增量超过 45px 时才更新响应式视图状态，其余微小微调直通底层原生 ScrollView。
3. **50ms 节流持久化**：进度写入 `$falcon.jsapi.storage` 严格通过 50ms Debounce 防抖，杜绝高频 I/O 阻塞。

---

## 20. 单双击冲突与侧滑返回多模手势状态机消解陷阱

### 20.1 致命现象
- 在阅读模式下，用户本想轻触图片返回上一层，却误触发了双击放大；或者想双击放大，却在第一次点击时立即退出到了书架。

### 20.2 底层根因逆向剖析
- 嵌入式触控屏由于手指面积与按压抖动，两次连击容易伴随数十像素的坐标位移，且点击间隔可能受到系统调度抖动影响（单核高负荷下主线程响应延迟）。

### 20.3 确定性防错范式
设计**多模手势消解状态机**：
1. **480ms 延时计时器与 95px 容差消解**：第一次触控抬起后，不立即触发单击返回，而是记录坐标并启动 480ms 定时器。若在 480ms 内且距离小于 95px 收到第二次触控，取消单击定时器并消费事件切换缩放倍率；超时才触发单击返回。
2. **边缘向右滑动最高优先级拦截**：在 `touchstart` 时判定 `pageX <= 108px`，一旦出现水平位移占优的向右滑动（$\Delta x \ge 36\text{px}$），立即拦截手势，层级式安全返回（单页 $\to$ 瀑布流 $\to$ 书架 $\to$ 桌面）。

---

## 21. USB MTP 目录沙箱可见性、目录指纹缓存与冷启动延迟陷阱

### 21.1 致命现象
- 用户通过 USB 连接电脑后，在电脑端找不到漫画存放目录；或者每次打开应用冷启动耗时超过 5 秒，一直在扫描全盘文件。

### 21.2 底层根因逆向剖析
- 词典笔作为 MTP 设备接入电脑时，系统的 `mtp-server` 仅映射暴露了特定的公开目录（如 `/userdisk/Favorite`、`/userdisk/Music`、`/userdisk/skip_re`）。应用若私自存放在内部目录（如 `/userdisk/manga`），用户在 Windows/macOS 上根本无法读写。
- 全盘深层遍历数千个文件在单核 I/O 下极度耗时。

### 21.3 确定性防错范式
1. **严格使用 MTP 暴露目录**：首选 `/userdisk/Favorite` 作为外部漫画导入主路径。
2. **轻量目录指纹缓存（Fingerprint Cache）实现 0ms 秒开**：启动时仅统计各候选根目录和一级子目录的文件数量拼装为轻量哈希指纹字符串。若指纹未变且无待处理 WebP，直接复用持久化缓存，**0ms 瞬间秒进书架**。
3. **自然排序（Natural Sort）**：按自然多段数字规则对文件名排序，杜绝 ASCII 排序造成的第一话紧接第十话的错乱。

---

## 总结：高健壮性应用研发“二十一项黄金防错清单”

| 序号 | 检查维度 | 判定合格标准 | 不合规后果 |
| :---: | :--- | :--- | :--- |
| **1** | **模块导出** | `app.js` 导出 Class 或 Object，严禁顶层调用 `App({...})` | 启动即报 `ReferenceError` 闪退 |
| **2** | **视口坐标** | 必须设定逻辑视口为 `1020px × 240px`，严禁手动 `rotate(270)` | 画面切出屏外或上下颠倒 |
| **3** | **触控事件** | 使用 DOM 原生逻辑坐标；若注入底端 evdev，使用 $X_{raw}=Y, Y_{raw}=1019-X$ | 点击完全错位无法交互 |
| **4** | **音频输出** | 长伴奏走 `mediaPlayerService`，短音效走 `soundPlayer` | ALSA 硬件死锁导致全局静音 |
| **5** | **RPC 回调** | Provider 响应必须包装为 `cb([0, result])` | 微服务切歌报错 9 并不再响应 |
| **6** | **网络请求** | 使用 `import http from 'http'`，不可使用 `fetch`/`WebSocket` | 报 `fetch is not defined` 崩溃 |
| **7** | **样式边界** | 仅使用 73 项白名单 Flexbox 属性，禁绝 `grid`/`calc()` | 布局坍塌或 C++ 除零崩溃 |
| **8** | **桌面展示** | `manifest.json` 必须包含 `props.addDesktop.y08_platform: true` | 应用无法在桌面图标中显示 |
| **9** | **息屏保护** | 关键阅读页面在 `onShow` 调用 `$falcon.keepScreenOn(true)` | 几十秒后自动黑屏熄火 |
| **10** | **文件读写** | 数据库与持久化数据写入 `/userdisk/` 或 `/data/`，严禁写入代码目录 | `Permission Denied` 写入失败 |
| **11** | **按键拼写** | 监听笔尖离开使用 `headButtonRelese` (无 a)，并在 mounted 调用 `setButtonEventReady(true)` | 硬件按键完全不触发 |
| **12** | **捏合手势** | 双指缩放必须在 JS 层手动计算两点距离，不依赖原生捏合 | 缩放操作完全无反应 |
| **13** | **窗口层级** | 弹窗必须在应用内实现，不可依赖系统多窗口浮动 | 窗口被强制全屏并不透明 |
| **14** | **触感反馈** | 放弃振动马达幻想，使用 `soundPlayer` 播放 `click.wav` | 报 `vibrator is not defined` |
| **15** | **跨页剪贴** | 跨页面文本暂存使用 `storage` 模块 | 报 `clipboard is not defined` |
| **16** | **横向滚动** | `<scroller scroll-direction="horizontal">` 内部必须嵌套显式 `flex-direction: row` 的包装 `div` | 首屏卡片单列纵向堆叠，首张被截断 |
| **17** | **点对点渲染** | 图像按物理视口严格 1:1 预采样（双列锁定 474px 直通），`<image>` 设置 `cover` | 产生严重网状摩尔纹与文字发虚发灰 |
| **18** | **WebP 转码** | 通过端侧 Linux 后台守护进程 (`webp_daemon.sh`) 调用 NEON `ffmpeg` 逐页静默转码 | 导入 WebP 识别为 0 页或应用死锁 |
| **19** | **滑动限频** | 采用 $O(\log N)$ 二分查找当前行，结合 45px 步长门禁限频更新响应式状态 | 60Hz 频繁全树 Diff 导致手指滑动顿挫卡死 |
| **20** | **手势消解** | 单击与双击采用 480ms 延时计时器与 95px 容差消解，`pageX <= 108px` 优先拦截侧滑返回 | 单击返回与双击放大混淆误触，跳出页面 |
| **21** | **MTP 存储** | 漫画导入严格放置于 `/userdisk/Favorite` 等 MTP 暴露目录，采用文件数量轻量指纹缓存 | 电脑无法访问文件，冷启动深层扫描耗时数秒 |
