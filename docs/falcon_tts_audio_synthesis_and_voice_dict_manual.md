# 有道词典笔 S7 Pro TTS 语音合成、离线发音词库与低延迟音频播放子系统深度逆向工程指南
## (Falcon TTS Synthesis, Offline Pronunciation Containers, StreamTTS & ALSA Low-Latency Pipeline Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `libfalcon.so` (QuickJS C-Module 注册), `libjsapi_export_core.so` (`JSSoundPlayerProxy`), `libcapt.so`, `libyddal_common_soundplayer.so`, AW883XX SmartPA (I2C)

---

## 目录索引

1. [C++ 类架构、导出绑定与核心接口逆向](#1-c-类架构导出绑定与核心接口逆向)
   - 1.1 [模块加载与原型链注册拓扑](#11-模块加载与原型链注册拓扑)
   - 1.2 [导出的 12 个核心原型方法反编译分析](#12-导出的-12-个核心原型方法反编译分析)
   - 1.3 [导出的 8 个原生信号 (JQSignal)](#13-导出的-8-个原生信号-jqsignal)
   - 1.4 [`StreamTTS` 专用模块接口](#14-streamtts-专用模块接口)
2. [离线 TTS 语音合成参数与字典发音库解构](#2-离线-tts-语音合成参数与字典发音库解构)
   - 2.1 [声学参数配置 (`setPlayTTSParam`) 协议](#21-声学参数配置-setplayttsparam-协议)
   - 2.2 [英音 (UK) 与美音 (US) 发音切换机制 (`switchTtsAutoPronType`)](#22-英音-uk-与美音-us-发音切换机制-switchttsautoprontype)
   - 2.3 [板载离线发音库与字典物理挂载路径](#23-板载离线发音库与字典物理挂载路径)
3. [音频流喂送机制、采样率与 ALSA 硬件环形缓冲区](#3-音频流喂送机制采样率与-alsa-硬件环形缓冲区)
   - 3.1 [采样率、位深与声道规格](#31-采样率位深与声道规格)
   - 3.2 [三态分片播放协议 (`frameStatus`)](#32-三态分片播放协议-framestatus)
   - 3.3 [共享内存直通与 ALSA Ringbuffer 约束](#33-共享内存直通与-alsa-ringbuffer-约束)
4. [并发陷阱剖析：`mediaPlayerService` 冲突与 `quickStop()` 硬件截断](#4-并发陷阱剖析mediaplayerservice-冲突与-quickstop-硬件截断)
   - 4.1 [单 DAC 独占声卡死锁陷阱](#41-单-dac-独占声卡死锁陷阱)
   - 4.2 [`stop()` 与 `quickStop()` 的本质差异与硬件截断机制](#42-stop-与-quickstop-的本质差异与硬件截断机制)
5. [生产级 JavaScript 范例代码](#5-生产级-javascript-范例代码)
   - 5.1 [场景一：离线多语种单词发音与英/美音动态切换 (`OfflineWordSpeaker`)](#51-场景一离线多语种单词发音与英美音动态切换)
   - 5.2 [场景二：流式整句语音合成 (`StreamTtsSynthesizer`)](#52-场景二流式整句语音合成)
   - 5.3 [场景三：结合 `mediaPlayerService` 音频焦点协同与笔尖微动中断 (`AudioPlaybackCoordinator`)](#53-场景三结合-mediaplayerservice-音频焦点协同与笔尖微动中断)

---

## 1. C++ 类架构、导出绑定与核心接口逆向

在 Falcon GUI 运行时体系中，QuickJS 2020-07-05 引擎通过 C 扩展模块机制动态挂载本地音频能力。音频子系统的核心实现位于动态库 `/usr/lib/libjsapi_export_core.so`。

### 1.1 模块加载与原型链注册拓扑

- **模块初始化入口**: `sound_player_module_init_jsapis`（虚拟地址 `0x00091114`）。
  该函数通过 `registerCModuleLoader("soundPlayer", 0x906d4)` 向 QuickJS 引擎注册模块加载器。
- **C-Module 回调结构**: 
  在入口 `0x000906d4` 执行时，调用 `JS_NewCModule(ctx, "soundPlayer", 0x91d60)` 并导出 `"default"` 类构造函数。
- **C++ 代理封装类**: `JSSoundPlayerProxy`（继承自 `JQBaseObject`）。
  在函数 `0x00091d60` 中，通过模板方法 `JQFunctionTemplate::SetProtoMethod<JSSoundPlayerProxy>` 绑定 12 个原型方法与 8 个信号（`JQSignal`）。
- **底座单例委托**: `JSSoundPlayerProxy` 的所有方法均不直接操作硬件，而是转发给内部核心单例 `YDALAPI::YSoundPlayerModule::Instance()`（通过 `libyddal_common_soundplayer.so` 接入硬件抽象层）。
- **全局并发互斥锁**: 地址 `0x000ef730` 处分配了全局互斥量 `_soundplayer_mutex`，用于对 QuickJS 执行线程与底层音频回调线程的写操作进行临界区互斥。

```
+----------------------------------------------------------------------------------+
|                            QuickJS 运行时 (MiniApp 线程)                          |
|  import soundPlayerModule from 'soundPlayer';                                    |
|  const player = new soundPlayerModule.SoundPlayer();                             |
+----------------------------------------|-----------------------------------------+
                                         | JQFunctionTemplate 绑定分发
+----------------------------------------v-----------------------------------------+
|                  C++ 代理层: JSSoundPlayerProxy (libjsapi_export_core.so)          |
|  [playTts] [playStreamTts] [setPlayTTSParam] [switchTtsAutoPronType] [quickStop] |
+----------------------------------------|-----------------------------------------+
                                         | 互斥锁保护: _soundplayer_mutex (0x0ef730)
+----------------------------------------v-----------------------------------------+
|                硬件适配抽象层: YDALAPI::YSoundPlayerModule (Singleton)             |
|                  动态链接至 libyddal_common_soundplayer.so                         |
+----------------------------------------|-----------------------------------------+
                                         | POSIX 共享内存 IPC (Zero-Copy)
+----------------------------------------v-----------------------------------------+
|               常驻后台音频守护进程: /oem/YoudaoDictPen/output/SoundPlayer           |
|                ALSA 驱动层: snd_pcm_writei / snd_pcm_drop (hw:1,0)               |
+----------------------------------------------------------------------------------+
```

### 1.2 导出的 12 个核心原型方法反编译分析

| 方法名 | 虚拟地址 | 参数规范及底层行为 |
| :--- | :--- | :--- |
| `playFile` | `0x00091584` | `(filePath: string, offsetMs: number, speed: number, loop: boolean, durationMs: number)`。直接由底层本地文件解码器读取文件并推入 DMA 缓冲。 |
| `stop` | `0x00091194` | `(taskId?: string)`。安全优雅停止当前播放任务，允许当前帧排空（Drain）。 |
| `quickStop` | `0x00091298` | `()`。无参数。瞬时重置底层 ALSA DMA 缓冲区，硬件输出在 `< 10ms` 内静音。 |
| `playTts` | `0x00090954` | `(text: string, voiceId?: string = "-1")`。用于查词词头朗读、短语离线离散合成。校验 `text` 必须为 `string`，底层缺省 voiceId 填 `"-1"`。 |
| `playStreamTts` | `0x00090a60` | `(method: string, request: string, options: string)`。流式语音合成专用底层接口，三参数均严格校验为 string（JSON 序列化串）。 |
| `play` | `0x00090ee0` | `(text: string, lang: string, voiceId: string, speed: number)`。通用带参数离线/在线混合发音接口。 |
| `playBase64` | `0x00090c4c` | `(base64Data: string)`。用于无需落盘的即时内存音频数据解码播放。 |
| `playOnlineAudio` | `0x00090d28` | `(url: string)`。在线流媒体 URL 快速播放。 |
| `playMediaSection` | `0x00090e04` | `(url: string, startMs: number, endMs: number)`。区间音频点读（课文听力例句复读）。 |
| `playOnlineAudioByMoreTransApp` | `0x0009196c` | `(param1: string, param2: string)`。多语种翻译专用发音管道。 |
| `switchTtsAutoPronType` | `0x00091334` | `(pronType: number)`。切换发音语系与发音字典映射类型，入参严格限制为 `int32` 数字。 |
| `setPlayTTSParam` | `0x00091b88` | `(params: string)`。配置离线 TTS 引擎核心声学参数（语速、音高、音量、发音人），入参必须为 string。 |

### 1.3 导出的 8 个原生信号 (JQSignal)

实例初始化时在模版内注册了以下系统状态事件：
1. `mediaPlayerPositionChanged(pos: number)`: 当前播放物理位置（毫秒）。
2. `mediaPlayerDurationChanged(duration: number)`: 媒体总时长更新。
3. `mediaPlayerProgressChanged(progress: number)`: 进度比例（0~1000）。
4. `mediaPlayerEndChanged(taskId: string)`: 播放自然完成回调。
5. `mediaPlayerEndWithErrorChanged(taskId: string, errCode: number)`: 播放异常中止。
6. `mediaPlayerEndWithErrorChangedEx(taskId: string, pos: number, err: YPlayerError)`: 携带最后播放帧时间戳与详细错误枚举的扩展中止信号。
7. `ttsDataStarted(taskId: string, text: string)`: 底层 TTS 引擎正式开始向声卡环形缓冲区填充首包音频数据（用于 UI 动效对齐）。
8. `onTtsError(taskId: string, errorMsg: string)`: 离线合成算法故障或在线网络断流事件。

### 1.4 `StreamTTS` 专用模块接口

针对拍照讲题与小P老师应用（`8001707294117702`、`8001735023580768`），系统还提供了专用的流式状态机封装类 `StreamTTS`：
- **导入方式**: `import streamTTSModule from 'streamTTS'; const sTts = new streamTTSModule.StreamTTS();`
- **核心方法**:
  - `requestTts(type: string, reqJson: string, authJson: string): string`: 返回任务 `UUID`，用于预加载或分类文本。
  - `playTts(type: string, reqJson: string, authJson: string): string`: 提交合成音频并播放。
  - `stop()`: 中止流式生成。
- **通知信号**: `onRequestTtsResult(uuid, code, status, result)`。
  其中状态字符串包含：
  - `'classify_text_end'`: 意图分类/文本切分完毕；
  - `'play_progress'`: 当前音频播放帧递增；
  - `'play_end'`: 单句音频播放完成；
  - `'play_error'`: 播放出错；
  - `'play_interrupted'`: 被外部高优先级事件截断。

---

## 2. 离线 TTS 语音合成参数与字典发音库解构

### 2.1 声学参数配置 (`setPlayTTSParam`) 协议

通过对 `JSSoundPlayerProxy::setPlayTTSParam` 及 `YSoundPlayerModule` 的反汇编分析，该接口接收序列化的 JSON 配置对象，主要控制以下声学引擎参量：

```json
{
  "speed": 1.0,
  "pitch": 0,
  "volume": 12,
  "voiceName": "youxiaoshi",
  "ttsSource": "offline_tts"
}
```

- **语速 (`speed`)**:
  - 离线语音支持浮点倍速（`0.8` ~ `1.2`）以及预设档位：
    - `'slow'`: 慢速研读（0.8x，重音与弱读音节明显拉长，便于学生跟读）。
    - `'moderate'`: 标准常速（1.0x）。
    - `'fast'`: 快速复习（1.2x）。
  - 词典详情页支持连续三次轻触词头扬声器触发 `detail_continuous_three_click`，在三种倍速间无缝轮换。
- **音量 (`volume`)**:
  - 取值范围严格为 `0 ~ 15`。
  - 该数值直接关联至 Linux ALSA 混音器的 `Playback Volume` 寄存器及板载 AW883XX SmartPA 芯片的硬件增益曲线。
- **音高 (`pitch`)**:
  - 取值范围 `-10` 至 `+10`，基准值为 `0`。控制声带基频（F0）偏移。
- **发音角色模型 (`voiceName`)**:
  - `'youxiaoshi'`: 板载纯离线端侧轻量发音人（WAV 格式，儿童与学前适配，低功耗）。
  - `'youlingling'`: 离线标准播音级女声发音人。
  - `'tai_yi_zhen_ren'`: 智云在线角色音色（MP3 格式，配合小P老师大模型问答使用）。

### 2.2 英音 (UK) 与美音 (US) 发音切换机制 (`switchTtsAutoPronType`)

通过逆向 `Constant-51a9bd76.js.bin`（闭包常量索引 72~80）与 `accentMixin-4325eb33.js.bin`，确认 `switchTtsAutoPronType(pronType)` 的常量映射表如下：

```javascript
// 固件标准枚举常量定义
const AutoPronType = {
  UK: 0,                 // 0: 英式发音 (British Pronunciation)
  US: 1,                 // 1: 美式发音 (American Pronunciation)
  PinYin: 2,             // 2: 汉语拼音教学发音
  CollinsPrimary: 3,     // 3: 柯林斯初阶专属例句库
  EnPolyPhone: 4,        // 4: 英语多音词/异音同形词矫正模型
  XinHua: 5,             // 5: 新华字典标准汉字朗读
  PronunciationGuide: 6, // 6: 自然拼读与音标切分发音指引
  OxFord: 7,             // 7: 牛津高阶词典专有原声音频
  ShakeSound: 8          // 8: 物理按键与震动音效
};
```

系统设置应用（AppID: `8080272425914438`）通过 `$falcon.env.custom.$set('accent', 'uk')` 改变全局偏好，随后调用 `soundPlayer.switchTtsAutoPronType(AutoPronType.UK)`。底层会立即重定向离线音频文件的解包寻址指针。

### 2.3 板载离线发音库与字典物理挂载路径

S7 Pro 拥有数 GB 独立离线多媒体资源包，固件将其只读挂载于闪存分区 `/userdisk/uresource/localdict/` 与 `/userdisk/uresource/localsound/`：

1. **英美真人离线发音库**:
   - 美音真人口型库：`/userdisk/uresource/localsound/dictpen-us-voiceV2.dat`（约 482MB）
   - 英音真人口型库：`/userdisk/uresource/localsound/dictpen-uk-voiceV2.dat`（约 489MB）
   - 中文标准朗诵库：`/userdisk/uresource/localsound/dictpen-zh-voiceV2.dat`（约 127MB）
2. **专业权威词典例句原声音频库**:
   - 牛津高阶 9/10 版词条原声：`/userdisk/uresource/localsound/dictpen-oxfordAdvance-nine-word-voiceV2.dat`（约 392MB）
   - 柯林斯初阶整句发音库：`/userdisk/uresource/localsound/dictpen-collins-primary-voiceV2.dat`（约 53MB）
3. **数据格式与索引解包**:
   - `.dat` 文件采用有道私有加盐高压缩索引结构。
   - 文件头部包含 32 字节 Hash 校验头，随后是按词条 MD5 散列排序的偏移量表（Offset Table）和长度表（Length Table）。
   - 音频数据主体以 16kHz Speex 或低比特率 CELP 格式压缩封装，在 `libyddal_base_dict.so` 查词命中后通过零拷贝映射（`mmap`）在内存中解码为 PCM 流推送至声卡。

---

## 3. 音频流喂送机制、采样率与 ALSA 硬件环形缓冲区

### 3.1 采样率、位深与声道规格

根据驱动层与 `libyddal_common_soundplayer.so` 的反编译结果：
- **离线 TTS 发音 / 字典词头朗诵**:
  - **采样率**: **16,000 Hz (16kHz)**。
  - **采样格式**: **S16_LE**（16-bit 符号整型，小端序）。
  - **声道数**: **单声道 (Mono)**。
  - **工程权衡**: Cortex-A7 单核 1.0GHz 算力受限，16kHz 既能完整覆盖人声泛音范围（8kHz 奈奎斯特频率），又能将内存占用削减至 44.1kHz 的 36%，确保低功耗下的极速合成。
- **多媒体背景音乐 (`mediaPlayerService`)**:
  - **采样率**: 44,100 Hz / 48,000 Hz 双声道立体声。
  - **重采样管线**: 依赖动态库 `libswresample.so.3`（FFmpeg Resampler），当 DAC 锁定在 48kHz 时自动完成上采样。

### 3.2 三态分片播放协议 (`frameStatus`)

在调用 `playStreamTts` 喂送实时分片数据时，必须维护精确的状态机生命周期：

```
+---------------+      frameStatus: 0 (Start)      +--------------------+
| 客户端流式接收 | ------------------------------> | 申请声卡硬件句柄   |
| (WebSocket/SSE) |                                 | 分配 Ringbuffer    |
+---------------+                                  +--------------------+
        |
        | frameStatus: 1 (Data)                    +--------------------+
        +----------------------------------------> | 连续写入 PCM 片段  |
        |                                          | Zero-Copy 环形灌包 |
        v                                          +--------------------+
+---------------+      frameStatus: 2 (End)        +--------------------+
| 数据接收完毕   | ------------------------------> | 触发 ALSA Drain    |
+---------------+                                  | 释放音频焦点锁     |
                                                   +--------------------+
```

- **`frameStatus: 0` (Start Frame)**:
  - 告知底层音频引擎启动新流。
  - 初始化解码器，在 `/dev/shm` 申请共享内存槽位，抢占音频路由通道。
- **`frameStatus: 1` (Data Push Frame)**:
  - 持续传入连续分片音频（PCM 或 Base64 字符串）。
  - 底层守护进程将数据直接 memcpy 入声卡环形缓冲区。
- **`frameStatus: 2` (End / Drain Frame)**:
  - 标记该句子流传输结束。
  - 触发 ALSA 驱动执行 `snd_pcm_drain`，当硬件缓冲区播放完毕后，触发 `mediaPlayerEndChanged` 信号。

### 3.3 共享内存直通与 ALSA Ringbuffer 约束

- **零拷贝直通管线 (Zero-Copy Pipeline)**:
  QuickJS 线程通过 `JSSoundPlayerProxy::playStreamTts` 将请求封装为结构体后，交由 `libyddal_common_soundplayer.so` 的 `WriteShmTask` 写入 POSIX 共享内存。常驻后台进程 `/oem/YoudaoDictPen/output/SoundPlayer` 的 `ReadShmTask` 经由信号量（`YShmSync`）唤醒后，直接调用 ALSA 原生 `snd_pcm_writei` 写入硬件。
- **硬件 ALSA 设备**: S7 Pro 的物理声卡挂载在 `hw:1,0`，输出端直连 AW883XX SmartPA 智能功放。
- **ALSA 缓冲区拓扑**:
  - **周期大小 (`period_size`)**: 1024 帧（Frames）。
  - **周期数 (`periods`)**: 4。
  - **总缓冲大小 (`buffer_size`)**: 4096 帧。
  - 在 16kHz 单声道模式下，每个周期时长为：
    $$\frac{1024}{16000} \approx 64 \text{ ms}$$
  - 为实现物理触笔提笔时的低延迟，`soundPlayer` 将底层 ALSA 阈值设置为极速唤醒模式，初始填充 1 个周期（约 64ms）后即刻打开发声阀门，使得物理启动总延迟稳定在 `< 10ms`。

---

## 4. 并发陷阱剖析：`mediaPlayerService` 冲突与 `quickStop()` 硬件截断

### 4.1 单 DAC 独占声卡死锁陷阱

CV1813H SoC 硬件上仅具备一个物理立体声 DAC 输出通道，且 Linux 4.9/5.10 固件中**未部署** PulseAudio 或 PipeWire 等软混音守护进程。
系统架构形成了“双轨并存”的矛盾局面：
1. **长音频伴奏轨 (`mediaPlayerService`, AppID: `8001650599023931`)**: 负责网易云音乐、听力练习、喜马拉雅等后台长时间播放。
2. **极速音效与 TTS 轨 (`soundPlayer` / `StreamTTS`)**: 负责查词发音、笔尖点击音、小P老师讲题。

**死锁场景**:
- 若后台 `mediaPlayerService` 正在播放听力 MP3，此时用户扫描单词触发 `soundPlayer.playTts()`。
- `SoundPlayer` 底层尝试以独占模式 `open("/dev/snd/pcmC1D0p")`，系统返回 `EBUSY`（Device or resource busy）。
- 如果前端代码未对异常进行处理，或未通知后台媒体服务降音/暂停，QuickJS 的互斥锁 `_soundplayer_mutex` 将持续持有，导致整个前端界面的音频调用完全挂起（死锁），直至整机重启。

**系统级音频焦点协同规则**:
- 在调起 `soundPlayer.playTts` 或 `playStreamTts` 之前，前端必须先通过 `$service_proxy` 发送暂停指令：
  ```javascript
  const proxy = new ServiceProxy();
  proxy.connect('falcon://8001650599023931/mediaPlayerService');
  proxy.sendCommand('pause', {}, () => {});
  ```
- 待 TTS 发音结束（捕获 `mediaPlayerEndChanged` 事件）后，再恢复背景音乐。

### 4.2 `stop()` 与 `quickStop()` 的本质差异与硬件截断机制

在反编译代码中，`stop()` 与 `quickStop()` 呈现出截然不同的行为路径：

```arm
; --- JSSoundPlayerProxy::quickStop (0x00091298) ---
0x9130c:  bl   YSoundPlayerModule::Instance()
0x91318:  b    YSoundPlayerModule::quickStop()  ; 直接跳转，无等待

; --- JSSoundPlayerProxy::stop (0x00091194) ---
0x91260:  bl   YSoundPlayerModule::Instance()
0x9126c:  b    YSoundPlayerModule::stop()       ; 状态机优雅清理
```

1. **`stop()` (优雅终止)**:
   - 走标准状态机流转。向音频处理队列末尾投递一个 `StopEvent`。
   - 驱动层保持当前正在向 DAC 传输的 DMA 块继续播放，直到将当前 Period（1024 帧）排空，平滑渐隐并关闭句柄。
   - 物理响应耗时通常在 **50ms ~ 120ms** 左右。
2. **`quickStop()` (硬件级瞬时截断)**:
   - 专为物理笔尖交互设计。当光电传感器检测到笔尖微动按键抬起（`buttonEvent.on('headButtonRelese')`），系统必须在用户提笔的瞬间切断声音，防止遗留上一次扫描的杂音。
   - 底层直接向声卡驱动发出 `ioctl(fd, SNDRV_PCM_IOCTL_DROP)` 指令，在内核层强行终止硬件 DMA 传输，丢弃环形缓冲区内剩余的所有待播放帧，并立即置零 SmartPA 增益。
   - 物理响应耗时 **$< 10\text{ ms}$**，实现“提笔即静音”的硬件级响应体验。

---

## 5. 生产级 JavaScript 范例代码

### 5.1 场景一：离线多语种单词发音与英/美音动态切换

```javascript
import soundPlayerModule from 'soundPlayer';

export const AccentType = {
  UK: 0,             // 英音
  US: 1,             // 美音
  PinYin: 2,         // 汉语拼音
  CollinsPrimary: 3  // 柯林斯原声
};

export class OfflineWordSpeaker {
  constructor() {
    this.player = new soundPlayerModule.SoundPlayer();
    this.currentAccent = AccentType.US;
    this.initSignals();
  }

  initSignals() {
    this.player.on('ttsDataStarted', (taskId, word) => {
      console.log(`[TTS] 开始发音: 任务ID=${taskId}, 词条=${word}`);
    });

    this.player.on('mediaPlayerEndChanged', (taskId) => {
      console.log(`[TTS] 播放完成: 任务ID=${taskId}`);
    });

    this.player.on('mediaPlayerEndWithErrorChangedEx', (taskId, pos, errCode) => {
      console.error(`[TTS] 播放中止: 任务ID=${taskId}, 截断位置=${pos}ms, 错误码=${errCode}`);
    });
  }

  configureEngine(config = {}) {
    const params = {
      speed: config.speed || 1.0,   // 0.8: 慢速, 1.0: 常速, 1.2: 快速
      volume: config.volume ?? 12,  // 0 ~ 15
      pitch: config.pitch || 0,
      voiceName: 'youxiaoshi',
      ttsSource: 'offline_tts'
    };
    this.player.setPlayTTSParam(JSON.stringify(params));
  }

  setAccent(accent) {
    if (accent !== AccentType.UK && accent !== AccentType.US) {
      throw new TypeError('Accent must be 0 (UK) or 1 (US)');
    }
    this.currentAccent = accent;
    this.player.switchTtsAutoPronType(this.currentAccent);
    console.log(`[TTS] 成功切换发音为: ${accent === 0 ? '英音(UK)' : '美音(US)'}`);
  }

  speakWord(word) {
    if (!word || typeof word !== 'string') return;
    this.player.quickStop();
    return this.player.playTts(word);
  }

  abort() {
    this.player.quickStop();
  }
}
```

---

### 5.2 场景二：流式整句语音合成

```javascript
import soundPlayerModule from 'soundPlayer';

export class StreamTtsSynthesizer {
  constructor() {
    this.player = new soundPlayerModule.SoundPlayer();
    this.isSessionActive = false;
  }

  async streamSynthesize(textStream) {
    this.sendStreamFrame('', 0);
    this.isSessionActive = true;

    try {
      for await (const chunk of textStream) {
        if (!this.isSessionActive) break;
        this.sendStreamFrame(chunk, 1);
      }
      if (this.isSessionActive) {
        this.sendStreamFrame('', 2);
      }
    } catch (err) {
      console.error('[StreamTTS] 推流异常中断:', err);
      this.player.quickStop();
    } finally {
      this.isSessionActive = false;
    }
  }

  sendStreamFrame(text, frameStatus) {
    const requestPayload = {
      action: 'ttsText',
      ttsText: {
        text: text,
        frameStatus: frameStatus // 0: Start, 1: Data, 2: End
      }
    };

    const optionsPayload = {
      ttsSource: 'zhiyun_tts_v1_ws',
      voiceName: 'tai_yi_zhen_ren',
      voiceEncoding: 'pcm'
    };

    return this.player.playStreamTts(
      'youdao_stream_tts',
      JSON.stringify(requestPayload),
      JSON.stringify(optionsPayload)
    );
  }

  cancel() {
    this.isSessionActive = false;
    this.player.quickStop();
  }
}
```

---

### 5.3 场景三：结合 `mediaPlayerService` 音频焦点协同与笔尖微动中断

```javascript
import soundPlayerModule from 'soundPlayer';
import buttonEventModule from 'buttonEvent';
import ServiceProxy from '$service_proxy';

export class AudioPlaybackCoordinator {
  constructor() {
    this.soundPlayer = new soundPlayerModule.SoundPlayer();
    this.btn = new buttonEventModule.ButtonEvent();
    this.mediaProxy = new ServiceProxy();
    this.isMediaPlayingBeforeTTS = false;
    
    this.setupHardwareTriggers();
    this.connectMediaService();
  }

  connectMediaService() {
    this.mediaProxy.connect('falcon://8001650599023931/mediaPlayerService');
  }

  setupHardwareTriggers() {
    this.btn.setButtonEventReady(true);

    this.btn.on('headButtonPress', () => {
      console.log('[HAL] 笔尖触底扫描，立即暂停所有发音');
      this.soundPlayer.quickStop();
    });

    this.btn.on('headButtonRelese', () => {
      console.log('[HAL] 笔尖离开纸面，保障 DMA 静音');
      this.soundPlayer.quickStop();
    });

    this.soundPlayer.on('mediaPlayerEndChanged', () => {
      this.onTTSFinished();
    });

    this.soundPlayer.on('mediaPlayerEndWithErrorChanged', () => {
      this.onTTSFinished();
    });
  }

  async safePlayTts(text) {
    await this.pauseBackgroundMediaIfPlaying();
    this.soundPlayer.quickStop();
    this.soundPlayer.playTts(text);
  }

  pauseBackgroundMediaIfPlaying() {
    return new Promise((resolve) => {
      this.mediaProxy.sendCommand('getPlayState', {}, (code, res) => {
        if (code === 0 && res && res.isPlaying) {
          this.isMediaPlayingBeforeTTS = true;
          this.mediaProxy.sendCommand('pause', {}, () => resolve());
        } else {
          this.isMediaPlayingBeforeTTS = false;
          resolve();
        }
      });
    });
  }

  onTTSFinished() {
    if (this.isMediaPlayingBeforeTTS) {
      this.mediaProxy.sendCommand('play', {}, () => {
        this.isMediaPlayingBeforeTTS = false;
        console.log('[AudioCoord] 背景音乐已自动恢复播放');
      });
    }
  }

  destroy() {
    this.soundPlayer.quickStop();
    this.mediaProxy.disconnect();
  }
}
```
