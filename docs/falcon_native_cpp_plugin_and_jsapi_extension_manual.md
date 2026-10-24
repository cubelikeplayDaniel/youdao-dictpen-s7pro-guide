# 有道词典笔 S7 Pro 原生 C++ 动态库插件 (Native Plugins) 与 JSAPI 扩展架构底层逆向工程与技术手册
## (Youdao S7 Pro Falcon Native C++ Plugins & JSAPI Extension Architecture Engineering Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件版本 4.22.0+)  
> **芯片架构**: 算能科技 (Cvitek) CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, ARMv7-A 32-bit Little-Endian, 硬浮点 VFPv4-D16 / NEON, Linux 5.10.4)  
> **核心组件与运行时**:  
> - 包管理与运行时底座: `/usr/lib/libfalcon.so` (PMS, GreenUI, Looper, Choreographer)  
> - JSAPI 代理与模板中台: `/usr/lib/libjsapi_proxy.so` (JQFunctionTemplate, jqutil_v2, QJSModuleExtension)  
> - 嵌入式 JavaScript 引擎: `/usr/lib/libquickjs.so` (QuickJS 2020-04-12 ARM32 特化版)  
> - 官方插件实证样本: `8080222437664451/a/libs/libjsapi_dictpen_home_1650062498.so`, `libbusiness_dictpen_home_1650062498.so` 等  

---

## 目录索引

1. [端到端架构拓扑与 PMS 动态链接重写机制](#1-端到端架构拓扑与-pms-动态链接重写机制)
   - 1.1 ARMv7-A 目标平台 ABI 与 ELF 规范
   - 1.2 `libfalcon.so` 内嵌 NixOS Patchelf 引擎逆向剖析
   - 1.3 PMS 安装时槽位隔离与动态重命名引擎 (`_Z14chrpathSoFilesPKcS0_` 反汇编)
   - 1.4 ELF 标头动态打补丁过程 (`DT_SONAME`, `DT_RUNPATH`, `DT_NEEDED`)
   - 1.5 槽位隔离体系与无锁零停机热升级优势
2. [Native JSAPI 插件导出入口与注册契约](#2-native-jsapi-插件导出入口与注册契约)
   - 2.1 Falcon 插件生命周期管理器 (`falcon::PrivateJSApiEntry::init` 反汇编)
   - 2.2 导出入口契约辨析 (`custom_init_jsapis` 与 `custom_init_jsmodules`)
   - 2.3 `libjsapi_proxy.so` 模块扩展注册网关 (`falcon::QJSModuleExtension`)
   - 2.4 QuickJS C 模块注册流水线 (`JS_NewCModule` -> `JS_AddModuleExport` -> `init_cb`)
   - 2.5 官方桌面插件 `libjsapi_dictpen_home` 初始化控制流汇编还原
   - 2.6 前端 JS 模块导入与字节码调用契约 (`dictpenHomeManager.js.bin`)
3. [QuickJS 与 C++ 边界数据类型转换与对象封送 (Marshalling)](#3-quickjs-与-c-边界数据类型转换与对象封送-marshalling)
   - 3.1 ARM32 架构下 64 位 `JSValue` 内存布局与 Tag 系统深度解构
   - 3.2 引用计数与垃圾回收生命周期 (`JS_GetGlobalObject` & `__JS_FreeValue` 反汇编)
   - 3.3 标量数据类型封送机制 (Int32, Float64, Bool, Null, Undefined)
   - 3.4 字符串转换与内存所有权契约 (`JS_ToCStringLen` vs `JS_FreeCString`)
   - 3.5 复杂对象与数组的解构与构造 (`JS_NewObject`, `JS_SetPropertyStr`, `JS_NewArray`)
   - 3.6 二进制高速封送中台 (`jqutil_v2::Bson` 序列化与反序列化)
   - 3.7 跨语言异常捕获与传递安全 (`JS_ThrowTypeError`, `JQReturnValue`)
4. [C++ 原生类绑定与 Class ID 生命周期管理](#4-c-原生类绑定与-class-id-生命周期管理)
   - 4.1 QuickJS 原生类系统架构 (`JSClassID`, `JSClassDef`, `JS_NewClass`)
   - 4.2 实例不透明指针 (Opaque Pointer) 机制与机器码解密 (`JS_SetOpaque` / `JS_GetOpaque` 汇编)
   - 4.3 `JSObject` 内存布局与 Finalizer 垃圾回收析构链路
   - 4.4 Falcon JQ 模板绑定框架 (Classic V1 vs Modern V2 `jqutil_v2`)
   - 4.5 原生方法分发与返回值通道 (`JQFunctionCallbackInfo`, `createMessageId` 汇编还原)
5. [异步任务、多线程安全与主线程回调机制](#5-异步任务多线程安全与主线程回调机制)
   - 5.1 单线程 QuickJS 引擎与并发调用冲突的本质
   - 5.2 Falcon Looper & Handler 线程中枢 (`JQuick::getJSLooper` 反汇编分析)
   - 5.3 跨线程任务封装器 (`JQuick::Task` 与 `C11FuncTask` 继承体系)
   - 5.4 异步 Promise 创建与主线程结算模型 (`JS_NewPromiseCapability` 与跨线程 Resolve)
   - 5.5 事件发布订阅与信号总线 (`JQPublishObject` & `YDALBASEAPI::observer`)
6. [生产级原生插件模板工程与跨平台交叉编译实践](#6-生产级原生插件模板工程与跨平台交叉编译实践)
   - 6.1 工程目录结构与文件组织
   - 6.2 ARMv7-A 交叉编译工具链与 `CMakeLists.txt` / `Makefile`
   - 6.3 生产级 C++ 插件完整源码实现 (`plugin_entry.cpp`, `device_controller.h`, `device_controller.cpp`)
   - 6.4 前端 JavaScript/Vue 封装与异步调用实现 (`DeviceService.js`)
   - 6.5 `.amr` 部署打包、ELF 检查清单与高频陷阱排查避坑指南

---

## 1. 端到端架构拓扑与 PMS 动态链接重写机制

在有道词典笔 S7 Pro 的微应用（MiniApp）架构中，前端由基于 Vue 2/3 定制的小程序 DSL 编写，经 Vite / Rollup 编译为 QuickJS 字节码 (`.bin`)。但受限于 CV1813H 单核 Cortex-A7 @ 1.0 GHz 的算力瓶颈与 QuickJS 纯解释执行的性能上限，官方应用（如系统桌面、查词引擎、云盘同步、扫描识别等）广泛采用 **Native C++ Plugins**（原生 C++ 动态库插件）。

原生插件打包于 `.amr` 应用归档内部的 `libs/` 目录下。当包管理服务（Package Management Service, PMS）安装或升级应用时，会触发内核级 ELF 重写引擎，完成动态重命名、库重定位与符号依赖隔离。

```
+-----------------------------------------------------------------------------------+
|                           有道 S7 Pro 原生插件加载与执行拓扑                        |
+-----------------------------------------------------------------------------------+
|  [ 前端 JavaScript/Vue ]                                                          |
|       import dictpenHome from 'dictpenHome';                                      |
|       const home = new dictpenHome.DictpenHome();                                 |
|       await home.enableOcr({ mode: 1 });                                          |
+-----------------------------------------------------------------------------------+
                                         │ QuickJS Module Import
                                         ▼
+-----------------------------------------------------------------------------------+
|  [ libjsapi_proxy.so - 模块网关与模板引擎 ]                                       |
|       falcon::QJSModuleExtension::registerModuleLoader("dictpenHome", &loader)    |
|       jqutil_v2::JQFunctionTemplate / JQObjectTemplate / JQReturnValue            |
+-----------------------------------------------------------------------------------+
                                         │ dlopen / dlsym("custom_init_jsapis")
                                         ▼
+-----------------------------------------------------------------------------------+
|  [ 插件层: libs/libjsapi_dictpen_home_<suffix>.so ]                               |
|       custom_init_jsapis() -> registerCModuleLoader()                             |
|       DictpenHomeProxy -> C11FuncTask 跨线程派发                                  |
+-----------------------------------------------------------------------------------+
                                         │ DT_NEEDED 动态依赖
                                         ▼
+-----------------------------------------------------------------------------------+
|  [ 底层业务/硬件支撑层: libbusiness_<suffix>.so / libfalcon.so ]                  |
|       JQuick::Looper::getMainLooper() / JQuick::Handler::post()                   |
|       YIMAGEOCR::YImageOcrManager / Linux V4L2 / ALSA / Sysfs / Devfs             |
+-----------------------------------------------------------------------------------+
```

### 1.1 ARMv7-A 目标平台 ABI 与 ELF 规范

原生插件为标准 ELF 32-bit LSB (Little-Endian) 动态共享目标文件 (`ET_DYN`)，必须严格符合 Linux ARM EABI v5 规范与芯片硬件浮点规范：

| 规范项 | 目标参数与取值 | 编译器关键标志 | 违规后果与异常表现 |
| :--- | :--- | :--- | :--- |
| **机器指令集** | ARMv7-A (32-bit Little Endian) | `-march=armv7-a -mtune=cortex-a7` | 非法指令崩溃 (`SIGILL`) |
| **浮点 ABI** | **Hard-Float** (硬件浮点调用约定) | `-mfloat-abi=hard -mfpu=neon-vfpv4` | 链接器加载拒绝：`Fatal error: ... uses VFP register arguments, ... does not` |
| **ELF 标志** | `EF_ARM_EABI_VER5` \| `EF_ARM_ABI_FLOAT_HARD` (`0x5000400`) | GCC/Clang 默认附加 | ld.so 拒绝重定位并退出 |
| **动态链接器** | `/lib/ld-linux-armhf.so.3` | `-Wl,--dynamic-linker=...` | 加载期报错 `No such file or directory` |
| **重定位模型** | PIC (Position Independent Code) | `-fPIC -shared` | 无法装载至动态内存段，`DT_TEXTREL` 告警 |
| **C++ 运行库** | GNU `libstdc++.so.6` (GLIBCXX_3.4.28) | `-std=c++14` 或 `-std=c++17` | ABI 符号修饰符不匹配 (`_cxx11` 标头) |

通过 `readelf -h` 验证官方插件 `libjsapi_dictpen_home_1650062498.so` 的头部信息：
```
ELF Header:
  Magic:   7f 45 4c 46 01 01 01 00 00 00 00 00 00 00 00 00 
  Class:                             ELF32
  Data:                              2's complement, little endian
  Version:                           1 (current)
  OS/ABI:                            UNIX - System V
  ABI Version:                       0
  Type:                              DYN (Shared object file)
  Machine:                           ARM
  Version:                           0x1
  Entry point address:               0x1b130
  Start of program headers:          52 (bytes into file)
  Start of section headers:          320144 (bytes into file)
  Flags:                             0x5000400, Version5 EABI, hard-float ABI
  Size of this header:               52 (bytes)
  Size of program headers:           32 (bytes)
  Number of program headers:         9
  Size of section headers:           40 (bytes)
  Number of section headers:         31
  Section header string table index: 30
```

### 1.2 `libfalcon.so` 内嵌 NixOS Patchelf 引擎逆向剖析

传统 Linux 系统在运行时动态修改 ELF 库依赖多依赖外部命令行工具（如 `patchelf`）。而在有道 S7 Pro 闭源平台中，网易有道工程师将开源项目 **NixOS `patchelf`** 的核心 C++ 源码静态内嵌编译入 `/usr/lib/libfalcon.so` 中。

在 `libfalcon.so` 中，反汇编可清晰定位到完整的 Patchelf 符号族与核心操作控制流：
- `patchelfSetRpath` (虚拟地址 `0x0026fde0`)
- `patchelf_rpath_deps` (虚拟地址 `0x0026ff58`)
- `ElfFile<Elf32_Ehdr, Elf32_Phdr, Elf32_Shdr, Elf32_Word, Elf32_Sword, Elf32_Addr, Elf32_Off, Elf32_Section, Elf32_Versym>::modifyRPath` (虚拟地址 `0x0026e6d4`)
- `ElfFile<...>::rewriteSections` (虚拟地址 `0x0026ca20`)

#### Patchelf 引擎内核重写原理
当调用 `modifyRPath` 或更改 `DT_NEEDED` / `DT_SONAME` 时，若目标字符串长度超出原始 ELF 镜像中的 `.dynstr` 预留空隙，Patchelf 引擎执行以下底层重定位序列：
1. **段表后移与页面扩展**: 扫描 `PT_LOAD` 程序头，定位包含 `.dynstr` 的内存加载段。若需要增加空间，将整个 Section Header Table (`Shdr`) 整体向后推移，在文件尾部扩展出新的对齐页面（基于 4096 字节页粒度）。
2. **重构 `.dynstr` 字符串表**: 将原动态字符串表复制至扩展缓冲区，在末尾追加新的 SONAME、RUNPATH 与 NEEDED 字符串条目，计算出对应的字符串偏移表指针。
3. **修复 `DT_DYNAMIC` 动态段条目**: 遍历 `_DYNAMIC` 数组，查找匹配的标记：
   - `DT_SONAME (14)`: 指向新计算的 `libjsapi_home_<suffix>.so` 偏移。
   - `DT_RUNPATH (29)`: 写入新的动态装载路径 `/userdata/miniapp/data/mini_app/pkg/<appid>/<slot>/libs/`。
   - `DT_NEEDED (1)`: 若依赖的业务库（如 `libbusiness_home.so`）同时被重命名，则顺次修补每个 `DT_NEEDED` 偏移。
4. **修复虚拟地址映射 (`p_vaddr` / `sh_addr`)**: 重新计算虚拟加载地址与文件偏移的一致性，确保 `p_align` 校验通过，避免 Linux `ld.so` 在装载时报 `SIGBUS` 或段错误。

### 1.3 PMS 安装时槽位隔离与动态重命名引擎 (`_Z14chrpathSoFilesPKcS0_` 反汇编)

PMS 安装 `.amr` 应用时，通过私有函数 `chrpathSoFiles` 遍历解压后的应用目录。该函数在 `libfalcon.so` 中的符号为 `_Z14chrpathSoFilesPKcS0_`（地址 `0x0025c3cc`），接受两个参数：
- `r0` (const char* app_libs_path): 应用内部的 `libs/` 物理路径，如 `/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/libs/`。
- `r1` (const char* runpath): 运行时设定的 RPATH/RUNPATH。

#### `_Z14chrpathSoFilesPKcS0_` 反汇编代码级证据
```arm
.text:0025C3CC _Z14chrpathSoFilesPKcS0_:
.text:0025C3CC                 push    {r4, r5, r6, r7, r8, sb, sl, fp, lr}
.text:0025C3D0                 sub     sp, sp, #0x464
.text:0025C3D4                 mov     r6, r0               @ r6 = app_libs_path
.text:0025C3D8                 mov     r8, r1               @ r8 = runpath
.text:0025C414                 bl      opendir              @ 打开 libs/ 目录
.text:0025C418                 subs    r4, r0, #0           @ DIR* handle
.text:0025C41C                 beq     loc_exit             @ 目录不存在直接返回
.text:0025C44C                 bl      jquick_get_current_time @ 获取毫秒级时间戳
.text:0025C450                 bl      srand                @ srand(seed)
.text:0025C46C                 bl      rand                 @ rand() 生成随机数
...
.text:0025C4A0                 bl      snprintf             @ 生成 10 位后缀格式: "%010u"
...
.text:0025C6F0                 bl      rename               @ rename("libjsapi_home.so", "libjsapi_home_1650062498.so")
...
.text:0025C7B4                 bl      patchelf_rpath_deps  @ 调用内嵌 patchelf 引擎修补 ELF 标头
.text:0025C7DC                 bl      closedir
.text:0025C7E0                 add     sp, sp, #0x464
.text:0025C7E4                 pop     {r4, r5, r6, r7, r8, sb, sl, fp, lr}
.text:0025C7E8                 bx      lr
```

#### 算法流程解析:
1. **时间随机种子初始化**: `0x0025c44c` 调用 `jquick_get_current_time()` 获取当前高精度系统时钟，传入 `srand`，随后调用 `rand()` 计算随机值，生成唯一的 10 位十进制数字后缀（如 `1650062498`、`1365027777`）。
2. **磁盘重命名**: 扫描目录下所有 `.so` 文件。将 `lib<name>.so` 重命名为 `lib<name>_<10digits>.so`。
3. **调用 `patchelf_rpath_deps`**: 对每个重命名后的动态库，重写其 `DT_SONAME`，将 `DT_RUNPATH` 设为传入的物理路径，并扫描其引用的其他动态库名，将 `DT_NEEDED` 同步升级为带后缀的对应库名。

### 1.4 ELF 标头动态打补丁过程 (`DT_SONAME`, `DT_RUNPATH`, `DT_NEEDED`)

以官方系统桌面插件 `libjsapi_dictpen_home` 为例，分析补丁前后的 ELF 标头变化：

```
+-----------------------------------------------------------------------------------------+
|                                  ELF 标头重写前后对照表                                   |
+---------------------+---------------------------------+---------------------------------+
| 动态段条目 (Tag)    | 原始编译产物 (Unpatched)         | PMS 重写后产物 (Patched in libs)|
+---------------------+---------------------------------+---------------------------------+
| DT_SONAME           | libjsapi_dictpen_home.so        | libjsapi_dictpen_home_1650062498.so|
| DT_RUNPATH          | $ORIGIN/                        | /userdata/miniapp/data/mini_app/|
|                     |                                 | pkg/8080222437664451/a/libs/    |
| DT_NEEDED (内部依赖)| libbusiness_dictpen_home.so     | libbusiness_dictpen_home_1650062498.so|
| DT_NEEDED (系统依赖)| libfalcon.so                    | libfalcon.so (保持不变)         |
| DT_NEEDED (JSAPI)   | libjsapi_proxy.so               | libjsapi_proxy.so (保持不变)    |
| DT_NEEDED (QuickJS) | libquickjs.so                   | libquickjs.so (保持不变)        |
+---------------------+---------------------------------+---------------------------------+
```

通过 Python 逆向提取真实物理二进制的 Dynamic 标头，印证此机制：
```bash
python3 -c '
from elftools.elf.elffile import ELFFile
with open("reverse_dump/8080222437664451/a/libs/libjsapi_dictpen_home_1650062498.so", "rb") as f:
    for tag in ELFFile(f).get_section_by_name(".dynamic").iter_tags():
        if tag.entry.d_tag in ("DT_SONAME", "DT_RUNPATH", "DT_NEEDED"):
            print(f"{tag.entry.d_tag:12s} -> {tag.needed if hasattr(tag, \"needed\") else tag.soname if hasattr(tag, \"soname\") else tag.runpath}")
'
```
输出结果完全一致：
- `DT_SONAME -> libjsapi_dictpen_home_1650062498.so`
- `DT_RUNPATH -> /userdata/miniapp/data/mini_app/pkg/8080222437664451/a/libs/`
- `DT_NEEDED -> libbusiness_dictpen_home_1650062498.so`
- `DT_NEEDED -> libfalcon.so`
- `DT_NEEDED -> libjsapi_proxy.so`
- `DT_NEEDED -> libquickjs.so`

### 1.5 槽位隔离体系与无锁零停机热升级优势

有道 S7 Pro 之所以在 PMS 安装时执行重命名与 ELF 重写，根本原因在于其 **A/B 槽位无锁零停机热升级架构**：
1. **规避全局动态链接器命名空间污染**: Linux 系统的动态装载器 `ld.so` 维护全局共享库命名空间。若所有应用包均使用 `libs/libjsapi_home.so`，当应用在后台运行时，若应用 B 升级或加载同名库，`dlopen` 将命中全局缓存直接返回旧实例，导致内存跨包错乱。
2. **A/B 双槽位原子切换**: 当应用正在 Slot A 运行，云端推送更新至 Slot B 时，Slot B 中的动态库获得全新的随机后缀（如 `1892304812`）。两组库在内存中拥有不同的 SONAME 与文件路径，互不干扰，完成后台加载验证后，仅需更新 Symlink 即可瞬间完成切换，无需重启系统或杀停前台进程。
3. **私有业务库与系统公用库精细分层**: 应用私有的业务逻辑库（`libbusiness_*.so`）被注入后缀与局部 RUNPATH，而系统全局服务库（`libfalcon.so`, `libquickjs.so`）保持原有名称，直接由 `/usr/lib/` 系统路径解析，兼顾了隔离性与系统资源复用。

---

## 2. Native JSAPI 插件导出入口与注册契约

原生 C++ 动态库并非通过 Linux 传统的 `main()` 函数启动，而是作为 QuickJS 运行时的动态扩展宿主。宿主进程 `libfalcon.so` 负责在微应用启动时扫描并动态挂载这些插件。

### 2.1 Falcon 插件生命周期管理器 (`falcon::PrivateJSApiEntry::init` 反汇编)

在 `/usr/lib/libfalcon.so` 中，应用上下文初始化类 `falcon::PrivateJSApiEntry` 主导插件加载。其入口函数 `falcon::PrivateJSApiEntry::init` 位于 `0x00560f4c`。

#### 汇编代码分析:
```arm
.text:00561814                 mov     r1, #1               @ r1 = 1 (RTLD_LAZY)
.text:00561818                 bl      dlopen               @ dlopen(so_path, RTLD_LAZY)
.text:0056181C                 subs    r4, r0, #0           @ r4 = lib_handle
.text:00561820                 beq     loc_load_fail
.text:00561824                 ldr     r1, =aCustomInitJsapis @ "custom_init_jsapis"
.text:00561828                 mov     r0, r4               @ handle
.text:00561830                 bl      dlsym                @ dlsym(handle, "custom_init_jsapis")
.text:00561834                 subs    r5, r0, #0
.text:00561838                 beq     loc_try_modules
.text:0056183c                 blx     r5                   @ 执行: custom_init_jsapis()
.text:00561840                 b       loc_record_handle
.text:loc_try_modules:
.text:00561850                 ldr     r1, =aCustomInitJsmodules @ "custom_init_jsmodules"
.text:00561854                 mov     r0, r4
.text:0056185c                 bl      dlsym                @ dlsym(handle, "custom_init_jsmodules")
.text:00561860                 subs    r6, r0, #0
.text:00561864                 beq     loc_record_handle
.text:00561868                 blx     r6                   @ 执行: custom_init_jsmodules()
.text:loc_record_handle:
.text:00561888                 mov     r0, r4
.text:0056188C                 bl      _ZN6falcon15recordLibHandleEPv @ falcon::recordLibHandle(handle)
```

#### 控制流图示:
```
             dlopen(plugin_path, RTLD_LAZY)
                         │
                  +──────┴──────+
                  │ Handle有效? │
                  +──────┬──────+
                     Yes │  No ──> 抛出加载错误日志
                         ▼
             dlsym("custom_init_jsapis")
                         │
                  +──────┴──────+
                  │ 符号存在?   │
                  +──────┬──────+
              Yes │         │ No
                  ▼         ▼
     执行 custom_init_jsapis()   dlsym("custom_init_jsmodules")
                  │                      │
                  │               +──────┴──────+
                  │               │ 符号存在?   │
                  │               +──────┬──────+
                  │                  Yes │  No
                  │                      ▼   │
                  │          执行 custom_init_jsmodules()
                  │                      │   │
                  └──────────┬───────────┘   │
                             ▼               ▼
                 falcon::recordLibHandle(handle)
                             │
                      完成插件注册并保留句柄
```

在插件卸载阶段，`falcon::PrivateJSApiEntry::deinit` (`0x00561e78`) 将依次调用清理钩子，并通过 `dlclose` 释放动态库句柄，完成干净的资源回收。

### 2.2 导出入口契约辨析 (`custom_init_jsapis` 与 `custom_init_jsmodules`)

在逆向工程中，我们发现 `libfalcon.so` 依次查询两个符号：
1. **`custom_init_jsapis` (主流标准)**: 所有的官方小程序插件（包括桌面、查词、设置、家长管控、拼写等 20+ 个插件）100% 均采用此导出符号。其原型为 `extern "C" void custom_init_jsapis(void)`.
2. **`custom_init_jsmodules` (备用/早期规范)**: 早期规范保留符号，如果在动态库中未找到 `custom_init_jsapis`，宿主会降级查询此符号。

**开发铁律**: 原生插件必须声明并导出带有 `extern "C"`  linkage 且 `__attribute__((visibility("default")))` 的 `custom_init_jsapis` 函数。

### 2.3 `libjsapi_proxy.so` 模块扩展注册网关 (`falcon::QJSModuleExtension`)

当 `custom_init_jsapis()` 被触发执行时，插件自身并不直接触碰 QuickJS 的原始 C 结构体，而是调用 `/usr/lib/libjsapi_proxy.so` 导出的中台注册函数：
```cpp
extern "C" void registerCModuleLoader(
    const std::string& module_name,
    JSModuleDef* (*module_loader)(JSContext* ctx, const char* module_name)
);
```

反汇编 `libjsapi_proxy.so` 的 `registerCModuleLoader` (虚拟地址 `0x00072f30`)：
```arm
.text:00072F84                 bl      _ZN6falcon18QJSModuleExtension9singletonEv @ 获取单例
.text:00072F88                 mov     r3, r0               @ QJSModuleExtension* 实例
.text:00072F90                 bl      _ZN6falcon18QJSModuleExtension19registerModuleLoaderENSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPFP11JSModuleDefP9JSContextPKcE
```
`falcon::QJSModuleExtension` 内部维护一个 `std::map<std::string, ModuleLoaderFunc>` 哈希表。当前端执行 `import ... from 'moduleName'` 时，QuickJS 引擎触发模块解析钩子，在表中检索对应的 loader 函数并传入当前活跃的 `JSContext*`。

### 2.4 QuickJS C 模块注册流水线 (`JS_NewCModule` -> `JS_AddModuleExport` -> `init_cb`)

在 Module Loader 回调函数中，必须遵循 QuickJS C Module 注册规范：

```
+-----------------------------------------------------------------------------------+
|                         QuickJS C 模块双阶段注册时序图                            |
+-----------------------------------------------------------------------------------+
|  [阶段 1: Loader 阶段 (加载声明)]                                                 |
|  1. JS_NewCModule(ctx, "myModule", &ModuleInitCallback)                          |
|     └── 在 QuickJS 运行时内创建一个未初始化的 C 模块节点                          |
|  2. JS_AddModuleExport(ctx, m, "default")                                         |
|     └── 声明该模块导出的符号名称 (通常声明 "default" 或各个命名导出)             |
|  3. 返回 JSModuleDef* 指针给 QuickJS                                             |
+-----------------------------------------------------------------------------------+
                                         │
                                         ▼ JS 运行时执行 import 语句
+-----------------------------------------------------------------------------------+
|  [阶段 2: Execution 阶段 (InitCallback 初始化)]                                   |
|  1. ModuleInitCallback(JSContext* ctx, JSModuleDef* m) 被引擎调度调用             |
|  2. 构建导出的 C++ 包装对象 (通过 JQFunctionTemplate / JQObjectTemplate)          |
|  3. JS_SetModuleExport(ctx, m, "default", export_object)                          |
|     └── 将具体的 JSValue 注入到模块导出槽位中                                     |
|  4. 返回 0 表示初始化成功                                                         |
+-----------------------------------------------------------------------------------+
```

### 2.5 官方桌面插件 `libjsapi_dictpen_home` 初始化控制流汇编还原

深入反汇编分析 `reverse_dump/8080222437664451/a/libs/libjsapi_dictpen_home_1650062498.so` 中的真实代码逻辑。

#### `custom_init_jsapis` 反汇编 (0x0001edc4):
```arm
.text:0001EDC4 custom_init_jsapis:
.text:0001EDC4                 push    {r4, lr}
.text:0001EF14                 ldr     r1, =0x1e48c         @ module_loader 回调指针
.text:0001EF18                 ldr     r0, =0x359c0         @ 模块名称字符串: "dictpenHome"
.text:0001EF2C                 bl      registerCModuleLoader @ 注册至 QJSModuleExtension
.text:0001EF30                 pop     {r4, pc}
```

#### Module Loader 回调反汇编 (0x0001e48c):
```arm
.text:0001E48C                 push    {r4, r5, lr}
.text:0001E494                 ldr     r2, =0x1f478         @ 执行期初始化回调 ModuleInitCallback
.text:0001E498                 bl      JS_NewCModule        @ JS_NewCModule(ctx, "dictpenHome", 0x1f478)
.text:0001E4A0                 mov     r4, r0               @ r4 = JSModuleDef* m
.text:0001E4B0                 ldr     r1, =0x359cc         @ "default"
.text:0001E4B4                 bl      JS_AddModuleExport   @ JS_AddModuleExport(ctx, m, "default")
.text:0001E4BC                 mov     r0, r4               @ 返回 m
.text:0001E4C0                 pop     {r4, r5, pc}
```

#### ModuleInitCallback 构造器绑定反汇编 (0x0001f478):
在 `0x0001f478` 中，插件初始化 C++ 类模板 `JQFunctionTemplate`：
```arm
.text:0001F480                 ldr     r5, [pc, #0x4cc]     @ GOT 基址
.text:0001F4A0                 ldr     r1, =0x35abf         @ "DictpenHome" 类名
.text:0001F4A8                 bl      JQFunctionTemplate::New @ 创建函数模板
...
.text:0001F564                 ldr     r1, =0x35acb         @ "checkLockState"
.text:0001F58C                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F594                 ldr     r1, =0x35ada         @ "baseUrl"
.text:0001F5BC                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F5F0                 ldr     r1, =0x35ae2         @ "lockStateChanged" (Signal)
.text:0001F618                 bl      JQObjectTemplate::Set
.text:0001F620                 ldr     r1, =0x35af3         @ "requestData"
.text:0001F648                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F65C                 ldr     r1, =0x35aff         @ "createMessageId"
.text:0001F680                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F784                 ldr     r1, =0x35b36         @ "enableOcr"
.text:0001F7AC                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F7B4                 ldr     r1, =0x35b40         @ "disableOcr"
.text:0001F7DC                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F7E4                 ldr     r1, =0x35b4b         @ "resetOcr"
.text:0001F80C                 bl      JQFunctionTemplate::SetProtoMethod
.text:0001F820                 ldr     r1, =0x35b54         @ "startOnlineOcr"
.text:0001F848                 bl      JQFunctionTemplate::SetProtoMethod
...
.text:0001F8F8                 ldr     r2, =0x359c0         @ 导出对象注入
.text:0001F904                 bl      JS_SetModuleExport   @ JS_SetModuleExport(ctx, m, "default", dictpenHome_export)
```

### 2.6 前端 JS 模块导入与字节码调用契约 (`dictpenHomeManager.js.bin`)

逆向提取官方桌面应用字节码模块 `8080222437664451/a/dictpenHomeManager-ce29544a.js.bin`，还原其前端调用封装：

```javascript
// dictpenHomeManager-ce29544a.js 反编译等效源码
import dictpenHome from 'dictpenHome';

let instance = null;

export function getDictpenHomeManager() {
    if (!instance) {
        // 调用 C++ 导出的 DictpenHome 构造器，触发 JQBaseObject::OnCtor
        instance = new dictpenHome.DictpenHome();
    }
    return instance;
}

export default getDictpenHomeManager;
```

而在桌面主业务 `indexPage-085a554f.js.bin` 中，调用非常直接：
```javascript
import getDictpenHomeManager from './dictpenHomeManager-ce29544a.js';

const homeMgr = getDictpenHomeManager();

// 同步调用 C++ 快速方法
const msgId = homeMgr.createMessageId();

// 注册 C++ 硬件信号监听器
homeMgr.onlineOCRFinished.connect((result) => {
    console.log("OCR Result received from C++ thread:", result);
});

// 异步调用底层硬件功能
homeMgr.enableOcr();
```

---

## 3. QuickJS 与 C++ 边界数据类型转换与对象封送 (Marshalling)

跨越 JavaScript 解释器与 C++ 本地内存边界时，数据类型封送（Marshalling）是核心技术瓶颈。理解 QuickJS 在 ARM32 架构下的二进制布局是编写安全高性能插件的基础。

### 3.1 ARM32 架构下 64 位 `JSValue` 内存布局与 Tag 系统深度解构

在 64 位 CPU 上，QuickJS 通常使用 NaN-Boxing 技术将 `JSValue` 压缩为单一 64 位整数。但在 **ARMv7-A 32 位 Little-Endian** 架构上，QuickJS 定义了经典的结构体传递模式：

```c
typedef struct JSValue {
    union {
        int32_t int32;
        double float64;
        void *ptr;
    } u;
    int32_t tag;
} JSValue;
```

#### ABI 传递规则:
在 ARM AAPCS (ARM Architecture Procedure Call Standard) 下，8 字节大小的结构体通过一对连续的 32 位通用寄存器传递：
- `r0` (低 32 位): 存储有效载荷 `u`（整型值、GC 对象堆指针 `JSGCObjectHeader*`、或双精度浮点低 32 位）。
- `r1` (高 32 位): 存储类型标签 `tag`。

#### Tag 标签枚举值定义 (ARM32 版):
```c
enum {
    /* 负标签: 堆上分配的 GC 垃圾回收管理对象 (均包含引用计数头) */
    JS_TAG_BIG_DECIMAL    = -11,
    JS_TAG_BIG_INT        = -10,
    JS_TAG_BIG_FLOAT      = -9,
    JS_TAG_SYMBOL         = -8,
    JS_TAG_STRING         = -7,  // 堆字符串
    JS_TAG_SHAPE          = -2,
    JS_TAG_ASYNC_FUNCTION = -3,
    JS_TAG_FUNCTION_BYTECODE = -2,
    JS_TAG_OBJECT         = -1,  // 普通 JS 对象、数组、函数等

    /* 0 及正标签: 立即数/值类型 (无引用计数，零内存分配开销) */
    JS_TAG_INT            = 0,   // 32 位带符号整数
    JS_TAG_BOOL           = 1,   // 布尔值 (u.int32 为 0 或 1)
    JS_TAG_NULL           = 2,   // null
    JS_TAG_UNDEFINED      = 3,   // undefined
    JS_TAG_UNINITIALIZED  = 4,
    JS_TAG_CATCH_OFFSET   = 5,
    JS_TAG_EXCEPTION      = 6,   // 异常标记
    JS_TAG_FLOAT64        = 7,   // 64 位双精度浮点
};
```

### 3.2 引用计数与垃圾回收生命周期 (`JS_GetGlobalObject` & `__JS_FreeValue` 反汇编)

由于负标签代表堆分配对象，QuickJS 引擎的垃圾回收基于侵入式引用计数（Intrusive Reference Counting）。

#### 汇编实证: `JS_GetGlobalObject` (虚拟地址 `0x00031bb4`)
```arm
.text:00031BB4 JS_GetGlobalObject:
.text:00031BB4                 ldrd    r0, r1, [r0, #0xC0]  @ (r0, r1) = ctx->global_obj
.text:00031BB8                 cmn     r1, #0xC             @ r1 - (-12) => 检查是否 r1 > -12
.text:00031BBC                 ldrhi   r3, [r0]             @ 若是 GC 对象, r0 指向 JSGCObjectHeader
.text:00031BC0                 addhi   r3, r3, #1           @ ref_count++
.text:00031BC4                 strhi   r3, [r0]             @ 写回引用计数
.text:00031BC8                 bx      lr                   @ 返回 (r0, r1) 为新引用的 JSValue
```

#### 汇编实证: `__JS_FreeValue` (虚拟地址 `0x0002bc6c`)
```arm
.text:0002BC6C __JS_FreeValue:
.text:0002BC6C                 ldr     r0, [r0, #0x10]      @ r0 = ctx->rt (运行时指针)
.text:0002BC70                 b       __JS_FreeValueRT     @ 尾调用释放逻辑
...
.text:0002BC74                 ldr     r1, [r2]             @ r1 = p->ref_count
.text:0002BC78                 sub     r1, r1, #1           @ ref_count--
.text:0002BC7C                 str     r1, [r2]
.text:0002BC80                 cmp     r1, #0               @ 判断是否归零
.text:0002BC84                 bxgt    lr                   @ 大于 0 直接返回
.text:0002BC88                 b       free_gc_object       @ 归零时销毁对象并触发 C++ 析构器
```

**内存所有权三大法则**:
1. **New / Dup 原则**: 调用 `JS_NewObject`, `JS_NewString`, `JS_DupValue` 会增加引用计数，所有权归调用方，使用完毕必须调用 `JS_FreeValue(ctx, val)`。
2. **Transfer 原则**: 将 `JSValue` 作为参数传给 `JS_SetPropertyStr` 时，QuickJS 会**盗用 (Steal)** 该值的引用计数，调用方无需、且**严禁**再对其调用 `JS_FreeValue`。
3. **Get 原则**: `JS_GetPropertyStr` 会返回一个增加了引用计数的新 `JSValue`，调用方必须负责 `JS_FreeValue`。

### 3.3 标量数据类型封送机制 (Int32, Float64, Bool, Null, Undefined)

标量类型在 QuickJS 中直接通过寄存器传值，不涉及堆分配：

```cpp
// C++ 标量封送辅助函数
inline JSValue to_js(JSContext* ctx, int32_t val) {
    return (JSValue){ .u = { .int32 = val }, .tag = JS_TAG_INT };
}

inline JSValue to_js(JSContext* ctx, bool val) {
    return (JSValue){ .u = { .int32 = val ? 1 : 0 }, .tag = JS_TAG_BOOL };
}

inline JSValue to_js(JSContext* ctx, double val) {
    return JS_NewFloat64(ctx, val); // 内部根据是否整数自动优化为 TAG_INT 或 TAG_FLOAT64
}

inline JSValue js_undefined() {
    return (JSValue){ .u = { .int32 = 0 }, .tag = JS_TAG_UNDEFINED };
}

inline JSValue js_null() {
    return (JSValue){ .u = { .int32 = 0 }, .tag = JS_TAG_NULL };
}
```

从 JSValue 提取值：
```cpp
inline bool from_js(JSContext* ctx, JSValue val, int32_t& out) {
    return JS_ToInt32(ctx, &out, val) == 0;
}

inline bool from_js(JSContext* ctx, JSValue val, double& out) {
    return JS_ToFloat64(ctx, &out, val) == 0;
}

inline bool from_js(JSContext* ctx, JSValue val, bool& out) {
    int res = JS_ToBool(ctx, val);
    if (res < 0) return false;
    out = (res != 0);
    return true;
}
```

### 3.4 字符串转换与内存所有权契约 (`JS_ToCStringLen` vs `JS_FreeCString`)

QuickJS 字符串在堆中分配，并支持 UTF-8 编码。与 `std::string` 互转必须严防内存泄漏与野指针：

```cpp
// JSValue -> std::string
std::string js_to_std_string(JSContext* ctx, JSValue val) {
    size_t len = 0;
    const char* str = JS_ToCStringLen(ctx, &len, val);
    if (!str) {
        return "";
    }
    std::string result(str, len); // 拷贝内容至 C++ 内存空间
    JS_FreeCString(ctx, str);     // 必须主动释放 QuickJS 临时 UTF-8 缓冲区
    return result;
}

// std::string -> JSValue
JSValue std_string_to_js(JSContext* ctx, const std::string& str) {
    // JS_NewStringLen 会自动在 QuickJS 堆上分配空间并拷贝数据
    return JS_NewStringLen(ctx, str.data(), str.length());
}
```

### 3.5 复杂对象与数组的解构与构造 (`JS_NewObject`, `JS_SetPropertyStr`, `JS_NewArray`)

```cpp
// 构造复合 JS 对象: { id: 101, name: "CIS_Sensor", active: true }
JSValue build_device_info(JSContext* ctx) {
    JSValue obj = JS_NewObject(ctx);
    if (JS_IsException(obj)) return obj;

    JS_SetPropertyStr(ctx, obj, "id", JS_NewInt32(ctx, 101));
    JS_SetPropertyStr(ctx, obj, "name", JS_NewString(ctx, "CIS_Sensor"));
    JS_SetPropertyStr(ctx, obj, "active", JS_NewBool(ctx, 1));
    
    // 注意: JS_SetPropertyStr 盗用 val 所有权，无需调用 JS_FreeValue
    return obj;
}

// 遍历 JS 数组
std::vector<int> parse_int_array(JSContext* ctx, JSValue array_val) {
    std::vector<int> result;
    if (!JS_IsArray(ctx, array_val)) return result;

    JSValue len_val = JS_GetPropertyStr(ctx, array_val, "length");
    int64_t len = 0;
    JS_ToInt64(ctx, &len, len_val);
    JS_FreeValue(ctx, len_val); // GetProperty 必须释放

    result.reserve(len);
    for (uint32_t i = 0; i < len; ++i) {
        JSValue elem = JS_GetPropertyUint32(ctx, array_val, i);
        int32_t val = 0;
        JS_ToInt32(ctx, &val, elem);
        result.push_back(val);
        JS_FreeValue(ctx, elem); // 每次循环释放获取的元素
    }
    return result;
}
```

### 3.6 二进制高速封送中台 (`jqutil_v2::Bson` 序列化与反序列化)

在官方查词、古诗词、教材等大型应用中，若每次通过属性逐个反射封送几万个字词，JS 解释器将发生严重掉帧。网易有道在 `libjsapi_proxy.so` 中实现了 `jqutil_v2::Bson` 二进制高效序列化引擎（符号 `_ZN9jqutil_v24Bson*`）：

```cpp
// 原生层向 JS 批量派发结构化数据时使用 BSON 高速序列化
jqutil_v2::Bson bson;
bson.putInt32("code", 0);
bson.putString("word", "falcon");
bson.putBinary("audio_pcm", pcm_buffer, pcm_size);

// 一键反序列化并封送到 JS 对象中
asyncInfo.post(bson, nullptr);
```
该机制将 C++ 内存块一次性打包，越过逐层反射，直接在 QuickJS 堆上由底层 C 代码重建对象，吞吐性能提升一个数量级。

### 3.7 跨语言异常捕获与传递安全 (`JS_ThrowTypeError`, `JQReturnValue`)

C++ 异常在跨越共享库边界时若发生未捕获的 Unwind，将导致整个进程 `std::terminate()` 崩溃退出。Native 插件必须确保所有 C++ 逻辑被包围在 `try-catch` 块中，并转换为 QuickJS 原生异常：

```cpp
void SafeMethodHandler(const JQFunctionCallbackInfo& info) {
    try {
        if (info.Length() < 1) {
            info.GetReturnValue().ThrowTypeError("Expected at least 1 argument");
            return;
        }
        // 执行业务逻辑
        std::string res = do_hardware_operation();
        info.GetReturnValue().Set(res);
    } catch (const std::exception& e) {
        // 安全拦截 C++ 异常并抛给 JavaScript
        info.GetReturnValue().ThrowInternalError("C++ Native Exception: %s", e.what());
    } catch (...) {
        info.GetReturnValue().ThrowInternalError("Unknown Native Error occurred");
    }
}
```

---

## 4. C++ 原生类绑定与 Class ID 生命周期管理

在 Native 插件中，最核心的能力是将 C++ 类实例与 JavaScript 对象深度绑定，使得 JS 可以像操作普通对象一样调用底层 C++ 驱动与硬件接口。

### 4.1 QuickJS 原生类系统架构 (`JSClassID`, `JSClassDef`, `JS_NewClass`)

在标准 QuickJS 体系中，每个 C++ 类需要向运行时注册一个全局唯一的 `JSClassID`：

```c
static JSClassID js_device_class_id;

static void js_device_finalizer(JSRuntime *rt, JSValue val) {
    // 当该 JS 对象被垃圾回收时自动触发
    DeviceController *dev = (DeviceController *)JS_GetOpaque(val, js_device_class_id);
    if (dev) {
        delete dev; // 安全析构原生 C++ 实例
    }
}

static JSClassDef js_device_class = {
    .class_name = "DeviceController",
    .finalizer = js_device_finalizer,
    .gc_mark = NULL,
    .call = NULL,
    .exotic = NULL,
};

void init_device_class(JSRuntime *rt) {
    JS_NewClassID(&js_device_class_id);
    JS_NewClass(rt, js_device_class_id, &js_device_class);
}
```

### 4.2 实例不透明指针 (Opaque Pointer) 机制与机器码解密 (`JS_SetOpaque` / `JS_GetOpaque` 汇编)

JavaScript 对象如何持有 C++ 对象指针？QuickJS 在 `JSObject` 结构体中预留了 `opaque` 字段。我们反汇编 `/usr/lib/libquickjs.so` 的底层实现，揭示其内存布局：

#### `JS_SetOpaque` 反汇编 (0x00031da8):
```arm
.text:00031DA8 JS_SetOpaque:
.text:00031DA8                 cmn     r1, #1               @ r1 == -1 ? (判断 tag 是否为 JS_TAG_OBJECT)
.text:00031DAC                 streq   r2, [r0, #0x20]      @ 若是对象: obj->opaque = r2 (存入 offset 0x20)
.text:00031DB0                 bx      lr
```

#### `JS_GetOpaque` 反汇编 (0x00031db4):
```arm
.text:00031DB4 JS_GetOpaque:
.text:00031DB4                 cmn     r1, #1               @ tag 是否为 JS_TAG_OBJECT
.text:00031DB8                 bne     loc_null             @ 非对象返回 NULL
.text:00031DBC                 ldrh    r3, [r0, #6]         @ r3 = obj->class_id (读取 offset 0x06 的 uint16)
.text:00031DC0                 cmp     r3, r2               @ 比较传入的 class_id 是否与预期一致
.text:00031DC4                 bne     loc_null             @ 不一致返回 NULL (类型安全保护!)
.text:00031DC8                 ldr     r0, [r0, #0x20]      @ r0 = obj->opaque (读取 offset 0x20 处的指针)
.text:00031DCC                 bx      lr
.text:loc_null:
.text:00031DD0                 mov     r0, #0
.text:00031DD4                 bx      lr
```

### 4.3 `JSObject` 内存布局与 Finalizer 垃圾回收析构链路

基于上述反汇编，还原出 QuickJS 在 ARM32 平台上的 `JSObject` 真实内存排布：

```
+-----------------------------------------------------------------------+
|                    QuickJS JSObject 内存布局 (ARM32)                  |
+-------------------+---------+-----------------------------------------+
| 字节偏移 (Offset) | 大小    | 字段描述                                |
+-------------------+---------+-----------------------------------------+
| 0x00 - 0x03       | 4 字节  | uint32_t ref_count (侵入式引用计数)      |
| 0x04              | 1 字节  | uint8_t gc_obj_type                     |
| 0x05              | 1 字节  | uint8_t gc_mark                         |
| 0x06 - 0x07       | 2 字节  | uint16_t class_id (用于类型安全校验)    |
| 0x08 - 0x1F       | 24 字节 | 原型指针, Shape, 属性散列表槽位等       |
| 0x20 - 0x23       | 4 字节  | void* opaque (指向原生 C++ 实例的物理地址)|
+-------------------+---------+-----------------------------------------+
```

当 `JS_FreeValue` 检测到 `ref_count` 归零时，引擎通过 `class_id` 检索到 `JSClassDef`，调用绑定的 `finalizer`。在此刻，C++ 对象被安全释放，杜绝了内存悬挂与泄漏。

### 4.4 Falcon JQ 模板绑定框架 (Classic V1 vs Modern V2 `jqutil_v2`)

网易有道在 `libjsapi_proxy.so` 中对 QuickJS 原始 C 接口进行了 C++ 面向对象封装，形成了两代绑定框架：

```
+-----------------------------------------------------------------------------------+
|                         Falcon JQ 两代绑定框架对比                                |
+---------------------------+---------------------------+---------------------------+
| 特征项                    | 第一代: Classic JQ (V1)   | 第二代: Modern JQ (V2)    |
+---------------------------+---------------------------+---------------------------+
| 命名空间                  | 全局 (无命名空间)         | `jqutil_v2::*`            |
| 核心模板类                | `JQFunctionTemplate`      | `jqutil_v2::JQFunction...`|
| 实例承载基类              | `JQBaseObject`            | `jqutil_v2::JQBaseObject` |
| 回调参数包装              | `JQFunctionCallbackInfo`  | `jqutil_v2::JQFunctionInfo`|
| 异步方法支持              | 需手动结合 Looper         | 内置 `_SetPromise` / Async|
| 数据封送中台              | JSON 字符串 / 标量        | `jqutil_v2::Bson` 二进制  |
| 典型应用                  | 系统桌面 (`dictpen_home`) | 查词、古诗词、学科综合    |
+---------------------------+---------------------------+---------------------------+
```

### 4.5 原生方法分发与返回值通道 (`JQFunctionCallbackInfo`, `createMessageId` 汇编还原)

以官方桌面插件 `createMessageId` 方法（虚拟地址 `0x0001ed84`）为例，剖析其调用约定与返回值机制：

#### `createMessageId` 反汇编实录:
```arm
.text:0001ED84 _ZN19JSDictPenHomeProxy15createMessageIdER22JQFunctionCallbackInfo:
.text:0001ED84                 push    {r4, r5, lr}
.text:0001ED88                 mov     r5, r1               @ r5 = const JQFunctionCallbackInfo& info
.text:0001ED8C                 sub     sp, sp, #0x1C        @ 预留 std::string 栈空间 (28 字节)
.text:0001ED90                 mov     r4, sp               @ r4 = temp_string
.text:0001ED94                 mov     r0, r4
.text:0001ED98                 bl      generate_uuid        @ 生成 UUID 字符串
.text:0001ED9C                 mov     r1, r4               @ r1 = temp_string
.text:0001EDA0                 add     r0, r5, #0x30        @ r0 = info + 0x30 (JQReturnValue 偏移!)
.text:0001EDA4                 bl      _ZN13JQReturnValue3SetERKNSt7__cxx1112basic_string... @ ReturnValue::Set(str)
.text:0001EDA8                 mov     r0, r4
.text:0001EDAC                 bl      _ZNSt7__cxx1112basic_string...D1Ev @ 析构临时 std::string
.text:0001EDB0                 add     sp, sp, #0x1C
.text:0001EDB4                 pop     {r4, r5, pc}
```

#### 逆向结构还原:
`JQFunctionCallbackInfo` 的物理内存布局：
- `offset 0x00`: `JSContext* m_ctx`
- `offset 0x04`: `JSValue m_this_val` (8 字节)
- `offset 0x0C`: `int m_argc`
- `offset 0x10`: `JSValue* m_argv`
- `offset 0x14 - 0x2F`: 私有调用上下文与标志
- `offset 0x30`: `JQReturnValue m_return_value` (持有返回值并负责将其封送回 QuickJS 堆)

---

## 5. 异步任务、多线程安全与主线程回调机制

### 5.1 单线程 QuickJS 引擎与并发调用冲突的本质

QuickJS 引擎的内部设计是**严格单线程非重入**的：
1. `JSRuntime` 与 `JSContext` 没有任何内部互斥锁（Mutex）。
2. GC 引用计数增减与内存分配器（`js_malloc`）均非原子操作。
3. 若从背景工作线程（如 Linux `pthread`）直接调用 `JS_Call`、`JS_NewObject` 或修改 `JSValue`，将立刻引发内存破坏、堆越界甚至引发 `SIGSEGV`。

因此，**所有的 JavaScript 执行、Promise 结算与回调通知，必须调度至 Falcon 主线程（UI 线程）执行。**

### 5.2 Falcon Looper & Handler 线程中枢 (`JQuick::getJSLooper` 反汇编分析)

在 `libfalcon.so` 与 `libjsapi_proxy.so` 中，网易有道移植了 Android 经典的消息循环模型 —— **`JQuick::Looper`** 与 **`JQuick::Handler`**。

#### 反汇编 `JQuick::getJSLooper(JSContext*)` (虚拟地址 `0x0002565c` in `libjsapi_proxy.so`):
```arm
.text:0002565C _ZN6JQuick11getJSLooperEP9JSContext:
.text:0002565C                 push    {r4, lr}
.text:00025660                 mov     r4, r0               @ r4 = sp<Looper> 存储槽
.text:00025664                 mov     r0, r1               @ r0 = JSContext*
.text:00025668                 bl      JS_GetRuntime        @ 获取 JSRuntime*
.text:0002566C                 mov     r1, r0               @ r1 = JSRuntime*
.text:00025670                 mov     r0, r4
.text:00025674                 bl      _ZN6JQuick11getJSLooperEP9JSRuntime @ getJSLooper(rt)
.text:00025678                 mov     r0, r4
.text:0002567C                 pop     {r4, pc}
```

深入 `JQuick::getJSLooper(JSRuntime*)` (`0x000255e0`):
```arm
.text:000255E0 _ZN6JQuick11getJSLooperEP9JSRuntime:
.text:000255E0                 push    {r4, lr}
.text:000255E4                 mov     r4, r0
.text:000255E8                 mov     r0, r1               @ r0 = JSRuntime*
.text:000255EC                 bl      JS_GetRuntimeOpaque  @ 获取绑定在 Runtime 上的环境上下文
.text:000255F0                 subs    r3, r0, #0
.text:000255FC                 ldr     r1, [r3, #4]         @ 读取 offset 4: 提取主线程 Looper 指针!
.text:00025600                 bl      sp<Looper>::operator=
.text:00025604                 mov     r0, r4
.text:00025608                 pop     {r4, pc}
```
**关键发现**: Falcon 框架在创建 `JSRuntime` 时，已将当前宿主线程的 `Looper` 注册到了 `RuntimeOpaque` 中。插件可以随时通过 `JQuick::getJSLooper(ctx)` 获取与 JS 引擎绑定的主线程循环。

### 5.3 跨线程任务封装器 (`JQuick::Task` 与 `C11FuncTask` 继承体系)

在 `libjsapi_dictpen_home` 中，逆向发现了一个精巧的 C++11 Lambda 任务封装类：**`C11FuncTask`**。

#### 符号与继承表:
- 抽象基类: `JQuick::Task` (声明虚函数 `virtual void run() = 0`)
- 派生实现: `C11FuncTask` (`0x0004cb04`)

#### 虚表反汇编实录 (`C11FuncTask::run` at `0x00022b40`):
```arm
.text:00022B40 _ZN11C11FuncTask3runEv:
.text:00022B40                 ldr     r3, [r0, #8]         @ 读取 std::function 内部调用指针
.text:00022B44                 cmp     r3, #0
.text:00022B48                 bxeq    lr
.text:00022B4C                 add     r0, r0, #4           @ this 指向 std::function
.text:00022B50                 bx      r3                   @ 执行: std::function<void()>::operator()()
```

#### 跨线程派发范式:
```cpp
// 在 background thread 中派发任务至主线程
void postToMainThread(JSContext* ctx, std::function<void()> callback) {
    JQuick::sp<JQuick::Looper> looper = JQuick::getJSLooper(ctx);
    JQuick::sp<JQuick::Handler> handler = new JQuick::Handler(looper);
    
    // C11FuncTask 封装 Lambda 并投递至消息队列
    handler->run(new C11FuncTask(callback));
}
```

### 5.4 异步 Promise 创建与主线程结算模型 (`JS_NewPromiseCapability` 与跨线程 Resolve)

在现代 JS 编程中，异步 API 必须返回 `Promise`。原生 C++ 插件如何实现 Promise 的创建与跨线程结算？

#### 1. 创建 Promise 并捕获 Resolving Functions
```cpp
struct PromiseContext {
    JSContext* ctx;
    JSValue promise;
    JSValue resolve_func;
    JSValue reject_func;
};

PromiseContext* create_promise(JSContext* ctx) {
    PromiseContext* pctx = new PromiseContext();
    pctx->ctx = ctx;

    JSValue resolving_funcs[2];
    // 调用 QuickJS 底层接口创建 Promise
    pctx->promise = JS_NewPromiseCapability(ctx, resolving_funcs);
    
    // resolving_funcs[0] 为 resolve 回调, [1] 为 reject 回调
    pctx->resolve_func = resolving_funcs[0];
    pctx->reject_func = resolving_funcs[1];
    
    return pctx;
}
```

#### 2. 背景线程执行耗时任务与主线程 Resolve 结算
```
[ 背景 Worker 线程 (pthread) ]                 [ Falcon UI 主线程 (Looper) ]
        │                                                     │
        ├─ 1. 执行耗时计算 (如图像处理、硬件采集)              │
        │                                                     │
        ├─ 2. 计算完成，打包数据                              │
        │                                                     │
        └─ 3. handler->run(new C11FuncTask([=]() { ─────────> │
                                                              ├─ 4. 在主线程被 Looper 唤醒执行
                                                              ├─ 5. 将 C++ 数据封送为 JSValue
                                                              ├─ 6. JS_Call(ctx, resolve_func, ...)
                                                              ├─ 7. JS_FreeValue 释放 Promise 上下文
                                                              └─ 8. JS 端 await 语句获得返回结果
```

#### 核心代码实现:
```cpp
void settle_promise_success(PromiseContext* pctx, const std::string& result_data) {
    // 派发到主线程执行
    postToMainThread(pctx->ctx, [pctx, result_data]() {
        JSValue res_val = JS_NewString(pctx->ctx, result_data.c_str());
        
        // 执行 resolve 回调: resolve(res_val)
        JSValue ret = JS_Call(pctx->ctx, pctx->resolve_func, JS_UNDEFINED, 1, &res_val);
        
        // 释放生命周期资源
        JS_FreeValue(pctx->ctx, res_val);
        JS_FreeValue(pctx->ctx, ret);
        JS_FreeValue(pctx->ctx, pctx->resolve_func);
        JS_FreeValue(pctx->ctx, pctx->reject_func);
        JS_FreeValue(pctx->ctx, pctx->promise);
        
        delete pctx;
    });
}
```

### 5.5 事件发布订阅与信号总线 (`JQPublishObject` & `YDALBASEAPI::observer`)

对于连续触发的硬件事件（如笔尖接触传感器扫描中断、WiFi 状态切换、录音数据流到达），官方插件采用 **Signal-Slot** 模式：
1. 原生类继承 `JQPublishObject`，在原型中通过 `JQObjectTemplate::Set` 挂载 `JQSignal` 属性（如 `onlineOCRFinished`）。
2. 前端通过 `instance.onlineOCRFinished.connect(callback)` 注册监听函数。
3. 底层驱动层（如 `YDALBASEAPI::observer::ObserverImpl`）检测到事件时，触发 `emit`，最终由 `JQPublishObject::_Publish` 封送数据并在主线程调用所有已注册的 JS 回调函数。

---

## 6. 生产级原生插件模板工程与跨平台交叉编译实践

本章提供一套可以直接编译、打包、部署并成功在有道 S7 Pro 真机运行的生产级原生插件工程模板：**`libjsapi_sample_device`**。

### 6.1 工程目录结构与文件组织

```
sample_device_plugin/
├── CMakeLists.txt              # CMake 交叉编译配置
├── Makefile                    # 极速原生构建脚本
├── include/
│   ├── quickjs.h               # QuickJS 引擎头文件 (ARM32 适配版)
│   ├── jq_template.h           # JQ 绑定模板头文件 (基于逆向还原)
│   └── device_controller.h     # 硬件设备控制器类声明
├── src/
│   ├── plugin_entry.cpp        # custom_init_jsapis 导出入口
│   └── device_controller.cpp   # C++ 原生业务与线程调度实现
└── js/
    └── DeviceService.js        # 前端调用与生命周期封装
```

### 6.2 ARMv7-A 交叉编译工具链与 `CMakeLists.txt` / `Makefile`

由于 S7 Pro 的 CPU 严格要求硬浮点，必须使用带有 `hf` 后缀的交叉编译链（如 `arm-linux-gnueabihf-g++`）。

#### `CMakeLists.txt`:
```cmake
cmake_minimum_required(VERSION 3.10)
project(sample_device CXX C)

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR arm)

# 强制硬浮点与 NEON 指令集
set(CMAKE_C_FLAGS   "${CMAKE_C_FLAGS}   -march=armv7-a -mtune=cortex-a7 -mfloat-abi=hard -mfpu=neon-vfpv4 -fPIC -O2 -Wall")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -march=armv7-a -mtune=cortex-a7 -mfloat-abi=hard -mfpu=neon-vfpv4 -fPIC -O2 -Wall -std=c++14")

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

# 动态链接平台库
link_directories(
    /usr/lib
    ${CMAKE_CURRENT_SOURCE_DIR}/sysroot/usr/lib
)

add_library(jsapi_sample_device SHARED
    src/plugin_entry.cpp
    src/device_controller.cpp
)

# 链接核心底层库: libfalcon, libjsapi_proxy, libquickjs, pthread
target_link_libraries(jsapi_sample_device
    falcon
    jsapi_proxy
    quickjs
    pthread
    dl
)

# 设置 soname
set_target_properties(jsapi_sample_device PROPERTIES
    OUTPUT_NAME "jsapi_sample_device"
    PREFIX "lib"
    SUFFIX ".so"
)
```

#### `Makefile` (推荐极速构建):
```makefile
CC  := arm-linux-gnueabihf-gcc
CXX := arm-linux-gnueabihf-g++

CFLAGS   := -march=armv7-a -mtune=cortex-a7 -mfloat-abi=hard -mfpu=neon-vfpv4 -fPIC -O2 -Wall -I./include
CXXFLAGS := -march=armv7-a -mtune=cortex-a7 -mfloat-abi=hard -mfpu=neon-vfpv4 -fPIC -O2 -Wall -std=c++14 -I./include
LDFLAGS  := -shared -Wl,-soname,libjsapi_sample_device.so -L./sysroot/usr/lib -lfalcon -ljsapi_proxy -lquickjs -lpthread

TARGET := libjsapi_sample_device.so
SRCS   := src/plugin_entry.cpp src/device_controller.cpp
OBJS   := $(SRCS:.cpp=.o)

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(OBJS) -o $@ $(LDFLAGS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)
```

### 6.3 生产级 C++ 插件完整源码实现

#### 1. 结构声明 (`include/device_controller.h`)
```cpp
#ifndef DEVICE_CONTROLLER_H
#define DEVICE_CONTROLLER_H

#include <string>
#include <thread>
#include <atomic>
#include <functional>
#include "quickjs.h"
#include "jq_template.h"

class DeviceController {
public:
    DeviceController();
    ~DeviceController();

    // 同步调用接口
    std::string getHardwareId();
    int32_t getBatteryLevel();

    // 异步硬件采集 (返回 Promise)
    void startAsyncScan(const JQFunctionCallbackInfo& info);

    // 停止硬件采集
    void stopScan();

private:
    void workerThreadLoop(JSContext* ctx, JSValue resolve_func, JSValue reject_func);

    std::atomic<bool> m_running;
    std::thread m_worker;
};

#endif // DEVICE_CONTROLLER_H
```

#### 2. 控制器实现 (`src/device_controller.cpp`)
```cpp
#include "device_controller.h"
#include <chrono>
#include <sstream>
#include <unistd.h>

DeviceController::DeviceController() : m_running(false) {
}

DeviceController::~DeviceController() {
    stopScan();
}

std::string DeviceController::getHardwareId() {
    return "S7PRO-CV1813H-HW-001";
}

int32_t DeviceController::getBatteryLevel() {
    // 模拟读取 sysfs 节点
    return 98;
}

void DeviceController::stopScan() {
    m_running = false;
    if (m_worker.joinable()) {
        m_worker.join();
    }
}

void DeviceController::startAsyncScan(const JQFunctionCallbackInfo& info) {
    JSContext* ctx = info.GetContext();
    
    // 1. 创建 Promise
    JSValue resolving_funcs[2];
    JSValue promise = JS_NewPromiseCapability(ctx, resolving_funcs);
    
    JSValue resolve_fn = resolving_funcs[0];
    JSValue reject_fn  = resolving_funcs[1];

    stopScan();
    m_running = true;

    // 2. 启动底层 worker 线程处理耗时任务
    m_worker = std::thread(&DeviceController::workerThreadLoop, this, ctx, resolve_fn, reject_fn);

    // 3. 立即向 JS 返回 Promise 实例
    info.GetReturnValue().Set(promise);
}

void DeviceController::workerThreadLoop(JSContext* ctx, JSValue resolve_func, JSValue reject_func) {
    // 模拟底层连续扫描与硬件帧采集 (耗时 500ms)
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    if (!m_running) {
        // 被取消，派发 Reject
        JQuick::sp<JQuick::Looper> looper = JQuick::getJSLooper(ctx);
        JQuick::sp<JQuick::Handler> handler = new JQuick::Handler(looper);
        handler->run(new C11FuncTask([ctx, resolve_func, reject_func]() {
            JSValue err = JS_NewString(ctx, "Scan Cancelled");
            JSValue ret = JS_Call(ctx, reject_func, JS_UNDEFINED, 1, &err);
            JS_FreeValue(ctx, err);
            JS_FreeValue(ctx, ret);
            JS_FreeValue(ctx, resolve_func);
            JS_FreeValue(ctx, reject_func);
        }));
        return;
    }

    // 模拟采集到的识别数据
    std::string scanResult = "{\"text\": \"Hello S7 Pro Native\", \"confidence\": 0.99}";

    // 获取主线程 Looper
    JQuick::sp<JQuick::Looper> looper = JQuick::getJSLooper(ctx);
    JQuick::sp<JQuick::Handler> handler = new JQuick::Handler(looper);

    // 跨线程派发到主线程完成 Promise 结算
    handler->run(new C11FuncTask([ctx, resolve_func, reject_func, scanResult]() {
        JSValue res = JS_NewString(ctx, scanResult.c_str());
        JSValue ret = JS_Call(ctx, resolve_func, JS_UNDEFINED, 1, &res);
        
        JS_FreeValue(ctx, res);
        JS_FreeValue(ctx, ret);
        JS_FreeValue(ctx, resolve_func);
        JS_FreeValue(ctx, reject_func);
    }));
}
```

#### 3. 插件导出入口与类注册 (`src/plugin_entry.cpp`)
```cpp
#include "device_controller.h"
#include <iostream>

// 静态 C++ 包装函数: 构造函数
static void Device_Constructor(const JQFunctionCallbackInfo& info) {
    DeviceController* controller = new DeviceController();
    info.SetOpaque(controller);
}

// 静态 C++ 包装函数: 析构/终结器
static void Device_Finalizer(void* opaque) {
    if (opaque) {
        delete static_cast<DeviceController*>(opaque);
    }
}

// 静态 C++ 包装函数: getHardwareId
static void Device_getHardwareId(const JQFunctionCallbackInfo& info) {
    DeviceController* self = static_cast<DeviceController*>(info.GetOpaque());
    if (self) {
        info.GetReturnValue().Set(self->getHardwareId());
    } else {
        info.GetReturnValue().ThrowTypeError("Invalid DeviceController native instance");
    }
}

// 静态 C++ 包装函数: getBatteryLevel
static void Device_getBatteryLevel(const JQFunctionCallbackInfo& info) {
    DeviceController* self = static_cast<DeviceController*>(info.GetOpaque());
    if (self) {
        info.GetReturnValue().Set(self->getBatteryLevel());
    }
}

// 静态 C++ 包装函数: startAsyncScan
static void Device_startAsyncScan(const JQFunctionCallbackInfo& info) {
    DeviceController* self = static_cast<DeviceController*>(info.GetOpaque());
    if (self) {
        self->startAsyncScan(info);
    }
}

// 模块初始化回调
static int sampleDevice_module_init(JSContext* ctx, JSModuleDef* m) {
    // 1. 创建 DeviceController 函数模板
    JQFunctionTemplate tpl = JQFunctionTemplate::New(ctx, "DeviceController", Device_Constructor, Device_Finalizer);
    
    // 2. 绑定原型方法
    tpl.SetProtoMethod("getHardwareId", Device_getHardwareId);
    tpl.SetProtoMethod("getBatteryLevel", Device_getBatteryLevel);
    tpl.SetProtoMethod("startAsyncScan", Device_startAsyncScan);

    // 3. 构建导出对象
    JSValue export_obj = JS_NewObject(ctx);
    JS_SetPropertyStr(ctx, export_obj, "DeviceController", tpl.GetFunction());

    // 4. 导出为 default
    JS_SetModuleExport(ctx, m, "default", export_obj);
    return 0;
}

// 模块加载器
static JSModuleDef* sampleDevice_loader(JSContext* ctx, const char* module_name) {
    JSModuleDef* m = JS_NewCModule(ctx, module_name, sampleDevice_module_init);
    if (!m) return nullptr;
    JS_AddModuleExport(ctx, m, "default");
    return m;
}

// 全局强制导出契约
extern "C" __attribute__((visibility("default"))) void custom_init_jsapis(void) {
    // 注册模块名称 "sampleDevice"
    registerCModuleLoader("sampleDevice", sampleDevice_loader);
}
```

### 6.4 前端 JavaScript/Vue 封装与异步调用实现 (`DeviceService.js`)

```javascript
/**
 * DeviceService.js - 有道 S7 Pro 原生插件前端接入中台
 */
import sampleDevice from 'sampleDevice';

class DeviceService {
    constructor() {
        if (!sampleDevice || !sampleDevice.DeviceController) {
            throw new Error("Failed to load native plugin: sampleDevice");
        }
        // 实例化 C++ 原生控制器
        this._native = new sampleDevice.DeviceController();
    }

    /**
     * 同步获取硬件唯一标识符
     * @returns {string}
     */
    getHardwareId() {
        return this._native.getHardwareId();
    }

    /**
     * 同步获取当前电量
     * @returns {number}
     */
    getBatteryLevel() {
        return this._native.getBatteryLevel();
    }

    /**
     * 异步启动硬件扫描，支持 Promise 与 await
     * @returns {Promise<{text: string, confidence: number}>}
     */
    async scanHardware() {
        try {
            // 调用 C++ 原生异步 Promise 接口
            const rawJson = await this._native.startAsyncScan();
            return JSON.parse(rawJson);
        } catch (error) {
            console.error("Native Scan failed:", error);
            throw error;
        }
    }
}

// 导出全局单例
export const deviceService = new DeviceService();
export default deviceService;
```

在 Vue 组件中直接使用：
```html
<template>
  <div class="container">
    <div class="header">硬件 ID: {{ hwId }} | 电量: {{ battery }}%</div>
    <button class="scan-btn" @click="handleScan">启动底层硬件识别</button>
    <div class="result" v-if="scanResult">{{ scanResult }}</div>
  </div>
</template>

<script>
import deviceService from './DeviceService.js';

export default {
  data() {
    return {
      hwId: '',
      battery: 0,
      scanResult: ''
    };
  },
  mounted() {
    this.hwId = deviceService.getHardwareId();
    this.battery = deviceService.getBatteryLevel();
  },
  methods: {
    async handleScan() {
      this.scanResult = "正在调用 Linux 原生驱动采集...";
      const res = await deviceService.scanHardware();
      this.scanResult = `识别成功: ${res.text} (置信度: ${res.confidence})`;
    }
  }
};
</script>
```

### 6.5 `.amr` 部署打包、ELF 检查清单与高频陷阱排查避坑指南

将编译生成的 `.so` 集成到小程序应用安装包中，必须遵循以下步骤：

#### 1. 应用包目录布局
```
my_app.amr (ZIP 格式归档)
├── manifest.json               # 微应用清单
├── app.bin                     # 主程序字节码
├── pages/                      # 页面目录
└── libs/                       # 原生动态库目录 (强制!)
    ├── libjsapi_sample_device.so
    └── libextra_driver.so (可选依赖库)
```

#### 2. 编译产物交付前 ELF 关键自检清单
在将 `.so` 复制进 `libs/` 之前，必须在主机执行三项验证：

```bash
# 检查 1: 验证是否为硬浮点 EABI v5
readelf -h libjsapi_sample_device.so | grep Flags
# 正确输出必须包含: Version5 EABI, hard-float ABI

# 检查 2: 验证 custom_init_jsapis 导出
nm -D libjsapi_sample_device.so | grep custom_init_jsapis
# 正确输出必须为: 0000xxxx T custom_init_jsapis

# 检查 3: 验证依赖项
readelf -d libjsapi_sample_device.so | grep NEEDED
# 确保系统依赖仅指向系统库 (libfalcon.so, libquickjs.so, libjsapi_proxy.so, libc.so, libm.so, libpthread.so)
```

#### 3. 常见避坑指南与高频崩溃排查表

| 故障现象 | 根因剖析 (Root Cause) | 解决方案 (Fix) |
| :--- | :--- | :--- |
| **`dlopen failed: ... uses VFP register arguments`** | 编译时使用了软浮点（`softfp` 或默认 `soft`），与 S7 Pro 系统库硬浮点冲突 | 检查编译器参数，确保显式声明 `-mfloat-abi=hard -mfpu=neon-vfpv4` |
| **安装后插件完全不执行** | 导出的初始化函数未加 `extern "C"` 导致 C++ 符号修饰符错乱，`dlsym` 找不到符号 | 在 C++ 入口处显式包裹 `extern "C" __attribute__((visibility("default")))` |
| **多线程调用时随机崩在 `js_malloc` 或 `JS_Call`** | 背景 `std::thread` 违规直接调用了 QuickJS 引擎函数，破坏了引擎单线程堆内存 | 严格使用 `JQuick::getJSLooper(ctx)` 与 `C11FuncTask` 将所有结算派发至主线程 |
| **微应用退出或切换时系统崩溃 `SIGSEGV`** | JS 对象被 GC 释放时，未定义 Finalizer 导致 C++ 悬挂指针；或在 Finalizer 中重复 `free` | 确保 `JSClassDef.finalizer` 与 C++ 析构函数一一对应，严格遵循单所有权模型 |
| **安装时报 `patchelf modifyRPath failed`** | 原生库编译时未包含动态段（启用了过度 strip），或者 `.dynstr` 严重受损 | 禁用 `-Wl,-s` 深度剥离，保留标准动态符号表与 `.dynamic` 段 |
| **应用热升级后调用的仍然是旧版逻辑** | 动态库没有放在 `libs/` 目录，逃逸了 PMS 的 `chrpathSoFiles` 随机化重命名机制 | 必须且只能将所有原生动态库置于 `.amr` 根目录的 `libs/` 子目录下 |

---
*手册结束 (Document End)*
