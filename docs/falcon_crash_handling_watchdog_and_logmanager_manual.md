# 有道词典笔 S7 Pro 异常崩溃防御、硬件/软件看门狗与 LogManager 系统参考手册
## (NetEase Youdao Dictionary Pen S7 Pro Falcon Crash Handling, Watchdog HAL, ANR Detection & LogManager Architecture Manual)

> **发布版本**: SDK Internal Reference Manual v4.22.0  
> **适用硬件平台**: 网易有道词典笔 S7 Pro (`YDPS7-2`)  
> **硬件主板标识**: `Y08_CV1813_V0`  
> **应用处理器 SoC**: Cvitek (算能科技) CV1813H (Single-core ARM Cortex-A7 @ 1.0 GHz, 32-bit EABIhf)  
> **宿主操作系统**: Embedded Linux 5.10.4-cvitek-armhf  
> **核心组件版本**: Falcon QuickJS Runtime Engine (`libfalcon.so` / `libquickjs.so`), YDDAL 基础核心库 (`libyddal_base_core.so`, `libyddal_adapter_core.so`, `libyddal_business_core.so`), PMS (Package & Process Management System Daemon)

---

## 文档概述与架构导读

本参考手册面向有道词典笔 S7 Pro 操作系统底层研发人员、中间件引擎维护者及高性能 MiniApp 应用开发者。在嵌入式智能硬件（单核 Cortex-A7 @ 1GHz、受限内存 256MB~512MB RAM、NAND Flash 存储）的苛刻运行环境下，运行时的稳健性与自愈能力直接决定了产品体验。

有道词典笔 S7 Pro 的系统架构跨越四个层级：
1. **Linux 内核与硬件驱动层 (Kernel & HAL)**：包含 CV1813H SoC 硬件看门狗定时器驱动（`/dev/watchdog`）、Framebuffer/DRM 显存驱动、ALSA 音频驱动及内核信号调度。
2. **YDDAL 基础中间件与守护进程层 (Native Middleware & Daemons)**：包含 PMS (包与进程管理守护进程)、`/usr/bin/log_manager` 日志服务、Google Breakpad 原生 Minidump 捕获器以及 `libyddal_*` 系列适配层。
3. **Falcon 原生渲染与脚本引擎层 (Falcon & QuickJS Engine)**：包含 `libfalcon.so` 原生 GUI 事件循环、`JQuick::Watchdog` UI 心跳检测线程、POSIX 信号处理状态机 `jquick_sig_handler` 以及 QuickJS JavaScript 解释器。
4. **MiniApp 前端应用运行时 (Vue.js MVVM / QuickJS Runtime)**：运行于 QuickJS 引擎之上的 Vue 2.x 小程序代码，通过 `JSLogManagerProxy` 与 `JSGlobalProxy` 穿透调用 Native 能力。

本文档基于对 S7 Pro 官方固件中真实二进制文件的深度反汇编与符号重构，详尽阐述崩溃捕获、多级看门狗检测、异常传播、日志管理和硬件复位机制。

---

## 目录索引

- [1. Linux 信号处理与 Native 崩溃捕获流水线](#1-linux-信号处理与-native-崩溃捕获流水线)
  - [1.1 POSIX 信号体系与 Falcon 信号注册架构](#11-posix-信号体系与-falcon-信号注册架构)
  - [1.2 替代信号栈机制 (sigaltstack) 与栈溢出崩溃防御](#12-替代信号栈机制-sigaltstack-与栈溢出崩溃防御)
  - [1.3 Falcon 原生信号分发状态机 (jquick_sig_handler)](#13-falcon-原生信号分发状态机-jquick_sig_handler)
  - [1.4 10 槽位 Tombstone 报告循环滚动归档算法](#14-10-槽位-tombstone-报告循环滚动归档算法)
  - [1.5 Google Breakpad 原生 Minidump 捕获子系统](#15-google-breakpad-原生-minidump-捕获子系统)
  - [1.6 崩溃紧急状态下的系统级安全屏障与驱动锁释放](#16-崩溃紧急状态下的系统级安全屏障与驱动锁释放)
- [2. UI 线程心跳与 ANR (Application Not Responding) 监测](#2-ui-线程心跳与-anr-application-not-responding-监测)
  - [2.1 Falcon 内部看门狗线程 (JQuick::Watchdog) 架构设计](#21-falcon-内部看门狗线程-jquickwatchdog-架构设计)
  - [2.2 监测轮询机制与 Looper 投递状态机](#22-监测轮询机制与-looper-投递状态机)
  - [2.3 ANR 超时阈值判定与 anrdebug 调试门禁](#23-anr-超时阈值判定与-anrdebug-调试门禁)
  - [2.4 PMS 外部进程级守护与双阶梯超时策略 (5s 软超时 / 7s 强杀)](#24-pms-外部进程级守护与双阶梯超时策略-5s-软超时--7s-强杀)
  - [2.5 崩溃频次统计熔断与桌面 Launcher 容灾回滚机制](#25-崩溃频次统计熔断与桌面-launcher-容灾回滚机制)
- [3. QuickJS 异常传播与 JavaScript 运行时保护](#3-quickjs-异常传播与-javascript-运行时保护)
  - [3.1 跨层异常拦截链条全景拓扑](#31-跨层异常拦截链条全景拓扑)
  - [3.2 QuickJS 原生堆栈展开与 C++ 格式化实现 (qjs_std_dump_error)](#32-quickjs-原生堆栈展开与-c-格式化实现-qjs_std_dump_error)
  - [3.3 未捕获 Promise 拒绝追踪 (JS_SetHostPromiseRejectionTracker)](#33-未捕获-promise-拒绝追踪-js_sethostpromiserejectiontracker)
  - [3.4 QuickJS 内存压力治理、GC 回收机制与堆内存防护](#34-quickjs-内存压力治理gc-回收机制与堆内存防护)
- [4. 系统日志管理架构 (LogManager)](#4-系统日志管理架构-logmanager)
  - [4.1 控制台标准输出劫持 (falcon::installJSConsole)](#41-控制台标准输出劫持-falconinstalljsconsole)
  - [4.2 原生 C 模块 logmanager (JSLogManagerProxy) 9 大 API 详解](#42-原生-c-模块-logmanager-jslogmanagerproxy-9-大-api-详解)
  - [4.3 YLogManagerModulePrivate 底层流向与压缩流水线](#43-ylogmanagermoduleprivate-底层流向与压缩流水线)
  - [4.4 守护进程 /usr/bin/log_manager 存储规划与云端遥测网关](#44-守护进程-usrbinlog_manager-存储规划与云端遥测网关)
- [5. 硬件看门狗 (/dev/watchdog) 联动](#5-硬件看门狗-devwatchdog-联动)
  - [5.1 SoC CV1813H 硬件看门狗 (WDT) 架构与 Linux ioctl 接口](#51-soc-cv1813h-硬件看门狗-wdt-架构与-linux-ioctl-接口)
  - [5.2 全链路穿透体系：从 MiniApp JS 到内核 WDT](#52-全链路穿透体系从-miniapp-js-到内核-wdt)
  - [5.3 喂狗周期策略与软硬件三层看门狗阶梯联动模型](#53-喂狗周期策略与软硬件三层看门狗阶梯联动模型)
  - [5.4 系统死锁、内核崩溃与整机硬件冷复位 (Hard Reset) 时序](#54-系统死锁内核崩溃与整机硬件冷复位-hard-reset-时序)
- [6. 开发者生产级防崩套件与调试诊断指南](#6-开发者生产级防崩套件与调试诊断指南)
  - [6.1 生产级防崩卫士全量源码 (GlobalCrashGuard.ts)](#61-生产级防崩卫士全量源码-globalcrashguardts)
  - [6.2 Minidump 与 Tombstone 符号还原实战指南](#62-minidump-与-tombstone-符号还原实战指南)
  - [6.3 生产环境典型崩溃与死锁排障剖析 (Gotchas)](#63-生产环境典型崩溃与死锁排障剖析-gotchas)
- [7. 术语表与规范索引](#7-术语表与规范索引)

---
## 1. Linux 信号处理与 Native 崩溃捕获流水线

### 1.1 POSIX 信号体系与 Falcon 信号注册架构

在有道词典笔 S7 Pro 的运行环境中，Falcon 引擎主进程启动时必须接管标准 POSIX 信号，以防止因未处理的底层异常直接导致内核抛出 SIGSEGV 强杀进程而留下未定义的硬件锁或损坏的数据文件。

#### 1.1.1 信号注册初始化函数 `installSignals` 逆向解析

在二进制文件 `/usr/lib/libfalcon.so` 中，信号体系的初始化由全局导出函数 `installSignals`（虚拟地址：`0x22b26c`）完成。反汇编逻辑如下：

```arm
// libfalcon.so: installSignals() @ 0x22b26c
0x0022b26c:  push    {r4, r5, r6, lr}
0x0022b270:  sub     sp, sp, #0x98          ; 在栈上分配 152 字节 sigaction 结构空间
0x0022b274:  mov     r1, #1                 ; SIG_IGN = 1
0x0022b278:  mov     r0, #1                 ; SIGHUP = 1
0x0022b27c:  bl      signal                 ; signal(SIGHUP, SIG_IGN)
0x0022b280:  mov     r1, #1                 ; SIG_IGN
0x0022b284:  mov     r0, #13                ; SIGPIPE = 13 (防止 Socket 对端关闭导致进程暴毙)
0x0022b288:  bl      signal                 ; signal(SIGPIPE, SIG_IGN)
0x0022b28c:  mov     r1, #1                 ; SIG_IGN
0x0022b290:  mov     r0, #3                 ; SIGQUIT = 3
0x0022b294:  bl      signal                 ; signal(SIGQUIT, SIG_IGN)
0x0022b298:  mov     r1, #1                 ; SIG_IGN
0x0022b29c:  mov     r0, #15                ; SIGTERM = 15
0x0022b2a0:  bl      signal                 ; signal(SIGTERM, SIG_IGN)

; 准备构造 sigaction 结构体
0x0022b2a4:  mov     r2, #0x8c              ; sizeof(struct sigaction) = 140
0x0022b2a8:  mov     r1, #0                 ; 清零缓冲区
0x0022b2ac:  add     r0, sp, #8
0x0022b2b0:  bl      memset
0x0022b2b4:  ldr     r3, [pc, #0x54]        ; 加载 jquick_sig_handler 地址 (0x22ab54)
0x0022b2b8:  mov     r2, #0x10000000        ; SA_RESTART (0x10000000)
0x0022b2bc:  str     r3, [sp, #8]           ; sa.sa_handler = jquick_sig_handler
0x0022b2c0:  str     r2, [sp, #0x90]        ; sa.sa_flags = SA_RESTART

; 循环注册目标致命信号与诊断信号
0x0022b2c4:  ldr     r4, [pc, #0x48]        ; 指向信号常量表数组
0x0022b2c8:  mov     r5, #0                 ; 计数器 i = 0
0x0022b2cc:  ldr     r0, [r4, r5, lsl #2]   ; 加载 sig = signal_table[i]
0x0022b2d0:  add     r1, sp, #8             ; 指向 sa 结构体
0x0022b2d4:  mov     r2, #0                 ; oldact = nullptr
0x0022b2d8:  bl      sigaction              ; sigaction(sig, &sa, NULL)
0x0022b2dc:  add     r5, r5, #1
0x0022b2e0:  cmp     r5, #0xb               ; 共计 11 个核心信号
0x0022b2e4:  bne     0x22b2cc
0x0022b2e8:  add     sp, sp, #0x98
0x0022b2ec:  pop     {r4, r5, r6, pc}
```

此外，在 `0x22b0e8` 处导出的 `installSignalHandler(int sig, void (*handler)(int))` 支持运行时动态覆盖或注入定制回调，使得外部崩溃监控探针可以在应用层建立链路钩子。

#### 1.1.2 接管信号矩阵与系统行为

| 信号名称 | 信号量编号 | POSIX 标准含义 | Falcon 框架响应策略 |
| :--- | :--- | :--- | :--- |
| `SIGHUP` | 1 | 终端挂起 (Hangup) | **显式忽略 (`SIG_IGN`)**：防止串口终端调试断开导致 GUI 退出 |
| `SIGQUIT` | 3 | 键盘退出 (Quit) | **显式忽略 (`SIG_IGN`)**：屏蔽意外的控制台退出组合键 |
| `SIGILL` | 4 | 非法指令 (Illegal Instruction) | **致命崩溃捕获**：生成崩溃 Tombstone，重置为默认动作后自毁 |
| `SIGTRAP` | 5 | 硬件断点/陷阱 (Trace Trap) | **致命崩溃捕获**：用于断点失效捕获与异常调试 |
| `SIGABRT` | 6 | 异常终止 (Abort) | **致命崩溃捕获**：多由 `assert()` 失败或 C++ 未捕获异常触发 |
| `SIGBUS` | 7 | 总线错误 (Bus Error) | **致命崩溃捕获**：多由物理内存对齐违例或 mmap 映射文件截断触发 |
| `SIGFPE` | 8 | 浮点异常 (Floating Point Exception) | **致命崩溃捕获**：整数除零或底层算术溢出 |
| `SIGUSR1` | 10 | 用户自定义信号 1 | **实时诊断转储**：转储当前主线程堆栈到 syslog，**不中断进程运行** |
| `SIGSEGV` | 11 | 段错误 (Segmentation Fault) | **致命崩溃捕获**：野指针、空指针解引用或越界读写物理内存 |
| `SIGUSR2` | 12 | 用户自定义信号 2 | **ANR 转储信号**：转储 ANR 堆栈至 10 槽位报告，**不中断进程运行** |
| `SIGPIPE` | 13 | 管道破裂 (Broken Pipe) | **显式忽略 (`SIG_IGN`)**：防止 IPC Domain Socket 断开杀死主进程 |
| `SIGALRM` | 14 | 实时时钟超时 (Alarm Clock) | **定时器异常捕获**：转储异常定时器超时上下文 |
| `SIGTERM` | 15 | 软件终止信号 (Termination) | **显式忽略 (`SIG_IGN`)**：强制通过系统控制脚本以优雅流程退出 |
| `SIGIO` | 29 | 异步 I/O 事件可读写 | **I/O 调度陷阱**：转储异常的非阻塞 I/O 事件 |
| `SIGSYS` | 31 | 非法系统调用 (Bad Syscall) | **安全违规捕获**：防止 Seccomp 或未授权架构系统调用击穿 |

---

### 1.2 替代信号栈机制 (sigaltstack) 与栈溢出崩溃防御

在 ARM Linux 架构下，函数调用的局部变量与返回地址均存储在当前的 SP（Stack Pointer，`r13`）栈空间中。当代码发生**深度递归调用（Deep Recursion）**或**局部超大数组爆栈**时，SP 寄存器将向下越界击穿分配的栈内存保护页（Guard Page），触发 MMU 的 Page Fault 进而产生 `SIGSEGV`。

#### 1.2.1 缺乏替代栈时的死锁陷阱

若未配置替代信号栈，内核在向故障线程投递 `SIGSEGV` 时，会尝试在**已经溢出损坏的当前线程栈**上压入信号上下文帧（`ucontext_t` 与 `sigframe`）。这会立刻在内核态触发二次 Page Fault（Double Fault）。此时 Linux 内核无法执行用户的信号处理逻辑，将直接强制发送 `SIGKILL` 清除进程。更严重的是，在嵌入式驱动存在未释放自旋锁（Spinlock）或互斥锁（Mutex）的情况下，硬杀进程会导致外设总线死锁。

#### 1.2.2 Breakpad 与 Falcon 中的 sigaltstack 实现对比

在 `/usr/lib/libyddal_base_core.so`（Google Breakpad 实现）的 `ExceptionHandler::InstallHandlersLocked`（偏移 `0xb5330`）中，Breakpad 严格声明并激活了替代信号栈：

```cpp
// Google Breakpad in libyddal_base_core.so
static void SetupAlternateStack() {
    stack_t new_stack;
    memset(&new_stack, 0, sizeof(new_stack));
    // 分配独立于进程主栈的 16KB 备用信号栈
    new_stack.ss_sp = malloc(16 * 1024);
    new_stack.ss_size = 16 * 1024;
    new_stack.ss_flags = 0;
    
    if (sigaltstack(&new_stack, nullptr) != 0) {
        // 替代栈注册失败降级处理
        YLog_print(0x8, "[Breakpad] Failed to setup sigaltstack!
");
    }
}
```

在注册 `sigaction` 时，Breakpad 显式设置了标志位：
```arm
// libyddal_base_core.so @ 0xb53f8
0x000b53f8:  str   r3, [sp, #4]       ; sa_sigaction = SignalHandler
0x000b53fc:  ldr   r3, [pc, #0x48]    ; 加载常量 0x08000004
0x000b5400:  str   r3, [sp, #0x88]    ; sa_flags = SA_ONSTACK | SA_SIGINFO
```

`0x08000004` 即：
- `SA_SIGINFO` (`0x00000004`)：要求内核向信号处理函数传递三参数 `(int sig, siginfo_t *info, void *ucontext)`，以获取 ARM 寄存器状态 `ucontext_t`。
- `SA_ONSTACK` (`0x08000000`)：告知内核处理该信号时必须切换至 `sigaltstack` 预分配的堆内存栈空间，确保栈溢出时信号处理器依然拥有独立安全的执行栈。

---

### 1.3 Falcon 原生信号分发状态机 (`jquick_sig_handler`)

在 `libfalcon.so` 中，`jquick_sig_handler`（虚拟地址：`0x22ab54`）是整个 GUI 运行时的核心信号调度中枢。它不是简单的打印退出，而是一个高度精密的**多路分支状态机**。

#### 1.3.1 逆向反汇编深度还原

```arm
// libfalcon.so: jquick_sig_handler(int sig) @ 0x22ab54
0x0022ab54:  push    {r4, r5, r6, r7, lr}
0x0022ab58:  sub     r1, r0, #0xa           ; r1 = sig - 10
0x0022ab5c:  bics    r1, r1, #2             ; 检查 r1 是否为 0 或 2 (即 sig == 10 或 sig == 12)
0x0022ab60:  beq     0x22abdc               ; 若 sig 为 10 或 12，跳转到 USR 诊断分支

; === 分支 1: 致命崩溃信号处理流水线 (Fatal Signals: 11, 7, 6, 4, 8 ...) ===
0x0022ab64:  mov     r4, r0                 ; r4 保存当前致命信号 sig
0x0022ab68:  bl      0x22afbc               ; 调用 10 槽位文件滚动算法，移动 miniapp_crash_report_%02d
0x0022ab6c:  ldr     r0, [pc, #0xac]        ; 加载路径: "/userdata/miniapp/data/crash_reports/miniapp_crash_report_00"
0x0022ab70:  ldr     r1, [pc, #0xac]        ; 模式: "w"
0x0022ab74:  bl      fopen                  ; 打开 00 号崩溃转储文件
0x0022ab78:  subs    r5, r0, #0             ; r5 = FILE*
0x0022ab7c:  beq     0x22aba0               ; 若文件打开失败则跳过文件写入

0x0022ab80:  mov     r0, r5
0x0022ab84:  mov     r1, r4                 ; 传递 sig
0x0022ab88:  bl      0x22ad78               ; 写入崩溃元信息头部 (PID, TID, Signal, Crash Time, Reason)
0x0022ab8c:  mov     r0, r5
0x0022ab90:  bl      0x22b04c               ; 调用 libc backtrace / backtrace_symbols 转储栈帧到文件
0x0022ab94:  mov     r0, r5
0x0022ab98:  bl      fflush                 ; 强制刷盘
0x0022ab9c:  bl      fclose                 ; 关闭文件

; 致命崩溃退出序列
0x0022aba0:  bl      0x22b1c0               ; 硬件保护动作：解除 Framebuffer 双缓冲与释放音频驱动锁
0x0022aba4:  mov     r0, r4
0x0022aba8:  mov     r1, #0                 ; SIG_DFL = 0
0x0022abac:  bl      signal                 ; signal(sig, SIG_DFL) 恢复内核默认信号处理
0x0022abb0:  mov     r0, r4
0x0022abb4:  bl      raise                  ; raise(sig) 重新向自身抛出致命信号，触发 Linux 内核标准自毁流程
0x0022abb8:  pop     {r4, r5, r6, r7, pc}

; === 分支 2: USR 信号分流与 ANR 诊断流水线 ===
0x0022abdc:  cmp     r0, #0xa               ; 判断是否为 SIGUSR1 (10)
0x0022abe0:  bne     0x22ac10               ; 若不等于 10，则必为 SIGUSR2 (12, ANR)

; --- 子分支 2.1: SIGUSR1 (10) 在线堆栈快速打印 ---
0x0022abe4:  ldr     r0, [pc, #0x40]        ; 加载格式串: "[JQuick-Diag] Live Backtrace Dump for PID %d:\n"
0x0022abe8:  bl      getpid
0x0022abec:  bl      printf
0x0022abf0:  mov     r0, #1                 ; fd = 1 (stdout / console)
0x0022abf4:  bl      0x22b04c               ; 打印当前调用栈至系统控制台
0x0022abf8:  pop     {r4, r5, r6, r7, pc}   ; 关键点：直接返回，不退出应用！

; --- 子分支 2.2: SIGUSR2 (12) ANR 无响应转储 ---
0x0022ac10:  bl      0x22b000               ; 调用 ANR 专属 10 槽位滚动算法: 移动 miniapp_anr_report_%02d
0x0022ac14:  ldr     r0, [pc, #0x28]        ; 加载路径: "/userdata/miniapp/data/crash_reports/miniapp_anr_report_00"
0x0022ac18:  ldr     r1, [pc, #0x28]        ; "w"
0x0022ac1c:  bl      fopen
0x0022ac20:  subs    r5, r0, #0
0x0022ac24:  beq     0x22ac44
0x0022ac28:  mov     r0, r5
0x0022ac2c:  bl      0x22ae40               ; 写入 ANR Header (PID, Looper State, Blocked Time)
0x0022ac30:  mov     r0, r5
0x0022ac34:  bl      0x22b04c               ; 转储死锁调用栈到 ANR 报告
0x0022ac38:  mov     r0, r5
0x0022ac3c:  bl      fflush
0x0022ac40:  bl      fclose
0x0022ac44:  pop     {r4, r5, r6, r7, pc}   ; 关键点：生成报告后返回，维持进程存活，等待 PMS 决策
```

#### 1.3.2 信号分发状态机流向图

```
                        ┌───────────────────────────────┐
                        │   jquick_sig_handler(sig)     │  (0x0022ab54)
                        └───────────────┬───────────────┘
                                        │
                         sub r1, r0, #10; bics r1, r1, #2
                                        │
                ┌───────────────────────┴───────────────────────┐
                │ [r1 == 0] (sig == 10 || sig == 12)            │ [r1 != 0] (Fatal Signals)
                ▼                                               ▼
       ┌──────────────────┐                           ┌───────────────────────────┐
       │   cmp sig, #10   │                           │ 触发 Crash 轮转算法 (0x22afbc)│
       └────────┬─────────┘                           │ 滚动 miniapp_crash_report │
                │                                     └─────────────┬─────────────┘
       ┌────────┴────────┐                                          │
[sig == 10]          [sig == 12]                                    ▼
       │                 │                            ┌───────────────────────────┐
       ▼                 ▼                            │ 打开 crash_report_00 写入  │
┌──────────────┐  ┌──────────────────────────┐        │ 转储 ARM 寄存器与 Backtrace│
│  SIGUSR1:    │  │ SIGUSR2:                 │        └─────────────┬─────────────┘
│ 在线诊断探针 │  │ 触发 ANR 轮转算法 (0x22b000)│                     │
│ 输出堆栈至   │  │ 滚动 miniapp_anr_report   │                     ▼
│ stdout/syslog│  │ 写入 anr_report_00 文件   │        ┌───────────────────────────┐
└──────┬───────┘  └─────────────┬────────────┘        │ 释放 Framebuffer/Audio 锁 │
       │                        │                     │ (0x0022b1c0)              │
       │                        │                     └─────────────┬─────────────┘
       ▼                        ▼                                   │
┌──────────────┐         ┌──────────────┐                           ▼
│ 返回中断现场 │         │ 返回中断现场 │              ┌───────────────────────────┐
│ 进程继续运行 │         │ 进程维持存活 │              │ signal(sig, SIG_DFL)      │
└──────────────┘         └──────────────┘              │ raise(sig) 触发内核级终止  │
                                                      └───────────────────────────┘
```

---

### 1.4 10 槽位 Tombstone 报告循环滚动归档算法

为了在闪存写寿命有限的嵌入式设备上防止磁盘空间被持续崩溃打满，Falcon 引擎实现了极为严格的 **10 槽位逆向升序滚动归档算法**。

#### 1.4.1 文件轮转算法原理

文件保存目录为 `/userdata/miniapp/data/crash_reports/`。
- Crash 报告前缀：`miniapp_crash_report_`
- ANR 报告前缀：`miniapp_anr_report_`
- 槽位编号：`00` 到 `09`（固定双字符十进制）。

在 `libfalcon.so` 的 `0x22afbc` 处，轮转算法的 C++ 还原如下：

```cpp
// libfalcon.so: 崩溃报告 10 槽位滚动算法逆向还原
void rotateCrashReports(const char* base_dir, const char* prefix) {
    char old_path[256];
    char new_path[256];
    
    // 步骤 1: 物理删除最古老的槽位 09 (若存在)
    snprintf(old_path, sizeof(old_path), "%s/%s_09", base_dir, prefix);
    unlink(old_path);
    
    // 步骤 2: 从 08 倒序迭代至 00，依次重命名顺移: i -> i + 1
    for (int i = 8; i >= 0; --i) {
        snprintf(old_path, sizeof(old_path), "%s/%s_%02d", base_dir, prefix, i);
        snprintf(new_path, sizeof(new_path), "%s/%s_%02d", base_dir, prefix, i + 1);
        
        // 若旧文件存在，原子重命名推入下一槽位
        if (access(old_path, F_OK) == 0) {
            rename(old_path, new_path);
        }
    }
    // 循环结束后，槽位 00 腾空，供当前最新转储写入
}
```

该算法保证了：
1. 任何时刻崩溃报告文件数不会超过 10 个，磁盘占用上限恒定（每个文件通常在 4KB~16KB，总开销 < 200KB）。
2. `00` 号文件始终代表**距离当前最近一次发生的崩溃或 ANR**。
3. 编号越大，代表发生时间越早。

#### 1.4.2 槽位演进状态机迁移表

下表示意连续 3 次发生崩溃时，磁盘上文件的状态迁移序列：

| 发生事件 | 槽位 00 (最新) | 槽位 01 | 槽位 02 | ... | 槽位 08 | 槽位 09 (最旧) | 磁盘清理动作 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **初始状态** | Crash_A | Crash_B | Crash_C | ... | Crash_I | Crash_J | - |
| **发生第 1 次崩溃** | **Crash_New_1** | Crash_A | Crash_B | ... | Crash_H | Crash_I | 自动 unlink Crash_J |
| **发生第 2 次崩溃** | **Crash_New_2** | Crash_New_1 | Crash_A | ... | Crash_G | Crash_H | 自动 unlink Crash_I |
| **发生第 3 次崩溃** | **Crash_New_3** | Crash_New_2 | Crash_New_1 | ... | Crash_F | Crash_G | 自动 unlink Crash_H |

---

### 1.5 Google Breakpad 原生 Minidump 捕获子系统

除 Falcon 引擎的原生 Tombstone 外，词典笔系统在 `/usr/lib/libyddal_base_core.so` 中完整集成了 Google Breakpad 跨平台崩溃处理框架。

#### 1.5.1 Breakpad 模块组件结构

```
libyddal_base_core.so
 ├── YDALBASEAPI::YBreakpad::init(dump_path, callback)  (0x0006f4f8)
 ├── google_breakpad::ExceptionHandler::InstallHandlersLocked() (0x000b5330)
 ├── google_breakpad::ExceptionHandler::SignalHandler()         (0x000b59a4)
 ├── google_breakpad::ExceptionHandler::GenerateDump()          (0x000b5578)
 ├── google_breakpad::UContextReader::FillCPUContext()          (0x000bfbb0)
 └── google_breakpad::LinuxPtraceDumper                         (0x000c00f0)
```

#### 1.5.2 ARM 32-bit CPU 上下文捕获 (`UContextReader::FillCPUContext`)

在 `libyddal_base_core.so` 偏移 `0xbfbb0` 处，Breakpad 从 Linux 内核传入的 `ucontext_t`（ARM 架构特有）提取全部 16 个核心整数通用寄存器与程序状态寄存器（CPSR），组装为 `MDRawContextARM` 标准 Minidump 结构：

```cpp
// Breakpad ARM 上下文填充逆向定义
struct MDRawContextARM {
    uint32_t context_flags; // MD_CONTEXT_ARM = 0x40000000
    uint32_t iregs[16];     // r0 - r15 (r13=SP, r14=LR, r15=PC)
    uint32_t cpsr;          // Current Program Status Register
    uint32_t float_save[64];// VFP / NEON 浮点寄存器
};

void UContextReader::FillCPUContext(const ucontext_t* uc, MDRawContextARM* out) {
    out->context_flags = 0x40000000; // MD_CONTEXT_ARM
    // 从 Linux 内核 mcontext_t 映射 ARM 核心寄存器
    out->iregs[0]  = uc->uc_mcontext.arm_r0;
    out->iregs[1]  = uc->uc_mcontext.arm_r1;
    out->iregs[2]  = uc->uc_mcontext.arm_r2;
    out->iregs[3]  = uc->uc_mcontext.arm_r3;
    out->iregs[4]  = uc->uc_mcontext.arm_r4;
    out->iregs[5]  = uc->uc_mcontext.arm_r5;
    out->iregs[6]  = uc->uc_mcontext.arm_r6;
    out->iregs[7]  = uc->uc_mcontext.arm_r7;
    out->iregs[8]  = uc->uc_mcontext.arm_r8;
    out->iregs[9]  = uc->uc_mcontext.arm_r9;
    out->iregs[10] = uc->uc_mcontext.arm_r10;
    out->iregs[11] = uc->uc_mcontext.arm_fp; // Frame Pointer
    out->iregs[12] = uc->uc_mcontext.arm_ip; // Intra-Procedure-Call scratch
    out->iregs[13] = uc->uc_mcontext.arm_sp; // Stack Pointer
    out->iregs[14] = uc->uc_mcontext.arm_lr; // Link Register (返回地址)
    out->iregs[15] = uc->uc_mcontext.arm_pc; // Program Counter (崩溃指令地址)
    out->cpsr      = uc->uc_mcontext.arm_cpsr;
}
```

#### 1.5.3 进程外 Ptrace 转储机制 (`YD_BREAKPAD_FORK_MODE`)

Breakpad 支持两种转储模式：
1. **进程内直接转储 (In-Process Dumper)**：在当前崩溃线程中直接写入 `.dmp` 文件。缺点是若堆已严重损坏，转储过程容易二次崩溃。
2. **Fork 子进程 Ptrace 转储 (Out-of-Process Dumper)**：当检测到环境变量 `YD_BREAKPAD_FORK_MODE=1` 时，Breakpad 在信号触发后调用 `sys_clone()` 创建子进程，子进程通过 `ptrace(PTRACE_ATTACH, parent_pid)` 挂载父进程，安全读取父进程的 `/proc/<pid>/maps` 虚拟内存镜像，生成 100% 完整的 `.dmp` 崩溃包。

#### 1.5.4 Minidump 二进制格式规范

生成的 Minidump 二进制包包含以下核心流（Streams）：
- `MD_HEADER`：文件魔数 `MDMP`（`0x504d444d`），版本号，流目录数量。
- `MD_DIRECTORY`：各个数据流在文件内的偏移与长度索引表。
- `MD_SYSTEM_INFO_STREAM`：操作系统版本（Linux 5.10.4）、CPU 架构（ARMv7 Processor rev 5）。
- `MD_THREAD_LIST_STREAM`：进程内所有线程的 ID、挂起计数、栈内存范围（Stack Memory Range）及 CPU 上下文指针。
- `MD_MODULE_LIST_STREAM`：加载的所有 ELF 共享动态库列表（基地址、尺寸、文件路径、Build ID 校验码）。
- `MD_EXCEPTION_STREAM`：发生崩溃的线程 ID、异常信号代码（如 `SIGSEGV`）、异常故障内存地址（`si_addr`）以及崩溃瞬间的寄存器状态。

---

### 1.6 崩溃紧急状态下的系统级安全屏障与驱动锁释放

在低端嵌入式设备中，用户界面进程发生段错误崩溃时，若直接被操作系统粗暴清理，通常会导致极为恶劣的硬件残留缺陷：
1. **液晶屏花屏与残留坏帧**：Cvitek CV1813H 的硬件显示控制器（VO / Video Output）依赖双缓冲机制（Front Buffer 与 Back Buffer）。若渲染线程持有 DRM/FB 显存锁时暴毙，物理屏幕将永远冻结在最后绘制到一半的破裂图像上。
2. **音频持续啸叫或暴音**：音频播放服务（`audio_server`）若通过 ALSA 独占打开了 `/dev/snd/pcmC0D0p` 设备并处于 DMA 环形缓冲区推送状态，应用猝死会导致 DMA 控制器持续循环读取同一段脏音频，产生刺耳的持续啸叫。

在 `libfalcon.so` 偏移 `0x22b1c0` 处封装的 `falcon_emergency_cleanup` 实现了硬件保护：
```cpp
// 崩溃保护流水线逆向逻辑
void falcon_emergency_cleanup() {
    // 1. 强制断开 Framebuffer 映射并重置驱动硬件图层
    int fb_fd = open("/dev/fb0", O_RDWR);
    if (fb_fd >= 0) {
        // 发送 ioctl 解除平面的硬件合成锁，置黑屏或待机色，防止花屏残留
        ioctl(fb_fd, FBIOPUT_VSCREENINFO, &fallback_vscreeninfo);
        close(fb_fd);
    }
    
    // 2. 音频子系统紧急静音
    int dsp_fd = open("/dev/snd/pcmC0D0p", O_WRONLY | O_NONBLOCK);
    if (dsp_fd >= 0) {
        ioctl(dsp_fd, SNDRV_PCM_IOCTL_DROP, 0); // 立即丢弃当前 DMA 缓冲数据
        close(dsp_fd);
    }
    
    // 3. 强制脏页落盘并同步关键描述符
    sync();
}
```

---
## 2. UI 线程心跳与 ANR (Application Not Responding) 监测

### 2.1 Falcon 内部看门狗线程 (`JQuick::Watchdog`) 架构设计

为了监控主事件循环（GUI Looper 线程）的健康状况，Falcon 运行时引擎在启动伊始便派生了一个名为 `"JQuick-Watchdog"` 的独立 POSIX 看门狗线程。

#### 2.1.1 内部数据结构与单例模式

在 `/usr/lib/libfalcon.so` 中，看门狗由类 `JQuick::Watchdog` 管理，其核心方法与符号分布如下：
- `Watchdog::singleton()`（`0x59faec`）：全局看门狗单例访问点。
- `Watchdog::Watchdog()`（`0x59fa10`）：看门狗初始化并启动守护线程。
- `Watchdog::addMonitor(Monitor*)`（`0x59fd78`）：向监控链表注册待监测的目标线程。
- `Watchdog::doMonitor()`（`0x5a02f0`）：工作循环，定期向所有受监控的 Looper 投递 Ping 探测包。
- `Watchdog::threadTimeout(Monitor*)`（`0x5a03dc`）：超时触发回调。

C++ 类结构逆向还原：
```cpp
namespace JQuick {

class Looper;

class Monitor {
public:
    std::string m_name;           // 线程标识名称 (例如: "Main", "Worker", "Render")
    Looper*     m_looper;         // 目标受监控线程所绑定的消息循环实例
    uint64_t    m_timeout_ms;     // 超时判定阈值 (默认 "Main" 线程为 30000ms，备用线程为 10000ms)
    uint64_t    m_last_ping_time; // 上一次投递探测消息时的单调时钟时间戳 (CLOCK_MONOTONIC)
    bool        m_completed;      // 主事件循环是否已成功取出并执行了本次 Ping 回调
};

class Watchdog {
public:
    static Watchdog* singleton();
    void addMonitor(Monitor* monitor);
    void start();
    void threadTimeout(Monitor* mon);

private:
    Watchdog();
    ~Watchdog();
    static void* threadEntry(void* arg); // pthread 线程入口函数
    void runThreadLoop();                // "JQuick-Watchdog" 线程内部执行体
    void doMonitor();                    // 遍历分发 Ping 包
    
    std::vector<Monitor*> m_monitors;
    pthread_mutex_t       m_mutex;
    pthread_cond_t        m_cond;
    pthread_t             m_thread_id;
    bool                  m_running;
};

} // namespace JQuick
```

---

### 2.2 监测轮询机制与 Looper 投递状态机

`JQuick-Watchdog` 线程不直接干涉业务执行，而是基于**异步 Ping-Pong 握手契约**工作：

```
 Watchdog 线程 ("JQuick-Watchdog")             主事件循环线程 ("Main" Looper)
          │                                                  │
          │────── 1. doMonitor() 遍历监控列表 ──────────────>│
          │       设置 m_completed = false                   │
          │       记录 m_last_ping_time = now                │
          │       投递 MonitorHandler::PING 消息 ───────────>│ (排入 Looper 消息队列尾部)
          │                                                  │
          │────── 2. 线程休眠 5000ms (usleep / cond_wait) ───│
          │                                                  │
          │                                                  │ ─── 3. 主循环处理队列中的 PING ───┐
          │                                                  │     设置 m_completed = true       │
          │<───── 4. 唤醒并检查: m_completed == true ? ──────│ <────────────────────────────────┘
          │       [状态正常]: 开启下一轮调度                   │
          │                                                  │
          │       [若 m_completed == false]:                 │
          │       now - m_last_ping_time > 30000ms ?         │
          │         ├─ 否: 维持等待，继续跟踪                  │ (主循环被密集计算或死锁卡住)
          │         └─ 是: 触发 threadTimeout(mon) ─────────>│
```

#### 2.2.1 逆向解析 `Watchdog::doMonitor` (`0x5a02f0`)

在反汇编中，`Watchdog::doMonitor` 的工作流程十分紧凑：
1. 调用 `clock_gettime(CLOCK_MONOTONIC, &ts)` 获取微秒级精确时钟。
2. 循环遍历 `m_monitors` 向量中的所有指针。
3. 若 `mon->m_completed` 为 `false` 且当前时间减去 `mon->m_last_ping_time` 超过了 `mon->m_timeout_ms`，直接分支调用 `Watchdog::threadTimeout(mon)`。
4. 若 `mon->m_completed` 为 `true`，则将 `mon->m_completed` 重置为 `false`，更新 `mon->m_last_ping_time`，并向目标 Looper 投递一个无参的 Ping 任务闭包。

---

### 2.3 ANR 超时阈值判定与 `anrdebug` 调试门禁

#### 2.3.1 超时判定分支反汇编

当主线程超过 30 秒（`0x7530` 毫秒）未回应 Ping 消息时，`Watchdog::threadTimeout` 将被激活。在 `libfalcon.so` 偏移 `0x221c38` 处的 `ThreadTimeoutCallback` 中，存在一段关键的安全调试分支检查：

```arm
// libfalcon.so @ 0x221c38: ThreadTimeoutCallback
0x00221c38:  push    {r4, r5, r6, lr}
0x00221c3c:  ldr     r0, [pc, #0x50]    ; 加载配置键名: "anrdebug"
0x00221c40:  bl      0x21bb14           ; getSystemConfigValue("anrdebug")
0x00221c44:  subs    r4, r0, #0         ; 检查配置返回值
0x00221c48:  beq     0x221c60           ; 若未设置或为 nullptr，进入生产自杀分支

0x00221c4c:  ldr     r1, [pc, #0x44]    ; 加载匹配串: "enable"
0x00221c50:  bl      strcmp             ; strcmp(val, "enable")
0x00221c54:  cmp     r0, #0
0x00221c58:  beq     0x221c80           ; 若为 "enable"，进入挂起等待调试分支

; 生产环境自毁分支
0x00221c60:  ldr     r0, [pc, #0x34]    ; 加载日志: "Kill self after 1 second due to ANR"
0x00221c64:  bl      0x21aa30           ; YLog_print(0x8, ...)
0x00221c68:  mov     r0, #1
0x00221c6c:  bl      sleep              ; 延时 1 秒给日志刷盘
0x00221c70:  bl      abort              ; 触发 SIGABRT 强杀进程，唤起系统级容灾
0x00221c74:  pop     {r4, r5, r6, pc}

; 开发者调试分支
0x00221c80:  ldr     r0, [pc, #0x18]    ; 加载日志: "[ANR Debug] ANR triggered but process preserved for GDB attachment.
"
0x00221c84:  bl      printf
0x00221c88:  pop     {r4, r5, r6, pc}   ; 直接返回，不杀进程
```

- **生产环境模式**：打印 `"Kill self after 1 second due to ANR"`，睡眠 1000ms 以保证 Tombstone 与 Syslog 完整落地，随后调用 `abort()` 触发进程自杀，由父守护进程 PMS 接管。
- **ANR 调试模式**：若系统环境变量中配置了 `anrdebug=enable`（可通过在 `/userdata/.testOptionsOn` 中写入配置激活），看门狗仅打印警告并主动保留现场，允许开发者通过 `gdbserver :1234 --attach <pid>` 附加调试。

---

### 2.4 PMS 外部进程级守护与双阶梯超时策略 (5s 软超时 / 7s 强杀)

除应用进程内部的 `JQuick::Watchdog` 外，操作系统底层的 PMS（Package & Process Management System，包与进程管理守护进程 `/usr/bin/pms`）在外部构筑了更具权威性的硬超时阶梯体系。

Falcon 主应用与 PMS 通过 UNIX 域套接字 `/tmp/miniapp_pms.sock` 维持双向心跳协议：
1. **应用正常态**：Falcon 事件循环每次完成一帧 UI 渲染或事件派发，向 Socket 发送 4 字节的 Keep-Alive 脉冲包。
2. **第一阶梯（5,000ms 软超时）**：若 PMS 连续 5 秒未收到心跳包，判定应用处于假死状态，执行 `kill(child_pid, SIGUSR2)`。
   - 正如第 1.3 节所述，`jquick_sig_handler` 捕获 `SIGUSR2` 后，**不会终止进程**，而是快速生成 `miniapp_anr_report_%02d` 诊断堆栈。
3. **第二阶梯（7,000ms 硬超时强杀）**：发送 `SIGUSR2` 后，PMS 开启 2000ms 的最后容忍窗口。若 2 秒后心跳仍未恢复，PMS 判定主线程陷入不可逆的内核级死锁或无限死循环，立即发送 `kill(child_pid, SIGKILL)` 物理回收进程。

#### 2.4.1 双阶梯机制的设计哲学

为什么不直接在 5 秒时强杀应用？
- **嵌入式 Flash 闪存 I/O 尖刺**：S7 Pro 的存储介质为 Raw NAND Flash。当后台进行 SQLite WAL 检查点合并或大日志滚动时，闪存写入可能会突发 1~2 秒的 I/O 停顿。
- **保护用户未保存状态**：若 5 秒即强杀，会导致偶发性卡顿被放大为闪退。通过 5 秒投递 `SIGUSR2`，系统不仅拿到了阻塞点诊断堆栈，还给予主线程 2 秒的喘息恢复机会。若 7 秒仍未响应，则证明彻底死锁，此时强杀无可挽回。

---

### 2.5 崩溃频次统计熔断与桌面 Launcher 容灾回滚机制

为了防止第三方小程序或系统组件因代码逻辑硬伤（如启动期必崩）导致设备陷入“启动 -> 崩溃 -> 重启 -> 崩溃”的死循环无限重启陷阱，PMS 设计了基于文件持久化的**启动健康门禁状态机**：

#### 2.5.1 启动统计文件结构 (`/userdata/miniapp/data/app_launch_stats.json`)

```json
{
  "8080262605498742": {
    "launch_count": 1,
    "consecutive_crashes": 0,
    "last_crash_timestamp": 1729580400,
    "status": "healthy"
  },
  "8080999900000001": {
    "launch_count": 3,
    "consecutive_crashes": 2,
    "last_crash_timestamp": 1729580450,
    "status": "disabled"
  }
}
```

#### 2.5.2 容灾决策树流程

```
              [应用拉起: pms_spawn_app(appid)]
                             │
            consecutive_crashes 计数器加 1
                             │
                   [应用平稳运行 10 秒?]
                   ├───────────────────────┐
                  (是)                    (否: 10s 内异常退出/被强杀)
                   ▼                       ▼
      consecutive_crashes 清零      consecutive_crashes >= 2 ?
      标记状态为 "healthy"                   ├───────────────────────┐
                                           (否)                    (是: 连续两次崩溃)
                                            ▼                       ▼
                                       允许重启一次           [触发系统级容灾熔断]
                                                             1. 标记 App 为 "disabled"
                                                             2. 清理 /tmp 与缓存数据
                                                             3. 强制回滚拉起系统桌面:
                                                                Launcher (8080222437664451)
                                                             4. 弹出全局 Toast 警告用户
```

通过这套机制，有道 S7 Pro 能够保证哪怕安装了恶意或极端缺陷的小程序，设备在经历最多两次闪退后也能安全稳定地停留在桌面 Launcher 界面，绝不会发生整机变砖。

---
## 3. QuickJS 异常传播与 JavaScript 运行时保护

### 3.1 跨层异常拦截链条全景拓扑

在基于 QuickJS 引擎的 MiniApp 框架中，一个在业务 JavaScript 代码中抛出的未捕获异常，需要跨越 JavaScript -> Vue 框架 -> Falcon C++ 引擎 -> 操作系统底层 四个抽象层级：

```
 [JavaScript 业务层]
   │  throw new Error("Null pointer exception in Page ViewModel");
   ▼
 [try...catch 结构] ─────────(未显式包裹)────────┐
                                                │
                                                ▼
 [Vue 框架层拦截]
   │  Vue.config.errorHandler(err, vm, info)
   ├────────────────────────────┬───────────────┘
  (若业务未注入 errorHandler)    (若拦截并阻断)
   │                            │
   ▼                            ▼
 [Falcon 引擎 C++ 胶水层]   [应用维持渲染并降级]
   │  MvvmEnv::callHandleError (0x0035d53c)
   ▼
 [QuickJS 核心运行时]
   │  JS_GetException(ctx) (0x00031c34)
   ├────────────────────────────────────────────┐
  (同步执行流程)                                (异步 Promise 链)
   ▼                                            ▼
 falcon::qjs_std_dump_error (0x0054bc04)    JS_SetHostPromiseRejectionTracker (0x00032740)
   │                                            │
   ▼                                            ▼
 YLog_print (Level 0x8, "(exception)...")    falcon::qjs_std_promise_rejection_tracker (0x0054a880)
   │                                            │
   └─────────────────────┬──────────────────────┘
                         │
                         ▼
        [检查 m_isFatalError 标记]
         ├─ true (首屏/框架级崩溃): 退出 Looper, 调用 exit(1) 触发 PMS
         └─ false (普通事件回调异常): 仅输出日志, 维持事件循环运行
```

#### 3.1.1 同步异常与异步异常的流向对比

| 异常触发场景 | 拦截入口 | 默认引擎动作 | 是否导致进程退出 | 业务自愈建议 |
| :--- | :--- | :--- | :--- | :--- |
| **Vue 生命周期 / 渲染函数** | `Vue.config.errorHandler` | 调用 `MvvmEnv::callHandleError` 打印堆栈 | **否** (维持 DOM，局部空白) | 设置 `vm.hasError = true` 展示兜底降级 UI |
| **页面首屏挂载期崩溃** | `app.$mount()` | 触发 `m_isFatalError = true` | **是** (调用 `exit(1)` 退出) | 异步分步初始化非首屏必须资源 |
| **异步定时器 (`setTimeout`)** | QuickJS 任务队列 | `qjs_std_dump_error` 输出至 syslog | **否** (抛出日志，继续调度) | 使用 `GlobalCrashGuard.safeCallback` 包装 |
| **未捕获 Promise Rejection** | `qjs_std_promise_rejection_tracker` | 输出 `[PromiseTracker]` 告警 | **否** (默认仅记录日志) | 监听 `unhandledrejection` 并 `preventDefault()` |
| **原生 C++ 扩展崩溃** | Linux 内核信号中断 | `jquick_sig_handler` 捕获 SIGSEGV | **是** (转储 Tombstone 后退出) | 严禁在 C 模块中裸解引用指针与堆越界 |

---

### 3.2 QuickJS 原生堆栈展开与 C++ 格式化实现 (`qjs_std_dump_error`)

当异常击穿前端所有防线到达 Native 引擎层时，Falcon 核心异常转储函数 `falcon::qjs_std_dump_error`（虚拟地址：`0x54bc04`）将被触发。

#### 3.2.1 逆向源码还原

```cpp
// libfalcon.so @ 0x54bc04: falcon::qjs_std_dump_error(JSContext *ctx) 逆向重构
void falcon::qjs_std_dump_error(JSContext *ctx) {
    JSValue exception_val = JS_GetException(ctx); // 提取异常对象，重置上下文错误状态
    bool is_error = JS_IsError(ctx, exception_val);
    
    // 1. 打印基础异常消息
    const char *err_msg = JS_ToCString(ctx, exception_val);
    if (err_msg) {
        YLog_print(0x8, "(exception): %s
", err_msg);
        JS_FreeCString(ctx, err_msg);
    }
    
    // 2. 深入解析 Error.prototype.stack
    if (is_error) {
        JSValue stack_val = JS_GetPropertyStr(ctx, exception_val, "stack");
        if (!JS_IsUndefined(stack_val)) {
            const char *stack_str = JS_ToCString(ctx, stack_val);
            if (stack_str) {
                // 逐行切分堆栈并通过 YLogger 格式化输出
                YLog_print(0x8, "(stack): %s
", stack_str);
                JS_FreeCString(ctx, stack_str);
            }
        }
        JS_FreeValue(ctx, stack_val);
    }
    
    // 3. 释放异常值本身引用计数，防止 QuickJS 内部 GC 泄漏
    JS_FreeValue(ctx, exception_val);
}
```

在 `libquickjs.so` 中，`qjs_dump_error`（偏移 `0x257ac`）通过类似逻辑将 QuickJS 虚拟机的字节码 PC 计数器映射回 JavaScript 源码文件名及行号（通过读取 QuickJS FunctionDef 中的 `debug_pc2line` 数据结构）。

#### 3.2.2 QuickJS `debug_pc2line` 寻址机制

QuickJS 采用紧凑的游程编码（Run-Length Encoding）存储字节码偏移到源码行号的映射：
- 每一条指令偏移由变长整数（LEB128）压缩。
- 当抛出异常时，虚拟机读取当前的 `cur_pc`，通过二分查找 `debug_pc2line` 数组解压出行号与列号。
- Falcon 引擎据此组装出形如 `at eval (app.js:142:15)` 的标准 V8 堆栈格式。

---

### 3.3 未捕获 Promise 拒绝追踪 (`JS_SetHostPromiseRejectionTracker`)

在现代化异步开发中，`Promise.reject()` 若缺少 `.catch()` 捕获，不会触发常规的 `try...catch` 分支。QuickJS 提供了宿主跟踪机制接口 `JS_SetHostPromiseRejectionTracker`（在 `libquickjs.so` 偏移 `0x32740`）。

Falcon 在启动 QuickJS 运行时实例时，注入了专属追踪器：
```cpp
// QuickJS 宿主 Promise 跟踪回调原型
typedef void JSHostPromiseRejectionTracker(
    JSContext *ctx,
    JSValueConst promise,
    JSValueConst reason,
    JS_BOOL is_handled,
    void *opaque
);

// libfalcon.so @ 0x54a880: falcon::qjs_std_promise_rejection_tracker
void falcon::qjs_std_promise_rejection_tracker(
    JSContext *ctx,
    JSValueConst promise,
    JSValueConst reason,
    JS_BOOL is_handled,
    void *opaque
) {
    if (!is_handled) {
        // 未捕获的 Promise 拒绝事件
        const char *reason_str = JS_ToCString(ctx, reason);
        YLog_print(0x8, "[PromiseTracker] Unhandled Promise Rejection trapped: %s
", 
                   reason_str ? reason_str : "Unknown Reason");
        if (reason_str) {
            JS_FreeCString(ctx, reason_str);
        }
        
        // 自动提取 Promise 拒绝原因中的 stack 属性
        if (JS_IsError(ctx, reason)) {
            JSValue stack = JS_GetPropertyStr(ctx, reason, "stack");
            const char *stack_str = JS_ToCString(ctx, stack);
            if (stack_str) {
                YLog_print(0x8, "[PromiseTracker] Rejection Stack: %s
", stack_str);
                JS_FreeCString(ctx, stack_str);
            }
            JS_FreeValue(ctx, stack);
        }
    } else {
        // 该 Promise 在稍后被补挂了 .catch() 处理器，撤销告警
        YLog_print(0x40, "[PromiseTracker] Promise Rejection was later handled.
");
    }
}
```

---

### 3.4 QuickJS 内存压力治理、GC 回收机制与堆内存防护

有道词典笔 S7 Pro 仅配备受限的 RAM 内存。当多个应用切换或大字典数据加载时，QuickJS 运行时的内存使用极易触顶。

#### 3.4.1 QuickJS 垃圾回收双核模型

1. **实时引用计数 (Reference Counting)**：
   - 所有的 `JSValue` 均包含头部的引用计数器。当 `JS_FreeValue` 使计数器归零时，内存立即就地释放。
   - 优点：内存回收零延迟，无 CPU 停顿（No Stop-The-World）。
2. **周期性环状依赖消除 (Cycle Removal GC)**：
   - 当 JavaScript 对象出现相互引用（例如闭包捕获了包含自身引用的 DOM/ViewModel 节点）时，引用计数永远无法归零。
   - Falcon 在主事件循环中定期调用 `JS_RunGC(JSRuntime *rt)`，扫描并解开对象引用孤岛。

#### 3.4.2 堆配额限制与 OOM 防御

在初始化 JSRuntime 时，Falcon 调用 `JS_SetMemoryLimit(rt, limit)`，为单个 MiniApp 设置了严格的虚拟内存配额（通常为 **32MB ~ 48MB**）：
- 当内存申请超过限额时，QuickJS 内部的 `js_malloc` 直接返回 `NULL`。
- 随后 QuickJS 会主动抛出内部的 Out-Of-Memory 异常。
- 若开发者在前端未做内存分页与图片释放，导致大量 `HTMLImageElement` 或大 JSON 对象驻留堆中，引擎将触发 `JS_ThrowOutOfMemory(ctx)`。
- **最佳实践防护**：在页面 `onHide` 与 `onUnload` 生命周期中，开发者必须主动解除全局事件监听（`$falcon.off`）、停止音频录音/播放实例、并将大数组引用置为 `null`。

---
## 4. 系统日志管理架构 (LogManager)

### 4.1 控制台标准输出劫持 (`falcon::installJSConsole`)

在 QuickJS 环境中，开发者熟悉的 `console.log`、`console.error` 并不是 JavaScript 原生语言标准的一部分，而是由宿主环境注入的。

#### 4.1.1 控制台安装与重定向实现

在 `/usr/lib/libfalcon.so` 的 `0x54d8f4` 处，函数 `falcon::installJSConsole(JSContext *ctx)` 创建了全局 `console` 对象，并通过 JQ 桥接库将其方法映射至内部统一派发器 `falcon::js_console_log`（虚拟地址：`0x54a700`）：

```cpp
// libfalcon.so: 控制台级别派发掩码定义
enum FalconLogLevel {
    LOG_LEVEL_DEBUG = 0x80, // 128: 调试级别
    LOG_LEVEL_LOG   = 0x40, // 64:  常规日志
    LOG_LEVEL_INFO  = 0x20, // 32:  信息提示
    LOG_LEVEL_WARN  = 0x10, // 16:  警告事件
    LOG_LEVEL_ERROR = 0x08  // 8:   严重错误
};

// 格式化输出模版映射表
static const char* kConsoleFormatTemplates[] = {
    "(console(%s).debug.%d): %s\n",
    "(console(%s).log.%d): %s\n",
    "(console(%s).info.%d): %s\n",
    "(console(%s).warn.%d): %s\n",
    "(console(%s).error.%d): %s\n"
};
```

当开发者执行 `console.log("Hello", 123)` 时：
1. 派发器提取当前活跃的小程序 AppID（例如 `"8080262605498742"`）。
2. 依次序列化传入的每个参数为字符串。
3. 按照模板注入 AppID 与参数索引序号 `%d`。
4. 调用底层 `YLogger::ylog_print(level, fmt, ...)`。
5. 数据同时被管道重定向输出至嵌入式系统的 Linux 内核环形缓冲区（RingBuffer）以及控制台 `/dev/console`。

#### 4.1.2 动态日志过滤与掩码控制

系统全局日志输出受控于 `/etc/miniapp/resources/env.json` 与 `/userdata/.testOptionsOn` 中的 `logLevel` 字段：
- **生产发布固件**：掩码通常收敛至 `0x18`（仅输出 `WARN` 与 `ERROR`），以降低磁盘 I/O 开销与 CPU 占用。
- **开发测试固件**：掩码开启为 `0xF8`（全量放行 `DEBUG`、`LOG`、`INFO`、`WARN`、`ERROR`）。

---

### 4.2 原生 C 模块 `logmanager` (`JSLogManagerProxy`) 9 大 API 详解

为了满足 MiniApp 进行高性能离线日志写入、用户行为埋点与性能诊断的需求，系统在 `/usr/lib/libjsapi_export_core.so` 偏移 `0x901a4` 处向 QuickJS 暴露了原生内置模块 `logmanager`。

```cpp
// libjsapi_export_core.so @ 0x901a4
void logmanager_module_init_jsapis(JSContext *ctx, JSValue ns) {
    JQFunctionTemplate *tmpl = JQFunctionTemplate::New(ctx, "LogManager", JSLogManagerProxy::Constructor);
    tmpl->SetProtoMethod("writeToFile",        JSLogManagerProxy::writeToFile);
    tmpl->SetProtoMethod("writeErrorLog",      JSLogManagerProxy::writeErrorLog);
    tmpl->SetProtoMethod("logSpy",             JSLogManagerProxy::logSpy);
    tmpl->SetProtoMethod("uploadStartupLog",    JSLogManagerProxy::uploadStartupLog);
    tmpl->SetProtoMethod("getCurAppIdPageName", JSLogManagerProxy::getCurAppIdPageName);
    tmpl->SetProtoMethod("addClock",           JSLogManagerProxy::addClock);
    tmpl->SetProtoMethod("addClockToPrint",    JSLogManagerProxy::addClockToPrint);
    tmpl->SetProtoMethod("printReport",        JSLogManagerProxy::printReport);
    tmpl->SetProtoMethod("clearReport",        JSLogManagerProxy::clearReport);
    tmpl->Export(ns, "LogManager");
}
```

#### 4.2.1 9 大 API 汇编调用与参数契约完全字典

```
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                 JSLogManagerProxy API 接口全景表                               │
├──────────────────────┬─────────┬──────────────┬────────────────────────────────────────────────┤
│ 方法签名             │ 参数    │ 原生虚地址   │ 底层行为与业务影响                             │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ writeToFile          │ tag,    │ 0x0008fca4   │ 提取 tag 与 content 字符串，调用底层           │
│                      │ content │              │ YLogManagerModulePrivate::writeToFile 写入闪存 │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ writeErrorLog        │ content │ 0x000900e4   │ 强行以 ERROR 级别直写 /userdata/applog/，      │
│                      │         │              │ 附带毫秒时间戳与当前活跃 AppID 上下文          │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ logSpy               │ event,  │ 0x0008fe04   │ 写入高频用户埋点缓冲区，排队等待遥测后台线程   │
│                      │ data    │              │ 批量 gzip 压缩并上传有道大数据平台             │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ uploadStartupLog     │ 无      │ 0x0008f988   │ 触发应用启动全链路耗时报告异步打包上报         │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ getCurAppIdPageName  │ 无      │ 0x0008fbb0   │ 查询前台活动视口，返回 "{appId}/{pageRoute}"   │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ addClock             │ name    │ 0x0008ff64   │ 在基准性能测试哈希表中记录当前微秒时间戳       │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ addClockToPrint      │ name    │ 0x00090024   │ 记录时间戳并立即输出与上一 Clock 的耗时差值    │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ printReport          │ 无      │ 0x0008f998   │ 将内部所有时钟节点格式化为 ASCII 表格打印      │
├──────────────────────┼─────────┼──────────────┼────────────────────────────────────────────────┤
│ clearReport          │ 无      │ 0x0008f9a8   │ 清空所有基准时钟节点，释放内存                 │
└──────────────────────┴─────────┴──────────────┴────────────────────────────────────────────────┘
```

#### 4.2.2 核心方法的深入剖析

1. **`writeToFile(tag: string, content: string)`**：
   - 入参校验：必须传入非空字符串。
   - 内部派发至 `YDALAPI::Internal::YLogManagerModulePrivate::writeToFile`（虚拟地址：`0xc662c`）。
   - 数据格式：`"[%Y-%m-%d %H:%M:%S.%03d] [%s] %s
"`。
   - 目标路径：`/userdata/applog/app_<appid>_<date>.log`。

2. **`logSpy(event: string, data: any)`**：
   - 遥测埋点专用 API。数据先进入内存环形缓冲队列（RingBuffer Queue）。
   - 若 WiFi 处于断开状态，数据被持久化写入磁盘文件 `/userdata/DictPenData/.logSpyCache_<appid>`。
   - 当网络重新连接，自动由后台上报线程恢复传输。

3. **`addClock` 与 `addClockToPrint` 性能探针对**：
   - 内部维护以 `clockName` 为键的 `std::map<std::string, uint64_t>` 哈希表。
   - `addClockToPrint` 会打印类似于：`[ClockProfiler] (Step: ImageProcessFinish) Elapsed: 42.15 ms` 的精准耗时度量，是优化冷启动和查词响应速度的核心工具。

---

### 4.3 `YLogManagerModulePrivate` 底层流向与压缩流水线

在 `/usr/lib/libyddal_business_core.so` 中，`YLogManagerModulePrivate` 承担了真正的文件 I/O、磁盘保护与打包工作：

#### 4.3.1 日志打包与上传算法 (`zipUploadDir` @ `0xc42cc`)

当日志累积达到阈值或触发上报事件时，底层调用 `zipUploadDir`：
1. 锁定日志互斥量 `m_logMutex`，防止多线程写入竞态破坏。
2. 遍历 `/userdata/applog/` 目录，筛选当前应用所属的 `.log` 文件。
3. 创建临时归档压缩包：`/tmp/applog_upload_<timestamp>.zip`。
4. 调用 MiniZip / Zlib 算法库对文本日志进行 Deflate 流式高压缩比打包（压缩率通常可达 80%~90%，极大节省 WiFi 上传流量与功耗）。
5. 压缩完成后重命名为待发送实体，唤起异步上传传输线程。

#### 4.3.2 耗时度量与生命周期回调绑定

在 `libyddal_business_core.so` 中，还存在两个关键的生命周期耗时探针：
- `appUseTimeUploadCallback`（`0xc526c`）：在小程序退到后台（`onHide`）或退出（`onUnload`）时被回调，统计本次前台活跃持续总时间并上报。
- `pageCreateFinishCallback`（`0xc5e5c`）：在首屏 DOM 挂载就绪后回调，写入 `/tmp/MiniappCreateFinishFlag`，通知外部看门狗首屏渲染成功。

---

### 4.4 守护进程 `/usr/bin/log_manager` 存储规划与云端遥测网关

#### 4.4.1 文件系统存储规划与限额机制

为避免日志写满 NAND Flash 导致系统启动只读挂载（Read-Only Mount），词典笔系统实施分层规划：

```
/userdata/
 ├── applog/                         <-- 应用业务日志 (硬上限: 20MB)
 │    ├── app_80802626_20261022.log
 │    └── app_80802626_20261022.log.1
 ├── log/                            <-- 系统服务日志 (硬上限: 10MB)
 │    ├── pms.log
 │    ├── audio_server.log
 │    └── wpa_supplicant.log
 ├── DictPenData/
 │    └── .logSpyCache_              <-- 埋点未上传本地持久化缓存
 └── miniapp/data/crash_reports/     <-- 崩溃与 ANR 归档区 (硬上限: 200KB)
      ├── miniapp_crash_report_00 ~ 09
      └── miniapp_anr_report_00 ~ 09
```

- **单文件切分阈值**：单个 `.log` 文件达到 **2MB** 时，自动触发滚动命名（追加 `.1`, `.2` 等后缀）。
- **总配额自动修剪**：当 `/userdata/applog/` 总体积接近 **20MB** 时，守护进程自动触发 LRU 裁剪算法，删除修改时间最古老的 `.log` 文件。

#### 4.4.2 云端遥测上报协议 (`YLogSpy`)

在 `libyddal_base_core.so` 偏移 `0xa7d24` 处实现的 `YDALBASEAPI::YLogSpy` 负责将设备诊断遥测数据上报至网易有道云端大数据网关。

- **云端网关接口 URL**: `http://sdk-log.youdao.com/gz-log/dict_pen`
- **传输层协议**: HTTP POST（基于 CPR / Libcurl 客户端）
- **数据压缩**: Gzip 格式（`Content-Encoding: gzip`）
- **报文 Payload 契约**:
```json
{
  "header": {
    "device_model": "YDPS7-2",
    "board": "Y08_CV1813_V0",
    "soc": "CV1813H",
    "os_version": "5.10.4-cvitek",
    "firmware": "4.22.0",
    "sn": "YD2026102200001",
    "user_id": "yd_user_998244353",
    "timestamp": 1729580400123
  },
  "payload": {
    "event_type": "app_crash_telemetry",
    "app_id": "8080262605498742",
    "tombstone": "*** CRASH REPORT ***\nPID: 1420\nSignal: 11 (SIGSEGV)...",
    "breadcrumbs": [
      {"t": 1729580398, "act": "page_open", "page": "pages/index/index"},
      {"t": 1729580399, "act": "touch_start", "x": 120, "y": 340}
    ]
  }
}
```

---
## 5. 硬件看门狗 (/dev/watchdog) 联动

### 5.1 SoC CV1813H 硬件看门狗 (WDT) 架构与 Linux ioctl 接口

在工业级嵌入式系统中，软件看门狗（如 PMS 或 Watchdog 线程）本身也是运行在操作系统调度器上的软件逻辑。若遇到**Linux 内核 Panic**、**中断风暴 (Interrupt Storm)**、**总线锁死**或**CPU 硬件死锁**，所有软件看门狗都将彻底失效。

为了提供终极底线保障，Cvitek CV1813H SoC 片上集成了物理硬件定时器单元（Hardware Watchdog Timer，WDT）。

#### 5.1.1 内核驱动与设备节点

- 设备节点：`/dev/watchdog`
- 设备类型：字符设备（Character Device，主设备号 10，次设备号 130）
- 驱动源码树：`drivers/watchdog/cvitek_wdt.c`

#### 5.1.2 Linux 标准 Watchdog API 控制契约

通过标准 `sys/ioctl.h` 与 `linux/watchdog.h`，用户态可与硬件看门狗交互：

```c
#include <linux/watchdog.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>

// 常用 ioctl 命令字定义
// WDIOC_SETTIMEOUT  : 设置硬件超时秒数 (_IOWR('W', 6, int))
// WDIOC_GETTIMEOUT  : 获取当前超时秒数 (_IOR('W', 7, int))
// WDIOC_KEEPALIVE   : 核心喂狗指令   (_IOR('W', 5, int))
// WDIOC_SETOPTIONS  : 启停看门狗     (_IOWR('W', 4, int))

int fd = open("/dev/watchdog", O_WRONLY);
int timeout = 15; // 设置硬件超时为 15 秒
ioctl(fd, WDIOC_SETTIMEOUT, &timeout);

// 周期性喂狗操作
ioctl(fd, WDIOC_KEEPALIVE, 0);
```

**魔术字符安全关闭机制 (Magic Close)**：
若应用想要正常关闭硬件看门狗而不触发重启，必须在关闭 `fd` 前向节点写入特定字符 `'V'`（ASCII `0x56`）。若未写入 `'V'` 直接调用 `close(fd)`，内核驱动会认为喂狗进程意外暴毙，立刻在超时到达后触发整机硬复位！

---

### 5.2 全链路穿透体系：从 MiniApp JS 到内核 WDT

在有道 S7 Pro 中，为了保证前台关键应用（如高强度全屏扫描查词）能够持续向硬件证明整机健康，架构打通了一条纵跨六层的**喂狗穿透流水线**：

```
 [1. MiniApp 前端 JavaScript]
      global.feedWatchdog();
         │
         ▼
 [2. QuickJS 脚本绑定层 (libjsapi_export_core.so)]
      JSGlobalProxy::feedWatchdog(const JQFunctionCallbackInfo& info) (0x0006a110)
      JSystemInfoProxy::feedWatchdog(const JQFunctionCallbackInfo& info) (0x000aef00)
         │
         ▼
 [3. 业务逻辑核心层 (libyddal_business_core.so)]
      YDALAPI::YSystemInfoModule::feedWatchdog() (0x001073bc)
      YDALAPI::Internal::YSystemInfoModulePrivate::feedWatchdog() (0x001072f8)
         │
         ▼
 [4. 驱动适配抽象层 (libyddal_adapter_core.so)]
      YADAPTERAPI::YSystemInfoAdapter::feedWatchdog() (0x00045f80)
      YADAPTERAPI::Internal::YSystemInfoAdapterPrivate::feedWatchdog() (0x00045eb4)
         │
         ▼
 [5. HAL 硬件抽象实现 (libyddal_adapter.so / Linux System Calls)]
      open("/dev/watchdog", O_WRONLY);
      ioctl(fd, WDIOC_KEEPALIVE, 0);
         │
         ▼
 [6. Linux 内核驱动与 CV1813H SoC 硬件]
      cvitek_wdt_ping() -> 写寄存器重置片上硬件硬件计数器
```

#### 5.2.1 适配层汇编逆向证实 (`YSystemInfoAdapterPrivate::feedWatchdog`)

在 `libyddal_adapter_core.so` 的 `0x45eb4` 处：
```arm
0x00045eb4:  push    {r4, r5, r6, lr}
0x00045eb8:  mov     r5, r0
0x00045ec4:  bl      YLogger::Instance()
...
0x00045f18:  bl      YLogger::LogStream()
; 打印系统跟踪标记: "===>>>> YSystemInfoAdapterPrivate::feedWatchdog <<<<=== called"
0x00045f48:  ldr     r3, [r5, #0x18]    ; 加载底层 HAL 适配器句柄 m_hal_adapter
0x00045f4c:  ldr     r3, [r3, #0x28]    ; 获取虚表偏移 0x28 (feedWatchdog 硬件实现入口)
0x00045f50:  add     sp, sp, #0x38
0x00045f54:  pop     {r4, r5, r6, lr}
0x00045f58:  bx      r3                 ; 跳转进入底层内核 ioctl 喂狗驱动
```

---

### 5.3 喂狗周期策略与软硬件三层看门狗阶梯联动模型

系统建立了三道环环相扣的安全防御阶梯：

```
防御层级     守护组件            检测粒度与超时窗口          容灾与自愈动作
═══════════════════════════════════════════════════════════════════════════════════════
第一道防线   Falcon Watchdog     UI 主事件循环 Looper       输出 ANR 堆栈，自杀退出，
            ("JQuick-Watchdog")  超时阈值: 30 秒            触发 PMS 外部调度
───────────────────────────────────────────────────────────────────────────────────
第二道防线   PMS 进程守护        UNIX Socket 心跳包         软超时 5s 发送 SIGUSR2 转储
            (/usr/bin/pms)       超时窗口: 5秒 / 7秒        硬超时 7s 发送 SIGKILL 强杀
───────────────────────────────────────────────────────────────────────────────────
第三道防线   SoC 硬件看门狗      硬件片上递减计数器         计数器归零直接拉低复位引脚
            (/dev/watchdog)      超时阈值: 15 秒 (固定)     整机硬件级冷重启 (Hard Reset)
```

**调度平衡最佳实践**：
- 前台应用主心跳投递周期应设定为 **3,000ms ~ 4,000ms**。
- 该周期远小于第一道防线的 30s 与第二道防线的 5s/7s，能够在任何单点异常发生时，逐级留出充足的系统转储与自愈时间窗口。

---

### 5.4 系统死锁、内核崩溃与整机硬件冷复位 (Hard Reset) 时序

当发生最为严重的系统死锁（例如内核内存踩踏触发 Kernel Panic，或者驱动持锁死循环）：
1. **0ms**：发生内核级挂起，中断被屏蔽，用户态所有进程（包括 PMS、Falcon、Watchdog 线程）全部彻底冻结。
2. **0ms ~ 15000ms**：CV1813H 片上硬件看门狗计时器以片内 24MHz 晶振分频后的固定时钟源持续递减，无法被重置。
3. **15000ms (超时溢出)**：看门狗计数器下溢归零，触发内部 `WDT_RST` 硬件事件。
4. **15005ms**：SoC 硬件看门狗控制器向电源管理芯片（PMIC）或片上 Reset Controller 投递全局复位脉冲。
5. **15010ms**：CPU 核心执行强制硬件冷复位，程序计数器（PC）被硬重置指向 Mask ROM 中的 Bootloader 启动地址 `0x00000000`，整机进入重新引导上电开机流程。

#### 5.4.1 内核级 Panic 自动重启配置

在 S7 Pro 系统初始化脚本 `/etc/init.d/rcS` 中，配置了 Linux 内核在 Panic 时的自动复位参数：
```bash
# 若发生内核 Panic，等待 5 秒后触发内核机器复位 (kernel restart)
echo 5 > /proc/sys/kernel/panic
```
当出现驱动级 Bug 时，内核打印 oops 日志至串口控制台，并在 5 秒后主动调用硬件复位逻辑重启系统，确保设备不会长久黑屏假死。

---
## 6. 开发者生产级防崩套件与调试诊断指南

### 6.1 生产级防崩卫士全量源码 (`GlobalCrashGuard.ts`)

以下是在生产级 MiniApp 项目中必须集成的全局防崩与日志监控完整源码。该模块实现了：
1. 原生 C 模块 `logmanager` 穿透与降级保护；
2. Vue 全局错误边界（`errorHandler`）；
3. 全局 Promise Unhandled Rejection 拦截；
4. 异步定时器与回调异常安全包装；
5. 定期软件看门狗喂狗。

```typescript
/**
 * 有道词典笔 S7 Pro 生产级全局防崩与日志保护套件
 * 文件名: GlobalCrashGuard.ts
 * 平台约束: CV1813H ARM32 QuickJS / Falcon Runtime
 */

export interface NativeLogManager {
  writeToFile(tag: string, content: string): void;
  writeErrorLog(content: string): void;
  logSpy(event: string, data: any): void;
  uploadStartupLog(): void;
  getCurAppIdPageName(): string;
  addClock(name: string): void;
  addClockToPrint(name: string): void;
  printReport(): void;
  clearReport(): void;
}

export interface TelemetryPayload {
  [key: string]: any;
}

export class GlobalCrashGuard {
  private static instance: GlobalCrashGuard;
  private nativeLog: NativeLogManager | null = null;
  private watchdogTimer: any = null;
  private isInitialized: boolean = false;
  private breadcrumbBuffer: Array<{ timestamp: number; action: string; details: any }> = [];
  private readonly MAX_BREADCRUMBS: number = 20;

  private constructor() {
    this.initNativeBridge();
  }

  public static getInstance(): GlobalCrashGuard {
    if (!GlobalCrashGuard.instance) {
      GlobalCrashGuard.instance = new GlobalCrashGuard();
    }
    return GlobalCrashGuard.instance;
  }

  /**
   * 初始化 Native 原生 C 模块桥接
   */
  private initNativeBridge(): void {
    try {
      // 穿透加载 libjsapi_export_core.so 导出的原生模块
      const lm = typeof require === 'function' ? require('logmanager') : null;
      if (lm && lm.LogManager) {
        this.nativeLog = new lm.LogManager();
        this.logInfo('CrashGuard', 'Successfully bound to Native LogManager module.');
      } else {
        this.logWarn('CrashGuard', 'Native LogManager not found. Falling back to console.');
      }
    } catch (e) {
      this.nativeLog = null;
      console.warn('[CrashGuard] Native LogManager require failed:', e);
    }
  }

  /**
   * 安装全局守护网关
   */
  public install(Vue?: any): void {
    if (this.isInitialized) return;
    this.isInitialized = true;

    // 1. 安装 Vue 框架错误边界
    if (Vue) {
      this.setupVueErrorHandler(Vue);
    }

    // 2. 安装 Promise 未捕获异常拦截
    this.setupPromiseRejectionHandler();

    // 3. 安装软硬件看门狗喂狗心跳 (每 3 秒调度一次)
    this.startWatchdogHeartbeat(3000);

    this.logInfo('CrashGuard', 'GlobalCrashGuard fully initialized and armed.');
  }

  /**
   * 记录用户交互行为面包屑 (Breadcrumbs) 用于崩溃现场回溯
   */
  public addBreadcrumb(action: string, details?: any): void {
    const entry = {
      timestamp: Date.now(),
      action,
      details: details || null
    };
    this.breadcrumbBuffer.push(entry);
    if (this.breadcrumbBuffer.length > this.MAX_BREADCRUMBS) {
      this.breadcrumbBuffer.shift();
    }
  }

  /**
   * 拦截 Vue 组件内部渲染与生命周期错误
   */
  private setupVueErrorHandler(Vue: any): void {
    const originalHandler = Vue.config.errorHandler;

    Vue.config.errorHandler = (err: Error, vm: any, info: string) => {
      const compName = vm?.$options?.name || vm?.$options?._componentTag || 'AnonymousComponent';
      const errMsg = `[VueCrash] Error in <${compName}> during (${info}): ${err?.message || err}`;
      const errStack = err?.stack || 'No Stack Available';

      // 记录至错误日志
      this.logFatal('VueBoundary', `${errMsg}\nStack: ${errStack}`);

      // 上报行为埋点
      this.logTelemetry('vue_lifecycle_crash', {
        component: compName,
        lifecycle: info,
        message: err?.message,
        stack: errStack,
        breadcrumbs: [...this.breadcrumbBuffer]
      });

      // 页面级降级处理，阻断异常击穿至引擎导致进程 abort
      if (vm && vm.$data) {
        vm.$data.__hasRenderError__ = true;
        vm.$data.__renderErrorMsg__ = '组件加载异常，已自动保护';
      }

      // 若有上一级错误处理器则传递
      if (typeof originalHandler === 'function') {
        originalHandler.call(Vue, err, vm, info);
      }
    };
  }

  /**
   * 拦截未处理的 Promise Rejection
   */
  private setupPromiseRejectionHandler(): void {
    const g: any = typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : {});

    // 标准浏览器/微前端事件
    if (typeof g.addEventListener === 'function') {
      g.addEventListener('unhandledrejection', (event: any) => {
        this.handlePromiseFailure(event?.reason);
        if (event && typeof event.preventDefault === 'function') {
          event.preventDefault(); // 阻止向上击穿
        }
      });
    }

    // Node/QuickJS 宿主钩子
    if (g.onunhandledrejection !== undefined) {
      g.onunhandledrejection = (event: any) => {
        this.handlePromiseFailure(event?.reason || event);
        return true;
      };
    }
  }

  private handlePromiseFailure(reason: any): void {
    const msg = reason instanceof Error ? reason.message : JSON.stringify(reason);
    const stack = reason instanceof Error ? reason.stack : 'N/A';
    this.logFatal('PromiseRejection', `Unhandled Rejection: ${msg}\nStack: ${stack}`);
    this.logTelemetry('unhandled_promise_rejection', { 
      message: msg, 
      stack,
      breadcrumbs: [...this.breadcrumbBuffer]
    });
  }

  /**
   * 安全包装异步回调函数，防止异步抛错击穿事件循环
   */
  public safeCallback<T extends (...args: any[]) => any>(fn: T, contextTag: string = 'AsyncAction'): T {
    const self = this;
    return function (this: any, ...args: any[]) {
      try {
        return fn.apply(this, args);
      } catch (err: any) {
        self.logFatal('SafeCallback', `Fatal crash trapped in async callback [${contextTag}]: ${err?.message}`, err);
        return undefined;
      }
    } as T;
  }

  /**
   * 启动看门狗定时心跳投递
   */
  private startWatchdogHeartbeat(intervalMs: number): void {
    if (this.watchdogTimer) clearInterval(this.watchdogTimer);

    this.watchdogTimer = setInterval(() => {
      try {
        const g: any = typeof window !== 'undefined' ? window : (typeof global !== 'undefined' ? global : {});
        // 调用 QuickJS 穿透注入的原生喂狗接口
        if (typeof g.feedWatchdog === 'function') {
          g.feedWatchdog();
        } else if (g.$falcon && typeof g.$falcon.feedWatchdog === 'function') {
          g.$falcon.feedWatchdog();
        }
      } catch (e) {
        console.error('[CrashGuard] Failed to feed watchdog:', e);
      }
    }, intervalMs);
  }

  public logInfo(tag: string, msg: string): void {
    const logStr = `[${tag}] ${msg}`;
    console.info(logStr);
    if (this.nativeLog) {
      this.nativeLog.writeToFile(tag, msg);
    }
  }

  public logWarn(tag: string, msg: string): void {
    const logStr = `[${tag}] ${msg}`;
    console.warn(logStr);
    if (this.nativeLog) {
      this.nativeLog.writeToFile(tag, `WARN: ${msg}`);
    }
  }

  public logFatal(tag: string, msg: string, err?: any): void {
    const full = `[${tag}] FATAL: ${msg} ${err ? (err.stack || JSON.stringify(err)) : ''}`;
    console.error(full);
    if (this.nativeLog) {
      this.nativeLog.writeErrorLog(full);
      this.nativeLog.writeToFile('FATAL_CRASH', full);
    }
  }

  public logTelemetry(event: string, data: any): void {
    if (this.nativeLog) {
      try {
        this.nativeLog.logSpy(event, JSON.stringify(data));
      } catch (_) {}
    }
  }

  public destroy(): void {
    if (this.watchdogTimer) {
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = null;
    }
    this.isInitialized = false;
  }
}
```

---

### 6.2 Minidump 与 Tombstone 符号还原实战指南

当生产环境或自动化压力测试捕获到底层崩溃转储时，开发者必须利用工具链进行堆栈还原与代码行定位。

#### 6.2.1 Tombstone 堆栈解析实操

系统生成的 `/userdata/miniapp/data/crash_reports/miniapp_crash_report_00` 包含如下内容：
```
*** CRASH REPORT ***
PID: 1420
Signal: 11 (SIGSEGV), Code: 1 (SEGV_MAPERR), Fault Address: 0x00000004
Backtrace:
  #00 pc 0022ab54  /usr/lib/libfalcon.so
  #01 pc 0008fca4  /usr/lib/libjsapi_export_core.so
  #02 pc 000c662c  /usr/lib/libyddal_business_core.so (_ZN7YDALAPI8Internal22YLogManagerModulePrivate11writeToFile...)
  #03 pc 00031c34  /usr/lib/libquickjs.so (JS_GetException+0x14)
```

**符号解析操作命令**：
利用针对 ARM 架构的 `addr2line` 工具，传入未裁剪（Unstripped）且包含 DWARF 调试符号的动态库：

```bash
# 还原 libyddal_business_core.so 中的崩溃偏移 0x000c662c
arm-linux-gnueabihf-addr2line -C -f -e /symbols/libyddal_business_core.so 0x000c662c

# 终端输出还原结果:
# YDALAPI::Internal::YLogManagerModulePrivate::writeToFile(std::string const&, std::string const&)
# /home/builder/youdao_repo/yddal/modules/logmanager/YLogManagerModulePrivate.cpp:342
```

#### 6.2.2 Google Breakpad Minidump 堆栈回溯工具

若生成了 Google Breakpad 的 `.dmp` 二进制文件：
1. 提取动态库符号文件（生成 `.sym`）：
   ```bash
   dump_syms /symbols/libfalcon.so > libfalcon.so.sym
   mkdir -p ./symbols/libfalcon.so/<BUILD_ID>/
   mv libfalcon.so.sym ./symbols/libfalcon.so/<BUILD_ID>/
   ```
2. 执行堆栈回溯分析：
   ```bash
   minidump_stackwalk /userdata/miniapp/data/crash.dmp ./symbols > crash_analysis.txt
   ```
3. 查看输出报告中的 `Thread 0 (crashed)` 部分，即可获取包括局部变量指针、调用栈参数以及寄存器 `r0-r15` 的全景镜像。

#### 6.2.3 基于 GDB Server 的在线现场诊断

若开发板开启了 `anrdebug=enable`：
```bash
# 设备端挂载调试进程
gdbserver :1234 --attach 1420

# 宿主开发机连接并调试
arm-linux-gnueabihf-gdb /symbols/libfalcon.so
(gdb) target remote 192.168.1.101:1234
(gdb) thread apply all bt
(gdb) info registers
```

---

### 6.3 生产环境典型崩溃与死锁排障剖析 (Gotchas)

#### 6.3.1 案例 1：QuickJS 闭包循环引用导致 OOM 崩溃
- **故障现象**：MiniApp 运行 30 分钟后，界面突然闪退，Tombstone 显示 `JS_ThrowOutOfMemory` 随后进程 abort。
- **根因剖析**：页面组件在 `created` 生命周期中向全局事件中枢注册了监听器（如 `$bus.on('scan_result', this.onResult)`），而在页面销毁（`destroyed`）时忘记调用 `$bus.off`。`onResult` 闭包强引用了 Vue 实例 `this`，导致页面 ViewModel、整棵 Virtual DOM 树及关联的图像纹理无法被 QuickJS 引用计数释放，最终击穿 32MB 堆配额。
- **治理法则**：建立生命周期闭环，在 `destroyed` 钩子中成对销毁全部事件监听与 Timer。

#### 6.3.2 案例 2：Native C 扩展越界破坏内存 (SIGBUS / SIGSEGV)
- **故障现象**：调用 OCR 图像拼接模块后，稍后执行无关的 `console.log` 时偶发 `SIGSEGV`，崩溃点在 `malloc()` 内部。
- **根因剖析**：典型的堆踩踏（Heap Corruption）。C++ 模块在处理摄像头送来的 NV21 图像帧时，写入长度超过了预分配的缓冲区，破坏了 glibc malloc 堆块的元数据头部（Chunk Header）。
- **治理法则**：在编译 Native 模块时开启 `-fsanitize=address`（ASan）并在测试板上跑回归测试，彻底消除越界写入。

#### 6.3.3 案例 3：主线程同步执行耗时 I/O 触发 ANR 软强杀
- **故障现象**：用户在无网络状态下点击大文件导出，5 秒后界面冻结，随后弹出“应用无响应”并被 PMS 强制杀死回滚桌面。
- **根因剖析**：JavaScript 业务代码通过同步 RPC 调用了底层文件复制接口，底层阻塞在读取慢速 SD 卡/Flash 超过 5 秒，导致 Falcon 主线程 Looper 无法响应看门狗的 Ping 探测，被 PMS 认定为 ANR 并在 7 秒硬超时触发 `SIGKILL`。
- **治理法则**：所有耗时大于 50ms 的文件操作、加解密或网络通信必须通过多线程异步任务调度，主线程仅接收完成回调。

#### 6.3.4 案例 4：硬件看门狗超时导致的突发冷重启 (Reboot Gotcha)
- **故障现象**：词典笔在极少数弱网环境下连续查词时，屏幕瞬间熄灭，随后出现有道开机 Logo，整机发生硬重启。
- **根因剖析**：应用层虽然捕获了异常，但在死锁恢复逻辑中陷入了死循环，未向 `/dev/watchdog` 发送 `WDIOC_KEEPALIVE`。硬件 15 秒定时器超时溢出，CV1813H SoC 硬件复位引脚触发整机 Hard Reset。
- **治理法则**：合理利用 `GlobalCrashGuard.ts` 的独立心跳定时器，并在紧急清理函数中妥善释放外设资源。

---

## 7. 术语表与规范索引

| 缩略语 / 术语 | 英文全称 | 解释说明 |
| :--- | :--- | :--- |
| **SoC** | System on Chip | 片上系统，此处特指 Cvitek CV1813H |
| **PMS** | Package & Process Management System | 有道词典笔嵌入式 Linux 系统的包管理器与进程生命周期守护核心 |
| **YDDAL** | YouDao Device Abstraction Layer | 有道设备抽象层，统一封装 Linux 底层驱动、IPC 与核心业务模块 |
| **WDT** | Watchdog Timer | 硬件看门狗定时器，防止整机死锁的最后一道物理硬件屏障 |
| **ANR** | Application Not Responding | 应用程序无响应，UI 事件循环阻塞超时事件 |
| **QuickJS** | QuickJS Javascript Engine | Fabrice Bellard 主导开发的轻量嵌入式 JavaScript 解释引擎 |
| **Tombstone** | Tombstone File | 墓碑文件，记录进程死亡时刻调用栈、信号和寄存器状态的转储日志 |
| **CPR** | C++ Requests | 基于 Libcurl 封装的现代化 C++ HTTP 请求库 |

---

> **手册版本控制与归档记录**:
> - 2026-10-22: 初版 SDK 内部技术架构手册封版发布（基于 S7 Pro 固件 v4.22.0 全量二进制反汇编工程验证）。
