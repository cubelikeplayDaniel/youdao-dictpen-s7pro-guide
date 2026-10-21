# 有道词典笔 S7 Pro QuickJS 字节码与打包校验底层机制深度分析报告

---

## 一、 硬件平台与操作系统全景 (Hardware & OS Invariants)

- **主控平台**: 算能 / 珠海全胜 CV1813H 单核 ARM Cortex-A7 @ 1.0GHz（ARMv7-A 架构，硬浮点 `armv7l`，Linux 5.10.4 内核）。
- **物理显示与视口映射**:
  - 显示设备：Linux Framebuffer（`/dev/fb0`），物理分辨率 1020 × 240（横屏呈现）。
  - 触控与几何变换：物理触控屏与 LCD 面板存在 270 度硬件坐标旋转映射。
- **存储与分区拓扑**:
  - 内存空间：128MB DDR3（常态可用空闲内存约为 15MB~30MB）。
  - 只读系统分区：`/`（SquashFS 挂载）。
  - 持久化配置分区：`/userdata`（可读写，存放全局已安装应用注册表 `/userdata/miniapp/data/mini_app/pkg/packages.json`）。
  - 应用与用户存储分区：`/userdisk`（应用部署于 `/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/`）。
- **GUI 框架与 JS 引擎**: 阿里定制的 HaaS UI / Falcon 嵌入式 GUI 运行时（核心动态库 `/usr/lib/libfalcon.so`），搭配 QuickJS 2020-07-05 作为 JavaScript 解释与字节码执行引擎。

---

## 二、 QuickJS 2020-07-05 字节码底层结构与反编译验证

### 1. 字节码头部规范与 "0x3f (63)" 迷思彻底辟谣
- **字节码首字节不变式**: QuickJS 2020-07-05 字节码的 Byte 0 **恒等于 `0x01` (`BC_VERSION`)**，其后紧随以无符号 LEB128 (ULEB128) 编码的 Atom 符号表计数及 Atom 字符串数组。
- **反编译汇编证据 (`reverse_dump/libquickjs.so` Address `0xac66c`)**:
  ```arm
  0xac66c:  ldrb  r2, [r1]        ; 从字节码起始地址读取 Byte 0
  0xac670:  mov   r0, r6          ; 载入 JSContext* 指针
  0xac674:  add   r1, r1, #1      ; 游标后移至 Atom 计数区域
  0xac678:  cmp   r2, #1          ; 严格比对: Byte 0 是否等于 BC_VERSION (1)
  0xac67c:  bne   #0xac884        ; 若 != 1，直接分支跳转至异常并抛出 "invalid binary object"
  ```
- **"0x3f" 的真实来源**:
  早期文档曾将部分官方包出现的 `0x3f`（十进制 63）误传为魔数。实际上，`0x3f` 是特定 JS 文件编译时**Atom 表数量恰好为 63**的 ULEB128 编码值，或指向 QuickJS 内置预定义 Atom `JS_ATOM_enumerable`（序号 63）。自定义小程序的首字节必须严格为 `0x01`，绝不能人为硬编码 `0x3f`。

### 2. ES 模块 (`-m`) 与 普通脚本 (`-c`) 的分水岭
- **Falcon 模块加载器的强制类型约束 (`falcon::evalJSModule` Address `0x54bd8c`)**:
  ```arm
  0x54c36c:  mov   r3, #1          ; 设置 flags = JS_READ_OBJ_BYTECODE (1)
  0x54c37c:  bl    #0x1de15c       ; 调用 JS_ReadObject(ctx, buf, len, 1)
  0x54c384:  cmp   r1, #6          ; 检查是否为 JS_TAG_EXCEPTION (6)
  0x54c38c:  beq   #0x54cd44       ; 异常退出分支
  0x54c390:  cmn   r1, #3          ; 关键指令: 检查 r1 是否等于 -3 (JS_TAG_MODULE)
  0x54c394:  beq   #0x54d1a4       ; 匹配成功: 进入 JS_ResolveModule 与模块执行流水线
  0x54c398:  ...                   ; 匹配失败: 抛出模块类型不匹配错误并终止应用
  ```
- **编译参数决定标签类型**:
  - `qjsc -c`（未开启 `-m`）：输出 `BC_TAG_FUNCTION_BYTECODE` (`0x0e`)，反序列化后为普通函数（Tag 非 `-3`），导致 Falcon 启动崩溃。
  - `qjsc -c -m`：输出 `BC_TAG_MODULE` (`0x0f`)，反序列化后生成 `JS_TAG_MODULE` (`-3`) 对象，顺利进入求值流水线。
  - **规范准则**: **无论 JS 源码是否显式写有 `import`/`export`，必须全部使用 `qjsc -c -m` 编译为 ES 模块字节码。**

### 3. 运行时内建 C 模块链接与 `-M` 选项
- **问题根源**: 当代码中存在 `import wifi from 'wifi'`、`import soundPlayer from 'soundPlayer'` 等 Falcon 原生扩展时，若在 PC 编译机直接执行 `qjsc`，编译器会尝试在宿主磁盘查找 `wifi.js` 并报错 `ReferenceError: could not load module filename 'wifi'`。
- **解决方案原理**: 传递 `-M <module_name>`（如 `-M wifi -M soundPlayer`），使 `qjsc` 跳过本地文件解析，向字节码依赖表中注入外部 C 模块声明。在词典笔端执行时，由 Falcon 运行时的 C++ 原生模块钩子完成绑定。

---

## 三、 应用包管理 (PMS) 与完整性校验逆向拆解

### 1. 核心校验函数 `verifyAmrContent` (`reverse_dump/libfalcon.so` Address `0x258934`)
该函数在解压临时目录后被调用，逐行反汇编逻辑如下：
```arm
// 1. 获取 manifest.json 的 "cert" 字典
0x25893c:  ldr   r1, [pc, #0x4bc]   ; "cert"
0x25896c:  bl    #0x1d34f4          ; Json::operator[]("cert")

// 2. 遍历 cert 表项
0x258a04:  movw  r3, #0x6973
0x258a08:  movt  r3, #0x657a        ; "size"
0x258a14:  ldr   r3, [pc, #0x3ec]   ; "md5"

// 3. 文件物理存在性校验
0x258a4c:  bl    #0x1df620          ; FileUtil::FileExists
0x258a54:  beq   #0x258d24          ; 失败分支: 打印 "[PMS]%s not exist\n"

// 4. 文件长度对比
0x258ac4:  bl    #0x1df62c          ; FileUtil::GetFileSize (基于 stat.st_size)
0x258acc:  cmp   r8, r0             ; 预期 size vs 实际 size
0x258ad0:  bne   #0x258d3c          ; 失败分支: 打印 "[PMS]%s size = %d, not equal describe size %d\n"

// 5. 文件内容 MD5 摘要对比
0x258b40:  bl    #0x1d7310          ; ReadFileAsString & 计算纯二进制流 MD5
0x258b68:  cmp   r2, r3             ; 预期 MD5 字符串 vs 实际 MD5 字符串
0x258c20:  bne   #0x258b78          ; 失败分支: 打印 "[PMS]%s md5 = %s, not equal describe md5 %s\n"
```

### 2. 校验机制三大核心规律
1. **纯二进制流 MD5**: 校验算法直接对文件字节流调用标准 MD5，不包含任何文件时间戳或文件系统属性。
2. **正向白名单遍历（非目录扫描）**: 校验循环是正向遍历 `manifest.json` 中 `"cert"` 字典包含的键。系统**未执行** `opendir`/`readdir`。因此，未在 `cert` 中列出的文件（例如额外附加的图片或辅助脚本）完全不会触发校验失败。
3. **空 `cert` 跳过机制**: 若 `"cert": {}`，循环执行 0 次直接返回 `true`，完全跳过文件尺寸与散列比对。

### 3. A/B 槽位更新与持久化状态机 (`executeInstallPackage` Address `0x25f2c8`)
- 安装包解压并校验通过后，PMS 会检测 `/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/` 下的当前槽位。
- 槽位设计为 `a` 与 `b` 互相备份轮转。系统在 `/userdata/miniapp/data/mini_app/pkg/packages.json` 中使用布尔字段 `"b"` 记录当前活跃槽位（`"b": false` 表示当前为 `a`，升级时写入 `b` 并切换为 `"b": true`）。
- 目录切换采用原子级 `rename`，应用私有数据目录 `/data` 保持独立隔离，保证升级不丢失持久化存储。

---

## 四、 `miniapp_cli` 完整指令集与底层 IPC 通信规范

### 1. 通信协议细节
- **物理接口**: UNIX Domain Socket `/var/run/miniapp-dbg.socket`（`AF_LOCAL`, `SOCK_STREAM`）。
- **应用层协议**: 标准 HTTP/1.1 RESTful 协议，Header 包含 `Host: 127.0.0.1`、`Content-Type: application/json` 与 `Connection: close`。

### 2. 17 条支持命令全量字典

| 命令行调用方式 | HTTP 方法与 Endpoint | JSON Payload 载荷 | 功能与实测说明 |
| :--- | :--- | :--- | :--- |
| `miniapp_cli install {amrPath}` | `POST /install` | `{"path":"{amrPath}"}` | 安装本地 `.amr` 包，自动触发 PMS 解包、校验、槽位切换与 packages.json 注册。 |
| `miniapp_cli uninstall {appid}` | `POST /uninstall` | `{"appID":"{appid}"}` | 卸载指定应用并清理物理文件与注册表。 |
| `miniapp_cli start {appId}` | `POST /start` | `{"appID":"{appId}"}` | 启动应用首屏。 |
| `miniapp_cli start {appId} --{page}` | `POST /start` | `{"appID":"{appId}","page":"{page}"}` | 启动应用并直接深度导航至指定页面。 |
| `miniapp_cli startService {appId} {service}` | `POST /startService` | `{"appID":"{appId}","service":"{service}"}` | 启动指定的后台无界面 JS 服务上下文。 |
| `miniapp_cli debugApp {appid}` | `POST /debugApp` | `{"appID":"{appid}"}` | 将该应用绑定为当前 DevTools 与内存调试目标。返回 `{"ret": 0}`。 |
| `miniapp_cli debugService {appid}` | `POST /debugService` | `{"appID":"{appid}"}` | 将指定的后台服务绑定为调试目标。 |
| `miniapp_cli memoryApp` | `GET /memoryApp` | *(无)* | 输出当前活跃进程的 DOM 树、YGNode 布局节点、组件尺寸与 C++ 内存占用。 |
| `miniapp_cli memoryUsage` | `GET /memoryUsage` | *(无)* | 打印 QuickJS 引擎详细内存占用（JSRuntime、JSContext、Atoms、Objects、Bytecode 等）。 |
| `miniapp_cli memoryUsageGC` | `GET /memoryUsageGC` | *(无)* | 强制触发 QuickJS 全量垃圾回收并打印回收后的内存指标。 |
| `miniapp_cli dumpMemory` | `GET /dumpMemory` | *(无)* | 将 QuickJS 堆镜像完整转储至 `/tmp/httpdump.snapshot`。 |
| `miniapp_cli trimImageCache` | `GET /trimImageCache` | *(无)* | 强制释放图片解码缓存与纹理显存。 |
| `miniapp_cli capture {path}` | `POST /capture` | `{"path":"{path}"}` | 截取 Falcon UI 视口画面输出为 PNG 图像。 |
| `miniapp_cli captureFB {path}` | `POST /captureFB` | `{"path":"{path}"}` | 直接从底层 `/dev/fb0` 原生物理帧缓冲区抓取原始像素数据。 |
| `miniapp_cli beginMonkey` | `GET /beginMonkey` | *(无)* | 启动自动化压力测试（Monkey Test）。 |
| `miniapp_cli stopMonkey` | `GET /stopMonkey` | *(无)* | 停止 Monkey 压力测试。 |
| `miniapp_cli injectKey {keyCode}` | `POST /injectKey` | `{"keycode":{keyCode}}` | 注入物理硬件按键事件（如电源、返回或音量键）。 |
| `miniapp_cli setRenderConfig {key} {value}` | `POST /setRenderConfig` | `{"key":"{key}","value":"{value}"}` | 动态修改渲染流水线参数配置。 |

---

## 五、 生产级自动化打包工具链 (`host_tools/build_amr.py`)

在工程根目录已落地生产级自动化打包工具 `host_tools/build_amr.py`（具备执行权限）：

### 1. 核心自动化能力
1. **自动提取外部依赖并注入 `-M`**: 自动利用正则提取 `.js` 文件中的 `import` / `export` 语句，识别内置原生模块（`wifi`、`soundPlayer`、`device` 等），自动在调用 `qjsc` 时附加 `-M <module>`。
2. **强制 ES Module 规范**: 统一使用 `qjsc -c -m`，确保字节码 Byte 0 为 `0x01` 且标签为 `0x0f` (`JS_TAG_MODULE`)。
3. **精准生成 `cert` 签名表**: 流式计算每个待打包文件的精确 `size` 与 `md5`（排除源码 `.js`），支持 `--no-cert` 参数供快速开发调试。
4. **一键构建与部署流 (`--deploy --start`)**: 自动完成 `打包 -> 上传至词典笔 /tmp -> 调用 miniapp_cli install -> 调用 miniapp_cli start`。

### 2. 命令行使用范例
```bash
# 1. 针对工程目录打包为 AMR（自动生成全量 cert）
/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/build_amr.py /path/to/my_app -o /path/to/output.amr

# 2. 外部引用了自定义 C 模块
/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/build_amr.py /path/to/my_app -M customNative

# 3. 快速调试模式（跳过 cert 校验，一键推送到设备安装并拉起）
/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/build_amr.py /path/to/my_app --no-cert --deploy --start
```

---

## 六、 自研应用开发避坑黄金定律

1. **字节码头部永远是 `0x01`**: 切勿在字节码开头手工填充或期望 `0x3f`，首字节严格为 `0x01`，其后为 ULEB128 Atom 计数。
2. **所有 JS 必须加 `-m` 编译**: Falcon 的 `falcon::evalJSModule` 仅接受 Tag 为 `-3` 的 ES 模块，普通函数字节码必定执行报错。
3. **原生模块声明 `-M`**: 遇到 `import ... from 'builtin'` 时，必须使用 `-M <builtin>` 告知 `qjsc` 生成外部链接引用。
4. **免校验调试策略**: 开发调试期间可将 `manifest.json` 中的 `"cert"` 设为 `{}`，PMS 会跳过文件完整性校验，大幅提升热迭代速度。
5. **绝对路径陷阱**: 词典笔采用 A/B 槽位轮转，应用安装路径会在 `/a/` 与 `/b/` 之间切换，代码中切忌硬编码安装目录，资源文件统一使用相对路径加载。

相关已落地的工程工具绝对路径：
- 打包工具：`/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/build_amr.py`
- 编译器：`/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/qjsc`
- Atom 分析工具：`/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/quickjs_atom_tool.py`
