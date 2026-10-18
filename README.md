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
- [六、 仓库目录与配套工具集](#六-仓库目录与配套工具集)

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

## 二、 突破思路与方案选型演进

1. **为什么放弃 ADB 密码暴力破解？**
   - 官方 `/usr/bin/adb_auth.sh` 内部硬编码了设备特定哈希，且设备上缺少包管理器。即使猜出密码，系统也是只读 EROFS 且受限于 Falcon 沙盒。
2. **为什么选用应用商店劫持与 Native 注入？**
   - Falcon 应用商店允许在线下载 `.amr` 应用包并解压安装到可读写的 `/userdata/app/<appid>/` 分区；
   - 宿主进程 `/usr/bin/miniapp` 天然具备 **UID 0 (root)** 特权，且应用包内支持加载架构动态库（`libs/arm-y08/libjsapi_*.so`）；
   - 动态库通过 `dlopen` 载入时直接继承宿主进程的全局 root 特权，可无限制执行系统级调用。
3. **定位：一次性“破门跳板”（Bootstrap）**：
   - 应用商店劫持与 QuickJS 逆向**仅用于第一步打开大门**；
   - 拿到 Root ADB 之后，后续应用开发彻底转为原生 Linux 开发流程，无需再逆向应用包。

---

## 三、 完整突破链条深度解析

```
+------------------+         HTTP 80 / HTTPS 443         +--------------------+
|  词典笔 (S7 Pro) | ----------------------------------> | macOS 透明代理服务 |
|  (192.168.2.x)   | <---------------------------------- | (192.168.2.1)      |
+------------------+     下发 custom_app.amr (14514)     +--------------------+
        |
        v 点击安装并打开
+-----------------------------------------------------------------------------+
| Falcon 宿主进程 (/usr/bin/miniapp) [UID 0 root]                             |
|  1. 扫描 libs/arm-y08/libjsapi_baidupan.so                                  |
|  2. dlopen 载入 -> 触发 custom_init_jsapis                                  |
|  3. 执行劫持后的 system("touch /tmp/.adb_auth_verified; echo root:root|...") |
+-----------------------------------------------------------------------------+
        |
        v
+-----------------------------------------------------------------------------+
| 1. /tmp/.adb_auth_verified 建立 -> adb shell 永久免密直通                   |
| 2. /etc/shadow root 密码被修改为 root                                       |
| 3. /userdisk/skip_re/skip_login.sh 写入 -> 开机持久化生效                   |
| 4. OpenSSH (sshd) 服务在 0.0.0.0:22 启动                                    |
+-----------------------------------------------------------------------------+
```

### 3.1 macOS 热点与透明代理搭建
- macOS 开启 Wi-Fi 共享，分配热点网卡 `bridge100`（网关 `192.168.2.1`）。
- 通过 `pfctl` 配置包过滤透明重定向：
  ```
  rdr pass on bridge100 proto tcp from any to any port 80 -> 192.168.2.1 port 8080
  rdr pass on bridge100 proto tcp from any to any port 443 -> 192.168.2.1 port 8443
  ```
- 部署包含所有有道 CDN / IoT 域名的自签名多域名 SSL 证书（SAN 扩展包含 `dictpen-appstore.youdao.com`、`hardware-iot.youdao.com`、`ydhardwarecommon.nosdn.127.net` 等）。

### 3.2 官方应用商店协议逆向与伪造注入
代理服务器（`host_tools/appstore_server.py`）针对关键 API 进行拦截注入：
1. **分类栏目接口 (`/front/store_column/store_column_s`)**：保持官方栏目（热门推荐、学习、工具）反向代理，保证 UI 正常渲染。
2. **栏目应用列表接口 (`/front/store_column/store_column_app_s`)**：在返回的 `appList` 首部注入自定义应用元数据（ID: `8888000188880001`，名称: `极客工具箱`）。

### 3.3 破解关键安装缺陷
- **缺陷 1：家长禁止下载应用**
  - **根因**：`pullSceneList` 返回数据缺少 `s202` 管控白名单。
  - **修复**：代理层将 `s202` 的 `sceneData.status` 与 `operation.status` 强制改写为 `1`。
- **缺陷 2：下载后提示“安装失败”**
  - **根因**：应用版本检查接口 `/app/store/version/info/batch` 返回网易云端状态码 `rollingBack: 407`，触发 Falcon 引擎底层汇编（`0x28fb20: cmp r5, #200; bhi markInstallError`）。
  - **修复**：代理层拦截该接口，强制改写为 `rollingBack: 0`，并下发本地 HTTP（端口 14514）下载链接与准确的文件 MD5 和 Size。

### 3.4 Falcon 容器特权模型与 Native SO 筛选机制
逆向 Falcon 核心库 `libfalcon.so` 确认：
1. 解压包时，`executeInstallPackage` 会将 `libs/arm-y08/` 重命名为 `libs/`。
2. 启动阶段，`falcon::PrivateJSApiEntry::init` 会遍历应用 `libs/` 目录，严格匹配以 `libjsapi_` 开头且以 `.so` 结尾的文件。
3. 加载函数 `dynamic_load_jsapi` 执行 `dlopen(path, RTLD_NOW | RTLD_GLOBAL)`，并调用导出的 `custom_init_jsapis` 入口。

### 3.5 ELF 符号劫持与 Root Shell 初始化
利用脚本 `host_tools/patch_so.py` 对官方 `libjsapi_baidupan.so` 进行二进制修补：
1. **符号表篡改**：在 `.dynstr` 中将等长字符串 `remove\x00`（7 字节）改写为 `system\x00`（7 字节）。
2. **跳转重定向**：在 `custom_init_jsapis`（`0x12478`）中，将原 `bl puts@plt` 指令替换为 `bl remove@plt`（`0xebfffb27`）。动态链接时，`remove@plt` 自动解析为 libc 的 `system()` 函数。
3. **命令注入**：将 `r0` 指向 `.rodata` 中的指令：
   ```sh
   touch /tmp/.adb_auth_verified; echo root:root|chpasswd 2>/dev/null; sh /userdata/app/*/init.sh &
   ```
4. **效果**：应用打开瞬间，系统在 **UID 0** 权限下创建 `/tmp/.adb_auth_verified`，ADB 调试鉴权瞬间失效，直通免密 Shell！

---

## 四、 永久固化机制 (开机免密 ADB + 无线 SSH)

系统根分区虽然为只读 EROFS，但在 `/etc/init.d/S99_run_test_scripts` 中存在原生扩展点：
```sh
[ -f /userdisk/skip_re/skip_login.sh ] || exit 0
start() {
    printf "Starting test script: skip_login.sh "
    /userdisk/skip_re/skip_login.sh &
    echo "done"
}
```

我们在 `/userdisk/skip_re/skip_login.sh` 部署了固化持久化脚本，在每次开机时执行以下关键操作：
1. **ADB 鉴权覆盖**：`mount --bind /userdata/bin/adb_auth.sh /usr/bin/adb_auth.sh`（永久直通，无论标志文件是否存在）。
2. **密码表覆盖**：`mount --bind /userdata/etc/shadow /etc/shadow`（将 root 登录密码永久设为 `root`）。
3. **启动无线 SSH**：调用系统自带的 `/usr/bin/sshd_service start`，监听 `0.0.0.0:22`。
4. **守护线程**：后台持续维护 `/tmp/.adb_auth_verified` 标志。

---

## 五、 原生应用极速开发工作流

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
4. **统一 Docker 构建环境（可选）**：
   ```bash
   docker build -f docker/Dockerfile.sdk -t s7pro-sdk .
   docker run --rm -v $(pwd):/workspace s7pro-sdk bash -c "cmake -B build -DCMAKE_TOOLCHAIN_FILE=cmake/arm-cv1813.cmake && cmake --build build"
   ```

---

## 六、 仓库目录与配套工具集

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
│   └── deploy.sh                 # 有线 ADB / 无线 SSH 一键极速部署与执行脚本
├── examples/
│   └── 01_hello_hardware/        # 硬件信息与 Framebuffer 探测示例源码
├── docs/
│   └── s7pro_developer_guide.md  # 详细硬件接口、驱动拓扑与外设开发指南
├── host_tools/
│   ├── appstore_server.py        # macOS 端透明代理与应用商店拦截下发服务器
│   ├── patch_so.py               # ELF 动态库 Native Hook 自动修补工具
│   └── quickjs_atom_tool.py      # QuickJS 字节码 (.js.bin) 原子表解析器
├── device_payload/
│   ├── skip_login.sh             # 设备端永久开机固化执行脚本
│   ├── adb_auth.sh               # 永久放行的 mock adb_auth 脚本
│   └── shadow                   # 固化 root 密码为 root 的 shadow 配置文件
└── certs/
    └── appstore_cert_gen.sh      # 多域名 SAN 自签名 SSL 证书生成脚本
```

---

## 开源许可证 / License
本项目采用 [MIT License](LICENSE) 开源许可协议。

---

## 免责声明 / Disclaimer
本项目仅供嵌入式 Linux 系统安全研究、硬件底层适配及设备所有者自研学习使用。请勿用于未授权的商业或恶意用途。
