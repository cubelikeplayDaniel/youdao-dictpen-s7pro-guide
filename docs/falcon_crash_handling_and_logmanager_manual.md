# 有道词典笔 S7 Pro 异常崩溃处理、LogManager 诊断与 PMS 容灾恢复全景指南
## (Falcon Crash Handling, ANR Tombstones, LogManager Subsystem & PMS Auto-Recovery Architecture Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `libfalcon.so` (`installSignals`, `jquick_sig_handler`), `libjsapi_export_core.so` (`JSLogManagerProxy`), PMS Watchdog Daemon

---

## 目录索引

1. [原生 QuickJS C 模块 `logmanager` (`JSLogManagerProxy`) 架构深度解构](#1-原生-quickjs-c-模块-logmanager-jslogmanagerproxy-架构深度解构)
   - 1.1 [模块注册与原型绑定机制](#11-模块注册与原型绑定机制)
   - 1.2 [导出的 9 大原生 API 字典](#12-导出的-9-大原生-api-字典)
   - 1.3 [日志持久化存储层级结构与路径规范](#13-日志持久化存储层级结构与路径规范)
   - 1.4 [Falcon 控制台重定向机制 (`falcon::installJSConsole`)](#14-falcon-控制台重定向机制-falconinstalljsconsole)
2. [QuickJS 未捕获异常处理与 MVVM 错误边界传播](#2-quickjs-未捕获异常处理与-mvvm-错误边界传播)
   - 2.1 [原生异常提取与堆栈展开 (`falcon::qjs_std_dump_error`)](#21-原生异常提取与堆栈展开-falconqjs_std_dump_error)
   - 2.2 [MVVM 错误边界捕获 (`MvvmEnv::callHandleError`)](#22-mvvm-错误边界捕获-mvvmenvcallhandleerror)
3. [Linux POSIX 信号捕获、Tombstone 生成与崩溃轮转](#3-linux-posix-信号捕获tombstone-生成与崩溃轮转)
   - 3.1 [信号初始化 (`installSignals`)](#31-信号初始化-installsignals)
   - 3.2 [信号派发的三大分支状态机 (`jquick_sig_handler`)](#32-信号派发的三大分支状态机-jquick_sig_handler)
   - 3.3 [ANR Watchdog 诊断转储 (SIGUSR2, 10 槽位轮转)](#33-anr-watchdog-诊断转储-sigusr2-10-槽位轮转)
   - 3.4 [致命崩溃转储与 Core Dump (SIGSEGV, SIGBUS, SIGABRT)](#34-致命崩溃转储与-core-dump-sigsegv-sigbus-sigabrt)
4. [PMS 进程守护、心跳看门狗与自动容灾恢复机制](#4-pms-进程守护心跳看门狗与自动容灾恢复机制)
   - 4.1 [进程衍生与 IPC 监听拓扑 (`/tmp/miniapp_pms.sock`)](#41-进程衍生与-ipc-监听拓扑-tmpminiapp_pmssock)
   - 4.2 [5000ms 软超时与 7000ms 强杀阶梯策略](#42-5000ms-软超时与-7000ms-强杀阶梯策略)
   - 4.3 [防死锁与连续崩溃回滚桌面机制 (`app_launch_stats.json`)](#43-防死锁与连续崩溃回滚桌面机制-app_launch_statsjson)
5. [生产级自研 MiniApp 容灾监控与错误边界库实现](#5-生产级自研-miniapp-容灾监控与错误边界库实现)

---

## 1. 原生 QuickJS C 模块 `logmanager` (`JSLogManagerProxy`) 架构深度解构

### 1.1 模块注册与原型绑定机制

原生日志子系统实现于 `/usr/lib/libjsapi_export_core.so`，并在 QuickJS 运行时中通过 JQ 框架在偏移 `0x901a4` 处完成模块注册（`logmanager_module_init_jsapis`）。

当 MiniApp 执行 `require('logmanager')` 时，触发如下绑定初始化：
```cpp
void logmanager_module_init_jsapis(JSContext *ctx, JSValue ns) {
    JQFunctionTemplate *tmpl = JQFunctionTemplate::New(ctx, "LogManager", JSLogManagerProxy::Constructor);
    tmpl->SetProtoMethod("writeToFile",       JSLogManagerProxy::writeToFile);
    tmpl->SetProtoMethod("writeErrorLog",     JSLogManagerProxy::writeErrorLog);
    tmpl->SetProtoMethod("logSpy",            JSLogManagerProxy::logSpy);
    tmpl->SetProtoMethod("uploadStartupLog",   JSLogManagerProxy::uploadStartupLog);
    tmpl->SetProtoMethod("getCurAppIdPageName",JSLogManagerProxy::getCurAppIdPageName);
    tmpl->SetProtoMethod("addClock",          JSLogManagerProxy::addClock);
    tmpl->SetProtoMethod("addClockToPrint",   JSLogManagerProxy::addClockToPrint);
    tmpl->SetProtoMethod("printReport",       JSLogManagerProxy::printReport);
    tmpl->SetProtoMethod("clearReport",       JSLogManagerProxy::clearReport);
    tmpl->Export(ns, "LogManager");
}
```

---

### 1.2 导出的 9 大原生 API 字典

| 方法名 | 参数 | 底层符号与偏移 | 行为与底层机制 |
| :--- | :--- | :--- | :--- |
| `writeToFile(tag, content)` | `(string, string)` | `0x8fca4` | 校验入参，解出 C 字符串后调用 `YDALAPI::YLogManagerModule::writeToFile`，写入持久日志 |
| `writeErrorLog(content)` | `(string)` | `0x900e4` | 捕获严重错误，附加系统上下文与时间戳，直写闪存错误日志环形缓冲区 |
| `logSpy(event, data)` | `(string, any)` | `0x8fe04` | 序列化用户行为埋点并推入遥测队列，由后台遥测守护进程批量异步上传 |
| `uploadStartupLog()` | 无 | `0x8f988` | 搜集冷启动耗时、QuickJS 初始化与首屏渲染指标，触发云端异步诊断上报 |
| `getCurAppIdPageName()` | 无 | `0x8fbb0` | 查询前台视口，返回 `"{appId}/{pageRoute}"`（如 `"8080999900000001/index"`） |
| `addClock(clockName)` | `(string)` | `0x8ff64` | 在性能基准耗时哈希表中插入当前微秒时间戳锚点 |
| `addClockToPrint(name)` | `(string)` | `0x90024` | 插入时间戳锚点并立即通过 `YLog_print` 输出与上一锚点的毫秒级 $\Delta t$ 差值 |
| `printReport()` | 无 | `0x8f998` | 将所有记录的基准时钟格式化为 ASCII 性能耗时表格并输出到日志 |
| `clearReport()` | 无 | `0x8f9a8` | 清空内部时钟向量，释放内存空间 |

---

### 1.3 日志持久化存储层级结构与路径规范

1. `/userdata/applog/`：`YLogManagerModule` 的主存储区。按 `app_<date>_<index>.log` 轮转，单机总上限严格限制为 20MB。
2. `/userdata/log/`：系统服务级守护进程日志（`pms.log`、`audio_server.log`、`wpa_supplicant.log`）。
3. `/tmp/log/`：基于 tmpfs 内存虚拟文件系统的瞬态日志目录，避免频繁刷盘磨损 NAND Flash。
4. `/userdata/miniapp/data/crash_reports/`：异常崩溃与 ANR 死锁 Tombstone 转储文件的核心归档区。

---

### 1.4 Falcon 控制台重定向机制 (`falcon::installJSConsole`)

在 `libfalcon.so` 中，`falcon::installJSConsole(JSContext *ctx)`（`0x54d8f4`）劫持了全局 JavaScript `console` 对象的所有方法，将其转发至原生派发器（`0x54a700`）：

| JS 控制台方法 | 派发索引 | 原生日志掩码位 (Level Bitmask) | Syslog 输出格式模板 |
| :--- | :--- | :--- | :--- |
| `console.debug` | 0 | `0x80` (128) | `"(console(%s).debug.%d): %s\n"` |
| `console.log` | 1 | `0x40` (64) | `"(console(%s).log.%d): %s\n"` |
| `console.info` | 2 | `0x20` (32) | `"(console(%s).info.%d): %s\n"` |
| `console.warn` | 3 | `0x10` (16) | `"(console(%s).warn.%d): %s\n"` |
| `console.error` | 4 | `0x8` (8) | `"(console(%s).error.%d): %s\n"` |

其中 `%s` 自动注入当前 AppID，`%d` 为参数索引序号。全局过滤由 `/etc/miniapp/resources/env.json` 中的 `logLevel` 控制。

---

## 2. QuickJS 未捕获异常处理与 MVVM 错误边界传播

### 2.1 原生异常提取与堆栈展开 (`falcon::qjs_std_dump_error`)

当 JavaScript 出现未捕获的未处理异常时，顶层调用 `falcon::qjs_std_dump_error(JSContext *ctx)`（地址：`0x54bc04`）：
1. `JS_GetException(ctx)`：提取异常对象并重置执行栈错误标记。
2. `JS_IsError(ctx, val)`：判断是否为标准 `Error` 实例。
3. `JS_ToCStringLen2`：将错误信息转为 C 字符串，通过 `YLog_print(0x8, "(exception): %s\n", err_str)` 输出。
4. 堆栈回溯：调用 `JS_GetPropertyStr(ctx, val, "stack")` 读取调用栈，通过 `YLog_print(0x8, "(stack): %s\n", stack_str)` 打印完整的行号与函数调用链。
5. 内存回收：递减引用计数并彻底释放 `JSValue`。

### 2.2 MVVM 错误边界捕获 (`MvvmEnv::callHandleError`)

在 Vue 2 组件生命周期中抛出的异常由 `MvvmEnv::callHandleError`（`0x35d53c`）捕获：
1. 检查是否存在全局 `Vue.config.errorHandler`。
2. 若存在，传递三参数：`(err, vm, info)` 执行用户态兜底。
3. 若无错误处理器，降级调用 `falcon::qjs_std_dump_error(ctx)`。
4. 若在根实例挂载（`app.$mount()`）或首屏启动阶段报错，Falcon 将 `m_isFatalError` 置为 `true`，退出事件循环并以退出码 `1` 终止进程，唤起 PMS 容灾恢复。

---

## 3. Linux POSIX 信号捕获、Tombstone 生成与崩溃轮转

### 3.1 信号初始化 (`installSignals`)

在 `libfalcon.so` 的 `0x22b26c` 处：
```cpp
void installSignals() {
    signal(SIGHUP,  SIG_IGN);
    signal(SIGPIPE, SIG_IGN);
    signal(SIGQUIT, SIG_IGN);
    signal(SIGTERM, SIG_IGN);
    
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = jquick_sig_handler;
    sa.sa_flags = SA_RESTART;
    
    int fatal_signals[] = {
        SIGSEGV, SIGBUS, SIGABRT, SIGFPE, SIGILL,
        SIGSYS,  SIGTRAP, SIGALRM, SIGIO, SIGUSR1, SIGUSR2
    };
    for (int sig : fatal_signals) {
        sigaction(sig, &sa, nullptr);
    }
}
```

---

### 3.2 信号派发的三大分支状态机 (`jquick_sig_handler`)

```
                      ┌─────────────────────────────┐
                      │   jquick_sig_handler(sig)   │ (0x22ab54)
                      └──────────────┬──────────────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         │                           │                           │
    [sig == 12]                 [sig == 10]                 [Fatal Signal]
     (SIGUSR2)                   (SIGUSR1)              (SIGSEGV, SIGBUS, ...)
         │                           │                           │
         ▼                           ▼                           ▼
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   ANR Watchdog   │        │  Live Backtrace  │        │ Crash Tombstone  │
│     Handler      │        │      Dumper      │        │    Generator     │
└────────┬─────────┘        └────────┬─────────┘        └────────┬─────────┘
         │ 10槽位轮转                 │ 直接输出到syslog          │ 10槽位轮转
         │ 写入ANR转储                │ 不终止进程                │ 写入崩溃墓碑
         │ 捕获backtrace              │ 立即恢复运行              │ 触发清理钩子
         │ 不终止进程                 │                           │ 恢复SIG_DFL再抛出
         ▼                           ▼                           ▼
      (继续运行)                  (继续运行)                  (进程终止/CoreDump)
```

---

### 3.3 ANR Watchdog 诊断转储 (SIGUSR2, 10 槽位轮转)

当 Falcon GUI 主线程卡死超过 5 秒时，PMS 外部看门狗向进程投递 `SIGUSR2`（信号 12）：
1. 触发 10 槽位循环文件滚升（Index 8 down to 0 顺移为 Index 9 down to 1）。
2. 在 `/userdata/miniapp/data/crash_reports/miniapp_anr_report_00` 写入头信息：
   ```
   *** ANR REPORT ***
   PID: %d
   TID: %d
   Time: %s
   ===================
   ```
3. 调用 libc `backtrace` 和 `backtrace_symbols_fd` 输出当前阻塞点的 C++ 符号堆栈。
4. 退出信号处理器，允许应用继续运行（不杀进程）。

---

### 3.4 致命崩溃转储与 Core Dump (SIGSEGV, SIGBUS, SIGABRT)

当发生底层非法内存访问、总线错误或主动断言崩溃时：
1. 循环轮转生成 `/userdata/miniapp/data/crash_reports/miniapp_crash_report_00`。
2. 捕获故障内存地址（`siginfo_t->si_addr`）、故障指令地址与完整堆栈。
3. 恢复默认信号处理器 `signal(sig, SIG_DFL)` 并重新触发信号，触发系统级进程终止，由内核通知父进程 PMS。

---

## 4. PMS 进程守护、心跳看门狗与自动容灾恢复机制

### 4.1 进程衍生与 IPC 监听拓扑

- PMS（包与进程管理中枢）通过 `fork() + execve("/usr/bin/miniapp")` 衍生子进程。
- 监听 UNIX Domain Socket 通道：`/tmp/miniapp_pms.sock`。
- Falcon GUI 事件循环每帧向 PMS 投递 Keep-Alive 脉冲。

### 4.2 5000ms 软超时与 7000ms 强杀阶梯策略

1. **软超时（5,000ms）**：若连续 5 秒未收到主循环心跳，判定 MiniApp 假死，投递 `kill(pid, SIGUSR2)` 触发 ANR 诊断生成。
2. **强杀硬超时（7,000ms）**：若发送 SIGUSR2 2 秒后仍然未恢复心跳，PMS 判定应用无法挽回，执行 `kill(pid, SIGKILL)` 物理清除进程。

### 4.3 防死锁与连续崩溃回滚桌面机制 (`app_launch_stats.json`)

为了彻底杜绝用户设备遭遇“开机启动即崩溃并不断循环死机”的恶性循环，PMS 建立了严密的安全门禁：
1. 启动计数：每次启动应用，持久化递增计数器。
2. 安全就绪门禁（10 秒）：若应用平稳运行超过 10 秒，计数器清零。
3. 容灾判定（连续崩溃 $\ge 2$ 次）：
   - 立即将该 MiniApp 标记为 `"disabled"` 禁用状态。
   - 物理清理该应用在 `/tmp/` 与 `/userdata/miniapp/cache/<appid>/` 的瞬态损坏缓存。
   - **无条件拉起系统桌面 Launcher（AppID: `8080222437664451`）**，恢复屏幕交互。
   - 弹出系统全局 Toast 提示：“应用连续发生异常，已为您返回主屏幕”。

---

## 5. 生产级自研 MiniApp 容灾监控与错误边界库实现

针对有道 S7 Pro 定制的生产级日志与错误边界组件（`logger.ts` 与 `setupErrorBoundary.ts`）：

```typescript
// 具备 Native 原生 C 模块桥接与 Web 降级双模架构的生产级 Logger
export class Logger {
  private static instance: Logger;
  private nativeLog: any = null;

  private constructor() {
    try {
      const lm = require('logmanager');
      if (lm && lm.LogManager) {
        this.nativeLog = new lm.LogManager();
      }
    } catch (_) {
      this.nativeLog = null;
    }
  }

  public static get(): Logger {
    if (!Logger.instance) Logger.instance = new Logger();
    return Logger.instance;
  }

  public error(tag: string, msg: string, err?: any): void {
    const full = `[${tag}] ${msg} ${err ? (err.stack || JSON.stringify(err)) : ''}`;
    console.error(full);
    if (this.nativeLog) {
      this.nativeLog.writeErrorLog(full);
    }
  }

  public fatal(tag: string, msg: string, err?: any): void {
    this.error(tag, `FATAL: ${msg}`, err);
    if (this.nativeLog) {
      this.nativeLog.writeToFile('CRASH_DUMP', `${msg}\n${err?.stack}`);
      this.nativeLog.logSpy('app_crash_event', JSON.stringify({ tag, msg }));
    }
  }
}

// Vue 全局错误边界与异步未捕获异常拦截
export function setupErrorBoundary(Vue: any): void {
  const logger = Logger.get();

  // 1. Vue 组件内渲染与生命周期错误边界
  Vue.config.errorHandler = (err: Error, vm: any, info: string) => {
    const name = vm?.$options?.name || 'UnknownComponent';
    logger.fatal('VueBoundary', `Error in [${name}] during [${info}]`, err);

    // 优雅降级：阻断异常向上击穿导致 Falcon 引擎直接 abort 退出
    if (vm && vm.$data) {
      vm.$data.hasError = true;
      vm.$data.errorTip = '页面渲染遇到问题，已拦截保护';
    }
  };

  // 2. 全局未处理 Promise 拒绝拦截
  const g = typeof window !== 'undefined' ? window : (global as any);
  if (g) {
    g.onunhandledrejection = (event: any) => {
      logger.fatal('PromiseRejection', 'Unhandled rejection trapped', event?.reason);
      if (event && event.preventDefault) event.preventDefault();
    };
  }
}
```
