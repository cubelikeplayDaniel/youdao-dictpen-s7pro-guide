# 有道词典笔 S7 Pro 蓝牙、Wi-Fi、电源管理 (PMIC AXP2101) 与硬件抽象层 (HAL) 全量指南
## (Falcon Bluetooth, Wi-Fi, PMIC AXP2101 & Hardware Abstraction Layer Developer Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A53/A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: BlueZ 5.x, `bluealsa`, `wpa_supplicant`, `wifi-manager`, `libjsapi_export_core.so`, `libydhal_devices.so`

---

## 目录索引

1. [蓝牙子系统架构与双模通信 (A2DP & BLE)](#1-蓝牙子系统架构与双模通信-a2dp--ble)
   - [1.1 BlueZ + BlueALSA 协议栈拓扑](#11-bluez--bluealsa-协议栈拓扑)
   - [1.2 `'bluetooth'` 核心模块与 API 字典](#12-bluetooth-核心模块与-api-字典)
   - [1.3 `'headSetInfo'` 音频外设统一抽象模块](#13-headsetinfo-音频外设统一抽象模块)
2. [Wi-Fi 网络子系统与连接状态机](#2-wi-fi-网络子系统与连接状态机)
   - [2.1 wpa_supplicant 与 wifi-manager 协同架构](#21-wpa_supplicant-与-wifi-manager-协同架构)
   - [2.2 热点扫描、四次握手认证与 DHCP 生效时序](#22-热点扫描四次握手认证与-dhcp-生效时序)
   - [2.3 `'wifi'` 模块 API 字典与信号质量定时轮询门禁](#23-wifi-模块-api-字典与信号质量定时轮询门禁)
   - [2.4 `'network'` 通用轻量网络监听模块](#24-network-通用轻量网络监听模块)
3. [电源管理系统 (PMIC AXP2101 / CPU 调频 / 屏幕背光)](#3-电源管理系统-pmic-axp2101--cpu-调频--屏幕背光)
   - [3.1 AXP2101 拓扑、硬件库仑计与 Sysfs 电量节点](#31-axp2101-拓扑硬件库仑计与-sysfs-电量节点)
   - [3.2 `'batteryInfo'` 模块 API 字典](#32-batteryinfo-模块-api-字典)
   - [3.3 CPU 1.0GHz 锁定与无 DVFS 机制](#33-cpu-10ghz-锁定与无-dvfs-机制)
   - [3.4 屏幕背光 PWM 调制机制 (20 kHz 零啸叫与无频闪)](#34-屏幕背光-pwm-调制机制-20-khz-零啸叫与无频闪)
4. [生产级实战范式与代码示例](#4-生产级实战范式与代码示例)

---

## 1. 蓝牙子系统架构与双模通信 (A2DP & BLE)

### 1.1 BlueZ + BlueALSA 协议栈拓扑
S7 Pro 采用标准 Linux BlueZ 官方开源协议栈，射频硬件为 SeekWave (SKW) Wi-Fi/BT 二合一无线芯片，系统服务如下：
- **BlueZ 守护进程**: `/usr/libexec/bluetooth/bluetoothd -C -n -d -E`（开启兼容与 BLE GATT 实验特性，监听 D-Bus 总线 `/var/run/dbus/system_bus_socket`）。
- **蓝牙音频中继**: `/usr/bin/bluealsa --profile=a2dp-source --profile=hfp-ag --a2dp-volume --sbc-quality=0`。
- **业务中枢**: `/usr/bin/bt-manager` 桥接 D-Bus 与 ubus，通过 `yd_bt_mgr.bt_device.*` 主题进行广播。
- **音频路由切换**: 当耳机连入时，ALSA 节点由本地 `pcm.speaker`（`hw:1,0`）动态重定向至 `bluealsa:PROFILE=a2dp,DEV=<BT_MAC>`。

### 1.2 `'bluetooth'` 核心模块与 API 字典
由 `libjsapi_export_core.so` 导出：

```javascript
import bluetoothModule from 'bluetooth';
const bt = new bluetoothModule.BlueTooth();
```

#### 经典蓝牙 (A2DP) 方法
- `open()`: 打开蓝牙射频
- `close()`: 关闭蓝牙射频
- `isBtOpen()`: 查询蓝牙开关状态 (`boolean`)
- `isConnected()`: 查询是否有耳机已连接 (`boolean`)
- `scanStart()`: 开启外设扫描
- `scanStop()`: 停止扫描
- `connect(mac, name)`: 连接指定蓝牙耳机
- `disconnect(mac, name)`: 断开指定耳机
- `remove(mac, name)`: 从配对列表彻底移除
- `btGetBattery()`: 获取耳机 HFP 剩余电量百分比
- `btGetInfo()`: 获取已配对设备元数据 JSON

#### BLE 低功耗蓝牙方法
- `bleOpen()`: 启动 BLE GATT
- `bleClose()`: 关闭 BLE
- `isBleOpen()`: BLE 是否就绪 (`boolean`)
- `isConnectBle()`: 是否有 BLE 外设连入 (`boolean`)
- `bleWrite(uuid, hexData)`: 向指定 GATT 特征值写入数据
- `bleDisconnect(mac)`: 断开 BLE 设备

#### 信号列表 (JQSignal)
- `bluetoothSwitchChanged.connect((isOpen) => {})`
- `bluetoothScanChanged.connect((isScanning) => {})`
- `bluetoothConnectStatusChanged.connect((isConnected) => {})`
- `connectDevice.connect((name, mac) => {})`
- `disconnectDevice.connect((name, mac) => {})`
- `onBluetoothA2dpVolumeChanged.connect((vol) => {})`
- `onBluetoothHfpBatteryChanged.connect((battery) => {})`

### 1.3 `'headSetInfo'` 音频外设统一抽象模块
若应用仅关注“是否有耳机连入以切换音频路由”，推荐使用 `'headSetInfo'` 模块，它统一抽象了蓝牙 A2DP 耳机和 Type-C 有线耳机：

```javascript
import headSetInfoModule from 'headSetInfo';
const headSet = new headSetInfoModule.HeadSetInfo();

headSet.headsetStateChanged.connect((hasOn) => {
  console.log('耳机插入/连入状态:', hasOn);
});

headSet.headsetChanged.connect((type, name, addr) => {
  // type: 1 = 蓝牙 A2DP 耳机; 2 = Type-C 数字有线耳机
  console.log(`耳机类型: ${type}, 名称: ${name}, 地址: ${addr}`);
});
```

---

## 2. Wi-Fi 网络子系统与连接状态机

### 2.1 wpa_supplicant 与 wifi-manager 协同架构
- **核心 WPA 引擎**: `/usr/sbin/wpa_supplicant -Dnl80211 -iwlan0 -c/userdata/cfg/wpa_supplicant.conf`
- **控制中枢**: `/usr/bin/wifi-manager` 通过客户端套接字与 ubus 转发指令并触发 `udhcpc` 获取 IP。

### 2.2 热点扫描、四次握手认证与 DHCP 生效时序
```
[MiniApp JS] wifi.scan()
     ↓
[wifi-manager] 下发 "SCAN" 指令至 wpa_supplicant
     ↓
[wpa_supplicant] 触发底层 802.11 射频扫描并回传 "CTRL-EVENT-SCAN-RESULTS"
     ↓
[wifi-manager] 提取 "SCAN_RESULTS" 并通过 ubus 发送 "yd_net_mgr.network.list"
     ↓
[MiniApp JS] wifi.wifiListChanged.connect((listJson) => {})
```

### 2.3 `'wifi'` 模块 API 字典与信号质量定时轮询门禁
由 `libjsapi_export_core.so` 导出：

```javascript
import wifiModule from 'wifi';
const wifi = new wifiModule.Wifi();
```

| 方法名 | 返回值 | 说明 |
| :--- | :--- | :--- |
| `isOpen()` | `boolean` | Wi-Fi 硬件是否开启 |
| `open()` | `void` | 开启 Wi-Fi 射频供电 |
| `close()` | `void` | 关闭 Wi-Fi 射频 |
| `isConnected()` | `boolean` | 是否已接入无线路由器 AP |
| `getWifiQual()` | `number` | 获取当前 Wi-Fi 信号强度格数 (`0` ~ `4`) |
| `getIP()` | `string` | 获取本机当前 IPv4 地址（如 `"192.168.1.105"`） |
| `scan()` | `void` | 发起异步周围热点扫描 |
| `connect(ssid, pwd, encrypt)` | `void` | 连接指定热点（encrypt: `"WPA"`, `"WPA2"`, `"NONE"`） |
| `disconnect()` | `void` | 断开当前 Wi-Fi 连接 |
| `startWifiQualTimer()` | `void` | **关键门禁：启动底层信号质量定时评估轮询线程** |
| `stopWifiQualTimer()` | `void` | **关键：停止信号质量轮询，防止后台空转耗电** |

#### 信号列表 (JQSignal)
- `wifiListChanged.connect((listJson) => {})`
- `wifiQualChanged.connect((qual) => {})`: 信号强度改变 (`0` ~ `4`)
- `internetConnectChanged.connect((ssid, isConnected) => {})`: 网络连通状态切换

### 2.4 `'network'` 通用轻量网络监听模块
若应用仅需轻量检测“是否有网”，无需操纵 Wi-Fi 硬件定时器，可直接使用内置 `'network'`：

```javascript
import network from 'network';

network.getType({
  success: (res) => { console.log('当前网络类型:', res.type); } // 'wifi' | 'none'
});

network.onStatusChange((res) => {
  console.log('网络状态改变:', res.isConnected, res.networkType);
});
```

---

## 3. 电源管理系统 (PMIC AXP2101 / CPU 调频 / 屏幕背光)

### 3.1 AXP2101 拓扑、硬件库仑计与 Sysfs 电量节点
S7 Pro 搭载 X-Powers AXP2101 高度集成可编程 PMIC：
- **物理总线**: CV1813H I2C-5（`0x0502B000`），从机地址 `0x34`，中断 IRQ 47。
- **设计电池容量**: `1020 mAh`（设备树 `pmu_battery_cap = 0x03fc`）。
- **恒流充电限流**: `800 mA`（设备树 `pmu_runtime_chgcur = 0x0320`）。
- **内核驱动节点**:
  - 剩余电量百分比: `/sys/class/power_supply/battery/capacity` (`0` ~ `100`，由 AXP2101 硬件库仑计计算)
  - 充电状态: `/sys/class/power_supply/battery/status` (`Charging`, `Discharging`, `Full`)
  - 充电器在线: `/sys/class/power_supply/ac/online` (`1` 为插入 Type-C)
  - 电池端电压: `/sys/class/power_supply/battery/voltage_now` (微伏 µV，如 `4365000` = 4.365V)
  - 电池温度: `/sys/class/power_supply/battery/temp` (摄氏度)

### 3.2 `'batteryInfo'` 模块 API 字典
由 `libjsapi_export.so` 导出：

```javascript
import batteryInfoModule from 'batteryInfo';
const battery = new batteryInfoModule.BatteryInfo();
```

- `getBatteryCapacity()`: 返回当前电量百分比 (`0` ~ `100`)
- `getBatteryStatus()`: 返回充电状态枚举（1: 充电中, 2: 放电中, 3: 充满, 4: 未接电池）
- `isCharging()`: 是否处于充电中 (`boolean`)
- `batteryInfoChange.connect((data) => {})`: 电池状态变更信号

### 3.3 CPU 1.0GHz 锁定与无 DVFS 机制
反编译内核时钟树 `/sys/kernel/debug/clk/clk_summary` 证实：
- CV1813H 核心时钟 `clk_a53` **被内核硬件时钟树严格锁死在 1.0 GHz (1,000,000,000 Hz)**。
- 设备**未启用 Linux `cpufreq` 调频子系统**，无运行时 DVFS。
- **设计初衷**：确保任何时刻提笔 OCR 扫描、图像拼接与神经网络推理拥有完全确定性的毫秒级低延迟响应。

### 3.4 屏幕背光 PWM 调制机制 (20 kHz 零啸叫与无频闪)
- **背光控制节点**: `/sys/class/backlight/backlight/brightness`
- **调节范围**: `0` ~ `255`（对应硬件 256 级灰阶阶梯，线性衰减）
- **PWM 通道**: CV1813H 硬件 PWM2 控制器（`0x03060000`）
- **PWM 周期与频率**: 周期 `50,000 ns`（50 微秒），**调制频率严格等于 20,000 Hz (20 kHz)**！
- **硬件工程意义**: 20 kHz 超出了人耳听觉极限（20 Hz ~ 20 kHz），彻底消除了便携式词典笔在低亮度 PWM 调光下陶瓷电容与电感产生的可闻音频震荡啸叫（Coil Whine），并杜绝肉眼可察觉的频闪现象。

---

## 4. 生产级实战范式与代码示例

```javascript
// 综合硬件监听服务类
export class HardwareStatusMonitor {
  constructor() {
    this.wifi = new (require('wifi').Wifi)();
    this.headset = new (require('headSetInfo').HeadSetInfo)();
    this.battery = new (require('batteryInfo').BatteryInfo)();
  }

  start() {
    // 1. 开启 Wi-Fi 信号轮询定时器
    this.wifi.startWifiQualTimer();
    this.wifi.wifiQualChanged.connect((qual) => {
      console.log('[HAL] Wi-Fi 信号格数变动:', qual);
    });

    // 2. 监听耳机外设接入
    this.headset.headsetStateChanged.connect((connected) => {
      console.log('[HAL] 耳机连入状态变动:', connected);
    });

    // 3. 监听电量变动
    this.battery.batteryInfoChange.connect(() => {
      console.log('[HAL] 当前电量:', this.battery.getBatteryCapacity(), '%');
    });
  }

  stop() {
    // 关键生命周期管理：离开页面必须停止定时器与解绑
    this.wifi.stopWifiQualTimer();
    this.wifi.wifiQualChanged.disconnect();
    this.headset.headsetStateChanged.disconnect();
    this.battery.batteryInfoChange.disconnect();
  }
}
```
