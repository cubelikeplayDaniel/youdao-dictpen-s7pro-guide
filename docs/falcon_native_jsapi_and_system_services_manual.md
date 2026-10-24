# 原生 JSAPI 与系统服务全量调用字典
## (Falcon Native C-Module JSAPI & System Services Developer Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **底层引擎**: Falcon GUI Runtime (`/usr/lib/libfalcon.so`) + QuickJS 2020-07-05 C-Module Loader  
> **反编译基准**: `_Z17register_jq_jsapiv` (地址 `0x006968a4`) 与 `libjsapi_export_core.so`

---

## 目录索引

1. [Native C 扩展模块加载原理](#1-native-c-扩展模块加载原理)
2. [数据持久化模块 (`'storage'`, `'sqlite3'`, `'fs'`)](#2-数据持久化模块)
   - [2.1 轻量 KV 键值存储: `'storage'`](#21-轻量-kv-键值存储-storage)
   - [2.2 关系型数据库引擎: `'sqlite3'`](#22-关系型数据库引擎-sqlite3)
   - [2.3 沙箱文件系统引擎: `'fs'`](#23-沙箱文件系统引擎-fs)
3. [跨进程微服务通信模块 (`'$service_proxy'`)](#3-跨进程微服务通信模块-service_proxy)
4. [网络与通信传输模块 (`'http'`, `'httpbridge'`, `'net'`, `'network'`, `'wpa'`)](#4-网络与通信传输模块)
   - [4.1 原生 HTTP 客户端: `'http'`](#41-原生-http-客户端-http)
   - [4.2 官方 HMAC 签名网络桥: `'httpbridge'`](#42-官方-hmac-签名网络桥-httpbridge)
   - [4.3 异步非阻塞 TCP 套接字: `'net'`](#43-异步非阻塞-tcp-套接字-net)
   - [4.4 网络状态监测: `'network'`](#44-网络状态监测-network)
5. [低延迟音频与硬件混音模块 (`'soundPlayer'`)](#5-低延迟音频与硬件混音模块-soundplayer)
6. [硬件抽象层 HAL 与设备控制 (`buttonEvent`, `brightness`, `volume`, `wifi`)](#6-硬件抽象层-hal-与设备控制)
   - [6.1 笔尖微动与物理按键: `'buttonEvent'`](#61-笔尖微动与物理按键-buttonevent)
   - [6.2 屏幕背光与常亮控制: `'brightness'`](#62-屏幕背光与常亮控制-brightness)
   - [6.3 系统音量控制: `'volume'`](#63-系统音量控制-volume)
   - [6.4 电池电量与电源管理: `'batteryInfo'`](#64-电池电量与电源管理-batteryinfo)
   - [6.5 Wi-Fi 硬件连接控制: `'wifi'`](#65-wi-fi-硬件连接控制-wifi)

---

## 1. Native C 扩展模块加载原理

Falcon 运行时不依赖 Node.js，深度整合了 QuickJS 的原生 C 模块加载体系。
在 `libfalcon.so` 的函数 `_Z17register_jq_jsapiv`（地址 `0x006968a4`）中，系统通过 `registerCModuleLoader` 注册了 13 个原生模块：
`"fs"`, `"path"`, `"zip"`, `"sqlite3"`, `"util"`, `"http"`, `"storage"`, `"crypto"`, `"miniapp"`, `"wpa"`, `"network"`, `"net"`, `"process"`.

此外，`/etc/miniapp/jsapis/libjsapi_export_core.so` 注册了设备控制代理：
`"global"`, `"systemInfo"`, `"headCamera"`, `"httpbridge"`, `"logmanager"`, `"lte"`, `"tel"`, `"wifi"`, `"brightness"`, `"volume"`, `"batteryInfo"`, `"buttonEvent"`.

在前端代码中直接使用标准 ES Module 语法导入即可，无需配置 npm 依赖：
```javascript
import { Database } from 'sqlite3';
import { getStorage, setStorage } from 'storage';
import fs from 'fs';
import http from 'http';
import ServiceProxy from '$service_proxy';
```

---

## 2. 数据持久化模块

### 2.1 轻量 KV 键值存储: `'storage'`
基于 Falcon C++ `JQuick::SharedPreferences` 实现（地址 `0x006c34f4`）。
- **文件存储位置**：`/userdata/miniapp/data/mini_app/pkg/<AppID>/data/storage/preferences.json`。
- **类型硬性约束**：**Key 与 Value 必须均为字符串**！对象必须先经过 `JSON.stringify()`，否则 C++ 层会抛出异常。
- **查询空键返回**：键不存在时**严格返回 `null`**（底层 sentinel `"__null__"` 会被转换为 JS `null`）。

#### 完整 API 规范
```javascript
import { getStorage, setStorage, removeStorage, getStorageKeys, clearStorage } from 'storage';

// 1. 设置键值 (异步 Promise, 必须均为 string)
await setStorage('user_setting', JSON.stringify({ volume: 10, theme: 'dark' }));

// 2. 读取键值 (不存在时返回 null)
const raw = await getStorage('user_setting');
if (raw !== null) {
  const setting = JSON.parse(raw);
  console.log('当前音量:', setting.volume);
}

// 3. 获取当前应用保存的所有键名列表
const keys = await getStorageKeys(); // 返回 ['user_setting', ...]

// 4. 删除指定键
await removeStorage('user_setting');

// 5. 清空当前应用所有存储
await clearStorage();
```

---

### 2.2 关系型数据库引擎: `'sqlite3'`
底层基于 SQLite 3.32.3 原生编译（地址 `0x006bd498`），工作于独立线程（Worker Thread），**全部方法均返回 ES6 Promise**。

#### 完整 API 规范
```javascript
import { Database } from 'sqlite3';

async function testDatabase() {
  const db = new Database();

  // 1. 打开数据库 (相对路径自动映射到 /data/mini_app/pkg/<AppID>/data/<name>.db)
  // 支持 ":memory:" 内存数据库
  await db.open('comic_history.db');

  // 2. 批量执行 DDL 语句
  await db.exec(`
    CREATE TABLE IF NOT EXISTS read_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      comic_id TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      last_page INTEGER DEFAULT 1,
      updated_at INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_comic_id ON read_history(comic_id);
  `);

  // 3. 编译预处理语句 (Prepared Statement)
  const insertStmt = await db.prepare(`
    INSERT OR REPLACE INTO read_history (comic_id, title, last_page, updated_at)
    VALUES (?, ?, ?, ?);
  `);

  // 4. 参数绑定与执行写入 (run)
  await insertStmt.bind('c_1001', '火影忍者 第一话', 42, Date.now());
  const runRes = await insertStmt.run();
  console.log('插入影响行数:', runRes.changes, 'RowID:', runRes.lastInsertRowid);
  await insertStmt.finalize(); // 必须显式释放语句

  // 5. 游标查询全部数据 (all)
  const queryStmt = await db.prepare(`
    SELECT * FROM read_history ORDER BY updated_at DESC LIMIT ?;
  `);
  await queryStmt.bind(10);
  const rows = await queryStmt.all(); // 返回对象数组 Array<Object>
  for (const item of rows) {
    console.log(`[历史记录] ${item.title} 进度: 第 ${item.last_page} 页`);
  }
  await queryStmt.finalize();

  // 6. 关闭数据库连接
  await db.close();
}
```

---

### 2.3 沙箱文件系统引擎: `'fs'`
底层由 `jq::JSFsModule` 实现（地址 `0x006a5668`），所有相对路径均受到 `jq::Sandbox` 沙箱隔离保护（位于应用私有 data 目录）。

#### 完整 API 规范
```javascript
import fs from 'fs';

// 1. 判断文件或目录是否存在
const exists = await fs.exists('cache/metadata.json');

// 2. 递归创建目录 (无需多级逐层创建)
if (!exists) {
  await fs.mkdir('cache');
}

// 3. 读取文本文件
const content = await fs.readFile('cache/metadata.json'); // 返回 UTF-8 字符串

// 4. 遍历目录文件 (支持 withFileTypes 获取文件类型)
const entries = await fs.readdir('cache', { withFileTypes: true });
for (const entry of entries) {
  if (entry.isDirectory()) {
    console.log('子目录:', entry.name);
  } else if (entry.isFile()) {
    console.log('普通文件:', entry.name);
  }
}

// 5. 获取文件详细元数据
const stat = await fs.stat('cache/metadata.json');
console.log('文件大小:', stat.blocks * 512, '修改时间:', stat.mtimeMs);

// 6. 获取磁盘空间容量
const diskInfo = await fs.statfs('/');
console.log('可用容量(字节):', diskInfo.free * diskInfo.bsize);

// 7. 删除文件或递归删除目录
await fs.rm('cache/metadata.json');
```

---

## 3. 跨进程微服务通信模块: `'$service_proxy'`

基于 Falcon C++ `falcon::JSDLink` 实现（地址 `0x537800`），支持微服务惰性冷启动与 10,000ms 事务看门狗超时监控。

#### 完整调用范式
```javascript
import ServiceProxy from '$service_proxy';

const proxy = new ServiceProxy();

// 1. 连接服务 (URI: falcon://<AppId>/<ServiceName>)
proxy.connect('falcon://8001650599023931/mediaPlayerService');

// 2. 监听连接成功与断开事件
proxy.onConnected = () => {
  console.log('[RPC] 微服务连接成功');
};

proxy.onDisconnected = () => {
  console.log('[RPC] 微服务链路断开');
};

// 3. 发送 RPC 指令 (Action, Params, Callback)
proxy.sendCommand('play', { mediaId: 'track_01' }, (code, res) => {
  if (code === 0) {
    console.log('指令执行成功:', res);
  } else {
    console.error('指令失败, 错误码:', code);
  }
});

// 4. 监听服务端主动推送的广播事件
const token = proxy.on('playStatusChange', (data) => {
  console.log('播放状态改变:', data.status);
});

// 5. 移除监听与释放连接
proxy.off('playStatusChange', token);
proxy.disconnect();
```

---

## 4. 网络与通信传输模块

### 4.1 原生 HTTP 客户端: `'http'`
```javascript
import http from 'http';

// 1. 发起 GET / POST 请求
const res = await http.request({
  url: 'https://api.example.com/data',
  method: 'GET',
  headers: { 'Accept': 'application/json' },
  timeout: 8000
});

// 2. 大文件流式下载
const downloadRes = await http.download({
  url: 'https://cdn.example.com/audio.mp3',
  filepath: '/userdisk/audio.mp3',
  timeout: 30000
});
```

---

## 5. 低延迟音频与硬件混音模块: `'soundPlayer'`

提供 `< 10ms` 物理启动延迟的本地音频播放，直接写入 ALSA 硬件环形缓冲区，支持 `quickStop()` 瞬时切断硬件 DMA 输出。

```javascript
import soundPlayerModule from 'soundPlayer';

const player = new soundPlayerModule.SoundPlayer();

// 1. 播放本地音频文件
// 参数: (filePath, offsetMs = 0, speed = 1.0, loop = false, durationMs = 0)
player.playFile('/system/media/audio/ui/click.wav', 0, 1.0, false, 0);

// 2. 瞬时停止播放 (立即清空 ALSA DMA 缓冲区，零延迟静音)
player.quickStop();
```

---

## 6. 硬件抽象层 HAL 与设备控制

### 6.1 笔尖微动与物理按键: `'buttonEvent'`
```javascript
import buttonEventModule from 'buttonEvent';

const btn = new buttonEventModule.ButtonEvent();
btn.setButtonEventReady(true);

// 监听笔尖触碰纸面 (压力微动开关触发, KEY_CAMERA)
btn.on('headButtonPress', () => {
  console.log('笔尖触底按压 (开始扫描)');
});

// 监听笔尖离开纸面
btn.on('headButtonRelese', () => {
  console.log('笔尖抬起释放 (结束扫描)');
});

// 监听实体 Home 键点击
btn.on('homeButtonClick', () => {
  console.log('实体 Home 键被点击');
});
```

### 6.2 屏幕背光与常亮控制: `'brightness'`
```javascript
import brightnessModule from 'brightness';

const brightness = new brightnessModule.Brightness();

// 1. 获取当前屏幕亮度 (范围: 10 ~ 255)
const cur = brightness.getBrightness();

// 2. 设置屏幕亮度
brightness.setBrightness(180);
```

### 6.3 系统音量控制: `'volume'`
```javascript
import volumeModule from 'volume';

const volume = new volumeModule.Volume();

// 1. 获取系统音量 (范围: 0 ~ 15)
const curVol = volume.getVolume();

// 2. 设置系统音量
volume.setVolume(10);
```

### 6.4 电池电量与电源管理: `'batteryInfo'`
```javascript
import batteryInfoModule from 'batteryInfo';

const battery = new batteryInfoModule.BatteryInfo();

// 1. 读取剩余电量百分比 (0 ~ 100)
const capacity = battery.getBatteryCapacity();

// 2. 读取是否正在充电
const isCharging = battery.isCharging();
```

### 6.5 Wi-Fi 硬件连接控制: `'wifi'`
```javascript
import wifiModule from 'wifi';

const wifi = new wifiModule.Wifi();

// 1. 判断 Wi-Fi 是否开启
const open = wifi.isOpen();

// 2. 获取 Wi-Fi 信号强度格数 (0 ~ 4)
const signal = wifi.getWifiQual();
```
