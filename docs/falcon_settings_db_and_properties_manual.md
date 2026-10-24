# 有道词典笔 S7 Pro 系统设置、配置管理与属性持久化子系统深度逆向分析
## (Falcon Settings, Configuration Management, and Properties Persistence Architecture Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB RAM, Linux 5.10.4)  
> **核心组件**: 系统设置 (`8080272425914438`), `libjsapi_settings_1365027777.so`, `libjsapi_export_core.so`, `libfalcon.so` (`JQuick::JQuickFalconEnv`)

---

## 目录索引

1. [系统配置三层解耦架构模型](#1-系统配置三层解耦架构模型)
   - 1.1 [三层存储拓扑架构](#11-三层存储拓扑架构)
   - 1.2 [硬件直接抽象层 HAL (`libjsapi_export_core.so`)](#12-硬件直接抽象层-hal-libjsapi_export_coreso)
   - 1.3 [全局自定义环境 (`$falcon.env.custom`) 与红黑树缓存](#13-全局自定义环境-falconenvcustom-与红黑树缓存)
   - 1.4 [应用沙盒存储与 SQLite 关系数据库](#14-应用沙盒存储与-sqlite-关系数据库)
2. [底层 C++ 符号与汇编级逆向剖析](#2-底层-c-符号与汇编级逆向剖析)
   - 2.1 [原生设置 C-Module (`libjsapi_settings_1365027777.so`)](#21-原生设置-c-module-libjsapi_settings_1365027777so)
   - 2.2 [`JSSettingsProxy::setEnvValue` 汇编反编译关键判定](#22-jssettingsproxysetenvvalue-汇编反编译关键判定)
   - 2.3 [100ms 防抖延迟落盘流水线 (`sendPersist` / `onPersist`)](#23-100ms-防抖延迟落盘流水线-sendpersist--onpersist)
   - 2.4 [跨应用跨进程直通内存注入 (`ServiceStack::notifyCustomEnvChange`)](#24-跨应用跨进程直通内存注入-servicestacknotifycustomenvchange)
3. [磁盘文件与持久化数据规范](#3-磁盘文件与持久化数据规范)
   - 3.1 [全局系统环境定义 (`/userdata/miniapp/resources/env.json`)](#31-全局系统环境定义-userdataminiappresourcesenvjson)
   - 3.2 [SharedPreferences 键值对规范 (`preferences.json`)](#32-sharedpreferences-键值对规范-preferencesjson)
   - 3.3 [词库离线授权与目录关系数据库 (`dicts.db`)](#33-词库离线授权与目录关系数据库-dictsdb)
4. [设置微服务 IPC 架构 (`falcon://8080272425914438/settings`)](#4-设置微服务-ipc-架构-falcon8080272425914438settings)
   - 4.1 [服务声明周期与 5 秒空闲自愈看门狗](#41-服务声明周期与-5-秒空闲自愈看门狗)
   - 4.2 [跨进程 RPC 通信指令字典](#42-跨进程-rpc-通信指令字典)
5. [生产级开发封装与统一接口实现](#5-生产级开发封装与统一接口实现)
   - 5.1 [高可靠系统设置客户端 (`SystemSettingsManager.js`)](#51-高可靠系统设置客户端-systemsettingsmanagerjs)

---

## 1. 系统配置三层解耦架构模型

### 1.1 三层存储拓扑架构

有道词典笔 S7 Pro 采用 NetEase Falcon GUI 运行时，系统配置、用户偏好与硬件属性被解耦为三层拓扑：

```
+----------------------------------------------------------------------------------------------------+
|                                    Falcon MiniApp JavaScript Layer                                 |
|  $falcon.env.custom.$set(key, val)  |  import ServiceProxy from '$service_proxy'  |  import 'volume' |
+----------------------------------------------------------------------------------------------------+
                   |                                           |                                |
                   v                                           v                                v
+---------------------------------------+   +------------------------------------+   +-------------------+
|     $falcon.env.custom ($set)         |   | Falcon IPC Daemon (ServiceStack)   |   | HAL Proxy Objects |
|  - falcon_custom_set (0x54ae30)       |   | - falcon://8080272425914438/       |   | (JSBrightnessProxy|
|  - JSValue2JSON (0x1d71cc)            |   |   settings                         |   |  JSVolumenessProxy|
|  - JQuickFalconEnv::setCustomEnvJson  |   | - JSDLink / UNIX Domain Socket     |   |  JSWifiProxy)     |
+---------------------------------------+   +------------------------------------+   +-------------------+
        |                       |                              |                                |
        v (Atomic Update)       v (Cross-App Broadcast)        v (RPC Command)                  v (Syscall/ioctl)
+------------------+    +---------------------------+   +-----------------------+    +-------------------+
| std::_Rb_tree    |    | ServiceStack::            |   | Settings Service      |    | Linux Kernel HAL  |
| In-Memory Cache  |    | notifyCustomEnvChange     |   | (settings.js.bin)     |    | /sys/class/back-  |
+------------------+    | (0x547c10)                |   +-----------------------+    | light, ALSA mixer,|
        |               +---------------------------+               |                | wpa_supplicant    |
        v (100ms Debounce)      |                                   v                +-------------------+
+------------------+            v (Push to Context)     +-----------------------+
| JQuickFalconEnv  |    +---------------------------+   | JSSettingsProxy       |
| ::onPersist      |    | ServiceAppImpl::          |   | (libjsapi_settings.so)|
| (0x54fb9c)       |    | notifyCustomEnvChange     |   | - YDALBASEAPI::       |
+------------------+    | (0x5385dc)                |   |   YEnvironment        |
        |               +---------------------------+   +-----------------------+
        v                                                           |
+---------------------------------------------------+               v
| Persistent Disk: /userdata/miniapp/resources/     |    +----------------------+
| env.json (Fallback: /etc/miniapp/resources/env.json)|   | System Environment   |
+---------------------------------------------------+    +----------------------+
```

---

## 2. 底层 C++ 符号与汇编级逆向剖析

### 2.1 原生设置 C-Module (`libjsapi_settings_1365027777.so`)
- **模块路径**: `/userdata/miniapp/data/mini_app/pkg/8080272425914438/b/libs/libjsapi_settings_1365027777.so`
- **初始化入口**: `custom_init_jsapis`（偏移 `0x000286fc`）通过 `registerCModuleLoader` 向 QuickJS 注入 `'settings'` 模块。
- **核心导出类**: `JSSettingsProxy`（继承自 `JQPublishObject`）。

#### 关键同步方法：
- `setWarnLevelLog(level: number): void`
- `syncGetDateTime(): string`
- `getDictionaryPublisher(): string`
- `getOnlineDictList(): string`
- `downloadDictionary(dictId: string): void`
- `removeDictionary(dictId: string): void`
- `getLocalDictionarys(): string`
- `setEnvValue(key: string, value: string): void`
- `getEnvValue(key: string): string`
- `getAllEnv(): string`
- `getTestOptionsOn(): boolean`
- `setTestOptionsOn(enabled: boolean): void`
- `startSpeedTest(): void`
- `stopSpeedTest(): void`
- `mockTheme(themeName: string): void`
- `startAlwaysScreenOn(): void`
- `stopAlwaysScreenOn(): void`

#### 关键异步 (Promise) 方法：
- `getAppDataStorageInfo(): Promise<{ usedBytes: number, totalBytes: number }>`
- `getLocalResourceInfo(): Promise<{ otaBytes: number, mediaBytes: number }>`
- `clearSystemCache(): Promise<boolean>`

---

### 2.2 `JSSettingsProxy::setEnvValue` 汇编反编译关键判定

在 `0x0002d4ac` 的反编译确认：若传入的值字符串长度为 0，底层自动判定为删除该键；若大于 0 则执行保存：

```arm
0x0002d594: ldr     r7, [sp, #0x10]     ; r7 = 指向 value std::string
0x0002d598: ldr     r3, [r7, #4]        ; r3 = value 字符串长度
0x0002d59c: cmp     r3, #0              ; 长度是否为 0?
0x0002d5a0: bne     0x0002d690          ; 长度 > 0 分支跳转至 setValue
0x0002d5a4: mov     r0, r4              ; r4 = key std::string 指针
0x0002d5a8: bl      0x00027110          ; PLT: YDALBASEAPI::YEnvironment::remove(std::string const&)
0x0002d5ac: b       0x0002d600          ; 返回
...
0x0002d690: mov     r1, r7              ; r1 = value std::string
0x0002d694: mov     r0, r4              ; r0 = key std::string
0x0002d698: bl      0x00027020          ; PLT: YDALBASEAPI::YEnvironment::setValue(std::string const&, std::string const&)
```

---

### 2.3 100ms 防抖延迟落盘流水线 (`sendPersist` / `onPersist`)

当调用 `$falcon.env.custom.$set(key, value)` 时，系统不会立刻触发昂贵的 eMMC 写入，而是启动 100ms 定时器防抖：

1. **汇编证据（`sendPersist` 0x00550028）**:
   ```arm
   0x00550048: bl      0x00544f80          ; JQuick::getPersistHandler()
   0x00550088: bl      0x0055048c          ; JQuick::bind(&JQuickFalconEnv::onPersist, this)
   0x005500e8: mov     r2, #0x64           ; r2 = 0x64 (10进制 100，即 100ms 延迟)
   0x005500ec: mvn     r3, #0              ; r3 = -1 (单次调度)
   0x005500f0: bl      0x00545220          ; JQuick::Handler::postDelayed(Task, 100, -1)
   ```
2. **落盘序列化（`onPersist` 0x0054fb9c）**:
   - `JQuick::Json::dump(std::string&)`
   - `JQuick::getDataCacheDir()` 获取路径前缀 `/userdata/miniapp/`
   - `std::string::append("resources/env.json")`
   - `FileUtil::WriteStringToFile(filePath, jsonStr)`

---

### 2.4 跨应用跨进程直通内存注入 (`ServiceStack::notifyCustomEnvChange`)

Falcon 彻底抛弃了重量级的 D-Bus 跨进程广播，而是由 Falcon 运行时核心通过 `ServiceStack::notifyCustomEnvChange` (`0x00547c10`) 直接遍历所有注册的微应用进程：
- 对目标微应用直接执行 `falcon::ServiceAppImpl::notifyCustomEnvChange` (`0x005385dc`)。
- 在目标应用所在的 QuickJS `JSContext` 堆中直接执行 `JS_SetPropertyStr` 覆写全局 `$falcon.env.custom[key]`。
- 随后触发 `$falcon.emit('customEnvChange', { key, value })`。
- **全链路时延仅 1~2 毫秒**，极其省电且响应极快。

---

## 3. 磁盘文件与持久化数据规范

### 3.1 全局系统环境定义 (`/userdata/miniapp/resources/env.json`)

```json
{
  "system_env_custom_theme": "theme-y08",
  "system_env_custom_locale": "zh_CN",
  "system_env_custom_preset_app_installed": "1",
  "system_env_custom_multiScan_littleP": "0",
  "system_env_custom_secondary_section_initialed": "1",
  "system_env_custom_secondary_app_need_install": "0",
  "auto_sleep_time": "120",
  "auto_shutdown_time": "3600",
  "volume_level": "10",
  "screen_brightness": "140",
  "screen_direction": "right_hand",
  "pronunciation_accent": "us",
  "auto_update_wifi_only": "true",
  "hardware_key_head_sound": "true",
  "ocr_auto_pronounce": "true",
  "network_dns_servers": "119.29.29.29,223.5.5.5"
}
```

#### 关键字段取值范围：
- `system_env_custom_theme`:
  - `"theme-y08"`: 有道经典黄/深黑 (S7 Pro 官方默认)
  - `"theme-hermes"`: 活力橙
  - `"theme-coco"`: 可可棕
  - `"theme-orange"`: 柑橘高对比
- `auto_sleep_time`: 自动休眠灭屏秒数（`"30"`, `"60"`, `"120"`, `"300"`, `"-1"` 从不）。
- `auto_shutdown_time`: 自动关机秒数（`"1800"`, `"3600"`, `"7200"`, `"-1"` 从不）。
- `volume_level`: 主音量等级（`"0"` ~ `"15"`）。
- `screen_brightness`: 屏幕亮度（`"10"` ~ `"255"`）。
- `screen_direction`: 手持方向与扫描朝向（`"right_hand"` = 0° 正常横屏, `"left_hand"` = 180° 翻转）。
- `pronunciation_accent`: 查词发音口音（`"us"` 美音, `"uk"` 英音）。

---

### 3.2 SharedPreferences 键值对规范 (`preferences.json`)

路径：`/userdata/miniapp/data/mini_app/pkg/8080272425914438/data/storage/preferences.json`  
规范：键和值必须严格为字符串类型，结构化对象必须通过 `JSON.stringify` 序列化保存。

---

## 4. 设置微服务 IPC 架构 (`falcon://8080272425914438/settings`)

### 4.1 服务生命周期与 5 秒空闲自愈看门狗

设置微服务（`settings.js.bin`）继承自 `$falcon.Service`：
- 当客户端连接时保持激活状态。
- 当最后一个客户端断开连接（`onDisconnected`）时，启动 5 秒倒计时看门狗：
  ```javascript
  onDisconnected() {
    super.onDisconnected();
    if (!this.hasConnection()) {
      setTimeout(() => {
        if (!this.hasConnection()) {
          this.finish(); // 终止自身，释放约 6.5MB 内存
        }
      }, 5000);
    }
  }
  ```
- 在 128MB 紧凑内存设备上，此设计确保设置完成后内存能被完整收回。

---

## 5. 生产级开发封装与统一接口实现

### 5.1 高可靠系统设置客户端 (`SystemSettingsManager.js`)

```javascript
/**
 * 生产级系统设置与全局配置管理器
 * 平台: 有道词典笔 S7 Pro (YDPS7-2)
 * 引擎: NetEase Falcon QuickJS 运行时
 */

import ServiceProxy from '$service_proxy';

// 原生 HAL 代理单例
let nativeBrightness = null;
let nativeVolume = null;
let nativeWifi = null;
let nativeBattery = null;

try {
  const mod = require('brightness');
  nativeBrightness = new mod.Brightness();
} catch (_) {}

try {
  const mod = require('volume');
  nativeVolume = new mod.Volume();
} catch (_) {}

try {
  const mod = require('wifi');
  nativeWifi = new mod.Wifi();
} catch (_) {}

try {
  const mod = require('batteryInfo');
  nativeBattery = new mod.BatteryInfo();
} catch (_) {}

export const SettingKeys = Object.freeze({
  THEME: 'system_env_custom_theme',
  LOCALE: 'system_env_custom_locale',
  SLEEP_TIMEOUT: 'auto_sleep_time',
  SHUTDOWN_TIMEOUT: 'auto_shutdown_time',
  VOLUME: 'volume_level',
  BRIGHTNESS: 'screen_brightness',
  ORIENTATION: 'screen_direction',
  ACCENT: 'pronunciation_accent',
  AUTO_UPDATE_WIFI: 'auto_update_wifi_only',
  OCR_AUTO_PRONOUNCE: 'ocr_auto_pronounce'
});

export const Themes = Object.freeze({
  CLASSIC_YELLOW: 'theme-y08',
  HERMES_ORANGE: 'theme-hermes',
  COCOA_BROWN: 'theme-coco',
  CITRUS_ORANGE: 'theme-orange'
});

class SystemSettingsManager {
  constructor() {
    this.subscribers = new Map();
    this.serviceProxy = null;
    this.isConnected = false;
    this._initEnvironmentListener();
  }

  _initEnvironmentListener() {
    if (typeof $falcon !== 'undefined' && typeof $falcon.on === 'function') {
      $falcon.on('customEnvChange', (event) => {
        if (!event || !event.key) return;
        this._notify(event.key, event.value);
      });
    }
  }

  _notify(key, value) {
    if (this.subscribers.has(key)) {
      this.subscribers.get(key).forEach((cb) => {
        try { cb(value, key); } catch (e) { console.error(e); }
      });
    }
  }

  get(key, defaultValue = null) {
    if (typeof $falcon !== 'undefined' && $falcon.env && $falcon.env.custom) {
      if (Object.prototype.hasOwnProperty.call($falcon.env.custom, key)) {
        return $falcon.env.custom[key];
      }
    }
    return defaultValue;
  }

  set(key, value) {
    const strVal = String(value);
    if (typeof $falcon !== 'undefined' && $falcon.env && $falcon.env.custom && typeof $falcon.env.custom.$set === 'function') {
      $falcon.env.custom.$set(key, strVal);
      this._notify(key, strVal);
      return true;
    }
    return false;
  }

  getBrightness() {
    if (nativeBrightness && typeof nativeBrightness.getBrightness === 'function') {
      return nativeBrightness.getBrightness();
    }
    return parseInt(this.get(SettingKeys.BRIGHTNESS, '128'), 10);
  }

  setBrightness(val) {
    const clamped = Math.max(10, Math.min(255, Math.round(val)));
    if (nativeBrightness && typeof nativeBrightness.setBrightness === 'function') {
      nativeBrightness.setBrightness(clamped);
    }
    this.set(SettingKeys.BRIGHTNESS, clamped);
  }

  getVolume() {
    if (nativeVolume && typeof nativeVolume.getVolume === 'function') {
      return nativeVolume.getVolume();
    }
    return parseInt(this.get(SettingKeys.VOLUME, '8'), 10);
  }

  setVolume(val) {
    const clamped = Math.max(0, Math.min(15, Math.round(val)));
    if (nativeVolume && typeof nativeVolume.setVolume === 'function') {
      nativeVolume.setVolume(clamped);
    }
    this.set(SettingKeys.VOLUME, clamped);
  }

  subscribe(key, callback) {
    if (!this.subscribers.has(key)) this.subscribers.set(key, new Set());
    this.subscribers.get(key).add(callback);
    return () => this.subscribers.get(key).delete(callback);
  }

  onThemeChanged(cb) { return this.subscribe(SettingKeys.THEME, cb); }
  onVolumeChanged(cb) { return this.subscribe(SettingKeys.VOLUME, (v) => cb(parseInt(v, 10))); }
  onBrightnessChanged(cb) { return this.subscribe(SettingKeys.BRIGHTNESS, (v) => cb(parseInt(v, 10))); }
}

export const systemSettings = new SystemSettingsManager();
export default systemSettings;
```
