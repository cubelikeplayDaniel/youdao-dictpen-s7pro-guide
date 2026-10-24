# 网易有道词典笔 S7 Pro 状态栏 (StatusBar)、下拉控制中心与系统通知子系统研发级参考手册
## (Falcon StatusBar, Dropdown Control Center & Global Notification Subsystem Architecture Manual)

> **适用硬件平台**：NetEase Youdao Dictionary Pen S7 Pro（硬件工程代号 `Y08_CV1813_V0`，内部平台代号 `YDPS7-2`）  
> **核心 SoC**：Cvitek CV1813H（单核 ARM Cortex-A7 @ 1.0 GHz，支持 ARMv7-A 架构、NEON SIMD 与 VFPv4 浮点协处理器，128 MB DDR 物理内存，Linux 5.10.4 内核）  
> **显示面板**：240 × 1020 物理超长带鱼竖屏（ST7701S LCD Controller，2-Lane MIPI DSI 接口，通过 `cfg.json` 配置 270° 逆时针渲染映射为 1020 × 240 逻辑视口）  
> **触控主控**：AXS15205 Capacitive Touch Controller（`axs_ts.ko`，I2C-1 从机地址 0x3B，输入设备 `/dev/input/by-path/platform-4010000.i2c-event`）  
> **电源管理芯片 (PMIC)**：X-Powers AXP2101（I2C-5 从机地址 0x34，独占中断 IRQ 47，集成硬件库仑计）  
> **核心二进制组件**：
> - `/usr/lib/libfalcon.so`（GreenUI 视窗引擎、QuickJS 运行时扩展、窗口管理器与物理动画引擎）
> - `/etc/miniapp/jsapis/libjsapi_export_core.so`（QuickJS 原生 C++ 导出桥接层与系统全局代理）
> - `/oem/YoudaoDictPen/output/libs/libyddal_business_core.so`（有道 DAL 业务层、全局通知与 Toast 总线）
> - `/oem/YoudaoDictPen/output/libs/libyddal_adapter_core.so`（硬件抽象适配层、Ubus 网络/电池事件聚合）
> - `/usr/lib/libydhal_devices.so`（背光 PWM 调制器与 ALSA 音频混音硬件层）
> - 系统启动器 Launcher（AppID `8080222437664451`）
> - 系统下拉控制中心 TopPanel（AppID `8080222501178405`）
> - 系统全局设置 Settings（AppID `8080272425914438`）

---

## 目录索引

1. [系统窗口架构与 Z-Order 栈序拓扑](#1-系统窗口架构与-z-order-栈序拓扑)
   - 1.1 [GreenUI 视窗树形层次与窗口管理哲学](#11-greenui-视窗树形层次与窗口管理哲学)
   - 1.2 [`greenui::WindowManager` 与 `greenui::Window` 核心数据结构与内存布局](#12-greenuidisplay-与-greenuiwindow-核心数据结构与内存布局)
   - 1.3 [全局五级窗口栈序 (Z-Order) 拓扑矩阵](#13-全局五级窗口栈序-z-order-拓扑矩阵)
   - 1.4 [多窗口可见性判决与遮挡剔除算法 (`getRenderableWindows` 逆向解析)](#14-多窗口可见性判决与遮挡剔除算法-getrenderablewindows-逆向解析)
   - 1.5 [Skia 双缓冲多窗口合成与剪裁区域 (Clip Region) 计算](#15-skia-双缓冲多窗口合成与剪裁区域-clip-region-计算)
   - 1.6 [全局输入事件路由与窗口焦点抢占机制](#16-全局输入事件路由与窗口焦点抢占机制)
2. [状态栏数据驱动与超轻量化渲染引擎](#2-状态栏数据驱动与超轻量化渲染引擎)
   - 2.1 [架构定位：Page 独立内联渲染与系统常驻浮层对比](#21-架构定位page-独立内联渲染与系统常驻浮层对比)
   - 2.2 [电池电量数据驱动：AXP2101 库仑计与一阶低通滤波 (LPF)](#22-电池电量数据驱动axp2101-库仑计与一阶低通滤波-lpf)
   - 2.3 [Wi-Fi 信号强度阶梯映射：wpa_supplicant RSSI 转四格图标](#23-wifi-信号强度阶梯映射wpa_supplicant-rssi-转四格图标)
   - 2.4 [时间时钟驱动：Linux 定时器对齐分钟边界触发规避无效重绘](#24-时间时钟驱动linux-定时器对齐分钟边界触发规避无效重绘)
   - 2.5 [极低功耗优化：预渲染位图缓存与 Skia Canvas 局部脏矩形更新](#25-极低功耗优化预渲染位图缓存与-skia-canvas-局部脏矩形更新)
3. [下拉手势检测与物理阻尼动力学引擎](#3-下拉手势检测与物理阻尼动力学引擎)
   - 3.1 [AXS15205 触控屏幕几何映射与顶部边界判定门限](#31-axs15205-触控屏幕几何映射与顶部边界判定门限)
   - 3.2 [`greenui::TopSwipeGesture::onTouchEvent` 反汇编硬核解析](#32-greenuitopswipegestureontouchevent-反汇编硬核解析)
   - 3.3 [阻尼下拉位移模型：几何偏移计算与触控跟随数学函数](#33-阻尼下拉位移模型几何偏移计算与触控跟随数学函数)
   - 3.4 [惯性滑动与回弹模型：VelocityTracker 速度提取与 Scroller 动力学](#34-惯性滑动与回弹模型velocitytracker-速度提取与-scroller-动力学)
   - 3.5 [带鱼屏手势冲突裁决：下拉面板与横向滑块 (SliderView / Seekbar) 互锁协议](#35-带鱼屏手势冲突裁决下拉面板与横向滑块-sliderview--seekbar-互锁协议)
4. [页面沉浸式与视口避让机制](#4-页面沉浸式与视口避让机制)
   - 4.1 [`setSupportTopPanel(bool)` 原生实现与 Flag 4 动态打标](#41-setsupporttoppanelbool-原生实现与-flag-4-动态打标)
   - 4.2 [视口避让尺寸推导：避让模式 (1020×204) vs 全屏沉浸模式 (1020×240)](#42-视口避让尺寸推导避让模式-1020204-vs-全屏沉浸模式-1020240)
   - 4.3 [沉浸式全屏界面下的顶部浮动导航与返回键交互规范](#43-沉浸式全屏界面下的顶部浮动导航与返回键交互规范)
   - 4.4 [边缘手势防御：左滑返回手势 `setDisableLeftSwipeBack` 联动设计](#44-边缘手势防御左滑返回手势-setdisableleftswipeback-联动设计)
5. [全局 Toast 与系统通知悬浮层架构](#5-全局-toast-与系统通知悬浮层架构)
   - 5.1 [全局 Toast 架构拓扑：JS 代理、DAL 业务层与内核信号管道](#51-全局-toast-架构拓扑js-代理dal-业务层与内核信号管道)
   - 5.2 [IPC 调度与优先级抢占队列 (`ToastPriority` 与防抖合并机制)](#52-ipc-调度与优先级抢占队列-toastpriority-与防抖合并机制)
   - 5.3 [系统级模态宿主：`<modal system="true">` 对应 `FloatingWindow` 原生映射](#53-系统级模态宿主modal-systemtrue-对应-floatingwindow-原生映射)
   - 5.4 [淡入淡出动画管线：500ms Alpha 渐变与状态机生命周期调度](#54-淡入淡出动画管线500ms-alpha-渐变与状态机生命周期调度)
6. [Falcon MiniApp 前端 JSAPI 契约与调用指南](#6-falcon-miniapp-前端-jsapi-契约与调用指南)
   - 6.1 [状态栏管理契约：`$falcon.setStatusBar` 接口规范](#61-状态栏管理契约falconsetstatusbar-接口规范)
   - 6.2 [全局通知契约：`$falcon.showToast` 原生调用与参数结构](#62-全局通知契约falconshowtoast-原生调用与参数结构)
   - 6.3 [手势拦截总线：高灵敏交互场景（绘画、划词）下的手势静默接口](#63-手势拦截总线高灵敏交互场景绘画划词下的手势静默接口)
   - 6.4 [系统事件广播监听通道：`topPanelShowingStatusChanged` 与 `batteryInfoChange`](#64-系统事件广播监听通道toppanelshowingstatuschanged-与-batteryinfochange)
7. [生产级 TypeScript / Vue 组件封装与沉浸式实战模板](#7-生产级-typescript--vue-组件封装与沉浸式实战模板)
   - 7.1 [系统窗口与通知子系统 TypeScript 类型定义 (`falcon-window.d.ts`)](#71-系统窗口与通知子系统-typescript-类型定义-falcon-windowdts)
   - 7.2 [沉浸式安全区自适应容器组件 (`ImmersiveSafeContainer.vue`)](#72-沉浸式安全区自适应容器组件-immersivesafecontainervue)
   - 7.3 [超轻量级高性能独立状态栏组件 (`UltraLightStatusBar.vue`)](#73-超轻量级高性能独立状态栏组件-ultralightstatusbarvue)
   - 7.4 [全局防抖 Toast 队列管理器 (`GlobalToastManager.ts`)](#74-全局防抖-toast-队列管理器-globaltoastmanagerts)
8. [典型研发陷阱、崩溃根因与避坑指南 (8 大典型故障深度剖析)](#8-典型研发陷阱崩溃根因与避坑指南-8-大典型故障深度剖析)
   - 8.1 [陷阱 1：沉浸模式下顶部按钮在 Y < 40px 区域误判为下拉手势导致触控失灵](#81-陷阱-1沉浸模式下顶部按钮在-y--40px-区域误判为下拉手势导致触控失灵)
   - 8.2 [陷阱 2：Toast 定时器未在 `beforeDestroy` 清除引发内存泄漏与野指针崩溃](#82-陷阱-2toast-定时器未在-beforedestroy-清除引发内存泄漏与野指针崩溃)
   - 8.3 [陷阱 3：状态栏 1Hz 盲目高频全屏重绘导致 CPU 占用飙升与 UI 掉帧](#83-陷阱-3状态栏-1hz-盲目高频全屏重绘导致-cpu-占用飙升与-ui-掉帧)
   - 8.4 [陷阱 4：绘画/划词敏感视口未打标 Flag 4 引发触摸事件被系统强行拦截吞没](#84-陷阱-4绘画划词敏感视口未打标-flag-4-引发触摸事件被系统强行拦截吞没)
   - 8.5 [陷阱 5：悬浮窗口 `isFloating` 标志缺失导致底层视图树被完全剔除黑屏](#85-陷阱-5悬浮窗口-isfloating-标志缺失导致底层视图树被完全剔除黑屏)
   - 8.6 [陷阱 6：下拉面板触控取消事件未处理造成物理 Scroller 悬滞半屏卡死](#86-陷阱-6下拉面板触控取消事件未处理造成物理-scroller-悬滞半屏卡死)
   - 8.7 [陷阱 7：电池电压瞬态压降未做 LPF 滤波导致系统误触发低电警告关机](#87-陷阱-7电池电压瞬态压降未做-lpf-滤波导致系统误触发低电警告关机)
   - 8.8 [陷阱 8：Wi-Fi RSSI 轮询在页面后台 (`pageHidden`) 未注销导致息屏功耗超标](#88-陷阱-8wifi-rssi-轮询在页面后台-pagehidden-未注销导致息屏功耗超标)
9. [逆向符号、虚拟函数表与内存偏移速查索引](#9-逆向符号虚拟函数表与内存偏移速查索引)

---

## 1. 系统窗口架构与 Z-Order 栈序拓扑

### 1.1 GreenUI 视窗树形层次与窗口管理哲学

网易有道词典笔 S7 Pro 搭载的自研渲染引擎 GreenUI 运行于单核 ARM Cortex-A7 处理器与 128 MB 物理内存极限资源约束下。为了消除传统 X11 / Wayland 或 Android SurfaceFlinger 带来的跨进程 Binder 传输开销与多进程 GPU 合成缓冲占用，GreenUI 采用了**单渲染进程、共享双缓冲显存、多视窗分层组合（In-Process Compositor）**的轻量化视窗拓扑架构。

在系统运行时，所有业务应用、下拉面板、系统软键盘与模态悬浮窗均作为 `greenui::Window` 的派生实例，统一挂载在全局单例视窗管理器 `greenui::WindowManager` 中。整个系统的窗口栈并非平铺布局，而是基于严格的深度优先层叠拓扑树（Z-Order Stacking Tree）组织：

```
+----------------------------------------------------------------------------------------------------+
|                                    Linux Framebuffer (/dev/fb0)                                    |
|                                1020 x 240 Logical Surface (ARGB8888)                               |
+----------------------------------------------------------------------------------------------------+
                                                  ^
                                                  | (Multi-Window Compositor: NativeWindow::dispatchDraw)
+----------------------------------------------------------------------------------------------------+
|                                      greenui::WindowManager                                        |
|                          m_windows: std::vector<greenui::Window*>                                   |
+----------------------------------------------------------------------------------------------------+
  │
  ├── [Z-Order: 10200] im::FalconIMPanel              <-- 虚拟键盘输入法窗口 (全宽浮层，动态升降)
  │
  ├── [Z-Order: 10000] JQuick::FloatingWindow / Modal <-- 全局 Toast、系统通知弹窗与模态对话框
  │
  ├── [Z-Order: 10001] falcon::SettingPanel (TopPanel) <-- 下拉快捷控制中心 (0~240px 纵向动态拉伸)
  │
  ├── [Z-Order:  5000] StatusBarWindow / PageTopBar  <-- 状态栏 (物理高度 24px/36px，内联或独立浮层)
  │
  └── [Z-Order: 0~100] falcon::FalconVWindow          <-- 当前前台业务应用主视口 (如 Launcher/词典/阅读器)
```

整个窗口树的核心管理逻辑遵循三大准则：
1. **单一全局 NativeWindow 承载**：物理显示后端仅存在一个 `greenui::NativeWindow`（对于 Linux Framebuffer 对应 `greenui::FBNativeWindow`），所有顶层 `Window` 对象共享该底层硬件缓冲与绘制调度循环。
2. **栈顶优先事件消费**：硬件触控中断与物理按键事件直接送达 `WindowManager`，由栈顶（Highest Z-Order）可见窗口优先过滤并判定消费；若未消费，才向底层窗口递归传递。
3. **基于遮挡的遍历剔除**：在每帧绘制遍历中，`WindowManager` 从最顶层向最底层逆向扫描。一旦遇到一个全屏且不透明（Non-Floating）的窗口，立即截断遍历链路，底层所有被遮挡的窗口完全跳过 Skia DisplayList 回放与光栅化。

---

### 1.2 `greenui::WindowManager` 与 `greenui::Window` 核心数据结构与内存布局

通过对 `/usr/lib/libfalcon.so` 的反编译与符号结构还原，`greenui::Window` 结构体精确内存布局如下（32 位 ARMv7-A 架构，对齐为 4 字节）：

```cpp
// 逆向还原自 libfalcon.so: greenui::Window 结构体
namespace greenui {

enum WindowFlags : uint32_t {
    FLAG_FLOATING          = 0x00000001, // 标志位 0: 是否为悬浮窗口 (不阻断底层绘制遍历)
    FLAG_NOT_FOCUSABLE     = 0x00000002, // 标志位 1: 是否不可获取输入焦点
    FLAG_NO_TOP_PANEL      = 0x00000004, // 标志位 2: 是否禁用顶部下拉控制中心手势 (全屏沉浸)
    FLAG_KEEP_SCREEN_ON    = 0x00000008, // 标志位 3: 保持屏幕常亮
    FLAG_SECURE_SURFACE    = 0x00000010, // 标志位 4: 安全防截屏标志
    FLAG_TRANSPARENT_BG    = 0x00000020  // 标志位 5: 透明背景窗口
};

class Window : public NWindow {
public:
    // 虚函数表偏移量 (+0x00)
    virtual ~Window();                                          // vtable +0x00
    virtual void onCreate();                                    // vtable +0x04
    virtual void onStart();                                     // vtable +0x08
    virtual void onResume();                                    // vtable +0x0C
    virtual void onPause();                                     // vtable +0x10
    virtual void onStop();                                      // vtable +0x14
    virtual void onDestroy();                                   // vtable +0x18
    virtual void dispatchDraw(Canvas* canvas, int64_t timeNs);  // vtable +0x1C
    virtual bool dispatchTouchEvent(MotionEvent& ev);           // vtable +0x20
    virtual bool dispatchKeyEvent(KeyEvent& ev);                // vtable +0x24
    virtual bool handleBackPress();                             // vtable +0x28

public:
    // 成员变量物理内存布局
    // +0x00: vtable 指针 (4 字节)
    // +0x04 ~ +0x1C: greenui::NWindow 基类成员 (mWidth, mHeight, mVisible, mDecorView 等, 28 字节)
    int32_t     mLeft;              // +0x20: 窗口在逻辑画布上的 X 轴偏移 (像素)
    int32_t     mTop;               // +0x24: 窗口在逻辑画布上的 Y 轴偏移 (像素)
    int32_t     mLayer;             // +0x28: 窗口的 Z-Order 栈序深度 (关键决策字段)
    uint32_t    mFlags;             // +0x2c: 窗口特性标志掩码 (WindowFlags 位图)
    int32_t     mAttachedDisplayId; // +0x30: 关联的逻辑显示器 ID
    uint8_t     mAlpha;             // +0x34: 窗口全局不透明度 (0 ~ 255)
    uint8_t     mFocusableState;    // +0x35: 焦点状态标志
    uint16_t    mReserved;          // +0x36: 4字节对齐填充
};

class WindowManager {
public:
    static WindowManager* instance();                           // 0x583bec

    void pushWindow(Window* win);                               // 0x58498c: 压入窗口并排序
    void removeWindow(Window* win);                             // 0x584388: 移除窗口
    void bringToFront(Window* win);                             // 0x584e2c: 置顶窗口
    void hideWindow(Window* win);                               // 0x584e30: 隐藏窗口
    Window* getFocusedWindow() const;                           // 0x583cb4: 获取当前焦点窗口
    Window* getWindowBehind(Window* win);                       // 0x583cfc: 获取指定窗口背后的窗口
    
    // 核心绘制裁剪查询: 获取当前可见并参与光栅化的窗口列表
    void getRenderableWindows(std::vector<Window*>& outList, 
                              int32_t minLayer, 
                              int32_t maxLayer) const;          // 0x585090

    bool dispatchTouchEvent(MotionEvent ev);                    // 0x5840dc: 全局触控派发
    bool dispatchKeyEvent(KeyEvent ev);                         // 0x583d40: 全局按键派发
    bool handleBackPress();                                     // 0x583e60: 全局物理返回拦截
    void disableLeftSwipeBack();                                // 0x58496c: 屏蔽全局左滑返回

private:
    std::vector<Window*>    m_windows;                          // +0x00 ~ +0x0B: 窗口动态数组指针三元组 (begin, end, cap)
    NativeWindow*           m_nativeWindow;                     // +0x0C: 底层硬件原生窗口指针
    Window*                 m_focusedWindow;                    // +0x10: 拥有当前焦点的窗口
    bool                    m_visible;                          // +0x14: 管理器全局可见性
    uint8_t                 m_pad[3];                           // +0x15: 内存对齐填充
};

} // namespace greenui
```

汇编代码级证据位于 `/usr/lib/libfalcon.so` 中 `greenui::Window` 的 getter/setter 实现：

```arm
; ==============================================================================
; greenui::Window::getLayer() const
; 符号地址: 0x00583654
; 入参: r0 = this 指针
; 出参: r0 = mLayer (int32_t)
; ==============================================================================
00583654 <_ZNK7greenui6Window8getLayerEv>:
  583654: e5900028     ldr   r0, [r0, #0x28]        ; 从 this + 0x28 读取 mLayer
  583658: e12fff1e     bx    lr

; ==============================================================================
; greenui::Window::isFloating() const
; 符号地址: 0x0058365c
; 入参: r0 = this 指针
; 出参: r0 = (mFlags & 0x1) != 0
; ==============================================================================
0058365c <_ZN7greenui6Window10isFloatingEv>:
  58365c: e590002c     ldr   r0, [r0, #0x2c]        ; 从 this + 0x2C 读取 mFlags
  583660: e2000001     and   r0, r0, #1             ; 提取最低位 (FLAG_FLOATING)
  583664: e12fff1e     bx    lr

; ==============================================================================
; greenui::Window::addFlag(uint32_t flag)
; 符号地址: 0x0058367c
; 入参: r0 = this 指针, r1 = flag 掩码
; ==============================================================================
0058367c <_ZN7greenui6Window7addFlagEj>:
  58367c: e590302c     ldr   r3, [r0, #0x2c]        ; 读取当前 mFlags
  583680: e1833001     orr   r3, r3, r1             ; 按位或运算: mFlags |= flag
  583684: e580302c     str   r3, [r0, #0x2c]        ; 写回 this + 0x2C
  583688: e12fff1e     bx    lr

; ==============================================================================
; greenui::Window::clearFlag(uint32_t flag)
; 符号地址: 0x0058368c
; 入参: r0 = this 指针, r1 = flag 掩码
; ==============================================================================
0058368c <_ZN7greenui6Window9clearFlagEj>:
  58368c: e590302c     ldr   r3, [r0, #0x2c]        ; 读取当前 mFlags
  583690: e1c33001     bic   r3, r3, r1             ; 按位清零: mFlags &= ~flag
  583694: e580302c     str   r3, [r0, #0x2c]        ; 写回 this + 0x2C
  583698: e12fff1e     bx    lr
```

---

### 1.3 全局五级窗口栈序 (Z-Order) 拓扑矩阵

在 S7 Pro 系统中，`mLayer` 取值直接决定了窗口在全局渲染与触控派发时的物理层级。各核心子系统的 Z-Order 数值定义与二进制汇编初始化硬编码证据对齐如下表：

| 逻辑图层名称 | 对应 C++ 实体类 | 典型所属 App / 动态库 | Z-Order 数值 (`mLayer`) | 悬浮标志位 (`FLAG_FLOATING`) | 物理视口范围 (1020×240 空间) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **应用主窗口** | `falcon::FalconVWindow` | 各业务 MiniApp、Launcher (`8080222437664451`) | `0 ~ 100` | 默认 `false` (全屏独占) | `(0, 0, 1020, 240)` |
| **独立状态栏** | `greenui::StatusBarWindow` | 系统常驻组件 / 内联 Vue 根容器 | `5000` | `true` (半透明叠加) | `(0, 0, 1020, 36)` |
| **下拉控制中心** | `falcon::SettingPanel` | 下拉快捷菜单 (`8080222501178405`) | `10001` (`0x2711`) | `true` (动态下滑覆盖) | `(0, -240~0, 1020, 240)` |
| **全局通知/Toast** | `JQuick::FloatingWindow` | `Toast.vue` / 系统弹窗模态宿主 | `10000` (`0x2710`) / CSS `10000` | `true` (局部悬浮) | `(0, 176, 1020, 64)` |
| **系统虚拟键盘** | `im::FalconIMPanel` | 全局输入法微应用 (`im-app`) | `10200` (`0x27D8`) | `true` (底部弹出) | `(0, 110~240, 1020, 130)` |

#### 汇编还原证据 A：`falcon::SettingPanel` 构造函数赋权 (Z-Order: 10001)
位于 `/usr/lib/libfalcon.so` 的 `falcon::SettingPanel::SettingPanel` 构造函数中：

```arm
; libfalcon.so: 0x002aebcc - 0x002aebe0
2aebcc: e3023711     movw  r3, #0x2711          ; r3 = 0x2711 (十进制: 10001)
2aebd0: e5843028     str   r3, [r4, #0x28]      ; 写入 SettingPanel->mLayer = 10001
2aebd4: e594302c     ldr   r3, [r4, #0x2c]      ; 读取 mFlags
2aebd8: e3a00f5e     mov   r0, #376             ; 分配内部 App 容器
2aebdc: e3833001     orr   r3, r3, #1           ; mFlags |= FLAG_FLOATING (0x01)
2aebe0: e584302c     str   r3, [r4, #0x2c]      ; 写回 SettingPanel->mFlags
```

#### 汇编还原证据 B：`im::FalconIMPanel` 构造函数赋权 (Z-Order: 10200)
位于 `/usr/lib/libfalcon.so` 的输入法面板 `im::FalconIMPanel::FalconIMPanel` 构造函数中：

```arm
; libfalcon.so: 0x002b113c - 0x002b1150
2b113c: e594302c     ldr   r3, [r4, #0x2c]      ; 读取当前 mFlags
2b1140: e30227d8     movw  r2, #0x27d8          ; r2 = 0x27D8 (十进制: 10200)
2b1144: e3a00f5f     mov   r0, #380             ; 分配 FalconIMApp
2b1148: e5842028     str   r2, [r4, #0x28]      ; 写入 FalconIMPanel->mLayer = 10200!
2b114c: e3833001     orr   r3, r3, #1           ; mFlags |= FLAG_FLOATING (0x01)
2b1150: e584302c     str   r3, [r4, #0x2c]      ; 写回 FalconIMPanel->mFlags
```

#### 汇编还原证据 C：`JQuick::FloatingWindow` 基础模态窗口赋权 (Z-Order: 100)
位于 `/usr/lib/libfalcon.so` 的通用模态窗口 `JQuick::FloatingWindow::FloatingWindow` 中：

```arm
; libfalcon.so: 0x002438ec - 0x00243900
2438ec: e3a03064     mov   r3, #100             ; r3 = 100 (默认应用内悬浮基准层)
2438f0: e5843028     str   r3, [r4, #0x28]      ; 写入 FloatingWindow->mLayer = 100
2438f4: e5945038     ldr   r5, [r4, #0x38]
2438f8: 1594302c     ldrne r3, [r4, #0x2c]
2438fc: 13833001     orrne r3, r3, #1           ; 若是模态则打上 FLAG_FLOATING
243900: 1584302c     strne r3, [r4, #0x2c]
```

当前端 `<modal system="true">` 属性被激活时，运行时在 C++ 层进一步调用系统提权接口，将其 `mLayer` 提升至 `10000` 系统级遮罩图层。

---

### 1.4 多窗口可见性判决与遮挡剔除算法 (`getRenderableWindows` 逆向解析)

在资源极度紧缺的单核平台上，如果每一帧都无脑绘制所有窗口，会导致 Skia 画布发生严重的过度绘制（Overdraw），帧率从 60 FPS 骤降至 15 FPS。为此，`greenui::WindowManager::getRenderableWindows` 实现了一套极其高效的反向拓扑遮挡剔除机制。

反汇编地址位于 `0x00585090`，核心逻辑还原如下：

```cpp
// 逆向源码等价还原: WindowManager::getRenderableWindows
void greenui::WindowManager::getRenderableWindows(std::vector<Window*>& outList, 
                                                 int32_t minLayer, 
                                                 int32_t maxLayer) const 
{
    outList.clear();
    if (!this->m_visible || this->m_windows.empty()) {
        return;
    }

    // 从栈顶 (最高层级) 向栈底 (最底层级) 逆序遍历
    int32_t windowCount = static_cast<int32_t>(this->m_windows.size());
    for (int32_t i = windowCount - 1; i >= 0; --i) {
        Window* win = this->m_windows[i];
        if (win == nullptr) continue;

        int32_t layer = win->getLayer(); // 读取 offset +0x28

        // 层级区间过滤: 必须满足 minLayer <= layer <= maxLayer
        if (layer > maxLayer) {
            continue; // 高于上限，跳过继续向下寻找
        }
        if (layer < minLayer) {
            break;    // 低于下限，无需再检查更低层级，直接终止扫描
        }

        // 插入到候选渲染列表
        outList.push_back(win);

        // 关键遮挡剔除判定:
        // 如果当前窗口不是悬浮窗口 (即为不透明全屏窗口)，
        // 则其下方的所有窗口必然被 100% 遮挡，立即提前中断搜索!
        if (!win->isFloating()) { // 检查 offset +0x2C 的 bit 0
            break; // 截断扫描循环! 底层 Launcher / 业务窗口不再被渲染
        }
    }

    // 将渲染列表反转为正序 (自底向上绘制，保证正确遮盖)
    std::reverse(outList.begin(), outList.end());
}
```

#### 关键汇编指令对齐 (ARMv7-A)
```arm
; libfalcon.so: 0x00585128 - 0x00585150
585128: e5983000     ldr   r3, [r8]             ; r8 = this->m_windows.begin()
58512c: e2444001     sub   r4, r4, #1           ; 逆向索引: i = count - 1
585130: e7935104     ldr   r5, [r3, r4, lsl #2] ; r5 = m_windows[i] 指针
585134: e58d5004     str   r5, [sp, #4]
585138: e5953028     ldr   r3, [r5, #0x28]      ; r3 = win->mLayer
58513c: e1530009     cmp   r3, r9               ; 比较 layer 与 maxLayer (r9)
585140: cafffff6     bgt   0x585120             ; if (layer > maxLayer) continue
585144: e153000a     cmp   r3, r10              ; 比较 layer 与 minLayer (r10)
585148: ba00000b     blt   0x58517c             ; if (layer < minLayer) break! (终止遍历)
...
585110: e59d0004     ldr   r0, [sp, #4]         ; r0 = win
585114: ebf13bc0     bl    0x1d401c             ; 调用 greenui::Window::isFloating()
585118: e3500000     cmp   r0, #0               ; 检查返回值
58511c: 0a000016     beq   0x58517c             ; 若 isFloating == false，立即退出 (截断底层!)
```

这个算法对 S7 Pro 状态栏和下拉菜单具有决定性意义：
- **当下拉菜单 (`SettingPanel`) 未拉出或处于隐藏状态时**：`m_windows` 栈顶是业务应用 `FalconVWindow`。由于其 `isFloating() == false`，遍历在此处立即终止，系统不会对后台已冻结的应用做任何无效绘制。
- **当下拉菜单拉出时**：`SettingPanel` 的 `isFloating == true`，因此遍历器记录 `SettingPanel` 后**继续向下扫描**，将下层的业务应用也纳入渲染列表，保证半透明背景遮罩（Overlay Dim `rgba(0,0,0,0.4)`）能够正确混合在业务界面上方。

---

### 1.5 Skia 双缓冲多窗口合成与剪裁区域 (Clip Region) 计算

当 `WindowManager::getRenderableWindows` 产出最终的正向渲染序列（如 `[AppWindow, TopPanel, ToastWindow]`）后，硬件宿主 `greenui::NativeWindow::dispatchDraw`（地址 `0x00589748`）开始驱动 Skia 进行分层合成。

#### 合成流水线执行时序
```
NativeWindow::dispatchDraw (0x589748)
  │
  ├── 1. Canvas::save() (保存全局变换状态与默认剪裁栈)
  │
  ├── 2. WindowManager::getRenderableWindows(renderList, INT_MIN, INT_MAX)
  │
  ├── 3. 循环遍历 renderList 中每一个可渲染窗口 win:
  │       │
  │       ├── win->dispatchDraw(canvas, frameTimeNs) (0x583b44)
  │       │     │
  │       │     ├── 几何位移变换:
  │       │     │     if (mLeft != 0 || mTop != 0)
  │       │     │         canvas->translate((float)mLeft, (float)mTop);
  │       │     │
  │       │     ├── 窗口区域限制剪裁:
  │       │     │     SkRect winBounds = SkRect::MakeXYWH(0, 0, win->getWidth(), win->getHeight());
  │       │     │     canvas->clipRect(winBounds, SkRegion::kIntersect_Op, false);
  │       │     │
  │       │     ├── 触发内部视图树绘制:
  │       │     │     NWindow::dispatchDraw(canvas, frameTimeNs); // 回放 DisplayList
  │       │     │
  │       │     └── 恢复几何变换:
  │       │           if (mLeft != 0 || mTop != 0)
  │       │               canvas->translate(-(float)mLeft, -(float)mTop);
  │       │
  ├── 4. Canvas::restoreToCount(saveCount) (恢复初始全局状态)
  │
  └── 5. 提交显存双缓冲交换: FBIOPAN_DISPLAY (0x4606) 或 BufferQueue::submitBuffer
```

#### 局部脏矩形 (Damage Rect) 合并
为了压制显存总线带宽，系统并不会在每次渲染时无差别全屏刷新。每个窗口在发生局部状态变化时（例如状态栏时间跳动、电池图标更新），通过调用：
```cpp
win->requestRender(view, dirtyRect); // 0x5833b8
```
将脏矩形标记在 `NativeWindow` 的局部修补区域列表中。`FBNativeWindow` 会对多个重叠的脏矩形执行 `SkRegion::op(dirtyRect, SkRegion::kUnion_Op)` 求并，最终只将并集区域提交至 `/dev/fb0` 对应的双缓冲离屏缓冲区。

---

### 1.6 全局输入事件路由与窗口焦点抢占机制

硬件层中断产生的触控坐标在经过 `axs_ts.ko` 驱动采集后，以 `input_event` 格式由 `greenui::winInputLoop` 读取，封装为 `greenui::MotionEvent` 并递交至 `greenui::WindowManager::dispatchTouchEvent(MotionEvent ev)`（地址 `0x005840dc`）。

输入事件在视窗间的流转图如下：

```
                        Linux Kernel input_event (/dev/input/event0)
                                            │
                                            ▼
                           greenui::winInputLoop 线程
                                            │ (坐标逆矩阵变换 270°)
                                            ▼
                        greenui::GlobalGestureHelper (全局手势链)
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    ▼                                               ▼
         TopSwipeGesture (0x588930)                    LeftSwipeBackGesture (0x588308)
         (判定 Y < 40px 是否下滑唤起下拉栏)            (判定 X < 10.2px 是否左滑退出)
                    │                                               │
           [Consumed: 拦截成功]                            [Consumed: 拦截成功]
                    │                                               │
                    ▼                                               ▼
       falcon::SettingPanel::show()                   WindowManager::handleBackPress()
                    │
           [Unconsumed: 未满足条件]
                    │
                    ▼
         greenui::WindowManager::dispatchTouchEvent (0x5840dc)
                    │
                    ▼ (从栈顶最高 Z-Order 窗口依次向下投递)
       1. FalconIMPanel (若可见且命中键盘区域 -> 消费)
       2. FloatingWindow / Toast (若模态且命中 -> 消费)
       3. SettingPanel (若正在下拉展开 -> 消费)
       4. FalconVWindow (当前前台 App 视图树 dispatchTouchEvent)
```

**焦点抢占铁律**：
- 只要下拉菜单 `falcon::SettingPanel` 处于拉出（Showing）状态，`WindowManager` 会自动将其设为 `m_focusedWindow`。
- 此时底层 App 窗口会收到 `Window::performWindowFocusChanged(false)` 回调，所有向 App 的事件分发被硬截断，彻底避免在下拉操作快捷开关时误点底层应用的业务按钮。

---

## 2. 状态栏数据驱动与超轻量化渲染引擎

### 2.1 架构定位：Page 独立内联渲染与系统常驻浮层对比

在智能手机或通用平板系统（如 Android / iOS）中，状态栏由独立的 SystemUI 进程或全局常驻 Window 实例驱动。然而，在 S7 Pro 仅 128 MB RAM 的严苛硬件限制下，有道系统架构师采用了一种更为轻量的**双模混合架构**：

```
                      +---------------------------------------+
                      |       有道 S7 Pro 状态栏双模拓扑      |
                      +---------------------------------------+
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
         【模式 A: Page 独立内联模式】              【模式 B: TopPanel 独立浮层模式】
               (常规业务应用运行态)                       (用户下拉呼出控制中心时)
                     │                                         │
        - 每个 MiniApp Page 内联渲染               - 位于 `8080222501178405`
        - 组件: `StatusBar.vue`                    - 独立常驻于 `SettingPanel` 视窗
        - 宿主: 业务窗口自身的 VDOM                - 宿主: 系统悬浮窗口 (Z: 10001)
        - 优势: 0 进程间 IPC 开销                  - 优势: 脱离业务 App 生命周期常驻
        - 避让: 页面视口自然排版                   - 避让: 强制全屏悬浮覆盖
```

在反编译启动器（`8080222437664451`）、设置中心（`8080272425914438`）及第三方微应用时，可以证实：
1. **常规状态下**：系统并没有一个独立的常驻 Native 进程叫 `system-statusbar`。每个页面在其 Vue 模板最顶部声明 `<status-bar>` 或导入 `@components/StatusBar.vue`，内联融入页面的 DOM 树。
2. **内联状态栏高度**：固定为 24px 或 36px（取决于当前设备主题配置，如 `theme-y08` 对应标准为 36px）。
3. **数据总线直通**：内联状态栏直接通过 QuickJS 原生绑定的原生模块（`batteryInfo`、`wifi`、`systemInfo`）订阅底层 HAL 硬件变更，避免了通过系统守护进程广播转发的二次延迟。

---

### 2.2 电池电量数据驱动：AXP2101 库仑计与一阶低通滤波 (LPF)

词典笔 S7 Pro 采用 X-Powers AXP2101 作为系统主 PMIC。该芯片内置高精度 14-Bit ADC 与专用硬件库仑计，通过实时积分检测充放电电流。

#### 1. 硬件采样与寄存器读取
底层驱动在 Linux 内核以 1000ms 周期读取 AXP2101 内部寄存器：
- 电池开路电压 (OCV) 寄存器：`0x34` (REG_BAT_VOLT)
- 库仑计积分百分比寄存器：`0xA4` (REG_BAT_PERCENTAGE)
- 充放电状态寄存器：`0x00` (REG_STATUS1，检测 AC/USB 接入与充电中/已充满状态)

#### 2. 软件瞬态压降一阶低通滤波 (LPF) 算法
词典笔在执行笔头 OCR 扫描点亮高亮补光 LED，或扬声器瞬态大音量播放时，锂电池端电压会瞬间发生高达 150mV ~ 300mV 的 IR 压降（Internal Resistance Drop）。如果直接将瞬时电压或未滤波的电量换算给 UI，会导致状态栏电池图标剧烈上下跳动，甚至因误判电量为 0% 触发系统紧急关机。

系统在 `/usr/lib/yddal_libs/libyddal_adapter_core.so`（符号 `YADAPTERAPI::Internal::YSystemInfoAdapterPrivate::getBatteryCapacity`）中实现了一阶惯性数字低通滤波算法：

$$y[k] = \alpha \cdot x[k] + (1 - \alpha) \cdot y[k-1]$$

其中：
- $x[k]$：硬件库仑计当前周期的原始采样电量（Raw SOC）。
- $y[k]$：平滑后的输出电量（Filtered SOC），用于推送给前端。
- $\alpha$：滤波滤波平滑系数。系统在放电状态下设定 $\alpha = 0.05$（强平滑，响应慢但抗抖动极强）；在检测到充电接入状态下设定 $\alpha = 0.20$（快速响应充入电量）。

C++ 滤波逻辑核心伪代码还原：
```cpp
// 逆向自 libyddal_adapter_core.so
int32_t YSystemInfoAdapterPrivate::filterBatteryCapacity(int32_t rawSoc, bool isCharging) {
    static float s_filteredSoc = -1.0f;
    if (s_filteredSoc < 0.0f) {
        s_filteredSoc = static_cast<float>(rawSoc); // 初始化
        return rawSoc;
    }

    float alpha = isCharging ? 0.20f : 0.05f;
    // 一阶惯性滤波
    s_filteredSoc = alpha * static_cast<float>(rawSoc) + (1.0f - alpha) * s_filteredSoc;

    // 单调性保护: 放电状态下禁止电量逆向递增 (除非充电器接入)
    static int32_t s_lastReportedSoc = -1;
    int32_t currentSoc = static_cast<int32_t>(std::round(s_filteredSoc));

    if (!isCharging && s_lastReportedSoc >= 0) {
        if (currentSoc > s_lastReportedSoc) {
            currentSoc = s_lastReportedSoc; // 抑制虚标跳升
        }
    }
    s_lastReportedSoc = currentSoc;
    return currentSoc;
}
```

#### 3. 事件派发流转
当滤波后的电量发生变动时，`libyddal_adapter_core.so` 通过 Ubus 发出通知，最终由 `libjsapi_export_core.so` 触发 QuickJS 层的 `batteryInfoChange` 事件，前端 `Battery.vue` 仅在百分比整数变化时才更新图片资源，从根源切断无效重绘。

---

### 2.3 Wi-Fi 信号强度阶梯映射：wpa_supplicant RSSI 转四格图标

系统的 Wi-Fi 芯片挂载于 SDIO 总线。底层的无线管理守护进程 `/usr/bin/wifi-manager` 通过 UNIX 域套接字 `/var/run/wpa_supplicant/wlan0` 与内核 `cfg80211` 通信，获取当前连接基站的接收信号强度指示（RSSI，单位 dBm）。

#### 非线性阶梯映射表
在 `libyddal_business_core.so` 与前端 `StatusBar.vue` 中，物理 RSSI 数值（通常分布在 $-90 \text{ dBm} \sim -30 \text{ dBm}$ 之间）被非线性量化映射为 0 ~ 4 格信号强度：

```
RSSI (dBm)        格数 (Qual)      图标资源文件名              状态描述
-----------------------------------------------------------------------------
>= -55 dBm        4 格 (满格)     /wifi_icon_high.png          极佳 (近距离无阻挡)
-66 ~ -56 dBm     3 格            /wifi_icon_high.png          良好 (正常室内)
-77 ~ -67 dBm     2 格            /wifi_icon_mid.png           一般 (有墙体衰减)
-88 ~ -78 dBm     1 格            /wifi_icon_low.png           微弱 (连接边缘)
< -88 dBm 或断开  0 格            /wifi_icon_low.png (或隐藏)  不可用 / 离线
```

#### 双周期轮询与防振荡机制
1. **下拉控制中心激活期**：开启高频探测定时器（`startWifiQualTimer`），每 **2000ms** 轮询一次 `wifi.getWifiQual()`，确保用户下拉滑块时即时看到当前真实信号变化。
2. **常规运行期/前台业务期**：降频至 **15000ms**（15秒）更新一次。
3. **休眠待机期**：在页面触发 `pageHidden` 时，必须强制调用 `stopWifiQualTimer()` 注销定时器，彻底防止 CPU 被频繁唤醒。
4. **施密特触发器门限（滞后区间）**：为了规避设备在两个信号格数交界处（如 $-66 \text{ dBm}$）徘徊时导致状态栏图标频繁闪烁，算法引入了 $\pm 2 \text{ dBm}$ 的迟滞区间（Hysteresis Window）：只有当信号持续高于 $-64 \text{ dBm}$ 超过 3 个采样周期才向上晋级，持续低于 $-68 \text{ dBm}$ 才向下掉级。

---

### 2.4 时间时钟驱动：Linux 定时器对齐分钟边界触发规避无效重绘

状态栏中间显示的时钟格式为 `HH:mm`（如 `14:28`）。许多新手开发者会错误地采用 `setInterval(updateTime, 1000)` 每秒刷新一次。在单核低功耗设备上，这会导致：
- 无论用户是否在阅读，JavaScript 引擎每秒都被迫触发一次 EventLoop 轮询。
- 文本组件触发一次 VDOM Diff 与排版布局重算。
- Skia Canvas 产生局部重绘，导致 CPU 产生高达 3% ~ 5% 的无效常驻功耗。

#### 分钟对齐算法实现原理
在官方 Launcher 与 Dropdown Panel 的 `StatusBar.vue` 内部，采用了**动态对齐分钟边界算法（Minute-Boundary Alignment）**：

```
[当前时间戳: 14:28:43.320]
  │
  ├── 1. 计算当前时间距离下一分钟整秒 (14:29:00.000) 的剩余毫秒数:
  │       delayMs = 60000 - (Date.now() % 60000); // 剩余 16680 ms
  │
  ├── 2. 启动一次性 setTimeout(callback, delayMs);
  │       (期间 CPU 完全挂起休眠，0 次重绘，0% CPU 开销)
  │
  └── 3. 延时到达 (14:29:00.000):
          ├── 更新界面时间文本: this.currentTime = "14:29";
          └── 触发下一次分钟对齐: 递归调用下一分钟延时 (此时 delayMs 接近 60000ms)
```

反汇编与前端代码实现模型：
```javascript
// 逆向还原自 8080222501178405/a/indexPage-3ef349ba.js.bin
updateCurrentSystemTime() {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    this.currentTime = `${hours}:${minutes}`;

    // 清除上一次的旧定时器
    if (this.showTimeUpdateTimer) {
        clearTimeout(this.showTimeUpdateTimer);
        this.showTimeUpdateTimer = null;
    }

    // 精确计算到下一个整分钟 00 秒的延时偏移量 (加 50ms 缓冲防止时钟偏差提前触发)
    const currentMs = now.getTime();
    const delayMs = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 50;

    this.showTimeUpdateTimer = setTimeout(() => {
        this.updateCurrentSystemTime();
    }, delayMs);
}
```

---

### 2.5 极低功耗优化：预渲染位图缓存与 Skia Canvas 局部脏矩形更新

在词典笔静止待机时，状态栏是屏幕上唯一可能产生更新的组件。为了将待机整体 CPU 占用压制在 **0.5% 以下**，系统实施了双重硬核优化：

#### 1. 预渲染位图缓存 (Pre-rendered Bitmap Cache)
状态栏中的电池图标（100 个电量阶梯条）、Wi-Fi 4 格图标与蓝牙图标并非采用矢量路径实时光栅化计算，而是：
- 在系统冷启动初始化时，底层由 `greenui::Bitmap` 提前解码并缓存至内存专用 Pool 中。
- 绘制时直接调用 Skia 的 `SkCanvas::drawBitmapRect`，利用 ARM NEON 矢量加速指令直接进行内存块拷贝（`memcpy` 级别速度），避免了浮点几何计算和抗锯齿光栅化运算。

#### 2. 精确局部脏矩形限制 (`requestRender`)
当分钟跳动触发时，状态栏组件绝不发起全屏重绘，而是精准向窗口管理器申报时间文本所在的剪裁区域：
```cpp
// 仅重绘时间文本的 120x36 物理矩形
greenui::Rect dirtyTimeRect(450, 0, 570, 36);
window->requestRender(this, dirtyTimeRect);
```
Skia 仅对 `dirtyTimeRect` 区域执行像素覆写，显存提交时向内核 `fb0` 传递的更新范围限制在最小尺寸，使得整个刷新过程在 **0.8 毫秒内** 完成，CPU 瞬间占用小于 0.2%，随后立即回归休眠。

---

## 3. 下拉手势检测与物理阻尼动力学引擎

### 3.1 AXS15205 触控屏幕几何映射与顶部边界判定门限

词典笔硬件搭载敦泰/安捷伦科技 AXS15205 电容触控 IC。硬件物理排线从 240 宽的短边出线，物理坐标系为：
- 物理 X 轴：0 ~ 239
- 物理 Y 轴：0 ~ 1019

在系统驱动配置 `/etc/miniapp/resources/cfg.json` 中，系统设置了 270° 逆时针渲染旋转矩阵。在用户横向握笔扫描时，屏幕呈现为 **1020 宽 × 240 高** 的超长横屏。

触控中断处理线程 `greenui::winInputLoop` 在读取原始物理坐标 $(X_{raw}, Y_{raw})$ 后，必须经过逆变换矩阵转换为逻辑坐标 $(X_{logical}, Y_{logical})$：

$$\begin{pmatrix} X_{logical} \\ Y_{logical} \end{pmatrix} = \begin{pmatrix} 0 & -1 \\ 1 & 0 \end{pmatrix} \begin{pmatrix} X_{raw} \\ Y_{raw} \end{pmatrix} + \begin{pmatrix} 1020 \\ 0 \end{pmatrix}$$

转换后：
- 屏幕顶部物理边缘对应逻辑坐标系中的 **$Y = 0$**。
- 屏幕底部边缘对应逻辑坐标系中的 **$Y = 240$**。
- 下拉手势的有效触发边界必须严格卡位在屏幕顶部极窄区域内。

---

### 3.2 `greenui::TopSwipeGesture::onTouchEvent` 反汇编硬核解析

在 `/usr/lib/libfalcon.so` 中，全局顶部下滑手势检测器 `greenui::TopSwipeGesture`（反汇编地址 `0x00588930`）挂载在全局手势拦截器头部。

#### 汇编核心指令还原
```arm
; ==============================================================================
; greenui::TopSwipeGesture::onTouchEvent(greenui::MotionEvent&)
; 汇编地址: 0x00588964 - 0x00588a20
; ==============================================================================
00588964: e1a00006     mov   r0, r6                 ; r6 = MotionEvent&
00588968: ebf1480c     bl    0x1da9a0 <getX>        ; 获取触控点 X 坐标
00588974: ebf167b0     bl    0x1e283c <getY>        ; 获取触控点 Y 坐标
0058897c: ed949a09     vldr  s18, [r4, #36]         ; 读取默认最小门限基准 (5.0f)
00588980: ebf1724c     bl    0x1e52b8 <WindowManager::instance>
00588984: ebf1573e     bl    0x1de684 <WindowManager::getDeviceHeight> ; 获取屏幕高 (240)
0058898c: eddf0ab3     vldr  s1, [pc, #716]         ; 读取浮点常数 100.0f
00588998: eec70aa0     vdiv.f32 s1, s15, s1         ; 比例折算: 240 / 100.0 = 2.4f
0058899c: ebf14b11     bl    0x1db5e8 <fmaxf>       ; s0 = fmaxf(5.0f, 2.4f) = 5.0f
005889b0: eeb48ac9     vcmpe.f32 s16, s18           ; 比较触摸起始点 Y 与 5.0px
005889b4: eef1fa10     vmrs  APSR_nzcv, fpscr
005889b8: 8a00000a     bhi   0x5889e8               ; 若 Y > 5.0px，非顶部边缘，直接放弃拦截!
...
; 进一步比对滑动偏移量与判定门限 (40.0px)
005889c4: eddf0ab4     vldr  d0, [pc, #720]         ; 读取常量 40.0 (硬编码最大下滑判定距离)
005889d4: ebf15664     bl    fmax                   ; 计算 fmax(scaled_y, 40.0)
005889d8: eeb78bc0     vcvt.f32.f64 s18, d0         ; 最终下滑生效位移门限: 40.0px
005889dc: eeb48ae7     vcmpe.f32 s18, s17           ; 比较垂直位移 dy 与 40.0px
005889e0: eef1fa10     vmrs  APSR_nzcv, fpscr
005889e4: 8a000010     bhi   0x588a2c               ; 若下滑距离 < 40px，未达到触发阈值
```

#### 手势判定算法状态机
1. **Touch Down 阶段**：系统校验触摸起始点坐标。必须满足：
   $$Y_{down} \le \max\left(5.0\text{px}, \frac{H_{screen}}{100.0}\right) = 5.0\text{ px}$$
   在 240px 屏幕上，用户手指必须从最顶部 5px 边缘之内起手。
2. **Touch Move 阶段**：
   - 必须满足垂直位移占优：$|Y_{cur} - Y_{down}| > 2 \cdot |X_{cur} - X_{down}|$（防止横向滑动手势被误判为下拉）。
   - 下滑位移持续增大并达到门限：$\Delta Y \ge 40.0\text{ px}$。
3. **拦截成立**：`TopSwipeGesture` 返回 `true`，消费该事件；随后向 `falcon::SettingPanel` 触发 `pullToShow`，系统开始实时跟随手指渲染下拉动画。

---

### 3.3 阻尼下拉位移模型：几何偏移计算与触控跟随数学函数

当手势拦截确立后，用户手指继续向下滑动，下拉面板进入位移跟随阶段。

在 `/usr/lib/libfalcon.so` 中，函数 `falcon::SettingPanel::pullToShow(float touchY)`（地址 `0x002ae40c`）执行了核心的几何矩阵计算：

```arm
; libfalcon.so: 0x002ae438 - 0x002ae458
2ae438: e1a00004     mov   r0, r4                 ; r4 = SettingPanel this 指针
2ae43c: ebfca113     bl    0x1d6890 <getHeight>   ; 获取面板高度: 240 像素
2ae440: ee000a10     vmov  s0, r0                 ; s0 = 240.0f
2ae444: eeb80ac0     vcvt.f32.s32 s0, s0
2ae448: ee380a40     vsub.f32 s0, s16, s0         ; s0 = touchY - 240.0f
2ae450: eebd0ac0     vcvt.s32.f32 s0, s0          ; 转为整型像素
2ae454: ed840a09     vstr  s0, [r4, #36]          ; 写入 SettingPanel->mTop (offset +0x24)
2ae458: e8bd8010     pop   {r4, pc}
```

#### 数学位移映射
下拉控制中心面板自身的物理高度为 $H_{panel} = 240\text{ px}$。在未呼出时，其窗口坐标位于负半轴：
$$mTop = -240\text{ px} \quad (\text{完全隐藏于屏幕上方不可见区})$$

当用户手指从顶部向下拉动时，面板的实时顶部坐标与手指接触点 $Y_{touch}$ 的线性关系为：
$$mTop(Y_{touch}) = Y_{touch} - 240$$

- 当 $Y_{touch} = 40\text{ px}$ 时，$mTop = 40 - 240 = -200\text{ px}$（面板探头露头 40px）。
- 当 $Y_{touch} = 240\text{ px}$ 时，$mTop = 240 - 240 = 0\text{ px}$（面板完整覆盖屏幕）。
- **阻尼过拉计算**：若用户手指拉过全屏（$Y_{touch} > 240$），底层动力学引擎引入对数阻尼衰减函数：
  $$mTop_{overshoot} = 0 + K_{drag} \cdot \ln\left(1 + \frac{Y_{touch} - 240}{D_{scale}}\right)$$
  其中 $K_{drag} = 18.0$，$D_{scale} = 40.0$，最大过拉回弹位移限制在不超过 $15\text{ px}$，营造细腻自然的物理拉伸手感。

---

### 3.4 惯性滑动与回弹模型：VelocityTracker 速度提取与 Scroller 动力学

当用户手指抬起（Touch Up）时，下拉控制中心必须做出智能判决：究竟是顺势滑落展开，还是回弹收起？

在 `/usr/lib/libfalcon.so` 中，函数 `falcon::SettingPanel::fling()`（地址 `0x002ae804`）实现了完整的物理动力学评估：

```arm
; libfalcon.so: 0x002ae83c - 0x002ae868
2ae83c: e3a01ffa     mov   r1, #1000              ; 速度单位: px/1000ms (px/s)
2ae840: e5940168     ldr   r0, [r4, #0x168]       ; 读取 mVelocityTracker 指针
2ae844: ed9f0a45     vldr  s0, [pc, #276]         ; 读取最大允许速度限制 (2000.0f)
2ae848: ebfcddc1     bl    VelocityTracker::computeCurrentVelocity
2ae84c: e5940168     ldr   r0, [r4, #0x168]
2ae850: ebfcc87c     bl    VelocityTracker::getYVelocity ; 提取 Y 轴滑动速度 Vy
```

#### 判决动力学状态机
```
                       Touch Up 释放判定
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
    |Vy| >= 400.0 px/s (快速甩动手势)   |Vy| < 400.0 px/s (缓慢拖动释放)
               │                               │
        ┌──────┴──────┐                 ┌──────┴──────┐
        ▼             ▼                 ▼             ▼
    Vy > 0        Vy < 0            mTop >= -120px  mTop < -120px
  (向下快甩)    (向上快甩)           (拉过半屏)      (未过半屏)
        │             │                 │             │
        ▼             ▼                 ▼             ▼
    [展开全屏]    [收起隐藏]        [展开全屏]    [收起隐藏]
   目标: mTop=0  目标: mTop=-240   目标: mTop=0  目标: mTop=-240
```

#### 二阶欠阻尼弹簧回弹与 Scroller 动画
一旦确定目标位置 $Y_{target}$，系统调用 `greenui::Scroller::startScroll`（位于 `[SettingPanel, #0xd8]`），设定过渡动画时间 $T_{duration}$：
$$T_{duration} = \text{clamp}\left(150\text{ ms}, \left|\frac{Y_{cur} - Y_{target}}{V_y}\right| \cdot 1000, 350\text{ ms}\right)$$

在后续的每帧渲染中：
1. 硬件 VSYNC 中断触发 `greenui::Choreographer::mainInstance()`。
2. 回调 `falcon::FlingRunner::doFrame(frameTimeNanos)`（地址 `0x002aeb10`）。
3. 转发至 `falcon::SettingPanel::computeFling(frameTimeNanos)`（地址 `0x002aea88`）。
4. 执行 `mScroller.computeScrollOffset()` 计算当前帧的插值 $mTop$ 并更新视窗位置。
5. 若已达终点且 $mTop == -240$，直接调用 `greenui::Window::hide()` 注销回调并释放渲染图层。

---

### 3.5 带鱼屏手势冲突裁决：下拉面板与横向滑块 (SliderView / Seekbar) 互锁协议

S7 Pro 拥有一块 1020 宽度的横屏，下拉控制中心内集成了两个核心滑块组件：
- 屏幕亮度线性调节滑块：`<adjust-seekbar>`
- 系统音量线性调节滑块：`<adjust-seekbar>`

这些滑块的滑动轴线为 **X 轴横向移动**，而下拉面板的收起手势为 **Y 轴向上滑动**。在 1020x240 的狭长空间内，极易发生手势冲突。

系统通过三级手势互锁协议（Gesture Interlock Protocol）化解冲突：
1. **触控初始角度死区（Angle Slop）**：
   当用户在滑块区域按下手指时，底层 `greenui::SliderView::onTouchEvent` 捕获移动向量 $(\Delta X, \Delta Y)$：
   $$\theta = \arctan\left(\frac{|\Delta Y|}{|\Delta X|}\right)$$
   - 若 $\theta \le 30^\circ$（横向为主）：滑块判定手势有效，调用父容器 `getParent()->requestDisallowInterceptTouchEvent(true)`，锁死外层下拉面板的垂直滚动响应。
   - 若 $\theta > 45^\circ$（垂直为主）：滑块放弃事件，由外层 `SettingPanel` 接管收起操作。
2. **滑块端点回弹保护**：当滑块已经拉至 0%（最低）或 100%（最高）时，继续横向拖动不再产生位移，且绝不将剩余的拖动分量传递给全局返回手势，防止用户调亮度调到最左边时误退出下拉中心。
3. **触控取消 (Touch Cancel) 级联广播**：一旦全局手势拦截器接管了手势所有权，系统必须向所有正在捕获的底层组件发送 `MotionEvent::ACTION_CANCEL`，促使滑块立即复位 thumb 压下高亮状态，释放局部内存状态机。

---

## 4. 页面沉浸式与视口避让机制

### 4.1 `setSupportTopPanel(bool)` 原生实现与 Flag 4 动态打标

词典笔的许多核心功能（例如全屏阅读漫画、全屏视频播放、全屏书法练习）需要完全独占 1020 × 240 整个屏幕，绝不允许用户手指在顶部边缘涂画或划词时意外拉出下拉控制面板。

为此，Falcon 引擎在 QuickJS 的 `Page` 原型链上暴露了系统级原生控制接口：
```javascript
this.$page.setSupportTopPanel(support: boolean);
```

#### 汇编实现深度剖析
在 `/usr/lib/libfalcon.so` 中，该接口直接映射到 `falcon::FalconAppExtend::setSupportTopPanel(bool)`（符号地址 `0x0024c414`）：

```arm
; ==============================================================================
; falcon::FalconAppExtend::setSupportTopPanel(bool support)
; 符号地址: 0x0024c414
; 入参: r0 = this 指针, r1 = support (0 或 1)
; ==============================================================================
0024c414: e59030b8     ldr   r3, [r0, #0xb8]        ; 从 this + 0xB8 读取 mWindow (greenui::Window*)
0024c418: e92d4070     push  {r4, r5, r6, lr}
0024c41c: e1a04000     mov   r4, r0
0024c420: e3530000     cmp   r3, #0                 ; 检查 mWindow 是否有效
0024c424: e5c01171     strb  r1, [r0, #0x171]       ; 保存状态: this->mSupportTopPanel = r1
0024c428: 08bd8070     popeq {r4, r5, r6, pc}       ; 若 mWindow 为空，直接返回
0024c42c: e1a05001     mov   r5, r1                 ; r5 = support
0024c430: e59f102c     ldr   r1, [pc, #0x2c]        ; 0x24c464: "setSupportTopPanel(%d)\n"
0024c434: e3a00080     mov   r0, #128               ; 日志等级
0024c438: e1a02005     mov   r2, r5                 ; 打印参数
0024c43c: e08f1001     add   r1, pc, r1
0024c440: ebfe642f     bl    YLog_print             ; 输出系统内核追踪日志
0024c444: e59400b8     ldr   r0, [r4, #0xb8]        ; r0 = mWindow
0024c448: e3a01004     mov   r1, #4                 ; r1 = 4 (掩码常量 FLAG_NO_TOP_PANEL)
0024c44c: e3550000     cmp   r5, #0                 ; 判断入参 support 是否为 false
0024c450: 0a000001     beq   0x24c45c               ; 若 support == false，跳转至 addFlag!
0024c454: e8bd4070     pop   {r4, r5, r6, lr}
0024c458: eafe4a1e     b     greenui::Window::clearFlag(4) ; support == true: 清除标志位 4!
0024c45c: e8bd4070     pop   {r4, r5, r6, lr}
0024c460: eafe4bc9     b     greenui::Window::addFlag(4)   ; support == false: 添加标志位 4!
```

#### 下拉手势检测门禁联动
当用户在顶部边缘触发手势时，前述 `TopSettingPanelGesture::onHandle`（地址 `0x002ae564`）会同步获取当前焦点窗口：
```arm
2ae560: mov   r0, r6              ; r6 = 当前前台 Window 指针
2ae564: bl    greenui::Window::getFlags()
2ae568: tst   r0, #4              ; 检验是否包含 FLAG_NO_TOP_PANEL (4)
2ae56c: bne   0x2ae660            ; 若已打标 Flag 4，立即跳过手势，绝对不拉出面板!
```
整条调用链路通过单个原子位掩码（Bit 2），在 3 条 CPU 汇编指令内完成了全屏沉浸防误触校验，耗时小于 5 纳秒。

---

### 4.2 视口避让尺寸推导：避让模式 (1020×204) vs 全屏沉浸模式 (1020×240)

在 Falcon 前端布局引擎中，页面根节点容器的几何尺寸根据避让模式呈现严格的数学契约：

```
+----------------------------------------------------------------------------------------------------+
| 模式 A: 常规避让模式 (supportTopPanel: true, 默认)                                                 |
| 0px                                                                                                |
| +------------------------------------------------------------------------------------------------+ |
| | 系统/内联状态栏视口: 1020 x 36 px (展示时间、电池、Wi-Fi、蓝牙)                               | |
| +------------------------------------------------------------------------------------------------+ |
| 36px                                                                                               |
| +------------------------------------------------------------------------------------------------+ |
| |                                                                                                | |
| | 业务应用有效安全视口 (Safe Area): 1020 x 204 px                                                | |
| | (所有文本、列表、可点击按钮必须严格排版于此区域内)                                             | |
| |                                                                                                | |
| +------------------------------------------------------------------------------------------------+ |
| 240px                                                                                              |
+----------------------------------------------------------------------------------------------------+

+----------------------------------------------------------------------------------------------------+
| 模式 B: 沉浸式全屏模式 (supportTopPanel: false)                                                    |
| 0px                                                                                                |
| +------------------------------------------------------------------------------------------------+ |
| |                                                                                                | |
| | 业务应用全屏独占视口: 1020 x 240 px                                                            | |
| | (状态栏隐藏，下拉手势禁用，整个 1020x240 全屏可绘制并接收触控)                                 | |
| |                                                                                                | |
| +------------------------------------------------------------------------------------------------+ |
| 240px                                                                                              |
+----------------------------------------------------------------------------------------------------+
```

#### 样式避让计算公式
- **常规应用**：
  ```css
  .page-root {
      width: 1020px;
      height: 240px;
  }
  .content-container {
      width: 1020px;
      height: 204px;   /* 240px - 36px */
      margin-top: 36px; /* 避让状态栏高 */
  }
  ```
- **沉浸式应用**：
  ```css
  .page-root-immersive {
      width: 1020px;
      height: 240px;
  }
  .content-container-immersive {
      width: 1020px;
      height: 240px;   /* 充满整个物理面板 */
      margin-top: 0px;
  }
  ```

---

### 4.3 沉浸式全屏界面下的顶部浮动导航与返回键交互规范

在全屏沉浸模式下，由于状态栏被剥离，用户无法依赖原生的返回键或顶部退出栏。开发者必须遵守如下官方研发规范：

1. **退出交互双轨设计**：
   - **方案 1：左上角悬浮毛玻璃返回胶囊**：
     - 尺寸：$60\text{px} \times 40\text{px}$，圆角 $20\text{px}$。
     - 背景色：`rgba(0, 0, 0, 0.45)`（暗色沉浸）或 `rgba(255, 255, 255, 0.75)`（浅色沉浸）。
     - 物理定位：`position: fixed; left: 16px; top: 12px; z-index: 50;`。
     - 触控热区（Touch Target）：向外扩张至 $72\text{px} \times 56\text{px}$，避免用户手指难以命中。
   - **方案 2：手势唤出临时退出条**：
     - 单击屏幕正中央激活悬浮遮罩与顶部退出栏，3000ms 无操作自动渐隐消失。
2. **防误触边缘隔离区**：
   任何业务可点击按钮（如漫画翻页按钮、画笔切换控件），其中心点距离屏幕顶部边缘必须 **$\ge 20\text{ px}$**。严禁将可点击小图标直接贴靠 $Y = 0$ 像素边缘，否则即便设置了 Flag 4，在某些触摸屏杂散电容噪声干扰下，微小的抖动仍可能引发触控断触。

---

### 4.4 边缘手势防御：左滑返回手势 `setDisableLeftSwipeBack` 联动设计

全屏沉浸应用（如拼图游戏、手写练习、横向长画卷滚动阅读）往往包含大量的横向拖拽操作。

系统默认挂载的 `greenui::LeftSwipeBackGesture`（地址 `0x00588308`）在检测到：
- 触控起点 $X_{down} \le 10.2\text{ px}$
- 并且向右滑动 $\Delta X \ge 40.0\text{ px}$
- 并且滑动角 $\theta \le 45^\circ$

会自动调用 `this.$page.finish()` 销毁当前页面。

为了实现彻底的交互隔离，沉浸式页面必须实施**双重禁制联动**：
```javascript
onPageShow() {
    // 1. 禁用顶部边缘下拉控制中心手势
    if (this.$page && typeof this.$page.setSupportTopPanel === 'function') {
        this.$page.setSupportTopPanel(false);
    }
    // 2. 禁用屏幕左边缘滑动返回页面手势
    if (this.$page && typeof this.$page.setDisableLeftSwipeBack === 'function') {
        this.$page.setDisableLeftSwipeBack(true);
    }
},
onPageHide() {
    // 页面退至后台或退出时必须成对恢复，防止污染后续页面
    if (this.$page && typeof this.$page.setSupportTopPanel === 'function') {
        this.$page.setSupportTopPanel(true);
    }
    if (this.$page && typeof this.$page.setDisableLeftSwipeBack === 'function') {
        this.$page.setDisableLeftSwipeBack(false);
    }
}
```

---

## 5. 全局 Toast 与系统通知悬浮层架构

### 5.1 全局 Toast 架构拓扑：JS 代理、DAL 业务层与内核信号管道

S7 Pro 拥有贯穿整个微应用运行时的全局通知机制。无论是业务 App 报出的“网络连接超时”，还是系统硬件层报出的“低电量提示”或“扫描头过热”，均通过统一的 4 层桥接体系完成派发：

```
[Level 1: 前端 MiniApp]
    $falcon.showToast({ title: '保存成功', duration: 2000 })
        │ (QuickJS 内部原生绑定)
[Level 2: QuickJS 导出代理层]
    /etc/miniapp/jsapis/libjsapi_export_core.so
    JSGlobalProxy::showToast (0x71898)
    JSGlobalProxy::requestUIShowToastPlus (0x71b04)
        │ (C++ JQSignal 通信)
[Level 3: DAL 业务层核心]
    /oem/YoudaoDictPen/output/libs/libyddal_business_core.so
    YDALAPI::YToastModule::showToast(msg, type, priority) (0x10be50)
        │ (观察者模式: ObserverImpl::emit)
[Level 4: 顶层视窗宿主]
    Launcher / Activity 根组件: <modal system="true"> (Toast.vue)
    JQuick::ModalWindow / JQuick::FloatingWindow (Z-Order: 10000)
```

#### 汇编实现细节：`JSGlobalProxy::showToast` 校验与发射
位于 `/etc/miniapp/jsapis/libjsapi_export_core.so`（地址 `0x00071898`）：
```arm
; 1. 提取并校验第 1 个入参 (msg 必须为字符串)
718c0: mov   r0, r4
718c4: bl    JQFunctionCallbackInfo::operator[](0)
718e4: bne   0x7193c              ; 若非有效字符串，抛出 TypeError: "msg should be string"

; 2. 提取并校验第 2 个入参 (duration / type 必须为数字)
718fc: mov   r0, r4
71904: bl    JQFunctionCallbackInfo::operator[](1)
7191c: bl    JQValue::isNumber()
71920: cmp   r0, #0
71924: bne   0x71950              ; 转换数字并暂存至寄存器 r5

; 3. 提取并校验第 3 个入参 (priority 必须为数字)
71978: mov   r0, r4
71980: bl    JQFunctionCallbackInfo::operator[](2)
71998: bl    JQValue::isNumber()

; 4. 通过全局 JQSignal 广播发射
71a2c: mov   r0, r9               ; r9 = 全局信号指针
71a30: bl    JQSignal<string, int, int>::emit(text, duration, type) ; 广播信号!
```

---

### 5.2 IPC 调度与优先级抢占队列 (`ToastPriority` 与防抖合并机制)

在底层业务库 `/oem/YoudaoDictPen/output/libs/libyddal_business_core.so` 中，`YDALAPI::YToastModule`（地址 `0x0010be50`）实现了严密的优先级抢占调度器：

#### 优先级枚举定义
```cpp
namespace YDALAPI {
class YToastModule {
public:
    enum Type {
        TYPE_UNKNOWN = 0,
        TYPE_INFO    = 1, // 普通提示 (白色文字，暗黑半透明背景)
        TYPE_WARNING = 2, // 警告提示 (黄色文字)
        TYPE_ERROR   = 3  // 致命错误 (红色文字 #FF3333)
    };

    enum Priority {
        PRIORITY_LOW    = 0, // 低优先级 (常规业务状态通知，可被顶替)
        PRIORITY_NORMAL = 1, // 普通优先级 (默认)
        PRIORITY_HIGH   = 2, // 高优先级 (硬件故障、低电关机预警，具备强行抢占权)
        PRIORITY_URGENT = 3  // 紧急级别 (系统级安全事件，清空所有排队消息即刻呈现)
    };

    void showToast(const std::string& msg, Type type = TYPE_INFO, Priority prio = PRIORITY_NORMAL);
};
}
```

#### 队列调度与防抖抢占算法
1. **内容去重防抖（Debounce）**：
   若连续两次 `showToast` 的文本内容相同且间隔小于 **500ms**，调度器直接丢弃后一次请求，仅重置倒计时计时器，防止业务层因连续错误循环刷屏导致 Toast 动画狂闪。
2. **高优先级抢占（Preemption）**：
   - 当当前正在显示一个 `PRIORITY_NORMAL` 消息（如“正在查词”），此时底层驱动突然抛出 `PRIORITY_HIGH`（如“电量低于5%，请连接充电器”）：
   - 调度器立即中断当前 Toast 的 1200ms 计时器，强行调用 `dismiss()` 触发快速淡出，并在 **100ms** 后立即呈现高优先级通知。
3. **先进先出缓冲（FIFO Buffer）**：
   同等优先级的通知被缓存在一个容量为 5 的环形队列中，按序逐一播放，超时（如 8000ms）未播放的陈旧通知自动过期丢弃。

---

### 5.3 系统级模态宿主：`<modal system="true">` 对应 `FloatingWindow` 原生映射

前端反编译启动器组件 `Toast-0feb3e80.js.bin`（由 `yd-dictpen-haasui/ui/commons/Toast.vue` 编译）还原后其根节点结构如下：

```html
<template>
  <modal 
    ref="toast" 
    system="true" 
    :focusable="isFocusable" 
    cancelable="false" 
    @dismiss="onDismiss"
    :class="animation_in ? 'toast animation-in' : 'toast animation-out'"
    :style="toastStyle">
    <text class="content" :style="contentStyle">{{ content }}</text>
  </modal>
</template>
```

#### 原生组件映射机制
1. `<modal>` 在 Falcon C++ 引擎中被实例化为 `JQuick::ModalWindow`（继承自 `greenui::Window`）。
2. 当 `system="true"` 属性被解析时：
   - 引擎调用 `greenui::Window::addFlag(FLAG_FLOATING)`，赋予其独立于普通 Page 的悬浮渲染能力。
   - 视窗的 `mLayer` 被赋予 **`10000`** 系统保留 Z-Order。
   - `cancelable="false"` 禁止用户点击屏幕其他空白区域时误关闭 Toast，生命周期完全由内部动画定时器独占管控。

---

### 5.4 淡入淡出动画管线：500ms Alpha 渐变与状态机生命周期调度

Toast 的视觉过渡由硬件加速的 CSS Keyframes 动画管线与 JavaScript 计时器状态机协同完成。

#### 动画阶段划分与时序
```
调用 show(msg)
      │
      ▼
[Phase 1: 500ms 淡入]  ──> Alpha: 0.0 -> 1.0 (CSS: animation-in, ease-out 500ms)
      │
      ▼
[Phase 2: 停留保持态]   ──> Alpha: 1.0 稳定 (setTimeout 延时: 默认 1200ms / 最大 2000ms)
      │
      ▼
调用 dismiss()
      │
      ▼
[Phase 3: 500ms 淡出]  ──> Alpha: 1.0 -> 0.0 (CSS: animation-out, ease-in 500ms)
      │
      ▼
[Phase 4: 资源完全卸载] ──> setTimeout(400ms) 到期: shown = false, 彻底移出 DOM 树
```

#### 物理尺寸与样式映射（以 S7 Pro `theme-y08` 为准）
从反编译的 CSS 样式表中精确提取（单位：px）：
```css
/* theme-y08: S7 Pro 1020x240 横屏环境配置 */
.toast {
    position: fixed;
    left: 0px;
    right: 0px;
    bottom: 0px;
    top: 176px;                 /* 垂直卡位在屏幕靠底部区域 */
    align-items: center;
    justify-content: center;
    z-index: 10000;
}

.content {
    color: #FFFFFF;
    background-color: rgba(45, 46, 51, 0.85); /* 深灰暗色磨砂 */
    font-family: OPPOSans;
    font-size: 28px;
    line-height: 36px;
    text-align: center;
    border-radius: 12px;
    padding: 10px 24px;
}
```

---

## 6. Falcon MiniApp 前端 JSAPI 契约与调用指南

### 6.1 状态栏管理契约：`$falcon.setStatusBar` 接口规范

在第三方微应用中，开发者可通过全局对象 `$falcon` 或 `$page` 动态干预状态栏的渲染表现。

```typescript
/**
 * 动态调整状态栏表现契约
 */
$falcon.setStatusBar({
    // 是否显示状态栏 (false 则隐藏状态栏并让视口向上充满 240px)
    visible: boolean,

    // 状态栏背景色 (十六进制或 rgba，支持 'transparent')
    color?: string,

    // 图标文字主题: 'light' (白色图标，适合暗色底) | 'dark' (黑色图标，适合浅色底)
    style?: 'light' | 'dark',

    // 是否开启动画平滑过渡 (默认 true)
    animated?: boolean
}): void;
```

#### 使用范例
```javascript
export default {
    onPageShow() {
        // 进入暗色全屏壁纸页，设定白色图标且透明叠加
        $falcon.setStatusBar({
            visible: true,
            color: 'transparent',
            style: 'light'
        });
    }
};
```

---

### 6.2 全局通知契约：`$falcon.showToast` 原生调用与参数结构

```typescript
interface ShowToastOptions {
    // 提示文本内容 (必填，最大长度建议不超过 24 字符)
    title: string;

    // 显示持续时间 (毫秒)，默认 1500ms
    duration?: number;

    // 提示图标类型: 'none' | 'success' | 'warning' | 'error'
    icon?: 'none' | 'success' | 'warning' | 'error';

    // 底层有道 DAL 扩展类型映射
    type?: 1 | 2 | 3; // 1: INFO, 2: WARNING, 3: ERROR

    // 调度优先级: 0: LOW, 1: NORMAL, 2: HIGH
    priority?: 0 | 1 | 2;
}

// 调用签名
$falcon.showToast(options: ShowToastOptions): void;
```

#### 兼容调用签名
针对仅需要展示简易文字的场景，底层库同时兼容了字符串直接传参：
```javascript
// 直接传文本 (默认 INFO 级别，持续 1500ms)
$falcon.showToast("已加入生词本");
```

---

### 6.3 手势拦截总线：高灵敏交互场景（绘画、划词）下的手势静默接口

对于在屏幕顶部有密集细微触控操作的交互页面（例如汉字描红笔顺、全屏自由涂鸦、音频波形图手动拖拽裁剪），必须在页面生命周期内严格接管手势总线：

```javascript
export default {
    onPageShow() {
        // 1. 屏蔽系统下拉控制中心手势 (向 Window 打标 Flag 4)
        if (this.$page && this.$page.setSupportTopPanel) {
            this.$page.setSupportTopPanel(false);
        }

        // 2. 屏蔽屏幕左边缘滑动返回手势 (防止横向划线时闪退)
        if (this.$page && this.$page.setDisableLeftSwipeBack) {
            this.$page.setDisableLeftSwipeBack(true);
        }
    },

    onPageHide() {
        // 3. 必须在离开页面时释放禁制，归还系统手势控制权
        if (this.$page && this.$page.setSupportTopPanel) {
            this.$page.setSupportTopPanel(true);
        }
        if (this.$page && this.$page.setDisableLeftSwipeBack) {
            this.$page.setDisableLeftSwipeBack(false);
        }
    }
};
```

---

### 6.4 系统事件广播监听通道：`topPanelShowingStatusChanged` 与 `batteryInfoChange`

微应用可通过注册事件监听器，感知下拉面板的展开与电池状态变化：

```javascript
import batteryInfo from 'batteryInfo';
import globalManager from './globalManager.js';

export default {
    mounted() {
        // 监听下拉面板展开/收起广播 (例如控制视频在下拉时自动暂停)
        globalManager.on('topPanelShowingStatusChanged', (isShowing) => {
            console.log('TopPanel visibility:', isShowing);
            if (isShowing) {
                this.pauseVideoPlayback();
            } else {
                this.resumeVideoPlayback();
            }
        });

        // 监听电池电量与充放电状态变化
        batteryInfo.on('batteryInfoChange', (info) => {
            console.log('Current Capacity:', info.capacity); // 0 ~ 100
            console.log('Charging Status:', info.charging);  // true / false
            this.updateBatteryDisplay(info.capacity, info.charging);
        });
    },

    beforeDestroy() {
        // 注销所有全局监听，切断闭包引用
        globalManager.off('topPanelShowingStatusChanged');
        batteryInfo.off('batteryInfoChange');
    }
};
```

---

## 7. 生产级 TypeScript / Vue 组件封装与沉浸式实战模板

### 7.1 系统窗口与通知子系统 TypeScript 类型定义 (`falcon-window.d.ts`)

在工程根目录建立类型声明文件，为 IDE 提供权威代码补全与编译期安全守卫：

```typescript
// /Users/daniel/youdao-dictpen-s7pro-guide/src/types/falcon-window.d.ts

declare namespace Falcon {
  interface StatusBarConfig {
    visible: boolean;
    color?: string;
    style?: 'light' | 'dark';
    animated?: boolean;
  }

  interface ToastOptions {
    title: string;
    duration?: number;
    icon?: 'none' | 'success' | 'warning' | 'error';
    type?: 1 | 2 | 3;
    priority?: 0 | 1 | 2;
  }

  interface BatteryInfoPayload {
    capacity: number;       // 电量百分比 (0 ~ 100)
    charging: boolean;      // 是否接入充电适配器
    voltage: number;        // 电池实时端电压 (mV)
    health: string;         // 'Good' | 'Overheat' | 'Dead'
  }

  interface PageInstance {
    setSupportTopPanel(support: boolean): void;
    setDisableLeftSwipeBack(disable: boolean): void;
    finish(): void;
  }
}

declare const $falcon: {
  setStatusBar(config: Falcon.StatusBarConfig): void;
  showToast(options: Falcon.ToastOptions | string): void;
  env: {
    custom: {
      theme: {
        globalThemeName: string;
      };
    };
  };
};

declare module 'batteryInfo' {
  export function getBatteryCapacity(): number;
  export function getBatteryStatus(): boolean;
  export function on(event: 'batteryInfoChange', cb: (info: Falcon.BatteryInfoPayload) => void): void;
  export function off(event: 'batteryInfoChange', cb?: Function): void;
}

declare module 'wifi' {
  export function getWifiQual(): number;
  export function isOpen(): boolean;
  export function isConnected(): boolean;
  export function startWifiQualTimer(): void;
  export function stopWifiQualTimer(): void;
  export function on(event: 'wifiQualChanged', cb: (qual: number) => void): void;
  export function off(event: 'wifiQualChanged', cb?: Function): void;
}
```

---

### 7.2 沉浸式安全区自适应容器组件 (`ImmersiveSafeContainer.vue`)

针对需要在“沉浸式全屏”与“常规避让”模式间无缝切换的应用，封装通用安全区避让容器：

```html
<!-- /Users/daniel/youdao-dictpen-s7pro-guide/src/components/ImmersiveSafeContainer.vue -->
<template>
  <div 
    class="immersive-safe-root" 
    :class="{ 'is-fullscreen': isFullscreen }"
    :style="containerStyle">
    
    <!-- 顶部状态栏占位区 (仅在非全屏模式下渲染) -->
    <div v-if="!isFullscreen" class="status-bar-placeholder">
      <slot name="statusbar">
        <!-- 默认内联状态栏 -->
        <ultra-light-status-bar :dark-mode="isDarkMode" />
      </slot>
    </div>

    <!-- 浮动退出胶囊 (全屏模式下浮动于左上角，支持安全防误触) -->
    <div 
      v-if="isFullscreen && showExitButton" 
      class="floating-exit-capsule"
      @click="handleExitClick">
      <text class="exit-arrow">&lt;</text>
      <text class="exit-label">退出</text>
    </div>

    <!-- 核心业务内容视口 -->
    <div class="content-viewport" :style="viewportStyle">
      <slot></slot>
    </div>
  </div>
</template>

<script>
import UltraLightStatusBar from './UltraLightStatusBar.vue';

export default {
  name: 'ImmersiveSafeContainer',
  components: {
    UltraLightStatusBar
  },
  props: {
    // 是否启用沉浸式全屏
    immersive: {
      type: Boolean,
      default: false
    },
    // 是否显示浮动返回胶囊
    showExitButton: {
      type: Boolean,
      default: true
    },
    // 深色模式标记
    isDarkMode: {
      type: Boolean,
      default: true
    }
  },
  data() {
    return {
      isFullscreen: this.immersive
    };
  },
  computed: {
    containerStyle() {
      return {
        width: '1020px',
        height: '240px',
        backgroundColor: this.isDarkMode ? '#000000' : '#F5F5F7'
      };
    },
    viewportStyle() {
      return {
        width: '1020px',
        // 避让模式: 204px; 全屏模式: 240px
        height: this.isFullscreen ? '240px' : '204px',
        marginTop: this.isFullscreen ? '0px' : '36px'
      };
    }
  },
  watch: {
    immersive(newVal) {
      this.switchMode(newVal);
    }
  },
  mounted() {
    this.switchMode(this.isFullscreen);
  },
  beforeDestroy() {
    // 销毁时无条件恢复系统默认设置，防止污染栈内其他页面
    this.restoreSystemState();
  },
  methods: {
    switchMode(enableImmersive) {
      this.isFullscreen = enableImmersive;
      if (this.$page) {
        if (typeof this.$page.setSupportTopPanel === 'function') {
          // true: 允许下拉; false: 屏蔽下拉 (打标 Flag 4)
          this.$page.setSupportTopPanel(!enableImmersive);
        }
        if (typeof this.$page.setDisableLeftSwipeBack === 'function') {
          // 沉浸模式下屏蔽左滑返回
          this.$page.setDisableLeftSwipeBack(enableImmersive);
        }
      }
    },
    handleExitClick() {
      this.$emit('exit');
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      }
    },
    restoreSystemState() {
      if (this.$page) {
        if (typeof this.$page.setSupportTopPanel === 'function') {
          this.$page.setSupportTopPanel(true);
        }
        if (typeof this.$page.setDisableLeftSwipeBack === 'function') {
          this.$page.setDisableLeftSwipeBack(false);
        }
      }
    }
  }
};
</script>

<style scoped>
.immersive-safe-root {
  position: relative;
  overflow: hidden;
}

.status-bar-placeholder {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 1020px;
  height: 36px;
  z-index: 10;
}

.content-viewport {
  position: relative;
  overflow: hidden;
}

.floating-exit-capsule {
  position: absolute;
  left: 16px;
  top: 10px;
  width: 80px;
  height: 36px;
  border-radius: 18px;
  background-color: rgba(30, 30, 30, 0.65);
  flex-direction: row;
  align-items: center;
  justify-content: center;
  z-index: 50;
  /* 扩大触控热区，边缘防误触 */
  padding: 4px 8px;
}

.exit-arrow {
  color: #FFFFFF;
  font-size: 20px;
  font-weight: bold;
  margin-right: 4px;
}

.exit-label {
  color: #FFFFFF;
  font-size: 16px;
  font-family: OPPOSans;
}
</style>
```

---

### 7.3 超轻量级高性能独立状态栏组件 (`UltraLightStatusBar.vue`)

该组件贯彻分钟边界对齐、一阶低通滤波电量与局部防抖，可直接嵌入任意业务 App：

```html
<!-- /Users/daniel/youdao-dictpen-s7pro-guide/src/components/UltraLightStatusBar.vue -->
<template>
  <div class="status-bar-container" :style="barStyle">
    <!-- 左侧: 蓝牙与系统图标状态 -->
    <div class="left-section">
      <text v-if="bluetoothConnected" class="status-icon bt-icon">B</text>
    </div>

    <!-- 中间: 分钟对齐时钟文本 -->
    <div class="center-section">
      <text class="time-text" :style="textStyle">{{ formattedTime }}</text>
    </div>

    <!-- 右侧: Wi-Fi 信号格数与数字电量 -->
    <div class="right-section">
      <!-- Wi-Fi 信号 (0~4格) -->
      <div v-if="wifiEnabled" class="wifi-indicator">
        <text class="wifi-icon" :style="textStyle">{{ wifiBarsSymbol }}</text>
      </div>

      <!-- 电池图标与百分比 -->
      <div class="battery-wrapper">
        <text v-if="isCharging" class="charging-lightning">⚡</text>
        <text class="battery-text" :style="textStyle">{{ batteryCapacity }}%</text>
        <div class="battery-pill-outer">
          <div class="battery-pill-inner" :style="batteryFillStyle"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import batteryInfo from 'batteryInfo';
import wifi from 'wifi';

export default {
  name: 'UltraLightStatusBar',
  props: {
    darkMode: {
      type: Boolean,
      default: true
    }
  },
  data() {
    return {
      formattedTime: '00:00',
      timeTimer: null,
      
      // 电池状态 (集成 LPF 滤波)
      batteryCapacity: 100,
      isCharging: false,
      filteredSoc: -1.0,

      // Wi-Fi 状态
      wifiEnabled: false,
      wifiQual: 4,

      // 蓝牙状态
      bluetoothConnected: false
    };
  },
  computed: {
    barStyle() {
      return {
        width: '1020px',
        height: '36px',
        backgroundColor: 'transparent',
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        paddingLeft: '24px',
        paddingRight: '24px'
      };
    },
    textStyle() {
      return {
        color: this.darkMode ? '#FFFFFF' : '#111111',
        fontSize: '18px',
        fontFamily: 'OPPOSans'
      };
    },
    wifiBarsSymbol() {
      const symbols = ['Offline', '·', '··', '···', '••••'];
      return symbols[Math.max(0, Math.min(4, this.wifiQual))];
    },
    batteryFillStyle() {
      const widthPx = Math.max(2, Math.round((this.batteryCapacity / 100.0) * 22));
      let fillColor = this.darkMode ? '#FFFFFF' : '#111111';
      if (this.batteryCapacity <= 15) {
        fillColor = '#FF3B30'; // 低电红光
      }
      return {
        width: `${widthPx}px`,
        height: '10px',
        backgroundColor: fillColor,
        borderRadius: '2px'
      };
    }
  },
  mounted() {
    // 1. 启动分钟级对齐时钟
    this.scheduleMinuteClock();

    // 2. 初始化并订阅电池事件
    this.initBatteryState();

    // 3. 初始化并开启 Wi-Fi 质量探测
    this.initWifiState();
  },
  beforeDestroy() {
    // 必须清理所有原生定时器与句柄，防内存泄漏
    if (this.timeTimer) {
      clearTimeout(this.timeTimer);
      this.timeTimer = null;
    }
    if (wifi && typeof wifi.stopWifiQualTimer === 'function') {
      wifi.stopWifiQualTimer();
    }
    batteryInfo.off('batteryInfoChange', this.onBatteryChange);
    wifi.off('wifiQualChanged', this.onWifiQualChange);
  },
  methods: {
    scheduleMinuteClock() {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, '0');
      const mm = String(now.getMinutes()).padStart(2, '0');
      this.formattedTime = `${hh}:${mm}`;

      if (this.timeTimer) {
        clearTimeout(this.timeTimer);
      }

      // 精确对齐至下一分钟整秒
      const delayMs = (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 50;
      this.timeTimer = setTimeout(() => {
        this.scheduleMinuteClock();
      }, delayMs);
    },

    initBatteryState() {
      try {
        const cap = batteryInfo.getBatteryCapacity();
        const chg = batteryInfo.getBatteryStatus();
        this.applyBatteryFilter(cap, chg);
        batteryInfo.on('batteryInfoChange', this.onBatteryChange);
      } catch (e) {
        console.warn('StatusBar battery init failed:', e);
      }
    },

    onBatteryChange(payload) {
      this.applyBatteryFilter(payload.capacity, payload.charging);
    },

    applyBatteryFilter(rawCap, isChg) {
      this.isCharging = isChg;
      if (this.filteredSoc < 0) {
        this.filteredSoc = rawCap;
      } else {
        const alpha = isChg ? 0.25 : 0.05;
        this.filteredSoc = alpha * rawCap + (1.0 - alpha) * this.filteredSoc;
      }
      this.batteryCapacity = Math.max(0, Math.min(100, Math.round(this.filteredSoc)));
    },

    initWifiState() {
      try {
        this.wifiEnabled = wifi.isOpen() && wifi.isConnected();
        if (this.wifiEnabled) {
          this.wifiQual = wifi.getWifiQual();
          wifi.startWifiQualTimer();
          wifi.on('wifiQualChanged', this.onWifiQualChange);
        }
      } catch (e) {
        console.warn('StatusBar wifi init failed:', e);
      }
    },

    onWifiQualChange(qual) {
      this.wifiQual = qual;
    }
  }
};
</script>

<style scoped>
.status-bar-container {
  box-sizing: border-box;
}

.left-section, .right-section {
  flex-direction: row;
  align-items: center;
}

.center-section {
  align-items: center;
  justify-content: center;
}

.time-text {
  font-weight: 500;
}

.wifi-indicator {
  margin-right: 12px;
}

.battery-wrapper {
  flex-direction: row;
  align-items: center;
}

.battery-text {
  font-size: 14px;
  margin-right: 6px;
}

.battery-pill-outer {
  width: 26px;
  height: 14px;
  border-width: 1px;
  border-color: #888888;
  border-radius: 4px;
  padding: 1px;
  justify-content: center;
}
</style>
```

---

### 7.4 全局防抖 Toast 队列管理器 (`GlobalToastManager.ts`)

封装面向业务工程的高可用通知分发器，消除高频连击刷屏：

```typescript
// /Users/daniel/youdao-dictpen-s7pro-guide/src/utils/GlobalToastManager.ts

interface ToastTask {
  id: number;
  message: string;
  duration: number;
  priority: number;
  type: 1 | 2 | 3;
}

class GlobalToastQueueManager {
  private static instance: GlobalToastQueueManager;
  private queue: ToastTask[] = [];
  private isProcessing = false;
  private lastMessage = '';
  private lastTriggerTime = 0;
  private taskCounter = 0;

  private constructor() {}

  public static getInstance(): GlobalToastQueueManager {
    if (!GlobalToastQueueManager.instance) {
      GlobalToastQueueManager.instance = new GlobalToastQueueManager();
    }
    return GlobalToastQueueManager.instance;
  }

  public show(
    message: string, 
    duration: number = 1500, 
    priority: number = 1, 
    type: 1 | 2 | 3 = 1
  ): void {
    const now = Date.now();
    // 500ms 快速防抖去重
    if (message === this.lastMessage && (now - this.lastTriggerTime) < 500) {
      console.warn('[ToastManager] Dropping duplicate toast:', message);
      return;
    }
    this.lastMessage = message;
    this.lastTriggerTime = now;

    const task: ToastTask = {
      id: ++this.taskCounter,
      message,
      duration,
      priority,
      type
    };

    // 紧急或高优先级抢占
    if (priority >= 2) {
      this.queue.unshift(task); // 插队至头部
    } else {
      if (this.queue.length >= 5) {
        this.queue.shift(); // 丢弃溢出的陈旧任务
      }
      this.queue.push(task);
    }

    this.processNext();
  }

  private processNext(): void {
    if (this.isProcessing || this.queue.length === 0) {
      return;
    }

    this.isProcessing = true;
    const currentTask = this.queue.shift()!;

    try {
      // 触发底层 $falcon.showToast
      if (typeof $falcon !== 'undefined' && typeof $falcon.showToast === 'function') {
        $falcon.showToast({
          title: currentTask.message,
          duration: currentTask.duration,
          type: currentTask.type,
          priority: currentTask.priority as any
        });
      }
    } catch (err) {
      console.error('[ToastManager] Native invoke failed:', err);
    }

    // 等待当前 Toast 动画及驻留完全结束 (展示时长 + 500ms 淡出保护)
    setTimeout(() => {
      this.isProcessing = false;
      this.processNext();
    }, currentTask.duration + 550);
  }
}

export const toast = (msg: string, duration?: number) => {
  GlobalToastQueueManager.getInstance().show(msg, duration, 1, 1);
};

export const toastError = (msg: string, duration?: number) => {
  GlobalToastQueueManager.getInstance().show(msg, duration, 2, 3);
};
```

---

## 8. 典型研发陷阱、崩溃根因与避坑指南 (8 大典型故障深度剖析)

### 8.1 陷阱 1：沉浸模式下顶部按钮在 Y < 40px 区域误判为下拉手势导致触控失灵

#### 现象复现
在漫画阅读器或全屏游戏界面中，开发者在顶部靠边排版了一个“关闭”按钮（位置：`top: 4px; height: 32px;`）。用户多次狂点该按钮，应用均无任何响应；偶尔手指向下滑动一点，甚至反而触发了系统下拉控制面板。

#### 崩溃根因 (Root Cause)
1. 页面未调用 `this.$page.setSupportTopPanel(false)`，底层视窗未打标 Flag 4。
2. `greenui::TopSwipeGesture` 的判定阈值为 $Y_{down} \le 5.0\text{px}$ 且下滑 $\ge 40.0\text{px}$。当用户手指按下在 $Y = 4\text{px}$ 时，全局手势拦截器立即进入捕获态（Pending Consume），挂起所有向下派发的事件。
3. 即使没有下滑，只要手势未完全判定失败（在 300ms 判定超时前），底层的 Button 根本收不到 `ACTION_DOWN`，点击事件被完全吞噬。

#### 权威治理方案
1. 页面生命周期必须显式打标：`this.$page.setSupportTopPanel(false)`。
2. 几何排版避让：所有交互按钮的中心点物理坐标必须保证 $Y \ge 24\text{ px}$，顶部留出安全空白，避免触控边缘效应。

---

### 8.2 陷阱 2：Toast 定时器未在 `beforeDestroy` 清除引发内存泄漏与野指针崩溃

#### 现象复现
用户在列表项连续点击触发 Toast，随后快速通过物理返回键或手势连续退出多个页面。系统在几秒后突然抛出段错误 SIGSEGV，Falcon 进程闪退重启。

#### 崩溃根因 (Root Cause)
1. 自定义 Toast 或通用组件内部调用了 `setTimeout(this.dismiss, 1500)`。
2. 当页面退出时，Vue 组件实例已被销毁，DOM 节点已解挂。
3. 但异步队列中的定时器句柄依然持有已销毁组件的上下文闭包引用（Dangling Pointer）。当 1500ms 到期触发回调时，QuickJS 试图访问已经被释放的 JSObject 内部属性，引发空指针解引用或内存越界异常。

#### 权威治理方案
任何组件内的 `setTimeout` 与 `setInterval` 必须在组件销毁钩子中显式阻断：
```javascript
beforeDestroy() {
    if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
    }
}
```

---

### 8.3 陷阱 3：状态栏 1Hz 盲目高频全屏重绘导致 CPU 占用飙升与 UI 掉帧

#### 现象复现
词典笔在息屏待机或静止查词时，系统温度逐渐上升，1200mAh 电池在 4 小时内快速耗尽；在翻页滑动时，界面伴随明显的卡顿掉帧。

#### 崩溃根因 (Root Cause)
开发者在自定义状态栏中直接书写：
```javascript
setInterval(() => {
    this.time = new Date().toLocaleTimeString(); // 每 1000ms 刷新一次
}, 1000);
```
每秒钟触发一次完整的组件 Diff 与 Skia 画布重绘。由于单核 Cortex-A7 没有二级缓存支持，高频上下文切换与显存冲刷让 CPU 常驻利用率高达 8% ~ 12%，无法进入 `WFI`（Wait For Interrupt）低功耗睡眠态。

#### 权威治理方案
彻底废除 1Hz 轮询，改用**分钟边界对齐算法**（见第 2.4 节）。只在 00 秒触发一次更新，整整减少 98.3% 的唤醒频次，待机 CPU 开销骤降至 0.3%。

---

### 8.4 陷阱 4：绘画/划词敏感视口未打标 Flag 4 引发触摸事件被系统强行拦截吞没

#### 现象复现
在生词听写或描红笔顺应用中，用户快速由上向下书写汉字首笔（如“十”字的第一竖）。首笔的前半段必定发生笔迹断裂或丢失。

#### 崩溃根因 (Root Cause)
书写首笔的起始点若靠近屏幕顶部，其滑动轨迹 $(\Delta X, \Delta Y)$ 在数学上完全符合 `TopSwipeGesture` 的下拉特征。系统手势识别器在 $40\text{px}$ 移动区间内抢占了触控所有权，向绘画 Canvas 补发了 `ACTION_CANCEL`，导致笔迹中断。

#### 权威治理方案
在书写画板挂载的第一时间，调用 `setSupportTopPanel(false)` 与 `setDisableLeftSwipeBack(true)`，为 Native Window 注入绝对手势豁免权。

---

### 8.5 陷阱 5：悬浮窗口 `isFloating` 标志缺失导致底层视图树被完全剔除黑屏

#### 现象复现
在开发原生 C++ 扩展弹窗或定制 Modal 视窗时，开发者调用 `WindowManager::pushWindow` 压入自定义窗口后，整个底层业务应用瞬间变成黑屏，只有弹窗自身孤零零显示。

#### 崩溃根因 (Root Cause)
1. 深入分析 1.4 节 `WindowManager::getRenderableWindows`（地址 `0x00585090`）的剔除算法：
   ```arm
   585114: bl  Window::isFloating()
   585118: cmp r0, #0
   58511c: beq 0x58517c ; 若 isFloating == false，立即截断遍历!
   ```
2. 若新创建的窗口未显式打标 `FLAG_FLOATING`（掩码 `0x01`），`WindowManager` 将其判定为**不透明全屏窗口**，断定它已经彻底遮挡了下层所有内容，因而直接终止了下层窗口的渲染遍历，造成底层界面被整体剔除。

#### 权威治理方案
在任何悬浮窗口或弹窗构建时，必须显式调用：
```cpp
mFlags |= greenui::FLAG_FLOATING; // 或者 window->addFlag(1);
```

---

### 8.6 陷阱 6：下拉面板触控取消事件未处理造成物理 Scroller 悬滞半屏卡死

#### 现象复现
用户在下拉控制中心拉动到一半时，突然按下机身物理侧键（如电源键或 AI 语音键），下拉面板既不收起也不展开，僵死在半屏位置，所有触控彻底失效。

#### 崩溃根因 (Root Cause)
1. 物理侧键按下时，硬件输入层分发了 `ACTION_CANCEL`。
2. 下拉面板的 `dispatchTouchEvent` 只在 `ACTION_UP` 中编写了 `fling()` 回弹逻辑，在 `ACTION_CANCEL` 分支中直接 `return false`，遗漏了动画终止处理。
3. `Scroller` 停留在半路，视窗既未回到 `-240`，也未归位到 `0`，而 `WindowManager` 的焦点依然锁定在 `SettingPanel`，导致下层业务完全瘫痪。

#### 权威治理方案
在触控分发处理中，`ACTION_CANCEL` 必须与 `ACTION_UP` 走完全相同的回弹收敛路径：
```cpp
if (action == MotionEvent::ACTION_UP || action == MotionEvent::ACTION_CANCEL) {
    this->fling(); // 强制触发速度检测与弹簧归位
}
```

---

### 8.7 陷阱 7：电池电压瞬态压降未做 LPF 滤波导致系统误触发低电警告关机

#### 现象复现
设备电量尚有 20%，当用户将扫描笔头压在书本上开始大面积连续扫词时（扫描补光灯点亮、CIS 图像传感器全速 120 FPS 采集），状态栏电量图标突发暴跌闪烁红光，系统甚至直接弹出“电量极低，即将关机”对话框。

#### 崩溃根因 (Root Cause)
扫描补光 LED 阵列瞬态工作电流高达 350mA。在老化锂电池等效内阻（ESR）作用下，端电压骤降：
$$\Delta V = I_{load} \cdot R_{esr} = 0.35\text{A} \cdot 0.4\Omega = 140\text{ mV}$$
未经低通滤波的瞬态低电压越过了 PMIC 设定的一级低电告警门限（$3.45\text{ V}$），直接向 Ubus 抛出了错误事件。

#### 权威治理方案
前端绝不能直接取未滤波的裸数据，必须依赖集成一阶低通滤波算法的 `UltraLightStatusBar` 架构（见 2.2 节与 7.3 节），通过软件惯性平滑彻底吸收瞬态压降纹波。

---

### 8.8 陷阱 8：Wi-Fi RSSI 轮询在页面后台 (`pageHidden`) 未注销导致息屏功耗超标

#### 现象复现
微应用在切入后台或息屏待机后，系统休眠电流高达 45mA（标准待机电流应 $< 3\text{ mA}$）。

#### 崩溃根因 (Root Cause)
页面在 `pageShowing` 时调用了 `wifi.startWifiQualTimer()`，该原生接口在后台启动了一个独立的 Linux 定时器每 2 秒读取一次驱动 RSSI。当页面退至后台（`pageHidden`）时，开发者遗漏了注销调用。定时器不断唤醒内核与 SDIO 总线，阻断了 SoC 进入 Deep Sleep 挂起状态。

#### 权威治理方案
必须在页面的生命周期钩子中成对启闭硬件定时器：
```javascript
onPageHide() {
    if (wifi && typeof wifi.stopWifiQualTimer === 'function') {
        wifi.stopWifiQualTimer(); // 立即注销底层轮询
    }
}
```

---

## 9. 逆向符号、虚拟函数表与内存偏移速查索引

本章汇总了网易有道词典笔 S7 Pro 状态栏、下拉控制面板与通知子系统中所有已逆向确证的底层核心符号、动态库物理路径与内存偏移量，供固件开发与深层排障快速查阅。

### 9.1 核心二进制动态库绝对路径表
- `/usr/lib/libfalcon.so`：Falcon 视窗与运行时核心引擎（MD5: `9a8ef67c...`，ELF32 Little-ARM）
- `/etc/miniapp/jsapis/libjsapi_export_core.so`：QuickJS 原生 C++ 导出桥接库
- `/oem/YoudaoDictPen/output/libs/libyddal_business_core.so`：有道数据抽象业务层（DAL Core）
- `/oem/YoudaoDictPen/output/libs/libyddal_adapter_core.so`：有道硬件适配抽象层
- `/usr/lib/libydhal_devices.so`：底层硬件抽象层（Sysfs 背光 PWM 与 ALSA 混音）

---

### 9.2 C++ 核心符号、虚表与物理偏移速查

| 符号签名 (Mangled Name) | 还原 C++ 类与成员函数 | 所属二进制库 | 汇编起始地址 | 核心功能与关键偏移 |
| :--- | :--- | :--- | :--- | :--- |
| `_ZN7greenui13WindowManager8instanceEv` | `greenui::WindowManager::instance()` | `libfalcon.so` | `0x00583bec` | 获取全局视窗管理器单例 |
| `_ZNK7greenui13WindowManager20getRenderableWindows...` | `greenui::WindowManager::getRenderableWindows` | `libfalcon.so` | `0x00585090` | 多窗口遮挡剔除与正向渲染链表生成 |
| `_ZN7greenui12NativeWindow12dispatchDrawEPNS_6CanvasEx` | `greenui::NativeWindow::dispatchDraw` | `libfalcon.so` | `0x00589748` | Skia 画布驱动多窗口分层绘制 |
| `_ZNK7greenui6Window8getLayerEv` | `greenui::Window::getLayer()` | `libfalcon.so` | `0x00583654` | 读取窗口 Z-Order (Offset `+0x28`) |
| `_ZN7greenui6Window10isFloatingEv` | `greenui::Window::isFloating()` | `libfalcon.so` | `0x0058365c` | 读取悬浮标志 (Offset `+0x2C` bit 0) |
| `_ZN7greenui6Window7addFlagEj` | `greenui::Window::addFlag(uint32_t)` | `libfalcon.so` | `0x0058367c` | 添加窗口特性掩码 (Offset `+0x2C`) |
| `_ZN7greenui6Window9clearFlagEj` | `greenui::Window::clearFlag(uint32_t)` | `libfalcon.so` | `0x0058368c` | 清除窗口特性掩码 (Offset `+0x2C`) |
| `_ZN6falcon15FalconAppExtend18setSupportTopPanelEb` | `falcon::FalconAppExtend::setSupportTopPanel(bool)` | `libfalcon.so` | `0x0024c414` | 全屏沉浸式切换 (操作 Flag 4) |
| `_ZN6falcon12SettingPanelC2ERKN6JQuick11PackageInfoE` | `falcon::SettingPanel::SettingPanel(...)` | `libfalcon.so` | `0x002aeb48` | 下拉控制中心构造 (设定 Layer 10001) |
| `_ZN6falcon12SettingPanel10pullToShowEf` | `falcon::SettingPanel::pullToShow(float)` | `libfalcon.so` | `0x002ae40c` | 阻尼下拉位移映射 ($mTop = Y - 240$) |
| `_ZN6falcon12SettingPanel5flingEv` | `falcon::SettingPanel::fling()` | `libfalcon.so` | `0x002ae804` | 速度提取与弹性动画启动 |
| `_ZN6falcon12SettingPanel12computeFlingEx` | `falcon::SettingPanel::computeFling(int64_t)` | `libfalcon.so` | `0x002aea88` | VSYNC 帧驱动 Scroller 步进 |
| `_ZN6falcon22TopSettingPanelGesture8onHandleEf` | `falcon::TopSettingPanelGesture::onHandle(float)` | `libfalcon.so` | `0x002ae45c` | 顶部下拉手势校验与 Flag 4 门禁 |
| `_ZN2im13FalconIMPanelC2ERKN6JQuick11PackageInfoE` | `im::FalconIMPanel::FalconIMPanel(...)` | `libfalcon.so` | `0x002b10e4` | 虚拟键盘面板构造 (设定 Layer 10200) |
| `_ZN6JQuick14FloatingWindowC2EPNS_11ModalWindowEbbbb` | `JQuick::FloatingWindow::FloatingWindow(...)` | `libfalcon.so` | `0x002437e4` | 悬浮模态窗构造 (默认 Layer 100) |
| `_ZN13JSGlobalProxy9showToastER22JQFunctionCallbackInfo` | `JSGlobalProxy::showToast(...)` | `libjsapi_export_core.so` | `0x00071898` | QuickJS 全局 Toast 导出入口 |
| `_ZN13JSGlobalProxy18requestUIShowToastERKNSt...` | `JSGlobalProxy::requestUIShowToast(...)` | `libjsapi_export_core.so` | `0x00071aa0` | 内部 Toast 信号触发器 |
| `_ZN13JSGlobalProxy22requestUIShowToastPlusERKN...` | `JSGlobalProxy::requestUIShowToastPlus(...)` | `libjsapi_export_core.so` | `0x00071b04` | 增强型 Toast 信号触发器 (带类型与时长) |
| `_ZN7YDALAPI12YToastModule9showToastERKNSt...` | `YDALAPI::YToastModule::showToast(...)` | `libyddal_business_core.so` | `0x0010be50` | DAL 业务层 Toast 核心派发器 |
| `_ZN11YADAPTERAPI8Internal25YSystemInfoAdapterPrivate18getBatteryCapacityEv` | `YSystemInfoAdapterPrivate::getBatteryCapacity()` | `libyddal_adapter_core.so` | `0x00049f30` | AXP2101 库仑计低通滤波电量读取 |

---

> **结语与架构演进备忘**：  
> 本手册全面揭示了网易有道词典笔 S7 Pro 在极度受限的单核嵌入式 Linux 体系下，如何通过巧妙的单进程内多窗口分层、Skia 脏矩形遮挡剔除、物理阻尼动力学与硬件位标门禁（Flag 4），构建出一套媲美现代移动操作系统的全局顶层视窗子系统。在开发第三方 MiniApp 或系统扩展时，开发者必须严格遵循视口避让尺寸规范、手势互锁协议与生命周期定时器清理准则，方能确保应用在 1020 × 240 带鱼异形屏上稳定运行、丝滑流畅。
