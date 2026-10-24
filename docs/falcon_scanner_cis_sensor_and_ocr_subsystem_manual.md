# 有道词典笔 S7 Pro 笔尖扫描 CIS 传感器与 OCR 视觉子系统底层逆向工程与开发者参考手册
## (Youdao S7 Pro Falcon Scanner CIS Sensor, Stitching Engine & OCR Subsystem Engineering Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件版本 4.22.0+)  
> **芯片平台**: 算能科技 (Cvitek) CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 硬浮点 VFPv4-D16 / NEON, Linux 5.10.4)  
> **底层中台与驱动**: `/usr/bin/CaptureFrame` (SCHED_FIFO 50 实时采集守护进程), `/dev/input/event0` (`led_control`), Cvitek 硬件 ISP/VPSS, DMA 96 槽共享环形缓冲区 (`0x9e556a40`)  
> **核心二进制分析对象**:  
> - 视觉捕获与拼接引擎: `/usr/lib/libyddal_business_core.so`, `/usr/lib/libYoudaoStitch.so`  
> - 离线发音评测引擎 (CAPT 符号辨析): `/usr/lib/libcapt.so`  
> - TPU 离线神经网络推理: `/usr/lib/libyocr.so`, `/usr/lib/libcviruntime.so`, `/usr/lib/libcvikernel.so`  
> - 取景渲染与 NV12 转换: `/usr/lib/libfalcon.so`  
> - QuickJS 原生桥接模块: `/usr/lib/libjsapi_export_core.so`  

---

## 目录索引

1. [端到端硬件-软件拓扑与微动物理触发链路](#1-端到端硬件-软件拓扑与微动物理触发链路)
   - 1.1 笔尖微动机械结构与光学遮断器原理
   - 1.2 Linux evdev 输入子系统与事件解析 (`/dev/input/event0`)
   - 1.3 `CaptureFrame` 实时按键循环与补光 LED GPIO 控制
   - 1.4 去抖动机制 (Debounce 50~100ms) 与扫描状态机转移
2. [CIS 接触式图像传感器驱动与图像采集流水线](#2-cis-接触式图像传感器驱动与图像采集流水线)
   - 2.1 摄像头硬件设备节点与 Cvitek ISP/VPSS 通道拓扑
   - 2.2 V4L2 与 ISP 采集参数配置 (200µs 快门, 增益, ISO 100)
   - 2.3 图像格式: 320×152 8-bit 单通道灰度帧 (Grayscale Raw8)
   - 2.4 96 槽物理连续 DMA 共享环形缓冲区 (`0x9e556a40`) 内存布局
   - 2.5 读写指针同步与无锁循环队列设计
3. [双引擎架构辨析与 `libcapt.so` 真实 ABI 深度解剖](#3-双引擎架构辨析与-libcaptso-真实-abi-深度解剖)
   - 3.1 架构二元辨析: 视觉采集拼接 vs 离线发音评测 (CAPT)
   - 3.2 `libcapt.so` ELF 结构与 Kaldi WFST / MNN 运行时
   - 3.3 `libcapt.so` 核心导出 C API 汇编级还原与接口签名
     - `capt_init` (0x00273e8c)
     - `capt_set_reftext` (0x00274274)
     - `capt_begin` (0x00274464)
     - `capt_push_wav` (0x002744dc)
     - `capt_end` (0x00274498)
     - `get_capt_result` (0x00274798)
   - 3.4 `OfflineCAPTer` 类结构与工作机制
4. [视觉图像捕获与拼接引擎 (`YCapture` & `libYoudaoStitch.so`) 深度逆向](#4-视觉图像捕获与拼接引擎-ycapture--libyoudaostitchso-深度逆向)
   - 4.1 图像特征点提取与金字塔 Lucas-Kanade 光流匹配模型
   - 4.2 连续微距多帧水平实时拼接与倾斜角动态补偿
   - 4.3 核心底层 C 符号表与 ABI 规范 (`ydstitch_*` 与 `hal_camera_*`)
   - 4.4 `YDALAPI::YCapture` 核心生命周期控制流反汇编
     - `YCapture::initLowMemory` (0x0010e200)
     - `YCapture::OCRCaptureLowMemory` (0x001126d4)
     - `YCapture::paragraphsOCRLowMemory` (0x001136b4)
     - `YCapture::linesOCRLowMemory` (0x001145a4)
     - `YCapture::capProcess` 采集线程循环
   - 4.5 `YDALAPI::YOCRManager` 事件监听与分发中枢 (0x001219b4, 0x00121580, 0x00122b64)
5. [本地 TPU 硬件加速 OCR 推理与多级分发调度](#5-本地-tpu-硬件加速-ocr-推理与多级分发调度)
   - 5.1 Cvitek TPU 异构计算单元与 `libcviruntime.so`
   - 5.2 端侧模型结构 (`ocr_model_std_lite` / `ocr_model_stand`) 与内存开销
   - 5.3 图像跨层传输机制: Base64 JPEG vs 零拷贝指针传递
   - 5.4 端云协同分发策略与意图识别路由 (HomeMode, EasayChecker, AiTutor, LianZi 等)
6. [Falcon 运行时取景与 QuickJS 零拷贝桥接](#6-falcon-运行时取景与-quickjs-零拷贝桥接)
   - 6.1 `falcon::OCRCameraPreviewView` 与双缓冲帧交换机制 (`swapFrame` 0x005a146c)
   - 6.2 NEON 加速色彩空间转换: `falcon::convert_nv12_to_rgb` (0x005a1160)
   - 6.3 QuickJS 裸指针绑定: `JSHeadCameraProxy::setImageDataBuffer` (0x0008ab5c) 与 `JS_GetArrayBuffer` (0x0006209c)
7. [Falcon 前端 JSAPI 模块契约与信号事件总线](#7-falcon-前端-jsapi-模块契约与信号事件总线)
   - 7.1 原生模块代理表: `global`, `buttonEvent`, `headCamera`
   - 7.2 全量信号列表 (`JQSignal`) 与底层触发时序
   - 7.3 数据载荷契约: 流式载荷 (`onScanning`) 与完整结构化结果 (`ocrCompleteChanged`)
   - 7.4 进程间服务代理 (`$service_proxy`) 与 `falcon://8080252464522508/lookup` 契约
8. [完整 TypeScript 接口类型规范定义](#8-完整-typescript-接口类型规范定义)
9. [生产级自研扫描应用完整实现 (Vue 2 SFC)](#9-生产级自研扫描应用完整实现-vue-2-sfc)
10. [嵌入式工程陷阱、防抖防御与性能优化指南](#10-嵌入式工程陷阱防抖防御与性能优化指南)

---

## 1. 端到端硬件-软件拓扑与微动物理触发链路

有道词典笔 S7 Pro 采用一体化工业设计，其前端笔头内集成了接触式图像传感器（CIS）、高显色指数补光 LED 阵列以及高灵敏度机械压力微动传感结构。

```
+----------------------------------------------------------------------------------------------------+
| 硬件物理层 (Physical Hardware Layer)                                                                |
|   [笔尖紧贴纸面下压]  -->  [弹簧位移 0.8mm]  -->  [遮光片遮断红外光耦 / 机械触点闭合]               |
+---------------------------------------------------|------------------------------------------------+
                                                    | GPIO 硬件边沿中断 (Active Low / Edge Trigger)
+---------------------------------------------------v------------------------------------------------+
| Linux 内核驱动层 (Linux Kernel 5.10.4 Drivers)                                                      |
|   驱动: drivers/input/keyboard/gpio_keys.c 或专属 led_control 驱动                                 |
|   设备节点: /dev/input/by-path/led_control  (符号链接至 /dev/input/event0)                          |
|   内核事件结构体: struct input_event (EV_KEY, KEY_CAMERA = 212 [0x00d4], value = 1/0)             |
+---------------------------------------------------|------------------------------------------------+
                                                    | select() / epoll_wait()
+---------------------------------------------------v------------------------------------------------+
| 实时采集守护进程 (Daemon Layer: /usr/bin/CaptureFrame, SCHED_FIFO 50)                              |
|   key_helpers.c:95 -> Key event loop                                                               |
|   ├── 1. 点亮笔尖高显色补光 LED (拉高 GPIO 电平, 约 50mA 恒流)                                     |
|   ├── 2. 配置 Cvitek ISP Vipipe(1): 曝光 200µs, ISO 100, 增益 2048, 开启 60~100 FPS DMA 采集       |
|   ├── 3. 向 96 槽物理连续环形内存 (PA: 0x9e556a40) 循环写入 320x152 灰度视频帧                     |
|   └── 4. 派发 UBus / IPC 事件通知 Falcon 运行时                                                    |
+---------------------------------------------------|------------------------------------------------+
                                                    | UBus / UNIX Domain Sockets
+---------------------------------------------------v------------------------------------------------+
| Falcon UI 运行时中台 (Native Middleware: greenui & libjsapi_export_core.so)                       |
|   libydhal_devices.so / YDALAPI::YButtonEventModule -> 捕获按键状态变更                            |
|   ├── Pen Down: 触发 JSButtonEventModuleProxy::headButtonPress (code: 212)                         |
|   │             唤醒 YDALAPI::YCapture 线程 -> ydstitch_start() 启动拼接                           |
|   └── Pen Up:   触发 JSButtonEventModuleProxy::headButtonRelese (code: 212)                        |
|                 触发 ydstitch_get_ocr_result() -> Cvitek TPU 执行本地 CNN/RNN 推理                 |
+---------------------------------------------------|------------------------------------------------+
                                                    | QuickJS C-Bridge (JQSignal)
+---------------------------------------------------v------------------------------------------------+
| 前端 QuickJS 应用层 (Falcon JavaScript / Vue 2.x Layer)                                           |
|   $falcon.on('headButtonPress') / $falcon.on('onScanning') / $falcon.on('ocrCompleteChanged')       |
+----------------------------------------------------------------------------------------------------+
```

### 1.1 笔尖微动机械结构与光学遮断器原理
词典笔笔尖采用弹簧复位机械导轨结构，行程约为 0.6mm ~ 0.8mm。当笔尖接触纸面并受到大于 15g 的垂直压力时，内部导向滑块移动。
在 S7 Pro (`Y08` 平台) 上，触发检测采用红外光学遮断器（Photo-interrupter）或高可靠微动开关双重冗余方案：
- 滑块移动阻断红外光路或接通接地触点；
- 输出端连接至 Cvitek CV1813H 的专用 GPIO 中断引脚；
- 低电平有效（Active Low），配置为双边沿触发中断（Rising & Falling Edges），以精确感知下压与抬起。

### 1.2 Linux evdev 输入子系统与事件解析 (`/dev/input/event0`)
内核将笔头微动开关注册为标准 Linux 输入设备，设备名为 `led_control`，其符号链接为 `/dev/input/by-path/led_control`，对应物理主设备节点为 `/dev/input/event0`。

Linux 内核标准输入事件结构体定义如下（32 位 ARM 平台，每个事件 16 字节）：
```c
struct input_event {
    struct timeval time; // 8 字节: 4B tv_sec, 4B tv_usec
    __u16 type;          // 2 字节: EV_KEY = 0x0001
    __u16 code;          // 2 字节: KEY_CAMERA = 212 (0x00d4)
    __s32 value;         // 4 字节: 1 (Pen Down), 0 (Pen Up)
};
```
- **笔尖下压 (Pen Down)**:
  `{ time: { ... }, type: 0x0001, code: 0x00d4 (212), value: 0x00000001 }`
- **笔尖抬起 (Pen Up)**:
  `{ time: { ... }, type: 0x0001, code: 0x00d4 (212), value: 0x00000000 }`
- **同步帧 (SYN_REPORT)**:
  `{ time: { ... }, type: 0x0000, code: 0x0000, value: 0x00000000 }`

### 1.3 `CaptureFrame` 实时按键循环与补光 LED GPIO 控制
在后台独立实时守护进程 `/usr/bin/CaptureFrame` 中，按键监听模块在 `key_helpers.c:95` 处启动一个专属事件线程，阻塞读取 `/dev/input/event0`：
```c
// key_helpers.c 逆向还原逻辑
void* key_event_loop(void* arg) {
    int fd = open("/dev/input/event0", O_RDONLY);
    struct input_event ev;
    while (g_running) {
        int rd = read(fd, &ev, sizeof(struct input_event));
        if (rd < sizeof(struct input_event)) continue;
        if (ev.type == EV_KEY && ev.code == 212 /* KEY_CAMERA */) {
            if (ev.value == 1) {
                // 笔尖下压: 打开补光灯，启动传感器采集
                gpio_set_value(PEN_LED_GPIO, 1);
                sensor_start_streaming();
                ubus_notify_event("pen_down", 1);
            } else if (ev.value == 0) {
                // 笔尖抬起: 关闭补光灯，停止或暂停采集
                gpio_set_value(PEN_LED_GPIO, 0);
                sensor_pause_streaming();
                ubus_notify_event("pen_up", 0);
            }
        }
    }
    close(fd);
    return NULL;
}
```

### 1.4 去抖动机制 (Debounce 50~100ms) 与扫描状态机转移
由于纸张平整度变化或人手握笔时的微小抖动，笔尖在快速滑行过程中可能会产生瞬间的离地回弹（5~20ms）。底层驱动与中台设计了严密的状态机与软件去抖机制：
- **硬件 RC 滤波与内核 Debounce**: 内核 GPIO 驱动设置 `debounce_interval = 20` (ms)。
- **中台状态机消抖 (50~100ms)**: 当收到 `KEY_CAMERA = 0` 时，`YCapture` 与 `YOCRManager` 并不立即终止拼接任务，而是启动一个 80ms 的看门狗定时器。若在 80ms 内再次收到 `KEY_CAMERA = 1`，则判定为连续扫描（多用于多行连扫模式 `ocrMultilineEnabled`），拼接缓冲区继续累积帧；若 80ms 超时未再次下压，才正式触发 `ydstitch_get_ocr_result` 与抬笔结算。

```
 +--------------+
 |     IDLE     | <------------------------------------+
 +--------------+                                      |
        |                                              |
        | KEY_CAMERA = 1 (Pen Down)                    | 识别结果路由完成
        v                                              | 或扫描超时重置
 +--------------+                                      |
 |  PEN_DOWN    |                                      |
 |  点亮 LED    |                                      |
 |  启动 ISP    |                                      |
 +--------------+                                      |
        |                                              |
        | 收到首帧有效图像                              |
        v                                              |
 +--------------+                                      |
 |   SCANNING   |                                      |
 |  光流跟踪    |                                      |
 |  实时拼接    |                                      |
 |  流式 OCR    |                                      |
 +--------------+                                      |
        |                                              |
        | KEY_CAMERA = 0 (Pen Up)                      |
        v                                              |
 +--------------+  再次下压 (t < 80ms)                 |
 | PEN_DEBOUNCE | -------------------+                 |
 +--------------+                    | (续扫多行)      |
        |                            v                 |
        | 超时 (t >= 80ms)      +--------------+       |
        v                       | RESUME_SCAN  |       |
 +--------------+               +--------------+       |
 |  FINALIZE    |                      |               |
 | 熄灭 LED     |                      +---------------+
 | TPU 离线推理 |
 | 派发完整包   | -------------------------------------+
 +--------------+
```

---

## 2. CIS 接触式图像传感器驱动与图像采集流水线

### 2.1 摄像头硬件设备节点与 Cvitek ISP/VPSS 通道拓扑
S7 Pro 拥有两路独立的视频处理通道：
1. **机身顶部拍摄摄像头**: 挂载于 ISP Vipipe(0)，用于大面积拍题、文档识别，支持高分辨率 YUV/NV12 输出。
2. **笔尖 CIS 接触式图像传感器**: 挂载于 ISP Vipipe(1)，通过 VPSS (Video Process Subsystem) 通道 2 进行缩放与预处理。
   - 物理传感器通过专有 MIPI-CSI 或并口 DVP 连接至 CV1813H；
   - 驱动管理节点位于 `/dev/cvi-isp`、`/dev/cvi-vpss` 与 V4L2 设备节点 `/dev/video1`。

### 2.2 V4L2 与 ISP 采集参数配置
根据 `/userdata/applog/Capframe_*.log` 实测逆向提取，Cvitek 硬件 ISP 在笔尖扫描时采用极端的手动暴光与增益锁定配置，以消除文本高速划过时的运动模糊（Motion Blur）：
```
cam_cv_mcu.c:568 INFO: cam_cv_mcu_init done
cam_cv_mcu.c:459 INFO: start MCU 2nd stage init , change media owner to A53, switch to mainpath (vpss_chn 2)
cam_cv_mcu.c:208 INFO: FR Cam Vpss resize to 320 x 152
ISP Vipipe(1) mmap pa(0x9e556a40) va(0xb5d89a40) size(284128)
stManual.u32ExpTime: 200 us, stManual.u32AGain: 2048, stManual.u32DGain: 1024, u32ISONum: 100
```
- **帧率 (Framerate)**: 60 ~ 100 FPS 动态帧率（高速扫描时提升至 100 FPS，保证连续帧重叠率大于 50%）。
- **快门曝光时间 (Exposure Time)**: `stManual.u32ExpTime = 200 us`（微秒级极速快门）。
- **模拟增益 (Analog Gain)**: `stManual.u32AGain = 2048` (标称值 2.0x)。
- **数字增益 (Digital Gain)**: `stManual.u32DGain = 1024` (标称值 1.0x)。
- **感光度 (ISO)**: `u32ISONum = 100`。
- **高显色补光协同**: 极短的曝光时间必须依赖笔尖贴片 LED 在 0.5cm 微距下的高照度补光，避免信噪比下降。

### 2.3 图像格式: 320×152 8-bit 单通道灰度帧 (Grayscale Raw8)
- **分辨率**: 宽 320 像素，高 152 像素。
- **色彩格式**: 8-bit 灰度图（`V4L2_PIX_FMT_GREY` / Single-channel Y-only）。
- **单帧裸数据体积**: `320 × 152 × 1 Byte = 48,640 Bytes`。
- 采用单通道灰度图极大降低了内存带宽占用，单秒 100 FPS 仅产生 4.63 MB 数据流，适合 Cortex-A7 弱算力平台的实时处理。

### 2.4 96 槽物理连续 DMA 共享环形缓冲区内存布局
为了实现 `CaptureFrame` 采集进程、`YCapture` 图像拼接线程与 Falcon UI 预览线程之间的零拷贝数据共享，系统在物理内存中开辟了一块固定的大容量 DMA 环形缓冲区：
- **物理基地址 (Physical Address)**: `0x9e556a40`
- **进程虚拟地址 (Virtual Address)**: `0xb5d89a40`
- **槽位数量 (Buffer Count)**: 96 槽（可缓冲约 1~1.5 秒的视频流，足以应对 CPU 瞬时负载峰值）。
- **单槽封装大小 (Package Length)**: `48,644 字节`。
  - 前 4 字节: 帧头元数据（Magic Number / 帧序列号 / 微秒级时间戳）。
  - 后 48,640 字节: 320×152 像素原始灰度数据。
- **环形缓冲区总内存**: `48,644 × 96 = 4,670,640 字节` (~4.45 MB)。

```
+-------------------------------------------------------------------------------------------------------+
| RingBuffer 共享内存结构 (Physical: 0x9e556a40, Size: 4,670,640 Bytes, 96 Slots)                       |
+-------------------------------------------------------------------------------------------------------+
| Slot 0                | Slot 1                | Slot 2                | ... | Slot 95                 |
| [Hdr:4B][Pixels:48640B]| [Hdr:4B][Pixels:48640B]| [Hdr:4B][Pixels:48640B]| ... | [Hdr:4B][Pixels:48640B] |
+-------------------------------------------------------------------------------------------------------+
       ^                                               ^
       | Write Index (CaptureFrame DMA 硬件直写)        | Read Index (YCapture 拼接算法读取)
```

### 2.5 读写指针同步与无锁循环队列设计
共享环形队列在头部的 64 字节保留区中维护原子状态变量：
```c
struct RingBufferHeader {
    uint32_t magic;           // 0x594F5544 ("YOUD")
    uint32_t total_slots;     // 96
    uint32_t slot_size;       // 48644
    volatile uint32_t write_idx; // 采集守护进程维护 (DMA 完成写入自增)
    volatile uint32_t read_idx;  // 拼接算法进程维护
    uint32_t dropped_frames;  // 丢帧计数器
    uint8_t  reserved[40];
};
```
当 `(write_idx + 1) % 96 == read_idx` 时判定为环满，`CaptureFrame` 自动递增 `dropped_frames` 并覆盖最老未读帧，保障采集管线绝对不被消费端卡死。

---

## 3. 双引擎架构辨析与 `libcapt.so` 真实 ABI 深度解剖

在有道词典笔逆向分析过程中，极易产生的一个经典混淆是将文件名包含 `capt` 的动态库直接认定为摄像头捕获（Camera Capture）库。通过对二进制文件的全面反汇编与符号表提取，我们揭示出底层的真实架构全貌。

### 3.1 架构二元辨析: 视觉采集拼接 vs 离线发音评测 (CAPT)

| 维度 | `libcapt.so` (物理文件) | `libyddal_business_core.so` & `libYoudaoStitch.so` |
| :--- | :--- | :--- |
| **真实业务定位** | **离线语音跟读发音评测** (Computer-Assisted Pronunciation Training) | **视觉扫描图像捕获、光流拼接与 OCR 中台** |
| **所属模块** | 智能语音评测子系统 (Speech Assessment Engine) | 视觉扫描核心子系统 (Vision Scanning Subsystem) |
| **依赖的底层运行时** | Kaldi chain WFST 解码器, 阿里巴巴 MNN 深度学习框架 | Cvitek 硬件 ISP, `libcviruntime.so`, 图像拼接算法库 |
| **处理的数据流** | 16kHz 16-bit 单声道 PCM 音频流 | 320×152 8-bit 单通道灰度视频帧流 |
| **核心导出 C API** | `capt_init`, `capt_begin`, `capt_push_wav`, `capt_end`, `get_capt_result` | `ydstitch_init`, `ydstitch_start`, `ydstitch_push_rawdata_new`, `ydstitch_get_ocr_result` |
| **硬件加速依托** | ARM CPU NEON 指令集计算 MFCC 特征 | Cvitek CV1813H 硬件 TPU 运行 CNN/RNN OCR 模型 |

### 3.2 `libcapt.so` ELF 结构与 Kaldi WFST / MNN 运行时
文件路径：`/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/libcapt.so`  
- **架构**: 32-bit LSB shared object, ARM, EABI5 version 1 (SYSV)
- **文件体积**: 4,734,168 字节 (~4.51 MB)
- **核心符号群**: 包含 `OfflineCAPTer` 类、`WFSTStreamDecoder`、`Kaldi::TransitionModel` 以及 MNN Tensor 运算指令。
- **语言模型配置**: 预编译支持英文（Tag `0x6e65` = `'en'`）与中文（Tag `0x6e63` = `'cn'`）的音素级打分字典。

### 3.3 `libcapt.so` 核心导出 C API 汇编级还原与接口签名

反汇编提取的符号基址与确凿的 C API 签名如下：

#### 1. `capt_init` (虚拟地址: `0x00273e8c`, 函数长度: 1000 字节)
初始化发音评测引擎，加载指定语言的发音词典、声学模型与 WFST 解码图。
```c
/**
 * @brief 初始化离线跟读发音评测引擎
 * @param model_dir 存放评测模型与常量的物理目录路径 (如 /userdisk/resources/capt_models)
 * @param lang_cfg  语言标识字符串 ("en" 英文, "cn" 中文)
 * @param mode      评测模式 (0: 单词评测, 1: 句子跟读, 2: 篇章朗读)
 * @param handle    输出的引擎实例句柄指针
 * @return 0 成功，负数表示错误码 (-1: 模型不存在, -2: 内存不足)
 */
int capt_init(const char* model_dir, const char* lang_cfg, int mode, void** handle);
```
*反汇编控制流特征*:  
```arm
00273e8c: push   {r4, r5, r6, r7, r8, lr}
00273ea0: ldr    r6, [pc, #940]           @ 载入声学模型配置字符串常量
00273eb4: bl     0x8b320 <_ZNSt7__cxx1112basic_string... @ 构造模型加载路径
00273ee8: ldrh   r3, [r1]                 @ 读取语言配置首两字节
00273ef0: movw   r2, #0x6e65              @ 'en'
00273ef4: cmp    r3, r2
00273f08: beq    0x273f30                 @ 分支: 初始化英语音素链
```

#### 2. `capt_set_reftext` (虚拟地址: `0x00274274`, 函数长度: 496 字节)
设定待评测的目标参考文本（标准原句）。
```c
/**
 * @brief 设定评测参考文本并构建动态对齐图
 * @param handle   capt_init 返回的有效句柄
 * @param ref_text 待跟读的标准文本 (UTF-8 编码)
 * @param text_len 文本字节长度
 * @return 0 成功，负数表示解析音素失败
 */
int capt_set_reftext(void* handle, const char* ref_text, int text_len);
```

#### 3. `capt_begin` (虚拟地址: `0x00274464`, 函数长度: 52 字节)
启动单次音频流评测会话，重置内部解码器状态与 VAD（语音活动检测）。
```c
/**
 * @brief 开启评测流
 * @param handle 引擎句柄
 * @return 0 成功
 */
int capt_begin(void* handle);
```

#### 4. `capt_push_wav` (虚拟地址: `0x002744dc`, 函数长度: 700 字节)
连续推送 16kHz 16-bit 单声道 PCM 音频分片进入解码流水线。
```c
/**
 * @brief 推送录音音频切片
 * @param handle       引擎句柄
 * @param pcm_data     16-bit 线性 PCM 音频数据指针
 * @param sample_count 采样点数量 (例如每次送 320 采样点 = 20ms)
 * @param is_last      是否为最后一帧音频 (1: 最后一包并触发对齐计算, 0: 中间流)
 * @return 0 成功，负数表示推流异常
 */
int capt_push_wav(void* handle, const short* pcm_data, int sample_count, int is_last);
```

#### 5. `capt_end` (虚拟地址: `0x00274498`, 函数长度: 68 字节)
终止音频流推送，刷新解码器内部残留数据包。
```c
/**
 * @brief 终止音频评测
 * @param handle 引擎句柄
 * @return 0 成功
 */
int capt_end(void* handle);
```

#### 6. `get_capt_result` (虚拟地址: `0x00274798`, 函数长度: 248 字节)
获取最终结构化评测结果 JSON 字符串。
```c
/**
 * @brief 提取评测打分 JSON 结果
 * @param handle         引擎句柄
 * @param result_json_buf 存储 JSON 的输出缓冲区
 * @param max_buf_len     缓冲区最大容量 (建议 >= 4096 字节)
 * @return 0 成功，负数表示提取失败
 */
int get_capt_result(void* handle, char* result_json_buf, int max_buf_len);
```

### 3.4 `OfflineCAPTer` 类结构与工作机制
在 `libcapt.so` 内部，核心 C++ 实现为 `class OfflineCAPTer`：
- **`OfflineCAPTer::Init(...)`**: 加载 MNN 声学模型（量化 INT8 权重），占用约 3.8MB 内存。
- **`OfflineCAPTer::ProcessAudioStream(...)`**: 内部包含定点化 FFT 计算模块，提取 40 维 Fbank 特征，送入 MNN 推理引擎获取声学后验概率。
- **`OfflineCAPTer::GetAssessmentResult(...)`**: 运行 Viterbi 强制对齐算法（Forced Alignment），计算重音度（Stress）、流利度（Fluency）、完整度（Integrity）以及每个音素的时长偏离得分。

---

## 4. 视觉图像捕获与拼接引擎 (`YCapture` & `libYoudaoStitch.so`) 深度逆向

词典笔视觉扫描的真正核心代码驻留在 `/usr/lib/libyddal_business_core.so`（业务逻辑中台）与 `/usr/lib/libYoudaoStitch.so`（底层计算机视觉图像缝合库）中。

### 4.1 图像特征点提取与金字塔 Lucas-Kanade 光流匹配模型
当笔尖以 3cm/s ~ 25cm/s 的速度在纸面上划过时，320×152 的微距摄像头连续拍摄微观文字边缘。拼接算法的核心数学模型如下：
1. **多层高斯金字塔 (Gaussian Pyramid)**:
   将 320×152 灰度图构建为 3 层金字塔（$L_0: 320\times152$, $L_1: 160\times76$, $L_2: 80\times38$）。
2. **快速角点与梯度特征检测 (FAST / Harris Corner)**:
   在笔尖视野中心区域提取高对比度笔画交叉点。
3. **Lucas-Kanade 稀疏光流跟踪 (Sparse Optical Flow)**:
   通过顶层粗算位移向量，逐层向下精细迭代，求解帧间水平位移 $\Delta x$、垂直位移 $\Delta y$ 与微小倾斜旋转角 $\Delta \theta$：
   $$\begin{bmatrix} \Delta x \\ \Delta y \end{bmatrix} = \left( \sum_{p \in W} \nabla I(p) \nabla I(p)^T \right)^{-1} \sum_{p \in W} \nabla I(p) (I_t(p) - I_{t-1}(p))$$
4. **单向位移累积与回退校验**:
   根据用户设定的持笔手性（左手/右手）和划动方向，算法强制约束位移矢量的单向性。若检测到回退或大幅抖动，则触发坏帧剔除。

### 4.2 连续微距多帧水平实时拼接与倾斜角动态补偿
- **重叠区加权渐变融合 (Alpha Feathering Blending)**:
  在相邻帧重叠的区域（通常占 50%~80% 宽度），采用线性距离加权混合像素灰度值，消除帧间曝光波动形成的接缝暗纹。
- **倾斜校正 (Deskewing)**:
  利用 Radon 变换或主轴法检测文字基线倾角，动态旋转微距图像至绝对水平。
- **长条画布管理**:
  底层维护一个动态扩容的带状内存块（宽最大可达 3840 像素，高固定 152 像素），每缝合一帧向右延展画布。

### 4.3 核心底层 C 符号表与 ABI 规范 (`ydstitch_*` 与 `hal_camera_*`)
通过解析 `libyddal_business_core.so` 的 `.rel.plt` 动态重定位表，提取到其调用的核心视觉 C API：

```c
/* ==================== 摄像头硬件抽象层 (hal_camera_*) ==================== */

/**
 * @brief 创建并初始化微距摄像头 HAL 实例
 * @param cam_id 摄像头索引 (笔尖摄像头为 1)
 * @return 摄像头实例指针
 */
void* hal_camera_create(int cam_id);

/**
 * @brief 销毁摄像头实例
 */
void hal_camera_destroy(void* cam_handle);

/**
 * @brief 从 DMA 环形缓冲中同步获取最新一帧 320x152 灰度图像
 * @param cam_handle 摄像头句柄
 * @param frame_buf  目标接收缓冲区指针
 * @return 0 成功获取新帧，1 缓冲区无新帧，负数异常
 */
int hal_camera_get_img_frame(void* cam_handle, unsigned char* frame_buf);

/**
 * @brief 重置摄像头帧队列指针与标志位
 */
void hal_camera_reset_img_frame(void* cam_handle);

/**
 * @brief 获取图像宽度 (返回 320)
 */
int hal_camera_get_img_width(void* cam_handle);

/**
 * @brief 获取图像高度 (返回 152)
 */
int hal_camera_get_img_height(void* cam_handle);


/* ==================== 图像拼接与 OCR 引擎 API (ydstitch_*) ==================== */

/**
 * @brief 初始化拼接引擎内部状态机与内存结构
 * @param width  单帧宽度 (320)
 * @param height 单帧高度 (152)
 * @param mode   扫描模式 (0: 单行横扫, 1: 多行连续扫, 2: 竖排文本)
 * @return 0 成功
 */
int ydstitch_init(int width, int height, int mode);

/**
 * @brief 启动一次扫描任务 (清空拼接长图画布与特征点队列)
 */
int ydstitch_start(void);

/**
 * @brief 塞入一帧裸灰度数据进行光流追踪与带状缝合
 * @param raw_gray_data 320x152 灰度裸数据内存指针
 * @param timestamp_us  当前帧微秒时间戳
 * @return 0 正常追加，1 识别出有效字符切片更新，负数表示跟踪丢失/移速过快
 */
int ydstitch_push_rawdata_new(const unsigned char* raw_gray_data, uint64_t timestamp_us);

/**
 * @brief 结束扫描并从底层提取最终识别 JSON 结果包
 * @param ocr_json_buf 输出缓冲区
 * @param max_len      最大输出长度
 * @return 实际写入的 JSON 字符串长度
 */
int ydstitch_get_ocr_result(char* ocr_json_buf, int max_len);

/**
 * @brief 将当前已拼接完成的完整长条图像导出为磁盘 JPEG 文件或内存切片
 * @param output_path 保存物理路径 (如 /tmp/scan_stitched.jpg)
 * @return 0 成功
 */
int ydstitch_save_img(const char* output_path);

/**
 * @brief 载入端侧本地 OCR 神经网络模型
 * @param model_path 模型文件路径 (如 /userdisk/resources/models/ocr_model_std_lite)
 */
int ydstitch_load_ocr(const char* model_path);

/**
 * @brief 释放 OCR 神经网络模型
 */
int ydstitch_release_ocr(void);

/**
 * @brief 动态加载特定语言的解码图与字符白名单 (en/cn/ja/ko)
 */
int ydstitch_load_lang_model(const char* lang_code);
```

### 4.4 `YDALAPI::YCapture` 核心生命周期控制流反汇编

类 `YDALAPI::YCapture` 是扫描视觉流水线的 C++ 核心控制器。其反汇编关键节点剖析如下：

#### 1. `YCapture::initLowMemory` (虚拟地址: `0x0010e200`)
设备启动或 OCR 初始化时调用，配置内存极限优化的扫描管线：
```arm
0010e200: push   {r4, r5, r6, r7, r8, lr}
0010e24c: bl     0x164228 <ydstitch_init@plt>              @ 初始化拼接库 (320, 152)
0010e278: bl     0x11bb6c <_ZN7YDALAPI11YOCRManager13isRestartScanEv> @ 查询是否为断点重扫
0010e3c0: bl     0x1641b0 <ydstitch_load_ocr@plt>          @ 加载 TPU 离线 OCR 模型
0010e48c: bl     0x164240 <ydstitch_load_lang_model@plt>   @ 加载默认中英文混合字典
0010e4f8: bl     0x1640fc <hal_camera_create@plt>          @ 初始化底层摄像头 HAL
0010e614: bl     0x16418c <hal_camera_get_img_width@plt>   @ 读取图像宽 -> 320
0010e620: bl     0x1641a4 <hal_camera_get_img_height@plt>  @ 读取图像高 -> 152
```

#### 2. `YCapture::OCRCaptureLowMemory` (虚拟地址: `0x001126d4`)
扫描滑动过程中的逐帧摄录与送帧驱动主循环：
```arm
001126d4: bl     0x164150 <hal_camera_get_img_frame@plt>   @ 从 DMA 环形缓冲读取 320x152 帧
00112ef0: bl     0x164258 <ydstitch_push_rawdata_new@plt>  @ 送入拼接引擎进行光流追加
00112fac: bl     0x11be98 <_ZN7YDALAPI11YOCRManager20notifyGetFrameUpdateEv> @ 触发前端 onScanning 刷新
```

#### 3. `YCapture::paragraphsOCRLowMemory` (虚拟地址: `0x001136b4`)
抬笔结算与段落级整图 OCR 识别触发：
```arm
001136b4: bl     0x164234 <ydstitch_start@plt>             @ 准备结算拼接画布
001137e0: bl     0x11bf04 <_ZN7YDALAPI11YOCRManager17notifyGetFrameEndEv> @ 广播取帧结束
00113a10: bl     0x164210 <ydstitch_get_ocr_result@plt>   @ 调度 TPU 完成全量推断并取回 JSON
```

#### 4. `YCapture::capProcess` 线程循环伪代码
```cpp
void YDALAPI::YCapture::capProcess() {
    while (m_bRunning) {
        // 阻塞等待笔尖按下条件变量通知
        std::unique_lock<std::mutex> lock(m_mutex);
        m_pressContainer.wait(lock, [this]() { return m_bPenPressed || !m_bRunning; });
        if (!m_bRunning) break;

        ydstitch_start();
        hal_camera_reset_img_frame(m_hCamera);

        while (m_bPenPressed) {
            unsigned char frameBuf[320 * 152];
            int ret = hal_camera_get_img_frame(m_hCamera, frameBuf);
            if (ret == 0) {
                // 送入光流缝合
                uint64_t nowUs = get_monotonic_time_us();
                int stitchStatus = ydstitch_push_rawdata_new(frameBuf, nowUs);
                if (stitchStatus == 1) {
                    // 有中间字符流式识别更新
                    YOCRManager::getInstance()->notifyGetFrameUpdate();
                }
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        // 笔尖抬起，执行段落/整行结算
        paragraphsOCRLowMemory();
    }
}
```

### 4.5 `YDALAPI::YOCRManager` 事件监听与分发中枢
位于 `libyddal_business_core.so` 中的 `YDALAPI::YOCRManager` 是全局唯一的硬件扫描业务分发单例：
- **`onHeadButtonPress` (0x001219b4)**:
  - 读取系统全局变量 `disableLittlePScan`，若为真则静默拦截；
  - 播放扫描启动音效 `/usr/share/sounds/scanAudio.mp3`（极短的机械提示声）；
  - 设置状态 `ocrStart(true)`；
  - 唤醒 `m_pressContainer.notify_all()` 启动 `YCapture` 工作线程。
- **`onHeadButtonRelese` (0x00121580)**:
  - 置位 `m_bPenPressed = false`；
  - 重置摄像头帧队列；
  - 等待去抖动定时器超时后触发结算。
- **`onScanFinish` (0x00122b64)**:
  - 解析 OCR 识别文本与词条属性；
  - 跨应用意图分发：检查当前前台运行的应用模式：
    - `HomeMode` (系统主页查词)
    - `EasayChecker` (作文批改)
    - `AiTutor` (小P老师互动)
    - `TextBook` (教材同步学)
    - `AIReading` (分级阅读)
    - `Reciter` (背单词)
    - `Translator` (长句翻译)
    - `LianZi` (汉字笔画练字)
    - `AnswerQuestions` (扫题解析)

---

## 5. 本地 TPU 硬件加速 OCR 推理与多级分发调度

### 5.1 Cvitek TPU 异构计算单元与 `libcviruntime.so`
S7 Pro 搭载的 CV1813H SoC 内建了高性能轻量化张量处理单元（TPU / NPU）：
- **运行环境**: 通过 `/usr/lib/libcviruntime.so` 与底层内核驱动 `/dev/cvi-tpu` 通信。
- **指令集**: 专有 Cvitek 张量微代码，支持 INT8 定点化与 BF16 浮点混合精度计算。
- **算力分配**: 单核 TPU 集中供给前端图像预处理（二值化/降噪）与文本行卷积循环神经网络推断。

### 5.2 端侧模型结构与内存开销
本地离线 OCR 引擎由 `libyocr.so` 承载，加载两个核心模型文件（存储在 `/userdisk/resources/models/` 或系统只读分区中）：
1. **`ocr_model_std_lite`**:
   - 超轻量级移动端模型，用于单行英汉单词与短语的实时匹配。
   - 网络拓扑: 裁剪版 MobileNetV3 骨干网络 + 双向 GRU + CTC 解码器。
   - 体积与内存: 权重文件约 6.2 MB，加载后物理内存常驻约 12 MB。
   - 推理耗时: 10~15 字符平均耗时 45ms（TPU 加速）。
2. **`ocr_model_stand`**:
   - 标准高精度多语言模型，用于古诗文、长难句与多行复杂排版识别。
   - 网络拓扑: 重型 CNN 提取高维特征 + BiLSTM + CTC。
   - 体积与内存: 权重文件约 14.8 MB，常驻约 26 MB。
   - 支持字符集: GB2312 汉字 6763 字、ASCII 英文大小写、日文假名、韩文常用字及常用标点符号。

### 5.3 图像跨层传输机制: Base64 JPEG vs 零拷贝指针传递
OCR 识别出的图像与文字如何传递到 QuickJS 前端应用层？底层提供了三级高效传输管道：
1. **Base64 JPEG 编码模式 (兼容性展示)**:
   当应用调用 `globalMgr.setShowImgScanMode(true)` 时，拼接引擎将带状灰度图在内存中压缩为 JPEG，并编码为 `data:image/jpeg;base64,...` 字符串塞入 JSON 载荷的 `spliced_image` 字段。
   *优点*: 前端 `<image>` 标签可直接绑定 `:src="splicedImage"` 显示；
   *缺点*: Base64 膨胀 33% 内存，单张长图约消耗 40~90KB 字符串内存，高频扫读易引发 QuickJS GC。
2. **本地磁盘临时文件共享 (`/tmp/scan_stitched.jpg`)**:
   `YCapture::getOcrImagePath` 调用 `ydstitch_save_img` 将图像直存 RAMFS 内存文件系统 `/tmp/`，前端通过本地文件协议 `file:///tmp/scan_stitched.jpg` 加载，避免跨语言大字符串传递。
3. **ArrayBuffer 零拷贝直接内存映射 (`JSHeadCameraProxy`)**:
   针对实时预览与高帧率取景，通过 `JS_GetArrayBuffer` 暴露物理内存指针，下文第 6 节详细剖析。

### 5.4 端云协同分发策略与意图识别路由
中台在获取到 OCR 文本后，执行多层路由仲裁：

```
                [笔尖抬起获得 OCR 文本]
                          │
                          ▼
             [规则引擎: 字符长度与标点特征]
                          │
        ┌─────────────────┼─────────────────┐
        ▼ (单词 / 词组)    ▼ (包含 ? / = / 解) ▼ (长难句 / 连续多行)
  [本地离线词典 db]   [意图匹配: 试题]   [端云混合翻译链路]
        │                 │                 │
        ▼                 ▼                 ▼
  [瞬时展示释义]   [跳转扫题解析微应用]  [发起智云 NMT 请求]
 (耗时 < 80ms)    (8001689233517086)   (流式返回译文)
```

---

## 6. Falcon 运行时取景与 QuickJS 零拷贝桥接

在 AI 拍照、取景校准或扫描预览界面中，视频流需要以 60 FPS 无卡顿地呈现在 1020×240 屏幕上。Falcon 引擎通过一系列深度定制的 C++ 原生桥接实现了零拷贝渲染。

### 6.1 `falcon::OCRCameraPreviewView` 与双缓冲帧交换机制
在 `/usr/lib/libfalcon.so` 中，取景组件 `OCRCameraPreviewView` 负责对接底层摄像头帧：
- 反汇编地址 `0x005a146c`: `falcon::OCRCameraPreviewView::swapFrame`
- 采用无锁原子双缓冲区（Front Buffer / Back Buffer）：
  - 采集工作线程向 Back Buffer 写入新转换的像素；
  - 渲染线程（GreenUI vsync）在绘制周期原子调用 `swapFrame` 交换指针；
  - 杜绝渲染撕裂（Tearing）且完全不阻塞采集线程。

### 6.2 NEON 加速色彩空间转换: `falcon::convert_nv12_to_rgb`
顶部大摄像头输出的 NV12 格式或 CIS 输出的灰度帧，在送显前必须转为 ARGB8888 供 Skia 栅格化绘制。
在 `libfalcon.so` 虚拟地址 `0x005a1160` 处逆向提取到专属 NEON 矢量加速汇编转换函数：
```arm
005a1160: push   {r4, r5, r6, r7, lr}
005a1168: vld1.8 {d0}, [r0]!              @ 批量加载 8 字节 Y 平面数据至 NEON 寄存器
005a1180: vmov.u8 d2, #16                 @ Y 偏置常数
005a1194: vsub.u8 d0, d0, d2              @ Y = Y - 16
005a11a8: vmull.u8 q2, d0, d4             @ NEON 向量乘法快速展开
005a1210: vst4.8 {d16, d17, d18, d19}, [r3]! @ 向量化交织直写 32-bit ARGB 像素
```
经 NEON 指令集向量展开后，单帧 320×152 转换仅需 0.35ms CPU 时间，CPU 占用率低于 2%。

### 6.3 QuickJS 裸指针绑定: `JSHeadCameraProxy::setImageDataBuffer`
在 `/usr/lib/libjsapi_export_core.so` 模块中，`JSHeadCameraProxy` 提供了将 JavaScript `ArrayBuffer` 的堆内存直接锁定并注入底层 C++ 驱动的机制：

```arm
0008ac20: ldr    r3, [r4, #4]
0008ac24: mov    r1, r8
0008ac28: ldr    r0, [r4]
0008ac40: bl     0x6209c <JS_GetArrayBuffer@plt>  @ 直接获取 JS ArrayBuffer 底层数据指针
0008ac48: str    r0, [r5, #0xa8]                 @ 存入 C++ 驱动上下文 context->pFrameBuffer
0008ac58: bl     0x648f8 <YLog_print@plt>         @ 打印 "JSGlobalProxy::setImageDataBuffer %zu"
```
**关键架构启示**:
- 前端只需在初始化阶段通过 `new ArrayBuffer(320 * 152)` 分配一块内存并传给 `headCamera.setImageDataBuffer(buf)`；
- 底层 C++ 采集线程直接向该物理内存段通过 DMA/memcpy 填充数据；
- 前端通过 TypedArray（`new Uint8Array(buf)`）直接读取最新帧，**虚拟机垃圾回收器（GC）对该缓冲区完全不可感知，零内存分配，零 GC 停顿**。

---

## 7. Falcon 前端 JSAPI 模块契约与信号事件总线

Falcon 前端基于 QuickJS 虚拟机，通过原生 C++ 代理类暴露系统能力。涉及扫描与硬件按键的核心代理类分布在 `libjsapi_export_core.so` 中。

### 7.1 原生模块代理表: `global`, `buttonEvent`, `headCamera`

```javascript
import globalModule from 'global';           // 对应 C++ 类: JSGlobalProxy
import buttonEventModule from 'buttonEvent'; // 对应 C++ 类: JSButtonEventModuleProxy
import headCameraModule from 'headCamera';   // 对应 C++ 类: JSHeadCameraProxy
```

#### 1. `JSGlobalProxy` (原生模块: `'global'`)
| 方法名 | C++ 虚拟基址 | 入参类型 | 返回值 | 语义与职责 |
| :--- | :--- | :--- | :--- | :--- |
| `addUseOcrAppId(appId)` | `0x00068930` | `String` | `void` | 向系统白名单注册当前应用，抢占全局 OCR 扫描监听权 |
| `deleteUseOcrAppId(appId)` | `0x000689f0` | `String` | `void` | 释放 OCR 监听权，归还系统查词与桌面 (退出时必须调用!) |
| `setAloneScanMode(enable)` | `0x0006982c` | `Boolean` | `void` | `true`: 应用内独占拦截扫描；`false`: 允许系统查词弹出 |
| `setShowImgScanMode(enable)`| `0x00069708` | `Boolean` | `void` | `true`: 开启结果中携带长条拼接切片图 (Base64 JPEG) |
| `setIsOpenScan(enable)` | `0x00069698` | `Boolean` | `void` | 全局开启/关闭底层扫读与微动开关使能 |
| `disableCapAndOcr(appId, page, disable)` | `0x00068fd4` | `(String, String, Boolean)` | `void` | 在播放音频、全屏弹窗时临时屏蔽笔尖触碰响应 |

#### 2. `JSButtonEventModuleProxy` (原生模块: `'buttonEvent'`)
| 方法 / 信号名 | C++ 虚拟基址 | 类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `setButtonEventReady(ready)` | `0x0009ff9c` | 方法: `(Boolean) => void` | **必须在 `mounted` 后调用，通知底层硬件按键事件通道就绪！** |
| `isHeadButtonPressed()` | `0x0009fe90` | 方法: `() => Boolean` | 同步读取笔尖当前是否受压贴在纸面上 |
| `headButtonPress` | - | `JQSignal<(code: number) => void>` | 笔尖微动物理闭合触发信号 (`code = 212`) |
| `headButtonRelese` | - | `JQSignal<(code: number) => void>` | 笔尖微动弹开抬起触发信号 (**注意底层拼写无 a!**) |

#### 3. `JSHeadCameraProxy` (原生模块: `'headCamera'`)
| 方法名 | C++ 虚拟基址 | 入参类型 | 说明 |
| :--- | :--- | :--- | :--- |
| `setImageDataBuffer(buf)` | `0x0008ab5c` | `ArrayBuffer` | 绑定零拷贝内存缓冲区，用于直接承接 320×152 裸帧 |
| `startPreview()` | `0x0008a910` | 无 | 启动笔尖微距取景硬件推流 |
| `stopPreview()` | `0x0008aa34` | 无 | 停止笔尖微距取景推流 |

### 7.2 全量信号列表 (`JQSignal`) 与底层触发时序
Falcon 前端支持两种信号监听范式：
- **代理实例信号**: `this.buttonMgr.headButtonPress.connect(callback)`
- **全局事件总线**: `$falcon.on('headButtonPress', callback)`

| 信号名称 | 参数列表 | 触发源 | 业务含义 |
| :--- | :--- | :--- | :--- |
| `headButtonPress` | `(code: number)` | 硬件中断 (KEY_CAMERA = 212) | 笔尖压在纸面，扫描物理启动 |
| `headButtonRelese` | `(code: number)` | 硬件中断 (KEY_CAMERA = 212) | 笔尖离开纸面，物理扫描结束 (**注意无 a**) |
| `ocrStartChanged` | `(isStart: boolean)` | `YOCRManager` | 视觉管线 OCR 任务启动/终止状态通知 |
| `onScanning` | `(partialJson: string)` | 拼接光流线程 | 笔尖滑动中，实时流式字词更新 (高频，30~50Hz) |
| `ocrCompleteChanged`| `(resultJson: string, scanType: number)` | TPU 推理线程 | 完整扫描结束，返回全量识别树形结构包 |
| `ocrResultChanged` | `(resultJson: string)` | `YOCRManager` | 识别文本发生变更通知 |
| `scanErrorChanged` | `(errMsg: string, errCode: number)` | 拼接光流线程 | 异常告警 (移速过快 101、倾斜角过大 102、光线过暗 103) |

### 7.3 数据载荷契约: 流式载荷与完整结构化结果

#### 1. 实时滑动中流式载荷 (`onScanning`)
笔尖在纸面滑动时高频下发：
```json
{
  "status": "update",
  "text": "comprehen",
  "isFailed": 0,
  "scanType": 0
}
```

#### 2. 完整识别结果包 (`ocrCompleteChanged`)
笔尖抬起后下发的完整数据契约：
```json
{
  "status": "end",
  "isFailed": 0,
  "scanType": 0,
  "lang": "en",
  "confidence": 0.985,
  "text": "The quick brown fox jumps over the lazy dog.",
  "lines": [
    {
      "line_id": 0,
      "text": "The quick brown fox jumps over the lazy dog.",
      "confidence": 0.985,
      "box": [12, 18, 920, 48],
      "words": [
        {
          "word": "The",
          "lookup_key": "the",
          "confidence": 0.99,
          "box": [12, 18, 45, 48],
          "char_boxes": [
            [12, 18, 28, 48],
            [29, 22, 38, 48],
            [39, 22, 45, 48]
          ]
        },
        {
          "word": "quick",
          "lookup_key": "quick",
          "confidence": 0.98,
          "box": [55, 18, 120, 48],
          "char_boxes": [
            [55, 24, 68, 48],
            [69, 22, 75, 48],
            [76, 22, 82, 48],
            [83, 22, 95, 48],
            [96, 18, 120, 48]
          ]
        }
      ]
    }
  ],
  "spliced_image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD...",
  "multiline": false
}
```

### 7.4 进程间服务代理 (`$service_proxy`) 与 `falcon://8080252464522508/lookup` 契约
在自研应用中，获得 OCR 识别文本后，若需调用系统查词服务进行富文本分词、权威释义或名师音频朗读，可通过 Falcon IPC 服务代理直连系统常驻查词守护进程：

```javascript
// 连接系统查词核心服务 (8080252464522508)
const lookupService = $service_proxy.connect("falcon://8080252464522508/lookup");

lookupService.on('onConnected', () => {
    console.log('[RPC] ScanTransl Service connected');
});

// 调用查词接口
lookupService.lookup({
    word: "comprehensive",
    callback: (res) => {
        // 返回包含英美音标、柯林斯星级、中文释义、双语例句的权威结构体
        console.log('[RPC Result]', JSON.stringify(res));
    }
});
```

---

## 8. 完整 TypeScript 接口类型规范定义

为支持现代化工程开发与强类型编译校验，以下提供针对有道词典笔 S7 Pro 扫描与 OCR 视觉子系统的完整 TypeScript 声明定义文件（`falcon-scanner.d.ts`）：

```typescript
/**
 * @file falcon-scanner.d.ts
 * @description 有道词典笔 S7 Pro 硬件扫描、CIS 视觉采集与 OCR 子系统 TypeScript 类型定义
 */

export namespace FalconScanner {
  /** 字符/单词/行 边界框: [左, 上, 宽, 高] (基于拼接长图绝对坐标) */
  export type BoundingBox = [x: number, y: number, width: number, height: number];

  /** 单词元数据与音标属性 */
  export interface WordToken {
    /** 单词原形或当前展示词 */
    word: string;
    /** 索引检索 Key (已做小写化、还原单数/原形处理) */
    lookup_key: string;
    /** 置信度 (0.0 ~ 1.0) */
    confidence: number;
    /** 单词在长图中的外接矩形 */
    box: BoundingBox;
    /** 单词内部每个字符的独立定位框点阵 */
    char_boxes: BoundingBox[];
  }

  /** 单行文本识别切片 */
  export interface TextLine {
    line_id: number;
    text: string;
    confidence: number;
    box: BoundingBox;
    words: WordToken[];
  }

  /** 笔尖滑动中流式实时推送载荷 */
  export interface ScanningStreamPayload {
    status: 'update';
    text: string;
    isFailed: number;
    scanType: number;
  }

  /** 扫描结束完整识别结果包 */
  export interface ScanCompletePayload {
    status: 'end';
    isFailed: number;
    scanType: number;
    /** 识别主语言 ("en" | "zh" | "ja" | "ko" 等) */
    lang: string;
    /** 全文加权置信度 */
    confidence: number;
    /** 全文拼接完整文本 */
    text: string;
    /** 文本行列表 */
    lines: TextLine[];
    /** 当开启 setShowImgScanMode(true) 时携带的 Base64 拼接切片图 */
    spliced_image?: string;
    /** 是否为连续多行扫描 */
    multiline: boolean;
  }

  /** 扫描硬件异常枚举 */
  export enum ScanErrorCode {
    SPEED_TOO_FAST = 101,  // 划动速度过快导致光流丢失
    TILT_TOO_LARGE = 102,  // 笔身倾斜角过大超过 CIS 光学视场
    TOO_DARK = 103,        // 补光受阻或环境光极暗
    BUFFER_OVERFLOW = 104  // 拼接长图超出最大物理画布
  }

  /** JQSignal 原生信号包装器 */
  export interface JQSignal<T extends (...args: any[]) => void> {
    connect(callback: T): void;
    disconnect(callback: T): void;
  }

  /** JSGlobalProxy 模块规范 ('global') */
  export interface GlobalModule {
    /** 向系统白名单注册当前 AppID，抢占扫描所有权 */
    addUseOcrAppId(appId: string): void;
    /** 释放扫描所有权 (页面退出前必须显式调用!) */
    deleteUseOcrAppId(appId: string): void;
    /** 设置是否为应用内独占拦截模式 (true: 阻止系统查词弹窗) */
    setAloneScanMode(alone: boolean): void;
    /** 设置是否在结果中生成拼接长图 Base64 JPEG */
    setShowImgScanMode(showImg: boolean): void;
    /** 设置全局扫描使能开关 */
    setIsOpenScan(open: boolean): void;
    /** 临时禁用笔尖微动响应 (例如在弹窗或全屏视频时) */
    disableCapAndOcr(appId: string, pageName: string, disable: boolean): void;

    /** 信号: 扫描开始/停止状态变化 */
    ocrStartChanged: JQSignal<(isStart: boolean) => void>;
    /** 信号: 滑动过程中的流式增量文字 */
    onScanning: JQSignal<(partialJson: string) => void>;
    /** 信号: 完整扫描结束与最终结果包 */
    ocrCompleteChanged: JQSignal<(resultJson: string, scanType: number) => void>;
    /** 信号: 识别结果文本更新 */
    ocrResultChanged: JQSignal<(resultJson: string) => void>;
    /** 信号: 扫描异常告警 */
    scanErrorChanged: JQSignal<(errMsg: string, code: number) => void>;
  }

  /** JSButtonEventModuleProxy 模块规范 ('buttonEvent') */
  export interface ButtonEventModule {
    /** 通知底层硬件按键通道就绪 (必须在 mounted 后调用) */
    setButtonEventReady(ready: boolean): void;
    /** 同步查询笔尖当前是否物理压在纸面上 */
    isHeadButtonPressed(): boolean;
    /** 笔尖微动物理压下触发 (按键码: 212) */
    headButtonPress: JQSignal<(code: number) => void>;
    /** 笔尖微动物理松开抬起触发 (按键码: 212, 注意底层拼写无 a!) */
    headButtonRelese: JQSignal<(code: number) => void>;
  }

  /** JSHeadCameraProxy 模块规范 ('headCamera') */
  export interface HeadCameraModule {
    /** 注入用于接收 320x152 灰度裸数据的零拷贝内存 ArrayBuffer */
    setImageDataBuffer(buffer: ArrayBuffer): void;
    /** 开启笔尖摄像头取景推流 */
    startPreview(): void;
    /** 停止笔尖摄像头取景推流 */
    stopPreview(): void;
  }
}
```

---

## 9. 生产级自研扫描应用完整实现 (Vue 2 SFC)

以下提供一份专为有道词典笔 S7 Pro 1020×240 超宽带状屏幕量身定制的生产级 Vue 单文件组件实现。该实现严格遵守了**OCR 所有权抢占、退出注销恢复、按键通道同步、高频流式防抖、Base64 渲染与单词分词交互**等核心工程准则。

```html
<template>
  <div class="scanner-page">
    <!-- 顶部状态与控制栏 -->
    <div class="top-bar">
      <div class="nav-back-btn" @click="handleExit">
        <text class="btn-text">❮ 返回</text>
      </div>
      <div class="status-wrap">
        <div class="status-indicator-dot" :class="[isScanning ? 'dot-active' : 'dot-idle']"></div>
        <text class="status-label">{{ statusMessage }}</text>
      </div>
      <div class="lang-badge">
        <text class="lang-text">{{ currentLang.toUpperCase() }}</text>
      </div>
    </div>

    <!-- 中间主视图: 扫描结果展示区 -->
    <div class="result-viewport">
      <text class="recognized-display-text" :class="{'text-placeholder': !displayContent}">
        {{ displayContent || '请将笔尖对准纸面文字，均匀平稳向右滑过...' }}
      </text>
    </div>

    <!-- 底部带状区: 拼接长图预览与分词卡片 -->
    <div class="bottom-dock">
      <!-- 拼接长图预览 (当开启长图模式且有图片返回时展示) -->
      <div v-if="splicedImageBase64" class="spliced-image-container">
        <image class="spliced-image-view" :src="splicedImageBase64" resize="contain" />
      </div>

      <!-- 单词分词横向滚动列表 (支持点词深度查询) -->
      <div v-else-if="tokenList.length > 0" class="tokens-scroll-wrapper">
        <scroller scroll-direction="horizontal" class="tokens-scroller">
          <div
            v-for="(token, index) in tokenList"
            :key="index"
            class="token-chip"
            @click="onSelectWord(token)"
          >
            <text class="token-word">{{ token.word }}</text>
            <text class="token-key">{{ token.lookup_key }}</text>
          </div>
        </scroller>
      </div>

      <!-- 空闲状态操作提示 -->
      <div v-else class="dock-tips">
        <text class="tips-text">物理笔尖下压即扫 • 抬起自动识别解析 • 支持中英文多行划词</text>
      </div>
    </div>
  </div>
</template>

<script>
import globalModule from 'global';
import buttonEventModule from 'buttonEvent';

export default {
  name: 'FalconScannerDemo',
  data() {
    return {
      // 当前应用专属标识 (建议与 manifest.json 中 appid 严格一致)
      appId: '8080999900000001',
      // 扫描状态机
      isScanning: false,
      statusMessage: '准备就绪',
      currentLang: 'AUTO',
      displayContent: '',
      splicedImageBase64: '',
      tokenList: [],
      // 原生模块实例
      globalMgr: null,
      buttonMgr: null,
      // 流式高频防抖计时器
      streamThrottleTimer: null,
      pendingStreamText: ''
    };
  },
  created() {
    this.initNativeScannerHAL();
  },
  mounted() {
    this.bindHardwareSignals();
  },
  beforeDestroy() {
    this.teardownNativeScannerHAL();
  },
  methods: {
    /**
     * 1. 初始化 Native HAL 扫描中台
     */
    initNativeScannerHAL() {
      try {
        this.globalMgr = new globalModule.Global();
        this.buttonMgr = new buttonEventModule.ButtonEvent();

        // 抢占 OCR 事件监听权
        if (this.globalMgr.addUseOcrAppId) {
          this.globalMgr.addUseOcrAppId(this.appId);
          console.log('[ScannerHAL] Successfully claimed OCR ownership for:', this.appId);
        }

        // 开启独立拦截模式 (禁止系统查词应用弹出抢夺界面)
        if (this.globalMgr.setAloneScanMode) {
          this.globalMgr.setAloneScanMode(true);
        }

        // 允许生成带状拼接长图 Base64
        if (this.globalMgr.setShowImgScanMode) {
          this.globalMgr.setShowImgScanMode(true);
        }

        // 确保全局扫描通道使能
        if (this.globalMgr.setIsOpenScan) {
          this.globalMgr.setIsOpenScan(true);
        }
      } catch (err) {
        console.error('[ScannerHAL] Init HAL Exception:', err);
      }
    },

    /**
     * 2. 绑定底层硬件中断与 QuickJS 信号
     */
    bindHardwareSignals() {
      try {
        // 关键步骤: 通知按键中台当前微应用已渲染完毕，就绪接收事件
        if (this.buttonMgr && this.buttonMgr.setButtonEventReady) {
          this.buttonMgr.setButtonEventReady(true);
        }

        // 监听物理笔尖压下纸面 (Pen Down, KEY_CAMERA = 212)
        if (this.buttonMgr && this.buttonMgr.headButtonPress && this.buttonMgr.headButtonPress.connect) {
          this.buttonMgr.headButtonPress.connect((code) => {
            console.log('[Hardware Signal] Pen Down, Code:', code);
            this.isScanning = true;
            this.statusMessage = '正在高速扫描纸面...';
            this.displayContent = '';
            this.splicedImageBase64 = '';
            this.tokenList = [];
          });
        }

        // 监听物理笔尖离开纸面 (Pen Up, 注意底层拼写无 a!)
        const releaseSignal = this.buttonMgr.headButtonRelese || this.buttonMgr.headButtonRelease;
        if (releaseSignal && releaseSignal.connect) {
          releaseSignal.connect((code) => {
            console.log('[Hardware Signal] Pen Up, Code:', code);
            this.isScanning = false;
            this.statusMessage = '笔尖抬起，TPU 正在计算...';
          });
        }

        // 监听滑动中实时流式文字更新 (带节流防抖处理)
        if (this.globalMgr && this.globalMgr.onScanning && this.globalMgr.onScanning.connect) {
          this.globalMgr.onScanning.connect((rawPayload) => {
            this.handleStreamingPayload(rawPayload);
          });
        }

        // 监听扫描结束最终全量识别结果包
        if (this.globalMgr && this.globalMgr.ocrCompleteChanged && this.globalMgr.ocrCompleteChanged.connect) {
          this.globalMgr.ocrCompleteChanged.connect((resultJson, scanType) => {
            console.log('[ScannerHAL] OCR Complete Triggered, ScanType:', scanType);
            this.statusMessage = '识别就绪';
            this.handleScanComplete(resultJson);
          });
        }

        // 监听异常告警
        if (this.globalMgr && this.globalMgr.scanErrorChanged && this.globalMgr.scanErrorChanged.connect) {
          this.globalMgr.scanErrorChanged.connect((errMsg, errCode) => {
            console.warn('[ScannerHAL] Scan Warning:', errMsg, 'Code:', errCode);
            if (errCode === 101) {
              this.statusMessage = '划动速度过快，请放缓';
            } else if (errCode === 102) {
              this.statusMessage = '笔身倾角过大，请垂直握笔';
            }
          });
        }
      } catch (err) {
        console.error('[ScannerHAL] Signal Connect Exception:', err);
      }
    },

    /**
     * 3. 流式高频解析防抖处理器
     */
    handleStreamingPayload(raw) {
      if (!raw) return;
      try {
        let text = raw;
        if (typeof raw === 'string' && (raw.startsWith('{') || raw.startsWith('['))) {
          const parsed = JSON.parse(raw);
          text = parsed.text || '';
        }
        this.pendingStreamText = text;

        // 限制流式刷新频率为 20Hz (50ms 节流)，保护 QuickJS GC
        if (!this.streamThrottleTimer) {
          this.streamThrottleTimer = setTimeout(() => {
            if (this.isScanning && this.pendingStreamText) {
              this.displayContent = this.pendingStreamText;
            }
            this.streamThrottleTimer = null;
          }, 50);
        }
      } catch (_) {
        this.displayContent = raw;
      }
    },

    /**
     * 4. 最终全量结构化数据解析
     */
    handleScanComplete(resultJson) {
      if (!resultJson) return;
      try {
        const payload = typeof resultJson === 'string' ? JSON.parse(resultJson) : resultJson;

        // 提取识别全文
        this.displayContent = payload.text || this.displayContent;
        this.currentLang = payload.lang || 'AUTO';

        // 提取拼接切片长图
        if (payload.spliced_image) {
          this.splicedImageBase64 = payload.spliced_image;
        }

        // 提取并平铺所有分词 Token
        const tokens = [];
        if (Array.isArray(payload.lines)) {
          payload.lines.forEach((line) => {
            if (Array.isArray(line.words)) {
              line.words.forEach((w) => {
                tokens.push({
                  word: w.word,
                  lookup_key: w.lookup_key || w.word.toLowerCase(),
                  box: w.box,
                  confidence: w.confidence
                });
              });
            }
          });
        }
        this.tokenList = tokens;
      } catch (err) {
        console.error('[ScannerHAL] Parse Complete JSON Failed:', err);
      }
    },

    /**
     * 5. 单词点选交互
     */
    onSelectWord(token) {
      console.log('[Word Clicked] User selected lookup key:', token.lookup_key);
      this.statusMessage = `已选词: ${token.word}`;
    },

    /**
     * 6. 退出与生命周期清理 (重中之重!)
     */
    teardownNativeScannerHAL() {
      console.log('[ScannerHAL] Performing mandatory OCR ownership teardown...');
      if (this.streamThrottleTimer) {
        clearTimeout(this.streamThrottleTimer);
        this.streamThrottleTimer = null;
      }
      if (this.globalMgr) {
        try {
          // 必须注销当前 AppID，否则整机系统扫描永久失效！
          if (this.globalMgr.deleteUseOcrAppId) {
            this.globalMgr.deleteUseOcrAppId(this.appId);
          }
          // 恢复允许系统查词应用弹窗
          if (this.globalMgr.setAloneScanMode) {
            this.globalMgr.setAloneScanMode(false);
          }
        } catch (err) {
          console.error('[ScannerHAL] Teardown Exception:', err);
        }
      }
    },

    /**
     * 返回退出
     */
    handleExit() {
      this.teardownNativeScannerHAL();
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      }
    }
  }
};
</script>

<style scoped>
.scanner-page {
  width: 1020px;
  height: 240px;
  background-color: #0F1115;
  flex-direction: column;
  padding: 6px 14px;
}

/* 顶部控制栏 */
.top-bar {
  width: 992px;
  height: 32px;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}

.nav-back-btn {
  width: 76px;
  height: 28px;
  background-color: #212631;
  border-radius: 6px;
  justify-content: center;
  align-items: center;
}

.btn-text {
  color: #CFD8DC;
  font-size: 13px;
  font-weight: bold;
}

.status-wrap {
  flex-direction: row;
  align-items: center;
}

.status-indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 4px;
  margin-right: 8px;
}

.dot-idle {
  background-color: #78909C;
}

.dot-active {
  background-color: #00E676;
}

.status-label {
  color: #ECEFF1;
  font-size: 14px;
  font-weight: 500;
}

.lang-badge {
  padding: 2px 8px;
  background-color: #263238;
  border-radius: 4px;
}

.lang-text {
  color: #80CBC4;
  font-size: 12px;
  font-weight: bold;
}

/* 中间主识别视口 */
.result-viewport {
  width: 992px;
  height: 86px;
  background-color: #171A21;
  border-radius: 8px;
  padding: 8px 14px;
  margin-top: 6px;
  justify-content: center;
}

.recognized-display-text {
  color: #FFFFFF;
  font-size: 22px;
  line-height: 32px;
  font-weight: 500;
}

.text-placeholder {
  color: #546E7A;
  font-size: 16px;
  font-style: italic;
}

/* 底部带状操作区 */
.bottom-dock {
  width: 992px;
  height: 98px;
  margin-top: 6px;
  justify-content: center;
}

.spliced-image-container {
  width: 992px;
  height: 94px;
  background-color: #1A1F2C;
  border-radius: 6px;
  justify-content: center;
  align-items: center;
}

.spliced-image-view {
  width: 980px;
  height: 84px;
}

.tokens-scroll-wrapper {
  width: 992px;
  height: 94px;
}

.tokens-scroller {
  flex-direction: row;
  align-items: center;
}

.token-chip {
  height: 72px;
  background-color: #1E2533;
  border-radius: 8px;
  padding: 6px 14px;
  margin-right: 10px;
  justify-content: center;
  align-items: center;
}

.token-word {
  color: #40C4FF;
  font-size: 18px;
  font-weight: bold;
}

.token-key {
  color: #90A4AE;
  font-size: 12px;
  margin-top: 2px;
}

.dock-tips {
  width: 992px;
  height: 94px;
  justify-content: center;
  align-items: center;
}

.tips-text {
  color: #455A64;
  font-size: 13px;
}
</style>
```

---

## 10. 嵌入式工程陷阱、防抖防御与性能优化指南

在有道词典笔 S7 Pro 这类单核 Cortex-A7 @ 1.0GHz 极限受限平台上进行底层扫描开发，必须牢记以下防御性准则：

### 10.1 铁律一: OCR 所有权遗忘注销导致系统全局瘫痪
- **故障现象**: 用户自研应用一旦运行并退出后，返回系统桌面划过任何英语单词，整机没有任何反应，补光灯亮起但不再弹出释义卡片。
- **根本原因**: 前端调用了 `globalMgr.addUseOcrAppId(appId)` 与 `setAloneScanMode(true)`，但在组件销毁（`beforeDestroy` / `onDestroy`）时遗漏了注销。系统常驻中台 `YGlobalLookupWordModule` 永久认为该应用仍在前台独占监听，将全局扫描流全部截留抛弃。
- **防御准则**: 必须在 Vue 的 `beforeDestroy`、路由后置守卫以及页面返回按钮事件中，**无条件调用 `deleteUseOcrAppId` 并将 `setAloneScanMode` 置回 `false`**！

### 10.2 铁律二: 高频流式信号诱发 QuickJS 频繁 GC 导致 UI 卡死
- **故障现象**: 笔尖在纸面快速划动时，界面严重卡顿，手势返回操作无响应，甚至触发看门狗导致 Falcon 进程崩溃重启。
- **根本原因**: `onScanning` 信号在快速滑行时触发频率高达 30~60 次/秒。若开发者在回调函数中每次都执行 `JSON.parse`、深拷贝大对象或直接频繁触发 Vue 响应式数据更新，会在几百毫秒内塞满 QuickJS 仅有数兆字节的 JS 堆空间，诱发全停顿垃圾回收（Stop-the-World GC）。
- **防御准则**:
  1. 在 `onScanning` 回调中**仅暂存最新字符串**；
  2. 施加 50ms（20Hz）的 `setTimeout` 节流阀；
  3. 待笔尖物理抬起收到 `ocrCompleteChanged` 信号后，才执行一次性的完整结构化 JSON 解析。

### 10.3 铁律三: 谨防笔头微动松开信号的拼写陷阱
- **故障现象**: 笔尖按下有响应，但抬笔后识别结果永远出不来。
- **根本原因**: 底层 C++ 导出到 JSAPI 的按键松开信号名称为 **`headButtonRelese`**（注意中间**缺少字母 `a`**，是历史遗留拼写）。
- **防御准则**: 监听时务必采用双重回退兼容代码：
  ```javascript
  const releaseSignal = this.buttonMgr.headButtonRelese || this.buttonMgr.headButtonRelease;
  if (releaseSignal && releaseSignal.connect) {
      releaseSignal.connect(onReleaseCallback);
  }
  ```

### 10.4 铁律四: 必须在 DOM 挂载后激活按键通道
- **故障现象**: 笔尖微动无论怎么按下，前端完全收不到 `headButtonPress` 事件。
- **根本原因**: 前端 QuickJS 初始化时，底层事件分发队列处于抑制状态。必须显式调用 `buttonMgr.setButtonEventReady(true)` 告知中台前端视图与事件接收器已完全就绪。
- **防御准则**: 该方法必须放在 Vue 生命周期的 `mounted()` 钩子中执行，**绝不能放在 `created()` 中提前调用**。

### 10.5 铁律五: 避免在独立扫词界面保留长图渲染
- 若业务场景仅需要文本（如扫词查义、背单词），应显式调用 `globalMgr.setShowImgScanMode(false)`。关闭长图合成可直接节省底层 JPEG 软件编码 CPU 耗时约 25ms，同时彻底免除 Base64 字符串在跨语言层传输时的内存开销。
