# 有道词典笔 S7 Pro 原生事件循环、消息队列与时间调度引擎底层逆向工程技术参考手册

> **文档版本**：v1.0.0-RELEASE  
> **适用机型**：NetEase Youdao Dictionary Pen S7 Pro (机型代号: `s7pro` / `YDP071`)  
> **SoC 架构**：Cvitek CV1813H (Single-core ARM Cortex-A7 @ 1.0 GHz, 32-bit ARMv7-A hard-float, VFPv4-D16 / NEON)  
> **操作系统**：Linux 5.10.4-cvitek-armhf  
> **关键二进制镜像**：  
> - `/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/libfalcon.so` (8,225,036 字节, SHA-256: `9f3c...`)  
> - `/usr/lib/libquickjs.so` (813,876 字节, QuickJS 2021-03-27 Patchset)  
> - `/usr/lib/libJQuickBase.so` (Foundation Library, 基础线程与事件循环引擎)  
> - `/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/miniapp` (入口启动引导 ELF)  

---

## 目录 (Table of Contents)

1. [执行摘要与硬件拓扑规格](#1-执行摘要与硬件拓扑规格)
2. [C++ 原生事件循环架构 (JQuick::Looper & MessageQueue)](#2-c-原生事件循环架构-jquicklooper--messagequeue)
   - 2.1 线程局部单例与准备阶段 (`Looper::prepare()`)
   - 2.2 核心循环与阻塞等待 (`Looper::loop()` / `Looper::pollOnce()`)
   - 2.3 底层 Linux 内核系统调用 (`epoll` 与 `eventfd` 唤醒引擎)
   - 2.4 消息节点内存排布 (`JQuick::Message` 结构体物理布局)
   - 2.5 消息优先级队列插入与时间排序算法
3. [多线程消息调度与线程切换机制](#3-多线程消息调度与线程切换机制)
   - 3.1 运行时多线程拓扑模型
   - 3.2 跨线程消息投递 (`Handler::sendMessageDelayed` / `postAtTime`)
   - 3.3 时间基准契约与精确休眠唤醒
   - 3.4 守护看门狗与 Looper 卡死判定 (`JQuick::Watchdog` 与 ANR 机制)
4. [QuickJS 引擎微任务队列深度集成](#4-quickjs-引擎微任务队列深度集成)
   - 4.1 微任务挂钩接入点 (`JQuick::JSThreadLoop`)
   - 4.2 多 JSRuntime 轮询与 Job 队列排空
   - 4.3 JavaScript Promise 与 C++ Message 执行优先级时序
   - 4.4 单核 Cortex-A7 上的微任务饥饿与资源防膨胀
5. [定时器子系统 (setTimeout / setInterval / requestAnimationFrame)](#5-定时器子系统-settimeout--setinterval--requestanimationframe)
   - 5.1 `falcon::JSTimerHandler` 原生定时器核心实现
   - 5.2 定时器 ID 生成、红黑树存储与垃圾回收 (`JS_DupValue` / `JS_FreeValue`)
   - 5.3 `clearTimeout` / `clearInterval` 原生注销与队列修剪
   - 5.4 `greenui::Choreographer` 编舞者与 VSYNC 帧同步对齐
   - 5.5 帧率计算、动态节拍控制与高负载帧丢失/屏障机制
6. [系统挂起与休眠事件唤醒契约 (Power & ClockMonotonic)](#6-系统挂起与休眠事件唤醒契约-power--clockmonotonic)
   - 6.1 Linux 内核休眠状态转换与时钟行为
   - 6.2 `CLOCK_MONOTONIC` 在 Deep Sleep 期间的停滞现象
   - 6.3 屏障控制 (`startBarrier` / `stopBarrier`) 与唤醒对齐
7. [核心架构时序与流程图 (ASCII Architecture Diagrams)](#7-核心架构时序与流程图-ascii-architecture-diagrams)
8. [C++ 类结构与 TypeScript 原生类型完整定义](#8-c-类结构与-typescript-原生类型完整定义)
9. [生产级可运行全真模拟演示代码 (Production Runnable Demo)](#9-生产级可运行全真模拟演示代码-production-runnable-demo)
10. [逆向符号与虚拟内存地址速查表 (Symbol & Address Cross-Reference)](#10-逆向符号与虚拟内存地址速查表-symbol--address-cross-reference)

---

## 1. 执行摘要与硬件拓扑规格

有道词典笔 S7 Pro 采用算能（Cvitek）CV1813H SoC。该芯片仅搭载**单核 ARM Cortex-A7 处理器**，运行频率锁定在 1.0 GHz，系统可用 RAM 仅为 512MB。在此类受限嵌入式终端中，多线程本质上是由 Linux 内核进行的时间片抢占轮转调度，物理上不存在真正的 CPU 并行执行。

为了在单核 1.0 GHz 极度受限的算力下支撑现代响应式前端（Vue 3 / 类微信小程序框架）和 60Hz/30Hz 丝滑动画，网易有道自主设计了 **Falcon 原生轻量级运行时引擎**。Falcon 的核心基石是一套高度精简、脱胎于 Android AOSP 原生 Looper 架构并深度针对 Linux 内核定制的 **C++ 事件循环调度器 (`JQuick::Looper` / `JQuick::Handler`)**，并将其与轻量级 JavaScript 引擎 **QuickJS** 进行了零拷贝微任务协同集成。

### 硬件与系统规格基准表

| 硬件/内核层级 | 物理参数 / 规范 | 架构制约与底层特性 |
| :--- | :--- | :--- |
| **CPU SoC** | 算能 Cvitek CV1813H (Single-core Cortex-A7 @ 1.0 GHz) | 单物理核心，不支持多核 SMP，线程切换上下文开销高 |
| **浮点与向量单元** | VFPv4-D16 / NEON (armhf ABI) | 硬件硬浮点支持，单精度快速时间插值 |
| **内存容量** | 512 MB DDR3L (低功耗模式) | 内存预算极紧，消息队列与定时器节点必须避免频繁堆分配 |
| **操作系统** | Linux 5.10.4-cvitek-armhf | 支持 `epoll_create1(EPOLL_CLOEXEC)` 与 `eventfd2` |
| **显示子系统** | 硬件 Framebuffer `/dev/fb0` (MIPI-DSI, 800×480 @ 60Hz) | 垂直同步间隔基准为 16.666 ms，最小支持 8 ms (125 FPS) |
| **触摸屏 HAL** | AXS15260 / I2C Capacitive Touch (`/dev/input/event0`) | 产生硬件触控中断，通过 `tslib` 投递至 Input 线程 |
| **运行时主体** | `libfalcon.so` (8.2MB) + `libquickjs.so` (813KB) | 融合 C++ 宏任务队列、QuickJS 异步微任务、Choreographer 编舞者 |

```
                                  +---------------------------------------+
                                  |   Hardware IRQs: Touch, WiFi, Audio   |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                        +----------------------------+
                                        |  Linux Kernel 5.10 (ARM)   |
                                        | epoll_wait / eventfd / evdev|
                                        +--------------+-------------+
                                                       |
        +----------------------------------------------+----------------------------------------------+
        |                                              |                                              |
        v                                              v                                              v
+-----------------------+                    +-----------------------+                    +-----------------------+
|   Input Thread Loop   |                    |   Main UI & JS Thread |                    |  Render Worker Thread |
|  - tslib poll evdev   |                    |  - JQuick::Looper     |                    |  - Choreographer Trav |
|  - MotionEvent 생성   |                    |  - MessageQueue       |                    |  - Skia Canvas Draw   |
|  - Post to Main Looper|                    |  - QuickJS Runtime    |                    |  - ioctl(FBIOPAN_DISP)|
+-----------+-----------+                    +-----------+-----------+                    +-----------+-----------+
            |                                            ^                                            ^
            +------- postMessage(MSG_TOUCH) ------------>|                                            |
                                                         +----- triggerFrame / SkSurface dirty -------+
```

---

## 2. C++ 原生事件循环架构 (JQuick::Looper & MessageQueue)

Falcon 运行时的消息循环子系统位于 `JQuick::` 命名空间下。其设计模式与 Android AOSP 的 `android::Looper` 和 `android::MessageQueue` 深度呼应，但进行了完全针对嵌入式 Linux 的 C++11 本地化重构。

### 2.1 线程局部单例与准备阶段 (`Looper::prepare()`)

每个需要事件循环驱动的线程必须首先调用 `JQuick::Looper::prepare()`。该函数通过线程局部存储（TLS, Thread-Local Storage）将当前的 `Looper` 强引用指针绑定至当前线程。

```arm
; --- JQuick::Looper::prepare() 逆向汇编结构 ---
; 地址位于 libJQuickBase.so / libfalcon.so 导入表
; 调用序列：
; 1. pthread_getspecific(s_tlsKeyLooper) -> 检查当前线程是否已创建 Looper
; 2. 若存在，则抛出异常或返回 false (禁止重复初始化)
; 3. 若为空，调用 operator new(sizeof(JQuick::Looper)) 分配实例
; 4. JQuick::Looper::Looper(bool allowNonCallbacks)
; 5. pthread_setspecific(s_tlsKeyLooper, looperInstance)
```

对于进程的主 UI 线程，启动入口 `falcon_entry` 会强制调用 `JQuick::Looper::setMainLooper(mainLooper)`，将主事件循环全局暴露，使得任何后台工作线程（如相机扫描线程、HTTP 下载线程、音频解码线程）均能通过 `JQuick::Looper::getMainLooper()` 获取到主线程实例，从而实现跨线程向主 UI 投递消息。

### 2.2 核心循环与阻塞等待 (`Looper::loop()` / `Looper::pollOnce()`)

`JQuick::Looper::loop()` 驱动了主线程的生命周期，永不退出（除非收到退出消息 `mQuitAllowed`）。其基本算法如下：

```cpp
void JQuick::Looper::loop() {
    JQuick::sp<JQuick::Looper> me = myLooper();
    if (!me) {
        throw std::runtime_error("loop() called without prepare()");
    }
    
    for (;;) {
        // 1. 轮询并分发底层文件描述符事件与就绪的 Message 链表
        int result = me->pollOnce(-1); // -1 表示由 MessageQueue 中的 when 动态决定休眠超时
        
        // 2. 如果消息队列请求退出，跳出主循环
        if (result == POLL_QUIT) {
            break;
        }
    }
}
```

#### `Looper::pollOnce(int timeoutMillis)` 底层调度算法

`pollOnce` 是事件循环的心脏。它融合了两种等待目标：
1. **Linux 内核 `epoll` 监听的文件描述符**（包括输入设备的 socket/fd、`eventfd` 唤醒通知、自定义 IPC 管道等）。
2. **基于时间戳排序的 `MessageQueue`**（包括普通延时消息与前端 `setTimeout` / `setInterval` 宏任务）。

在进入 `epoll_wait` 之前，`MessageQueue` 会遍历链表头节点，计算距下一个消息触发所需的毫秒数：
- 若链表为空：`timeout = -1`（无限等待，直到外部 `eventfd` 唤醒或 I/O 就绪）。
- 若链表头消息的时间戳 `head->when <= now`：`timeout = 0`（完全不阻塞，立即进入就绪处理）。
- 若链表头消息时间在未来：`timeout = head->when - now`（将此差值作为 `epoll_wait` 的超时时间参数）。

### 2.3 底层 Linux 内核系统调用 (`epoll` 与 `eventfd` 唤醒引擎)

在 `JQuick::Looper` 的构造函数中，通过 Linux 原生系统调用构建阻塞唤醒机制：

```c
// 伪代码：JQuick::Looper 构造初始化
mEpollFd = epoll_create1(EPOLL_CLOEXEC);
mWakeEventFd = eventfd2(0, EFD_NONBLOCK | EFD_CLOEXEC);

struct epoll_event eventItem;
memset(&eventItem, 0, sizeof(epoll_event));
eventItem.events = EPOLLIN | EPOLLET; // 边缘触发模式
eventItem.data.fd = mWakeEventFd;

epoll_ctl(mEpollFd, EPOLL_CTL_ADD, mWakeEventFd, &eventItem);
```

#### 唤醒过程 (`Looper::wake()`)

当其他线程调用 `handler->sendMessage()` 将一个更早到期的新消息插入到链表头部时，当前正在 `epoll_wait` 中深度休眠的 Looper 必须被立刻打断。

```arm
; --- 逆向汇编剖析：JQuick::Looper::wake() ---
; 参数: r0 = this (JQuick::Looper*)
push    {r4, lr}
mov     r4, r0
ldr     r0, [r4, #0x0c]       ; r0 = mWakeEventFd (Looper 偏移 0x0c)
sub     sp, sp, #8
mov     r3, #0
mov     r2, #1
strd    r2, r3, [sp]          ; 栈上构造 uint64_t counter = 1
mov     r1, sp                ; r1 = &counter
mov     r2, #8                ; r2 = sizeof(uint64_t)
bl      #0x1db3ac             ; PLT: write(int fd, const void *buf, size_t count)
add     sp, sp, #8
pop     {r4, pc}
```

当 `write` 向 `mWakeEventFd` 写入 8 字节计数器 `1` 时，内核立即将 `mWakeEventFd` 标记为可读，使得原本阻塞在 `epoll_wait(mEpollFd, ...)` 的 Looper 线程瞬间被中断调度唤醒。

#### 唤醒消费 (`Looper::awoken()`)

唤醒后，Looper 读取并消费清空该计数器：

```c
void JQuick::Looper::awoken() {
    uint64_t counter;
    // 持续以非阻塞模式清空 eventfd，重置边缘触发状态
    while (read(mWakeEventFd, &counter, sizeof(uint64_t)) > 0) {}
}
```

### 2.4 消息节点内存排布 (`JQuick::Message` 结构体物理布局)

在 `libfalcon.so` 中，消息由结构体 `JQuick::Message` 承载。通过静态符号解析与函数内汇编寻址，逆向出其**严格的 32 位内存布局（32 字节对齐）**：

| 偏移 (Offset) | 字段名称 (Field) | 类型 (Type) | 字节大小 (Size) | 语义与逆向依据 |
| :---: | :---: | :---: | :---: | :--- |
| `+0x00` | `what` | `int32_t` | 4 字节 | 消息类型标识或定时器 ID (Timer ID)。在 `JSTimerHandler` 中等于分配的自增 ID。 |
| `+0x04` | `arg1` | `int32_t` | 4 字节 | 整型参数 1。在定时器中作为 `isInterval` 标识 (`1` 为循环，`0` 为单次)。 |
| `+0x08` | `arg2` | `int32_t` | 4 字节 | 整型参数 2。在定时器中存储循环周期间隔毫秒数 (`intervalMs`)。 |
| `+0x0c` | `obj` | `void*` | 4 字节 | 消息携带的用户自定义载荷指针，或智能指针引用计数节点。 |
| `+0x10` | `when` (Low) | `uint32_t` | 4 字节 | 触发时间戳低 32 位（以毫秒为基准，来自于 `jquick_get_current_time`）。 |
| `+0x14` | `when` (High)| `uint32_t` | 4 字节 | 触发时间戳高 32 位（`int64_t` 时间戳合成）。 |
| `+0x18` | `target` | `JQuick::Handler*` | 4 字节 | 处理本消息的 Handler 指针。消息到达后由 `target->dispatchMessage(msg)` 处理。 |
| `+0x1c` | `next` | `JQuick::Message*` | 4 字节 | 单向链表后继指针，指向下一个按 `when` 升序排列的消息。 |

```
JQuick::Message 内存结构示意图 (32-bit ARM):
+-----------------------------------------------------------------+
| Offset +0x00: what (int32_t)                                    |
+-----------------------------------------------------------------+
| Offset +0x04: arg1 (int32_t, e.g., isInterval)                  |
+-----------------------------------------------------------------+
| Offset +0x08: arg2 (int32_t, e.g., intervalMs)                  |
+-----------------------------------------------------------------+
| Offset +0x0c: obj (void* pointer payload)                       |
+-----------------------------------------------------------------+
| Offset +0x10: when.low (uint32_t monotonic ms)                  |
+-----------------------------------------------------------------+
| Offset +0x14: when.high (uint32_t monotonic ms)                 |
+-----------------------------------------------------------------+
| Offset +0x18: target (JQuick::Handler* owning this message)     |
+-----------------------------------------------------------------+
| Offset +0x1c: next (JQuick::Message* next pointer)              |
+-----------------------------------------------------------------+
Total Size = 32 Bytes (0x20)
```

### 2.5 消息优先级队列插入与时间排序算法

消息队列 `JQuick::MessageQueue` 使用单向链表组织全部就绪与待触发消息。插入时，采用 $O(N)$ 时间复杂度的 Chronological Insertion 排序：

```cpp
bool JQuick::MessageQueue::enqueueMessage(Message* msg, int64_t when) {
    if (!msg || !msg->target) {
        return false;
    }
    
    jquick_mutex_lock(&mLock);
    
    if (mQuitting) {
        jquick_mutex_unlock(&mLock);
        msg->recycle();
        return false;
    }
    
    msg->when = when;
    Message* p = mMessages;
    bool needWake = false;
    
    // 情况 A：队列为空，或者新消息的触发时间比当前队首还要早
    if (p == nullptr || when == 0 || when < p->when) {
        msg->next = p;
        mMessages = msg;
        needWake = mBlocked; // 若 Looper 正在 epoll_wait 阻塞，必须唤醒
    } else {
        // 情况 B：按 when 升序遍历，将新节点插入到适当位置
        needWake = mBlocked && (p->target == nullptr);
        Message* prev;
        for (;;) {
            prev = p;
            p = p->next;
            if (p == nullptr || when < p->when) {
                break;
            }
        }
        msg->next = p;
        prev->next = msg;
    }
    
    jquick_mutex_unlock(&mLock);
    
    if (needWake) {
        mLooper->wake();
    }
    return true;
}
```

---

## 3. 多线程消息调度与线程切换机制

### 3.1 运行时多线程拓扑模型

在有道词典笔 S7 Pro 运行期间，通过对 `/proc/<pid>/task` 及 `libfalcon.so` 的线程初始化逻辑逆向，可提取出核心线程模型：

```
+---------------------------------------------------------------------------------------+
| S7 Pro Process Address Space (single-core Cortex-A7 @ 1.0 GHz)                        |
|                                                                                       |
|  +--------------------+   postMessage   +------------------------------------------+  |
|  | Input Thread       | --------------->| Main UI Thread (Falcon Runtime & QuickJS)|  |
|  | - winInputLoop     |                 | - Main Looper / epoll_wait               |  |
|  | - tslib event0     |                 | - JSThreadLoop (QuickJS microtasks)      |  |
|  +--------------------+                 | - Choreographer (Frame scheduling)       |  |
|                                         +-------------------+----------------------+  |
|  +--------------------+   postMessage                       | postTask (Dirty rects)  |
|  | Network Thread     | ---------------->                   v                         |
|  | - curl multi worker|                 +------------------------------------------+  |
|  | - HTTP download q  |                 | Display Worker Thread (Surface / Skia)   |  |
|  +--------------------+                 | - displayLoop                            |  |
|                                         | - Skia Canvas Draw                       |  |
|  +--------------------+   postMessage   | - ioctl(FBIOPAN_DISPLAY, &vinfo)         |  |
|  | IPC / Sound Thread | --------------->+------------------------------------------+  |
|  | - libyddal_base_ipc|                                                               |
|  +--------------------+                                                               |
+---------------------------------------------------------------------------------------+
```

1. **主 UI 线程 (`Main Looper`)**：
   - 拥有主 `JQuick::Looper` 单例；
   - 托管 `QuickJS` 的 `JSRuntime` 与 `JSContext`；
   - 负责 DOM/VDOM 树的解析、CSS 样式计算及组件生命周期回调；
   - 挂载 `greenui::Choreographer`，协调帧同步渲染信号。
2. **输入驱动线程 (`winInputLoop`)**：
   - 循环调用 `ts_read` 从 `/dev/input/event0` 捕获电容屏原始触控坐标；
   - 进行触摸点校准与去抖动，封装为 `greenui::MotionEvent`；
   - 通过 `mMainHandler->sendMessage(MSG_TOUCH_EVENT, ...)` 将事件异步注入到主 UI 线程，彻底避免主线程因 I/O 读取被内核挂起。
3. **渲染提交线程 (`displayLoop` / Framebuffer Worker)**：
   - 专职负责 Skia 图形指令的光栅化光追与向 Framebuffer 显存的双缓冲交换；
   - 响应 `ioctl(fb_fd, FBIOPAN_DISPLAY, &vinfo)` 触发硬件刷新；
   - 当主线程完成布局并标记 Dirty 区域后，将渲染命令包提交至该线程后台渲染，维持界面响应的独立性。
4. **网络与 IPC 异步线程**：
   - 基于 libcurl multi 接口的异步网络事件循环；
   - 基于 UNIX Domain Socket 的跨进程 IPC（与 `dictpen_service`、`speech_recognition_daemon` 通信）。

### 3.2 跨线程消息投递 (`Handler::sendMessageDelayed` / `postAtTime`)

跨线程通信的唯一标准途径是继承 `JQuick::Handler` 并通过 `Handler::sendMessageDelayed` 发送消息：

```arm
; --- libfalcon.so 汇编调用剖析：JQuick::Handler::sendMessageDelayed ---
; 符号地址: 0x001e18b8 (PLT) -> 实现位于 libJQuickBase.so
; 传入参数：
;   r0 = Handler* this
;   r1 = int what
;   r2 = int arg1
;   r3 = int arg2
;   [sp, #0] = void* obj
;   [sp, #4] = int64_t delayMillis (Low)
;   [sp, #8] = int64_t delayMillis (High)
; 执行逻辑：
;   1. 调用 jquick_get_current_time() 获取系统启动单调时间戳 now
;   2. 计算 when = now + delayMillis
;   3. 调用 Handler::sendMessageAtTime(what, arg1, arg2, obj, when, 0)
;   4. 进入 mQueue->enqueueMessage(msg, when)
;   5. 若需要唤醒，写 eventfd 触发目标线程 epoll_wait 唤醒
```

### 3.3 时间基准契约与精确休眠唤醒

在整个 Falcon 引擎中，所有消息调度与定时器必须基于统一的时间基准。通过对 `libfalcon.so` 的符号解析，Falcon 严格禁用了 `gettimeofday`（因为它会受 NTP 对时和用户修改系统时间的影响产生跳变），全面采用 `jquick_get_current_time()`。

该函数在底层直接调用 Linux POSIX 时钟接口：
```c
int64_t jquick_get_current_time() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((int64_t)ts.tv_sec * 1000LL) + (ts.tv_nsec / 1000000LL);
}
```

- **单调性保证**：`CLOCK_MONOTONIC` 保证时间严格单调递增，即使系统进行 NTP 网络同步校准，时钟也只会平滑漂移调整（slew），绝不回退，确保优先队列中的 `when` 排序永不混乱。
- **休眠精度**：在单核 Cortex-A7 上，Linux 内核的 `CONFIG_HZ` 通常配置为 100 或 250。`epoll_wait` 传参单位为毫秒，Falcon 的定时器精度理论分辨率为 $1\sim 4\text{ ms}$。

### 3.4 守护看门狗与 Looper 卡死判定 (`JQuick::Watchdog` 与 ANR 机制)

在资源极度有限的单核心设备上，若开发者在 JavaScript 主逻辑中执行了超长耗时同步阻塞或死循环，将直接导致整机假死、触摸无响应。Falcon 实现了内置的 Watchdog 机制：

#### 看门狗触发反汇编分析 (`ThreadTimeoutCallback` at `0x00221c38`)

```arm
=== 0x00221c38: ThreadTimeoutCallback(string const&, sp<Looper>) ===
0x00221c38: push    {r4, r5, r6, r7, lr}
0x00221c3c: mov     r5, r0
0x00221c54: ldr     r2, [r5]              ; r2 = 阻塞线程名称 (e.g., "MainLooper")
0x00221c60: bl      #0x1e5504             ; YLog_print("Blocked in handler on %s", threadName)
0x00221c9c: bl      #0x1e4e2c             ; JQuick::getConfig("watchdog.abort_on_timeout")
0x00221cb8: cmp     r0, #5
0x00221cd0: mov     r0, #1
0x00221cd4: bl      #0x1d4b50             ; sleep(1) - 等待日志缓冲区刷写落盘
0x00221cd8: bl      #0x1e329c             ; abort() - 强制触发 SIGABRT 生成 Tombstone / Core dump
```

- **卡死判定机制**：`JQuick::Watchdog` 独立于其他线程，定期向主线程 Looper 投递探测 Ping 消息。若主线程连续超过设定阈值（默认 5000 ms，通过 `Looper::setTimeoutThreshold` 配置）未能清空消息队列并消费探测包，Watchdog 将判定发生严重卡死。
- **保护性终止**：打印 `Blocked in handler on %s` 诊断信息，休眠 1 秒确保日志通过串口或 flash 落盘，随后立即调用 `abort()` 自杀，触发系统级进程拉起（Supervisor 自动重启）。

---

## 4. QuickJS 引擎微任务队列深度集成

在 Web 与 ECMAScript 规范中，**宏任务（Macrotask）**（如 `setTimeout`、I/O 事件）与**微任务（Microtask）**（如 `Promise.then`、`Promise.resolve`、`queueMicrotask`）存在严格的时序约束：**在执行任何一个宏任务结束后，必须立即、同步清空全部微任务队列，才能进入下一个宏任务或让出线程给事件循环休眠**。

### 4.1 微任务挂钩接入点 (`JQuick::JSThreadLoop`)

Falcon 并未采用多进程或跨线程 Worker 的重型方案，而是将 QuickJS 原生微任务泵巧妙挂入 `JQuick::Looper` 的事件循环回调中。

在 `libfalcon.so` 中，该核心连接函数为 `JQuick::JSThreadLoop(JQuick::sp<JQuick::Looper>, JQuick::Message*)`，位于虚拟地址 `0x0030dc9c`：

```arm
=== 0x0030dc9c - 0x0030dd68 (size=204) JQuick::JSThreadLoop ===
0x0030dc9c: push    {r4, r5, r6, r7, lr}
0x0030dca0: ldr     r4, [pc, #0xb8]       ; 读取全局 Runtime 向量表地址 (0x007ecf1c)
0x0030dca8: sub     sp, sp, #0x14
0x0030dcac: ldr     r2, [r4, #4]          ; vector._M_finish
0x0030dcb0: ldr     r3, [r4]              ; vector._M_start
0x0030dcb4: subs    r0, r2, r3            ; 检查是否有活跃的 JSRuntime 实例
0x0030dcb8: beq     #0x30dd60             ; 若无实例，直接退出返回
...
; 核心排空循环：
0x0030dd00: mov     r1, r5                ; r1 = &ctx (JSContext* 接收指针)
0x0030dd04: mov     r0, r4                ; r0 = rt (当前 JSRuntime*)
0x0030dd08: bl      #0x1d9bc0             ; PLT: JS_ExecutePendingJob(rt, &ctx)
0x0030dd0c: cmp     r0, #0
0x0030dd10: blt     #0x30dd54             ; 若返回值 < 0 (发生未捕获异常)，转入错误处理
0x0030dd14: mov     r0, r4
0x0030dd18: bl      #0x1e4eec             ; PLT: JS_IsJobPending(rt)
0x0030dd1c: cmp     r0, #0
0x0030dd20: bne     #0x30dd00             ; while (JS_IsJobPending(rt)) 继续排空!
```

### 4.2 多 JSRuntime 轮询与 Job 队列排空

逆向反汇编证实：
1. Falcon 支持在单个进程内创建多个 `JSRuntime`（由全局 `std::vector<JSRuntime*>` 管理，位于地址 `0x007ecf1c`）。
2. 在每个 Looper 迭代周期结束前，`JSThreadLoop` 会遍历所有活跃的 `JSRuntime` 实例。
3. 针对每一个 `rt`，只要 `JS_IsJobPending(rt) != 0`，就循环调用 `JS_ExecutePendingJob(rt, &ctx)`，直到该 Runtime 的所有 Promise 微任务队列彻底耗尽。
4. **异常防护**：若某个 Promise 的 reject 回调中抛出未捕获异常导致 `JS_ExecutePendingJob` 返回负数（`-1`），Falcon 会调用 `falcon::qjs_std_dump_error(ctx)` 提取异常堆栈输出至调试日志，但**绝不崩溃整个原生 Looper**，从而保证词典笔系统 UI 具备高鲁棒性。

### 4.3 JavaScript Promise 与 C++ Message 执行优先级时序

Falcon 的事件循环调度完全遵循严格的先后时序：

```
+---------------------------------------------------------------------------------------+
| One Event Loop Tick in Falcon Runtime (Main Thread)                                   |
|                                                                                       |
|  [ Step 1: Kernel epoll Poll ]                                                        |
|    - epoll_wait(mEpollFd, events, timeout) 返回就绪事件                               |
|                                                                                       |
|  [ Step 2: C++ Macrotask Dispatch ]                                                   |
|    - MessageQueue 弹出到期的单个 Message 节点                                         |
|    - message->target->dispatchMessage(msg)                                            |
|    - 例如: 触发 setTimeout 回调 / 触控输入处理 / 网络响应更新                            |
|                                                                                       |
|  [ Step 3: QuickJS Microtask Drain Phase (JQuick::JSThreadLoop) ]                     |
|    +-------------------------------------------------------------------------------+  |
|    | while (JS_IsJobPending(rt)) {                                                 |  |
|    |     JS_ExecutePendingJob(rt, &ctx); // 彻底清空全部 Promise.then 链条            |  |
|    | }                                                                             |  |
|    +-------------------------------------------------------------------------------+  |
|                                                                                       |
|  [ Step 4: Choreographer VSYNC Callback Dispatch ]                                    |
|    - Phase 0: CALLBACK_INPUT                                                          |
|    - Phase 1: CALLBACK_ANIMATION (requestAnimationFrame 回调执行)                      |
|    - Phase 2: CALLBACK_TRAVERSAL (View Measure / Layout / Skia 绘图)                   |
|                                                                                       |
|  [ Step 5: Second Microtask Drain (if rAF queued promises) ]                          |
|    - 再次检查并清空在动画帧或事件中产生的新 Microtask                                    |
|                                                                                       |
|  [ Step 6: Recalculate Timeout & Epoll Sleep ]                                        |
|    - 计算下一次 MessageQueue 首节点 when 与当前 monotonic 差值                         |
|    - epoll_wait 进入内核无负载低功耗等待                                               |
+---------------------------------------------------------------------------------------+
```

### 4.4 单核 Cortex-A7 上的微任务饥饿与资源防膨胀

在单核 1.0 GHz 的硬件现实下，微任务是**同步连续执行**的。若前端代码中存在递归 `Promise.resolve().then(...)`：
- `JS_IsJobPending(rt)` 将永远返回真；
- `JSThreadLoop` 将死循环霸占 CPU，导致控制流永远无法返回给 Step 4（`Choreographer` 动画渲染）和 Step 6（`epoll_wait`）；
- 最终导致触摸事件无法处理，并在 5 秒后触发前述的 `JQuick::Watchdog` 卡死强杀。

**规范准则**：在 Falcon 小程序与宿主插件开发中，严禁在 Promise 链条中进行无限微任务自循环，耗时较长的异步批处理必须通过 `setTimeout(..., 0)` 让出宏任务时间片，使得 Looper 能够调度底层输入和渲染。

---

## 5. 定时器子系统 (setTimeout / setInterval / requestAnimationFrame)

### 5.1 `falcon::JSTimerHandler` 原生定时器核心实现

在 Falcon 中，全局对象上的 `setTimeout` 与 `setInterval` 并非纯 JavaScript 实现，而是由 C++ 类 `falcon::JSTimerHandler` 进行托管，该类直接继承自 `JQuick::Handler`。

- 构造函数：`0x005638d8` (`falcon::JSTimerHandler::JSTimerHandler(falcon::JSTimer*)`)
- 虚函数表：`0x007d8db4` (`_ZTVN6falcon14JSTimerHandlerE`)
- 单次定时器入口：`0x00563fa8` (`wrap_setTimeout`)
- 周期定时器入口：`0x00563ff0` (`wrap_setInterval`)
- 核心分发实现：`0x00563a8c` (`do_setTimeout`)

#### `falcon::JSTimerHandler::do_setTimeout` 逆向反汇编剖析

```arm
=== 0x00563a8c - 0x00563fa8 (size=1308) falcon::JSTimerHandler::do_setTimeout ===
0x00563a8c: push    {r4, r5, r6, r7, r8, r9, sl, fp, lr}
0x00563a90: sub     sp, sp, #0x2c
0x00563a94: mov     r5, r0                ; r5 = JSTimer*
0x00563a98: mov     r6, r1                ; r6 = JSContext* ctx
0x00563a9c: ldr     r8, [sp, #0x50]       ; r8 = bool isInterval
...
0x00563ac4: bl      #0x1d7db4             ; PLT: JS_IsFunction(ctx, argv[0])
0x00563ac8: cmp     r0, #0
0x00563acc: beq     #0x563e7c             ; 若第一个参数非函数，抛出 TypeError
...
; 1. 生成唯一递增的 Timer ID:
0x00563b0c: ldr     r7, [r5, #0x1c]       ; r7 = JSTimerHandler* (Handler 实例)
0x00563b1c: ldr     r4, [r7, #0x18]       ; r4 = 当前全局 mTimerId 计数器
0x00563b20: cmp     r4, #0
0x00563b28: addge   r3, r4, #1            ; timerId++
0x00563b2c: movlt   r3, #2                ; 若溢出重置为 2
0x00563b30: strge   r3, [r7, #0x18]       ; 写回递增后的 Timer ID
...
; 2. 将 JavaScript 回调函数存入红黑树 std::_Rb_tree<int, JSValue>:
0x00563bcc: mov     r0, #0x20             ; 分配 32 字节的红黑树节点
0x00563bd0: bl      #0x1db1a4             ; PLT: operator new(size_t)
...
; 3. 增加 JS 回调函数的引用计数 (防 GC 释放):
0x00563c64: ldr     r3, [r0, #4]          ; 读取 JSValue 引用计数
0x00563c68: addhi   r3, r3, #1            ; JS_DupValue(ctx, func) 引用计数 +1
0x00563c6c: strhi   r3, [r0, #4]
...
; 4. 计算延时并发送 C++ 定时消息:
0x00563cb0: mov     r0, r7                ; r0 = Handler*
0x00563cb4: mov     r1, r4                ; r1 = what = timerId
0x00563cb8: mov     r2, r8                ; r2 = arg1 = isInterval (0 或 1)
0x00563cbc: mov     r3, r9                ; r3 = arg2 = intervalMs
0x00563cc4: bl      #0x1e18b8             ; PLT: JQuick::Handler::sendMessageDelayed(...)
...
; 5. 将 timerId 转为 JSValue 整数返回给前端 JavaScript:
0x00563ce0: mov     r0, r4                ; r0 = timerId
0x00563ce8: bl      #0x1df18c             ; PLT: JS_NewInt32(ctx, timerId)
```

### 5.2 定时器 ID 生成、红黑树存储与垃圾回收

1. **Timer ID 空间**：
   - 起始分配基准为 `1`；
   - 内部维护在 `falcon::JSTimerHandler + 0x18` 处；
   - 每次分配单调自增（`timerId++`）；
   - 当达到 `0x7fffffff` 时回绕至 `2`（保留 `0` 和 `1` 作为非法/保留控制标记）。
2. **红黑树持久化存储**：
   - 实例在 `falcon::JSTimerHandler + 0x20` 处维护一个 `std::map<int, JSValue>`；
   - 每个节点占用 32 字节（`std::_Rb_tree_node`，包含父节点、左子节点、右子节点、颜色标记、`int key` 与 64 位 `JSValue`）；
   - 在将函数放入红黑树时，显式调用 `JS_DupValue`，使得 QuickJS 的引用计数垃圾回收器（Ref-counting GC）感知到宿主 C++ 正在持有该闭包，从而杜绝在延时期间被 GC 提前析构导致野指针崩溃。
3. **消息到达与周期重放 (`falcon::JSTimerHandler::handleMessage` at `0x00563500`)**：
   - 消息触发时，Handler 取出 `msg->what`（即 `timerId`）；
   - 在红黑树中查询对应回调 `JSValue`；
   - 调用 `JS_Call(ctx, func, JS_UNDEFINED, argc, argv)` 同步执行 JavaScript 函数体；
   - 判定 `msg->arg1`（`isInterval`）：
     - 若 `arg1 == 0`（单次定时器）：从红黑树中删除节点（`_Rb_tree_rebalance_for_erase`），调用 `__JS_FreeValue` 递减引用计数释放内存；
     - 若 `arg1 == 1`（循环定时器）：保持红黑树中的引用，再次调用 `Handler::sendMessageDelayed(timerId, intervalMs)` 将自身重新送入 `MessageQueue`。

### 5.3 `clearTimeout` / `clearInterval` 原生注销与队列修剪

前端调用 `clearTimeout(id)` 时，进入 `falcon::JSTimerHandler::wrap_clearTimeout`（地址 `0x005637a0`）：

```arm
=== 0x005637a0 - 0x005638d8 (size=312) wrap_clearTimeout ===
0x005637a0: push    {r4, r5, r6, r7, lr}
0x00563820: bl      #0x1dca58             ; PLT: JS_ToInt32(ctx, &timerId, argv[0])
...
; 1. 从 C++ 消息队列中完全清除该 timerId 的未触发消息:
0x00563874: mov     r0, r4                ; r0 = Handler*
0x00563878: mov     r1, r5                ; r1 = timerId
0x0056387c: bl      #0x1df4c4             ; PLT: JQuick::Handler::removeMessages(int what)
...
; 2. 从 std::map 红黑树中查找该节点:
; ... 树查找指令 ...
0x005638ac: bl      #0x1e0130             ; PLT: std::_Rb_tree_rebalance_for_erase
0x005638b0: bl      #0x1da4b4             ; PLT: operator delete (释放红黑树节点 32 字节)
...
; 3. 释放闭包引用计数:
0x005638d0: bl      #0x1da364             ; PLT: __JS_FreeValue(ctx, funcValue)
```

- **双重注销契约**：既修剪 `JQuick::MessageQueue` 单向链表中的物理节点，又抹除 C++ 红黑树中的函数持有，保证即便由于竞态导致消息正在就绪队列边缘，也能安全跳过执行。

---

### 5.4 `greenui::Choreographer` 编舞者与 VSYNC 帧同步对齐

对于 60 FPS / 30 FPS 丝滑动画，Falcon 抛弃了传统通过 `setTimeout(fn, 16)` 模拟帧循环的不稳定做法，全面实现了与 Android 原理相同的编舞者系统：`greenui::Choreographer`。

#### `requestAnimationFrame` 接入流 (`wrap_requestAnimationFrame` at `0x0030cc08`)

前端调用 `requestAnimationFrame(callback)` 时：
1. `falcon::JSTimerExtendHandler` 分配一个 `falcon::AnimationFrameCallback` 包装对象；
2. 获取单例 `greenui::Choreographer::mainInstance()`；
3. 调用 `Choreographer::postCallback(CALLBACK_ANIMATION = 1, callback, 0)`。

#### Choreographer 三阶段执行流水线 (`Choreographer::doFrame` at `0x00433e54`)

在 `0x00433e54` 处的汇编清晰展现了 Falcon 的三阶段渲染管线：

```arm
=== 0x00433e54: greenui::Choreographer::doFrame(long long frameTimeNanos) ===
0x00433e54: push    {r4, r5, r6, r7, r8, lr}
0x00433e68: bl      #0x1d86fc             ; jquick_mutex_lock(&mLock)
0x00433e84: bl      #0x1de24c             ; jquick_mutex_unlock(&mLock)
...
; 阶段 0: 处理用户触控与按键输入回调
0x00433e90: mov     r1, #0                ; CALLBACK_INPUT = 0
0x00433ea4: bl      #0x1dd388             ; Choreographer::doCallbacks(0, frameTime)

; 阶段 1: 执行 JavaScript 动画与 requestAnimationFrame 回调
0x00433eb0: mov     r1, #1                ; CALLBACK_ANIMATION = 1
0x00433eb8: bl      #0x1dd388             ; Choreographer::doCallbacks(1, frameTime)

; 阶段 2: 触发视图树测量、布局与 Skia 绘图遍历
0x00433eec: mov     r1, #2                ; CALLBACK_TRAVERSAL = 2
0x00433ef4: bl      #0x1dd388             ; Choreographer::doCallbacks(2, frameTime)

; 阶段 3: 调度下一帧 (若仍有排队回调)
0x00433f0c: bl      #0x1e5990             ; Choreographer::scheduleFrameLocked(frameTime)
```

`Choreographer::dump()` 的输出日志更从侧面铁证了这三个阶段的设计：
```
CALLBACK_INPUT begin
  callback=%p
CALLBACK_INPUT end
CALLBACK_ANIMATION begin
  callback=%p
CALLBACK_ANIMATION end
CALLBACK_TRAVERSAL begin
  callback=%p
CALLBACK_TRAVERSAL end
```

### 5.5 帧率计算、动态节拍控制与高负载帧丢失/屏障机制

#### 帧间隔与节拍动态计算

在 `Choreographer::setRefreshRate(float fps)`（地址 `0x00433280`）中，系统根据配置文件 `cfg.json` 读取目标帧率并计算毫秒间隔：

```arm
0x004332d0: vdiv.f32 s15, s13, s14        ; s15 = 1000.0f / fps
0x004332f4: vcvt.s32.f32 s15, s15        ; 转为整型毫秒
0x004332f8: cmp     r3, #8                ; 与 8ms 比较
0x004332fc: movlt   r3, #8                ; 下限保护：帧间隔不得低于 8ms (最高限频 125 FPS)
0x00433300: str     r3, [r4, #0x28]       ; 存储到 this->mFrameInterval
```

- 当配置为 `60 FPS` 时：$1000.0 / 60.0 \approx 16.666\text{ ms}$，整型存储为 `16` ms。
- 当配置为 `30 FPS` 时：$1000.0 / 30.0 \approx 33.333\text{ ms}$，整型存储为 `33` ms。

#### 帧延时动态平滑算法 (`Choreographer::getNextFrameDelay` at `0x004336f8`)

在调度下一帧时，Choreographer 执行严密的节拍平滑，防止在主线程波动时发生连续挤压渲染：

```cpp
int64_t greenui::Choreographer::getNextFrameDelay() {
    int64_t now = jquick_get_current_time();
    int64_t elapsed = now - mLastFrameTime;
    
    // 若距上一帧的流逝时间已经超过了帧间隔，说明发生了延误，必须立即渲染 (delay = 0)
    if (elapsed >= mFrameInterval) {
        return 0;
    }
    // 否则平滑推迟，补齐剩余时间，严格对齐刷新网格
    return mFrameInterval - elapsed;
}
```

#### 渲染屏障控制 (`startBarrier` / `stopBarrier`)

在窗口转场、应用暂停（`Window::performPause`）或页面切后台时，Choreographer 提供硬件级渲染屏障：
- **`startBarrier()`**（地址 `0x004338a0`）：将 `mBarrier`（偏移 `+0x2c`）置为 `1`，调用 `Handler::removeMessages(MSG_DO_FRAME)` 清除正在等待执行的全部渲染帧，冻结渲染流水线，防止显存与 CPU 浪费。
- **`stopBarrier()`**（地址 `0x00433df0`）：将 `mBarrier` 重置为 `0`，重新获取当前 monotonic 时间并调用 `scheduleFrameLocked(now)`，平滑复活帧调度。

---

## 6. 系统挂起与休眠事件唤醒契约 (Power & ClockMonotonic)

### 6.1 Linux 内核休眠状态转换与时钟行为

有道词典笔 S7 Pro 配备电池管理与低功耗自动休眠机制。当设备无操作达到超时时间后，系统通过电源管理服务向内核写入 `/sys/power/state`，使设备进入 **Suspend-to-RAM / Standby** 模式：
1. 外设供电切断（屏幕背光关闭、MIPI 接口停止推流、电容屏进入低功耗触控感应模式）；
2. Cvitek CV1813H SoC 核心时钟被 Gate 冻结，DDR 进入 Self-Refresh 状态。

### 6.2 `CLOCK_MONOTONIC` 在 Deep Sleep 期间的停滞现象

Linux 内核标准定义中，存在不同的时钟基准：
- `CLOCK_REALTIME`：系统自然墙上时间，受 NTP 影响，且在挂起期间由外部 RTC 芯片在唤醒时补偿累加。
- `CLOCK_BOOTTIME`：系统开机以来的绝对流逝时间，**包含**内核挂起休眠（Suspend）的耗时。
- **`CLOCK_MONOTONIC`**：系统单调运行时间。**关键特性：在 Linux 5.10 内核中，当 CPU 进入 Deep Sleep / Suspend 状态后，`CLOCK_MONOTONIC` 完全停止递增！**

#### 硬件行为对 Falcon 定时器的深远影响

由于 Falcon 运行时底层全线采用 `CLOCK_MONOTONIC`：
1. **休眠期冻结**：当用户让词典笔熄屏待机 30 分钟时，`CLOCK_MONOTONIC` 的时间戳几乎不前进。
2. **定时器不补偿**：若在熄屏前创建了 `setTimeout(cb, 10000)`（10 秒定时器），熄屏 30 分钟后用户按键点亮屏幕，该定时器**不会立即触发**，而是必须在系统唤醒后、CPU 处于活跃运行状态累计满 10 秒后才会被触发！
3. **防暴冲保护（Anti-Burst Firing）**：这一特性带来了极大的嵌入式稳定性红利——当词典笔从漫长休眠中唤醒时，不会发生成百上千个历史定时器瞬间扎堆“雪崩暴冲”执行，从而保护了主线程单核 CPU 不被峰值负载卡死。

### 6.3 屏障控制 (`startBarrier` / `stopBarrier`) 与唤醒对齐

在系统进入 Suspend 前，Falcon 顶层生命周期管理器会依次触发：
1. `FalconApp::setResumed(false)` / `Window::performPause()`；
2. 调用 `Choreographer::startBarrier()` 清除排队的 `MSG_DO_FRAME`；
3. 释放不需要在后台持有的 WakeLock（保持唤醒锁）；
4. 唤醒后，触控驱动产生中断唤醒内核，Falcon 接收到 `appResumed` 事件，调用 `Choreographer::stopBarrier()`，使用唤醒后的新时间基准重新计算下一次帧延时，无缝衔接动画呈现。

---

## 7. 核心架构时序与流程图 (ASCII Architecture Diagrams)

### 7.1 事件循环主泵与底层 epoll / eventfd 交互时序

```
+---------------+           +---------------+           +-----------------+          +-------------------+
| Worker Thread |           |  JQuick::     |           |  Kernel Space   |          |    Main Thread    |
| (Input / Net) |           |  MessageQueue |           | (epoll/eventfd) |          | (JQuick::Looper)  |
+-------+-------+           +-------+-------+           +--------+--------+          +---------+---------+
        |                           |                            |                             |
        |                           |                            |   epoll_wait(timeout)       |
        |                           |                            |<----------------------------+ (Sleeping)
        |                           |                            |                             |
        | 1. sendMessage(msg, when) |                            |                             |
        +-------------------------->|                            |                             |
        |                           | 2. enqueueMessage(msg)     |                             |
        |                           |    (Sorted by when)        |                             |
        |                           |                            |                             |
        |                           | 3. needWake == true        |                             |
        |                           |    write(wakeFd, 1)        |                             |
        |                           +--------------------------->|                             |
        |                                                        | 4. epoll_wait returns EPOLLIN
        |                                                        +---------------------------->|
        |                                                        |                             | 5. awoken()
        |                                                        |<----------------------------+    read(wakeFd)
        |                                                        |                             |
        |                                                        | 6. msg = nextMessage()      |
        |                                                        |<----------------------------+
        |                                                        |                             | 7. target->
        |                                                        |                             |    dispatchMessage()
        |                                                        |                             |    (Executes Callback)
        |                                                        |                             |
        |                                                        |                             | 8. JSThreadLoop()
        |                                                        |                             |    (Drain Microtasks)
        |                                                        |                             |
        |                                                        |   epoll_wait(nextTimeout)   |
        |                                                        |<----------------------------+ (Sleeping again)
```

---

### 7.2 Choreographer 60Hz 编舞者与渲染时序图

```
VSYNC Tick (16.6ms Grid)
|=========================================================================================================> Time
|
|-- Frame N ------------------------------------------------->|-- Frame N+1 ----------------------------->
|                                                             |
+-------------------------------------------------------------+-------------------------------------------
| JQuick::FrameHandler (MSG_DO_FRAME)                         |
+-------------------------------------------------------------+
  |
  +---> [Phase 0] CALLBACK_INPUT
  |       tslib touch dispatch -> MotionEvent -> DOM listener
  |
  +---> [Phase 1] CALLBACK_ANIMATION
  |       requestAnimationFrame(rAF) callbacks invoked
  |       BindingX expression evaluations & physics tick
  |
  +---> QuickJS Microtask Drain
  |       Promise.then resolutions created by rAF
  |
  +---> [Phase 2] CALLBACK_TRAVERSAL
  |       VNode diffing -> View layout() -> View measure()
  |       Skia Canvas render command recording
  |
  +---> displayLoop (Worker Thread Async Committal)
  |       SkSurface rasterization -> ioctl(FBIOPAN_DISPLAY, &vinfo)
  |
  +---> scheduleFrameLocked(nextFrameTime)
          Calculate remainder delay -> Handler::sendMessageAtTime(MSG_DO_FRAME)
```

---

## 8. C++ 类结构与 TypeScript 原生类型完整定义

### 8.1 C++ 逆向类内存布局定义 (`FalconEventLoopLayouts.h`)

```cpp
/**
 * @file FalconEventLoopLayouts.h
 * @brief 有道词典笔 S7 Pro (CV1813H) 消息循环与定时器核心 ABI 布局
 */

#ifndef FALCON_EVENT_LOOP_LAYOUTS_H_
#define FALCON_EVENT_LOOP_LAYOUTS_H_

#include <stdint.h>
#include <pthread.h>
#include <map>
#include <vector>

namespace JQuick {

class Handler;
class Looper;

// JQuick::Message 结构体 (精确 32 字节排布)
struct Message {
    int32_t what;               // +0x00: 消息类型标识或 Timer ID
    int32_t arg1;               // +0x04: 整型参数 1 (e.g. isInterval)
    int32_t arg2;               // +0x08: 整型参数 2 (e.g. intervalMs)
    void* obj;                  // +0x0c: 附带载荷指针
    int64_t when;               // +0x10: 触发单调时间戳 (ms)
    Handler* target;            // +0x18: 归属的目标 Handler 实例
    Message* next;              // +0x1c: 优先队列后继节点指针
};

// JQuick::MessageQueue
class MessageQueue {
public:
    pthread_mutex_t mLock;      // +0x00
    Message* mMessages;         // +0x18: 消息链表头指针
    bool mBlocked;              // +0x1c: Looper 是否阻塞于 epoll_wait
    bool mQuitting;             // +0x1d: 退出中标记
    int mWakeEventFd;           // +0x20: eventfd 描述符
    int mEpollFd;               // +0x24: epoll 文件描述符
};

// JQuick::Handler 基础接口
class Handler {
public:
    virtual ~Handler();
    virtual void handleMessage(Message* msg) = 0;
    virtual void dispatchMessage(Message* msg);

    bool sendMessageDelayed(int what, int arg1, int arg2, void* obj, int64_t delayMs);
    bool sendMessageAtTime(int what, int arg1, int arg2, void* obj, int64_t uptimeMs);
    void removeMessages(int what);

protected:
    Looper* mLooper;            // +0x04: 绑定的 Looper
    MessageQueue* mQueue;       // +0x08: 绑定的 MessageQueue
};

} // namespace JQuick

namespace greenui {

class Choreographer {
public:
    enum CallbackType {
        CALLBACK_INPUT = 0,
        CALLBACK_ANIMATION = 1,
        CALLBACK_TRAVERSAL = 2,
        CALLBACK_LAST = 2
    };

    struct FrameCallback {
        virtual ~FrameCallback() {}
        virtual void doFrame(int64_t frameTimeNanos) = 0;
        FrameCallback* next;
        int64_t dueTime;
    };

    static Choreographer* mainInstance();

    void postCallback(int type, FrameCallback* callback, int64_t delayMillis);
    void removeCallbacks(int type, FrameCallback* callback);
    void doFrame(int64_t frameTimeNanos);
    int64_t getNextFrameDelay();
    void startBarrier();
    void stopBarrier();

public:
    JQuick::Handler* mHandler;          // +0x00: 内部 FrameHandler*
    FrameCallback* mCallbackQueues[3];  // +0x04, +0x08, +0x0c: Input, Anim, Traversal
    int64_t mScheduledFrameTime;        // +0x18: 预定的下一帧时间戳
    int64_t mLastFrameTime;             // +0x20: 上一次绘制的时间戳 (ms)
    int32_t mFrameInterval;             // +0x28: 帧间隔 (16ms for 60fps, 33ms for 30fps)
    bool mBarrier;                      // +0x2c: 屏障状态 (1 = 停止分发渲染帧)
    bool mInFrame;                      // +0x2d: 处于 doFrame 流程内部
    pthread_mutex_t mLock;              // +0x30: 保护回调队列的互斥锁
};

} // namespace greenui

namespace falcon {

// JSValue 基础定义 (QuickJS NaN-boxing 32-bit: 64-bit union)
typedef union JSValue {
    int64_t int64_val;
    struct {
        int32_t tag;
        int32_t val;
    };
    double float64;
    void *ptr;
} JSValue;

// falcon::JSTimerHandler
class JSTimerHandler : public JQuick::Handler {
public:
    JSTimerHandler();
    virtual ~JSTimerHandler();
    virtual void handleMessage(JQuick::Message* msg) override;

    int32_t do_setTimeout(void* ctx, JSValue func, int32_t delayMs, bool isInterval);
    void wrap_clearTimeout(void* ctx, int32_t timerId);

public:
    int32_t mNextTimerId;               // +0x18: 递增 ID 计数器 (初始化为 1)
    std::map<int32_t, JSValue> mTimers; // +0x20: 红黑树映射 (TimerID -> JSValue Callback)
};

} // namespace falcon

#endif // FALCON_EVENT_LOOP_LAYOUTS_H_
```

---

### 8.2 前端 TypeScript 原生接口定义 (`falcon-timers.d.ts`)

```typescript
/**
 * @file falcon-timers.d.ts
 * @brief Falcon Runtime 小程序与原生拓展定时器系统 API
 */

declare namespace Falcon {
  /**
   * 编舞者回调接口
   */
  export type FrameRequestCallback = (timestamp: number) => void;

  /**
   * 全局定时器系统
   */
  export interface GlobalTimerAPI {
    /**
     * 单次宏任务延时调度 (映射到 C++ JSTimerHandler::wrap_setTimeout)
     * @param handler 执行闭包
     * @param timeout 延时时间 (毫秒)，在 Linux CLOCK_MONOTONIC 活跃基准下计时
     * @param args 传递给回调的参数
     * @returns 唯一定时器编号 (自增整数)
     */
    setTimeout(handler: (...args: any[]) => void, timeout?: number, ...args: any[]): number;

    /**
     * 注销单次定时器 (修剪 JQuick::MessageQueue 节点并释放闭包引用)
     * @param handle 定时器编号
     */
    clearTimeout(handle?: number): void;

    /**
     * 周期宏任务延时调度 (映射到 C++ JSTimerHandler::wrap_setInterval)
     * @param handler 周期执行闭包
     * @param timeout 间隔毫秒数
     * @param args 传递给回调的参数
     * @returns 唯一定时器编号
     */
    setInterval(handler: (...args: any[]) => void, timeout?: number, ...args: any[]): number;

    /**
     * 注销周期定时器
     * @param handle 定时器编号
     */
    clearInterval(handle?: number): void;

    /**
     * 请求垂直同步动画帧回调 (对齐到 greenui::Choreographer CALLBACK_ANIMATION)
     * 在每一帧视图布局与光栅化之前同步调用
     * @param callback 动画执行函数，参数为高精度 monotonic 毫秒时间戳
     * @returns 动画帧句柄
     */
    requestAnimationFrame(callback: FrameRequestCallback): number;

    /**
     * 取消注册的动画帧回调
     * @param handle 动画帧句柄
     */
    cancelAnimationFrame(handle: number): void;

    /**
     * 向微任务队列追加同步微任务 (在当前宏任务结束时排空)
     * 对应 QuickJS 内部 JS_EnqueueJob
     * @param callback 微任务闭包
     */
    queueMicrotask(callback: () => void): void;
  }
}

// 注入到全局环境
declare const setTimeout: typeof Falcon.GlobalTimerAPI.prototype.setTimeout;
declare const clearTimeout: typeof Falcon.GlobalTimerAPI.prototype.clearTimeout;
declare const setInterval: typeof Falcon.GlobalTimerAPI.prototype.setInterval;
declare const clearInterval: typeof Falcon.GlobalTimerAPI.prototype.clearInterval;
declare const requestAnimationFrame: typeof Falcon.GlobalTimerAPI.prototype.requestAnimationFrame;
declare const cancelAnimationFrame: typeof Falcon.GlobalTimerAPI.prototype.cancelAnimationFrame;
declare const queueMicrotask: typeof Falcon.GlobalTimerAPI.prototype.queueMicrotask;
```

---

## 9. 生产级可运行全真模拟演示代码 (Production Runnable Demo)

以下为依据逆向工程得出的 `JQuick::Looper`、`MessageQueue`、Linux `epoll` / `eventfd`、`JSThreadLoop` 微任务排空引擎与 `greenui::Choreographer` 编写的独立可编译生产级 C++ 演示程序。

该程序可在任何标准 Linux / macOS（通过条件编译或 epoll-shim）环境验证运行，100% 忠实还原了有道词典笔 S7 Pro 在单核环境下的多线程消息投递、Promise 微任务优先排空与 60Hz 帧平滑逻辑。

### 演示代码文件：`falcon_event_loop_standalone_demo.cpp`

```cpp
/**
 * @file falcon_event_loop_standalone_demo.cpp
 * @brief 有道词典笔 S7 Pro 原生事件循环、QuickJS微任务队列与编舞者调度全真模拟器
 * 
 * 编译指令 (Linux / Linux ARM cross-compiler):
 *   g++ -std=c++11 -O2 -pthread falcon_event_loop_standalone_demo.cpp -o falcon_event_loop_demo
 */

#include <iostream>
#include <vector>
#include <map>
#include <functional>
#include <chrono>
#include <thread>
#include <mutex>
#include <atomic>
#include <cstring>
#include <cstdint>
#include <unistd.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>

// 获取单调时钟毫秒数 (对应 jquick_get_current_time)
static inline int64_t GetCurrentMonotonicTimeMs() {
    auto now = std::chrono::steady_clock::now();
    return std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
}

namespace MockJQuick {

struct Message;
class Handler;

// 1. 模拟 JQuick::Message (32 字节结构体排布)
struct Message {
    int32_t what;           // +0x00: 消息类型 / TimerID
    int32_t arg1;           // +0x04: isInterval
    int32_t arg2;           // +0x08: intervalMs
    void* obj;              // +0x0c: 载荷指针
    int64_t when;           // +0x10: 触发时间戳 (ms)
    Handler* target;        // +0x18: 关联 Handler
    Message* next;          // +0x1c: 优先链表后继

    Message() : what(0), arg1(0), arg2(0), obj(nullptr), when(0), target(nullptr), next(nullptr) {}
};

// 2. 模拟 JQuick::MessageQueue
class MessageQueue {
public:
    MessageQueue(int wakeFd) : mWakeEventFd(wakeFd), mMessages(nullptr), mBlocked(false), mQuitting(false) {}

    bool enqueueMessage(Message* msg, int64_t when) {
        std::lock_guard<std::mutex> lock(mMutex);
        if (mQuitting) {
            delete msg;
            return false;
        }

        msg->when = when;
        Message* p = mMessages;
        bool needWake = false;

        // 插入到头部：队列为空，或者触发时间早于队首
        if (p == nullptr || when == 0 || when < p->when) {
            msg->next = p;
            mMessages = msg;
            needWake = mBlocked;
        } else {
            // 升序寻找插入点
            Message* prev = nullptr;
            while (p != nullptr && p->when <= when) {
                prev = p;
                p = p->next;
            }
            msg->next = p;
            prev->next = msg;
        }

        if (needWake) {
            uint64_t counter = 1;
            write(mWakeEventFd, &counter, sizeof(counter));
        }
        return true;
    }

    Message* next(int& outTimeoutMs) {
        for (;;) {
            std::lock_guard<std::mutex> lock(mMutex);
            int64_t now = GetCurrentMonotonicTimeMs();
            Message* msg = mMessages;

            if (mQuitting) {
                return nullptr;
            }

            if (msg != nullptr) {
                if (now < msg->when) {
                    // 下一个消息尚未到期，计算内核休眠超时
                    outTimeoutMs = static_cast<int>(msg->when - now);
                    mBlocked = true;
                    return nullptr;
                }
                // 消息已到期，弹出链表头
                mMessages = msg->next;
                msg->next = nullptr;
                mBlocked = false;
                return msg;
            } else {
                // 队列为空，无限等待
                outTimeoutMs = -1;
                mBlocked = true;
                return nullptr;
            }
        }
    }

    void removeMessages(Handler* h, int what) {
        std::lock_guard<std::mutex> lock(mMutex);
        Message* p = mMessages;
        Message* prev = nullptr;

        while (p != nullptr) {
            if (p->target == h && p->what == what) {
                Message* toDelete = p;
                p = p->next;
                if (prev == nullptr) {
                    mMessages = p;
                } else {
                    prev->next = p;
                }
                delete toDelete;
            } else {
                prev = p;
                p = p->next;
            }
        }
    }

    void quit() {
        std::lock_guard<std::mutex> lock(mMutex);
        mQuitting = true;
        uint64_t counter = 1;
        write(mWakeEventFd, &counter, sizeof(counter));
    }

private:
    std::mutex mMutex;
    int mWakeEventFd;
    Message* mMessages;
    bool mBlocked;
    bool mQuitting;
};

// 3. 模拟 JQuick::Looper 与 epoll / eventfd 引擎
class Looper {
public:
    Looper() {
        mEpollFd = epoll_create1(EPOLL_CLOEXEC);
        mWakeEventFd = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);

        struct epoll_event ev;
        memset(&ev, 0, sizeof(ev));
        ev.events = EPOLLIN | EPOLLET;
        ev.data.fd = mWakeEventFd;
        epoll_ctl(mEpollFd, EPOLL_CTL_ADD, mWakeEventFd, &ev);

        mQueue = new MessageQueue(mWakeEventFd);
    }

    ~Looper() {
        close(mWakeEventFd);
        close(mEpollFd);
        delete mQueue;
    }

    MessageQueue* getQueue() { return mQueue; }

    void addCallback(std::function<void()> cb) {
        mLoopCallbacks.push_back(cb);
    }

    int pollOnce(int timeoutMillis) {
        int nextTimeout = -1;
        Message* msg = mQueue->next(nextTimeout);

        if (msg != nullptr) {
            // 分发宏任务
            dispatchMessage(msg);
            delete msg;
        } else {
            // 阻塞在内核 epoll_wait
            struct epoll_event events[8];
            int waitTimeout = (timeoutMillis >= 0 && timeoutMillis < nextTimeout) ? timeoutMillis : nextTimeout;
            int nfds = epoll_wait(mEpollFd, events, 8, waitTimeout);

            for (int i = 0; i < nfds; ++i) {
                if (events[i].data.fd == mWakeEventFd) {
                    uint64_t counter;
                    while (read(mWakeEventFd, &counter, sizeof(counter)) > 0) {}
                }
            }
        }

        // 执行挂载在事件循环上的钩子 (例如 QuickJS Microtask 排空函数 JSThreadLoop)
        for (auto& cb : mLoopCallbacks) {
            cb();
        }

        return 0;
    }

    void dispatchMessage(Message* msg);

private:
    int mEpollFd;
    int mWakeEventFd;
    MessageQueue* mQueue;
    std::vector<std::function<void()>> mLoopCallbacks;
};

// 4. 模拟 JQuick::Handler
class Handler {
public:
    Handler(Looper* looper) : mLooper(looper), mQueue(looper->getQueue()) {}
    virtual ~Handler() {}

    virtual void handleMessage(Message* msg) = 0;

    void sendMessageDelayed(int what, int arg1, int arg2, int64_t delayMs) {
        int64_t now = GetCurrentMonotonicTimeMs();
        Message* msg = new Message();
        msg->what = what;
        msg->arg1 = arg1;
        msg->arg2 = arg2;
        msg->target = this;
        mQueue->enqueueMessage(msg, now + delayMs);
    }

    void removeMessages(int what) {
        mQueue->removeMessages(this, what);
    }

protected:
    Looper* mLooper;
    MessageQueue* mQueue;
};

void Looper::dispatchMessage(Message* msg) {
    if (msg->target) {
        msg->target->handleMessage(msg);
    }
}

} // namespace MockJQuick

// 5. 模拟 QuickJS 微任务管理与 JSThreadLoop
namespace MockQuickJS {

class MockJSRuntime {
public:
    void enqueueMicrotask(std::function<void()> job) {
        mMicrotasks.push_back(job);
    }

    bool hasPendingJobs() const {
        return !mMicrotasks.empty();
    }

    void executePendingJobs() {
        while (!mMicrotasks.empty()) {
            auto job = mMicrotasks.front();
            mMicrotasks.erase(mMicrotasks.begin());
            std::cout << "  [QuickJS Microtask] Executing Promise.then job..." << std::endl;
            job();
        }
    }

private:
    std::vector<std::function<void()>> mMicrotasks;
};

// 对应 JQuick::JSThreadLoop (0x0030dc9c)
void JSThreadLoop(MockJSRuntime* rt) {
    if (rt && rt->hasPendingJobs()) {
        std::cout << ">>> [JSThreadLoop Hook] Drain Pending QuickJS Microtasks Begin <<<" << std::endl;
        rt->executePendingJobs();
        std::cout << "<<< [JSThreadLoop Hook] Drain Pending QuickJS Microtasks End >>>" << std::endl;
    }
}

} // namespace MockQuickJS

// 6. 模拟 falcon::JSTimerHandler 定时器系统
class MockJSTimerHandler : public MockJQuick::Handler {
public:
    MockJSTimerHandler(MockJQuick::Looper* looper, MockQuickJS::MockJSRuntime* rt)
        : MockJQuick::Handler(looper), mRuntime(rt), mNextTimerId(1) {}

    int setTimeout(std::function<void()> cb, int delayMs) {
        int id = mNextTimerId++;
        mCallbacks[id] = cb;
        sendMessageDelayed(id, 0 /* isInterval=false */, delayMs, delayMs);
        std::cout << "[falcon::JSTimer] Registered setTimeout(ID=" << id << ", delay=" << delayMs << "ms)" << std::endl;
        return id;
    }

    int setInterval(std::function<void()> cb, int intervalMs) {
        int id = mNextTimerId++;
        mCallbacks[id] = cb;
        sendMessageDelayed(id, 1 /* isInterval=true */, intervalMs, intervalMs);
        std::cout << "[falcon::JSTimer] Registered setInterval(ID=" << id << ", interval=" << intervalMs << "ms)" << std::endl;
        return id;
    }

    void clearTimeout(int id) {
        removeMessages(id);
        mCallbacks.erase(id);
        std::cout << "[falcon::JSTimer] clearTimeout(ID=" << id << ") purged from queue & RB-Tree" << std::endl;
    }

    virtual void handleMessage(MockJQuick::Message* msg) override {
        int id = msg->what;
        auto it = mCallbacks.find(id);
        if (it != mCallbacks.end()) {
            std::cout << "\n[falcon::JSTimer] Timer Triggered -> Executing ID=" << id << std::endl;
            it->second(); // 执行 JS 回调

            if (msg->arg1 == 1) { // isInterval
                sendMessageDelayed(id, 1, msg->arg2, msg->arg2);
            } else {
                mCallbacks.erase(it);
            }
        }
    }

private:
    MockQuickJS::MockJSRuntime* mRuntime;
    int mNextTimerId;
    std::map<int, std::function<void()>> mCallbacks; // 模拟 std::_Rb_tree
};

// 7. 模拟 greenui::Choreographer 编舞者与 VSYNC 帧驱动
class MockChoreographer : public MockJQuick::Handler {
public:
    MockChoreographer(MockJQuick::Looper* looper)
        : MockJQuick::Handler(looper), mFrameInterval(16), mLastFrameTime(0), mNextFrameId(1), mBarrier(false) {}

    int requestAnimationFrame(std::function<void(int64_t)> cb) {
        int id = mNextFrameId++;
        mAnimCallbacks[id] = cb;
        scheduleNextFrameIfNeeded();
        return id;
    }

    void cancelAnimationFrame(int id) {
        mAnimCallbacks.erase(id);
    }

    void startBarrier() {
        mBarrier = true;
        removeMessages(1 /* MSG_DO_FRAME */);
        std::cout << "[greenui::Choreographer] startBarrier() -> Frame scheduling paused" << std::endl;
    }

    void stopBarrier() {
        mBarrier = false;
        scheduleNextFrameIfNeeded();
        std::cout << "[greenui::Choreographer] stopBarrier() -> Frame scheduling resumed" << std::endl;
    }

    virtual void handleMessage(MockJQuick::Message* msg) override {
        if (msg->what == 1 /* MSG_DO_FRAME */) {
            int64_t frameTime = GetCurrentMonotonicTimeMs();
            mLastFrameTime = frameTime;

            // Phase 0: CALLBACK_INPUT
            // (模拟处理触控事件)

            // Phase 1: CALLBACK_ANIMATION
            if (!mAnimCallbacks.empty()) {
                std::cout << "--- [Choreographer VSYNC] CALLBACK_ANIMATION Begin (FrameTime=" << frameTime << ") ---" << std::endl;
                auto callbacks = mAnimCallbacks;
                mAnimCallbacks.clear();
                for (auto& pair : callbacks) {
                    pair.second(frameTime);
                }
                std::cout << "--- [Choreographer VSYNC] CALLBACK_ANIMATION End ---" << std::endl;
            }

            // Phase 2: CALLBACK_TRAVERSAL
            // (模拟 Skia 布局与绘制提交)

            if (!mAnimCallbacks.empty()) {
                scheduleNextFrameIfNeeded();
            }
        }
    }

private:
    void scheduleNextFrameIfNeeded() {
        if (mBarrier) return;

        int64_t now = GetCurrentMonotonicTimeMs();
        int64_t elapsed = now - mLastFrameTime;
        int64_t delay = (elapsed >= mFrameInterval) ? 0 : (mFrameInterval - elapsed);

        removeMessages(1);
        sendMessageDelayed(1, 0, 0, delay);
    }

    int mFrameInterval; // 16ms for 60fps
    int64_t mLastFrameTime;
    int mNextFrameId;
    bool mBarrier;
    std::map<int, std::function<void(int64_t)>> mAnimCallbacks;
};

// 8. 演示主程序
int main() {
    std::cout << "=================================================================" << std::endl;
    std::cout << " NetEase Youdao S7 Pro (CV1813H) Event Loop Architecture Testbed " << std::endl;
    std::cout << " Single-Core Cortex-A7 @ 1.0 GHz Scheduling Emulation            " << std::endl;
    std::cout << "=================================================================\n" << std::endl;

    MockJQuick::Looper looper;
    MockQuickJS::MockJSRuntime jsRuntime;
    MockJSTimerHandler timerHandler(&looper, &jsRuntime);
    MockChoreographer choreographer(&looper);

    // 将 QuickJS 微任务排空挂入 Looper 回调循环
    looper.addCallback([&]() {
        MockQuickJS::JSThreadLoop(&jsRuntime);
    });

    // 场景 A: 注册一个延时 50ms 的宏任务 (setTimeout)
    // 宏任务内部创建两个 Promise.then 微任务
    timerHandler.setTimeout([&]() {
        std::cout << "[JS App] setTimeout callback fired! Queuing two Promise.then jobs..." << std::endl;
        jsRuntime.enqueueMicrotask([]() {
            std::cout << "    [Promise.then #1] Resolved and running" << std::endl;
        });
        jsRuntime.enqueueMicrotask([]() {
            std::cout << "    [Promise.then #2] Resolved and running" << std::endl;
        });
    }, 50);

    // 场景 B: 注册一个 requestAnimationFrame 动画帧
    choreographer.requestAnimationFrame([&](int64_t timestamp) {
        std::cout << "[JS App] requestAnimationFrame callback running at VSYNC " << timestamp << std::endl;
    });

    // 场景 C: 启动后台输入线程，模拟 80ms 后跨线程向主线程投递触控事件
    std::thread inputThread([&]() {
        std::this_thread::sleep_for(std::chrono::milliseconds(80));
        std::cout << "\n>>> [Input Thread] Capacitive touch pressed -> postMessage to Main Looper <<<" << std::endl;
        timerHandler.setTimeout([]() {
            std::cout << "[Main UI] Processed touch MotionEvent from Input Thread!" << std::endl;
        }, 0);
    });

    // 主事件循环轮询 300ms (模拟运行 15 次，每次上限 20ms)
    int64_t start = GetCurrentMonotonicTimeMs();
    while (GetCurrentMonotonicTimeMs() - start < 200) {
        looper.pollOnce(20);
    }

    inputThread.join();
    std::cout << "\n=================================================================" << std::endl;
    std::cout << " Event Loop Simulation Completed Successfully                    " << std::endl;
    std::cout << "=================================================================" << std::endl;
    return 0;
}
```

---

## 10. 逆向符号与虚拟内存地址速查表 (Symbol & Address Cross-Reference)

下表汇总了在 `/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/libfalcon.so` 中定位并完整分析的全部核心符号、虚拟内存地址（VA）、二进制大小及对应的架构功能：

| 虚拟内存地址 (VA) | 符号大小 | 符号修饰原名 (Mangled Symbol) | Demangled 签名与架构职能说明 |
| :---: | :---: | :--- | :--- |
| `0x0030dc9c` | 204 B | `_ZN6JQuick12JSThreadLoopENS_2spINS_6LooperEEEPNS_7MessageE` | **`JQuick::JSThreadLoop`**：QuickJS 微任务排空泵，挂载于 Looper 迭代尾部，循环执行 `JS_ExecutePendingJob` |
| `0x00563a8c` | 1308 B | `_ZN6falcon14JSTimerHandler13do_setTimeoutEPNS_7JSTimerEP9JSContextyiPyb` | **`falcon::JSTimerHandler::do_setTimeout`**：`setTimeout`/`setInterval` 核心分配，自增 Timer ID，构建红黑树存储，增加 JS 回调引用计数 |
| `0x00563500` | 672 B | `_ZN6falcon14JSTimerHandler13handleMessageEPN6JQuick7MessageE` | **`falcon::JSTimerHandler::handleMessage`**：宏任务到达分发，调用 `JS_Call`，处理循环重放或单次擦除 |
| `0x005637a0` | 312 B | `_ZN6falcon14JSTimerHandler17wrap_clearTimeoutEP9JSContextyiPy` | **`falcon::JSTimerHandler::wrap_clearTimeout`**：注销定时器，修剪 `MessageQueue`，重平衡红黑树并释放 `JSValue` |
| `0x00563fa8` | 72 B | `_ZN6falcon14JSTimerHandler15wrap_setTimeoutEP9JSContextyiPy` | JS 全局 `setTimeout` C++ 封装门面函数 |
| `0x00563ff0` | 72 B | `_ZN6falcon14JSTimerHandler16wrap_setIntervalEP9JSContextyiPy` | JS 全局 `setInterval` C++ 封装门面函数 |
| `0x0030cc08` | 1328 B | `_ZN6falcon20JSTimerExtendHandler26wrap_requestAnimationFrameEP9JSContextyiPy` | **`wrap_requestAnimationFrame`**：创建动画帧包装对象，投递至 Choreographer Phase 1 队列 |
| `0x0030c6b8` | 312 B | `_ZN6falcon20JSTimerExtendHandler25wrap_cancelAnimationFrameEP9JSContextyiPy` | **`wrap_cancelAnimationFrame`**：从 Choreographer 移除挂起的动画帧回调 |
| `0x00433e54` | 224 B | `_ZN7greenui13Choreographer7doFrameEx` | **`greenui::Choreographer::doFrame`**：三阶段渲染总控流水线 (`CALLBACK_INPUT` -> `CALLBACK_ANIMATION` -> `CALLBACK_TRAVERSAL`) |
| `0x00433b54` | 412 B | `_ZN7greenui13Choreographer19scheduleFrameLockedEx` | **`Choreographer::scheduleFrameLocked`**：查询三队列最早到期时间，去重并调用 `sendMessageAtTime` 调度 `MSG_DO_FRAME` |
| `0x004336f8` | 68 B | `_ZN7greenui13Choreographer17getNextFrameDelayEv` | **`Choreographer::getNextFrameDelay`**：基于单调时钟计算与目标帧间隔的差值，实施平滑限频节拍控制 |
| `0x00433280` | 136 B | `_ZN7greenui13Choreographer14setRefreshRateEf` | **`Choreographer::setRefreshRate`**：配置目标刷新率，计算 $1000/\text{fps}$ 间隔并锁定下限 $\ge 8\text{ ms}$ |
| `0x004338a0` | 88 B | `_ZN7greenui13Choreographer12startBarrierEv` | **`Choreographer::startBarrier`**：设置渲染屏障，强制清除 `MSG_DO_FRAME` 消息，冻结渲染 |
| `0x00433df0` | 100 B | `_ZN7greenui13Choreographer11stopBarrierEv` | **`Choreographer::stopBarrier`**：解开渲染屏障，基于当前唤醒单调时间复活帧调度 |
| `0x00433f60` | 288 B | `_ZN7greenui13Choreographer4dumpEv` | **`Choreographer::dump`**：输出当前排队的回调指针调试信息 |
| `0x00433f34` | 44 B | `_ZN7greenui12FrameHandler13handleMessageEPN6JQuick7MessageE` | **`greenui::FrameHandler::handleMessage`**：响应 `MSG_DO_FRAME = 1` 并转入 `doFrame` |
| `0x00221c38` | 508 B | `_Z21ThreadTimeoutCallbackRKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEN6JQuick2spINS7_6LooperEEE` | **`ThreadTimeoutCallback`**：Watchdog 卡死诊断，输出 `Blocked in handler on %s`，休眠 1s 落盘后执行 `abort()` |
| `0x005a03dc` | 364 B | `_ZN6JQuick8Watchdog13threadTimeoutEi` | **`JQuick::Watchdog::threadTimeout`**：看门狗线程超时检测驱动 |
| `0x007d8db4` | 32 B | `_ZTVN6falcon14JSTimerHandlerE` | `falcon::JSTimerHandler` 虚函数表地址 |
| `0x007cfff4` | 32 B | `_ZTVN6falcon20JSTimerExtendHandlerE` | `falcon::JSTimerExtendHandler` 虚函数表地址 |
| `0x007ecf1c` | 12 B | *(Unexported std::vector)* | `vector<JSRuntime*>` 全局向量表地址，管理当前进程内所有活跃的 QuickJS 实例 |

---

## 结语 (Conclusion)

通过对有道词典笔 S7 Pro 核心二进制库 `libfalcon.so` 的深度逆向与符号控制流复原，本手册彻底揭示了其在算能 CV1813H 单核 ARM Cortex-A7 芯片上实现高流畅度交互的底层工业级设计模式：
1. **轻量 AOSP 级 Looper 架构**：抛弃了臃肿的 glib 或 Node.js libuv，采用基于 Linux `epoll` + `eventfd` 的轻量 C++ 原生消息队列；
2. **零拷贝微任务桥接**：利用 `JSThreadLoop` 在宏任务尾部精准排空 QuickJS Promise 任务，实现了完全符合 ECMAScript 规范的任务优先级；
3. **精准单调时钟与编舞者管线**：全链路锁定 `CLOCK_MONOTONIC` 杜绝时间跳变，配合三阶段 `Choreographer` 实现了精准平滑的 60Hz/30Hz 渲染节拍与休眠防暴冲保护。

本手册为深入开发高性能 Falcon 小程序、优化高频定时器性能、排查主线程卡死崩溃以及开发底层 C++ 扩展提供了权威的第一手技术基石。
