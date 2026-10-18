# 有道词典笔 S7 Pro (YDPS7-2 / Y08) 全栈开发与系统级适配指南

本指南汇集了对网易有道词典笔 S7 Pro（硬件平台代号：`Y08_CV1813_V0`，SoC 架构：Cvitek CV181X / ARM Cortex-A7 hard-float，Linux 内核版本：5.10.4）系统固件解构所得的硬件接口规范、底层驱动、系统服务、预装工具库与五大自研应用（网页浏览器、AI 客户端、漫画阅读器、高级文件管理器、系统定制化）的落地方案。

---

## 目录
1. [硬件规格与硬件拓扑架构](#1-硬件规格与硬件拓扑架构)
2. [外设底层驱动与交互接口规范](#2-外设底层驱动与交互接口规范)
   - [2.1 屏幕与 Framebuffer 显示系统](#21-屏幕与-framebuffer-显示系统)
   - [2.2 触摸屏与按键输入子系统](#22-触摸屏与按键输入子系统)
   - [2.3 音频采集与播放子系统 (ALSA)](#23-音频采集与播放子系统-alsa)
   - [2.4 扫描头光学模组与补光控制](#24-扫描头光学模组与补光控制)
   - [2.5 电池管理与系统供电](#25-电池管理与系统供电)
   - [2.6 无线网络与蓝牙协议栈](#26-无线网络与蓝牙协议栈)
3. [存储分区布局与引导生命周期](#3-存储分区布局与引导生命周期)
   - [3.1 GPT 分区映射表](#31-gpt-分区映射表)
   - [3.2 系统引导与 A/B 分区机制](#32-系统引导与-ab-分区机制)
   - [3.3 自动化启动执行链与用户级扩展点](#33-自动化启动执行链与用户级扩展点)
4. [固件预置库与原生运行时生态](#4-固件预置库与原生运行时生态)
   - [4.1 C 运行时与 ABI 规范](#41-c-运行时与-abi-规范)
   - [4.2 核心多媒体与网络共享库](#42-核心多媒体与网络共享库)
   - [4.3 系统内置调试与控制实用工具](#43-系统内置调试与控制实用工具)
5. [官方应用容器 (Miniapp) 架构解析](#5-官方应用容器-miniapp-架构解析)
   - [5.1 AMR 安装包结构与校验标准](#51-amr-安装包结构与校验标准)
   - [5.2 容器进程 IPC 通信协议 (`miniapp_cli`)](#52-容器进程-ipc-通信协议-miniapp_cli)
6. [五大目标应用全栈工程实现方案](#6-五大目标应用全栈工程实现方案)
   - [6.1 轻量级网页浏览器 (Web Browser)](#61-轻量级网页浏览器-web-browser)
   - [6.2 实时流式 AI 语音客户端 (AI Client)](#62-实时流式-ai-语音客户端-ai-client)
   - [6.3 垂直流式漫画阅读器 (Comic Reader)](#63-垂直流式漫画阅读器-comic-reader)
   - [6.4 高级本地与远程文件管理器 (File Manager)](#64-高级本地与远程文件管理器-file-manager)
   - [6.5 深度系统定制化与服务自动化 (System Customization)](#65-深度系统定制化与服务自动化-system-customization)
7. [交叉编译环境与持续部署工作流](#7-交叉编译环境与持续部署工作流)

---

## 1. 硬件规格与硬件拓扑架构

- **SoC 芯片**：Cvitek CV1813H / CV181X 系列
- **CPU 核心**：ARM Cortex-A7 单核/双核，Hard-Float（`armhf`），最高主频 ~1.0 GHz
- **系统内存**：512MB / 1GB LPDDR3，支持 ZRAM/Swap 扩展交换区
- **存储介质**：eMMC 5.1（`/dev/mmcblk0`）
- **显示面板**：超长条形 IPS 液晶屏，原生物理分辨率为 **240 × 1020 像素**，支持 32 位 ARGB8888 双缓冲渲染，系统配置旋转角度为 **270°**
- **触控芯片**：Axustek 触控 IC，挂载于 I2C 总线，支持多点触控与滑动事件
- **音频系统**：
  - 扬声器功放：AW883XX SmartPA，高保真微型功放芯片
  - 拾音模组：PDM 双麦克风阵列，支持高信噪比远场/近场语音采集
- **扫描头模组**：
  - 图像传感器：挂载于 `/dev/video0`，支持动态曝光与窗口裁剪
  - 补光灯：白色 LED 与红外（IR）双光源，由专用 SoC GPIO 驱动
- **通信模组**：
  - Wi-Fi：802.11 b/g/n，基于 `wpa_supplicant`
  - 蓝牙：BLE 4.2 / 5.0，基于 BlueZ 与 BlueAlsa 音频桥接

---

## 2. 外设底层驱动与交互接口规范

### 2.1 屏幕与 Framebuffer 显示系统

#### 设备节点与硬件参数
- **设备路径**：`/dev/fb0`
- **颜色格式**：32-bit ARGB8888（4 字节/像素）
- **坐标映射与物理方向**：
  - 硬件配置（见 `/etc/miniapp/resources/cfg.json`）：
    ```json
    {
      "screen": {
        "width": 240,
        "height": 1020,
        "xoffset": 0,
        "yoffset": 0,
        "dbuffer": true,
        "direction": 270,
        "tp_direction": 270,
        "fps_max": 60
      },
      "device": {
        "fb": "/dev/fb0",
        "tp": "/dev/input/by-path/platform-4010000.i2c-event"
      }
    }
    ```
- **行步幅（Stride）**：`240 * 4 = 960` 字节
- **显存单帧大小**：`240 * 1020 * 4 = 979,200` 字节（约 956.25 KB）

#### 背光控制与息屏策略
- **背光控制接口**：
  - 路径：`/sys/devices/platform/backlight/backlight/backlight/brightness`
  - 取值范围：`0`（完全关闭）到 `255`（最高亮度）
  - 示例：`echo 180 > /sys/devices/platform/backlight/backlight/backlight/brightness`
- **系统级亮度与显示控制命令行**：
  ```bash
  hal-screen set 80       # 设置亮度百分比 (0-100)
  hal-screen get          # 获取当前屏幕亮度与状态
  hal-screen on           # 唤醒并开启屏幕
  hal-screen off          # 关闭屏幕进入待机
  hal-screen keep         # 保持屏幕常亮 30 秒
  ```

#### C 语言直接渲染与旋转映射示例
```c
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/ioctl.h>
#include <linux/fb.h>
#include <stdint.h>

#define FB_DEV "/dev/fb0"
#define SCREEN_W 240
#define SCREEN_H 1020

typedef struct {
    int fd;
    uint32_t *fbp;
    size_t screensize;
    struct fb_var_screeninfo vinfo;
    struct fb_fix_screeninfo finfo;
} fb_ctx_t;

int fb_init(fb_ctx_t *ctx) {
    ctx->fd = open(FB_DEV, O_RDWR);
    if (ctx->fd < 0) return -1;
    ioctl(ctx->fd, FBIOGET_FSCREENINFO, &ctx->finfo);
    ioctl(ctx->fd, FBIOGET_VSCREENINFO, &ctx->vinfo);
    ctx->screensize = ctx->vinfo.yres_virtual * ctx->finfo.line_length;
    ctx->fbp = (uint32_t *)mmap(0, ctx->screensize, PROT_READ | PROT_WRITE, MAP_SHARED, ctx->fd, 0);
    return (ctx->fbp == MAP_FAILED) ? -1 : 0;
}

// 绘制单个像素（自动处理 270 度旋转与坐标映射）
static inline void put_pixel_rotated(fb_ctx_t *ctx, int x, int y, uint32_t argb) {
    if (x < 0 || x >= SCREEN_W || y < 0 || y >= SCREEN_H) return;
    // direction=270: rx = SCREEN_H - 1 - y, ry = x
    int rx = (SCREEN_H - 1) - y;
    int ry = x;
    ctx->fbp[ry * (ctx->finfo.line_length / 4) + rx] = argb;
}

void fb_close(fb_ctx_t *ctx) {
    if (ctx->fbp) munmap(ctx->fbp, ctx->screensize);
    if (ctx->fd >= 0) close(ctx->fd);
}
```

---

### 2.2 触摸屏与按键输入子系统

#### 设备节点拓扑
- **触摸屏事件节点**：
  - 物理路径：`/dev/input/by-path/platform-4010000.i2c-event`
  - 快捷符号链接：`/dev/input/by-path/axs_ts` 或 `/dev/input/event1`
  - 驱动模块：`/lib/modules/axs_ts.ko`
- **物理按键事件节点**：
  - 路径：`/dev/input/by-path/gpio-keys`（电源键、主页/AI 唤醒键）
  - 辅助按键：`/dev/input/by-path/fake-keys`

#### 坐标转换算法
触控芯片输出原始绝对坐标（`EV_ABS`，`ABS_MT_POSITION_X`，`ABS_MT_POSITION_Y`）。由于显示面板旋转了 270 度，触控输入必须进行相应的坐标变换以实现几何对齐：
```c
void transform_touch_coordinates(int raw_x, int raw_y, int *screen_x, int *screen_y) {
    // 原始范围通常为 0~1020 与 0~240
    *screen_x = raw_y;
    *screen_y = (1020 - 1) - raw_x;
}
```

#### 按键事件守护进程
系统由 `/usr/bin/input-event-daemon` 统一监听事件并根据 `/etc/input-event-daemon_Y08.conf` 执行操作（短按锁屏、长按关机菜单、双击快查等）。

---

### 2.3 音频采集与播放子系统 (ALSA)

硬件平台 `Y08_CV1813_V0` 采用了优化的非对称音频架构（配置位于 `/etc/asound.conf.VY08` 和 `/etc/asound.state.y08`）：

#### 音频路由拓扑
- **播放通道（Playback）**：
  - 默认 PCM 设备：`speaker` -> `spk_softvol` 软音量控制
  - 物理声卡：`hw:1,0`
  - 功放芯片：AW883XX SmartPA，具备低失真升压与过温防护
- **录音通道（Capture）**：
  - 默认 PCM 设备：`softvol_cap`
  - 物理声卡：`hw:0,0`
  - 采样规格：双声道（2-channel），标准采样率 48,000 Hz，16-bit 线性 PCM
  - 重采样插件：`speexrate_medium` 软重采样

#### 常用音频交互命令
```bash
# 播放测试音频文件
aplay -D speaker /userdisk/test.wav
mpg123 -a speaker /userdisk/music.mp3

# 从麦克风录制 5 秒音频（48kHz 双声道）
arecord -D softvol_cap -f S16_LE -r 48000 -c 2 -d 5 /tmp/record.wav

# 音量调节与静音控制
hal-audio -s 75         # 设置音量为 75%
hal-audio -g            # 读取当前系统音量
amixer -c 1 sset 'Master Playback Volume' 80%
```

---

### 2.4 扫描头光学模组与补光控制

词典笔前端集成了专用的高速高帧率光学传感器与双色补光灯，用于微距文本拍摄与离线 OCR 识别。

#### 摄像头传感器配置
- **设备路径**：`/dev/video0`（V4L2 接口）
- **裁剪参数与曝光控制**（见 `/usr/bin/set_camera_crop.sh`）：
  ```bash
  v4l2-ctl -d /dev/video0 --set-selection=target=crop,top=80,left=224,width=208,height=320 --set-ctrl 'exposure=74,analogue_gain=45'
  ```
- **图像采集守护程序**：`/usr/bin/CaptureFrame`

#### 补光灯 GPIO 硬件引脚映射
在 `Y08_CV1813_V0` 架构中，笔尖补光灯通过 sysfs GPIO 统一控制（见 `/usr/bin/len_onoff.sh`）：
- **白色补光 LED**：`GPIO 490`
- **红外补光 LED**：`GPIO 491`

#### 控制指令
```bash
# 使用官方封装脚本
/usr/bin/len_onoff.sh on        # 开启笔尖白色补光灯
/usr/bin/len_onoff.sh off       # 关闭笔尖白色补光灯
/usr/bin/len_onoff.sh on IR     # 开启笔尖红外 LED
/usr/bin/len_onoff.sh off IR    # 关闭笔尖红外 LED

# 直接通过 sysfs 节点操作
echo 490 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio490/direction
echo 1 > /sys/class/gpio/gpio490/value   # 点亮
echo 0 > /sys/class/gpio/gpio490/value   # 熄灭
```

---

### 2.5 电池管理与系统供电

电池状态由专用的电量计芯片通过 I2C 监测，并由内核暴露于标准 Linux sysfs 接口：
- **电池状态节点**：`/sys/class/power_supply/battery/status`（输出 `Charging`、`Discharging`、`Full`）
- **剩余百分比**：`/sys/class/power_supply/battery/capacity`（取值 `0`~`100`）
- **当前实时电压**：`/sys/class/power_supply/battery/voltage_now`（单位：微伏，如 `3850000` 表示 3.85V）
- **充放电电流**：`/sys/class/power_supply/battery/current_now`

---

### 2.6 无线网络与蓝牙协议栈

- **网络管理**：
  - 核心服务：`/usr/sbin/wpa_supplicant`
  - 配置文件：`/userdata/cfg/wpa_supplicant.conf`
  - 控制命令行：
    ```bash
    hal-wifi scan                       # 扫描周围 Wi-Fi 接入点
    hal-wifi connect "MySSID" "MyPassword"  # 连接指定无线网络
    ```
- **蓝牙管理**：
  - 核心服务：BlueZ 守护进程与 `bluealsa`
  - 控制命令行：`bluetoothctl`、`hal-bt`

---

## 3. 存储分区布局与引导生命周期

### 3.1 GPT 分区映射表

存储介质为 `/dev/mmcblk0`，系统采用标准的 GPT 分区表拓扑：

| 分区号 | 分区名称 | 文件系统类型 | 挂载点 | 访问权限 | 说明与用途 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `p1` | `boot` | raw | - | RO | 内核镜像与设备树 (FIT 镜像) |
| `p2` | `recovery` | raw | - | RO | 恢复模式内核与初始 RAMDisk |
| `p3` | `system_a` | EROFS | `/` (A 槽) | RO | 主系统根文件系统（只读、带压缩） |
| `p4` | `system_b` | EROFS | `/` (B 槽) | RO | 备用系统根文件系统（OTA 切换） |
| `p5` | `oem` | EROFS | `/oem` | RO | 厂商静态资源、本地词库与基础库 |
| `p6` | `misc` | raw | - | RW | 启动控制标志、BCB 指令与槽位定义 |
| `p14` | `userdata` | ext4 | `/userdata` | RW | 用户数据、Wi-Fi 凭证、应用安装目录 |
| `p15` | `userdisk` | ext4 | `/userdisk` | RW | MTP 大容量文件共享存储区 |

---

### 3.2 系统引导与 A/B 分区机制

1. **U-Boot 阶段**：读取 `misc` 分区（`p6`），确定活动槽位为 `_a` 或 `_b`。
2. **内核启动**：挂载对应的 EROFS 根分区（例如 `p3` 对应 `system_a`），以只读方式保护基础系统文件不被篡改。
3. **安全回滚保护**：在 `/usr/bin/runDictPen` 中内置崩溃看门狗计数器。如果应用启动在 15 秒内发生连续崩溃超过 5 次，系统将自动触发 `update_engine --misc=clear` 并执行硬件重启进行槽位回退保护。

---

### 3.3 自动化启动执行链与用户级扩展点

词典笔系统的 SysV init / procd 启动序列按照以下顺序执行：
1. `/etc/init.d/rcS` 逐个调用启动脚本。
2. `/etc/init.d/S01systeminit`：挂载 `/userdata` 与 `/userdisk`，初始化音频路由，启动 `ubusd`，拉起官方容器 `runDictPen`。
3. `/etc/init.d/S50launcher`：启动外设监控与网络守护进程。
4. **关键扩展入口：`/etc/init.d/S99_run_test_scripts`**：
   ```sh
   #! /bin/sh
   [ -f /userdisk/skip_re/skip_login.sh ] || exit 0
   start() {
       printf "Starting test script: skip_login.sh "
       /userdisk/skip_re/skip_login.sh &
       echo "done"
   }
   ```
   **工程价值**：系统在此处提供了一个完全合法的开机执行钩子。只要在可读写的 `/userdisk/skip_re/` 目录下放置可执行脚本 `skip_login.sh`，系统将在启动的最终阶段以 **UID 0 (root)** 权限无条件在后台拉起该脚本。

---

## 4. 固件预置库与原生运行时生态

本系统固件自带了极其完善的开源工具链与共享库，自研应用可直接动态链接使用，无需额外打包庞大的运行时依赖。

### 4.1 C 运行时与 ABI 规范
- **C 库版本**：GNU C Library (glibc) **2.33**
- **动态链接器**：`/lib/ld-linux-armhf.so.3`
- **目标架构三元组**：`arm-linux-gnueabihf`（ARMv7-A，Hard-Float）

### 4.2 核心多媒体与网络共享库
- **网络与传输**：
  - `libcurl.so.4`（支持 HTTP, HTTPS, WebDAV, FTP, HTTP/2）
  - `libssl.so.1.1` & `libcrypto.so.1.1`（完整 TLS 1.3 密码套件）
- **多媒体音视频处理**：
  - `libavcodec.so.58`、`libavformat.so.58`、`libavfilter.so.7`、`libswscale.so.5`、`libswresample.so.3`（完整的 FFmpeg 编解码库）
  - `libasound.so.2`（ALSA 原生声卡驱动库）
  - `libFLAC.so.8`、`libmpg123.so.0`（高保真音频解压）
- **图像与排版渲染**：
  - `libfreetype.so.6`（矢量 TrueType 字体平滑光栅化渲染引擎）
  - `libjpeg.so.8` & `libturbojpeg.so.0`（硬件加速/SIMD 优化 JPEG 解码）
  - `libpng16.so.16`（PNG 带透明通道图像解析）
- **数据结构与并发**：
  - `libsqlite3.so.0`（全功能轻量级嵌入式关系数据库）
  - `libevent-2.1.so.7` & `libev.so.4`（高性能异步事件驱动网络循环）

### 4.3 系统内置调试与控制实用工具
- **图形与截屏工具**：
  - `/usr/bin/fbshow`：在 Framebuffer 上直显 PNG 图片（用法：`fbshow <path.png> /dev/fb0`）
  - `/usr/bin/gsnap`：捕获当前屏幕到 PNG 图片（用法：`gsnap <output.png> /dev/fb0`）
- **多媒体命令行**：
  - `ffmpeg`、`ffprobe`：音视频流转换与信息提取
  - `mpg123`、`sox`、`lame`、`flac`：音频播放、录音与格式变换
  - `aplay`、`arecord`、`amixer`：ALSA 声卡交互工具
- **网络与调试服务**：
  - `/usr/sbin/dropbear`、`/usr/sbin/sshd`：原生 SSH 服务器
  - `gdb`、`strace`、`lsof`：底层动态调试与系统调用追踪
  - `evtest`、`ts_test`、`ts_test_mt`：输入子系统与多点触控测试

---

## 5. 官方应用容器 (Miniapp) 架构解析

词典笔原厂 UI 运行在官方的 `miniapp` 微应用框架之上，开发者既可以与官方应用生态融合，也可以采用独立的原生应用模式。

### 5.1 AMR 安装包结构与校验标准

官方应用以 `.amr`（Application Mini Runtime）格式分发，实质为标准的 ZIP 压缩包：

```
example_app.amr
├── manifest.json            # 应用清单与元数据
├── app_icon.png             # 桌面图标
├── app.js.bin               # QuickJS 编译的字节码主程序
├── images/                  # 静态图像资源目录
└── libs/arm-y08/libext.so   # （可选）原生 C/C++ 动态链接扩展库
```

#### `manifest.json` 配置规范示例
```json
{
  "appName": "自定义工具",
  "version": "1.0.0",
  "appid": "9000100010001001",
  "icon": "app_icon.png",
  "quickjs": {
    "version": "20200705",
    "bigNum": false
  },
  "props": {
    "supportUnInstall": true,
    "addDesktop": {
      "y08_platform": true
    }
  },
  "cert": {
    "app.js.bin": {
      "size": 13081,
      "md5": "0947210ce3efce63369f4a3967da38ca"
    }
  }
}
```

### 5.2 容器进程 IPC 通信协议 (`miniapp_cli`)

官方 `miniapp` 主服务在 `/var/run/miniapp-dbg.socket` 监听本地 UNIX 域套接字，通过 `/usr/bin/miniapp_cli` 暴露了完整的命令行调试与控制命令：

```bash
# 1. 应用生命周期管理
miniapp_cli install /userdisk/app.amr      # 安装指定路径的 AMR 应用包
miniapp_cli uninstall 9000100010001001    # 卸载指定 AppID 的应用
miniapp_cli start 9000100010001001        # 启动指定应用
miniapp_cli startService <appId> <service> # 启动应用后台服务

# 2. 图像捕获与渲染控制
miniapp_cli capture /tmp/screen.png       # 请求容器渲染引擎捕获界面
miniapp_cli captureFB /tmp/fb.raw         # 直接导出 Framebuffer 设备内存

# 3. 输入注入与调试
miniapp_cli injectKey 116                 # 模拟按键事件注入
miniapp_cli memoryApp                     # 输出当前各微应用内存占用情况
```

---

## 6. 五大目标应用全栈工程实现方案

---

### 6.1 轻量级网页浏览器 (Web Browser)

#### 核心设计考量
- 屏幕物理比例为 240 × 1020（宽窄高长），常规桌面网页（1200px+）无法直接以标准布局呈现。
- 系统内存有限，运行完整 WebKit 或 Chromium 开销过大。
- 架构策略：**轻量级本地渲染器 + 智能内容重排引擎（Readability）**。

#### 系统架构图
```
[外部万维网 (HTTP/HTTPS)]
           │
           ▼
[内置 libcurl.so.4 抓取模块 (TLS 1.3)]
           │
           ▼
[轻量级 DOM/HTML 快速解析器 (例如 gumbo / lexbor 或 markdown 转换器)]
           │
           ▼
[文本排版与流式重排引擎]
 ├── 将文章主干重排为 220px 宽度流
 └── 基于 libfreetype.so.6 进行中文字体抗锯齿光栅化
           │
           ▼
[虚拟画布与滑动视口缓冲区]
           │
           ▼
[直接映射至 /dev/fb0 双缓冲输出 (支持惯性触控手势)]
```

#### 关键技术点实现
1. **触控滑动与惯性算法**：通过读取 `/dev/input/by-path/axs_ts` 的多点触摸事件，计算 `dy / dt` 速度向量，在手指抬起后应用二阶阻尼滑动，确保阅读体验如丝般顺滑。
2. **文本超链接命中检测**：将排版过程中每个 `<a>` 标签的文本矩形边界框（Bounding Box）存入轻量级 R-Tree 或线性数组，触摸事件发生时根据屏幕坐标快速检索并触发后续页面导航。

---

### 6.2 实时流式 AI 语音客户端 (AI Client)

#### 核心设计考量
实现兼具“语音问答”与“文本交互”的高性能智能助手客户端，全流程支持流式数据传输，端到端延迟控制在 1 秒以内。

#### 完整处理管线
```
 ┌───────────────┐
 │ 物理按键/触屏 │ 触发语音监听
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ ALSA 音频录制 │ arecord / libasound 采集 16kHz S16_LE PCM 裸流
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │ libcurl 上行  │ 基于 chunked transfer 或 WebSocket 发送至 ASR 服务
 └───────┬───────┘
         ▼
 ┌───────────────┐
 │  LLM 推理引擎 │ SSE (Server-Sent Events) 流式文本下行
 └───────┬───────┘
         ├────────────────────────────────┐
         ▼                                ▼
 ┌────────────────┐              ┌────────────────┐
 │ 文字实时打字机 │              │ TTS 语音合成   │
 │ FreeType 渲染  │              │ 后台分段缓冲   │
 └───────┬────────┘              └────────┬───────┘
         ▼                                ▼
 ┌────────────────┐              ┌────────────────┐
 │ /dev/fb0 刷新  │              │ aplay / mpg123 │
 │ 垂直滚动展示   │              │ 扬声器实时放音 │
 └────────────────┘              └────────────────┘
```

#### 关键代码：基于 libcurl 的 SSE 实时流式解析回调
```c
#include <curl/curl.h>

// 处理 LLM 逐字吐出的 SSE 数据块
static size_t sse_stream_write_cb(char *ptr, size_t size, size_t nmemb, void *userdata) {
    size_t total = size * nmemb;
    // 快速过滤出 data: {"content": "..."} 字段
    if (strncmp(ptr, "data: ", 6) == 0) {
        char *payload = ptr + 6;
        // 增量推入 UI 文本队列并触发局部屏幕刷新
        ui_append_text_chunk(payload);
    }
    return total;
}

void ai_chat_stream_request(const char *prompt) {
    CURL *curl = curl_easy_init();
    if (!curl) return;
    
    struct curl_slist *headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");
    headers = curl_slist_append(headers, "Authorization: Bearer YOUR_API_TOKEN");
    
    char body[1024];
    snprintf(body, sizeof(body), "{\"model\":\"deepseek-chat\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"%s\"}]}", prompt);
    
    curl_easy_setopt(curl, CURLOPT_URL, "https://api.deepseek.com/chat/completions");
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, sse_stream_write_cb);
    
    curl_easy_perform(curl);
    curl_easy_cleanup(curl);
}
```

---

### 6.3 垂直流式漫画阅读器 (Comic Reader)

#### 核心设计考量
- 240 × 1020 的长条屏幕是条漫（韩漫、国产长条漫）的天然黄金阅读器。
- 单张漫画切片图片分辨率可能高达 800 × 3000，必须避免一次性全部加载导致嵌入式系统 OOM（内存溢出）。

#### 关键渲染技术方案
1. **高性能图像缩放与解码**：
   - 调用预装的 `libturbojpeg.so.0`。
   - 利用 TurboJPEG 的 `tjDecompress2()` 支持 1/2、1/4、1/8 的降采样直接解压特性，在解码阶段直接将图片等比缩放至宽度 240 像素，极大地节省解码时间与显存占用。
2. **分块三级瓦片缓存（Tile Cache）**：
   - 内存中仅保留当前可见屏、前一屏与后一屏的位图像素（约占用 `3 * 1MB = 3MB` 内存）。
   - 超出视野范围的历史页面立即调用 `free()` 释放物理内存，滑入时动态异步预加载。
3. **格式原生支持**：
   - 支持读取标准 `.zip` / `.cbz` / 目录结构漫画包。

---

### 6.4 高级本地与远程文件管理器 (File Manager)

#### 核心设计考量
提供直观的双列或单列高信息密度触摸管理界面，打通词典笔与个人云存储、电脑之间的通道。

#### 功能矩阵
- **本地文件浏览器**：
  - 访问 `/userdata`（应用数据与安装包）、`/userdisk`（用户资料）、`/tmp`（临时挂载区）。
  - 文件常见属性、重命名、批量删除、移动、软链接创建。
- **内置查看器**：
  - 文本文件（`.txt`、`.log`、`.json`）：基于 FreeType 的彩色或黑白文本阅读器。
  - 图片（`.png`、`.jpg`）：全屏居中缩放预览。
  - 音频（`.mp3`、`.wav`、`.flac`）：调用后台 `mpg123` / `aplay` 浮窗播放。
- **远程传输协议集成**：
  - **WebDAV 客户端**：借助 `libcurl.so.4` 原生支持的 WebDAV 方法（`PROPFIND`、`MKCOL`、`PUT`、`GET`），无缝挂载个人坚果云、Alist 或群晖 NAS。
  - **FTP 客户端与服务端**：内置小巧的 FTP 传输支持，实现局域网内免驱动高速无线双向对传。
  - **本地文件共享服务**：一键在词典笔上启动 Micro-HTTPD 或基于 `dropbear` 的 SFTP 服务，电脑浏览器输入 `http://词典笔IP:8080` 即可通过网页拖拽上传文件。

---

### 6.5 深度系统定制化与服务自动化 (System Customization)

针对高级玩家与二次开发者，提供完整的持久化与全权控制机制：

#### 方案 A：共存式服务常驻（保留官方原厂词典笔功能）
- 在 `/userdisk/skip_re/skip_login.sh` 中挂载自定义服务后台守护进程。
- 自动化启动 Dropbear SSH 服务器，并在 Wi-Fi 成功获取 IP 地址后自动向本地记录或网络广播当前 IP。
- 保持官方 `miniapp` 桌面正常工作，通过 `miniapp_cli start` 唤起自研小组件。

#### 方案 B：纯净原生系统模式（完全接管硬件）
- 在启动脚本中主动终止官方 UI 守护进程：
  ```bash
  killall -9 guardian_run
  killall -9 miniapp
  killall -9 SoundPlayer
  killall -9 SoundRecord
  ```
- 此时 Framebuffer `/dev/fb0` 与触控设备 `/dev/input/by-path/axs_ts` 完全空闲，不会受到任何官方界面的竞争刷新与按键抢占。
- 启动全屏自研操作系统 UI（例如基于 **LVGL 9**、**Raylib** 或自研轻量级 GUI 框架构建的启动器）。

---

## 7. 交叉编译环境与持续部署工作流

### 7.1 主机端工具链编译规范
推荐使用标准 ARMv7 硬浮点工具链（如 `arm-linux-gnueabihf-gcc` 10.x+ 或 Rust `armv7-unknown-linux-gnueabihf`）。

#### 推荐编译器参数
```makefile
CC = arm-linux-gnueabihf-gcc
CFLAGS = -O2 -march=armv7-a -mtune=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard \
         -I$(SYSROOT)/usr/include -I$(SYSROOT)/include
LDFLAGS = -L$(SYSROOT)/usr/lib -L$(SYSROOT)/lib \
          -Wl,-rpath,/usr/lib -Wl,-rpath,/lib \
          -lasound -lcurl -lssl -lcrypto -lfreetype -lturbojpeg -lpng16 -lsqlite3 -lpthread -lm
```

### 7.2 自动化部署脚本 (`deploy.sh`)
```bash
#!/bin/bash
TARGET_IP="192.168.31.188"
TARGET_DIR="/userdisk/apps"

echo "[1/3] 编译应用目标二进制..."
make clean && make -j$(nproc)

echo "[2/3] 通过 MTP 或网络同步至词典笔..."
# 如果使用 SSH/SCP:
scp ./my_app root@${TARGET_IP}:${TARGET_DIR}/my_app
# 如果使用 USB MTP 挂载目录:
# cp ./my_app /Users/daniel/Library/CloudStorage/MacDroid-DictPen/MTP/apps/

echo "[3/3] 赋予执行权限并测试运行..."
ssh root@${TARGET_IP} "chmod +x ${TARGET_DIR}/my_app && ${TARGET_DIR}/my_app &"
echo "部署完成！"
```

---

*文档版本：v1.0.0*  
*适用平台：NetEase Youdao Dictionary Pen S7 Pro (CV1813 / Y08)*  
*生成时间：2026-10-18*
