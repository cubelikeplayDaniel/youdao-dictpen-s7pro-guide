# 有道词典笔 S7 Pro 原生 TCP 网络与 WPA Wi-Fi 子系统深度逆向工程指南
## (Falcon Native TCP Net, POSIX select(2), WPA Supplicant & Network HAL Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `libfalcon.so` (`jq::JSNet`, `jq::IOPoll`, `jq::JSWpa`), `wpa_supplicant`, `libjsapi_export_core.so` (`JSWifiProxy`, `JSLteProxy`)

---

## 目录索引

1. [`"net"` 模块 (`jq::JSNet`) 底层网络 I/O 架构深度解析](#1-net-模块-jqjsnet-底层网络-io-架构深度解析)
   - 1.1 [模块注册与导出类结构 (仅 Client Socket，无 Server)](#11-模块注册与导出类结构-仅-client-socket无-server)
   - 1.2 [底层 I/O 多路复用实相：POSIX `select(2)` 核心事件循环](#12-底层-io-多路复用实相posix-select2-核心事件循环)
   - 1.3 [非阻塞连接建立与 `EINPROGRESS` 处理机制](#13-非阻塞连接建立与-einprogress-处理机制)
   - 1.4 [二进制 Buffer 读写与 ArrayBuffer 数据通道](#14-二进制-buffer-读写与-arraybuffer-数据通道)
2. [`"network"` 模块 (`jq::JSNetwork`) 与系统连通性状态感知](#2-network-模块-jqjsnetwork-与系统连通性状态感知)
   - 2.1 [导出形式与 `getStatus()` 底层 8.8.8.8:53 探活实相](#21-导出形式与-getstatus-底层-888853-探活实相)
   - 2.2 [设备全局网络分流与状态监控 (Wi-Fi / 蜂窝 / 飞行模式)](#22-设备全局网络分流与状态监控-wi-fi--蜂窝--飞行模式)
3. [`"wpa"` 模块 (`jq::JSWpa`) 底层控制与状态机通信机制](#3-wpa-模块-jqjswpa-底层控制与状态机通信机制)
   - 3.1 [UNIX Domain Socket 架构与双套接字设计 (Control & Monitor)](#31-unix-domain-socket-架构与双套接字设计-control--monitor)
   - 3.2 [`"wpa"` 模块导出与 `WpaMonitor` 类体系](#32-wpa-模块导出与-wpamonitor-类体系)
   - 3.3 [Wi-Fi 全生命周期命令流 (SCAN, ADD_NETWORK, SET_NETWORK, RECONNECT)](#33-wi-fi-全生命周期命令流)
   - 3.4 [底层 Supplicant 消息到 JS 事件的分发映射表](#34-底层-supplicant-消息到-js-事件的分发映射表)
4. [生产级 JavaScript 范例代码](#4-生产级-javascript-范例代码)
   - 4.1 [生产级 TCP Socket 通信客户端 (`DictPenSocketClient`)](#41-生产级-tcp-socket-通信客户端-dictpensocketclient)
   - 4.2 [Wi-Fi 管理与网络连通性状态监控器 (`DictPenNetworkManager`)](#42-wi-fi-管理与网络连通性状态监控器-dictpennetworkmanager)

---

## 1. `"net"` 模块 (`jq::JSNet`) 底层网络 I/O 架构深度解析

### 1.1 模块注册与导出类结构

Falcon 引擎在启动时调用 `register_jq_jsapi()`（位于 `libfalcon.so` 偏移 `0x006968a4`），通过 `registerCModuleLoader("net", 0x696390)` 将 `"net"` 注册为 QuickJS 原生 C 模块。

在加载时，模块初始化函数 `jq::net_init(jqutil_v2::JQModuleEnv*)`（`0x006b05b0`）执行以下绑定：
1. 模块导出对象通过 `JS_NewObject` 创建，并挂载于 QuickJS 模块的 `"default"` 导出名中。
2. **导出的类：仅导出 `Socket` 类**（Falcon 原生未暴露 `Server` 类，词典笔终端仅作为 TCP/UDP 客户端）。
3. 原型方法（通过 `JQFunctionTemplate::PrototypeTemplate()` 绑定）：
   - `.connect(options)`（`0x006af2f8`）：建立非阻塞连接。
   - `.send(data)`（`0x006afa34`）：发送二进制或字符串数据。
   - `.close()`（`0x006af864`）：关闭底层套接字。
4. 原型访问器（Getters）：
   - `localAddress`、`localPort`
   - `remoteAddress`、`remotePort`
5. 事件派发基类继承：
   调用 `jqutil_v2::JQPublishObject::InitTpl(tpl)`（`0x0005965c`），赋予 `Socket` 实例 `.on(eventName, handler)` 和 `.off(eventName, handler)` 事件订阅机制。

---

### 1.2 底层 I/O 多路复用实相：POSIX `select(2)` 核心事件循环

在 Linux 嵌入式上通常假定采用 `epoll`，但经逆向反汇编证实：
**Falcon 的 `jq::IOPoll` 底层并非 `epoll_create`/`epoll_wait`，而是基于 POSIX `select(2)` 的专用多路复用工作线程！**

- **核心函数**：`jq::IOPoll::_pollOnce(int timeout)`（`0x006e84d8`）
- **数据结构**：在栈与堆上分配 128 字节的 `fd_set`（即 1024 个描述符容量，匹配 glibc `__FD_SETSIZE`）。
- **线程协同与唤醒机制**：
  - `_pollOnce` 将注册的 socket fd 写入读/写 `fd_set`，并监控内部的自管道/eventfd（`m_wakeupFd`）。
  - 当主线程需要注册新 fd 或写入数据时，通过 `jq::IOPoll::_wakeupLocked()` 向 `m_wakeupFd` 发送单字节，唤醒阻塞中的 `select(2)`。
  - 线程解除阻塞后调用 `_wakeupConsumeLocked()` 清除信号，并调用 `jq::JSNet::handleIOPoll(int fd, int events, void* userData)`（`0x006aff20`）。
  - 回调结果通过 `_scheduleCallback` 投递至 QuickJS 主线程事件队列，确保 JS 单线程执行环境的内存安全。

---

### 1.3 非阻塞连接建立与 `EINPROGRESS` 处理机制

在 `jq::JSNet::connect(jqutil_v2::JQAsyncInfo&)`（`0x006af2f8`）中：
1. 解析 JS 传入的选项对象：
   - `options.host`：目标 IP 或域名（若为域名，调用 `getaddrinfo` 解析）。
   - `options.port`：目标端口（范围校验 1 - 65535）。
   - `options.type`：缺省为 `"tcp"`（使用 `SOCK_STREAM`）；若为 `"udp"` 则使用 `SOCK_DGRAM`。
2. 创建套接字：`socket(AF_INET, SOCK_STREAM, 0)`。
3. 设置非阻塞：调用 `fcntl64(fd, F_SETFL, flags | O_NONBLOCK)`。
4. 发起连接：`connect(fd, &sockaddr, sizeof(sockaddr))`。若返回 `-1` 且 `errno == EINPROGRESS`（ARM 架构常数 115），将套接字写入 `IOPoll` 的写监听集合（Write FD Set）。
5. 握手完成：当 `select` 捕获可写事件后，通过 `getsockopt(fd, SOL_SOCKET, SO_ERROR)` 确认无错误，随后触发 JS 事件 `"connect"`，并将 Promise 状态置为 Resolved。

---

### 1.4 二进制 Buffer 读写与 ArrayBuffer 数据通道

- **数据接收（Socket Read -> JS Event）**：
  1. `jq::IOPoll` 轮询到套接字有可读事件，触发 `jq::JSNet::handleIOPoll`（`0x006aff20`）。
  2. 内部开辟 4096 字节缓冲区，执行 `read(fd, buffer, 4096)`。
  3. **数据到达（`ret > 0`）**：调用 `_notifyData`（`0x006afd64`），将原生 C 字节数组封装为 `jqutil_v2::Bson`（底层通过 QuickJS 的 `JS_NewArrayBufferCopy` 创建 `ArrayBuffer` 对象），并调用 `publish("data", bson)` 触发 JS 监听函数。
  4. **远端断开（`ret == 0`）**：从 `IOPoll` 中注销 fd，并调用 `publish("disconnect", ...)`。
  5. **读取异常（`ret < 0` 且 `errno != EAGAIN`）**：调用 `publish("error", strerror(errno))`。
- **数据发送（JS Method -> Socket Write）**：
  1. 调用 `.send(data)` 时，由 `send_prepareParams`（`0x006b1584`）进行参数多态解析：
     - 若输入为 `ArrayBuffer`、`TypedArray`（如 `Uint8Array`）或 `DataView`，获取裸指针 `uint8_t*` 与字节长度。
     - 若输入为 JS `String`，提取 UTF-8 C 字符串。
  2. 调用 `jq::IOPoll::WriteFdSync(fd, data, len)` 执行同步/非阻塞写。
  3. 返回 Promise，其 resolve 结果为成功写入的实际字节数（`int`）。

---

## 2. `"network"` 模块 (`jq::JSNetwork`) 与系统连通性状态感知

### 2.1 导出形式与 `getStatus()` 底层 8.8.8.8:53 探活实相

模块注册函数 `jq::network_init`（`0x006b3ab8`）注册 `NetworkModule` 类，并通过 `JQFunctionTemplate::CallConstructor(0, nullptr)` 在加载阶段直接实例化单例，导出在 `"default"` 上。

`network` 导出的唯一核心原型方法是：
- `network.getStatus()`（`0x006b3928`）$\rightarrow$ 返回 `Promise<string>`

反汇编表明，`getStatus` 的底层实现为真实网络主动探测：
1. 调用 `jq::check_internet_connection()`（`0x006b36fc`）。
2. 该函数通过 `getaddrinfo` 解析节点 `"8.8.8.8"`，服务端口 `"53"`（DNS 常用端口）。
3. 创建非阻塞 TCP 套接字 `socket(AF_INET, SOCK_STREAM, 0)` 并设置 `O_NONBLOCK`。
4. 发起 `connect`，并调用 `select(fd + 1, NULL, &wset, NULL, &timeout)`，其中超时参数设定为：
   - `tv_sec = 5`（5 秒超时）
   - `tv_usec = 0`
5. 通过 `getsockopt(SOL_SOCKET, SO_ERROR)` 检测握手状态。
6. **返回值映射**：
   - 探测成功（返回 0）：Promise resolve 为字符串常量 `"connect"`（位于 `0x744744`）。
   - 探测失败（返回非 0）：Promise resolve 为字符串常量 `"disconnect"`（位于 `0x72f284`）。

---

### 2.2 设备全局网络分流与状态监控 (Wi-Fi / 蜂窝 / 飞行模式)

在有道词典笔 S7 Pro 架构中，精细化的网络链路状态由服务总线及 `/etc/miniapp/jsapis/libjsapi_export_core.so`（依托 `/oem/YoudaoDictPen/output/libs/libyddal_business_core.so`）统一管理：

- **Wi-Fi 服务代理（`JSWifiProxy` / `YDALAPI::YWifiModule`）**：
  - 状态查询：`isOpen()`、`isConnected()`、`getState()`、`getIP()`、`getWifiQual()`。
  - 信号（Signal）派发：
    - `onWifiStatusChanged(bool)`：Wi-Fi 网卡启停通知。
    - `onInternetConnectChanged(string ssid, bool isConnected)`：连通性变更。
    - `onWifiQualChanged(string qual)`：RSSI 信号质量变动。
- **蜂窝 LTE 服务代理（`JSLteProxy`）**：
  - 状态与 SIM 识别：`getStatus()`、`getLteImei()`、`getIccid()`、`getLteProvider()`、`getLteQual()`。
  - 飞行模式控制：`entryAirplaneMode()`、`exitAirplaneMode()`。
  - 信号派发：`onLteStatusChanged(int)`、`onLteQualChanged(int)`。
- **电话通信服务代理（`JSTelProxy`）**：
  - 网络接入制式查询：`getTelNetWorkType()`。

---

## 3. `"wpa"` 模块 (`jq::JSWpa`) 底层控制与状态机通信机制

### 3.1 UNIX Domain Socket 架构与双套接字设计 (Control & Monitor)

词典笔的 Wi-Fi 芯片通过后台守护进程 `wpa_supplicant` 管理，其控制接口套接字路径位于：
`/var/run/wpa_supplicant/wlan0`

`libfalcon.so` 的 `wpa::wifi_connect_to_supplicant(char const* iface)`（`0x006e92d8`）建立了**双 UNIX Domain Datagram Socket**：
1. **控制通道（Control Socket）**：
   - 调用 `wpa_ctrl_open2(path, "/tmp")`。
   - 创建 `AF_UNIX` 数据报套接字（`SOCK_DGRAM`），本地绑定路径格式为 `/tmp/wpa_ctrl_<pid>-<counter>`。
   - `connect` 到 `/var/run/wpa_supplicant/wlan0`。
   - 用于应用层发起同步请求（Request/Reply 事务），操作期间受 `pthread_mutex` 互斥保护。
2. **监听通道（Monitor Socket）**：
   - 再次调用 `wpa_ctrl_open2` 创建第二个独立的 UNIX 域套接字。
   - 调用 `wpa_ctrl_attach(monitor_conn)`（向 supplicant 发送 `"ATTACH"` 命令）。
   - 创建 `socketpair(AF_UNIX, SOCK_STREAM, 0, exit_sockets)` 作为中断唤醒管道。
   - 在专用监听线程中，通过 `wpa::wifi_wait_for_event`（`0x006e9468`）在 `select(2)` 中同时等待 `monitor_conn` 和 `exit_sockets[0]`。
   - 一旦收到 supplicant 的主动广播通知，立即通过 `wpa_ctrl_recv` 接收。

---

### 3.2 `"wpa"` 模块导出与 `WpaMonitor` 类体系

`jq::wpa_init`（`0x006c5880`）向 JS 运行环境导出了三个实体：
1. **`WpaMonitor` 类**：构造函数接收网卡名（如 `new WpaMonitor("wlan0")`）。
   - 继承自 `jqutil_v2::JQPublishObject`，提供 `.on(event, handler)`、`.off(event, handler)`。
   - 原型方法：`.doCommand(cmd)`（异步 Promise，向 supplicant 直接发送控制字串并返回响应文本）。
2. **`startWpaMonitorManager(iface)`**：启动全局监听循环线程。
3. **`stopWpaMonitorManager()`**：注销监听并释放线程资源。

---

### 3.3 Wi-Fi 全生命周期命令流

第三方 JS 应用通过 `monitor.doCommand(string)` 可以直接驱动 `wpa_supplicant` 协议栈：

1. **触发扫描与等待**：
   - 执行：`await monitor.doCommand("SCAN")`（Supplicant 返回 `"OK"`）。
   - 监听事件：等待 `SCAN_RESULTS_EVENT` 广播。
2. **获取与解析扫描结果**：
   - 执行：`await monitor.doCommand("SCAN_RESULTS")`。
   - Supplicant 返回制表符分隔的纯文本表格：
     ```text
     bssid / frequency / signal level / flags / ssid
     34:ce:00:11:22:33	2412	-48	[WPA2-PSK-CCMP][ESS]	MyHomeWifi
     ```
3. **创建网络配置块（Network Block）**：
   - 执行：`const netId = (await monitor.doCommand("ADD_NETWORK")).trim();`（例如返回 `"0"`）。
4. **注入 PSK 密码与凭证**：
   - 设置 SSID：`await monitor.doCommand('SET_NETWORK ' + netId + ' ssid "MyHomeWifi"')`。
   - 配置 WPA-PSK 密钥：`await monitor.doCommand('SET_NETWORK ' + netId + ' psk "SecretPass123"')`。
   - 若为开放未加密 Wi-Fi：`await monitor.doCommand('SET_NETWORK ' + netId + ' key_mgmt NONE')`。
5. **使能与发起关联**：
   - 选择该网络：`await monitor.doCommand('SELECT_NETWORK ' + netId)`。
   - 启用网络：`await monitor.doCommand('ENABLE_NETWORK ' + netId)`。
   - 触发重连：`await monitor.doCommand("RECONNECT")`。
   - 持久化配置：`await monitor.doCommand("SAVE_CONFIG")`。

---

### 3.4 底层 Supplicant 消息到 JS 事件的分发映射表

| 底层 Supplicant 消息特征 | 派发的 JS 事件名称 | 典型携带数据 / 业务意义 |
| :--- | :--- | :--- |
| `CTRL-EVENT-SCAN-RESULTS` | `SCAN_RESULTS_EVENT` | AP 扫描完成，可立即提取列表 |
| `CTRL-EVENT-CONNECTED` | `NETWORK_CONNECTION_EVENT` | 链路层握手完成，BSSID 与网络 ID |
| `CTRL-EVENT-DISCONNECTED` | `NETWORK_DISCONNECTION_EVENT` | Wi-Fi 掉线或断开，携带 reason 码 |
| `CTRL-EVENT-STATE-CHANGE` | `SUPPLICANT_STATE_CHANGE_EVENT` | 状态机跃迁（SCANNING/ASSOCIATING/COMPLETED） |
| `pre-shared key may be incorrect` / `CTRL-EVENT-EAP-FAILURE` | `AUTHENTICATION_FAILURE_EVENT` | WPA PSK 密码错误或鉴权失败 |
| `CTRL-EVENT-ASSOC-REJECT` | `ASSOCIATION_REJECTION_EVENT` | 路由器拒绝连接 |
| `CTRL-EVENT-TERMINATING` | `SUP_DISCONNECTION_EVENT` | wpa_supplicant 进程终止 |

---

## 4. 生产级 JavaScript 范例代码

### 4.1 生产级 TCP Socket 通信客户端 (`DictPenSocketClient`)

```javascript
import net from 'net';

export class DictPenSocketClient {
  constructor(host, port) {
    this.host = host;
    this.port = port;
    this.socket = null;
    this.isConnected = false;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
  }

  async connect() {
    try {
      this.cleanup();
      this.socket = new net.Socket({
        host: this.host,
        port: this.port,
        type: 'tcp'
      });
      this.bindEvents();
      await this.socket.connect();
    } catch (err) {
      console.error('[TCP] Connection failed:', err);
      this.scheduleReconnect();
    }
  }

  bindEvents() {
    if (!this.socket) return;

    this.socket.on('connect', () => {
      this.isConnected = true;
      console.log(`[TCP] Connected: ${this.socket.remoteAddress}:${this.socket.remotePort}`);
      this.startHeartbeat();
    });

    this.socket.on('data', (arrayBuffer) => {
      const bytes = new Uint8Array(arrayBuffer);
      console.log(`[TCP] Received ${bytes.byteLength} bytes.`);
    });

    this.socket.on('disconnect', () => {
      this.handleClose();
    });

    this.socket.on('error', (err) => {
      console.error('[TCP] Socket error:', err);
      this.handleClose();
    });
  }

  async send(payload) {
    if (!this.isConnected || !this.socket) {
      throw new Error('[TCP] Socket not connected');
    }
    return await this.socket.send(payload);
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(async () => {
      if (!this.isConnected) return;
      try {
        await this.send(JSON.stringify({ type: 'PING', ts: Date.now() }));
      } catch (_) {}
    }, 15000);
  }

  stopHeartbeat() {
    if (this.heartbeatTimer) clearInterval(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  handleClose() {
    this.isConnected = false;
    this.stopHeartbeat();
    this.cleanup();
    this.scheduleReconnect();
  }

  scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, 5000);
  }

  cleanup() {
    if (this.socket) {
      try { this.socket.close(); } catch (_) {}
      this.socket = null;
    }
  }
}
```

---

### 4.2 Wi-Fi 管理与网络连通性状态监控器 (`DictPenNetworkManager`)

```javascript
import wpa from 'wpa';
import network from 'network';

export class DictPenNetworkManager {
  constructor(iface = 'wlan0') {
    this.iface = iface;
    this.wpaMonitor = null;
  }

  async init() {
    wpa.startWpaMonitorManager(this.iface);
    this.wpaMonitor = new wpa.WpaMonitor(this.iface);

    this.wpaMonitor.on('SCAN_RESULTS_EVENT', async () => {
      const apList = await this.getScanResults();
      console.log(`[WPA] Discovered ${apList.length} APs.`);
    });

    this.wpaMonitor.on('NETWORK_CONNECTION_EVENT', async () => {
      const hasInternet = await this.verifyInternetStatus();
      console.log('[WPA] Link connected, Internet verified:', hasInternet);
    });

    this.wpaMonitor.on('AUTHENTICATION_FAILURE_EVENT', () => {
      console.error('[WPA] Wi-Fi password incorrect!');
    });
  }

  async triggerScan() {
    return await this.wpaMonitor.doCommand('SCAN');
  }

  async getScanResults() {
    const raw = await this.wpaMonitor.doCommand('SCAN_RESULTS');
    const lines = raw.split('\n');
    const apList = [];
    for (let i = 1; i < lines.length; i++) {
      const parts = lines[i].trim().split('\t');
      if (parts.length >= 5) {
        apList.push({
          bssid: parts[0],
          frequency: parseInt(parts[1], 10),
          rssi: parseInt(parts[2], 10),
          flags: parts[3],
          ssid: parts[4]
        });
      }
    }
    return apList;
  }

  async connectToWifi(ssid, password = '') {
    const netId = (await this.wpaMonitor.doCommand('ADD_NETWORK')).trim();
    await this.wpaMonitor.doCommand(`SET_NETWORK ${netId} ssid "${ssid}"`);
    if (password && password.length >= 8) {
      await this.wpaMonitor.doCommand(`SET_NETWORK ${netId} psk "${password}"`);
    } else {
      await this.wpaMonitor.doCommand(`SET_NETWORK ${netId} key_mgmt NONE`);
    }
    await this.wpaMonitor.doCommand(`SELECT_NETWORK ${netId}`);
    await this.wpaMonitor.doCommand(`ENABLE_NETWORK ${netId}`);
    await this.wpaMonitor.doCommand('RECONNECT');
    await this.wpaMonitor.doCommand('SAVE_CONFIG');
  }

  async verifyInternetStatus() {
    try {
      const status = await network.getStatus();
      return status === 'connect';
    } catch (_) {
      return false;
    }
  }

  destroy() {
    if (this.wpaMonitor) {
      wpa.stopWpaMonitorManager();
      this.wpaMonitor = null;
    }
  }
}
```
