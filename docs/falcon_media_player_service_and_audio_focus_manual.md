# 网易有道词典笔 S7 Pro 媒体播放服务与音频系统逆向分析技术手册
## (NetEase Youdao Dictionary Pen S7 Pro: Media Player Service & Audio Pipeline Engineering Manual)

> **适用固件**: Youdao OS 4.22.0+ (设备型号: `YDPS7-2`, 平台代码: `VY08` / `melonpro`)  
> **核心芯片**: Cvitek CV1813 Dual-Core ARM Cortex-A53 / A7 @ 1.0GHz (嵌入式 Linux Buildroot 5.10.4 内核)  
> **核心产物**:  
> - `/userdata/miniapp/data/mini_app/pkg/8001650599023931` (`mediaPlayerService` 系统服务)  
> - `/usr/lib/libfalcon.so` (Falcon IPC 总线与 QuickJS C-Module 运行时)  
> - `/etc/miniapp/jsapis/libjsapi_export_core.so` (HAL 导出层与音频硬件抽象)  
> - `/etc/asound.conf.VY08` & `/etc/asound.state.y08` (ALSA 音频驱动路由)

---

## 目录索引

1. [系统架构与二进制拓扑](#1-系统架构与二进制拓扑)
2. [Falcon IPC 通信协议与 DLink 机制](#2-falcon-ipc-通信协议与-dlink-机制)
   - 2.1 [寻址 Schema 规范](#21-寻址-schema-规范)
   - 2.2 [灾难恢复与断线热重连](#22-灾难恢复与断线热重连)
   - 2.3 [防抖调度机制 (Debounce Timer)](#23-防抖调度机制-debounce-timer)
3. [全量 RPC 方法、参数及返回值规范](#3-全量-rpc-方法参数及返回值规范)
   - 3.1 [完整 RPC 方法索引字典 (37 个指令)](#31-完整-rpc-方法索引字典-37-个指令)
   - 3.2 [关键 Payload 结构 Schema](#32-关键-payload-结构-schema)
   - 3.3 [音频解码格式支持矩阵](#33-音频解码格式支持矩阵)
4. [广播事件契约与数据载荷](#4-广播事件契约与数据载荷)
   - 4.1 [广播事件全集与 Payload 定义](#41-广播事件全集与-payload-定义)
   - 4.2 [核心状态枚举常量](#42-核心状态枚举常量)
   - 4.3 [系统错误码规范](#43-系统错误码规范)
5. [音频焦点模型与 ALSA DAC 硬件竞争仲裁](#5-音频焦点模型与-alsa-dac-硬件竞争仲裁)
   - 5.1 [物理通路拓扑与 ALSA 约束](#51-物理通路拓扑与-alsa-约束)
   - 5.2 [互斥锁 `_soundplayer_mutex` 逆向证据](#52-互斥锁-_soundplayer_mutex-逆向证据)
   - 5.3 [音频优先级金字塔与焦点抢占机制](#53-音频优先级金字塔与焦点抢占机制)
6. [反向提供者契约 (Reverse Provider Contract)](#6-反向提供者契约-reverse-provider-contract)
   - 6.1 [核心防错铁律：`cb([0, data])`](#61-核心防错铁律cb0-data)
7. [生产级 JavaScript 完整封装 (`ProductionMediaPlayerClient`)](#7-生产级-javascript-完整封装-productionmediaplayerclient)
8. [调试与逆向验证指南](#8-调试与逆向验证指南)

---

## 1. 系统架构与二进制拓扑

有道词典笔 S7 Pro 运行基于 Buildroot 定制的轻量级 Linux 操作系统，整个用户态交互基于 Falcon GUI 引擎与 QuickJS 字节码解释器。系统针对 128MB RAM 极度受限环境采用了**微服务化解耦架构**：前台 MiniApp 与后台持久服务之间通过 UNIX Domain Socket + DLink 路由实现 RPC 隔离。

```
+-----------------------------------------------------------------------------------------+
| 前台微应用进程 (MiniApp / Dictionary UI / Reader)                                           |
|   - 引入客户端 SDK: import ServiceProxy from '$service_proxy'                            |
|   - 状态追踪与防抖队列: MediaPlayerService (100ms Debounce Timer)                           |
+-----------------------------------------------------------------------------------------+
                                           |  ^
                      UNIX Domain Sockets  |  |  RPC 指令 (sendCommand) / 广播事件 (on)
                     /var/run/miniapp-*    v  |
+-----------------------------------------------------------------------------------------+
| Falcon IPC 内核总线 (/usr/lib/libfalcon.so)                                              |
|   - 命名空间解析: falcon::ParseFalconSchema ("falcon://<AppID>/<ServiceName>")          |
|   - 跨进程端点抽象: falcon::JSDLink / JQuick::DLinkManager                                |
|   - 进程生命周期看门狗: falcon::ServiceStack (支持冷启动、崩溃自动拉起与事件广播)             |
+-----------------------------------------------------------------------------------------+
         |                                                                |
         v                                                                v
+------------------------------------------+    +-----------------------------------------+
| 后台媒体服务进程 (AppID: 8001650599023931)|    | 硬件抽象导出层 (/usr/lib/libjsapi_export_core.so)|
|   - 守护进程: mediaPlayerService          |    |   - JSSoundPlayerProxy (UI 音效/TTS 播放)  |
|   - 播放列表与反向提供者调度协议          |    |   - 硬件互斥量: _soundplayer_mutex        |
|   - 持有系统电源唤醒锁 (WakeLock)         |    |     (BSS 地址: 0x000ef730, GOT: 0xeee50) |
+------------------------------------------+    +-----------------------------------------+
         |                                                                |
         +--------------------------------+-------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------------+
| 低延迟音效守护与 IPC 通道                                                                 |
|   - 守护进程: /usr/bin/runSoundPlayer -> /oem/YoudaoDictPen/output/SoundPlayer          |
|   - 进程间共享内存: /userdata/shm/Miniapp2SoundRecord, /userdata/shm/SoundRecord2Miniapp  |
|   - 硬件同步信号量: /dev/shm/sem.SoundPlayerSemRead, /dev/shm/sem.SoundPlayerSemWrite   |
+-----------------------------------------------------------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------------+
| Linux ALSA 音频子系统 (/etc/asound.conf.VY08 & /usr/lib/libasound.so.2)                  |
|   - 逻辑输出设备: speaker -> spk_softvol (0~100 软件衰减增益)                             |
|   - 物理输出 DAC: hw:1,0 (Cvitek CV1813 SoC I2S Controller)                             |
|   - 微型功放芯片: AW883XX SmartPA (I2C 控制总线, 动态防破音与升压驱动)                   |
|   - 录音采集通路: softvol_cap -> hw:0,0 (48kHz, 16-bit Mono/Stereo PCM)                |
+-----------------------------------------------------------------------------------------+
```

---

## 2. Falcon IPC 通信协议与 DLink 机制

### 2.1 寻址 Schema 规范
客户端与微服务间通过 URI 进行唯一寻址，规范如下：
```text
falcon://<TargetAppId>/<ServiceName>
```
- **媒体播放服务 URI**: `falcon://8001650599023931/mediaPlayerService`
- **解析函数**: 在 `/usr/lib/libfalcon.so` 中由 `falcon::ParseFalconSchema(char const*, falcon::FalconUri&)` 解析。若检测到目标端点尚未注册，DLink 触发 `falcon::ServiceStack::instance()` 执行该 AppID 对应后台进程的惰性冷启动（Lazy Spawning）。

### 2.2 灾难恢复与断线热重连
在官方 `mediaPlayerService-54347d20.js.bin` 逆向分析中，SDK 实现了完整的生命周期监听机制，利用底层包管理服务（Package Manager, `pm`）避免服务由于 OOM 崩溃后客户端死锁：

```javascript
init() {
  if (!this.mediaplayer_service_proxy) {
    this.tokenSet = new Set();
    this.mediaplayer_service_proxy = new ServiceProxy();
  }
  if (this.initialized !== true) {
    this.mediaplayer_service_proxy.onConnected = () => {
      console.log('mediaPlayerService.js === init -> onConnected()');
      pm.off(this.pmToken);
    };
    this.mediaplayer_service_proxy.onDisconnected = () => {
      console.log('mediaPlayerService.js === init -> onDisconnected()');
      this.initialized = false;
    };
    this.pmToken = pm.on('package', (res) => {
      if (res.info.appid === '8001650599023931' && res.type === 'installed') {
        console.warn('mediaPlayerService: package installed!!!');
        this.connect();
      }
    });
    this.connect();
    this.initialized = true;
  }
}
```

### 2.3 防抖调度机制 (Debounce Timer)
高频切歌或点击可能导致微服务与底层的音频解码器产生线程死锁。官方 SDK 在 `playAlbum` 方法上设置了 100ms 定时防抖机制：
```javascript
playAlbum(playInfo, playOptions, cb) {
  this.init();
  if (cb) { cb(true); }
  if (this.playAlbumTimer) {
    clearTimeout(this.playAlbumTimer);
  }
  this.playAlbumTimer = setTimeout(() => {
    this.mediaplayer_service_proxy.sendCommand('playAlbum', {
      playInfo: playInfo,
      playOptions: playOptions
    }, (errCode, res) => {});
  }, 100);
}
```

---

## 3. 全量 RPC 方法、参数及返回值规范

`mediaPlayerService` 通过 `$service_proxy` 对外暴露 **37 个控制与查询指令**。系统设计遵循“主动查询 / 广播触发”双模态设计：调用查询方法时若传入 Callback 则同步等待应答；若不传入 Callback，则触发对应的 `notify*` 广播事件。

### 3.1 完整 RPC 方法索引字典

| 方法名 (Action) | 输入参数 Schema | 回调参数 (code, res) / 返回值 | 语义与底层行为 |
| :--- | :--- | :--- | :--- |
| `init()` | 无 | 无 | 实例化 `ServiceProxy` 并挂载 `pm` 看门狗 |
| `connect()` | 无 | 无 | 连接 `falcon://8001650599023931/mediaPlayerService` |
| `disconnect()` | 无 | 无 | 清理全部事件 Token 并调用底层断开连接 |
| `playAlbum` | `{ playInfo: Object, playOptions: Object }` | `(code: number, res: Object)` | 注册播放上下文、播放列表并启动连续播放 |
| `loadRecentPlayList` | `{ requestInfo: Object }` | `(code: number, res: Object)` | 加载本地最近播放历史记录 |
| `play` | `{}` | `(code: number, res: Object)` | 恢复暂停中的媒体或从头播放当前项目 |
| `pause` | `{}` | `(code: number, res: Object)` | 暂停当前流解码，保持 ALSA 设备句柄处于挂起态 |
| `stop` | `{}` | `(code: number, res: Object)` | 彻底终止播放，释放解码资源与声卡占用 |
| `playNext` | `{}` | `(code: number, res: Object)` | 步进至下一首（根据循环模式决定） |
| `playPrev` | `{}` | `(code: number, res: Object)` | 步退至上一首（根据循环模式决定） |
| `playNextLrc` | `{}` | `(code: number, res: Object)` | 依据当前歌词时间轴跳跃至下一句歌词时间戳 |
| `playPrevLrc` | `{}` | `(code: number, res: Object)` | 依据当前歌词时间轴跳跃至上一句歌词时间戳 |
| `getPlayState` | `{}` (可选回调) | `(code: number, res: { playState: number })` | 双模方法：有回调返回当前状态；无回调派发 `notifyPlayState` |
| `getIsPlaying` | `{}` | `(code: number, res: { isPlaying: boolean })` | 查询解码器是否处于激活播放状态 |
| `getIsAiSoundOpened`| `{}` | `(code: number, res: { isOpen: boolean })` | 查询智能语音降噪/人声增强音效开关 |
| `resetPlayer` | `{}` | `(code: number, res: Object)` | 硬件管线硬重置，清空待播缓冲队列与歌词缓存 |
| `getCurrentMedia` | `{}` (可选回调) | `(code: number, res: Object)` | 双模方法：查询或派发 `currentMediaChanged` |
| `getCurrentAlbum` | `{}` (可选回调) | `(code: number, res: Object)` | 双模方法：查询或派发 `currentAlbumChanged` |
| `getCurrentDuration`| `{}` (可选回调) | `(code: number, res: number)` | 双模方法：获取当前音频总时长 (毫秒) |
| `getCurrentPos` | `{}` (可选回调) | `(code: number, res: number)` | 双模方法：获取当前播放游标位置 (毫秒) |
| `getCurrentProgress`| `{}` (可选回调) | `(code: number, res: number)` | 双模方法：获取播放进度浮点比率 (0.0 ~ 1.0) |
| `changePlayCycleMode`| `mode: number` | `(code: number, res: Object)` | 切换循环模式 (Order / Random / Single / Cycle) |
| `addCurrentToFavorite`| `{}` | `(code: number, res: Object)` | 将当前 `mediaId` 写入系统音频收藏夹 SQLite 数据库 |
| `removeCurrentFromFavorite`| `{}` | `(code: number, res: Object)` | 从收藏夹中移除当前媒体条目 |
| `getIsMp4File` | `{}` | `(code: number, res: { isMp4: boolean })` | 检测当前流是否为 MP4 容器封装 |
| `getSubtitleContent`| `{}` (可选回调) | `(code: number, res: Object)` | 双模方法：获取解析后的 LRC/SRT 结构化歌词数据 |
| `getCustomPlayOptions`| `{}` (可选回调) | `(code: number, res: Object)` | 双模方法：获取当前均衡器、倍速等自定义属性 |
| `showMediaPlayer` | `params: Object` | `(code: number, res: Object)` | 唤起系统全局全屏播放器界面 |
| `showPlayerGuide` | `params: Object` | `(code: number, res: Object)` | 弹出播放器手势与按键操作新手引导 |
| `notifyCurrentSubtitleIndex`| `{}` | 无 | 触发服务端立即重发当前歌词索引广播 |
| `notifySubtitleStatus`| `{}` | 无 | 触发服务端重新广播歌词展示开/关状态 |
| `notifySubtitleLoadStatus`| `{}` | 无 | 触发服务端重新广播歌词文件载入状态 |
| `notifySubtitleContent`| `{}` | 无 | 触发服务端重新全量广播已缓存歌词文本 |
| `notifyCustomPlayOptions`| `{}` | 无 | 触发服务端重新广播用户定制播放项 |
| `notifyPlayState` | `{}` | 无 | 触发广播当前 `playStateChanged` |
| `notifyCurrentAlbum`| `{}` | 无 | 触发广播当前 `currentAlbumChanged` |
| `notifyCurrentMedia`| `{}` | 无 | 触发广播当前 `currentMediaChanged` |
| `notifyCurrentDuration`| `{}` | 无 | 触发广播当前 `duration` |
| `notifyCurrentPos` | `{}` | 无 | 触发广播当前 `position` |
| `notifyCurrentProgress`| `{}` | 无 | 触发广播当前 `progress` |
| `getProxy()` | 无 | `ServiceProxy` 实例 | 返回底层的 Falcon JSDLink 代理对象 |

---

### 3.2 关键 Payload 结构 Schema

```typescript
interface PlayInfoPayload {
  provider_info: {
    provider_name: string;        // 提供者唯一标识，如 "MyCustomAudioList"
    provider_path: string;        // 反向 RPC 路径: "falcon://<AppId>/<ProviderName>"
  };
  album_info: {
    albumId: string;              // 专辑/列表唯一 ID
    albumName?: string;           // 列表展示标题
    mediaCount: number;           // 列表内音频总数
    coverUrl?: string;            // 封面图片绝对路径或网络 URL
  };
  media_info: {
    mediaId: string;              // 当前待播条目唯一 ID
    title: string;                // 音频名称
    artist?: string;              // 创作者
    url: string;                  // 音频资源路径 (本地: /userdisk/..., 网络: http(s)://...)
    duration?: number;            // 预估时长 (ms)
    lrcUrl?: string;              // 关联 LRC 歌词路径
  };
}

interface PlayOptionsPayload {
  cycleMode: number;              // 播放模式: 28 (顺序), 29 (随机), 30 (单曲), 31 (单曲循环), 32 (列表循环)
  autoPlay: boolean;              // 载入完成后是否自动启动解码
  startPosition?: number;         // 起始播放进度偏移量 (ms)
  playbackRate?: number;          // 倍速播放: 0.5 ~ 2.0 (默认 1.0)
}
```

---

## 4. 广播事件契约与数据载荷

### 4.1 核心状态枚举常量

#### 播放状态 (`PlayAction`)
- `Started`: `18` (音频解码启动并向 ALSA DMA 推送流)
- `Stopped`: `19` (播放停止，音频设备句柄释放)
- `Paused`: `20` (播放暂停，解码器挂起)
- `Completed`: `21` (当前音频自然播放到达末尾)
- `Progress`: `27` (心跳式播放进度汇报)

#### 循环模式 (`MediaCycleMode`)
- `Order`: `28` (列表顺序播放，最后一条播完后终止)
- `Random`: `29` (列表内随机挑选乱序播放)
- `Single`: `30` (单曲播放一次即停)
- `One_Shot`: `31` (单曲无限循环播放)
- `Order_Cycle`: `32` (列表无限循环)

---

## 5. 音频焦点模型与 ALSA DAC 硬件竞争仲裁

### 5.1 物理通路拓扑与 ALSA 约束
Cvitek CV1813H SoC 硬件上仅具备一个物理立体声 DAC 输出通道，且 Linux 内核在未启用 `dmix` 时，其硬件 PCM 节点 `/dev/snd/pcmC1D0p` **具有独占性**。任何对声卡的直接 `open()` 系统调用在已被占用时均会立即返回 `-EBUSY (Device or resource busy)`。

### 5.2 互斥锁 `_soundplayer_mutex` 逆向证据
通过对 `/etc/miniapp/jsapis/libjsapi_export_core.so` 反编译，定位到全局互斥锁：
- **符号名称**: `_soundplayer_mutex`
- **BSS 段地址**: `0x000ef730`
- **保护范围**: `JSSoundPlayerProxy::playFile`, `playTts`, `playStreamTts`, `quickStop`。

### 5.3 音频优先级金字塔与焦点抢占机制

```
       ▲  [优先级 1] 低延迟即时音效 (UI Sound / Scan Beep / Key Click)
      / \   - 通过 'soundPlayer' 模块调用
     /   \  - 延迟 < 10ms，具备硬件 DMA 强行打断能力 (quickStop)
    /     \
   /       \ [优先级 2] 离线/在线语音合成 (TTS Pronunciation)
  /         \ - 词典查词发音、整句翻译朗读
 /           \ - 独占持有 _soundplayer_mutex
/             \
+---------------+ [优先级 3] 后台长音频流 (mediaPlayerService)
                  - 英文听力、课本音频、音乐播放
                  - 跨进程 Falcon IPC 调度，主动避让抢占
```

---

## 6. 反向提供者契约 (Reverse Provider Contract)

### 6.1 核心防错铁律：`cb([0, data])`
在 MiniApp 中通过 `$falcon.registerProvider` 注册数据钩子时，必须严格遵守两元数组包装原则：
- **`arg[0] = 0`**: 状态标识码，0 代表数据成功取得。
- **`arg[1] = data`**: 真实的媒体元数据对象。

若错误地直接传入 `cb(data)`，Falcon 底层解析器会将对象直接按类型转换为非零错误码，微服务将判定数据提取失败，抛出 `MediaStatus.Unknown (ErrorCode: 9)` 异常并中断播放流程！

---

## 7. 生产级 JavaScript 完整封装

```javascript
import ServiceProxy from '$service_proxy';

export const PlayState = {
  STARTED: 18,
  STOPPED: 19,
  PAUSED: 20,
  COMPLETED: 21,
  PROGRESS: 27
};

export const CycleMode = {
  ORDER: 28,
  RANDOM: 29,
  SINGLE: 30,
  ONE_SHOT: 31,
  ORDER_CYCLE: 32
};

export class ProductionMediaPlayerClient {
  constructor(appId) {
    this.appId = appId || '8080999900000001';
    this.proxy = null;
    this.initialized = false;
    this.playAlbumTimer = null;
    this.tokenSet = new Set();
    this.playlist = [];
    this.currentIndex = 0;
    this.providerName = 'GlobalMediaListProvider';
  }

  init() {
    if (this.initialized && this.proxy && this.proxy.isConnected()) return;

    if (!this.proxy) {
      this.proxy = new ServiceProxy();
    }

    this.proxy.onConnected = () => {
      console.log('[MediaPlayer] Falcon IPC connected successfully.');
    };

    this.proxy.onDisconnected = () => {
      console.warn('[MediaPlayer] Falcon IPC link dropped.');
      this.initialized = false;
    };

    this.connect();
    this._registerReverseProvider();
    this.initialized = true;
  }

  connect() {
    if (this.proxy && !this.proxy.isConnected()) {
      this.proxy.connect('falcon://8001650599023931/mediaPlayerService');
    }
  }

  _registerReverseProvider() {
    if (typeof $falcon !== 'undefined' && $falcon.registerProvider) {
      $falcon.registerProvider(this.providerName, {
        onCommand: (action, params, cb) => {
          switch (action) {
            case 'getProviderType':
              return cb && cb(0, 'mediaplayer_list');

            case 'loadMedia': {
              const current = this.playlist[this.currentIndex];
              if (!current) return cb && cb(-1, 'No media');
              return cb && cb([0, {
                mediaId: String(current.id),
                title: current.title,
                url: current.url,
                duration: current.duration || 0
              }]);
            }

            case 'next': {
              if (this.playlist.length === 0) return cb && cb(-1, 'Empty list');
              this.currentIndex = (this.currentIndex + 1) % this.playlist.length;
              const nextTrack = this.playlist[this.currentIndex];
              return cb && cb([0, {
                mediaId: String(nextTrack.id),
                title: nextTrack.title,
                url: nextTrack.url,
                duration: nextTrack.duration || 0
              }]);
            }

            case 'prev': {
              if (this.playlist.length === 0) return cb && cb(-1, 'Empty list');
              this.currentIndex = (this.currentIndex - 1 + this.playlist.length) % this.playlist.length;
              const prevTrack = this.playlist[this.currentIndex];
              return cb && cb([0, {
                mediaId: String(prevTrack.id),
                title: prevTrack.title,
                url: prevTrack.url,
                duration: prevTrack.duration || 0
              }]);
            }

            default:
              return cb && cb(-1, `Action ${action} unsupported`);
          }
        }
      });
    }
  }

  playPlaylist(tracks, startIndex = 0, cycleMode = CycleMode.ORDER_CYCLE) {
    this.init();
    if (!tracks || tracks.length === 0) throw new Error('Empty playlist');

    this.playlist = tracks;
    this.currentIndex = Math.min(Math.max(0, startIndex), tracks.length - 1);
    const initialTrack = this.playlist[this.currentIndex];

    const playInfo = {
      provider_info: {
        provider_name: this.providerName,
        provider_path: `falcon://${this.appId}/${this.providerName}`
      },
      album_info: {
        albumId: `album_${Date.now()}`,
        mediaCount: tracks.length
      },
      media_info: {
        mediaId: String(initialTrack.id),
        title: initialTrack.title,
        url: initialTrack.url,
        duration: initialTrack.duration || 0
      }
    };

    const playOptions = {
      cycleMode: cycleMode,
      autoPlay: true,
      startPosition: 0
    };

    if (this.playAlbumTimer) clearTimeout(this.playAlbumTimer);

    return new Promise((resolve, reject) => {
      this.playAlbumTimer = setTimeout(() => {
        this.proxy.sendCommand('playAlbum', {
          playInfo: playInfo,
          playOptions: playOptions
        }, (code, res) => {
          if (code === 0) resolve(res);
          else reject(new Error(`playAlbum failed code ${code}`));
        });
      }, 100);
    });
  }

  play() {
    return new Promise((resolve) => {
      this.proxy.sendCommand('play', {}, (code) => resolve(code === 0));
    });
  }

  pause() {
    return new Promise((resolve) => {
      this.proxy.sendCommand('pause', {}, (code) => resolve(code === 0));
    });
  }

  stop() {
    return new Promise((resolve) => {
      this.proxy.sendCommand('stop', {}, (code) => resolve(code === 0));
    });
  }

  destroy() {
    if (this.playAlbumTimer) {
      clearTimeout(this.playAlbumTimer);
      this.playAlbumTimer = null;
    }
    if (this.proxy) {
      this.stop();
      for (const token of this.tokenSet) {
        this.proxy.off(token);
      }
      this.tokenSet.clear();
      this.proxy.disconnect();
      this.proxy = null;
    }
    this.initialized = false;
  }
}

export default new ProductionMediaPlayerClient();
```
