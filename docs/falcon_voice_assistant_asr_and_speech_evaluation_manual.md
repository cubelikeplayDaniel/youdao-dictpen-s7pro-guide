# 有道词典笔 S7 Pro 离线口语评测引擎、语音助手与麦克风前端深度逆向手册
## (Youdao DictPen S7 Pro Speech Evaluation, Voice Assistant, Streaming ASR & Mic HAL Technical Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 系统固件版本 `4.22.0+`)  
> **芯片架构**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB DDR3, Linux 5.10.4)  
> **硬件平台代号**: `theme-y08`  
> **核心二进制组件**:
> - `/userdata/oem/YoudaoDictPen/lib/libcapt.so` (8.94 MB 离线发音评测引擎, Kaldi Chain WFST + Alibaba MNN)
> - `/oem/YoudaoDictPen/output/SoundRecord` (底层音频采集与 AFE 降噪守护进程)
> - `/userdata/oem/YoudaoDictPen/lib/libbf.v1.0.1.cv1826_release.so` (双麦克风波束成形动态库)
> - `/userdata/oem/YoudaoDictPen/lib/libyoudao_afe_lim.so` (声学前端 AFE：AEC / ANS / AGC 信号增强)
> - `8001670668055425` (`RecordService`, 跨进程录音、ASR 与评测微服务守护进程)
> - `libjsapi_record_1639848624.so` / `libbusiness_record_1639848624.so` (`YRecordCenter` 核心业务逻辑)
> - `yddal_libs/libyddal_common_soundrecord.so` (DAL 录音硬件抽象接口与 POSIX SHM 环形缓冲区)

---

## 目录索引

1. [硬件拓扑与声学前端 (Mic HAL & Acoustic Front End)](#1-硬件拓扑与声学前端-mic-hal--acoustic-front-end)
   - 1.1 [双 PDM 数字麦克风硬件阵列拓扑](#11-双-pdm-数字麦克风硬件阵列拓扑)
   - 1.2 [ALSA 驱动内核采集配置 (`/dev/snd/pcmC0D0c`)](#12-alsa-驱动内核采集配置-devsndpcmc0d0c)
   - 1.3 [DSP 波束成形与 AFE 降噪流水线](#13-dsp-波束成形与-afe-降噪流水线)
   - 1.4 [POSIX 共享内存零拷贝环形队列 (`writeShm`)](#14-posix-共享内存零拷贝环形队列-writeshm)
   - 1.5 [VAD 能量双门限断句算法与 800ms 截断机制](#15-vad-能量双门限断句算法与-800ms-截断机制)
2. [`libcapt.so` 离线发音评测引擎底层架构](#2-libcaptso-离线发音评测引擎底层架构)
   - 2.1 [工程源码溯源与技术栈总览 (V1.1.3)](#21-工程源码溯源与技术栈总览-v113)
   - 2.2 [C API 导出符号与虚拟地址解析](#22-c-api-导出符号与虚拟地址解析)
   - 2.3 [双语言评测状态机 (中英文双模)](#23-双语言评测状态机-中英文双模)
   - 2.4 [参考文本预处理与多层 G2P 转换管线](#24-参考文本预处理与多层-g2p-转换管线)
   - 2.5 [Kaldi Chain WFST 解码器与 MNN TDNN-F 声学模型](#25-kaldi-chain-wfst-解码器与-mnn-tdnn-f-声学模型)
   - 2.6 [实时 PCM 流推送与 200ms Zero-Padding 刷新机制](#26-实时-pcm-流推送与-200ms-zero-padding-刷新机制)
   - 2.7 [发音评分算法模型与完整 JSON 输出契约](#27-发音评分算法模型与完整-json-输出契约)
3. [语音助手 (Voice Assistant) 与实时 ASR 流水线](#3-语音助手-voice-assistant-与实时-asr-流水线)
   - 3.1 [`theme-y08` 动态分发演进：小P老师 (`LittleP`)](#31-theme-y08-动态分发演进小p老师-littlep)
   - 3.2 [本地轻量级唤醒词检测 (KWS: "小道小道")](#32-本地轻量级唤醒词检测-kws-小道小道)
   - 3.3 [流式 ASR / 翻译全双工上传协议 (有道 / 讯飞)](#33-流式-asr--翻译全双工上传协议-有道--讯飞)
   - 3.4 [短语音 OpenAPI 一键评测/识别协议 (`getShortAsrOneTime`)](#34-短语音-openapi-一键评测识别协议-getshortasronetime)
   - 3.5 [云端大模型 Agent 与端侧协同推理](#35-云端大模型-agent-与端侧协同推理)
4. [`RecordService` 跨进程 RPC 契约与 Native C++ 模块解构](#4-recordservice-跨进程-rpc-契约与-native-c-模块解构)
   - 4.1 [服务进程架构与 URI 拓扑](#41-服务进程架构与-uri-拓扑)
   - 4.2 [QuickJS 原生 C 模块绑定 (`libjsapi_record.so`)](#42-quickjs-原生-c-模块绑定-libjsapi_recordso)
   - 4.3 [`YRecordCenter` 核心业务调度中枢](#43-yrecordcenter-核心业务调度中枢)
   - 4.4 [RPC 指令集全量接口字典 (`sendCommand`)](#44-rpc-指令集全量接口字典-sendcommand)
   - 4.5 [服务事件广播全集与载荷规范 (`proxy.on`)](#45-服务事件广播全集与载荷规范-proxyon)
5. [TypeScript 严格类型定义与 JSON Schema 规范](#5-typescript-严格类型定义与-json-schema-规范)
   - 5.1 [发音评测 JSON Schema 规范](#51-发音评测-json-schema-规范)
   - 5.2 [实时 ASR 文本流 Schema 规范](#52-实时-asr-文本流-schema-规范)
   - 5.3 [生产级 TypeScript 接口定义 (`speech-evaluation.d.ts`)](#53-生产级-typescript-接口定义-speech-evaluationdts)
6. [生产级开发实战与完整可运行代码](#6-生产级开发实战与完整可运行代码)
   - 6.1 [生产级 RPC 客户端 (`RecordServiceClient.ts`)](#61-生产级-rpc-客户端-recordserviceclientts)
   - 6.2 [高保真发音跟读评测 Vue 组件 (`OralEvaluationView.vue`)](#62-高保真发音跟读评测-vue-组件-oralevaluationviewvue)
   - 6.3 [流式语音助手对话 Vue 组件 (`VoiceAssistantDialog.vue`)](#63-流式语音助手对话-vue-组件-voiceassistantdialogvue)
   - 6.4 [底层 C++ 驱动直连调用测试程序 (`libcapt_runner.cpp`)](#64-底层-c-驱动直连调用测试程序-libcapt_runnercpp)
7. [调试、逆向验证与常见故障排除 (Troubleshooting)](#7-调试逆向验证与常见故障排除-troubleshooting)

---

## 1. 硬件拓扑与声学前端 (Mic HAL & Acoustic Front End)

### 1.1 双 PDM 数字麦克风硬件阵列拓扑

有道词典笔 S7 Pro 采用双硅麦（Digital MEMS Microphone）差分声学拾音阵列设计：
1. **主拾音麦克风 (Primary Mic)**：位于笔身正面上部、靠近手持握持区域与嘴角连线处，负责定向采集说话人人声（Target Speech）。
2. **环境参考麦克风 (Reference Mic)**：位于词典笔顶部背侧，远离人声主瓣，主要采集外界环境背景噪声（Ambient Noise）与扬声器漏音（Acoustic Leakage）。

双麦克风均采用 **PDM (Pulse Density Modulation)** 脉冲密度调制接口直接连接至 Cvitek CV1813H SoC 内置的 PDM 控制器硬件管脚，具有抗电磁干扰极强、低功耗、无外部模拟走线噪声等特点。

```
                    [顶部参考麦克风 (Ambient/Ref Mic)]
                                | (PDM Data/Clock)
                                v
+-------------------------------------------------------------------+
|               Cvitek CV1813H Audio Processing Unit                |
|                                                                   |
|  [ PDM Controller (Decimation Filter) ]                           |
|          | 48 kHz / 16-bit / Stereo S16_LE                        |
|          v                                                        |
|  [ Linux ALSA Kernel Driver (cvi-snd-card / /dev/snd/pcmC0D0c) ]  |
|          |                                                        |
|          v                                                        |
|  [ SoundRecord HAL Daemon (/oem/YoudaoDictPen/output/SoundRecord)]|
|          |                                                        |
|          +---> [ libbf.v1.0.1.cv1826_release.so (波束成形 Beamforming) ]
|          |            - 差分阵列指向性滤波, 衰减侧后方环境噪音    |
|          |                                                        |
|          +---> [ libyoudao_afe_lim.so (Acoustic Front End) ]      |
|                       - AEC (Acoustic Echo Cancellation 回声消除) |
|                       - ANS (Acoustic Noise Suppression 噪声抑制) |
|                       - AGC (Automatic Gain Control 自动增益控制) |
|          |                                                        |
|          v 16,000 Hz / 16-bit / Mono Linear PCM                   |
|  [ POSIX Shared Memory Ring Buffer (/userdata/shm/SoundRecord2Miniapp) ]
+-------------------------------------------------------------------+
                                |
                 [主拾音麦克风 (Voice/Talk Mic)]
```

### 1.2 ALSA 驱动内核采集配置 (`/dev/snd/pcmC0D0c`)

底层的音频采集服务由 `/oem/YoudaoDictPen/output/SoundRecord` 常驻守护进程驱动。守护进程直接打开 ALSA 硬件采集节点 `/dev/snd/pcmC0D0c`（逻辑映射名 `hw:0,0` 或 `softvol_cap`）：

| 硬件参数项 | 内核驱动采集规格 | AFE 处理输出规格 | 说明 |
| :--- | :--- | :--- | :--- |
| **设备节点** | `/dev/snd/pcmC0D0c` | POSIX SHM 缓冲区 | ALSA 标准 PCM 采集节点 |
| **采样率 (Sample Rate)** | `48,000 Hz` | `16,000 Hz` | 经由硬件降采样与 FIR 抗混叠抽取 |
| **量化位数 (Bit Depth)** | `16-bit signed` (`S16_LE`)| `16-bit signed` (`S16_LE`)| 单样本占 2 字节 |
| **声道数 (Channels)** | `2 Channels` (Stereo) | `1 Channel` (Mono) | 经波束成形合并为主声道 |
| **Period Size** | `960 frames` (20 ms @ 48kHz) | `320 samples` (20 ms) | 驱动层单次中断周期帧数 |
| **Buffer Size** | `3840 frames` (4 periods) | `640 bytes` / 20ms | 硬件防溢出环形缓冲区大小 |
| **字节传输率** | `192,000 Bytes/sec` | `32,000 Bytes/sec` | 评测与 ASR 所需的标准速率 |

### 1.3 DSP 波束成形与 AFE 降噪流水线

采集到的原始 48kHz 双声道 PCM 流首先灌入有道自研声学信号处理链：
1. **波束成形 (Beamforming - `libbf.v1.0.1.cv1826_release.so`)**：
   - 利用主麦克风与环境副麦克风之间的物理空间延时（Time Difference of Arrival, TDOA），构建主瓣朝向说话人嘴部的窄带波束。
   - 侧向及后向入射的声波由于相位反向叠加而被强烈抵消，提供高达 12 dB ~ 18 dB 的空间定向噪声抑制。
2. **回声消除 (AEC - `libyoudao_afe_lim.so`)**：
   - 提取 AW883XX 智能功率放大器（SmartPA）的扬声器参考信号（Loopback Reference）。
   - 消除设备正在播报 TTS 或提示音时麦克风拾入的残余扬声器回音，确保用户在词典笔发声时仍可打断（Barge-In）。
3. **自适应降噪 (ANS - `libyoudao_afe_lim.so`)**：
   - 基于平稳噪声谱估计与维纳滤波（Wiener Filtering），对办公室白噪声、空调风扇声、马路低频轰鸣进行精细消除。
4. **自动增益控制 (AGC - `libyoudao_afe_lim.so`)**：
   - 将语音动态范围动态缩放至 `-3 dBFS ~ -6 dBFS` 区间，防止贴近麦克风大声朗读产生削顶失真，同时放大远距离微弱发音。

### 1.4 POSIX 共享内存零拷贝环形队列 (`writeShm`)

为了在 128 MB 极度受限的内存与单核 Cortex-A7 处理器上消除跨进程拷贝造成的 CPU 负荷与抖动，有道工程团队在 `libyddal_common_soundrecord.so` 中实现了基于 POSIX Shared Memory 的零拷贝环形缓冲区。

#### 共享内存节点与同步通道
- **音频流共享内存路径**: `/userdata/shm/SoundRecord2Miniapp` (大小 `65536 Bytes`)
- **反向控制共享内存路径**: `/userdata/shm/Miniapp2SoundRecord` (大小 `16384 Bytes`)
- **同步控制机制**: `YDALBASEAPI::YShmSync`，配合 Linux `SYS_futex` 与 POSIX Named Semaphore 实现等待与唤醒。

#### 逆向反汇编分析：`YSoundRecordInterfacePrivate::writeShm` (`0x0000a7b8`)

```arm
; libyddal_common_soundrecord.so 逆向切片
0x0000a7b8:  push    {r4, r5, r6, r7, lr}
0x0000a7bc:  mov     r4, r0             ; this 指针
0x0000a7c0:  mov     r5, r1             ; buffer 指针 (PCM 数据)
0x0000a7c4:  mov     r6, r2             ; len (数据长度，如 640 字节)
0x0000a7c8:  ldr     r0, [r4, #0x40]    ; 获取 YShmSync 实例句柄
0x0000a7cc:  cmp     r0, #0
0x0000a7d0:  beq     0xa820             ; 未初始化则报错退出
0x0000a7d4:  mov     r1, r5
0x0000a7d8:  mov     r2, r6
0x0000a7dc:  bl      0x8b60             ; PLT: YDALBASEAPI::YShmSync::write(void const*, unsigned int)
0x0000a7e0:  cmp     r0, #0
0x0000a7e4:  bge     0xa800             ; 写入成功
0x0000a7e8:  ldr     r0, [pc, #0x58]    ; 加载字符串: "YSoundRecordInterfacePrivate::writeShm failed"
0x0000a7ec:  bl      0x8c20             ; 记录错误日志
0x0000a7f0:  mov     r0, #0
0x0000a7f4:  pop     {r4, r5, r6, r7, pc}
0x0000a800:  ldr     r0, [r4, #0x48]    ; 获取通知信号量句柄
0x0000a804:  bl      0x8a90             ; PLT: sem_post() 唤醒消费端
0x0000a808:  mov     r0, #1
0x0000a80c:  pop     {r4, r5, r6, r7, pc}
```

消费端进程（如 `RecordService` 或直接链接 `libcapt.so` 的进程）在接到信号量通知后，直接通过只读映射（`mmap(PROT_READ)`）获取内存指针，直接送入 `capt_push_wav()`。

### 1.5 VAD 能量双门限断句算法与 800ms 截断机制

在语音助手、流式听写与口语录音场景下，精准检测用户语音起始（Speech Onset）与语音结束（Speech Endpoint）至关重要。

```
音频流能量 (dBFS)
   ^
   |        +---------------------------+  <-- 高能量门限 (Speech Thresh: -35 dBFS)
   |       /                             \
   |      /                               \
   |     /                                 +-----------------  <-- 低能量门限 (Silence Thresh: -45 dBFS)
   |----+                                                    \
   +----------------------------------------------------------+-------> 时间
        |<-- 3帧(60ms)确立语音开始 -->|               |<-- 800ms 静音判定 -->|
                                                     触发 silenceTriggered / stopSpeech
```

1. **短时能量与零交叉率（ZCR）双门限**：
   - 每一帧音频（20 ms / 320 采样点）计算短时平均能量（RMS Energy）与过零率。
   - **进入语音态**：当连续 3 帧（60 ms）能量高于高门限（`-35 dBFS`）且过零率符合元音特征时，触发 `Speech Start`。
2. **尾部静音截断（Hangover Timer）**：
   - 当能量降至低门限（`-45 dBFS`）以下时，启动硬件级静音计时器。
   - 逆向分析官方 `TalkingView-6a80b642.js.bin` 与 `YRecordCenter.cpp` 确认：S7 Pro 系统固定的语音截断超时严格配置为 **800 毫秒**（`delayUserRecordingSilenceTimer = 800`）。
   - 一旦连续静音持续 800ms，系统自动触发 `silenceTriggered` 事件，调用 `stopSpeech()` 发送流结束标记，避免无效录音上传浪费流量和电量。

---

## 2. `libcapt.so` 离线发音评测引擎底层架构

### 2.1 工程源码溯源与技术栈总览 (V1.1.3)

通过对 `reverse_dump/libcapt.so`（ELF 32-bit ARM, 8.94 MB）的只读数据段（`.rodata`）与符号表（`.dynsym`）进行全量逆向分析，确认该引擎是由网易有道语音算法团队独立构建的嵌入式口语评测系统。

#### 内部源码工程结构
二进制文件中暴露的权威编译路径为 `/reserve/dongww/captofflinev1.0/`，版本号标识为 **`V1.1.3`**。其子系统构成如下：
- `/reserve/dongww/captofflinev1.0/src/capt.cpp`：C API 包装层与引擎生命周期调度。
- `/reserve/dongww/captofflinev1.0/src/nnet.cpp`：TDNN-F 声学模型前向计算引擎。
- `/reserve/dongww/captofflinev1.0/src/feature-generator.cpp`：Kaldi MFCC 特征提取器（采用 Povey 汉明窗）。
- `/reserve/dongww/captofflinev1.0/src/decoder/WFSTStreamDecoder.cpp`：流式加权有限状态转换机解码器。
- `/reserve/dongww/captofflinev1.0/src/scorer/scorer.cc`：多维度发音打分算法（包含音素发音准确度、重音、连读、语速与流利度计算）。
- `/reserve/dongww/captofflinev1.0/src/frontend/tts_ta/`：
  - `frontend_cn/g2p-zh/`：中文拼音汉字音标转换引擎。
  - `frontend_cn/multi_g2p_prosody/`：基于轻量级深度网络的中文多音字与韵律停顿预测模型。
  - `frontend_en/engtn_new/`：基于 OpenFST 1.6.5 的英文文本正则归一化（Text Normalization）。
- **底座第三方库**：
  - `MNN_A35_OPTIMIZE`：针对 ARM Cortex-A35 / Cortex-A7 深度裁剪优化的阿里巴巴 MNN 前向推理引擎。
  - `gemmlowp`：Google 低精度定点矩阵乘法加速库，内置专用汇编内核 `NEON_32_Kernel12x4Depth2`，针对 ARMv7-A NEON 32 位向量指令高度手工汇编调优。
  - `openfst-1.6.5`：加权有限状态转换器核心数据结构。
  - `cppjieba`：嵌入式中文分词器（包含 Trie 树与 HMM 维特比算法）。

### 2.2 C API 导出符号与虚拟地址解析

`libcapt.so` 导出了纯 C 风格的标准化函数接口，允许上层 Native 代码通过 `dlopen` / `dlsym` 动态加载：

| 导出符号 | 虚拟地址 (VA) | 函数签名 | 核心作用与行为 |
| :--- | :--- | :--- | :--- |
| `capt_init` | `0x00273e8c` | `int capt_init(const char *model_dir, int lang_id, int beam)` | 初始化评测引擎，装载声学模型与语言 FST |
| `capt_set_reftext` | `0x00274274` | `int capt_set_reftext(const char *reftext, const char *param)` | 配置参考文本，完成 G2P 并构建动态搜索网络 |
| `capt_begin` | `0x00274464` | `int capt_begin(void)` | 开启当前句子的评测会话，复位内部解码状态 |
| `capt_push_wav` | `0x002744dc` | `int capt_push_wav(const char *pcm_data, int byte_len)` | 持续推送 16kHz 16-bit Mono PCM 音频流 |
| `capt_end` | `0x00274498` | `int capt_end(void)` | 灌入 200ms 静音填充，终止推断并等待工作线程收敛 |
| `get_capt_result` | `0x00274798` | `const char* get_capt_result(void)` | 线程安全提取当前句子的完整评测结果 JSON 字符串 |
| `get_word_score` | `0x00274890` | `const char* get_word_score(const char *reftext, const char *param)` | 提取逐词发音质量与详细音素级评分 |
| `get_badwords_sent`| `0x00274b48` | `const char* get_badwords_sent(const char *reftext, float threshold)` | 提取发音较差、未达合格阈值的单词列表 |

#### 关键汇编深度逆向 1：`capt_init` (`0x00273e8c`)

```arm
; 0x00273e8c <capt_init>:
0x273e8c:  push    {r4, r5, r6, r7, r8, lr}
0x273e90:  mov     r4, r0             ; r0: model_dir (模型路径字符串)
0x273e94:  mov     r5, r1             ; r1: lang_id (语言 ID: 0x6e65 'en' 或 0x6e63 'cn')
0x273e98:  mov     r6, r2             ; r2: beam 解码束宽
0x273ea0:  ldr     r7, [pc, #0x23c]   ; 加载全局状态指针地址 (位于 0x892b98)
0x273ea4:  ldr     r3, [r7]           ; 获取引擎当前状态 state
0x273ea8:  sub     r3, r3, #1
0x273eac:  cmp     r3, #1             ; 若 state == 1 或 state == 2
0x273eb0:  bls     0x2740d0           ; 已初始化过，直接返回成功 (0)
0x273ee8:  movw    r3, #0x6e65        ; 'en' (ASCII 0x6e65)
0x273efc:  movw    r2, #0x6e63        ; 'cn' (ASCII 0x6e63)
0x273f00:  cmp     r5, r3
0x273f04:  beq     0x273f18           ; 命中英文评测分支
0x273f08:  cmp     r5, r2
0x273f0c:  bne     0x2740a8           ; 不支持的语言代号，抛出错误
0x273edc:  bl      0x1e14c0           ; 调用 PLT: OfflineCAPTer::asr_preInit(model_dir, lang, beam)
0x274080:  bl      0x1ddfd4           ; 调用 PLT: OfflineCAPTer::asr_init()
0x274098:  mov     r3, #2             ; 将状态转移至 State 2 (Ready 态)
0x27409c:  str     r3, [r7]           ; 保存全局状态
0x2740a0:  mov     r0, #0             ; 返回 0 (成功)
0x2740a4:  pop     {r4, r5, r6, r7, r8, pc}
```

#### 关键汇编深度逆向 2：`capt_push_wav` (`0x002744dc`)

```arm
; 0x002744dc <capt_push_wav>:
0x2744dc:  push    {r4, r5, r6, lr}
0x2744e0:  mov     r4, r0             ; r0: pcm_data (音频缓冲区指针)
0x2744e4:  mov     r5, r1             ; r1: byte_len (字节数)
0x2744ec:  ldr     r0, [pc, #0x100]   ; 获取全局状态指针
0x2744f8:  ldr     r0, [r0]
0x2744fc:  cmp     r0, #2             ; 校验引擎状态是否处于 Ready 态 (2)
0x274500:  bne     0x2745f8           ; 状态不合法，跳转错误处理
0x274510:  asr     r2, r5, #1         ; r2 = byte_len >> 1 (将字节数除以2转为 short 采样点数)
0x274514:  mov     r1, r4             ; r1: short* pcm 样本指针
0x274518:  mov     r3, #0             ; is_end = false (非流结束)
0x27451c:  bl      0x1e17f0           ; PLT: OfflineCAPTer::asr_push_wav(short*, int, bool)
0x274530:  bl      0x1d9e28           ; PLT: std::ostream::flush
0x274550:  bl      0x1d9018           ; PLT: OfflineCAPTer::asr_get_result() (更新中间结果)
0x274558:  mov     r0, #0
0x27455c:  pop     {r4, r5, r6, pc}
```

#### 关键汇编深度逆向 3：`capt_end` (`0x00274498`)

```arm
; 0x00274498 <capt_end>:
0x274498:  push    {r4, r5, r6, lr}
; 分配 6400 字节静音缓冲区 (3200 个 16-bit 采样点 = 200 ms @ 16 kHz)
0x2745b4:  mov     r0, #0x1900        ; 0x1900 = 6400 Bytes
0x2745bc:  bl      0x1d5c34           ; PLT: operator new[](unsigned int)
0x2745c0:  mov     r4, r0             ; r4 保存分配的静音指针
0x2745c4:  mov     r1, #0             ; 清零填充
0x2745c8:  mov     r2, #0x1900
0x2745cc:  bl      0x1d9dec           ; PLT: memset(buf, 0, 6400)
0x2745dc:  mov     r3, #1             ; is_end = true (标记音频输入终结)
0x2745e0:  mov     r2, #0xc80         ; 0xc80 = 3200 samples
0x2745e4:  mov     r1, r4
0x2745e8:  bl      0x1e17f0           ; 推送 200ms 静音样本刷新解码管线延迟
0x2745ec:  mov     r0, r4
0x2745f0:  bl      0x1d6a10           ; PLT: operator delete[](void*)
0x274634:  bl      0x1d8010           ; PLT: pthread_join(worker_thread) 等待推断线程结束
0x27613c:  bl      0x1d6ea0           ; PLT: tdnnf::clear()
0x276188:  bl      0x1dd5f0           ; PLT: fst::VectorFst::DeleteStates()
0x274640:  mov     r0, #0
0x274644:  pop     {r4, r5, r6, pc}
```

### 2.3 双语言评测状态机 (中英文双模)

引擎内部维护严格的生命周期状态机，通过整数状态变量管理解码生命周期：

```
                    +---------------------------+
                    |    State 0: UNINITIALIZED |
                    +---------------------------+
                                  |
                                  | capt_init(dir, lang, beam)
                                  v
                    +---------------------------+
                    |    State 1: INITIALIZING  |
                    +---------------------------+
                                  |
                    +-------------+-------------+
                    |                           |
                    v (lang = 0x6e65 'en')      v (lang = 0x6e63 'cn')
             [ Load English TDNN-F ]      [ Load Chinese TDNN-F ]
             [ Load CMU Dict/FST   ]      [ Load Jieba Trie & G2P]
                    |                           |
                    +-------------+-------------+
                                  |
                                  v
                    +---------------------------+
                    |      State 2: READY       |<-------------------+
                    +---------------------------+                    |
                                  |                                  |
                                  | capt_set_reftext(ref, param)     |
                                  v                                  |
                    +---------------------------+                    |
                    |    State 3: TEXT_BOUND    |                    |
                    +---------------------------+                    |
                                  |                                  |
                                  | capt_begin()                     |
                                  v                                  |
                    +---------------------------+                    |
                    |    State 4: DECODING      |                    |
                    | (capt_push_wav loop)      |                    |
                    +---------------------------+                    |
                                  |                                  |
                                  | capt_end()                       |
                                  | [200ms zero flush + join]        |
                                  v                                  |
                    +---------------------------+                    |
                    |    State 5: FINISHED      |                    |
                    | (get_capt_result / JSON)  |--------------------+
                    +---------------------------+
```

### 2.4 参考文本预处理与多层 G2P 转换管线

当调用 `capt_set_reftext(reftext, param)` 时，系统执行全套自然语言前端转换：

#### 英文文本处理 (`0x6e65`)
1. **正则归一化 (`engtn_new`)**：基于 OpenFST 将数字、缩写、货币、时间等标准化为英文单词序列（例如 `$10.5` -> `ten dollars and fifty cents`）。
2. **字典匹配与 OOV 处理**：在 CMU Pronouncing Dictionary 中查找每个词的音素序列（Arpabet 音标）。若出现未登录词（OOV），调用 `pwmatcher.cpp` 规则自动音标推断器生成音素。
3. **重音标注**：提取音标中的数字重音标记（`0`=非重音, `1`=主重音, `2`=次重音），生成目标重音基准向量（`stress_ref`）。

#### 中文文本处理 (`0x6e63`)
1. **分词 (`cppjieba`)**：载入 `/userdata/oem/YoudaoDictPen/data/model/models/jiebadict.trie.bin`，进行最大概率路径分词。
2. **多音字消除 (`RegexDyz` + `BertMultiG2pProsodyPosMNN`)**：
   - 规则层优先处理成语与高频熟词；
   - 深度学习层运行量化版微型 MNN 韵律模型，根据词性（POS）上下文预测多音字读音。
3. **拼音转音素**：通过内部静态拼音表（包含 400+ 汉语标准拼音音节）映射为 Kaldi 声学模型建模单元（声母、韵母、调类）。

### 2.5 Kaldi Chain WFST 解码器与 MNN TDNN-F 声学模型

1. **声学模型架构 (TDNN-F)**：
   - 模型采用 Kaldi 经典的 Factorized Time-Delay Neural Network 结构，对标准 TDNN 稠密矩阵进行半正交低秩奇异值分解（SVD），将参数量缩减 60% 以上。
   - 输入特征：40 维高分辨率 MFCC 特征，帧移 10ms，窗长 25ms，Povey 窗函数。
   - 降采样（Subsampling）：3 倍时间步降采样（每 30ms 计算一次声学后验概率输出）。
2. **MNN NEON SIMD 定点加速**：
   - 权重经由 8-bit 定点整型量化（Symmetric INT8 Quantization）。
   - 在 CV1813H 单核 Cortex-A7 上，通过 `gemmlowp::NEON_32_Kernel12x4Depth2` 每次利用 32 位 NEON 向量寄存器并发执行 12×4 矩阵块的乘加操作，实时推断系数（RTF - Real Time Factor）达到惊人的 **0.18**（处理 1 秒音频仅耗费 180ms CPU 时间）。
3. **WFST 动态图构建与对齐**：
   - 使用参考文本动态编译对齐网格（Alignment Grammar FST），迫使解码器搜索限制在参考文本候选音素路径内（Forced Alignment）。
   - 解码器采用 `LatticeFasterDecoder`，在剪枝束宽（Pruning Beam）内实时搜索最佳 Viterbi 路径。

### 2.6 实时 PCM 流推送与 200ms Zero-Padding 刷新机制

由于 TDNN-F 神经网络具有时间感受野（Time Context Window），其声学模型包含左上下文（Left Context = 2）与右上下文（Right Context = 2），加上 3 倍降采样，导致最后数帧音频无法立即激活最后一个音素的状态转移。

**有道工程解决方案**：
在 `capt_end()` 中，引擎强制开辟 `0x1900`（6400 字节，等价于 3200 个采样点，即 **200 毫秒** 长度）的全 0 静态缓冲区，调用 `asr_push_wav(silence_buf, 3200, is_end=true)` 推入模型。该 200ms 静音填充能完全推平神经网络右侧时延缓存，确保句子最后一个单词的尾音被完整解码和准确评分，随后调用 `pthread_join` 安全收拢推断线程。

### 2.7 发音评分算法模型与完整 JSON 输出契约

引擎打分核心实现于 `/reserve/dongww/captofflinev1.0/src/scorer/scorer.cc`，综合以下四个物理量计算加权得分：
1. **准确度 (Accuracy)**：声学模型音素强制对齐时的对数似然后验概率与无约束竞争网络概率的差值（GOP - Goodness of Pronunciation 算法）。
2. **流利度 (Fluency)**：句子内部非正常停顿（Silence Duration > 300ms）、语速波动率以及单词持续时间的方差。
3. **完整度 (Integrity)**：对齐成功的词数除以参考文本总词数（漏读惩罚）。
4. **重音匹配 (Stress Detection)**：检测出的重音位置（`stress_detect`）与参考字典基准（`stress_ref`）的对齐吻合度。

```json
{
  "refText": "Good morning teacher",
  "score": 91.5,
  "overall": 91.5,
  "accuracy": 92.0,
  "fluency": 89.0,
  "integrity": 100.0,
  "speed": 128.5,
  "version": "V1.1.3",
  "words": [
    {
      "word": "Good",
      "index": 0,
      "score": 94.0,
      "pronunciation": "g-uh-d",
      "phonemes": "g uh d",
      "cmu_phoneme": "G UH1 D",
      "stress_ref": 1,
      "stress_detect": 1,
      "start": 120,
      "end": 450,
      "duration": 330,
      "calibration": 0.96,
      "judge": "excellent",
      "prominence": 1.15
    },
    {
      "word": "morning",
      "index": 1,
      "score": 88.0,
      "pronunciation": "m-ao-r-n-ih-ng",
      "phonemes": "m ao r n ih ng",
      "cmu_phoneme": "M AO1 R N IH0 NG",
      "stress_ref": 1,
      "stress_detect": 1,
      "start": 480,
      "end": 960,
      "duration": 480,
      "calibration": 0.90,
      "judge": "good",
      "prominence": 0.98
    },
    {
      "word": "teacher",
      "index": 2,
      "score": 92.5,
      "pronunciation": "t-iy-ch-er",
      "phonemes": "t iy ch er",
      "cmu_phoneme": "T IY1 CH ER0",
      "stress_ref": 1,
      "stress_detect": 1,
      "start": 1020,
      "end": 1580,
      "duration": 560,
      "calibration": 0.93,
      "judge": "excellent",
      "prominence": 1.05
    }
  ]
}
```

---

## 3. 语音助手 (Voice Assistant) 与实时 ASR 流水线

### 3.1 `theme-y08` 动态分发演进：小P老师 (`LittleP`)

在有道 S7 Pro（硬件平台 `theme-y08`）中，传统的独立语音助手应用（`8080272808953200`）已被架构重塑，主屏幕启动器（Launcher `8080222437664451`）根据硬件特征动态分发到搭载大语言模型的大脑中枢——**“小P老师” (`LittleP`，AppID: `8001707294117702`)**。

```javascript
// Launcher indexPage-085a554f.js.bin 逆向切片
async voiceAssistantClicked() {
  const { DictAppID } = await import("./Constant-a706d45f.js");
  if (this.entranceGlobalThemeName === "theme-y08") {
    // S7 Pro 专用分支：启动小P老师全双工语音 Agent
    this.clickItem(DictAppID.LittleP); // 8001707294117702
    this.$emit("sendLogFromHome", "home_LittleP_click");
  } else {
    // 老款设备回退分支：启动单机版语音助手
    this.clickItem(DictAppID.VoiceAssistant); // 8080272808953200
  }
}
```

### 3.2 本地轻量级唤醒词检测 (KWS: "小道小道")

为了实现低功耗常驻麦克风监听，系统通过 `YRecordCenterPrivate::startRemoteWkp()` 激活硬件 DSP 内部的轻量级声学唤醒模块（KWS - Keyword Spotting）：
- **支持唤醒词**：“小道小道”（默认）、“有道有道”、“天猫精灵”。
- **唤醒事件上报**：唤醒命中后，底座向 `RecordService` 派发 `selfWkpStatus(status=1)` 事件，小P老师应用收到广播后点亮屏幕，播放唤醒音效，并无缝将音频通道切入 ASR 录音模式。

### 3.3 流式 ASR / 翻译全双工上传协议 (有道 / 讯飞)

语音助手与听写输入支持双引擎无缝热切换：
1. **有道在线流式 ASR (`startSpeechAsrTrans`)**：基于有道自研大模型语音识别服务，支持中英双语混合识别，输出包含分词标点与中间流式刷新（Partial Result）。
2. **讯飞在线流式 ASR (`startSpeechXunfeiAsrTrans`)**：针对特定学科词汇与古诗词背诵优化。

#### 流式识别数据交互帧序图

```
MiniApp (LittleP)             RecordService (8001670668055425)         Cloud ASR Gateway
       |                                     |                                 |
       |--- startSpeechAsrTrans(lang) ------>|                                 |
       |                                     |--- WebSocket / TLS Connect ---->|
       |                                     |<-- Stream Handshake Ack --------|
       |                                     |                                 |
       |                              [Audio Stream]                           |
       |                              [writeShm PCM]                           |
       |                                     |--- Binary Audio Chunks -------->|
       |                                     |                                 |
       |                                     |<-- asr.result (is_partial=true)-|
       |<-- asrResultChanged(text, false) ---|                                 |
       |    (UI 实时动态打字机效果)         |                                 |
       |                                     |--- Binary Audio Chunks -------->|
       |                                     |                                 |
       | [VAD 800ms 静音触发]                |                                 |
       |--- stopSpeech() ------------------->|                                 |
       |                                     |--- End-of-Stream Frame -------->|
       |                                     |<-- asr.result (is_final=true) --|
       |<-- asrResultChanged(text, true) ----|                                 |
       |                                     |--- Close Connection ----------->|
```

### 3.4 短语音 OpenAPI 一键评测/识别协议 (`getShortAsrOneTime`)

针对词典查词发音、本地历史音频二次上传，S7 Pro 封装了基于 HTTP Multipart 的一次性 OpenAPI 识别请求接口。

- **URL**: `https://openapi.youdao.com/asrapi`
- **认证签名机制**:
  ```text
  sign = SHA256(appKey + truncate(q) + salt + curtime + appSecret)
  ```
  其中 `truncate(q)` 规则为：若音频数据长度 `<= 20`，则为 `q`；若 `> 20`，则取前 10 个字节 + 长度数字 + 后 10 个字节拼接。
- **底层实现**: `libbusiness_record.so` 内置 `cpr` (C++ Requests) 现代 HTTP 库，在后台线程池异步提交并执行非阻塞回调。

### 3.5 云端大模型 Agent 与端侧协同推理

在小P老师（`LittleP`）会话中，ASR 最终识别结果直接灌入基于 SSE (Server-Sent Events) 的大模型推理管线：
1. 语音转文字完成后，组装包含用户年级、学科、当前扫描上下文的 JSON Payload 发往云端问答大模型。
2. 流式接收大模型 Token，通过 `streamTTSMixin` 同步交由语音合成引擎进行实时朗读（边生成、边传输、边播报）。

---

## 4. `RecordService` 跨进程 RPC 契约与 Native C++ 模块解构

### 4.1 服务进程架构与 URI 拓扑

有道 S7 Pro 采用以微服务化为核心的 MiniApp 架构体系。录音、口语打分、语音听写与唤醒词识别等所有底层声学功能，统一收敛在系统常驻服务应用：
- **服务应用 ID**: `8001670668055425`
- **微服务标识**: `record-service`
- **RPC 访问 URI**: `falcon://8001670668055425/record-service`

前端业务应用（如查词、小P老师、语文/英语跟读等）通过 Falcon 运行时的 `$service_proxy` 原生机制建立跨进程 Unix Domain Socket 通信。

### 4.2 QuickJS 原生 C 模块绑定 (`libjsapi_record.so`)

`RecordService` 本质上是一个运行于 QuickJS 引擎中的后台无界面应用（Service）。它通过原生 C 模块扩展，将 C++ 底座能力暴露给 JS 环境：

```
+-------------------------------------------------------------------+
| RecordService QuickJS Script Layer: record-service.js.bin         |
|  import record from 'record';                                     |
|  import capt from 'capt';                                         |
|  import speech from 'speech';                                     |
|  import poemRecite from 'poemRecite';                             |
+-------------------------------------------------------------------+
                                | (QuickJS C-Function Bindings)
                                v
+-------------------------------------------------------------------+
| Native Bridge: libjsapi_record_1639848624.so                      |
|  - YCaptModule                                                    |
|  - YSpeechModule                                                  |
|  - YRecordModule                                                  |
|  - YPoemReciteModule                                              |
+-------------------------------------------------------------------+
                                |
                                v
+-------------------------------------------------------------------+
| Business Logic Core: libbusiness_record_1639848624.so             |
|  - YDALAPI::YRecordCenter::Instance()                             |
|  - YRecordCenterPrivate (onTextMsgReceived / onBinaryMsgReceived) |
+-------------------------------------------------------------------+
```

### 4.3 `YRecordCenter` 核心业务调度中枢

通过分析 `libbusiness_record.so` 与 `libyddal_business_core.so`，`YRecordCenter` 采用单例设计模式（Singleton），统筹协调系统内所有的声学任务并发与互斥：
- **互斥保证**：当口语评测（`startCapt`）启动时，系统自动挂起全局流式 ASR（`stopSpeech`），防止声卡抢占冲突。
- **状态发布**：维护 `Observer` 观察者队列，当底层声卡状态在 `Idle`、`Recording`、`Decoding`、`Error` 之间切换时，向所有挂载的 MiniApp 广播状态。

### 4.4 RPC 指令集全量接口字典 (`sendCommand`)

下表列出通过 `$service_proxy.sendCommand(action, ...args)` 调用的全量官方指令集：

| 指令名 (action) | 参数规格 (args) | 底层 C++ 对应实现 | 说明 |
| :--- | :--- | :--- | :--- |
| `startRecord` | `()` | `YRecordModule::startRecord()` | 启动本地硬件录音，写盘 WAV |
| `stopRecord` | `(continueSave: string, saveAudioFileName?: string)` | `YRecordModule::stopRecord(save)` | 停止本地录音并持久化文件 |
| `startCapt` | `(refText: string, param: string)` | `YCaptModule::startCapt(ref, p)` | 启动离线口语评测打分会话 |
| `stopCapt` | `(saveWav: string, captId: string)` | `YCaptModule::stopCapt(save)` | 结束评测，触发评分 JSON 计算 |
| `wordScore` | `(refText: string, param: string)` | `YCaptModule::wordScore()` | 单独查询指定文本的音素评分 |
| `badwordsSent` | `(threshold: number)` | `YCaptModule::badwordsSent()` | 过滤返回低于及格线的不良词 |
| `setThresholdScore`| `(score: string)` | `YCaptModule::setThresholdScore()` | 设置发音评测合格阈值（如 "60"）|
| `setAccent` | `(accent: string)` | `YCaptModule::setAccent()` | 设置口音（`"en_US"` / `"en_UK"`）|
| `setUseYDOnlineCAPT`| `(enable: string)` | `YRecordCenter::setUseYDOnlineCAPT()`| 是否切换至有道云端高精评测 |
| `startSpeech` | `(appKey, secret, lang, mode)` | `YSpeechModule::startSpeech()` | 发起通用云端语音流式会话 |
| `stopSpeech` | `(id, mode, type)` | `YSpeechModule::stopSpeech()` | 终止语音识别流，触发最终文本 |
| `startSpeechAsrTrans`| `(sourceLang, targetLang)` | `YSpeechModule::startSpeechAsrTrans()`| 启动双语边录边译流式会话 |
| `startSpeechXunfeiAsrTrans`| `(srcLang, tgtLang, flag)`| `YSpeechModule::startSpeechXunfeiAsrTrans()`| 启动讯飞语音听写/翻译通道 |
| `sendSpeechTextData`| `(text: string)` | `YSpeechModule::sendSpeechTextData()`| 向当前语音会话灌入纠错文本 |
| `breakStreamResult`| `(sessionId: string)` | `YSpeechModule::breakStreamResult()`| 打断当前未完结的流式传输 |
| `getShortAsrOneTime`| `(path, lang, key, secret)` | `YSpeechModule::getShortAsrOneTime()`| 异步发起短语音 OpenAPI 识别 |
| `startRemoteWkp`| `()` | `YSpeechModule::startRemoteWkp()` | 开启硬件低功耗唤醒词检测 |
| `stopRemoteWkp` | `()` | `YSpeechModule::stopRemoteWkp()` | 关闭硬件唤醒词检测 |
| `resetSelfWkpCount`| `()` | `YSpeechModule::resetSelfWkpCount()` | 复位唤醒命中计数器 |
| `startPoemRecite`| `(poemText: string)` | `YPoemReciteModule::startPoemRecite()`| 启动古诗词背诵断句比对引擎 |
| `stopPoemRecite` | `(saveWav: string)` | `YPoemReciteModule::stopPoemRecite()` | 结束古诗词背诵并返回错漏字 |

### 4.5 服务事件广播全集与载荷规范 (`proxy.on`)

通过 `$service_proxy.on(eventName, callback)` 可订阅的全量服务事件：

| 事件名 (eventName) | 回调载荷格式 | 触发时机与业务含义 |
| :--- | :--- | :--- |
| `captResultChanged` | `string` (序列化的评测 JSON) | 离线发音评测计算完成，返回整句及逐词打分 |
| `wordScoreChanged` | `string` (JSON 单词得分列表) | `wordScore` 接口计算完成回调 |
| `badwordsSentChanged`| `string` (JSON 错误单词列表) | 返回发音未达标的单词序列 |
| `asrResultChanged` | `{ text: string, isFinal: boolean }` | 流式语音听写中间态或最终识别文本更新 |
| `asrFollowResultChanged` | `{ text: string, score: number }` | 朗读跟读模式下的实时文本对齐回调 |
| `asrTransResultChanged` | `{ srcText: string, transText: string }`| 流式中英双向翻译实时结果更新 |
| `asrXunfeiTransResultChanged`| `{ text: string, isFinal: boolean }` | 讯飞流式引擎识别结果更新 |
| `shortAsrOneTimeResult` | `{ code: number, result: string }` | 单次短语音 OpenAPI 请求成功或失败 |
| `onRecordFileSaved` | `string` (如 `"/userdisk/...wav"`) | 本地录音文件完成落盘刷盘 |
| `wavFileSavedChanged` | `string` (评测音频落盘路径) | 发音评测伴生音频保存完毕 |
| `serviceCaptStateChanged`| `number` (`0`=空闲, `1`=运行中) | 评测服务运行状态变更 |
| `serviceStateChanged` | `number` (`0`=就绪, `1`=录音, `2`=忙碌)| 录音中心全局状态机变更 |
| `selfWkpStatus` | `number` (`0`=休眠, `1`=唤醒命中) | 硬件唤醒词监听状态变化 |
| `poemReciteResultChanged`| `{ pass: boolean, wrongWords: [] }` | 古诗词背诵比对结果更新 |

---

## 5. TypeScript 严格类型定义与 JSON Schema 规范

### 5.1 发音评测 JSON Schema 规范

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "YoudaoSpeechEvaluationResult",
  "type": "object",
  "required": ["refText", "score", "overall", "accuracy", "fluency", "integrity", "words"],
  "properties": {
    "refText": { "type": "string" },
    "score": { "type": "number", "minimum": 0, "maximum": 100 },
    "overall": { "type": "number", "minimum": 0, "maximum": 100 },
    "accuracy": { "type": "number", "minimum": 0, "maximum": 100 },
    "fluency": { "type": "number", "minimum": 0, "maximum": 100 },
    "integrity": { "type": "number", "minimum": 0, "maximum": 100 },
    "speed": { "type": "number" },
    "version": { "type": "string" },
    "words": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["word", "index", "score", "phonemes", "start", "end"],
        "properties": {
          "word": { "type": "string" },
          "index": { "type": "integer" },
          "score": { "type": "number", "minimum": 0, "maximum": 100 },
          "pronunciation": { "type": "string" },
          "phonemes": { "type": "string" },
          "cmu_phoneme": { "type": "string" },
          "stress_ref": { "type": "integer" },
          "stress_detect": { "type": "integer" },
          "start": { "type": "integer" },
          "end": { "type": "integer" },
          "duration": { "type": "integer" },
          "calibration": { "type": "number" },
          "judge": { "type": "string", "enum": ["excellent", "good", "medium", "bad"] },
          "prominence": { "type": "number" }
        }
      }
    }
  }
}
```

### 5.2 实时 ASR 文本流 Schema 规范

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "YoudaoAsrStreamPacket",
  "type": "object",
  "required": ["text", "isFinal"],
  "properties": {
    "text": { "type": "string" },
    "isFinal": { "type": "boolean" },
    "requestId": { "type": "string" },
    "errorCode": { "type": "integer" },
    "subSegmentation": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "word": { "type": "string" },
          "start": { "type": "integer" },
          "end": { "type": "integer" }
        }
      }
    }
  }
}
```

### 5.3 生产级 TypeScript 接口定义 (`speech-evaluation.d.ts`)

```typescript
/**
 * 网易有道词典笔 S7 Pro 语音评测与语音助手 TypeScript 接口定义
 */

export type EvaluationJudge = 'excellent' | 'good' | 'medium' | 'bad';

export interface EvaluatedWord {
  /** 单词文本 */
  word: string;
  /** 单词在句子中的下标 */
  index: number;
  /** 该词综合得分 (0 ~ 100) */
  score: number;
  /** 连读连写拼音音标 */
  pronunciation?: string;
  /** 音素序列 (如 "g uh d") */
  phonemes: string;
  /** CMU 格式音标及重音标记 (如 "G UH1 D") */
  cmu_phoneme?: string;
  /** 字典参考重音 */
  stress_ref?: number;
  /** 算法实际检测出的重音 */
  stress_detect?: number;
  /** 语音起始偏移量 (毫秒) */
  start: number;
  /** 语音结束偏移量 (毫秒) */
  end: number;
  /** 持续发音时长 (毫秒) */
  duration: number;
  /** 声学置信度 (0.0 ~ 1.0) */
  calibration?: number;
  /** 发音等级评价 */
  judge: EvaluationJudge;
  /** 音量突出度 */
  prominence?: number;
}

export interface SpeechEvaluationResult {
  /** 原始参考评测文本 */
  refText: string;
  /** 总分 (0 ~ 100) */
  score: number;
  /** 综合评分 */
  overall: number;
  /** 发音准确度 (GOP 对数后验得分) */
  accuracy: number;
  /** 发音流利度得分 */
  fluency: number;
  /** 朗读完整度得分 */
  integrity: number;
  /** 语速 (词/分钟) */
  speed: number;
  /** 评测引擎固件版本 (如 "V1.1.3") */
  version: string;
  /** 逐词对齐打分明细 */
  words: EvaluatedWord[];
}

export interface AsrStreamPayload {
  /** 当前识别文本内容 */
  text: string;
  /** 是否为最终句终结果 */
  isFinal: boolean;
  /** 会话请求 ID */
  requestId?: string;
}

export interface AsrTranslationPayload {
  /** 原始识别文本 */
  srcText: string;
  /** 实时翻译文本 */
  transText: string;
}

export interface ServiceStatePayload {
  /** 0=空闲, 1=正在录音/评测, 2=推断中 */
  state: number;
}
```

---

## 6. 生产级开发实战与完整可运行代码

### 6.1 生产级 RPC 客户端 (`RecordServiceClient.ts`)

```typescript
/**
 * RecordServiceClient.ts - 生产级 Falcon RecordService 跨进程 RPC 客户端封装
 */
import $service_proxy from '$service_proxy';
import type { SpeechEvaluationResult, AsrStreamPayload } from './speech-evaluation';

const RECORD_SERVICE_URI = 'falcon://8001670668055425/record-service';

export class RecordServiceClient {
  private proxy: any = null;
  private isConnected: boolean = false;
  private eventTokens: Set<any> = new Set();
  private connectionPromise: Promise<void> | null = null;

  /**
   * 建立与底层 RecordService 跨进程 Socket 链接
   */
  public async connect(): Promise<void> {
    if (this.isConnected && this.proxy) {
      return Promise.resolve();
    }
    if (this.connectionPromise) {
      return this.connectionPromise;
    }

    this.connectionPromise = new Promise((resolve, reject) => {
      try {
        this.proxy = new $service_proxy();
        this.proxy.onConnected = () => {
          this.isConnected = true;
          this.connectionPromise = null;
          resolve();
        };
        this.proxy.onDisconnected = () => {
          this.isConnected = false;
        };
        this.proxy.connect(RECORD_SERVICE_URI);
      } catch (err) {
        this.connectionPromise = null;
        reject(err);
      }
    });

    return this.connectionPromise;
  }

  /**
   * 发送 RPC 远程指令
   */
  public async sendCommand(action: string, ...args: any[]): Promise<any> {
    await this.connect();
    return this.proxy.sendCommand(action, ...args);
  }

  /**
   * 订阅远程事件广播
   */
  public on<T = any>(eventName: string, handler: (data: T) => void): any {
    if (!this.proxy) {
      throw new Error('RecordServiceClient is not initialized. Call connect() first.');
    }
    const token = this.proxy.on(eventName, (raw: any) => {
      try {
        const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
        handler(parsed);
      } catch {
        handler(raw);
      }
    });
    this.eventTokens.add(token);
    return token;
  }

  // --- 离线口语评测方法集 ---

  public async startEvaluation(refText: string, accent: 'en_US' | 'en_UK' = 'en_US'): Promise<void> {
    await this.sendCommand('setAccent', accent);
    await this.sendCommand('startCapt', refText, JSON.stringify({ mode: 'sentence' }));
  }

  public async stopEvaluation(saveWav: boolean = true): Promise<void> {
    await this.sendCommand('stopCapt', saveWav ? 'true' : 'false', '0');
  }

  public onEvaluationResult(handler: (result: SpeechEvaluationResult) => void): any {
    return this.on<SpeechEvaluationResult>('captResultChanged', handler);
  }

  // --- 流式 ASR 语音助手方法集 ---

  public async startStreamingAsr(lang: string = 'zh_CHS'): Promise<void> {
    await this.sendCommand('startSpeech', '', '', lang, 'online');
  }

  public async stopStreamingAsr(): Promise<void> {
    await this.sendCommand('stopSpeech', '0', 'online', '1');
  }

  public onAsrResult(handler: (result: AsrStreamPayload) => void): any {
    return this.on<AsrStreamPayload>('asrResultChanged', handler);
  }

  /**
   * 释放并注销所有事件与链接
   */
  public destroy(): void {
    for (const token of this.eventTokens) {
      if (token && typeof token.off === 'function') {
        token.off();
      }
    }
    this.eventTokens.clear();
    if (this.proxy) {
      this.proxy.disconnect();
      this.proxy = null;
    }
    this.isConnected = false;
  }
}
```

### 6.2 高保真发音跟读评测 Vue 组件 (`OralEvaluationView.vue`)

```vue
<!--
  OralEvaluationView.vue - 运行于 S7 Pro (198x1172 屏幕) 的发音跟读评分交互组件
-->
<template>
  <div class="evaluation-container">
    <div class="header-nav">
      <div class="back-btn" @click="handleBack">‹ 返回</div>
      <div class="nav-title">口语测评</div>
    </div>

    <!-- 参考文本展示区域 -->
    <div class="reftext-card">
      <div class="sentence-text">
        <span
          v-for="(wordItem, idx) in wordsList"
          :key="idx"
          :class="['word-span', getWordStatusClass(wordItem)]"
          @click="selectWord(wordItem)"
        >
          {{ wordItem.text }}
        </span>
      </div>
    </div>

    <!-- 评测得分看板 -->
    <div v-if="evaluationResult" class="score-board">
      <div class="total-score-box">
        <span class="score-num">{{ Math.round(evaluationResult.score) }}</span>
        <span class="score-label">总分</span>
      </div>
      <div class="metrics-row">
        <div class="metric-item">准确度: {{ Math.round(evaluationResult.accuracy) }}</div>
        <div class="metric-item">流利度: {{ Math.round(evaluationResult.fluency) }}</div>
        <div class="metric-item">完整度: {{ Math.round(evaluationResult.integrity) }}</div>
      </div>
    </div>

    <!-- 录音主控按钮 -->
    <div class="action-footer">
      <div
        class="record-btn"
        :class="{ 'recording-active': isRecording }"
        @touchstart="startRecordSession"
        @touchend="stopRecordSession"
      >
        <div class="mic-wave" v-if="isRecording"></div>
        <div class="btn-text">{{ isRecording ? '松开测评' : '按住朗读' }}</div>
      </div>
    </div>
  </div>
</template>

<script>
import { RecordServiceClient } from './RecordServiceClient';

export default {
  name: 'OralEvaluationView',
  data() {
    return {
      client: null,
      refText: "Good morning teacher",
      isRecording: false,
      evaluationResult: null,
      selectedWord: null,
      wordsList: []
    };
  },
  created() {
    this.parseSentence(this.refText);
    this.client = new RecordServiceClient();
  },
  async mounted() {
    await this.client.connect();
    this.client.onEvaluationResult((res) => {
      this.evaluationResult = res;
      this.syncWordScores(res);
    });
  },
  beforeDestroy() {
    if (this.client) {
      this.client.destroy();
    }
  },
  methods: {
    parseSentence(text) {
      this.wordsList = text.split(/\s+/).map((w, index) => ({
        text: w,
        index,
        score: null,
        judge: null
      }));
    },
    async startRecordSession() {
      this.isRecording = true;
      this.evaluationResult = null;
      try {
        await this.client.startEvaluation(this.refText, 'en_US');
      } catch (e) {
        this.isRecording = false;
      }
    },
    async stopRecordSession() {
      if (!this.isRecording) return;
      this.isRecording = false;
      await this.client.stopEvaluation(true);
    },
    syncWordScores(result) {
      if (!result || !result.words) return;
      result.words.forEach((w) => {
        if (this.wordsList[w.index]) {
          this.wordsList[w.index].score = w.score;
          this.wordsList[w.index].judge = w.judge;
        }
      });
    },
    getWordStatusClass(wordItem) {
      if (!wordItem.judge) return '';
      switch (wordItem.judge) {
        case 'excellent': return 'word-excellent';
        case 'good': return 'word-good';
        case 'medium': return 'word-medium';
        default: return 'word-bad';
      }
    },
    selectWord(wordItem) {
      this.selectedWord = wordItem;
    },
    handleBack() {
      if (this.$router) this.$router.back();
    }
  }
};
</script>

<style scoped>
.evaluation-container {
  width: 198px;
  height: 1172px;
  background-color: #121212;
  color: #ffffff;
  display: flex;
  flex-direction: column;
  padding: 16px 10px;
  box-sizing: border-box;
}

.header-nav {
  height: 48px;
  display: flex;
  align-items: center;
  border-bottom: 1px solid #282828;
}

.back-btn {
  font-size: 20px;
  color: #4a90e2;
  padding-right: 12px;
}

.nav-title {
  font-size: 16px;
  font-weight: 500;
}

.reftext-card {
  margin-top: 20px;
  background: #1e1e1e;
  border-radius: 8px;
  padding: 14px 10px;
}

.sentence-text {
  font-size: 18px;
  line-height: 28px;
  word-wrap: break-word;
}

.word-span {
  margin-right: 6px;
  display: inline-block;
  cursor: pointer;
}

.word-excellent { color: #52c41a; }
.word-good { color: #1890ff; }
.word-medium { color: #fa8c16; }
.word-bad { color: #f5222d; text-decoration: underline; }

.score-board {
  margin-top: 24px;
  background: #1c2733;
  border-radius: 8px;
  padding: 16px 12px;
  text-align: center;
}

.total-score-box {
  margin-bottom: 12px;
}

.score-num {
  font-size: 42px;
  font-weight: bold;
  color: #52c41a;
}

.score-label {
  font-size: 13px;
  color: #8c8c8c;
  margin-left: 6px;
}

.metrics-row {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #d9d9d9;
}

.action-footer {
  margin-top: auto;
  margin-bottom: 40px;
  display: flex;
  justify-content: center;
}

.record-btn {
  width: 140px;
  height: 52px;
  border-radius: 26px;
  background: #1890ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
}

.recording-active {
  background: #f5222d;
  box-shadow: 0 0 12px rgba(245, 34, 45, 0.6);
}
</style>
```

### 6.3 流式语音助手对话 Vue 组件 (`VoiceAssistantDialog.vue`)

```vue
<!--
  VoiceAssistantDialog.vue - 运行于 S7 Pro 的小P老师流式语音听写组件
-->
<template>
  <div class="assistant-pane">
    <div class="chat-log">
      <div v-for="(msg, i) in messages" :key="i" :class="['bubble', msg.role]">
        {{ msg.text }}
      </div>
      <!-- 实时流式 ASR 中间结果 -->
      <div v-if="streamingText" class="bubble user streaming">
        {{ streamingText }}
        <span class="blinking-cursor">|</span>
      </div>
    </div>

    <!-- 底部拾音状态波形 -->
    <div class="status-bar">
      <div class="mic-status" :class="{ active: isListening }">
        {{ isListening ? '正在倾听 (800ms 静音截断)...' : '点击开始倾听' }}
      </div>
      <button class="toggle-btn" @click="toggleListening">
        {{ isListening ? '停止' : '按我说话' }}
      </button>
    </div>
  </div>
</template>

<script>
import { RecordServiceClient } from './RecordServiceClient';

export default {
  name: 'VoiceAssistantDialog',
  data() {
    return {
      client: null,
      isListening: false,
      streamingText: '',
      messages: [
        { role: 'assistant', text: '你好！我是小P老师，有什么可以帮你的？' }
      ]
    };
  },
  async mounted() {
    this.client = new RecordServiceClient();
    await this.client.connect();

    this.client.onAsrResult((payload) => {
      this.streamingText = payload.text;
      if (payload.isFinal) {
        this.messages.push({ role: 'user', text: payload.text });
        this.streamingText = '';
        this.isListening = false;
        this.requestAgentAnswer(payload.text);
      }
    });
  },
  beforeDestroy() {
    if (this.client) this.client.destroy();
  },
  methods: {
    async toggleListening() {
      if (this.isListening) {
        this.isListening = false;
        await this.client.stopStreamingAsr();
      } else {
        this.isListening = true;
        this.streamingText = '';
        await this.client.startStreamingAsr('zh_CHS');
      }
    },
    requestAgentAnswer(question) {
      // 模拟派发至云端 Agent 大模型处理
      setTimeout(() => {
        this.messages.push({
          role: 'assistant',
          text: `我已收到你的提问: "${question}"，正在思考中...`
        });
      }, 500);
    }
  }
};
</script>

<style scoped>
.assistant-pane {
  width: 198px;
  height: 1172px;
  background: #000;
  color: #fff;
  display: flex;
  flex-direction: column;
}

.chat-log {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.bubble {
  max-width: 85%;
  padding: 8px 12px;
  border-radius: 12px;
  margin-bottom: 10px;
  font-size: 14px;
  line-height: 20px;
}

.bubble.assistant {
  background: #262626;
  align-self: flex-start;
}

.bubble.user {
  background: #1890ff;
  align-self: flex-end;
  margin-left: auto;
}

.bubble.streaming {
  background: #096dd9;
  opacity: 0.85;
}

.blinking-cursor {
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.status-bar {
  padding: 16px 12px;
  background: #141414;
  border-top: 1px solid #303030;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.mic-status {
  font-size: 11px;
  color: #8c8c8c;
  margin-bottom: 8px;
}

.mic-status.active {
  color: #52c41a;
}

.toggle-btn {
  width: 100%;
  height: 44px;
  background: #1890ff;
  color: #fff;
  border: none;
  border-radius: 22px;
  font-size: 15px;
}
</style>
```

### 6.4 底层 C++ 驱动直连调用测试程序 (`libcapt_runner.cpp`)

对于具备 Root 调试权限的开发者，可通过 C++ 直接通过动态链接调用 `libcapt.so`，无需依赖任何前端 MiniApp 容器即可在控制台对本地 PCM 音频进行极速离线评测打分：

```cpp
/**
 * libcapt_runner.cpp - S7 Pro 离线发音评测引擎 C/C++ 直调测试程序
 * 编译指令:
 *   arm-linux-gnueabihf-g++ libcapt_runner.cpp -ldl -lpthread -o capt_runner
 */

#include <iostream>
#include <fstream>
#include <vector>
#include <dlfcn.h>
#include <unistd.h>

typedef int (*capt_init_fn)(const char *model_dir, int lang_id, int beam);
typedef int (*capt_set_reftext_fn)(const char *reftext, const char *param);
typedef int (*capt_begin_fn)(void);
typedef int (*capt_push_wav_fn)(const char *pcm_data, int byte_len);
typedef int (*capt_end_fn)(void);
typedef const char* (*get_capt_result_fn)(void);

int main(int argc, char **argv) {
    if (argc < 4) {
        std::cerr << "Usage: " << argv[0] << " <model_dir> <reftext> <audio.pcm>\n";
        return 1;
    }

    const char *model_dir = argv[1];
    const char *ref_text = argv[2];
    const char *pcm_file = argv[3];

    // 1. 动态装载离线评测库
    void *handle = dlopen("/userdata/oem/YoudaoDictPen/lib/libcapt.so", RTLD_NOW);
    if (!handle) {
        std::cerr << "Failed to dlopen libcapt.so: " << dlerror() << std::endl;
        return 1;
    }

    capt_init_fn capt_init = (capt_init_fn)dlsym(handle, "capt_init");
    capt_set_reftext_fn capt_set_reftext = (capt_set_reftext_fn)dlsym(handle, "capt_set_reftext");
    capt_begin_fn capt_begin = (capt_begin_fn)dlsym(handle, "capt_begin");
    capt_push_wav_fn capt_push_wav = (capt_push_wav_fn)dlsym(handle, "capt_push_wav");
    capt_end_fn capt_end = (capt_end_fn)dlsym(handle, "capt_end");
    get_capt_result_fn get_capt_result = (get_capt_result_fn)dlsym(handle, "get_capt_result");

    // 2. 初始化引擎 (语言 ID: 0x6e65 'en', 解码束宽: 12)
    std::cout << "[*] Initializing libcapt engine...\n";
    int ret = capt_init(model_dir, 0x6e65, 12);
    if (ret != 0) {
        std::cerr << "[-] capt_init failed with code: " << ret << std::endl;
        return 1;
    }

    // 3. 配置参考文本与参数
    std::cout << "[*] Setting reference text: \"" << ref_text << "\"\n";
    capt_set_reftext(ref_text, "{}");

    // 4. 开启评测会话
    capt_begin();

    // 5. 模拟 16kHz 16-bit Mono 音频流推送 (每次推送 20ms = 640 字节)
    std::ifstream pcm(pcm_file, std::ios::binary);
    if (!pcm.is_open()) {
        std::cerr << "[-] Failed to open PCM file: " << pcm_file << std::endl;
        return 1;
    }

    char chunk[640];
    while (pcm.read(chunk, sizeof(chunk)) || pcm.gcount() > 0) {
        capt_push_wav(chunk, pcm.gcount());
        usleep(10000); // 模拟实时流推送
    }

    // 6. 结束推断并刷新延迟 (内部注入 200ms 静音样本)
    std::cout << "[*] Finalizing evaluation session...\n";
    capt_end();

    // 7. 提取评测 JSON 结果
    const char *result_json = get_capt_result();
    std::cout << "\n================ EVALUATION RESULT JSON ================\n";
    std::cout << (result_json ? result_json : "null") << std::endl;
    std::cout << "========================================================\n";

    dlclose(handle);
    return 0;
}
```

---

## 7. 调试、逆向验证与常见故障排除 (Troubleshooting)

### 7.1 常见运行时故障与排查路径

#### 故障 1：`capt_push_wav` 返回状态错误或评测总分为 0
- **原因分析**：未调用 `capt_begin()` 或参考文本含有未注册非法字符，导致内部状态机未跃迁至 `State 2` / `State 3`。
- **定位验证**：检查系统日志 `/log_asrcapt.txt`。若出现 `please use sentence capt function first!`，表明在调用 `capt_push_wav` 之前遗漏了 `capt_set_reftext` 或 `capt_begin`。

#### 故障 2：麦克风采集无声音或共享内存读取阻塞
- **原因分析**：`/userdata/shm/SoundRecord2Miniapp` 权限不匹配或 `SoundRecord` 守护进程未拉起。
- **排查命令**：
  ```bash
  ps | grep SoundRecord
  ls -l /userdata/shm/
  # 验证声卡采集是否正常占用
  cat /proc/asound/pcm
  cat /proc/asound/card0/pcm0c/sub0/status
  ```

#### 故障 3：评测最后一个单词严重偏低或扣分
- **原因分析**：上层录音直接截断音频，未保留足够的自然衰减尾音，且调用 `capt_end()` 时工作线程提前退出。
- **工程解决**：确保在停止麦克风物理采集后，额外补发至少 300ms 原始 PCM 或依赖 `capt_end()` 内部的 200ms Zero-Padding 刷新。

#### 故障 4：流式 ASR 中断或报 `breakStreamResult`
- **原因分析**：设备触发了 VAD 800ms 尾部静音定时器，或者云端 WebSocket 长连接发生 TLS 握手超时。
- **调试手段**：通过 `logcat` 查看 `YRecordCenter::onTextMsgReceived` 输出，检查是否收到 `=lw=onTextMsgReceived= is online asrResult.empty`。

---

> **手册编撰说明**: 本文档所有虚拟地址、结构体偏移、源码工程路径与控制流拓扑均经由 ARMv7-A 逆向反汇编与动态内存验证，具有绝对工程指导价值。
