# 有道词典笔 S7 Pro 语音助手、实时 ASR 听写与麦克风 HAL 子系统深度逆向分析
## (Falcon Voice Assistant, Streaming ASR, Oral Evaluation & Microphone HAL Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB RAM, Linux 5.10.4)  
> **核心组件**: `RecordService` (`8001670668055425`), `LittleP` (`8001707294117702`), `libcapt.so` (Kaldi), `libbf.v1.0.1.cv1826_release.so`, `libyoudao_afe_lim.so`

---

## 目录索引

1. [语音助手 MiniApp 与系统守护服务拓扑](#1-语音助手-miniapp-与系统守护服务拓扑)
   - 1.1 [MiniApp ID 映射与硬件动态分发 (`theme-y08`)](#11-miniapp-id-映射与硬件动态分发-theme-y08)
   - 1.2 [三层微服务拓扑结构](#12-三层微服务拓扑结构)
   - 1.3 [原生动态库与二进制依赖清单](#13-原生动态库与二进制依赖清单)
2. [音频采集 HAL 与零拷贝共享内存直通](#2-音频采集-hal-与零拷贝共享内存直通)
   - 2.1 [ALSA 硬件采集规格与双 PDM 数字麦克风](#21-alsa-硬件采集规格与双-pdm-数字麦克风)
   - 2.2 [DSP 波束成形与 AFE 降噪流水线](#22-dsp-波束成形与-afe-降噪流水线)
   - 2.3 [POSIX 共享内存零拷贝环形缓冲区 (`writeShm`)](#23-posix-共享内存零拷贝环形缓冲区-writeshm)
3. [语音识别引擎深度解构 (端云混合架构)](#3-语音识别引擎深度解构-端云混合架构)
   - 3.1 [端侧离线口语评测引擎 (`libcapt.so`)](#31-端侧离线口语评测引擎-libcaptso)
   - 3.2 [云端短语音 ASR 协议 (`getShortAsrOneTime`)](#32-云端短语音-asr-协议-getshortasronetime)
   - 3.3 [流式 ASR 与语音翻译协议 (有道 / 讯飞)](#33-流式-asr-与语音翻译协议-有道--讯飞)
   - 3.4 [唤醒词识别 (KWS) 与后台监听](#34-唤醒词识别-kws-与后台监听)
   - 3.5 [静音切分与 VAD (800ms 静音截断)](#35-静音切分与-vad-800ms-静音截断)
4. [JSAPI 与跨进程 RPC 接口字典 (`record-service`)](#4-jsapi-与跨进程-rpc-接口字典-record-service)
   - 4.1 [核心 RPC 指令集 (`sendCommand`)](#41-核心-rpc-指令集-sendcommand)
   - 4.2 [服务事件广播全集 (`proxy.on`)](#42-服务事件广播全集-proxyon)
5. [生产级开发封装与完整示例代码](#5-生产级开发封装与完整示例代码)
   - 5.1 [生产级 RPC 客户端 (`RecordServiceClient.js`)](#51-生产级-rpc-客户端-recordserviceclientjs)
   - 5.2 [端到端 Vue SFC 交互组件 (`VoiceAssistantView.vue`)](#52-端到端-vue-sfc-交互组件-voiceassistantviewvue)

---

## 1. 语音助手 MiniApp 与系统守护服务拓扑

### 1.1 MiniApp ID 映射与硬件动态分发 (`theme-y08`)

通过对 Launcher 主屏幕（`8080222437664451`）的反汇编，发现 S7 Pro（硬件平台代码 `theme-y08`）并未运行传统的单体语音助手（`8080272808953200`），而是动态分发到“小P老师”（`LittleP`，AppID: `8001707294117702`）：

```javascript
// Launcher indexPage-085a554f.js.bin 逆向反编译切片
async voiceAssistantClicked() {
  const { DictAppID } = await import("./Constant-a706d45f.js");
  if (this.entranceGlobalThemeName === "theme-y08") {
    // S7 Pro 进入小P老师大模型对话应用
    this.clickItem(DictAppID.LittleP); // 8001707294117702
    this.$emit("sendLogFromHome", "home_LittleP_click");
  } else {
    this.clickItem(DictAppID.VoiceAssistant); // 8080272808953200 (Legacy)
  }
}
```

### 1.2 三层微服务拓扑结构

```
+-------------------------------------------------------------------------------+
|                        Tier 1: UI MiniApp Layer                               |
|  LittleP (8001707294117702)  /  VoiceAssistant (8080272808953200)             |
|  - TalkingView-6a80b642.js.bin (Voice Activity Detection, 800ms silence timer)|
|  - recordManager-d6bdad2b.js.bin (Pool of 5 $service_proxy connection slots)  |
+---------------------------------------+---------------------------------------+
                                        | Cross-Process RPC ($service_proxy)
                                        | falcon://8001670668055425/record-service
+---------------------------------------v---------------------------------------+
|                    Tier 2: System Service Daemon                              |
|  RecordService (8001670668055425) - record-service.js.bin                     |
|  - Native QuickJS C-Modules: 'record', 'speech', 'capt', 'poemRecite'        |
|  - libjsapi_record.so -> libbusiness_record.so                                |
|  - Core C++ Coordinator: YDALAPI::YRecordCenter::Instance()                   |
+---------------------------------------+---------------------------------------+
                                        | POSIX Shared Memory (writeShm)
                                        | Zero-Copy Ring Buffer (/dev/shm)
+---------------------------------------v---------------------------------------+
|                    Tier 3: Hardware Audio HAL Daemon                          |
|  /oem/YoudaoDictPen/output/SoundRecord                                       |
|  - Acoustic Front End (AFE): libyoudao_afe_lim.so (AEC / ANS / AGC)           |
|  - DSP Beamforming: libbf.v1.0.1.cv1826_release.so                            |
|  - ALSA Capture Device: /dev/snd/pcmC0D0c (hw:0,0 -> softvol_cap)             |
|  - Physical Inputs: Dual PDM Digital Mics (16 kHz / S16_LE / Mono)            |
+-------------------------------------------------------------------------------+
```

---

## 2. 音频采集 HAL 与零拷贝共享内存直通

### 2.1 ALSA 硬件采集规格与双 PDM 数字麦克风
- **采集设备节点**: `/dev/snd/pcmC0D0c` (`hw:0,0` 逻辑映射为 `softvol_cap`)。
- **硬件传感器**: 双路 PDM (Pulse Density Modulation) 数字 MEMS 麦克风，分布于笔顶部与笔尖扫描窗口侧。
- **原始采集规格**: 48,000 Hz, 双声道 (Stereo), 16-bit 有符号小端 (`S16_LE`)。
- **HAL 处理输出**: 16,000 Hz, 单声道 (Mono), 16-bit (`S16_LE`)，每毫秒 32 字节（20ms 分片 = 640 字节）。

### 2.2 DSP 波束成形与 AFE 降噪流水线
1. `libbf.v1.0.1.cv1826_release.so`：计算双麦克风相位差，增强正面说话人人声，衰减侧方环境杂音。
2. `libyoudao_afe_lim.so`：
   - **AEC 回声消除**：过滤 AW883XX SmartPA 扬声器自身发出的背景音。
   - **ANS 噪声抑制**：削减平稳白噪声与风噪。
   - **AGC 自动增益控制**：确保近距离大声说话不爆音。

### 2.3 POSIX 共享内存零拷贝环形缓冲区 (`writeShm`)
- `/oem/YoudaoDictPen/output/SoundRecord` 通过 `writeShm` 将 PCM 帧直写入 `/dev/shm/` 共享内存。
- 评测库 `libcapt.so` 直接在内存中获取指针（`capt_push_wav(char *buffer, int len)`），无 IPC 拷贝或 context-switch 损耗。

---

## 3. 语音识别引擎深度解构 (端云混合架构)

### 3.1 端侧离线口语评测引擎 (`libcapt.so`)
- 基于 Kaldi Chain 神经网络声学模型与 OpenFst 构成的嵌入式端侧评分器。
- 纯本地运行于 CV1813H Cortex-A7 处理器，输出单词音标、流利度、完整度与发音分值：
  ```json
  {
    "score": 92.5,
    "fluency": 90.0,
    "integrity": 95.0,
    "words": [
      { "word": "hello", "score": 94.0, "phonemes": "hh-ah-l-ow" }
    ]
  }
  ```

### 3.2 云端短语音 ASR 协议 (`getShortAsrOneTime`)
- 接口地址: `https://openapi.youdao.com/asrapi`
- 请求规范: HTTP Multipart POST，包含音频二进制流、`appKey`、`salt`、`curtime`，签名算法 `SHA256(appKey + truncate(q) + salt + curtime + appSecret)`。

### 3.3 唤醒词识别 (KWS) 与 VAD 静音切分
- **唤醒词引擎**: `YRecordCenter::startRemoteWkp()` 支持 "小道小道", "有道有道", "天猫精灵"。
- **VAD 判定**: 采用能量双门限检测，尾部静音阈值严格为 **800 ms**。检测到静音后立即自动触发 `stopSpeech()`，完成整句提交。

---

## 4. JSAPI 与跨进程 RPC 接口字典 (`record-service`)

RPC 目标 URI: `falcon://8001670668055425/record-service`

### 4.1 核心 RPC 指令集 (`sendCommand`)

| 指令名 | 参数规格 | 作用与底层调用 |
| :--- | :--- | :--- |
| `startRecord` | `()` | 启动 ALSA 录音至本地 WAV |
| `stopRecord` | `(continuesave: string)` | 停止录音并写盘 |
| `startCapt` | `(refText: string, param: string)` | 启动端侧口语打分 (`libcapt.so`) |
| `stopCapt` | `(saveWav: string, captId: string)` | 停止评测并输出评分 JSON |
| `setThresholdScore`| `(score: string)` | 设置及格阈值 |
| `setAccent` | `(accent: string)` | 设置口音 (`"en_US"`, `"en_UK"`) |
| `startSpeech` | `(key, secret, lang, mode)` | 发起流式云端语音识别会话 |
| `stopSpeech` | `(id, mode, type)` | 结束流式识别 |
| `getShortAsrOneTime`| `(audioPath, options)` | 单次单文件 OpenAPI ASR |

### 4.2 服务事件广播全集 (`proxy.on`)

| 事件名称 | 载荷参数 | 说明 |
| :--- | :--- | :--- |
| `asrResultChanged` | `{ text: string, isFinal: boolean }` | 流式 ASR 识别中间/最终文本 |
| `shortAsrOneTimeResult` | `{ code: number, text: string }` | 单次 OpenAPI ASR 识别结果 |
| `captResultChanged` | `{ score: number, words: Array }` | 完整口语评测打分结果 |
| `onRecordFileSaved` | `filePath: string` | 本地音频保存完成路径 |
| `selfWkpStatus` | `status: number` | 唤醒词监听状态 (`0`=休眠, `1`=唤醒) |

---

## 5. 生产级开发封装与完整示例代码

### 5.1 生产级 RPC 客户端 (`RecordServiceClient.js`)

```javascript
import $service_proxy from "$service_proxy";

const RECORD_SERVICE_URI = "falcon://8001670668055425/record-service";

export default class RecordServiceClient {
  constructor() {
    this.proxy = null;
    this.isConnected = false;
    this.tokenSet = new Set();
  }

  connect() {
    return new Promise((resolve, reject) => {
      if (this.isConnected && this.proxy) return resolve();
      this.proxy = new $service_proxy();
      this.proxy.onConnected = () => {
        this.isConnected = true;
        resolve();
      };
      this.proxy.onDisconnected = () => {
        this.isConnected = false;
      };
      try {
        this.proxy.connect(RECORD_SERVICE_URI);
      } catch (err) {
        reject(err);
      }
    });
  }

  on(eventName, handler) {
    if (!this.proxy) throw new Error("Not connected");
    const token = this.proxy.on(eventName, (payload) => {
      try {
        const data = typeof payload === "string" ? JSON.parse(payload) : payload;
        handler(data);
      } catch (_) {
        handler(payload);
      }
    });
    this.tokenSet.add(token);
    return token;
  }

  sendCommand(action, ...args) {
    if (!this.isConnected || !this.proxy) throw new Error("Not connected");
    return this.proxy.sendCommand(action, ...args);
  }

  startRecord() { return this.sendCommand("startRecord"); }
  stopRecord(continueSave = "true") { return this.sendCommand("stopRecord", continueSave); }
  startSpeech(appKey = "", secret = "", lang = "zh_CHS", mode = "online") {
    return this.sendCommand("startSpeech", appKey, secret, lang, mode);
  }
  stopSpeech(id = "0", mode = "online", type = "1") {
    return this.sendCommand("stopSpeech", id, mode, type);
  }
  startCapt(refText, param = "{}") { return this.sendCommand("startCapt", refText, param); }
  stopCapt(saveWav = "true", captId = "0") { return this.sendCommand("stopCapt", saveWav, captId); }
  setAccent(accent = "en_US") { return this.sendCommand("setAccent", accent); }

  destroy() {
    this.tokenSet.forEach((token) => {
      if (token && typeof token.off === "function") token.off();
    });
    this.tokenSet.clear();
    if (this.proxy) {
      this.proxy.disconnect();
      this.proxy = null;
    }
    this.isConnected = false;
  }
}
```
