# 网易有道词典笔 S7 Pro 官方系统 API 与服务子系统全景开发指南
## NetEase Youdao S7 Pro Official APIs & Subsystem Architecture Manual

在完成网易有道词典笔 S7 Pro（硬件代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813 ARMv7-A，系统：Buildroot Linux 5.10）的 Root 权限与免密 ADB 固化后，我们进一步对系统内置固件及阿里 HaaS UI / Falcon 框架进行了全面深度逆向。

**核心结论**：词典笔出厂固件内已经内置了极其丰富、经过硬件加速的成熟底层服务与 JSAPI，**无需也不应该在应用层用从零手写简陋的 UI 组件或重新发明操作系统轮子**。开发者可以直接调用系统已有的输入法键盘、硬件加速视频播放器、音频播放与歌词引擎、网络与系统设置服务。

---

## 一、 系统内置服务应用包全景注册表

系统所有官方应用及底层服务均在 `/oem/secondary/etc/miniapp/resources/local_packages.json` 中统一注册与寻址。应用包为 `.amr` 格式，运行时由 `/usr/bin/miniapp`（PID 171）动态解压并挂载：

| App ID | 名称 | 分类 (Category) | 预置包路径 | 核心暴露能力与系统角色 |
| :--- | :--- | :--- | :--- | :--- |
| `8001666679481944` | **输入法** | `IM_PANEL_DICT` | `presetpkgs/8001666679481944.amr` | **系统全功能软键盘**（全键盘/九宫格/符号/拼音候选词/语音输入） |
| `8001661999525016` | **视频播放器** | `VIDEOPLAYER` | `presetpkgs/8001661999525016.amr` | **硬件加速视频播放**（`softvplayer` / `CVPlayer` 图层映射） |
| `8001650599023931` | **音频播放器** | `MEDIAPLAYER` | `presetpkgs/8001650599023931.amr` | **系统音乐与音频引擎**（`media_player` / LRC 歌词同步解析） |
| `8080272425914438` | **设置** | `SETTING` | `presetpkgs/8080272425914438.amr` | **系统核心设置**（Wi-Fi、蓝牙、背光亮度、音量、存储管理） |
| `8080222501178405` | **下拉菜单** | `TOP_PANEL` | `presetpkgs/8080222501178405.amr` | **顶部控制中心**（亮度滑块、Wi-Fi/蓝牙快捷开关） |
| `8001670668055425` | **录音服务** | `RECORD_SERVICES` | `presetpkgs/8001670668055425.amr` | **双 PDM 麦克风硬件录音与降噪采集** |
| `8080272808953200` | **语音助手** | `VOICE_ASSISTANT` | `presetpkgs/8080272808953200.amr` | **流式语音识别与 AI 问答交互引擎** |
| `8001699004677776` | **Ai-慧眼** | `AI_CAMERA` | `presetpkgs/8001699004677776.amr` | **笔头与前置摄像头视觉流抓取** |
| `8001667273038889` | **有道云盘** | `CLOUDDISK` | `presetpkgs/8001667273038889.amr` | **文件上传下载与网络存储传输** |

---

## 二、 关键官方 API 与子系统接口

### 2.1 官方软键盘与输入法服务子系统 (`IM_PANEL_DICT`)
* **服务 App ID**：`8001666679481944`（分类：`IM_PANEL_DICT`）
* **部署路径**：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001666679481944/a/`
* **底层 C++ 引擎**：内置于 `/usr/lib/libfalcon.so` 中的 `greenui::InputMethodImpl`；
* **应用组件树拓扑**：
  ```
  8001666679481944/a/
  ├── manifest.json                  # 清单元数据 (QuickJS 20200705, page_rotation: inherit)
  ├── app.js.bin                     # 动画帧与样式注入入口
  ├── app-97c7b333.js.bin            # 全局调度器 (theme-y08 / theme-apollo 适配器)
  ├── InputPage-38d8bb4d.js.bin      # Apollo / Y08 平台主输入页面 (关键容器)
  ├── NumberKeyboard-b9891f44.js.bin # 九宫格按键组件 (4x4 阵列，无外部依赖)
  ├── OnlyCharKeyboard-35023e1a.js.bin # 26 键独立组件
  ├── SymbolKeyboard-90c069d9.js.bin # 标点符号与特殊字符面板
  ├── WordsPanel-e084886d.js.bin     # 候选词横向滚动条 (绑定 im.searchWord)
  └── [功能按键组件]                 # CloseButton, CapsLockButton, EnterButton, DeleteButton 等
  ```
* **系统输入服务通信契约 (IPC / JSAPI)**：
  * **字符上屏**：`$falcon.im.commitText(str)`（向当前焦点输入框提交字符或字符串）；
  * **退格删除**：`$falcon.im.deleteSurroundingText(beforeLength, afterLength)`（通常传入 `1, 0` 实现退格）；
  * **编辑器动作触发**：`$falcon.im.sendEditorAction(actionId)`（例如 `6` 对应 `ACTION_DONE` 确认完成）；
  * **全屏编辑模式切换**：`$falcon.im.setFullscreenMode(boolean)`（控制长文本多行全屏编辑视窗）；
  * **中文词库检索接口**：
    ```javascript
    // 调用底层 ime_pinyin 拼音矩阵检索核心
    $falcon.im.searchWord(pinyinChars, function(candidateList) {
        // 返回匹配词列表，例如 ['有道', '幼岛', '邮电']
        this.candidates = candidateList;
    });
    ```
* **第三方应用唤起方式**：通过 Falcon 框架的标准软键盘调度器调用：
  ```js
  // 唤起官方输入法
  $falcon.showSoftInput({
      type: "text", // 或 "number", "symbol"
      placeholder: "请输入搜索内容...",
      onConfirm: (text) => {
          console.log("用户输入内容:", text);
      }
  });
  // 隐藏输入法
  $falcon.hideSoftInput();
  ```

---

### 2.2 MiniApp 进程生命周期与 QuickJS 字节码机制
词典笔所有官方 UI 应用均基于 QuickJS 2020-07-05 编译的二进制字节码运行：

1. **字节码底层格式规范**：
   - 字节码版本头标（Bytecode Version Tag）：单字节 `0x3f`（十进制 63，对应 QuickJS 2020-07-05 源码常量 `DUMP_BYTECODE = 63`）；
   - 编译标志：必须以模块模式编译（`JS_EVAL_TYPE_MODULE | JS_EVAL_FLAG_COMPILE_ONLY`），并使用 `JS_WriteObject(..., JS_WRITE_OBJ_BYTECODE)` 导出；
   - 宿主机交叉编译工具：仓库提供 `host_tools/qjsc` 与 `host_tools/compile_js_bin.py`，支持将 `.js` 源码直接编译为适配设备的 `.js.bin`。

2. **MiniApp 无头进程管理命令行 (`miniapp_cli`)**：
   系统提供专用命令行控制微应用进程生命周期、截图抓取与按键注入，开发过程中无需人工操作屏幕：
   ```bash
   /usr/bin/miniapp_cli start <AppID> [--page]   # 启动指定小程序应用 (例如 8001666679481944)
   /usr/bin/miniapp_cli install <amrPath>        # 安装或热重载 .amr 应用包
   /usr/bin/miniapp_cli uninstall <AppID>        # 卸载指定小程序
   /usr/bin/miniapp_cli capture <save_path.png>  # 截取小程序当前渲染画面
   /usr/bin/miniapp_cli captureFB <save_path>    # 截取 Linux 帧缓冲区原始数据
   /usr/bin/miniapp_cli injectKey <keyCode>      # 向当前活动小程序注入按键事件
   /usr/bin/miniapp_cli memoryUsage              # 监测 QuickJS 虚拟机内存开销
   ```

---

### 2.3 视频播放子系统 (`VIDEOPLAYER` / `CVPlayer`)
* **服务入口**：`8001661999525016`
* **底层硬解驱动库**：`/oem/YoudaoDictPen/output/libs/libyddal_business_cvplayer.so`
  * 直接与 CV1813 SoC 的 VPSS（视频处理子系统）与 VDEC（硬件解码器）对接。
  * 原生 C++ 导出类 `YCVPlayer` / `cvi_player` 核心控制接口：
    ```cpp
    YCVPlayer::setDataSource(const char* url);       // 本地路径或网络流媒体地址
    YCVPlayer::play(int pos_ms);                      // 起始位置播放
    YCVPlayer::pause();                               // 暂停播放
    YCVPlayer::resume();                              // 恢复播放
    YCVPlayer::stop();                                // 停止播放
    YCVPlayer::seek(int pos_ms);                      // 定位跳转
    YCVPlayer::setRate(float rate);                   // 倍速播放 (0.5x, 1.0x, 1.5x, 2.0x)
    YCVPlayer::getRate();                             // 获取当前倍速
    YCVPlayer::setVideoSurface(int x, int y, int h);  // 设置显示层绝对屏幕坐标
    YCVPlayer::videoCrop(int x, int y, int w, int h); // 视口硬件裁剪 (完美契合 240x1020)
    ```
* **JSAPI 扩展层**：
  * `/oem/secondary/etc/miniapp/resources/presetpkgs/8001661999525016.amr` 内置 `libjsapi_softvideo.so`，导出 QuickJS 模块 `softvplayer`（`init()`, `play(path)`, `pause()`, `resume()`, `stop()`, `seek(ms)`）；
  * `/oem/secondary/etc/miniapp/jsapis/libjsapi_export.so` 导出 `CVPlayer` 对象。

---

### 2.4 音频播放与歌词字幕同步 (`MEDIAPLAYER`)
* **服务入口**：`8001650599023931`
* **后台守护进程**：
  * PID 398：`/oem/YoudaoDictPen/output/SoundPlayer`
  * PID 612/646：`/oem/YoudaoDictPen/output/SoundRecord`
* **底层驱动层**：`libyddal_common_soundplayer.so`
  * 专为 AW883XX SmartPA 智能微功放设计，接管 ALSA `hw:1,0`，内置防爆音与音量保护曲线；
* **JSAPI 导出模块 (`libjsapi_mediaplayer.so`)**：
  ```js
  import * as mediaPlayer from 'media_player';

  mediaPlayer.initMediaPlayer();
  mediaPlayer.play("/userdisk/music/song.mp3");
  mediaPlayer.seek(30000); // 跳转到 30 秒
  mediaPlayer.playNextLrc(); // 同步下一句歌词
  mediaPlayer.getSubtitleStatus(); // 获取字幕状态
  mediaPlayer.getPlayBackRate(); // 获取播放倍率
  ```

---

### 2.5 网络、蓝牙与系统设置子系统 (`SETTING`)
* **服务入口**：`8080272425914438`
* **系统守护进程**：
  * `/usr/bin/wifi-manager 1`（自动扫描、SSID 接入、信号监控）；
  * `/usr/bin/bt-manager 1` 与 `/usr/bin/bluealsa`（蓝牙 A2DP 音频源驱动）；
  * `/usr/bin/sysconfig-manager`（持久化参数管理）。
* **JSAPI 导出模块 (`libjsapi_settings.so`)**：
  * 封装了 Wi-Fi 扫描 (`scan`)、加入网络 (`connect`)、网络状态回调；
  * 封装了屏幕背光 PWM（0-255 级）无级平滑调光；
  * 封装了系统存储空间与电池健康监控。

---

### 2.6 系统 IPC 与多应用通信骨干
1. **UBus IPC 总线**（`/usr/bin/ubusd`）：
   * 系统运行状态对象注册（`uevent.power_supply.status`、`uevent.input_subsystem.status`、`uevent.digital_audio_device.status`）；
   * 原生提供 `libubus.so`、`libblobmsg_json.so`，支持跨进程高性能发布/订阅模式。
2. **D-Bus 总线**（`dbus-daemon --system`）：
   * 监听地址 `/var/run/dbus/system_bus_socket`；
   * 托管 `org.bluealsa` 与 `org.bluez`，供蓝牙耳机与外设互联。
3. **共享内存 IPC**（`libyddal_base_ipc.so`）：
   * 基于标准 Linux System V 共享内存（`shmget` / `shmat`），提供进程间图像帧与音频流的高性能零拷贝传输。
4. **Falcon 应用路由协议**：
   * 支持通过 URI 快速调起系统任意预置服务应用：
     ```js
     $falcon.navToApp("8001661999525016", "pages/player/index", { src: "/userdisk/video.mp4" });
     // 或使用标准 URL Scheme 路由:
     navTo("falcon://8001661999525016/pages/player/index?src=/userdisk/video.mp4");
     ```

---

## 三、 基于官方 API 的杀手级应用构建蓝图

| 杀手级应用 | 涉及的核心官方 API / 服务 | 实现路径与设计优势 |
| :--- | :--- | :--- |
| **全功能多格式文件管理器** | Falcon Skia 2D 滚动列表 + `libyddal_base_ipc` + 官方输入法 (`8001666679481944`) | 利用 Skia 2D 实现丝滑 60FPS 纵向长列表滑动；新建/重命名文件时直接唤出官方中文拼音键盘。 |
| **完整网页浏览器** | Falcon 页面容器 + `libcpr` / `libcurl` + 官方输入法 | 地址栏与表单直接接入官方软键盘与语音输入；页面渲染复用 Falcon 矢量字体与图像管线。 |
| **条漫长图阅读器** | Skia 2D 图片解码引擎 + PlutoVG / LunaSVG | 深度契合 240x1020 狭长物理长屏，利用系统级图片缓存实现长条漫画无缝预加载与惯性滚动。 |
| **iPod 音乐播放器** | `media_player` (`8001650599023931`) + `SoundPlayer` | 直接复用官方 LRC 歌词滚动与双语字幕同步组件；音频直通 AW883XX SmartPA，音质与系统原生一致。 |
| **电子相册** | `fbshow` / Falcon Image 渲染管线 + 触控手势 | 支持双向轻扫切图、多级缩放与壁纸一键设置。 |
| **AI 流式语音助手** | 双 PDM 麦克风 (`8001670668055425`) + `streamtts` (`libjsapi_export.so`) + `cpr` SSE 流 | 录音直接走官方低底噪降噪管线，流式文本实时推送到界面，合成语音通过 SmartPA 清晰播放。 |
