# 有道词典笔 S7 Pro 硬件抽象层 (HAL) 与服务代理 (IPC) 逆向工程技术报告

基于对设备系统动态库（`/usr/lib/libfalcon.so`、`/etc/miniapp/jsapis/libjsapi_export_core.so`、`/oem/secondary/etc/miniapp/jsapis/libjsapi_export.so`、`/usr/lib/libydhal_devices.so`、`/usr/lib/libyddal_adapter_core.so`、`/usr/lib/libyddal_business_core.so`）、官方生产微应用包（喜马拉雅 `xmlyNativeSdk-bf5810d5.js`、系统设置 `SettingManager-41d1e6fb.js.bin`、音频播放服务 `mediaPlayerService.js.bin`、OCR 提笔及扫 `8001733883553973`）及 Linux 底层驱动的反汇编与符号审计，完整解构报告如下。

---

## 1. 原生 JS 模块架构机制与接口真实签名

### 1.1 QuickJS 原生 C 模块导出与实例化铁律
在 Falcon Runtime 中，内建硬件模块基于 JQuick 原生 C 模块机制（`registerCModuleLoader`）实现。
1. 当执行 `import moduleName from 'moduleName'` 时，QuickJS 载入 C 模块导出的 `'default'` 字典对象。
2. 字典对象内挂载了对应 C++ Proxy 类的 PascalCase 构造函数（如 `{ Brightness: [Function Brightness] }`）。
3. **调用铁律**：模块导入后**绝不能**直接以静态对象方式调用方法，必须显式通过 `new module.ClassName()` 构造出代理实例，才能完成底层 `JQSignal` 绑定并调用原生原型方法。

---

### 1.2 `brightness`（背光控制模块）
- **模块标识**：`import brightnessModule from 'brightness'`
- **构造类名**：`Brightness`（`const brightness = new brightnessModule.Brightness()`）
- **底层映射**：`JSBrightnessProxy` -> `YBrightnessAdapterPrivate` -> `/sys/class/backlight/backlight/brightness`
- **数值标尺**：**0 到 255**（整型绝对值）。

#### 真实方法签名
- `setBrightness(brightness: number): void`：设置物理屏幕背光（范围 0 ~ 255）。
- `getBrightness(): number`：获取当前物理背光值（0 ~ 255）。
- `keepScreenOn(keep: boolean): void`：开启或关闭屏幕常亮策略。
- `screenOnOff(on: boolean): void`：强制开启 (`true`) 或关闭 (`false`) 屏幕输出。
- `getScreenState(): boolean`：获取当前屏幕点亮状态（`true`=亮屏，`false`=灭屏）。
- `startAlwaysScreenOn(): void`：开启持久常亮模式（禁用自动休眠计时）。
- `stopAlwaysScreenOn(): void`：停止持久常亮模式（恢复系统休眠策略）。
- `getTpUpdateStatus(): number`：获取触控固件升级状态码。

> **接口澄清**：系统**不存在** `getMinBrightness` 与 `getMaxBrightness` 接口。硬件级有效范围固定为 0 ~ 255。

#### 信号与事件订阅
- `brightnessChanged`: `(isSuccess: boolean) => void` — 背光调节完成通知。
- `brightnessValueChanged`: `(val: number) => void` — 外部按键或系统更改亮度广播。
- `screenStatusChanged`: `(isOn: boolean) => void` — 亮灭屏突变广播。
- `tpUpdateResult`: `(resultCode: number) => void` — 触控固件刷新结果。

---

### 1.3 `volume`（系统音量控制模块）
- **模块标识**：`import volumeModule from 'volume'`
- **构造类名**：`Volume`（`const volume = new volumeModule.Volume()`）
- **底层映射**：`JSVolumenessProxy` -> `YDALAPI::YVolumeModule` -> `ubus` 发送 `set_volume`（`volume_level`）
- **数值标尺**：**0 到 15**（系统主音量分级）。

#### 真实方法签名
- `setVolume(volume: number): void`：设置系统主音量（范围 0 ~ 15，非法类型抛出 `ThrowTypeError`）。
- `getVolume(): number`：获取当前系统主音量（0 ~ 15）。
- `startVolumeThread(): void`：启动音量监听线程与物理按键联动（进入音量页面时调用）。
- `stopVolumeThread(): void`：挂起音量监听线程（离开页面时调用释放资源）。
- `getCurrentShowPage(): string`：获取当前活跃页面标识。

> **接口澄清**：系统**不存在** `getMaxVolume` 接口。音量档位固定为 0 ~ 15。

#### 信号与事件订阅
- `volumeChanged`: `(isSuccess: boolean) => void` — 音量设置是否成功。
- `callBackVolumeValue`: `(volume: number) => void` — 音量值变化广播（内部对应 `onNotifyVolumeValue`）。

---

### 1.4 `batteryInfo`（电池与电源信息模块）
- **模块标识**：`import batteryInfoModule from 'batteryInfo'`
- **构造类名**：`BatteryInfo`（`const batteryInfo = new batteryInfoModule.BatteryInfo()`）
- **底层映射**：`JBatteryInfoProxy` -> `/sys/class/power_supply/battery/`
- **数值标尺**：**0 到 100**（剩余电量百分比）。

#### 真实方法签名
- `getBatteryCapacity(): number`：获取当前电池电量百分比（0 ~ 100）。
- `getBatteryStatus(): number`：获取电池状态（1: 充电中, 2: 放电中, 3: 充满, 4: 未接电池）。
- `isCharging(): boolean`：查询当前是否处于外接供电充电状态。

> **接口澄清**：开发者容易误设为 `getBatteryLevel()`，反编译汇编确认官方唯一名称为 `getBatteryCapacity()`。

#### 信号与事件订阅
- `batteryInfoChange`: `(isCharging: boolean, capacity: number) => void` — 充电状态或电量变动广播。

---

### 1.5 `wifi`（Wi-Fi 网络管理模块）
- **模块标识**：`import wifiModule from 'wifi'`
- **构造类名**：`Wifi`（`const wifi = new wifiModule.Wifi()`）
- **底层映射**：`JSWifiProxy` -> `wpa_supplicant` / `wifi-manager`

#### 真实方法签名
- `open(): void`：开启物理 Wi-Fi 芯片电源与射频。
- `close(): void`：关闭物理 Wi-Fi 芯片。
- `isOpen(): boolean`：查询 Wi-Fi 芯片是否处于开启状态。
- `isConnected(): boolean`：查询当前是否已接入无线网络。
- `getState(): number`：获取网络状态机状态码（0: 关闭, 1: 扫描, 2: 认证, 3: 已连接）。
- `scan(): void`：发起热点扫描（结果通过事件异步通知）。
- `connect(ssid: string, pwd: string, encrypt?: string): void`：连接指定 AP（`encrypt` 支持 `'WPA2-PSK'` 等）。
- `disconnect(): void`：断开当前 Wi-Fi 连接。
- `getIP(): string`：获取设备当前局域网 IPv4 地址。
- `getWifiQual(): number`：获取当前信号质量分贝/档位（0 ~ 4）。
- `startWifiQualTimer(): void` / `stopWifiQualTimer(): void`：启停信号强度轮询定时器。
- `wifiPageBackButtonClicked(): void`：Wi-Fi 配置页面返回事件。

#### 信号与事件订阅
- `wifiStatusChanged`: `(enabled: boolean) => void` — 开关状态切换。
- `wifiListChanged`: `(listJson: string) => void` — 热点列表更新（JSON 数组字符串）。
- `wifiQualChanged`: `(qual: string) => void` — 信号强度波动通知。
- `internetConnectChanged`: `(ssid: string, connected: boolean) => void` — 外网连通状态变动。
- `wifiScanError`: `(code: string, msg: string) => void` — 扫描异常回调。

---

### 1.6 `buttonEvent`（物理按键与手势模块）
- **模块标识**：`import buttonEventModule from 'buttonEvent'`
- **构造类名**：`ButtonEvent`（`const buttonEvent = new buttonEventModule.ButtonEvent()`）
- **底层映射**：`JSButtonEventModuleProxy` -> `/dev/input/event3` -> `input_subsytem_monitor`

#### 原型方法
- `isHeadButtonPressed(): boolean`：查询笔尖微动开关当前是否受压触纸。
- `setButtonEventReady(ready: boolean): void`：通知系统当前微应用按键监听就绪。
- `emitBottomSwipeBackEvent(): void`：软件触发屏幕底部边缘上滑返回事件。
- `softButtonEvent(action: string): void`：模拟注入按键动作。

#### 42 种物理按键与手势信号全景（含特异性拼写）
底层符号表存在历史拼写差异：部分按键采用 **`Relese`**（无 `a`），部分按键采用标准 **`Release`**。必须完全按符号注册：

1. **笔尖开关 (Pen Tip)**：
   - `headButtonPress`
   - `headButtonRelese`（**无 a**）
2. **Home 按键**：
   - `homeButtonPress`
   - `homeButtonRelease`（**有 a**）
   - `homeButtonClick`
   - `homeButtonDoubleClick`
   - `homeButtonLongPress`
3. **电源键 (Power Key)**：
   - `powerButtonPress`
   - `powerButtonRelese`（**无 a**）
   - `powerButtonClick`
   - `powerButtonDoubleClick`
   - `powerButtonLongPress`
4. **播放键 (Play Key)**：
   - `playButtonPress`
   - `playButtonRelese`（**无 a**）
   - `playButtonClick`
   - `playDoubleClick`
   - `playButtonLongPress`
5. **返回 / 前进键**：
   - `backButtonPress` / `backButtonRelese`（**无 a**）/ `backButtonClick` / `backDoubleClick` / `backButtonLongPress`
   - `forwardButtonPress` / `forwardButtonRelese`（**无 a**）/ `forwardButtonClick` / `forwardDoubleClick` / `forwardButtonLongPress`
6. **音量加减键**：
   - `volumeUpButtonPress` / `volumeUpButtonRelese`（**无 a**）/ `volumeUpButtonClick` / `volumeUpDoubleClick` / `volumeUpButtonLongPress`
   - `volumeDownButtonPress` / `volumeDownButtonRelese`（**无 a**）/ `volumeDownButtonClick` / `volumeDownDoubleClick` / `volumeDownButtonLongPress`
7. **霍尔传感器与滚轮**：
   - `hallTop` / `hallBottom`
   - `rotaryTurn`
8. **取景键 (Camera Preview Button)**：
   - `headCameraPreviewButtonPress`
   - `headCameraPreviewButtonRelease`（**有 a**）
   - `headCameraPreviewButtonClick`
   - `headCameraPreviewButtonDoubleClick`
9. **手势操作**：
   - `bottomSwipeBackEvent`（屏幕底沿上滑返回）

---

### 1.7 `systemInfo`（系统硬件信息模块）
- **模块标识**：`import systemInfoModule from 'systemInfo'`
- **构造类名**：`SystemInfo`（`const systemInfo = new systemInfoModule.SystemInfo()`）
- **底层映射**：`JSystemInfoProxy` -> `YDALAPI::YSystemInfoModule`

#### 真实方法签名
- `getSNInfo(): string`：获取设备唯一序列号 SN。
- `getMacInfo(): string`：获取 Wi-Fi 芯片硬件 MAC 地址。
- `getDeviceType(): string`：获取设备硬件型号代号（如 `"S7 Pro"` / `"Peach"`）。
- `getDeviceName(): string`：获取设备出厂命名。
- `getVersion(): string`：获取 Falcon 固件与 OS 版本号（如 `"4.23.0"`）。
- `getUUIDInfo(): string`：获取设备硬件全局 UUID。
- `getAdbEnable(): number`：获取 ADB 调试开关（0=关, 1=开）。
- `setAdbEnable(enable: number): void`：动态设置 ADB 调试模式。
- `getStorageInfo(): string`：获取存储分区使用情况 JSON 字符串。
- `getAvailableSpace(): number`：获取用户分区当前可用字节（Bytes）。
- `getSystemFlashSize(): number`：获取主板 Flash 总容量。
- `getHandedness(): number`：获取左右手握笔习惯（0: 右手正常, 1: 左手屏幕反转 180 度）。
- `setHandedness(mode: number): void`：设置握笔习惯。
- `getSystemTime(): string`：获取当前系统时间戳。
- `updateCurrentSystemTime(): void`：强制触发 NTP 网络对时。
- `feedWatchdog(): void`：喂硬件看门狗（防止硬件被 MCU 复位）。
- `closeBootLogo(): void`：关闭开机第一帧静态 Logo。
- 信号：`onSystemTimeChange`。

---

### 1.8 `pm`（包管理器模块）
- **模块标识**：`import pmModule from 'pm'`
- **构造类名**：`PackageManager`（`const pm = new pmModule.PackageManager()`）
- **底层映射**：`libfalcon.so` -> `pm::JSPackageManager` -> `JQuick::IotPackageManager`

#### 真实方法签名
- `getInstalledPackages(): Array<PackageInfo>`：获取已安装微应用全量元数据。
- `getPackagesByCategory(category: string): Array<PackageInfo>`：按分类筛选应用（如 `'SERVICE'`, `'MEDIAPLAYER'`, `'SETTING'`）。
- `getPackageInfo(appId: string): PackageInfo`：获取指定 16 位 AppID 的详情与权限配置。
- `installPackage(amrPath: string, callback: (code: number, res: any) => void): void`：安装本地 `.amr` 安装包。
- `removePackage(appId: string, callback: (code: number, res: any) => void): void`：卸载指定微应用。
- 信号：`packageInstalled`、`packageRemoved`、`packageUpdated`。

---

## 2. IPC 服务代理机制 (`$service_proxy`) 与后台服务常驻解构

### 2.1 后台服务自启与常驻机制
在 `/etc/miniapp/resources/local_packages.json` 与 `/userdata/miniapp/data/mini_app/pkg/packages.json` 中，配置为 `Category: "SERVICE"` 或具体服务分类（如 `MEDIAPLAYER`、`RECORD_SERVICES`）的应用具有以下运行时特征：
1. **DLink 延迟按需唤醒 (Lazy Launch)**：开机并不盲目启动所有后台应用。当客户端调用 `$service_proxy.connect("falcon://<AppID>/<ServiceName>")` 时，`falcon::ServiceStack::startServiceUri` 检测实例运行状态。
2. **Headless 无界面实例**：若未运行，Falcon 引擎以轻量级模式拉起该 AppID，执行环境采用 `/etc/miniapp/resources/framework/jsfm-service.js.bin`，载入对应 `services/<ServiceName>.js.bin` 脚本，不创建 UI 窗口和渲染树，内存占用控制在 3MB~6MB。
3. **常驻与保活策略**：只要客户端维持 IPC Channel 连接，或服务处于活跃状态（如音频播放器处于播放中），Falcon 不会触发 OOM 销毁。若包配置具备 `Important: true`，在异常崩溃后由引擎主动重新实例化。

---

### 2.2 服务端开发契约 (`services/<ServiceName>.js`)
服务实现者在其脚本中通过 `$falcon.Service` 注册生命周期钩子：

```javascript
$falcon.Service({
    onCreate() {
        console.log("Service: 初始化资源");
    },
    onNewOptions(options) {
        console.log("Service: 接收启动参数", options);
    },
    onConnected(owner) {
        console.log("Service: 客户端连入 Token=" + owner);
    },
    onDisconnected(owner) {
        console.log("Service: 客户端断开 Token=" + owner);
    },
    onCommand(action, params, callback) {
        // action: 客户端调用的命令字符串
        // params: 携带的参数对象
        // callback(code, resultObject): 应答客户端
        if (action === 'getPlayState') {
            callback(0, { isPlaying: true, position: 1024, duration: 60000 });
        } else {
            callback(-1, { error: 'Unknown action' });
        }
    },
    onDestroy() {
        console.log("Service: 资源释放与退出");
    }
});
```

---

### 2.3 前台微应用 IPC 连接调用规范

```javascript
import ServiceProxy from '$service_proxy';

const proxy = new ServiceProxy();

// 1. 注册连接建立事件
proxy.onConnected = () => {
    console.log("IPC 已连通");
    
    // 2. 发送业务指令 (action, params, callback)
    proxy.sendCommand('play', { mediaId: '10001' }, (code, res) => {
        console.log("指令执行结果 code=" + code, res);
    });
};

// 3. 注册连接断开事件
proxy.onDisconnected = () => {
    console.log("IPC 连接断开");
};

// 4. 监听服务端主动下发的广播事件
const token = proxy.on('onPlayStateChanged', (data) => {
    console.log("收到服务事件广播:", data);
});

// 5. 建立连接 (falcon://<AppID>/<ServiceName>)
proxy.connect('falcon://8001650599023931/mediaPlayerService');

// 6. 销毁时解绑与断开
// proxy.off(token);
// proxy.disconnect();
```

---

## 3. 本地持久化存储 (`$falcon.jsapi.storage`) 深度解构

### 3.1 C++ 存储机制与磁盘物理文件
- **底层驱动**：`libfalcon.so` 中的 `sharedpreferences`。
- **存储文件绝对路径**：
  `/userdata/miniapp/data/mini_app/sharedpreferences/<AppID>/preferences.json`
- **全局预置配置路径**：
  `/userdata/miniapp/data/mini_app/sharedpreferences/__PRESET__/preferences.json`
- **持久化格式**：基于 JSON 树形结构的键值对磁盘序列化，进程退出或系统意外重启数据不丢失。

### 3.2 真实接口签名与 Promise 返回规范

#### 1) `setStorage({ key, data })`
- **入参格式**：`{ key: string, data: any }`。
- **返回规范**：`Promise<void>`。写入成功后 resolve。

#### 2) `getStorage({ key })`
- **入参格式**：`{ key: string }`。
- **返回规范**：`Promise<{ data?: any, error?: string }>`。
- **解析契约**：返回值对象中核心数据存放在 `.data` 属性内：
  ```javascript
  const res = await $falcon.jsapi.storage.getStorage({ key: 'user_token' });
  const token = res && !res.error ? res.data : null;
  ```

#### 3) `removeStorage({ key })`
- **入参格式**：`{ key: string }`。
- **返回规范**：`Promise<void>`。删除对应键。

#### 4) `clearStorage()`
- **入参格式**：无入参。
- **返回规范**：`Promise<void>`。清空当前 AppID 命名空间下的全部键值。

#### 5) `getStorageInfo()`
- **返回规范**：`Promise<{ keys: string[], currentSize: number, limitSize: number }>`。返回已用字节与上限。

---

## 4. 全量 HAL 硬件控制调用代码库

可直接在微应用中引入使用的生产级控制库源码如下：

```javascript
/**
 * YoudaoPenHAL.js - 有道词典笔 S7 Pro 统一硬件抽象层 (HAL)
 * 适配运行时: QuickJS 2020-07-05 / Falcon 4.23.0
 */

import brightnessModule from 'brightness';
import volumeModule from 'volume';
import batteryInfoModule from 'batteryInfo';
import wifiModule from 'wifi';
import buttonEventModule from 'buttonEvent';
import systemInfoModule from 'systemInfo';
import pmModule from 'pm';
import ServiceProxy from '$service_proxy';

export class BrightnessManager {
    constructor() {
        this._native = new brightnessModule.Brightness();
    }
    setLevel(level) {
        const val = Math.max(0, Math.min(255, Math.round(level)));
        this._native.setBrightness(val);
    }
    getLevel() {
        return this._native.getBrightness();
    }
    setScreenPower(on) {
        this._native.screenOnOff(!!on);
    }
    isScreenOn() {
        return !!this._native.getScreenState();
    }
    setKeepScreenOn(keep) {
        if (keep) {
            this._native.startAlwaysScreenOn();
        } else {
            this._native.stopAlwaysScreenOn();
        }
        this._native.keepScreenOn(!!keep);
    }
    onBrightnessChange(callback) {
        this._native.on('brightnessValueChanged', callback);
    }
    onScreenStatusChange(callback) {
        this._native.on('screenStatusChanged', callback);
    }
}

export class VolumeManager {
    constructor() {
        this._native = new volumeModule.Volume();
    }
    setLevel(level) {
        const val = Math.max(0, Math.min(15, Math.round(level)));
        this._native.setVolume(val);
    }
    getLevel() {
        return this._native.getVolume();
    }
    attach() {
        this._native.startVolumeThread();
    }
    detach() {
        this._native.stopVolumeThread();
    }
    onVolumeChange(callback) {
        this._native.on('callBackVolumeValue', callback);
    }
}

export class BatteryManager {
    constructor() {
        this._native = new batteryInfoModule.BatteryInfo();
    }
    getCapacity() {
        return this._native.getBatteryCapacity();
    }
    isCharging() {
        return !!this._native.isCharging();
    }
    getStatus() {
        return this._native.getBatteryStatus();
    }
    onChange(callback) {
        this._native.on('batteryInfoChange', callback);
    }
}

export class WifiManager {
    constructor() {
        this._native = new wifiModule.Wifi();
    }
    enable() { this._native.open(); }
    disable() { this._native.close(); }
    isEnabled() { return !!this._native.isOpen(); }
    isConnected() { return !!this._native.isConnected(); }
    getIpAddress() { return this._native.getIP(); }
    getSignalQuality() { return this._native.getWifiQual(); }
    scan() {
        return new Promise((resolve) => {
            const onList = (jsonStr) => {
                try {
                    const list = typeof jsonStr === 'string' ? JSON.parse(jsonStr) : jsonStr;
                    resolve(list || []);
                } catch (e) {
                    resolve([]);
                }
            };
            this._native.on('wifiListChanged', onList);
            this._native.scan();
        });
    }
    connect(ssid, password, encrypt = 'WPA2-PSK') {
        this._native.connect(ssid, password, encrypt);
    }
    disconnect() { this._native.disconnect(); }
    onInternetChange(callback) {
        this._native.on('internetConnectChanged', callback);
    }
}

export class ButtonEventManager {
    constructor() {
        this._native = new buttonEventModule.ButtonEvent();
        this._native.setButtonEventReady(true);
    }
    isTipPressed() {
        return !!this._native.isHeadButtonPressed();
    }
    onPenTip(onPress, onRelease) {
        if (onPress) this._native.on('headButtonPress', onPress);
        if (onRelease) this._native.on('headButtonRelese', onRelease); // 底层严格拼写 Relese
    }
    onHomeKey({ click, doubleClick, longPress, press, release } = {}) {
        if (click) this._native.on('homeButtonClick', click);
        if (doubleClick) this._native.on('homeButtonDoubleClick', doubleClick);
        if (longPress) this._native.on('homeButtonLongPress', longPress);
        if (press) this._native.on('homeButtonPress', press);
        if (release) this._native.on('homeButtonRelease', release); // 底层拼写 Release
    }
    onPowerKey({ click, doubleClick, longPress } = {}) {
        if (click) this._native.on('powerButtonClick', click);
        if (doubleClick) this._native.on('powerButtonDoubleClick', doubleClick);
        if (longPress) this._native.on('powerButtonLongPress', longPress);
    }
    onVolumeKeys({ onUp, onDown } = {}) {
        if (onUp) this._native.on('volumeUpButtonClick', onUp);
        if (onDown) this._native.on('volumeDownButtonClick', onDown);
    }
    onBottomSwipeBack(callback) {
        this._native.on('bottomSwipeBackEvent', callback);
    }
}

export class SystemInfoManager {
    constructor() {
        this._native = new systemInfoModule.SystemInfo();
    }
    getSummary() {
        return {
            sn: this._native.getSNInfo(),
            mac: this._native.getMacInfo(),
            model: this._native.getDeviceType(),
            deviceName: this._native.getDeviceName(),
            firmwareVersion: this._native.getVersion(),
            uuid: this._native.getUUIDInfo(),
            availableDiskBytes: this._native.getAvailableSpace(),
            flashSizeBytes: this._native.getSystemFlashSize(),
            isLeftHand: this._native.getHandedness() === 1,
            isAdbEnabled: this._native.getAdbEnable() === 1
        };
    }
    setHandedness(isLeftHand) {
        this._native.setHandedness(isLeftHand ? 1 : 0);
    }
    feedWatchdog() {
        this._native.feedWatchdog();
    }
}

export class StorageService {
    static async get(key, defaultValue = null) {
        try {
            if ($falcon && $falcon.jsapi && $falcon.jsapi.storage) {
                const res = await $falcon.jsapi.storage.getStorage({ key });
                if (res && !res.error && res.data !== undefined && res.data !== null) {
                    return res.data;
                }
            } else if (typeof localStorage !== 'undefined') {
                const v = localStorage.getItem(key);
                return v !== null ? v : defaultValue;
            }
        } catch (e) {
            console.error('StorageService.get error:', e);
        }
        return defaultValue;
    }
    static async set(key, value) {
        try {
            const dataStr = typeof value === 'object' ? JSON.stringify(value) : String(value);
            if ($falcon && $falcon.jsapi && $falcon.jsapi.storage) {
                return await $falcon.jsapi.storage.setStorage({ key, data: dataStr });
            } else if (typeof localStorage !== 'undefined') {
                localStorage.setItem(key, dataStr);
            }
        } catch (e) {
            console.error('StorageService.set error:', e);
        }
    }
    static async remove(key) {
        if ($falcon && $falcon.jsapi && $falcon.jsapi.storage) {
            return await $falcon.jsapi.storage.removeStorage({ key });
        } else if (typeof localStorage !== 'undefined') {
            localStorage.removeItem(key);
        }
    }
    static async clear() {
        if ($falcon && $falcon.jsapi && $falcon.jsapi.storage) {
            return await $falcon.jsapi.storage.clearStorage();
        } else if (typeof localStorage !== 'undefined') {
            localStorage.clear();
        }
    }
}

export class ServiceClient {
    constructor(serviceUri) {
        this._uri = serviceUri;
        this._proxy = new ServiceProxy();
        this._isConnected = false;
        this._pendingCommands = [];

        this._proxy.onConnected = () => {
            this._isConnected = true;
            this._flushPending();
            if (this.onConnected) this.onConnected();
        };
        this._proxy.onDisconnected = () => {
            this._isConnected = false;
            if (this.onDisconnected) this.onDisconnected();
        };
    }
    connect() { this._proxy.connect(this._uri); }
    disconnect() {
        if (this._isConnected) this._proxy.disconnect();
    }
    invoke(action, params = {}) {
        return new Promise((resolve, reject) => {
            const execute = () => {
                this._proxy.sendCommand(action, params, (code, result) => {
                    if (code === 0) resolve(result);
                    else reject(new Error(`IPC 指令执行失败 [${action}] code=${code}`));
                });
            };
            if (this._isConnected) execute();
            else this._pendingCommands.push(execute);
        });
    }
    subscribe(eventName, handler) {
        return this._proxy.on(eventName, handler);
    }
    unsubscribe(token) {
        this._proxy.off(token);
    }
    _flushPending() {
        while (this._pendingCommands.length > 0) {
            const cmd = this._pendingCommands.shift();
            try { cmd(); } catch (e) { console.error('IPC flush error:', e); }
        }
    }
}

export default class YoudaoPenHAL {
    static get brightness() {
        if (!this._brightness) this._brightness = new BrightnessManager();
        return this._brightness;
    }
    static get volume() {
        if (!this._volume) this._volume = new VolumeManager();
        return this._volume;
    }
    static get battery() {
        if (!this._battery) this._battery = new BatteryManager();
        return this._battery;
    }
    static get wifi() {
        if (!this._wifi) this._wifi = new WifiManager();
        return this._wifi;
    }
    static get button() {
        if (!this._button) this._button = new ButtonEventManager();
        return this._button;
    }
    static get system() {
        if (!this._system) this._system = new SystemInfoManager();
        return this._system;
    }
    static get storage() {
        return StorageService;
    }
    static getServiceClient(uri) {
        return new ServiceClient(uri);
    }
}
```

---

## 5. 关键文件与设备绝对路径清单

- **原生 JSAPI 核心库**：
  - `/etc/miniapp/jsapis/libjsapi_export_core.so`
  - `/oem/secondary/etc/miniapp/jsapis/libjsapi_export.so`
- **Falcon 引擎与 IPC 底层库**：
  - `/usr/lib/libfalcon.so`
  - `/usr/lib/libjsapi_proxy.so`
- **HAL 与底层硬件适配库**：
  - `/usr/lib/libydhal_devices.so`
  - `/usr/lib/libyddal_adapter_core.so`
  - `/usr/lib/libyddal_business_core.so`
- **服务运行时与无界面框架**：
  - `/etc/miniapp/resources/framework/jsfm-service.js.bin`
- **全局微应用包注册清单**：
  - `/etc/miniapp/resources/local_packages.json`
  - `/oem/secondary/etc/miniapp/resources/local_packages.json`
  - `/userdata/miniapp/data/mini_app/pkg/packages.json`
- **本地存储持久化文件根目录**：
  - `/userdata/miniapp/data/mini_app/sharedpreferences/<AppID>/preferences.json`
  - `/userdata/miniapp/data/mini_app/sharedpreferences/__PRESET__/preferences.json`
- **Linux 内核驱动 Sysfs 节点**：
  - `/sys/class/backlight/backlight/brightness`（0 ~ 255）
  - `/sys/class/power_supply/battery/capacity`
  - `/dev/input/event3`（按键输入中断流）