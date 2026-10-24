# 有道词典笔 S7 Pro 硬件输入、物理按键、触控驱动与 HAL 深度逆向分析
## (Falcon Hardware Input Subsystem, Physical Keys, and Touch Digitizer HAL Deep-Dive Engineering Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB RAM, Linux 5.10.4)  
> **核心组件**: `axs_ts.ko` (AXS15205), `axp2101-pek`, `libfalcon.so` (`greenui`), `libydhal_devices.so`, `libjsapi_export_core.so` (`buttonEvent`)

---

## 目录索引

1. [硬件输入拓扑与内核设备树硬件映射](#1-硬件输入拓扑与内核设备树硬件映射)
   - 1.1 [四层交互架构全景拓扑](#11-四层交互架构全景拓扑)
   - 1.2 [Linux 内核 Evdev 节点与设备树引脚分配](#12-linux-内核-evdev-节点与设备树引脚分配)
   - 1.3 [笔尖压力/光学微动开关 (`/dev/input/event0`)](#13-笔尖压力光学微动开关-devinputevent0)
   - 1.4 [AXP2101 PMIC 电源按键 (`/dev/input/event1`)](#14-axp2101-pmic-电源按键-devinputevent1)
   - 1.5 [实体 Home/语音侧键 (`/dev/input/event2`)](#15-实体-home语音侧键-devinputevent2)
   - 1.6 [AXS15205 极窄电容触控屏驱动 (`/dev/input/event3`)](#16-axs15205-极窄电容触控屏驱动-devinputevent3)
2. [触控坐标变换流水线与数学逆运算证明](#2-触控坐标变换流水线与数学逆运算证明)
   - 2.1 [物理屏幕与逻辑视口几何差异](#21-物理屏幕与逻辑视口几何差异)
   - 2.2 [`greenui::winInputLoop` (0x002275d4) 逆向反汇编](#22-greenuiwininputloop-0x002275d4-逆向反汇编)
   - 2.3 [双向变换数学封闭性与零误差证明](#23-双向变换数学封闭性与零误差证明)
   - 2.4 [32 位 ARM Linux 二进制结构体严格对齐 (16 字节 `IIHHi`) 与单调时钟约束](#24-32-位-arm-linux-二进制结构体严格对齐-16-字节-iihhi-与单调时钟约束)
3. [物理按键事件分发与 QuickJS JSAPI 桥接](#3-物理按键事件分发与-quickjs-jsapi-桥接)
   - 3.1 [C++ HAL 观察者管道 (`libydhal_devices.so`)](#31-c-hal-观察者管道-libydhal_devicesso)
   - 3.2 [`libjsapi_export_core.so` 模块加载与原型绑定](#32-libjsapi_export_coreso-模块加载与原型绑定)
   - 3.3 [JavaScript 原型方法字典](#33-javascript-原型方法字典)
   - 3.4 [45 组全量 JQSignal 信号清单与固件历史拼写缺陷 ("Relese")](#34-45-组全量-jqsignal-信号清单与固件历史拼写缺陷-relese)
4. [屏幕睡眠、唤醒锁与触控挂起/恢复全链路](#4-屏幕睡眠唤醒锁与触控挂起恢复全链路)
   - 4.1 [Framebuffer 广播与 `axs_fb_notifier_callback`](#41-framebuffer-广播与-axs_fb_notifier_callback)
   - 4.2 [`axs_lcd_off` 13 字节休眠指令封包反汇编](#42-axs_lcd_off-13-字节休眠指令封包反汇编)
   - 4.3 [硬件复位脉冲与 100ms 驱动恢复延迟](#43-硬件复位脉冲与-100ms-驱动恢复延迟)
   - 4.4 [硬件级唤醒电路与屏下不可唤醒铁律](#44-硬件级唤醒电路与屏下不可唤醒铁律)
5. [生产级开发规范与全功能实现代码](#5-生产级开发规范与全功能实现代码)
   - 5.1 [精确 C 数据结构定义 (`s7pro_input.h`)](#51-精确-c-数据结构定义-s7pro_inputh)
   - 5.2 [原生 C 事件注入独立工具 (`s7pro_inject.c`)](#52-原生-c-事件注入独立工具-s7pro_injectc)
   - 5.3 [生产级 Python 3 触控/按键注入器 (`s7pro_input.py`)](#53-生产级-python-3-触控按键注入器-s7pro_inputpy)
   - 5.4 [生产级 QuickJS 硬件按键管理器 (`S7ProButtonManager.js`)](#54-生产级-quickjs-硬件按键管理器-s7probuttonmanagerjs)
   - 5.5 [端到端 Vue SFC 组件集成示例](#55-端到端-vue-sfc-组件集成示例)

---

## 1. 硬件输入拓扑与内核设备树硬件映射

### 1.1 四层交互架构全景拓扑

网易有道词典笔 S7 Pro 采用全横屏交互模式（逻辑画布 $1020 \times 240$），但硬件底层装配的是一块 $240 \times 1020$ 物理竖屏与同规格触控 IC。整机硬件交互系统跨越了四个清晰的体系层次：

```
+---------------------------------------------------------------------------------------+
| 1. 应用层 (QuickJS MiniApp / Vue SFC)                                                 |
|    - import buttonEventModule from 'buttonEvent'                                      |
|    - 逻辑坐标系: 1020 x 240 (横屏视口，Skia 矢量渲染，Flexbox 弹性布局)               |
|    - 事件信号: headButtonPress, headButtonRelese, homeButtonRelease 等                |
+------------------------------------------^--------------------------------------------+
                                           | JQuick / JQSignal IPC 跨语言分发
+------------------------------------------v--------------------------------------------+
| 2. 原生 Falcon GUI 与 HAL 桥接层                                                      |
|    - libjsapi_export_core.so: JSButtonEventModuleProxy / registerCModuleLoader        |
|    - libydhal_devices.so: YDALAPI::YButtonEventModule 反应式观察者管道                 |
|    - libfalcon.so: greenui::winInputLoop (0x002275d4)                                 |
|        * tslib 集成: ts_setup, ts_read_mt                                             |
|        * 270 度逆向旋转投影: X_log = clamp(1019 - Y_raw, 0, 1019), Y_log = X_raw      |
|        * Framebuffer 翻转: ARM NEON SIMD yd_l_rotate90_S32 (顺时针 270° / 逆时针 90°)  |
+------------------------------------------^--------------------------------------------+
                                           | Linux Evdev Polling / Framebuffer Notifier
+------------------------------------------v--------------------------------------------+
| 3. Linux 内核驱动子系统 (Linux 5.10.4)                                                |
|    - /dev/input/event0: 光学对射微动开关 / 笔尖触发器 (KEY_CAMERA = 212)              |
|    - /dev/input/event1: AXP2101 PMIC 电源键 (axp2101-pek, KEY_POWER = 116)            |
|    - /dev/input/event2: 侧边实体功能键 (gpio-keys, KEY_ENTER = 28)                    |
|    - /dev/input/event3: AXS15205 极窄电容触控屏 (axs_ts.ko, 多点触控 Protocol B)      |
|    - /dev/fb0: Framebuffer (物理 240x1020, 虚拟 240x2040, ARGB8888 双缓冲)             |
+------------------------------------------^--------------------------------------------+
                                           | 硬件物理总线 (I2C-1, I2C-5, SoC GPIOs)
+------------------------------------------v--------------------------------------------+
| 4. 物理外设实体                                                                       |
|    - 笔尖弹簧光学对射式微动传感器                                                     |
|    - X-Powers AXP2101 高度集成 PMIC (I2C-5 地址 0x34, 独占 IRQ 47)                    |
|    - 侧边金属按压按键 (Home / 语音功能复用)                                           |
|    - AXS15205 电容触控 IC (I2C-1 地址 0x38, 物理尺寸 240x1020)                       |
+---------------------------------------------------------------------------------------+
```

---

### 1.2 Linux 内核 Evdev 节点与设备树引脚分配

| 设备节点路径 | 绑定驱动程序 / 子系统 | 核心 Linux Keycode | 硬件外设物理作用 |
| :--- | :--- | :--- | :--- |
| `/dev/input/event0` | `gpio-keys` / `pen-switch-sensor` | `KEY_CAMERA` (212) | 笔尖触纸光学对射微动开关 |
| `/dev/input/event1` | `axp2101-pek` (PMIC PEK) | `KEY_POWER` (116) | AXP2101 独立电源管理按键 |
| `/dev/input/event2` | `gpio-keys` (side/home keys) | `KEY_ENTER` (28) | 侧边物理功能键 (Home / 语音唤醒) |
| `/dev/input/event3` | `axs_ts` (AXS15205 触控驱动) | `ABS_MT_*` (Protocol B) | $240 \times 1020$ 极窄电容触控面板 |

#### 1.3 笔尖压力/光学微动开关 (`/dev/input/event0`)
- **硬件拓扑**: 笔尖内装配微型弹簧复位机构与光学遮断器（Optical Interrupter）。当笔尖接触纸面受压向内缩进约 $0.5\text{ mm}$ 时，遮光叶片切断红外光路。
- **内核映射**: 绑定为 `gpio-keys`，映射至 `KEY_CAMERA`（代码 `212`，十六进制 `0x00d4`）。
- **运行机制**: 
  - 笔尖下压触发 `KEY_CAMERA` 闭合（`value = 1`），Falcon 运行时接收后瞬间激活高帧率 CMOS 扫描摄像头（`/dev/video0`）与照明补光 LED；
  - 笔尖离纸弹回触发 `KEY_CAMERA` 释放（`value = 0`），系统立即停止摄流，截断拼接图像并交由端侧 OCR 神经网络识别。

#### 1.4 AXP2101 PMIC 电源按键 (`/dev/input/event1`)
- **硬件拓扑**: 连接至 X-Powers AXP2101 PMIC 芯片的 PEK 引脚。PMIC 挂载于 SoC 的 I2C-5 控制器（基地址 `0x0502B000`，从机地址 `0x34`，中断号 47）。
- **内核映射**: 驱动 `axp2101-pek` 上报 `KEY_POWER`（代码 `116`，十六进制 `0x0074`）。
- **去抖与硬件时序**: 硬件去抖时长约为 $128\text{ ms}$。短按触发屏幕点亮与熄灭（挂起/唤醒循环），持续长按 $4\text{ s}$ 或 $8\text{ s}$ 触发 PMIC 内部硬件级紧急断电下电状态机。

#### 1.5 实体 Home/语音侧键 (`/dev/input/event2`)
- **硬件拓扑**: 笔身侧边金属微动开关，通过 SoC 内部上拉 GPIO 采样。
- **内核映射**: 映射为 `KEY_ENTER`（代码 `28`，`0x001c`）或 `KEY_HOMEPAGE`。
- **业务逻辑**: 
  - 短按（$< 400\text{ ms}$）：由 Falcon 派发 `homeButtonClick` 信号，强制返回 Launcher 桌面；
  - 长按（$> 800\text{ ms}$）：派发 `homeButtonLongPress` 信号，唤醒小P老师语音大模型录音流水线。

#### 1.6 AXS15205 极窄电容触控屏驱动 (`/dev/input/event3`)
- **硬件拓扑**: AxSemi (艾矽微) AXS15205 电容触控控制器，挂载于 I2C-1（地址 `0x38`），具备独立的复位引脚（Reset GPIO）与中断引脚（INT GPIO）。
- **内核驱动**: `axs_ts.ko`。反汇编 `axs_ts_probe` 可见：
  ```c
  input_set_abs_params(dev, ABS_MT_POSITION_X, 0, 170, 0, 0);
  input_set_abs_params(dev, ABS_MT_POSITION_Y, 0, 560, 0, 0);
  input_set_abs_params(dev, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);
  input_set_abs_params(dev, ABS_MT_PRESSURE, 0, 255, 0, 0);
  input_set_capability(dev, EV_KEY, BTN_TOUCH);
  input_mt_init_slots(dev, 2, INPUT_MT_DIRECT);
  ```
  固件支持最多 2 点同时触控（Linux Multi-Touch Type B 槽协议）。

---

## 2. 触控坐标变换流水线与数学逆运算证明

### 2.1 物理屏幕与逻辑视口几何差异

- **物理液晶面板与触控 IC**: 宽度 $W_{phy} = 240$，高度 $H_{phy} = 1020$。
- **UI 渲染与逻辑视口**: 宽度 $W_{log} = 1020$，高度 $H_{log} = 240$。
- **旋转方位配置**: `/etc/miniapp/resources/cfg.json` 中配置 `_tp_direction: 270`。

```
[触控 IC 原始采样: 240x1020]
                 ↓ ABS_MT_POSITION_X (0~239), ABS_MT_POSITION_Y (0~1019)
[tslib 校准层: /etc/ts.conf + /etc/pointercal (ts_linear)]
                 ↓ ts_read_mt 读取归一化物理像素坐标
[Falcon GUI greenui::winInputLoop (0x002275d4)]
                 ↓ 270 度旋转投影与浮点截断 (libfalcon.so)
                 ↓ X_log = clamp(1019 - Y_raw, 0, 1019)
                 ↓ Y_log = X_raw
[greenui::MotionEvent (1020 x 240 视口坐标)]
                 ↓ JQuick::WXGesture 分发
[QuickJS MiniApp JS 空间: touches[0].pageX ∈ [0, 1019], pageY ∈ [0, 239]]
```

---

### 2.2 `greenui::winInputLoop` (0x002275d4) 逆向反汇编

在 `libfalcon.so` 的触控监听线程中，反汇编提取出的核心旋转分支与浮点数学运算：

```arm
; --- 检查 _tp_direction 旋转参数 ---
0x002278ac: movw lr, #0x10e              ; 加载立即数 0x10e (十进制 270)
0x002278b0: cmp  ip, lr                  ; 比较当前触控旋转参数是否等于 270
0x002278b4: beq  #0x227bcc               ; 命中 270 度，跳转至核心旋转计算块

; --- 270 度坐标投影与数学变换运算块 ---
0x00227bd0: vmov r2, s17                 ; r2 = (float) raw_y - tp_yoffset
0x00227bd4: ldr  r3, [sp, #0x40]         ; r3 = mWidth (1020, 来自 FBNativeWindow)
0x00227bdc: vmov.f32 s17, s16            ; 新 Y 坐标 = raw_x - tp_xoffset (即 Y_log = X_raw)
0x00227be0: sub  ip, r3, r2              ; ip = 1020 - raw_y
0x00227be4: sub  r2, ip, #1              ; r2 = (1020 - raw_y) - 1 = 1019 - raw_y
0x00227be8: vmov s2, r2                  ; 将整型载入 VFP 浮点寄存器 s2
0x00227bec: vcvt.f64.s32 d1, s2          ; 转换 signed int32 为 double float
0x00227bf0: bl   fmax                    ; 调用 fmax(0.0, (double)(1019 - raw_y)) 下边界截断

; --- 上边界截断块 ---
0x00227a9c: ldr  r3, [sp, #0x40]         ; r3 = mWidth (1020)
0x00227aa0: sub  r3, r3, #1              ; r3 = 1019 (最大允许边界)
0x00227aac: bl   fmin                    ; 调用 fmin(1019.0, max_result) 上边界截断
0x00227ab4: vcvt.s32.f64 s16, d0         ; 新 X 坐标 = (int32) 最终浮点截断值 (X_log)
```

**数学变换公式**:
$$X_{log} = \text{clamp}(1019 - Y_{raw}, 0, 1019)$$
$$Y_{log} = X_{raw}$$

---

### 2.3 双向变换数学封闭性与零误差证明

在图形渲染端（`greenui::rotate_fb`，虚拟地址 `0x00223c5c`），Skia 引擎将 $1020 \times 240$ 的离屏绘制位图通过 ARM NEON 矢量加速核 `yd_l_rotate90_S32`（`0x002289f0`）顺时针旋转 270 度（逆时针 90 度）输出到物理屏 `/dev/fb0`：
$$\begin{bmatrix} X_{fb} \\ Y_{fb} \end{bmatrix} = \begin{bmatrix} 0 & 1 \\ -1 & 0 \end{bmatrix} \begin{bmatrix} X_{log} \\ Y_{log} \end{bmatrix} + \begin{bmatrix} 0 \\ 1019 \end{bmatrix} = \begin{bmatrix} Y_{log} \\ 1019 - X_{log} \end{bmatrix}$$

当用户手指按压在屏幕上显示坐标为 $(X_{fb}, Y_{fb})$ 的物理发光点时，触控屏 IC 采集到的原始坐标必为：
$$X_{raw} = X_{fb} = Y_{log}$$
$$Y_{raw} = Y_{fb} = 1019 - X_{log}$$

将 $(X_{raw}, Y_{raw})$ 代入输入线程 `greenui::winInputLoop` 的变换方程：
$$X_{event} = 1019 - Y_{raw} = 1019 - (1019 - X_{log}) = X_{log}$$
$$Y_{event} = X_{raw} = Y_{log}$$
$$(X_{event}, Y_{event}) \equiv (X_{log}, Y_{log})$$

**逆向注入所需逆算公式**:
若要在宿主机或测试脚本中向 `/dev/input/event3` 注入逻辑坐标 $(X_{log}, Y_{log})$ 的点击，其必须经过的逆算公式为：
$$X_{raw} = Y_{log}$$
$$Y_{raw} = 1019 - X_{log}$$

---

### 2.4 32 位 ARM Linux 二进制结构体严格对齐 (16 字节 `IIHHi`) 与单调时钟约束

在 Linux 5.10.4 32 位 ARM 平台（`armhf`）上，内核与用户空间交互的 `struct input_event` 内存布局为：

```c
struct input_event {
    struct timeval time; /* tv_sec (4 bytes) + tv_usec (4 bytes) = 8 bytes */
    __u16 type;          /* 2 bytes */
    __u16 code;          /* 2 bytes */
    __s32 value;         /* 4 bytes */
}; /* 总尺寸严格为 16 字节 */
```

#### 致命失效陷阱 (Binary ABI Failures):
1. **64 位 host 注入导致的 `-EINVAL` (22)**:
   在 64 位 x86_64 或 macOS 宿主机上，`timeval` 为 16 字节，总结构体达 24 字节（`QQHHi`）。若直接跨架构注入，内核 `evdev_write()` 会因 `count % 16 != 0` 或字段切片错位直接返回 `-EINVAL` 拒绝写入。
   **标准 Python 打包格式必须严格指定为 32 位小端**: `'<IIHHi'`。
2. **全零时间戳引发的速度追踪崩溃**:
   `tslib` 与 `greenui::VelocityTracker` 计算滑动手势速度时采用差分公式 $\Delta v = \frac{\Delta s}{\Delta t}$。若注入时将 `tv_sec` 与 `tv_usec` 填为 0，会导致 $\Delta t \le 0$，在 VFP 浮点单元中触发除以零异常（`NaN` / `Inf`），导致手势丢弃或窗口管理器崩溃。
   必须使用 `time.clock_gettime(time.CLOCK_MONOTONIC)` 获取严格递增的单调时间戳。

---

## 3. 物理按键事件分发与 QuickJS JSAPI 桥接

### 3.1 C++ HAL 观察者管道 (`libydhal_devices.so`)
`libydhal_devices.so` 内部常驻一个 `epoll` 线程池监控三个物理输入节点（`event0`, `event1`, `event2`）。底层驱动上报的键值经过硬件去抖滤波、长按短按状态机判决后，打包为 `YDALAPI::YButtonEventModule` 观察者事件。

### 3.2 `libjsapi_export_core.so` 模块加载与原型绑定
- **动态模块注册**: `buttonEvent_module_init_jsapis`（`0x000a0040`）调用 `registerCModuleLoader("buttonEvent", ...)` 将原生 C 模块注入 QuickJS。
- **类模板构造**: 创建 `ButtonEvent` 原型，当 JS 执行 `new buttonEvent.ButtonEvent()` 时，实例化底层 `JSButtonEventModuleProxy`。
- **观察者挂载**: `JSButtonEventModuleProxy::initObserver`（`0x000a2258`）将自身的 C++ 回调函数接入 HAL 单例。当按键动作触发时，通过 `JQSignal::emit` 投递至 JS 主事件循环。

### 3.3 JavaScript 原型方法字典

| 方法名 | 汇编虚拟地址 | 入参规格 | 详细功能与底层行为 |
| :--- | :--- | :--- | :--- |
| `softButtonEvent` | `0x000a1844` | `(key: string, event: string)` | 软件模拟注入按键。<br>`key`: `"home"`, `"play"`, `"volume_up"` 等。<br>`event`: `"press"`, `"release"`, `"click"`, `"long_press"`。 |
| `emitBottomSwipeBackEvent` | `0x0009fc78` | `()` | 主动触发底部上滑返回手势，通知系统销毁退出当前 MiniApp。 |
| `setButtonEventReady` | `0x0009ff9c` | `(ready: boolean)` | 通知底层 HAL 观察者：JS 运行环境已准备就绪，可以开始投递按键中断。 |
| `isHeadButtonPressed` | `0x0009fe90` | `(): boolean` | 同步轮询当前笔尖微动开关是否处于按压闭合状态。 |

---

### 3.4 45 组全量 JQSignal 信号清单与固件历史拼写缺陷 ("Relese")

通过对 `libjsapi_export_core.so` 符号表与常量字符串池的完整反汇编，提取出全部 45 组按键信号标识：

```
+------------------------------------+---------------------------------------------------------------------------------+
| 物理按键类别                       | 原生暴露的 JQSignal 信号标识符                                                  |
+------------------------------------+---------------------------------------------------------------------------------+
| 笔尖光学微动开关                   | headButtonPress, headButtonRelese                                               |
| 实体 Home / 语音侧键               | homeButtonPress, homeButtonRelease, homeButtonLongPress,                        |
|                                    | homeButtonClick, homeButtonDoubleClick                                          |
| 电源键                             | powerButtonPress, powerButtonRelese, powerButtonLongPress,                       |
|                                    | powerButtonClick, powerButtonDoubleClick                                        |
| 播放 / 暂停键                      | playButtonPress, playButtonRelese, playButtonLongPress,                          |
|                                    | playButtonClick, playDoubleClick                                                |
| 返回键                             | backButtonPress, backButtonRelese, backButtonLongPress,                          |
|                                    | backButtonClick, backDoubleClick                                                |
| 前进键                             | forwardButtonPress, forwardButtonRelese, forwardButtonLongPress,                  |
|                                    | forwardButtonClick, forwardDoubleClick                                          |
| 音量加键                           | volumeUpButtonPress, volumeUpButtonRelese, volumeUpButtonLongPress,              |
|                                    | volumeUpButtonClick, volumeUpDoubleClick                                        |
| 音量减键                           | volumeDownButtonPress, volumeDownButtonRelese, volumeDownButtonLongPress,        |
|                                    | volumeDownButtonClick, volumeDownDoubleClick                                    |
| 摄像头取景触发                     | headCameraPreviewButtonPress, headCameraPreviewButtonRelease,                   |
|                                    | headCameraPreviewButtonClick, headCameraPreviewButtonDoubleClick                |
| 霍尔与旋钮传感器                   | hallTop, hallBottom, rotaryTurn                                                 |
| 边缘滑动手势导航                   | bottomSwipeBackEvent                                                            |
+------------------------------------+---------------------------------------------------------------------------------+
```

> ⚠️ **高危固件逆向陷阱：释放事件的 "Relese" 拼写错误**  
> 有道固件开发团队在底层 C++ 信号字符串常量定义时出现了拼写笔误：  
> `headButton`、`powerButton`、`playButton`、`backButton`、`forwardButton`、`volumeUpButton`、`volumeDownButton` 的释放事件**全部少了一个字母 "a"，拼写为 `Relese`**！  
> 而 `homeButtonRelease` 与 `headCameraPreviewButtonRelease` 却采用了正确的标准英文拼写 `Release`。  
> 开发者在编写 JS 监听器时必须精确匹配上述标识，否则永远无法接收到按键松开回调！

---

## 4. 屏幕睡眠、唤醒锁与触控挂起/恢复全链路

### 4.1 Framebuffer 广播与 `axs_fb_notifier_callback`
当无操作超时或按下电源键时，Falcon 触发息屏：
1. `ioctl(fb_fd, FBIOBLANK, FB_BLANK_POWERDOWN)`（参数 `4`）。
2. Linux Framebuffer 核心向内核链表广播 `FB_EVENT_BLANK`。
3. `axs_ts.ko` 中的注册函数 `axs_fb_notifier_callback` 捕获该事件。

### 4.2 `axs_lcd_off` 13 字节休眠指令封包反汇编
在 `axs_ts.ko` 的 `.text.unlikely` 段（偏移 `0x00000024`）中反汇编发现：
```arm
0x00000024: push {r4, lr}
0x00000026: sub  sp, #24                 ; 分配 24 字节栈帧
0x00000028: ldr  r1, [pc, #36]           ; 加载 .rodata (0xdf) 中的 13 字节休眠指令包
0x0000002a: add  r0, sp, #4
0x0000002c: ldm  r1!, {r2, r3, ip}       ; 复制前 12 字节
0x00000030: ldrb r1, [r1]                ; 复制第 13 字节
0x00000032: stm  r0!, {r2, r3, ip}
0x00000036: strb r1, [r0]
0x00000038: add  r1, sp, #4
0x0000003a: mov  r2, #13                 ; 长度 = 13 字节
0x0000003c: bl   axs_write_bytes         ; 通过 I2C-1 向 AXS15205 写入休眠封包
0x00000040: ldr  r0, [pc, #20]           ; 打印日志: " write 0x28 %s\n"
0x00000042: bl   printk
```
提取出的 13 字节休眠封包十六进制载荷为：
`\xb5\xab\x5a\xa5\x00\x02\x00\x00\x00\x00\x00\x28\x10`
写入该指令后，AXS15205 触控芯片彻底关闭内部振荡器与电荷泵，进入微安级休眠状态。驱动接着调用 `disable_irq_nosync()` 禁用硬件中断线。

### 4.3 硬件复位脉冲与 100ms 驱动恢复延迟
在屏幕唤醒（`FB_BLANK_UNBLANK` 即 `0`）时，`axs_ts_resume` 执行严苛的硬件时序恢复：
1. 拉低 Reset GPIO 并维持 $10\text{ ms}$ 复位脉冲；
2. 拉高 Reset GPIO 后，调用 `usleep_range(100000, 110000)` **强制休眠等待 100~110 毫秒**，以等待 AXS15205 内部 8051 内核固件引导自检完成；
3. 重新向中断控制器使能 `enable_irq()`。
> **工程提示**: 屏幕点亮后的前 $120\text{ ms}$ 内，触控屏幕无法响应任何输入，测试脚本必须在此延时后方可注入触控。

### 4.4 硬件级唤醒电路与屏下不可唤醒铁律
由于息屏后触控芯片已被完全断电/休眠且中断关闭，**在 S7 Pro 处于休眠状态时，双击或触摸屏幕绝对无法点亮屏幕**。
能够将 CPU 从 `suspend`（`/sys/power/state` 写 `mem`）唤醒的物理源仅有设备树中声明了 `wakeup-source` 的物理硬件引脚：
1. **AXP2101 PMIC PEK (`KEY_POWER`)**: 按下电源键触发 PMIC IRQ 唤醒；
2. **笔尖微动开关 (`KEY_CAMERA`)**: 笔尖接触纸面受压下压瞬间闭合 GPIO 唤醒，实现“提笔即扫”；
3. **实体 Home 键 (`KEY_HOMEPAGE`)**: 侧键物理触发。

---

## 5. 生产级开发规范与全功能实现代码

### 5.1 精确 C 数据结构定义 (`s7pro_input.h`)

```c
#ifndef _S7PRO_INPUT_H_
#define _S7PRO_INPUT_H_

#include <stdint.h>
#include <linux/input.h>

/*
 * 适用于 32 位 ARM Linux (armhf) 的严格 16 字节 input_event 内存布局
 */
struct s7pro_input_event {
    uint32_t tv_sec;  /* 单调时间戳秒数 (CLOCK_MONOTONIC) */
    uint32_t tv_usec; /* 微秒数 */
    uint16_t type;    /* EV_SYN (0x00), EV_KEY (0x01), EV_ABS (0x03) */
    uint16_t code;    /* ABS_MT_*, KEY_* */
    int32_t  value;   /* 键值、坐标或状态 */
} __attribute__((packed));

#define S7PRO_INPUT_EVENT_SIZE sizeof(struct s7pro_input_event) /* 16 字节 */

/* 物理按键代码定义 */
#define S7PRO_KEY_PEN_TIP   212  /* KEY_CAMERA (/dev/input/event0) */
#define S7PRO_KEY_POWER     116  /* KEY_POWER  (/dev/input/event1) */
#define S7PRO_KEY_SIDE_HOME 28   /* KEY_ENTER  (/dev/input/event2) */

/* 屏幕与触控几何参数 */
#define S7PRO_RAW_MAX_X     239
#define S7PRO_RAW_MAX_Y     1019
#define S7PRO_LOGIC_WIDTH   1020
#define S7PRO_LOGIC_HEIGHT  240

#endif /* _S7PRO_INPUT_H_ */
```

---

### 5.2 原生 C 事件注入独立工具 (`s7pro_inject.c`)

该工具可在 ARM 词典笔端直接运行，支持毫秒级高精度触控与按键注入：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <errno.h>
#include <linux/input.h>
#include "s7pro_input.h"

static void emit_raw(int fd, uint16_t type, uint16_t code, int32_t value) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);

    struct s7pro_input_event ev;
    ev.tv_sec  = (uint32_t)ts.tv_sec;
    ev.tv_usec = (uint32_t)(ts.tv_nsec / 1000);
    ev.type    = type;
    ev.code    = code;
    ev.value   = value;

    if (write(fd, &ev, sizeof(ev)) != sizeof(ev)) {
        fprintf(stderr, "Write error: %s\n", strerror(errno));
    }
}

static void emit_syn(int fd) {
    emit_raw(fd, EV_SYN, SYN_REPORT, 0);
}

/*
 * 注入逻辑视口点击 (1020 x 240)
 * 自动完成逆向旋转: raw_x = log_y, raw_y = 1019 - log_x
 */
int inject_tap(int log_x, int log_y, int duration_ms) {
    int fd = open("/dev/input/event3", O_WRONLY);
    if (fd < 0) {
        perror("Open /dev/input/event3 failed");
        return -1;
    }

    /* 边界约束 */
    if (log_x < 0) log_x = 0;
    if (log_x > 1019) log_x = 1019;
    if (log_y < 0) log_y = 0;
    if (log_y > 239) log_y = 239;

    int raw_x = log_y;
    int raw_y = 1019 - log_x;

    /* 1. 按下 */
    emit_raw(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_raw(fd, EV_ABS, ABS_MT_TRACKING_ID, 100);
    emit_raw(fd, EV_ABS, ABS_MT_POSITION_X, raw_x);
    emit_raw(fd, EV_ABS, ABS_MT_POSITION_Y, raw_y);
    emit_raw(fd, EV_ABS, ABS_MT_PRESSURE, 60);
    emit_raw(fd, EV_ABS, ABS_MT_TOUCH_MAJOR, 10);
    emit_raw(fd, EV_KEY, BTN_TOUCH, 1);
    emit_syn(fd);

    usleep(duration_ms * 1000);

    /* 2. 松开 */
    emit_raw(fd, EV_ABS, ABS_MT_SLOT, 0);
    emit_raw(fd, EV_ABS, ABS_MT_TRACKING_ID, -1);
    emit_raw(fd, EV_KEY, BTN_TOUCH, 0);
    emit_syn(fd);

    close(fd);
    return 0;
}
```

---

### 5.3 生产级 Python 3 触控/按键注入器 (`s7pro_input.py`)

运行于宿主机并通过 SSH 管道流式写入，或直接在测试机执行：

```python
#!/usr/bin/env python3
"""
s7pro_input.py - 有道 S7 Pro 硬件输入与触控手势注入工具
严格遵循 16 字节 ARM EABI 结构体与 270 度逆向旋转方程
"""

import struct
import time
import os
import sys

EV_SYN = 0x00
EV_KEY = 0x01
EV_ABS = 0x03

SYN_REPORT = 0x00
BTN_TOUCH = 0x14A

ABS_MT_SLOT = 0x2F
ABS_MT_TOUCH_MAJOR = 0x30
ABS_MT_POSITION_X = 0x35
ABS_MT_POSITION_Y = 0x36
ABS_MT_TRACKING_ID = 0x39
ABS_MT_PRESSURE = 0x3A

# 严格对齐 32 位 Linux 格式: uint32, uint32, uint16, uint16, int32 (16 字节)
FORMAT = '<IIHHi'

def pack_ev(ev_type: int, code: int, val: int) -> bytes:
    now = time.clock_gettime(time.CLOCK_MONOTONIC)
    sec = int(now)
    usec = int((now - sec) * 1_000_000)
    return struct.pack(FORMAT, sec, usec, ev_type, code, val)

def syn() -> bytes:
    return pack_ev(EV_SYN, SYN_REPORT, 0)

class S7ProTouch:
    def __init__(self, dev="/dev/input/event3"):
        self.dev = dev

    @staticmethod
    def log2raw(lx: int, ly: int):
        clamped_x = max(0, min(1019, lx))
        clamped_y = max(0, min(239, ly))
        return clamped_y, (1019 - clamped_x)

    def tap(self, lx: int, ly: int, duration: float = 0.05):
        rx, ry = self.log2raw(lx, ly)
        with open(self.dev, "wb", buffering=0) as f:
            f.write(b"".join([
                pack_ev(EV_ABS, ABS_MT_SLOT, 0),
                pack_ev(EV_ABS, ABS_MT_TRACKING_ID, 501),
                pack_ev(EV_ABS, ABS_MT_POSITION_X, rx),
                pack_ev(EV_ABS, ABS_MT_POSITION_Y, ry),
                pack_ev(EV_ABS, ABS_MT_PRESSURE, 50),
                pack_ev(EV_ABS, ABS_MT_TOUCH_MAJOR, 8),
                pack_ev(EV_KEY, BTN_TOUCH, 1),
                syn()
            ]))
            time.sleep(duration)
            f.write(b"".join([
                pack_ev(EV_ABS, ABS_MT_SLOT, 0),
                pack_ev(EV_ABS, ABS_MT_TRACKING_ID, -1),
                pack_ev(EV_KEY, BTN_TOUCH, 0),
                syn()
            ]))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, steps: int = 20, duration: float = 0.25):
        rx1, ry1 = self.log2raw(x1, y1)
        rx2, ry2 = self.log2raw(x2, y2)
        step_dt = duration / max(steps, 1)

        with open(self.dev, "wb", buffering=0) as f:
            f.write(b"".join([
                pack_ev(EV_ABS, ABS_MT_SLOT, 0),
                pack_ev(EV_ABS, ABS_MT_TRACKING_ID, 502),
                pack_ev(EV_ABS, ABS_MT_POSITION_X, rx1),
                pack_ev(EV_ABS, ABS_MT_POSITION_Y, ry1),
                pack_ev(EV_ABS, ABS_MT_PRESSURE, 60),
                pack_ev(EV_KEY, BTN_TOUCH, 1),
                syn()
            ]))
            for i in range(1, steps + 1):
                cur_x = int(rx1 + (rx2 - rx1) * (i / steps))
                cur_y = int(ry1 + (ry2 - ry1) * (i / steps))
                f.write(b"".join([
                    pack_ev(EV_ABS, ABS_MT_SLOT, 0),
                    pack_ev(EV_ABS, ABS_MT_POSITION_X, cur_x),
                    pack_ev(EV_ABS, ABS_MT_POSITION_Y, cur_y),
                    syn()
                ]))
                time.sleep(step_dt)
            f.write(b"".join([
                pack_ev(EV_ABS, ABS_MT_SLOT, 0),
                pack_ev(EV_ABS, ABS_MT_TRACKING_ID, -1),
                pack_ev(EV_KEY, BTN_TOUCH, 0),
                syn()
            ]))

if __name__ == "__main__":
    touch = S7ProTouch()
    # 点击主屏幕正中心
    touch.tap(510, 120)
```

---

### 5.4 生产级 QuickJS 硬件按键管理器 (`S7ProButtonManager.js`)

彻底屏蔽底层拼写缺陷（自动兼容 `Relese` 与 `Release`），提供安全的信号生命周期注销机制：

```javascript
/**
 * S7ProButtonManager.js
 * 专为有道词典笔 S7 Pro 打造的生产级硬件按键与传感器管理器
 */
export class S7ProButtonManager {
  constructor() {
    this._module = null;
    this._proxy = null;
    this._subscriptions = [];
    this._handlers = {
      penDown: [],
      penUp: [],
      homeClick: [],
      homeLongPress: [],
      powerPress: [],
      swipeBack: []
    };

    this._bootstrap();
  }

  _bootstrap() {
    try {
      const buttonEventModule = require('buttonEvent');
      this._module = buttonEventModule;
      this._proxy = new buttonEventModule.ButtonEvent();
      
      // 通知底层 HAL 观察者已准备接收事件
      if (typeof this._proxy.setButtonEventReady === 'function') {
        this._proxy.setButtonEventReady(true);
      }
    } catch (e) {
      console.warn('[ButtonManager] Failed to load native buttonEvent module:', e);
    }
  }

  _attach(signal, cb) {
    if (signal && typeof signal.connect === 'function') {
      signal.connect(cb);
      this._subscriptions.push({ signal, cb });
    }
  }

  /**
   * 启动硬件事件监听 (全自动抹平底层拼写笔误)
   */
  start() {
    if (!this._proxy) return;

    // 1. 笔尖触纸微动传感器 (注意固件历史拼写缺陷: headButtonRelese)
    this._attach(this._proxy.headButtonPress, () => {
      this._handlers.penDown.forEach(fn => fn());
    });
    const headReleaseSig = this._proxy.headButtonRelese || this._proxy.headButtonRelease;
    this._attach(headReleaseSig, () => {
      this._handlers.penUp.forEach(fn => fn());
    });

    // 2. 侧边 Home 功能键 (正确拼写: homeButtonRelease)
    this._attach(this._proxy.homeButtonClick, () => {
      this._handlers.homeClick.forEach(fn => fn());
    });
    this._attach(this._proxy.homeButtonLongPress, () => {
      this._handlers.homeLongPress.forEach(fn => fn());
    });

    // 3. 电源按键 (注意拼写: powerButtonRelese)
    this._attach(this._proxy.powerButtonPress, () => {
      this._handlers.powerPress.forEach(fn => fn());
    });

    // 4. 底部边缘返回滑动手势
    this._attach(this._proxy.bottomSwipeBackEvent, () => {
      this._handlers.swipeBack.forEach(fn => fn());
    });
  }

  onPenDown(fn)     { this._handlers.penDown.push(fn); return this; }
  onPenUp(fn)       { this._handlers.penUp.push(fn); return this; }
  onHomeClick(fn)   { this._handlers.homeClick.push(fn); return this; }
  onHomeLong(fn)    { this._handlers.homeLongPress.push(fn); return this; }
  onSwipeBack(fn)   { this._handlers.swipeBack.push(fn); return this; }

  /**
   * 同步查询笔尖是否正压在纸面上
   */
  isPenDepressed() {
    if (this._proxy && typeof this._proxy.isHeadButtonPressed === 'function') {
      return this._proxy.isHeadButtonPressed();
    }
    return false;
  }

  /**
   * 页面卸载时必须调用销毁，严防 QuickJS 闭包内存泄漏
   */
  destroy() {
    for (const sub of this._subscriptions) {
      if (sub.signal && typeof sub.signal.disconnect === 'function') {
        try {
          sub.signal.disconnect(sub.cb);
        } catch (_) {}
      }
    }
    this._subscriptions = [];
    this._handlers = { penDown: [], penUp: [], homeClick: [], homeLongPress: [], powerPress: [], swipeBack: [] };
    this._proxy = null;
  }
}
```

---

### 5.5 端到端 Vue SFC 组件集成示例

```html
<template>
  <div class="reader-viewport">
    <div class="status-indicator">
      <span class="status-title">笔尖扫描状态:</span>
      <span :class="['status-badge', isScanning ? 'badge-active' : 'badge-idle']">
        {{ isScanning ? '正在划词扫描...' : '就绪 (笔尖未着纸)' }}
      </span>
    </div>
    <div class="debug-panel">
      <text class="debug-text">{{ eventLog }}</text>
    </div>
  </div>
</template>

<script>
import { S7ProButtonManager } from './S7ProButtonManager.js';

export default {
  data() {
    return {
      btnManager: null,
      isScanning: false,
      eventLog: '等待按键或笔尖触发...'
    };
  },
  mounted() {
    this.btnManager = new S7ProButtonManager();

    this.btnManager
      .onPenDown(() => {
        this.isScanning = true;
        this.eventLog = '笔尖触纸: 启动高速 CMOS 图像采集 (/dev/video0)';
      })
      .onPenUp(() => {
        this.isScanning = false;
        this.eventLog = '笔尖离纸: 截流送检端侧 OCR 识别引擎';
      })
      .onHomeClick(() => {
        this.eventLog = '点击 Home 键: 保存进度并退出';
      })
      .onHomeLong(() => {
        this.eventLog = '长按 Home 键: 激活小P老师实时语音助手';
      })
      .onSwipeBack(() => {
        this.eventLog = '边缘滑动手势: 页面后退';
      });

    this.btnManager.start();
  },
  beforeDestroy() {
    if (this.btnManager) {
      this.btnManager.destroy();
      this.btnManager = null;
    }
  }
};
</script>

<style scoped>
.reader-viewport {
  width: 1020px;
  height: 240px;
  background-color: #0F1115;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
.status-indicator {
  display: flex;
  flex-direction: row;
  align-items: center;
  margin-bottom: 12px;
}
.status-title {
  font-size: 18px;
  color: #9E9E9E;
  margin-right: 10px;
}
.status-badge {
  font-size: 18px;
  padding: 4px 12px;
  border-radius: 6px;
}
.badge-active {
  background-color: #00E676;
  color: #000000;
  font-weight: bold;
}
.badge-idle {
  background-color: #263238;
  color: #B0BEC5;
}
.debug-panel {
  width: 900px;
  height: 60px;
  background-color: #1A1D24;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.debug-text {
  font-size: 16px;
  color: #40C4FF;
}
</style>
```
