# 有道词典笔 S7 Pro 包管理系统 (PMS)、AMR 格式与沙箱安全全景手册
## (Falcon PMS, AMR Pipeline, Package Verification & Security Sandbox Architecture Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `/usr/bin/miniapp`, `/usr/bin/miniapp_cli`, `/usr/lib/libfalcon.so` (`JQuick::IotPackageManager`, `jq::Sandbox`)

---

## 目录索引

1. [miniapp 守护进程与 miniapp_cli 通信协议](#1-miniapp-守护进程与-miniapp_cli-通信协议)
2. [.amr 安装流水线与校验状态机全流程](#2-amr-安装流水线与校验状态机全流程)
   - [2.1 ZIP 归档提取与目录结构规范](#21-zip-归档提取与目录结构规范)
   - [2.2 `manifest.json` 模式解析与字段定义](#22-manifestjson-模式解析与字段定义)
   - [2.3 `cert` 散列表校验真相与白名单遍历漏洞](#23-cert-散列表校验真相与白名单遍历漏洞)
   - [2.4 数字签名验证缺失与证书过期提示真相](#24-数字签名验证缺失与证书过期提示真相)
   - [2.5 原生动态库重定位与 `chrpathSoFiles` 机制](#25-原生动态库重定位与-chrpathsofiles-机制)
   - [2.6 A/B 槽位轮转部署状态机与 `packages.json` 注册表](#26-ab-槽位轮转部署状态机与-packagesjson-注册表)
3. [沙箱文件系统与系统级权限深度评估](#3-沙箱文件系统与系统级权限深度评估)
   - [3.1 虚拟路径转换与父目录遍历漏洞 (`jq::Sandbox::changePath`)](#31-虚拟路径转换与父目录遍历漏洞-jqsandboxchangepath)
   - [3.2 高危无校验接口 (`fs.rm` / `fs.mkdir`)](#32-高危无校验接口-fsrm--fsmkdir)
   - [3.3 内置 `process` 原生 C 模块与任意 Shell 命令执行](#33-内置-process-原生-c-模块与任意-shell-命令执行)
   - [3.4 Linux 系统级隔离机制现状 (DAC / Namespaces / Seccomp)](#34-linux-系统级隔离机制现状-dac--namespaces--seccomp)
4. [生产级打包工具实现规范 (`build_amr.py` 核心逻辑)](#4-生产级打包工具实现规范-build_amrpy-核心逻辑)

---

## 1. miniapp 守护进程与 miniapp_cli 通信协议

在 S7 Pro 固件中：
- `/usr/bin/miniapp` 是微型启动存根，无条件跳转至 `libfalcon.so` 的 `falcon_entry()`。
- `libfalcon.so` 在启动时创建了 UNIX Domain Socket 监听端点：`/var/run/miniapp-dbg.socket`（`AF_LOCAL`, `SOCK_STREAM`），其内嵌了一个轻量级 HTTP/1.1 RESTful 服务。
- 命令行工具 `/usr/bin/miniapp_cli` 并不是通过 D-Bus 或 Binder 通信，而是直接向该 Socket 发送标准的 HTTP 请求：

```http
POST /install HTTP/1.1
Host: 127.0.0.1
Content-Type: application/json
Connection: close
Content-Length: <length>

{"path":"/tmp/my_app.amr"}
```

服务端在 `PkgUploadViews::install(HttpCtx&)`（地址 `0x719768`）中提取 `path` 参数，并将其交由 `JQuick::IotPackageManager::installPackageSync` 执行。

---

## 2. .amr 安装流水线与校验状态机全流程

```
[miniapp_cli install /tmp/my_app.amr]
                    │
                    ▼
[AF_LOCAL Socket POST /install]
                    │
                    ▼
[JQuick::IotPackageManager::executeInstallPackage (0x25f2c8)]
  ├── 1. 临时目录解压: miniUnzip(amrPath, "/tmp/miniapp_xxxxxx")
  ├── 2. 读取并解析 "manifest.json"
  ├── 3. IotPackageManager::verifyAmrContent()
  │        ├── 若 manifest["cert"] 为空对象 {} -> 直接跳过验证，返回成功 (1)!
  │        └── 若包含 cert -> 仅遍历 cert 声明的文件，比对 st_size 与 MD5
  ├── 4. 原生库提取: processArchLibs(tmpDir) -> 移动 libs/arm/*.so
  ├── 5. A/B 槽位轮转: slot = slot ^ 1 (a 或 b)
  ├── 6. 原子目录切换: rename(tmpDir, installPath)
  ├── 7. ELF RPATH 重定位: chrpathSoFiles(installPath + "/libs/", ".so")
  └── 8. 持久化注册: 写入 /userdata/miniapp/data/mini_app/pkg/packages.json
```

### 2.1 ZIP 归档提取与目录结构规范
- `.amr` 本质为标准 PKZIP 归档格式，解压过程直接调用 `miniUnzip`（`0x579950`，基于 Info-ZIP / zlib）。
- 解压前**不进行任何外层数字签名或压缩包校验**。

### 2.2 `manifest.json` 模式解析与字段定义
```json
{
  "appid": "8080999900000001",
  "appName": "MyCustomApp",
  "version": "1.0.0",
  "icon": "icon.png",
  "props": {
    "deviceLevel": "1",
    "addDesktop": {
      "y08_platform": true
    }
  },
  "cert": {}
}
```

### 2.3 `cert` 散列表校验真相与白名单遍历漏洞
在 `IotPackageManager::verifyAmrContent`（`0x258934`）的反编译中，证实了如下三大底层结论：
1. **纯二进制 MD5 比对**：仅比对文件字节流，不校验时间戳或文件权限。
2. **白名单单向遍历漏洞**：校验算法仅仅通过 `std::map<string, Json>` 正向遍历 `manifest.json["cert"]` 中声明的文件。**完全没有通过 `readdir()` 检查解压目录中的实际物理文件**！如果攻击者在包内植入未在 `cert` 中声明的额外脚本、可执行 ELF 文件或动态库，**校验过程完全视而不见并无条件放行**！
3. **空 `cert` 免校验后门**：当 `"cert": {}` 时，迭代器 `begin == end`，函数直接无条件返回 `1`（校验通过）。

### 2.4 数字签名验证缺失与证书过期提示真相
- 全动态符号表检索证实：**Falcon 运行时根本不存在任何 RSA、ECDSA 等非对称公钥数字签名校验逻辑**！
- 固件中出现的 `"The certificate validity has expired"`（`0x733338`）确证属于阿里云 LinkKit 物联网组件中内嵌的开源库 `mbedtls` 的诊断文本，与 MiniApp 的安装校验无任何代码关联。
- **结论**：任何开发者均可自由打包部署自研应用，设备未锁定任何官方私钥签名。

### 2.5 原生动态库重定位与 `chrpathSoFiles` 机制
当安装包中包含 `libs/*.so` 时，PMS 调用 `chrpathSoFiles`（`0x25c3cc`）：
- 直接遍历 ELF 的 `PT_DYNAMIC` 段。
- 将 `DT_RPATH` 和 `DT_RUNPATH` 强制修改为当前应用的物理安装目录（如 `/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/a/libs`），保证动态链接器 `dlopen` 时优先加载应用私有库。

### 2.6 A/B 槽位轮转部署状态机与 `packages.json` 注册表
每次成功安装，槽位在 `a` 与 `b` 之间翻转，避免升级过程中文件被部分写入破坏。安装完成后，元数据写入 `/userdata/miniapp/data/mini_app/pkg/packages.json`，并通过 `pm.emit('installed')` 事件通知桌面刷新卡片。

---

## 3. 沙箱文件系统与系统级权限深度评估

### 3.1 虚拟路径转换与父目录遍历漏洞 (`jq::Sandbox::changePath`)
在 `libfalcon.so` 的地址 `0x6e1840` 处，`Sandbox::changePath` 的实现如下：
```cpp
std::string changePath(const std::string& inputPath) {
    if (startswith(inputPath, this->baseDir)) {
        return inputPath;
    }
    return this->baseDir + "/" + inputPath;
}
```
**严重缺陷**：代码**完全未调用 `realpath` 或过滤 `..` 序列**！
若应用传入相对路径：`../../../../../../etc/passwd`，Linux 内核 VFS 自动展开父目录，应用可直接读取系统敏感文件。

### 3.2 高危无校验接口 (`fs.rm` / `fs.mkdir`)
逆向审计证实，JSAPI `fs` 模块中的 `fs.rm`（`0x6a5f4c`）和 `fs.mkdir`（`0x6a5668`）**根本未调用 `changePath` 进行任何前缀检查**，直接接收开发者传入的原始绝对路径传给底层的 `removeFile` 和 `mkdirs`！
这意味着应用可以直接调用 `fs.rm('/tmp/some_file')` 删除系统临时文件。

### 3.3 内置 `process` 原生 C 模块与任意 Shell 命令执行
在 `_Z17register_jq_jsapiv`（`0x6968a4`）中，系统无条件注册了 `"process"` 模块。
反编译 `0x6b7a50` - `0x6b7d20` 证实：
- 导出类 `ProcessModule` 提供了 `exec(cmd)` 方法。
- 底层通过 `openpty()`、`fork()` 和 `execve()` 衍生子进程。
- **无任何权限隔离**：任何第三方应用在 JS 中导入 `process`，均可以 **`root` (uid=0)** 身份在词典笔上执行任意 Linux Shell 命令！

```javascript
import process from 'process';
process.exec('reboot'); // 具备完整 root 权限
```

### 3.4 Linux 系统级隔离机制现状
- **进程身份**: `miniapp` 主进程直接以 `root` (uid=0, gid=0) 运行。
- **Seccomp / AppArmor / SELinux**: 全部未启用。
- **Namespaces / Chroot**: 未使用任何容器化或命名空间隔离。
- **唯一物理级防御**: 根文件系统 `/` 是只读挂载的 SquashFS。因此 `/bin`、`/usr` 等固件区不可写入，但 `/tmp`、`/userdisk`、`/userdata` 全盘可读写。

---

## 4. 生产级打包工具实现规范

基于底层逆向事实，自研自动化打包工具 `host_tools/build_amr.py` 必须遵守以下工程标准：
1. **排除递归与源码泄露**：遍历文件时必须显式跳过 `manifest.json`、已有 `.amr` 以及已编译为 `.js.bin` 的 `.js` 源码。
2. **ES 模块编译 (`-m`)**：调用 `qjsc` 编译时必须携带 `-m` 参数，并且通过 `-M <module>` 声明外部 C 模块，确保字节码首字节严格为 `0x01` (`BC_VERSION`)。
3. **免验秒级部署**：开发调试阶段可传递 `--no-cert` 参数将 `"cert": {}` 置空，规避 MD5 散列计算与 PMS 校验开销。
