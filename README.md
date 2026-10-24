# 网易有道词典笔 S7 Pro (Y08 / CV1813) 深度逆向与全栈开发指南
## NetEase Youdao Dictionary Pen S7 Pro Breakthrough & Developer Manual

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Cvitek%20CV1813-blue.svg)](https://github.com/cubelikeplayDaniel/youdao-dictpen-s7pro-guide)
[![OS](https://img.shields.io/badge/OS-Buildroot%20Linux%205.10-green.svg)](https://github.com/cubelikeplayDaniel/youdao-dictpen-s7pro-guide)

本项目记录了对**网易有道词典笔 S7 Pro**（硬件代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813 ARMv7-A Cortex-A7，操作系统：Buildroot Linux 5.10 + 阿里巴巴 HaaS UI / Falcon 运行时）从**零特权环境**到**永久获得 Root 权限、免密 ADB 直通与无线 SSH 终端**的完整开发与技术解构流程，并提供后续脱离官方框架进行 Linux 原生应用开发的完整技术规范。

---

## 目录
- [一、 设备软硬件架构与设计背景](#一-设备软硬件架构与设计背景)
- [二、 突破思路与方案选型演进](#二-突破思路与方案选型演进)
- [三、 完整突破链条深度解析](#三-完整突破链条深度解析)
  - [3.1 macOS 热点与透明代理搭建](#31-macos-热点与透明代理搭建)
  - [3.2 官方应用商店协议逆向与伪造注入](#32-官方应用商店协议逆向与伪造注入)
  - [3.3 破解关键安装缺陷 (家长管控与版本回退)](#33-破解关键安装缺陷-家长管控与版本回退)
  - [3.4 Falcon 容器特权模型与 Native SO 筛选机制](#34-falcon-容器特权模型与-native-so-筛选机制)
  - [3.5 ELF 符号劫持与 Root Shell 初始化](#35-elf-符号劫持与-root-shell-初始化)
- [四、 永久固化机制 (开机免密 ADB + 无线 SSH)](#四-永久固化机制-开机免密-adb--无线-ssh)
- [五、 原生应用极速开发工作流](#五-原生应用极速开发工作流)
- [六、 官方系统服务与 API 子系统全景](#六-官方系统服务与-api-子系统全景)
- [七、 仓库目录与配套工具集](#七-仓库目录与配套工具集)

---

## 一、 设备软硬件架构与设计背景

- **SoC 芯片**：Cvitek（算能）CV1813H / CV181X ARM Cortex-A7，主频最高 ~1.0 GHz，支持 Hard-Float（`armhf`）。
- **内存与存储**：512MB / 1GB LPDDR3，板载 eMMC 5.1。
- **操作系统**：Buildroot Linux 5.10.4 内核，根文件系统为只读 **EROFS** 分区，数据分区为 **EXT4**（`/userdata` 和 `/userdisk`）。
- **显示面板**：长条形 IPS 彩屏，物理分辨率 **240 × 1020 像素**，系统通过 Framebuffer（`/dev/fb0`）管理，默认硬件旋转角度 **270°**。
- **运行时环境**：系统由 `procd` 直接以 **UID 0 (root)** 特权启动 `/usr/bin/miniapp`。前端运行阿里巴巴 HaaS UI / Falcon 混合引擎（`libfalcon.so`），JS 引擎基于 QuickJS 2020 二进制字节码（`.js.bin`）。
- **出厂安全限制**：
  - `adbd` 守护进程默认开启，但客户端执行 `adb shell` 时被重定向至 `/usr/bin/adb_auth.sh` 强制要求输入动态密码；
  - 精简系统工具链，无 Android 标准组件（无 `pm`、`am`、`apk`、`dpkg`），常规提权工具不可用。

---

## 二、 开发者权限与设备解锁

在进行真机开发与调试前，设备需要开放 root 调试通道与无线 SSH 服务。

为了方便开发者快速上手、降低认知负荷，所有底层提权工具、USB MTP 物理固化脚本与网络透明代理套件已**完全独立至专门仓库维护**：

👉 **[s7pro-device-unlock (S7 Pro 开发者模式激活与调试解锁工具箱)](https://github.com/cubelikeplayDaniel/s7pro-device-unlock)**

* **USB 物理秒开法（强烈推荐）**：无需任何网络代理配置，直接通过 Type-C 数据线将 `skip_login.sh` 等文件拷贝至词典笔的 `/userdisk/skip_re/` 目录，重启后内核自动以 UID 0 (root) 执行，永久开启无线 SSH（密码: `root`）与免密 ADB；
* **局域网应用商店代理法（备选）**：针对 USB 隐藏了测试目录的特定固件批次，使用配套透明代理服务激活。

完成设备解锁后，设备已处于标准的 ARMv7 嵌入式 Linux 可调状态，无需再进行任何逆向破解，直接进入下方原生开发与 MiniApp SDK 流程。

---

## 三、 原生应用极速开发工作流

完成 Root 破门后，**不需要再做任何应用包逆向**。词典笔已变成一台标准的 ARMv7 嵌入式 Linux 终端：

### 1. 终端连接
- **有线 ADB**：
  ```bash
  adb shell
  ```
- **无线 SSH**（连接设备 Wi-Fi IP，如 `192.168.2.2`）：
  ```bash
  ssh root@192.168.2.2
  # 密码: root
  ```

### 2. 原生程序部署
直接通过 ADB 推送编译好的 ARM 架构程序或脚本：
```bash
adb push my_tool /userdata/
adb shell chmod +x /userdata/my_tool
adb shell /userdata/my_tool
```

### 3. 屏幕 Framebuffer (240 × 1020) 极速渲染
系统内置了 `/usr/bin/fbshow` 工具，支持命令行秒刷 PNG 图片到长条屏：
```bash
fbshow /path/to/image.png /dev/fb0
```
或直接通过 C/Python/Go 向 `/dev/fb0` 写入 32 位 ARGB 像素数据，构建轻量 GUI（如 LVGL、SDL）。

### 4. 交叉编译与 SDK 快速上手 (Native Toolchain)

1. **提取设备端 Sysroot 动态库与头文件**：
   ```bash
   ./scripts/extract_sysroot.sh
   ```
2. **使用 CMake 进行交叉编译**：
   ```bash
   cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-cv1813.cmake
   cmake --build build
   ```
3. **一键快速部署并远程执行**：
   ```bash
   # 有线 ADB 部署
   ./scripts/deploy.sh build/examples/01_hello_hardware/hello_hardware /userdata/bin/ --run

   # 无线 SSH 部署
   ./scripts/deploy.sh build/examples/01_hello_hardware/hello_hardware /userdisk/bin/ --ip 192.168.2.2 --run
   ```
4. **编译并部署 Go 原生运行时 (`s7pro_runner`)**：
   ```bash
   cd host_tools/runner && ./build.sh
   ./scripts/deploy.sh s7pro_runner /userdata/bin/
   ```

### 5. 桌面卡片进入与前台切换机制 (App Card Lifecycle)

通过应用商店安装的微应用卡片，可实现前后台进程调度与显示切换：
1. **点击卡片启动**：桌面点击图标，Falcon 容器加载 Native SO 并触发 `/userdata/app/default/init.sh`；
2. **硬件接管**：后台运行 `s7pro_runner`，向官方前台发送 `SIGSTOP` 信号挂起前台进程，接管 Framebuffer（`/dev/fb0`）；
3. **输入事件监听**：`s7pro_runner` 监听 `/dev/input/by-path/gpio-keys`（物理 Home 键）与 `/dev/input/by-path/axs_ts`（屏幕触控）；
4. **恢复桌面**：按下按键、点击屏幕或达到 15 秒超时时，向挂起的官方进程发送 `SIGCONT` 信号，恢复原桌面进程运行。

---

## 六、 官方系统服务与 API 子系统全景

词典笔出厂固件（`/oem/secondary/etc/miniapp/`、`/usr/lib/libfalcon.so`、`/oem/YoudaoDictPen/output/libs/`）包含以下系统服务与硬件加速接口：

1. **输入法服务 (`8001666679481944` / `greenui::InputMethodImpl`)**：
   - 包含 QWERTY 全键盘、九宫格、符号面板、拼音候选词推荐与语音转文字接口；
   - 系统调用接口：`$falcon.showSoftInput({ type, placeholder, onConfirm })`。
2. **视频播放服务 (`8001661999525016` / `CVPlayer` & `softvplayer`)**：
   - 包含硬件解码库 `libyddal_business_cvplayer.so`，对接 CV1813 VPSS/VDEC 硬件单元；
   - 支持图层视口硬件裁剪（`videoCrop`）、倍速播放（`setRate`）与图层定位（`setVideoSurface`）。
3. **音频播放服务 (`8001650599023931` / `media_player` & `SoundPlayer`)**：
   - 守护进程 `/oem/YoudaoDictPen/output/SoundPlayer` 管控 AW883XX SmartPA 智能功放（`hw:1,0`）；
   - 提供 LRC 歌词解析与字幕同步接口（`playNextLrc`、`getSubtitleStatus`）。
4. **网络与系统设置 (`8080272425914438` / `libjsapi_settings.so`)**：
   - 常驻 `wifi-manager` 与 `bt-manager`，提供 Wi-Fi/蓝牙接入与背光 PWM 调光接口。

> 📖 **完整官方 API 规范与子系统手册**：详见 [docs/s7pro_official_api_guide.md](docs/s7pro_official_api_guide.md)。

---

## 七、 仓库目录与配套工具集

```
.
├── LICENSE                        # MIT 开源许可证
├── README.md                      # 全流程技术复盘文档 (本文件)
├── CMakeLists.txt                 # SDK 顶层 CMake 构建配置
├── cmake/
│   └── arm-cv1813.cmake          # ARMv7-A Cortex-A7 交叉编译工具链定义
├── docker/
│   └── Dockerfile.sdk            # 统一交叉编译 SDK 容器镜像配置
├── scripts/
│   ├── extract_sysroot.sh        # 设备端 sysroot 自动化提取与软链接修复工具
│   ├── deploy.sh                 # 有线 ADB / 无线 SSH 一键极速部署与执行脚本
│   ├── display_image.sh          # 屏幕图像快速刷新工具
│   └── restore_official_ui.sh    # 官方词典界面一键恢复工具
├── examples/
│   └── 01_hello_hardware/        # 硬件信息与 Framebuffer 探测示例源码
├── docs/
│   ├── s7pro_official_api_guide.md # 官方系统 API、服务子系统与组件架构开发指南
│   ├── s7pro_developer_guide.md  # 详细硬件接口、驱动拓扑与外设开发指南
│   └── fb_verify.png             # 物理屏幕 240x1020 真实回读截图
├── host_tools/
│   ├── appstore_server.py        # macOS 端透明代理与应用商店拦截下发服务器
│   ├── patch_so.py               # ELF 动态库 Native Hook 自动修补工具
│   ├── quickjs_atom_tool.py      # QuickJS 字节码 (.js.bin) 原子表解析器
│   └── runner/                   # 原生 App 进退与输入监听守护程序 (Go)
│       ├── main.go
│       └── build.sh
├── device_payload/
│   ├── skip_login.sh             # 设备端永久开机固化执行脚本
│   ├── adb_auth.sh               # 永久放行的 mock adb_auth 脚本
│   └── shadow                   # 固化 root 密码为 root 的 shadow 配置文件
└── certs/
    └── appstore_cert_gen.sh      # 多域名 SAN 自签名 SSL 证书生成脚本
```

---

## 八、 厂商官方研发级 SDK 深度逆向参考手册索引

针对有道 S7 Pro 搭载的阿里 HaaS UI / Falcon 混合引擎与 CV1813H 芯片硬件体系，本项目通过全量二进制反汇编、符号追踪与数据流分析，编撰了一整套媲美官方内部研发级的专项架构指南与技术参考手册：

| 领域 / 核心子系统 | 对应技术参考手册与权威文档 | 核心技术亮点与反汇编解析范围 |
| :--- | :--- | :--- |
| **原生组件与 VDOM 布局引擎** | [docs/falcon_native_components_and_vdom_layout_engine_manual.md](docs/falcon_native_components_and_vdom_layout_engine_manual.md) | `ComponentRegistry` 原生注册表、Yoga Flexbox 排版算法、`greenui::ScrollView` 惯性滚动物理衰减 |
| **原生事件循环与定时调度引擎** | [docs/falcon_event_loop_looper_and_timer_scheduling_manual.md](docs/falcon_event_loop_looper_and_timer_scheduling_manual.md) | `JQuick::Looper` epoll/eventfd 机制、QuickJS 微任务清空、`Choreographer` Vsync 帧同步 |
| **图形渲染管线、Skia 与 FB0** | [docs/falcon_graphics_pipeline_skia_and_fb0_manual.md](docs/falcon_graphics_pipeline_skia_and_fb0_manual.md) | ARM NEON `yd_l_rotate90_S32` 4×4 像素转置、Skia 脏矩形求并双缓冲、`FBIOPAN_DISPLAY` 零撕裂刷新 |
| **安装包规范、PMS 与沙箱隔离** | [docs/falcon_packaging_manifest_signature_and_pms_manual.md](docs/falcon_packaging_manifest_signature_and_pms_manual.md) | `.amr` PKZIP 归档规范、A/B 双槽位轮换升级、`patchelf_rpath_deps` 运行时链接修补与权限白名单 |
| **官方内置应用反编译与架构模式** | [docs/falcon_official_apps_architectural_patterns_and_case_studies.md](docs/falcon_official_apps_architectural_patterns_and_case_studies.md) | 41 款官方内置应用全景解构、`$falcon.App`/`$falcon.Page` 双阶生命周期、Launcher 过滤注入 |
| **资源、图片解码与字体引擎** | [docs/falcon_resource_image_font_and_assets_pipeline_manual.md](docs/falcon_resource_image_font_and_assets_pipeline_manual.md) | 4MB 内存上限 LRU 缓存、LunaSVG 矢量渲染、FreeType 字体阶梯 fallback 与 WebP 避坑 |
| **硬件扫描传感器、CIS 与 OCR 管线** | [docs/falcon_scanner_cis_sensor_and_ocr_subsystem_manual.md](docs/falcon_scanner_cis_sensor_and_ocr_subsystem_manual.md) | 320×152 单通道灰度 CIS 传感器、96 槽 DMA 环形缓冲区、CV1813H 端侧 TPU 硬件加速 OCR |
| **音频解码管线、ALSA 与音频焦点** | [docs/falcon_audio_media_decoder_and_hardware_playback_manual.md](docs/falcon_audio_media_decoder_and_hardware_playback_manual.md) | AW883XX SmartPA 硬件节点、POSIX 共享内存双轨播放、WSOLA 变速不变调与 8.4ms 硬件截断 |
| **电源管理、WakeLock、调频与电池** | [docs/falcon_power_management_wakelock_and_battery_manual.md](docs/falcon_power_management_wakelock_and_battery_manual.md) | AXP2101 PMIC、`/sys/power/wake_lock`、1.0 GHz 固定频点决策、20 kHz 超声频 PWM 背光防啸叫 |
| **存储子系统、SQLite 与 KV 持久化** | [docs/falcon_storage_sqlite_and_kv_persistence_manual.md](docs/falcon_storage_sqlite_and_kv_persistence_manual.md) | SPI NAND/eMMC 15 分区、`sharedpreferences` 内存散列、原生 SQLite 驱动与 WAL 锁避让 |
| **网络通信栈、Wi-Fi 与 TLS/HTTPS** | [docs/falcon_network_wifi_tls_and_cloud_api_manual.md](docs/falcon_network_wifi_tls_and_cloud_api_manual.md) | `wpa_supplicant` 控制套接字、`ubus` 状态机、6 并发任务队列、mbedtls 双向握手与 WebSocket |
| **语音助手 ASR、VAD 与口语跟读评测** | [docs/falcon_voice_assistant_asr_and_speech_evaluation_manual.md](docs/falcon_voice_assistant_asr_and_speech_evaluation_manual.md) | `libcapt.so` 8.9MB Kaldi/MNN 离线评测引擎、双 PDM 麦克风 AFE 降噪、800ms VAD 断句与 RecordService |
| **QuickJS 字节码虚拟机与模块** | [docs/falcon_quickjs_module_loader_and_bytecode_protocol.md](docs/falcon_quickjs_module_loader_and_bytecode_protocol.md) | QuickJS 2020 字节码 Tag/Flag 协议、ES6 模块动态导入机制、JSFM 跨语言通道 |
| **触控输入、手势识别与双向几何** | [docs/falcon_touch_input_event_and_gesture_subsystem_manual.md](docs/falcon_touch_input_event_and_gesture_subsystem_manual.md) | AXS15205 驱动剪裁边界（$X_{raw} \le 170$ 物理限制）、Linux Multi-Touch 协议 B、长按/双击手势 |
| **页面生命周期与路由导航体系** | [docs/falcon_page_lifecycle_and_router_navigation_manual.md](docs/falcon_page_lifecycle_and_router_navigation_manual.md) | 导航栈压栈/出栈状态机、`setSupportTopPanel` 顶部状态栏避让、返回键与侧滑手势拦截 |
| **系统守护进程 IPC、Domain Socket 与事件总线** | [docs/falcon_daemon_ipc_and_event_bus_manual.md](docs/falcon_daemon_ipc_and_event_bus_manual.md) | `miniapp-dbg.socket` 15 大端点、`JQPublishObject` 红黑树快照隔离、D-Bus/Ubus 桥接与 WAL 历史库 |
| **Native C++ 插件与 JSAPI 扩展架构** | [docs/falcon_native_cpp_plugin_and_jsapi_extension_manual.md](docs/falcon_native_cpp_plugin_and_jsapi_extension_manual.md) | ARMv7-A 硬浮点 ABI、Patchelf 动态段重写、10位随机后缀隔离、QuickJS JSValue 封送与 Opaque 绑定 |
| **原生硬件 JSAPI 与系统 IPC 总线** | [docs/falcon_native_hardware_jsapi_and_ipc_manual.md](docs/falcon_native_hardware_jsapi_and_ipc_manual.md) | `libjsapi_export_core.so` 符号表、`JQSignal` 响应式总线、Unix Domain Sockets 守护通信 |
| **OTA 固件更新、A/B 分区容灾与 Bootloader** | [docs/falcon_ota_update_ab_partition_recovery_and_bootloader_manual.md](docs/falcon_ota_update_ab_partition_recovery_and_bootloader_manual.md) | eMMC 15分区拓扑、`misc` 分区 AVB `\0AB0` 结构体、U-Boot 容灾回滚与 Adups FOTA 块差分 |
| **离线词典检索、端侧 NMT 与汉字矢量笔顺** | [docs/falcon_offline_dict_nmt_and_translation_engine_manual.md](docs/falcon_offline_dict_nmt_and_translation_engine_manual.md) | `.dat` 专有双模 XOR 混淆、两级分桶稀疏索引、CV1813 TPU 加速 Tiny-Transformer 与骨骼笔顺 |
| **重力传感器 Gsensor、握姿识别与硬件遥测** | [docs/falcon_gsensor_orientation_and_hardware_telemetry_manual.md](docs/falcon_gsensor_orientation_and_hardware_telemetry_manual.md) | I2C-1 SC7A20、六面体空间朝向、左右手 180° 视口转置、NEON 像素翻转与抬笔唤醒 |
| **蓝牙通信协议栈、BLE GATT 与 A2DP HAL** | [docs/falcon_bluetooth_stack_ble_and_a2dp_subsystem_manual.md](docs/falcon_bluetooth_stack_ble_and_a2dp_subsystem_manual.md) | SKW 4线 UART 1.5Mbps、BlueZ D-Bus 桥接、BlueALSA A2DP 发射、AVRCP 反控与 GB18030 转码 |
| **安全沙箱机制、代码完整性与动态链接器** | [docs/falcon_security_sandbox_integrity_and_dynamic_linker_manual.md](docs/falcon_security_sandbox_integrity_and_dynamic_linker_manual.md) | UID 0 特权模型、空证书绕过、版本回退检测、NixOS patchelf 运行时重写与 Native 沙箱穿透 |
| **输入法服务、软键盘与拼音输入引擎** | [docs/falcon_ime_virtual_keyboard_and_input_method_engine_manual.md](docs/falcon_ime_virtual_keyboard_and_input_method_engine_manual.md) | 双窗口图层隔离、Google Pinyin 矩阵搜索算法、`greenui::EditText` 视口自动避让与按键连击 |
| **异常崩溃防御、硬件/软件看门狗与 LogManager** | [docs/falcon_crash_handling_watchdog_and_logmanager_manual.md](docs/falcon_crash_handling_watchdog_and_logmanager_manual.md) | `sigaltstack` 栈溢出保护、10槽位 Tombstone、Breakpad Minidump、ANR 5s 检测与看门狗复位 |
| **摄像头视觉采集、条码识别与畸变矫正** | [docs/falcon_camera_vision_and_barcode_scanning_manual.md](docs/falcon_camera_vision_and_barcode_scanning_manual.md) | 双光学通道、96槽环形显存、Surface 挖洞黑科技、Bradley-Roth 自适应二值化与相位相干拼接 |
| **视频播放、硬件 VDEC/VPSS 解码器与 CVPlayer** | [docs/falcon_video_hardware_decoding_cvplayer_and_vpss_manual.md](docs/falcon_video_hardware_decoding_cvplayer_and_vpss_manual.md) | H.264 VPU 硬解、VPSS 270°硬件转置、ION 显存映射、Surface 挖洞 OSD 叠加与 ALSA 音画同步 |
| **硬件按键驱动、GPIO 中断与笔尖微动开关** | [docs/falcon_gpio_keys_hardware_interrupt_and_button_driver_manual.md](docs/falcon_gpio_keys_hardware_interrupt_and_button_driver_manual.md) | GPIOA_14/18 中断拓扑、16 字节 ABI 对齐、三阶段 KeyEvent 分发、600ms 长按 / 300ms 双击状态机与固件 Typo 兼容 |
| **双 PDM 麦克风录音、AFE 降噪与音频输入管线** | [docs/falcon_audio_recording_mic_array_and_afe_subsystem_manual.md](docs/falcon_audio_recording_mic_array_and_afe_subsystem_manual.md) | PDM 3.072 MHz 过采样、GSC 波束成形 NEON 加速、AEC 回声消除、POSIX 共享内存零拷贝与 RecordService RPC |
| **状态栏、下拉控制中心与系统通知架构** | [docs/falcon_statusbar_notification_and_dropdown_panel_manual.md](docs/falcon_statusbar_notification_and_dropdown_panel_manual.md) | Z-Index 5000 状态栏、8000 下拉面板、`setSupportTopPanel` 沉浸式避让、图标注册与通知事件总线 |
| **全景踩坑排错与避坑防御指南** | [docs/falcon_miniapp_pitfalls_and_failure_prevention.md](docs/falcon_miniapp_pitfalls_and_failure_prevention.md) | 二十一项黄金防错清单：Yoga 弹性流塌陷、低 DPI 摩尔纹消解、多模触控消解状态机与 MTP 沙箱 |
| **原生 Image 架构与内存优化** | [docs/falcon_image_subsystem_and_memory_optimization.md](docs/falcon_image_subsystem_and_memory_optimization.md) | 474px 硬件点对点直通渲染、WebP 后台转码守护进程、Skia 脏矩形与双转换进度条架构 |
| **原生 19 核心组件与 CSS 规范** | [docs/falcon_miniapp_component_and_css_reference.md](docs/falcon_miniapp_component_and_css_reference.md) | `greenui` 原生控件集、CSS 盒模型约束与属性白名单全量速查 |
| **Vue SFC 编译器与 VDOM 架构** | [docs/falcon_vue_compiler_and_vdom_architecture.md](docs/falcon_vue_compiler_and_vdom_architecture.md) | 模板 AST 解析、render 函数转译与 QuickJS 字节码生成机制 |
| **BindingX 物理动效与手势引擎** | [docs/falcon_bindingx_physics_and_animation_guide.md](docs/falcon_bindingx_physics_and_animation_guide.md) | 60FPS 原生手势动力学、插值公式与高性能动画绑定 |
| **现代化构建工具链与脚手架** | [docs/falcon_miniapp_vite_rollup_toolchain_guide.md](docs/falcon_miniapp_vite_rollup_toolchain_guide.md) | 基于 Vite/Rollup 与 QuickJS 的现代化编译与热重载流 |
| **原生 JSAPI 与系统服务全量调用字典** | [docs/falcon_native_jsapi_and_system_services_manual.md](docs/falcon_native_jsapi_and_system_services_manual.md) | 词典笔原生软硬件 JSAPI 与底层系统服务全量接口字典 |
| **官方系统服务 RPC 通信指南** | [docs/falcon_ipc_service_rpc_communication_guide.md](docs/falcon_ipc_service_rpc_communication_guide.md) | Falcon IPC 总线机制、Unix Domain Socket 服务契约与消息流 |
| **TTS 语音合成与低延迟发音引擎** | [docs/falcon_tts_audio_synthesis_and_voice_dict_manual.md](docs/falcon_tts_audio_synthesis_and_voice_dict_manual.md) | TTS 语音合成、离线发音词库与低延迟音频播放子系统深度逆向指南 |
| **桌面启动器与多屏滑动卡片架构** | [docs/falcon_launcher_architecture_and_card_slider_manual.md](docs/falcon_launcher_architecture_and_card_slider_manual.md) | 系统桌面启动器 Launcher、PagesSlider 多屏滑动与卡片管理 |
| **官方原生 MiniApp 全生态开发教程** | [docs/s7pro_miniapp_master_tutorial.md](docs/s7pro_miniapp_master_tutorial.md) | 全景开发实战教程：双阶生命周期、Native 双列瀑布流、双向触控、资源管控与避坑规范 |

---

## 开源许可证 / License
本项目采用 [MIT License](LICENSE) 开源许可协议。

---

## 免责声明 / Disclaimer
本项目仅供嵌入式 Linux 系统安全研究、硬件底层适配及设备所有者自研学习使用。请勿用于未授权的商业或恶意用途。
