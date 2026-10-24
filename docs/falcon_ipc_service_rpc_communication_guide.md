# 官方系统服务 RPC 通信指南 (Falcon IPC Bus)
## (Falcon Inter-Process Communication & System Services RPC Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **底层引擎**: Falcon IPC Bus (`/usr/lib/libfalcon.so`) + UNIX Domain Socket + RPC 调度器  
> **核心组件**: `$service_proxy` (客户端调用桥) 与 `$falcon.ServiceProvider` (数据提供者服务端)

---

## 目录索引

1. [Falcon IPC 跨进程通信拓扑](#1-falcon-ipc-跨进程通信拓扑)
2. [客户端代理: `$service_proxy` 核心契约](#2-客户端代理-service_proxy-核心契约)
3. [服务端反向提供者: `ServiceProvider` 规范](#3-服务端反向提供者-serviceprovider-规范)
4. [核心系统微服务全景 RPC 字典](#4-核心系统微服务全景-rpc-字典)
   - [4.1 媒体与后台音频服务 (`mediaPlayerService`)](#41-媒体与后台音频服务-mediaplayerservice)
   - [4.2 词典查词与翻译服务 (`dictService`)](#42-词典查词与翻译服务-dictservice)
   - [4.3 扫读取词与 OCR 视觉识别服务 (`ocrService`)](#43-扫读取词与-ocr-视觉识别服务-ocrservice)
   - [4.4 系统设置与硬件状态服务 (`systemSettingService`)](#44-系统设置与硬件状态服务-systemsettingservice)
5. [生产级代码实战：全功能后台长音频管理器](#5-生产级代码实战全功能后台长音频管理器)
6. [生产级代码实战：词典划词翻译查询客户端](#6-生产级代码实战词典划词翻译查询客户端)

---

## 1. Falcon IPC 跨进程通信拓扑

词典笔系统采用**微服务化架构**（Microservices Architecture）。为了保证低内存（128MB）下的系统高内聚与容错性，诸如后台音乐播放、光学文字识别（OCR）、整句英汉互译、系统网络连接管理等重型基础设施，均以常驻或惰性唤起的独立微服务进程运行。

各个 MiniApp 前台页面与系统微服务之间通过 **Falcon IPC Bus** 进行隔离通信：

```
+--------------------------------------------------------------------+
| 前台微应用 (MiniApp Process, 如: 漫画阅读器 / 单词本)                 |
|   import ServiceProxy from '$service_proxy';                       |
|   proxy.sendCommand('playAlbum', payload, callback);               |
+--------------------------------------------------------------------+
                               ▲  | (双向 RPC 封包)
                               |  v
+--------------------------------------------------------------------+
| Falcon IPC 内核通道 (libfalcon.so)                                 |
|   JQuick::IPCChannel <--> UNIX Domain Socket (/var/run/miniapp-*)  |
+--------------------------------------------------------------------+
                               ▲  |
                               |  v
+--------------------------------------------------------------------+
| 后台系统微服务 (Microservice Process, 如: mediaPlayerService)       |
|   AppID: 8001650599023931                                          |
|   管理 Linux ALSA 音频硬件独占句柄 / 持有 Wakelock 电源锁           |
+--------------------------------------------------------------------+
```

---

## 2. 客户端代理: `$service_proxy` 核心契约

前端应用若要调用系统后台服务，必须通过内建模块 `'$service_proxy'` 建立连接。

### 2.1 基础 API 方法
```javascript
import ServiceProxy from '$service_proxy';

// 1. 创建代理实例
const proxy = new ServiceProxy();

// 2. 连接到指定的目标微服务
// URI 格式: falcon://<TargetAppId>/<ServiceName>
proxy.connect('falcon://8001650599023931/mediaPlayerService');

// 3. 检查通信链路是否畅通
const connected = proxy.isConnected(); // true | false

// 4. 发送指令 (Action, Params, Callback)
proxy.sendCommand('play', { mediaId: '1001' }, (errCode, response) => {
  if (errCode === 0) {
    console.log('指令执行成功:', response);
  } else {
    console.error('指令执行失败, 错误码:', errCode);
  }
});

// 5. 断开连接释放通道
proxy.disconnect();
```

---

## 3. 服务端反向提供者: `ServiceProvider` 规范

在很多高级业务场景中，系统微服务需要反向从调用方拉取业务数据（例如：系统播放器切歌时，需要向自研 MiniApp 索取下一首歌曲的音频 URL 与歌词）。

Falcon 采用 **双向反向契约（Reverse Provider Contract）**：
应用向微服务注册一个 `provider_path`，微服务通过该 Path 跨进程向应用派发数据请求。

### 3.1 核心防错铁律：`cb([0, data])`
在实现 Provider 回调时，返回给系统的参数**必须严格包装为二元数组**：
- `arg[0] = 0`：代表本次数据提取成功。
- `arg[1] = data`：实际返回的数据 Payload。
若直接传 `cb(data)`，系统会误将对象识别为错误码，导致微服务抛出 `MediaStatus.Unknown (code: 9)` 异常！

---

## 4. 核心系统微服务全景 RPC 字典

### 4.1 媒体与后台音频服务 (`mediaPlayerService`)
- **AppID**: `8001650599023931`
- **Path**: `falcon://8001650599023931/mediaPlayerService`
- **常驻特性**: 页面退出或屏幕熄灭后，音频持续播放，系统持有硬件电源锁。

#### 核心 Action 列表

| Action 名称 | 传入参数 (Params) | 返回结果 (Response) | 说明 |
| :--- | :--- | :--- | :--- |
| `playAlbum` | `{ playInfo, playOptions }` | `{ status: 0 }` | 注册播放列表并启动连续播放 |
| `play` | `{ mediaId? }` | `{ status: 0 }` | 恢复播放或播放指定音频 |
| `pause` | `{}` | `{ status: 0 }` | 暂停播放 |
| `stop` | `{}` | `{ status: 0 }` | 彻底停止播放并释放音频解码器 |
| `next` | `{}` | `{ currentMediaId }` | 切换下一首 |
| `prev` | `{}` | `{ currentMediaId }` | 切换上一首 |
| `seekTo` | `{ position: 60000 }` | `{ currentPosition }` | 跳转到指定毫秒进度 |
| `getPlayStatus`| `{}` | `{ state, position, duration }` | 查询当前播放器状态 |
| `setVolume` | `{ volume: 0.8 }` | `{ volume }` | 调节当前流媒体音量 |

#### 播放状态常量 (`PlayAction`)
- `Started`: `18` (开始播放)
- `Stopped`: `19` (停止播放)
- `Paused`: `20` (暂停中)
- `Completed`: `21` (当前音频自然播放完毕)
- `Progress`: `27` (播放进度汇报，每 500ms 触发一次)

#### 循环模式常量 (`MediaCycleMode`)
- `Order`: `28` (顺序播放，播完列表停止)
- `Random`: `29` (随机播放)
- `Single`: `30` (单曲单次)
- `One_Shot`: `31` (单曲循环)
- `Order_Cycle`: `32` (列表无限循环)

---

### 4.2 词典查词与翻译服务 (`dictService`)
- **AppID**: `8001680085293935` (系统查词服务)
- **Path**: `falcon://8001680085293935/dictService`

#### 核心 Action 列表
- **`queryWord`**:
  ```javascript
  proxy.sendCommand('queryWord', { word: 'abandon', dictType: 'oxford' }, (code, res) => {
    // res 包含: { word, phonetic, meanings: [...], examples: [...] }
  });
  ```
- **`translateSentence`**:
  ```javascript
  proxy.sendCommand('translateSentence', {
    text: 'Failure is the mother of success.',
    from: 'en',
    to: 'zh'
  }, (code, res) => {
    // res.translation = '失败是成功之母。'
  });
  ```

---

### 4.3 扫读取词与 OCR 视觉识别服务 (`ocrService`)
- **AppID**: `8001670668055425`
- **Path**: `falcon://8001670668055425/ocrService`
- **硬件关联**: 联动控制笔尖红外补光灯（LED）与 60FPS 高速全局快门 CMOS 传感器。

#### 核心 Action 列表
- **`startScanSession`**: 开启扫描会话，使能笔尖微动中断。
- **`stopScanSession`**: 关闭补光灯，结束图像拼接流。
- **`recognizeImage`**: 手动传入已拍摄帧缓冲图片绝对路径，进行离线神经 OCR 识别。

---

### 4.4 系统设置与硬件状态服务 (`systemSettingService`)
- **AppID**: `8080222437664451` (系统桌面与管控中枢)
- **Path**: `falcon://8080222437664451/systemSettingService`

#### 核心 Action 列表
- **`setBrightness`**: `{ value: 70 }` (调节全局亮度)
- **`setVolume`**: `{ value: 10 }` (调节主音量)
- **`setWifiEnabled`**: `{ enabled: true }` (开关 Wi-Fi 芯片电源)
- **`setSleepTimeout`**: `{ seconds: 120 }` (设定系统无操作息屏时限)

---

## 5. 生产级代码实战：全功能后台长音频管理器

以下为在自研 MiniApp 中集成系统 `mediaPlayerService` 的**完整商业级封装**：

```javascript
import ServiceProxy from '$service_proxy';

export const PlayState = {
  STOPPED: 0,
  PLAYING: 1,
  PAUSED: 2
};

export const CycleMode = {
  ORDER: 28,
  RANDOM: 29,
  SINGLE: 30,
  CYCLE: 32
};

class ProductionAudioManager {
  constructor() {
    this.proxy = null;
    this.appId = '8080999900000001'; // 当前 MiniApp 的 AppID
    this.playlist = [];
    this.currentIndex = 0;
    this.state = PlayState.STOPPED;
    this.onStateChangeCallback = null;
  }

  /**
   * 初始化并连接系统媒体服务
   */
  init(myAppId) {
    if (myAppId) this.appId = myAppId;
    if (!this.proxy) {
      this.proxy = new ServiceProxy();
      this.proxy.connect('falcon://8001650599023931/mediaPlayerService');
      this._registerProvider();
    }
  }

  /**
   * 注册反向数据提供者 (关键防错 cb([0, data]))
   */
  _registerProvider() {
    if (typeof $falcon !== 'undefined' && $falcon.registerProvider) {
      $falcon.registerProvider('mediaPlayerListProvider', {
        onCommand: (action, params, cb) => {
          switch (action) {
            case 'getProviderType':
              return cb && cb(0, 'mediaplayer_list');

            case 'loadMedia':
              const item = this.playlist[this.currentIndex];
              if (!item) return cb && cb(-1, 'No media available');
              return cb && cb([0, {
                mediaId: item.id,
                title: item.title,
                url: item.url,
                duration: item.duration || 0
              }]);

            case 'next':
              this.currentIndex = (this.currentIndex + 1) % this.playlist.length;
              const nextItem = this.playlist[this.currentIndex];
              return cb && cb([0, nextItem]);

            case 'prev':
              this.currentIndex = (this.currentIndex - 1 + this.playlist.length) % this.playlist.length;
              const prevItem = this.playlist[this.currentIndex];
              return cb && cb([0, prevItem]);

            default:
              return cb && cb(-1, `Action ${action} unsupported`);
          }
        }
      });
    }
  }

  /**
   * 播放专辑/列表
   */
  playAlbum(tracks, startIndex = 0, callback) {
    this.init();
    this.playlist = tracks;
    this.currentIndex = startIndex;

    const firstTrack = tracks[startIndex];
    const playInfo = {
      provider_info: {
        provider_name: 'CustomAudioListProvider',
        provider_path: `falcon://${this.appId}/mediaPlayerListProvider`
      },
      album_info: {
        albumId: 'custom_playlist',
        mediaCount: tracks.length
      },
      media_info: {
        mediaId: firstTrack.id,
        title: firstTrack.title,
        url: firstTrack.url
      }
    };

    this.proxy.sendCommand('playAlbum', {
      playInfo,
      playOptions: {
        cycleMode: CycleMode.CYCLE,
        autoPlay: true
      }
    }, (errCode, res) => {
      if (errCode === 0) {
        this.state = PlayState.PLAYING;
        if (callback) callback(true, res);
      } else {
        if (callback) callback(false, errCode);
      }
    });
  }

  /**
   * 恢复/暂停切换
   */
  togglePlay() {
    if (this.state === PlayState.PLAYING) {
      this.proxy.sendCommand('pause', {}, () => {
        this.state = PlayState.PAUSED;
      });
    } else {
      this.proxy.sendCommand('play', {}, () => {
        this.state = PlayState.PLAYING;
      });
    }
  }

  /**
   * 切歌：下一首
   */
  next() {
    this.proxy.sendCommand('next', {}, (errCode, res) => {
      console.log('切歌下一首结果:', errCode);
    });
  }

  /**
   * 销毁与资源释放
   */
  destroy() {
    if (this.proxy) {
      this.proxy.sendCommand('stop', {}, () => {
        this.proxy.disconnect();
        this.proxy = null;
      });
    }
  }
}

export default new ProductionAudioManager();
```

---

## 6. 生产级代码实战：词典划词翻译查询客户端

以下为在漫画阅读器或小说阅读器中直接调用系统官方词库的**查词客户端封装**：

```javascript
import ServiceProxy from '$service_proxy';

class DictServiceClient {
  constructor() {
    this.proxy = null;
  }

  _ensureConnect() {
    if (!this.proxy || !this.proxy.isConnected()) {
      this.proxy = new ServiceProxy();
      this.proxy.connect('falcon://8001680085293935/dictService');
    }
  }

  /**
   * 快速单词查询 (带本地离线词典缓存)
   * @param {string} word - 要查询的英文或中文单词
   * @returns {Promise<Object>} 释义结果
   */
  lookup(word) {
    this._ensureConnect();
    return new Promise((resolve, reject) => {
      this.proxy.sendCommand('queryWord', { word: word.trim() }, (code, res) => {
        if (code === 0 && res) {
          resolve({
            word: res.word,
            phonetic: res.phonetic || '',
            ukPhonetic: res.ukPhonetic || '',
            usPhonetic: res.usPhonetic || '',
            translation: res.translation || (res.meanings && res.meanings.join('\n')) || '暂无释义',
            audioUrl: res.audioUrl || ''
          });
        } else {
          reject(new Error(`Query failed with code ${code}`));
        }
      });
    });
  }

  /**
   * 整句或长段落机器翻译
   */
  translate(sentence) {
    this._ensureConnect();
    return new Promise((resolve, reject) => {
      this.proxy.sendCommand('translateSentence', {
        text: sentence.trim(),
        from: 'auto',
        to: 'zh'
      }, (code, res) => {
        if (code === 0 && res) {
          resolve(res.translation);
        } else {
          reject(new Error(`Translate failed with code ${code}`));
        }
      });
    });
  }
}

export default new DictServiceClient();
```
