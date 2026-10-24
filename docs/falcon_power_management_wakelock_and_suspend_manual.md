# Linux 电源管理、屏幕超时休眠、WakeLock 与唤醒子系统深度逆向分析
## (Falcon Power Management, Screen Idle Timeout, Kernel WakeLocks, and Suspend/Resume HAL Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `libfalcon.so`, `libjsapi_export_core.so`, `axs_ts.ko`, `dictpen-home` (Launcher), Linux PM Core (`/sys/power/`)

---

## 目录索引

1. [屏幕常亮与息屏控制全链路逆向剖析](#1-屏幕常亮与息屏控制全链路逆向剖析)
   - 1.1 [双轨控制架构：直接保活 vs 全局信号广播](#11-双轨控制架构直接保活-vs-全局信号广播)
   - 1.2 [`libjsapi_export_core.so` 核心导出符号反汇编](#12-libjsapi_export_coreso-核心导出符号反汇编)
   - 1.3 [`dictpen-home` 系统常驻服务与心跳守护](#13-dictpen-home-系统常驻服务与心跳守护)
   - 1.4 [`libfalcon.so` 窗口管理器屏幕状态门禁 (`mScreenOn`)](#14-libfalconso-窗口管理器屏幕状态门禁-mscreenon)
2. [Linux 内核 Sysfs 电源与背光底层接口](#2-linux-内核-sysfs-电源与背光底层接口)
   - 2.1 [`/sys/power/wake_lock` 与 `/sys/power/wake_unlock`](#21-syspowerwake_lock-与-syspowerwake_unlock)
   - 2.2 [`/sys/power/state` (系统全局睡眠状态)](#22-syspowerstate-系统全局睡眠状态)
   - 2.3 [`/sys/class/backlight/backlight/` (屏幕背光子系统)](#23-sysclassbacklightbacklight-屏幕背光子系统)
3. [屏幕超时休眠机制与无操作空闲计时器](#3-屏幕超时休眠机制与无操作空闲计时器)
   - 3.1 [系统设置中的超时挡位映射](#31-系统设置中的超时挡位映射)
   - 3.2 [空闲检测机制与定时器重置源](#32-空闲检测机制与定时器重置源)
   - 3.3 [息屏倒计时超时处理全时序](#33-息屏倒计时超时处理全时序)
4. [硬件中断唤醒源与驱动 Suspend/Resume 逆向分析](#4-硬件中断唤醒源与驱动-suspendresume-逆向分析)
   - 4.1 [核心唤醒中断源分析](#41-核心唤醒中断源分析)
   - 4.2 [`axs_ts.ko` 驱动的挂起与恢复流程深度逆向](#42-axs_tsko-驱动的挂起与恢复流程深度逆向)
5. [生产级 MiniApp 屏幕常亮与电源生命周期安全管理范式](#5-生产级-miniapp-屏幕常亮与电源生命周期安全管理范式)
   - 5.1 [生产级 `ScreenWakeLockManager.js`](#51-生产级-screenwakelockmanagerjs)
   - 5.2 [在长篇阅读 / 音频播放页面中的标准生命周期挂载](#52-在长篇阅读--音频播放页面中的标准生命周期挂载)
   - 5.3 [伴奏/有声书后台音频播放（仅保活 CPU，放行屏幕休眠）](#53-伴奏有声书后台音频播放仅保活-cpu放行屏幕休眠)
6. [核心架构与逆向结论对照全景](#6-核心架构与逆向结论对照全景)

---

## 1. 屏幕常亮与息屏控制全链路逆向剖析

在有道词典笔 S7 Pro 的 Falcon 运行时架构中，屏幕常亮（Keep Screen On）并非单一的布尔变量赋值，而是横跨 **MiniApp JS 运行时**、**C++ JSAPI 代理导出层 (`libjsapi_export_core.so`)**、**主屏幕应用守护服务 (`dictpen-home`)**、**硬件抽象层 (`libydhal_devices.so` / `hal-screen`)** 与 **Linux Framebuffer/Backlight 内核驱动** 的多层分布式协同机制。

### 1.1 双轨控制架构：直接保活 vs 全局信号广播

```
[MiniApp JS Layer]
   │
   ├── 通道 A: $falcon.keepScreenOn() / new Brightness().keepScreenOn()
   │      │
   │      ▼ [libjsapi_export_core.so]
   │      JSGlobalProxy::keepScreenOn (0x6a348) / JSBrightnessProxy::keepScreenOn (0x9db6c)
   │      │
   │      ▼ [HAL Interface]
   │      YDALAPI::YBrightnessModule::Instance()->keepScreenOn() (无参, void)
   │      │
   │      ▼ [System Service / CLI]
   │      hal-screen keep (重置硬件空闲计时器，延长 30 秒)
   │
   └── 通道 B: startAlwaysScreenOn() / startPermanentScreenOn()
          │
          ▼ [libjsapi_export_core.so]
          JSGlobalProxy::startAlwaysScreenOn (0x70160) / JSBrightnessProxy::startAlwaysScreenOn (0x9e56c)
          │
          ▼ [JQSignal 广播]
          JQSignal<bool>::emit(true) (触发 startAlwaysScreenOnTriggered 信号)
          │
          ▼ [dictpen-home (Launcher 常驻微服务)]
          indexPage.startAlwaysScreenOnTriggered 监听器激活
          │
          ▼ [心跳看门狗循环]
          keepScreenOnTimer = setInterval(() => { keepScreenOn(); }, 15000)
```

---

### 1.2 `libjsapi_export_core.so` 核心导出符号反汇编

#### (1) `JSBrightnessProxy::keepScreenOn` (虚拟地址 `0x9db6c`, 196 字节)
- **底层签名**: `void keepScreenOn(void)`。
- **关键发现**：底层 `YBrightnessModule::keepScreenOn()` **不接受任何布尔值参数**。它本质上是一次性向硬件或系统看门狗发送“延长保活 30 秒”的刷新指令（类似 `hal-screen keep`）。

#### (2) `JSBrightnessProxy::startAlwaysScreenOn` (虚拟地址 `0x9e56c`, 84 字节)
- 发射 `JQSignal<bool>::emit(true)`（信号 `startAlwaysScreenOnTriggered`），通知常驻桌面服务开启 15s 心跳。

#### (3) `JSGlobalProxy` 内部全局信号偏移对照表

| 方法名称 | 虚拟地址 | 结构体偏移 | 触发的 JQSignal 信号 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `startAlwaysScreenOn` | `0x70160` | `+0x918` | `startAlwaysScreenOnTriggered` | 临时常亮请求（应用级） |
| `stopAlwaysScreenOn` | `0x701ac` | `+0x954` | `stopAlwaysScreenOnTriggered` | 释放临时常亮 |
| `startPermanentScreenOn` | `0x701f8` | `+0x990` | `startPermanentScreenOnTriggered` | 永久常亮请求（系统设置级） |
| `stopPermanentScreenOn` | `0x70240` | `+0x9cc` | `stopPermanentScreenOnTriggered` | 释放永久常亮 |
| `setCloseScreenTime` | `0x6a40c` | —— | 调用 `YBrightnessModule::setCloseScreenTime(int)` | 设置息屏超时时间 |

---

### 1.3 `dictpen-home` 系统常驻服务与心跳守护

```javascript
// dictpen-home 内部事件绑定与心跳保活逻辑逆向还原
this.brightnessManager.startAlwaysScreenOnTriggered.connect(() => {
    console.log("Home index=========startAlwaysScreenOnTriggered");
    if (this.keepScreenOnTimer) {
        clearInterval(this.keepScreenOnTimer);
    }
    // 立即执行一次底层 30s 保活
    this.brightnessManager.keepScreenOn();
    // 启动 15 秒间隔的心跳定时器，确保护航周期永不过期
    this.keepScreenOnTimer = setInterval(() => {
        this.brightnessManager.keepScreenOn();
    }, 15000);
});

this.brightnessManager.stopAlwaysScreenOnTriggered.connect(() => {
    console.log("Home index=========stopAlwaysScreenOnTriggered");
    if (this.keepScreenOnTimer) {
        clearInterval(this.keepScreenOnTimer);
        this.keepScreenOnTimer = null;
    }
});
```

---

### 1.4 `libfalcon.so` 窗口管理器屏幕状态门禁 (`mScreenOn`)

在 `libfalcon.so` 中，屏幕开关状态直接决定了 GUI 事件分发与渲染循环的生命周期：
- 熄屏时调用 `greenui::WindowManager::setVisible(false)`（`0x583fd4`），将 `mScreenOn` 置 0 并停止看门狗监控。
- 在 `dispatchTouchEvent`（`0x5840dc`）中，若 `mScreenOn == 0`，**所有触控事件在入口处被彻底丢弃**！

---

## 2. Linux 内核 Sysfs 电源与背光底层接口

### 2.1 `/sys/power/wake_lock` 与 `/sys/power/wake_unlock`
内核启用了 Linux 原生 Android-style 唤醒锁机制（`CONFIG_PM_WAKELOCKS`）：
- 写入锁标识：`echo "my_lock" > /sys/power/wake_lock`
- 释放锁：`echo "my_lock" > /sys/power/wake_unlock`
- `mediaPlayerService` 在后台播放时写入 `PowerManager_AudioPlayer` 锁，确保即使用户关闭屏幕，CPU 仍持续供电解码音频流。

### 2.2 `/sys/power/state`
- `freeze`（Suspend-to-idle）与 `mem`（Suspend-to-RAM）。
- 当屏幕关闭且无活跃 WakeLock 超过 60 秒后，电源守护进程向 `/sys/power/state` 写入 `mem`，整机进入深度睡眠。

### 2.3 `/sys/class/backlight/backlight/`
- `brightness`: 0 ~ 255（最低可用 10，最大 255），对应 **20,000 Hz (20 kHz)** 高频 PWM，彻底消除频闪。
- `bl_power`: `0`（开启）或 `4`（`FB_BLANK_POWERDOWN` 彻底断电）。写入 4 时触发内核 Framebuffer 广播 `FB_EVENT_BLANK`，联动挂起触控驱动。

---

## 3. 屏幕超时休眠机制与无操作空闲计时器

### 3.1 系统设置中的超时挡位映射

| 挡位名称 | UI 文本 Key | 传入 `setCloseScreenTime` 的参数 | 物理时长 |
| :---: | :--- | :---: | :---: |
| **1 分钟** | `settings_closescreen_time_one` | `60` | 60 秒 |
| **3 分钟** | `settings_closescreen_time_three` | `180` | 180 秒 |
| **5 分钟** | `settings_closescreen_time_five` | `300` | 300 秒 |
| **10 分钟** | `settings_closescreen_time_ten` | `600` | 600 秒 |
| **30 分钟** | `settings_closescreen_time_thirty` | `1800` | 1800 秒 |
| **永不休眠** | `settings_closescreen_time_never` | 触发 `startPermanentScreenOn()` | 1440 分钟 (24 小时) |

### 3.2 空闲检测机制与定时器重置源
1. 触控屏幕滑动/点击（`evdev: /dev/input/event3`）。
2. 笔尖触纸微动开关（`KEY_CAMERA`, Keycode 212）。
3. 物理按键（`KEY_POWER`, `KEY_HOMEPAGE`）。
4. 软件 KeepAlive（`hal-screen keep`）。

---

## 4. 硬件中断唤醒源与驱动 Suspend/Resume 逆向分析

### 4.1 核心唤醒中断源分析

在词典笔息屏挂起后，由于系统关闭了触控 IC 供电并禁用了触控中断，**点击或滑动屏幕绝对无法唤醒设备**。设备的唤醒完全依赖于内核设备树（Device Tree）中配置为 `wakeup-source` 的物理引脚：
- **电源按键 (`KEY_POWER`, 116)**：AXP2101 PMIC IRQ 下降沿唤醒。
- **笔尖微动开关 (`KEY_CAMERA`, 212)**：笔尖触底按压瞬间闭合 GPIO 唤醒，“提笔即扫”。
- **实体 Home 键 (`KEY_HOMEPAGE`, 172)**：路由回 Launcher 首页。

### 4.2 `axs_ts.ko` 驱动的挂起与恢复流程
- **挂起 (`axs_ts_suspend`, 0xe8d)**：捕获 `FB_BLANK_POWERDOWN (4)`，调用 `disable_irq_nosync()` 彻底禁用触控中断，并向 AXS15205 写入 `0x54` 进入低功耗 Sleep 模式。
- **恢复 (`axs_ts_resume`, 0xf65)**：捕获 `FB_BLANK_UNBLANK (0)`，硬件复位并重新使能 `enable_irq()`。

---

## 5. 生产级 MiniApp 屏幕常亮与电源生命周期安全管理范式

### 5.1 生产级 `ScreenWakeLockManager.js`

```javascript
import brightnessModule from 'brightness';

class ScreenWakeLockManager {
    constructor() {
        this._brightness = null;
        this._heartbeatTimer = null;
        this._isLocked = false;
        this._refCount = 0;
        
        try {
            if (brightnessModule && typeof brightnessModule.Brightness === 'function') {
                this._brightness = new brightnessModule.Brightness();
            }
        } catch (e) {
            console.warn('[WakeLock] Brightness native module init failed:', e);
        }
    }

    acquire() {
        this._refCount++;
        if (this._isLocked) return;

        console.log('[WakeLock] Acquiring Screen WakeLock...');
        this._isLocked = true;

        if (this._brightness && typeof this._brightness.startAlwaysScreenOn === 'function') {
            try { this._brightness.startAlwaysScreenOn(); } catch (_) {}
        } else if (typeof $falcon !== 'undefined' && typeof $falcon.startAlwaysScreenOn === 'function') {
            try { $falcon.startAlwaysScreenOn(); } catch (_) {}
        }

        this._sendKeepScreenOn();

        this._stopHeartbeat();
        this._heartbeatTimer = setInterval(() => {
            if (this._isLocked) this._sendKeepScreenOn();
        }, 15000);
    }

    release(force = false) {
        if (!this._isLocked) return;

        if (!force && --this._refCount > 0) return;

        console.log('[WakeLock] Releasing Screen WakeLock completely...');
        this._refCount = 0;
        this._isLocked = false;

        this._stopHeartbeat();

        if (this._brightness && typeof this._brightness.stopAlwaysScreenOn === 'function') {
            try { this._brightness.stopAlwaysScreenOn(); } catch (_) {}
        } else if (typeof $falcon !== 'undefined' && typeof $falcon.stopAlwaysScreenOn === 'function') {
            try { $falcon.stopAlwaysScreenOn(); } catch (_) {}
        }
    }

    _sendKeepScreenOn() {
        try {
            if (this._brightness && typeof this._brightness.keepScreenOn === 'function') {
                this._brightness.keepScreenOn();
            } else if (typeof $falcon !== 'undefined' && typeof $falcon.keepScreenOn === 'function') {
                $falcon.keepScreenOn(true);
            }
        } catch (_) {}
    }

    _stopHeartbeat() {
        if (this._heartbeatTimer) {
            clearInterval(this._heartbeatTimer);
            this._heartbeatTimer = null;
        }
    }

    isScreenOnLocked() {
        return this._isLocked;
    }
}

export const wakeLockManager = new ScreenWakeLockManager();
export default wakeLockManager;
```

### 5.2 页面生命周期标准挂载
```javascript
import wakeLockManager from './utils/ScreenWakeLockManager.js';

export default class ReadingPage extends $falcon.Page {
    onShow() {
        wakeLockManager.acquire();
    }
    onHide() {
        wakeLockManager.release();
    }
    onDestroy() {
        wakeLockManager.release(true);
    }
}
```
