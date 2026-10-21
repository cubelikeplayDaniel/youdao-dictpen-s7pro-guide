# 网易有道词典笔 S7 Pro 官方系统 API 与服务子系统技术指南
## NetEase Youdao S7 Pro Official APIs & Subsystem Architecture Manual

本文档记录网易有道词典笔 S7 Pro（硬件代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813 ARMv7-A，内核：Linux 5.10.4）系统内置服务、底层 C/C++ 驱动库、MiniApp 运行环境及 IPC 通信接口技术规范。

系统架构特征如下：
1. **底层引擎服务**：出厂固件预置了多媒体硬件解码、音频功放管理、网络连接以及基于有道词库的拼音检索服务，驻留于 `/usr/lib` 与 `/oem` 目录；
2. **应用执行环境**：系统 UI 基于阿里 HaaS UI / Falcon 轻量级框架运行，采用 QuickJS 2020-07-05 编译的二进制字节码（`.js.bin`）；
3. **系统集成模式**：自研应用可直接通过 Falcon JSAPI、UBus、D-Bus 等总线接入系统底层服务，前端视图层可针对 1020 × 240 物理屏幕进行自主排版与交互设计。

---

## 一、 系统内置服务应用包注册表

系统所有官方应用及底层服务均在 `/oem/secondary/etc/miniapp/resources/local_packages.json` 中统一注册与寻址。应用包为 `.amr` 格式（标准 zip 压缩归档），运行时由 `/usr/bin/miniapp`（PID 171）动态解压并挂载至 `/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/a/`：

| App ID | 名称 | 分类 (Category) | 预置包路径 | 系统职责与底层能力 |
| :--- | :--- | :--- | :--- | :--- |
| `8001666679481944` | **输入法** | `IM_PANEL_DICT` | `presetpkgs/8001666679481944.amr` | 系统软键盘（全键盘/九宫格/符号/拼音词库检索） |
| `8001661999525016` | **视频播放器** | `VIDEOPLAYER` | `presetpkgs/8001661999525016.amr` | 硬件加速视频播放（`softvplayer` / `CVPlayer` 图层映射） |
| `8001650599023931` | **音频播放器** | `MEDIAPLAYER` | `presetpkgs/8001650599023931.amr` | 音频播放与 LRC 歌词同步（`media_player`） |
| `8080272425914438` | **设置** | `SETTING` | `presetpkgs/8080272425914438.amr` | 系统基础设置（Wi-Fi、蓝牙、背光亮度、音量、存储管理） |
| `8080222501178405` | **下拉菜单** | `TOP_PANEL` | `presetpkgs/8080222501178405.amr` | 顶部状态栏与控制中心 |
| `8001670668055425` | **录音服务** | `RECORD_SERVICES` | `presetpkgs/8001670668055425.amr` | PDM 双麦克风硬件录音与降噪采集 |
| `8080272808953200` | **语音助手** | `VOICE_ASSISTANT` | `presetpkgs/8080272808953200.amr` | 流式语音识别与问答引擎 |
| `8001699004677776` | **Ai-慧眼** | `AI_CAMERA` | `presetpkgs/8001699004677776.amr` | 摄像头视频流采集与图像处理 |
| `8001667273038889` | **有道云盘** | `CLOUDDISK` | `presetpkgs/8001667273038889.amr` | 文件上传下载与网络存储传输 |

---

## 二、 核心服务子系统与 API 接口规范

### 2.1 软键盘与输入法服务子系统 (`IM_PANEL_DICT`)
* **服务 App ID**：`8001666679481944`（分类：`IM_PANEL_DICT`）
* **运行目录**：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001666679481944/a/`
* **底层 C++ 引擎**：`/usr/lib/libfalcon.so` 中的 `greenui::InputMethodImpl`
* **原厂组件包拓扑**：
  ```
  8001666679481944/a/
  ├── manifest.json                  # 元数据 (QuickJS 20200705, page_rotation: inherit)
  ├── app.js.bin                     # 入口及样式注入
  ├── app-97c7b333.js.bin            # 全局调度器 (theme-y08 / theme-apollo 适配器)
  ├── InputPage-38d8bb4d.js.bin      # Apollo / Y08 平台主输入页面
  ├── NumberKeyboard-b9891f44.js.bin # 九宫格按键组件
  ├── OnlyCharKeyboard-35023e1a.js.bin # 26 键独立组件
  ├── SymbolKeyboard-90c069d9.js.bin # 标点符号与特殊字符面板
  ├── WordsPanel-e084886d.js.bin     # 候选词横向滚动条 (绑定 im.searchWord)
  └── [功能键组件]                   # CloseButton, CapsLockButton, EnterButton, DeleteButton 等
  ```
* **系统输入通信契约 (IPC / JSAPI)**：
  * **字符上屏**：`$falcon.im.commitText(str)`
  * **退格删除**：`$falcon.im.deleteSurroundingText(beforeLength, afterLength)`（通常传入 `1, 0`）
  * **编辑器动作**：`$falcon.im.sendEditorAction(actionId)`（例如 `6` 对应 `ACTION_DONE`）
  * **全屏编辑模式**：`$falcon.im.setFullscreenMode(boolean)`
  * **中文词库检索接口**：
    ```javascript
    $falcon.im.searchWord(pinyinChars, function(candidateList) {
        // candidateList 为拼音检索候选词数组
        this.candidates = candidateList;
    });
    ```
* **外部应用唤起软键盘接口**：
  ```javascript
  $falcon.showSoftInput({
      type: "text", // "number" | "symbol"
      placeholder: "请输入搜索内容...",
      onConfirm: (text) => {
          console.log("输入内容:", text);
      }
  });
  $falcon.hideSoftInput();
  ```

---

### 2.2 MiniApp 运行环境与 QuickJS 字节码规范
系统 UI 应用基于 QuickJS 2020-07-05 编译的二进制字节码（`.js.bin`）执行：

1. **字节码格式规范**：
   - **版本头标 (Bytecode Version Tag)**：单字节 `0x3f`（十进制 63，对应源码常量 `DUMP_BYTECODE = 63`）；
   - **编译标志**：必须以模块模式编译（`JS_EVAL_TYPE_MODULE | JS_EVAL_FLAG_COMPILE_ONLY`），使用 `JS_WriteObject(..., JS_WRITE_OBJ_BYTECODE)` 序列化；
   - **编译工具**：仓库提供 `host_tools/qjsc` 与 `host_tools/compile_js_bin.py`。

2. **MiniApp 进程管理命令行 (`miniapp_cli`)**：
   ```bash
   /usr/bin/miniapp_cli start <AppID> [--page]   # 启动应用或指定页面
   /usr/bin/miniapp_cli install <amrPath>        # 安装或热重载 .amr 应用包
   /usr/bin/miniapp_cli uninstall <AppID>        # 卸载指定小程序
   /usr/bin/miniapp_cli capture <save_path.png>  # 截取小程序当前渲染画面 (输出 1020x240 PNG)
   /usr/bin/miniapp_cli captureFB <save_path>    # 截取帧缓冲区原始数据
   /usr/bin/miniapp_cli injectKey <keyCode>      # 注入按键事件
   /usr/bin/miniapp_cli memoryUsage              # 查询 QuickJS 内存使用情况
   ```

---

### 2.3 视频播放子系统 (`VIDEOPLAYER` / `CVPlayer`)
* **服务 App ID**：`8001661999525016`
* **硬件解码驱动库**：`/oem/YoudaoDictPen/output/libs/libyddal_business_cvplayer.so`
  * 对接 CV1813 SoC 的 VPSS（视频处理子系统）与 VDEC（硬件解码器）。
  * 原生 C++ 类 `YCVPlayer` / `cvi_player` 控制接口：
    ```cpp
    YCVPlayer::setDataSource(const char* url);       // 本地路径或流媒体 URL
    YCVPlayer::play(int pos_ms);                      // 起始位置播放
    YCVPlayer::pause();                               // 暂停
    YCVPlayer::resume();                              // 恢复
    YCVPlayer::stop();                                // 停止
    YCVPlayer::seek(int pos_ms);                      // 绝对位置跳转
    YCVPlayer::setRate(float rate);                   // 倍速设置 (0.5 ~ 2.0)
    YCVPlayer::getRate();                             // 获取倍速
    YCVPlayer::setVideoSurface(int x, int y, int h);  // 设置输出视口绝对屏幕坐标
    YCVPlayer::videoCrop(int x, int y, int w, int h); // 视口硬件裁剪
    ```
* **JSAPI 扩展层**：
  * `8001661999525016.amr` 内置 `libjsapi_softvideo.so`，导出 QuickJS 模块 `softvplayer`（`init()`, `play(path)`, `pause()`, `resume()`, `stop()`, `seek(ms)`）；
  * `/oem/secondary/etc/miniapp/jsapis/libjsapi_export.so` 导出 `CVPlayer` 对象。

---

### 2.4 音频播放与歌词字幕同步 (`MEDIAPLAYER`)
* **服务 App ID**：`8001650599023931`
* **守护进程**：
  * PID 398：`/oem/YoudaoDictPen/output/SoundPlayer`
  * PID 612/646：`/oem/YoudaoDictPen/output/SoundRecord`
* **驱动层**：`libyddal_common_soundplayer.so`
  * 对接 AW883XX SmartPA 智能功放，独占 ALSA `hw:1,0`，内置防爆音与音量限制曲线；
* **JSAPI 导出模块 (`libjsapi_mediaplayer.so`)**：
  ```javascript
  import * as mediaPlayer from 'media_player';

  mediaPlayer.initMediaPlayer();
  mediaPlayer.play("/userdisk/music/song.mp3");
  mediaPlayer.seek(30000);          // 跳转至 30000ms
  mediaPlayer.playNextLrc();         // 触发下一句歌词
  mediaPlayer.getSubtitleStatus();   // 获取字幕解析状态
  mediaPlayer.getPlayBackRate();     // 获取当前播放倍率
  ```

---

### 2.5 网络、蓝牙与系统设置子系统 (`SETTING`)
* **服务 App ID**：`8080272425914438`
* **守护进程**：
  * `/usr/bin/wifi-manager 1`（Wi-Fi 扫描与状态监控）；
  * `/usr/bin/bt-manager 1` 与 `/usr/bin/bluealsa`（蓝牙 A2DP 音频源驱动）；
  * `/usr/bin/sysconfig-manager`（系统参数持久化配置）。
* **JSAPI 导出模块 (`libjsapi_settings.so`)**：
  * 提供 Wi-Fi 扫描 (`scan`)、连接 (`connect`)、网络状态回调接口；
  * 提供屏幕背光 PWM（0-255）调光接口；
  * 提供存储与电池状态监控接口。

---

### 2.6 系统 IPC 与跨进程通信
1. **UBus IPC 总线**（`/usr/bin/ubusd`）：
   * 注册对象：`uevent.power_supply.status`、`uevent.input_subsystem.status`、`uevent.digital_audio_device.status`；
   * 提供 `libubus.so` 与 `libblobmsg_json.so`，支持跨进程发布/订阅模式。
2. **D-Bus 总线**（`dbus-daemon --system`）：
   * Socket 地址：`/var/run/dbus/system_bus_socket`；
   * 托管 `org.bluealsa` 与 `org.bluez` 接口。
3. **共享内存 IPC**（`libyddal_base_ipc.so`）：
   * 基于 Linux System V 共享内存（`shmget` / `shmat`），用于进程间图像帧与音频流传输。
4. **Falcon 应用路由协议**：
   * 支持通过 URI 调起系统预置应用：
     ```javascript
     $falcon.navToApp("8001661999525016", "pages/player/index", { src: "/userdisk/video.mp4" });
     // 或使用 URL Scheme 格式:
     navTo("falcon://8001661999525016/pages/player/index?src=/userdisk/video.mp4");
     ```

---

## 三、 系统服务在各应用场景中的接口映射

| 业务功能 | 涉及系统服务与底层模块 | 接口特性与技术路径 |
| :--- | :--- | :--- |
| **双列瀑布流漫画阅读器** | Framebuffer 直接渲染 / Skia 2D + `axs_ts` 触控 | 针对 1020x240 横屏实现双列长卷瀑布流布局；接入 `/dev/input/event3` 实现双击与双指手势缩放；采用滑动窗口释放已滑出视口的像素内存。 |
| **全功能多格式文件管理器** | Falcon 列表组件 + `libyddal_base_ipc` + 输入法 IPC (`8001666679481944`) | 基于 Skia 2D 实现文件长列表平滑滚动；重命名与检索时调用 `$falcon.showSoftInput()` 唤起软键盘。 |
| **轻量级网页浏览器** | Falcon 页面容器 + `libcpr` / `libcurl` + 输入法 IPC | 表单与地址栏输入接入输入法服务；网络通信复用系统 curl 动态库。 |
| **本地音频播放器** | `media_player` (`8001650599023931`) + `SoundPlayer` | 音频输出至 ALSA `hw:1,0`（AW883XX 功放）；解析 LRC 歌词时间戳实现同步滚动。 |
| **电子相册与壁纸中心** | Falcon Image 渲染管线 + `libjsapi_settings.so` | 利用系统图像解码器实现手势翻页与多级缩放；通过 settings 接口调节屏幕背光。 |
| **AI 实时语音助手** | 录音服务 (`8001670668055425`) + `streamtts` (`libjsapi_export.so`) | 双 PDM 麦克风硬件降噪采集；调用流式 TTS 引擎完成语音合成输出。 |
