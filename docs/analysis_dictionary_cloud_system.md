# 有道词典笔 S7 Pro 核心词典、云同步、应用商店与系统管控深度逆向报告

---

## 一、 架构总览与 8 款官方微应用元数据拓扑

网易有道词典笔 S7 Pro（硬件平台代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813H ARMv7-A 32-bit Hard-Float，Linux 5.10.4 内核，128MB 物理内存，1020 × 240 极窄横向画布）上的核心系统与工具类应用构建于**阿里 HaaS UI / Falcon 轻量级渲染框架**之上，JS 引擎采用 QuickJS 2020-07-05 编译的二进制字节码（`.js.bin`）。

针对 8 款核心词典、云服务、应用分发与系统管控微应用，其包拓扑、版本与物理路径如下表所示：

| 应用名称 | 英文标识 | 官方 AppID | 物理包路径 / 版本 | 核心架构特征 |
| :--- | :--- | :--- | :--- | :--- |
| **有道词典** | Youdao Dictionary | `8080252464522508` | `/userdata/miniapp/data/mini_app/pkg/8080252464522508/b/` (v4.22.0) | 多词典检索内核、牛津/柯林斯嵌套排版、右侧导航轨、本地离线发音 |
| **历史记录** | Search History | `8080292157485624` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8080292157485624/a/` (v4.22.0) | SQLite 离线队列、复合主键去重、多语种翻译快照、增量上传机制 |
| **有道云笔记** | Youdao Note | `8001656491465980` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001656491465980/a/` (v4.22.0) | 离线先行暂存（`draft.db`）、双向增量同步、Cookie 票据换取、录音附件 |
| **有道云盘** | Youdao Cloud Drive | `8001667273038889` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001667273038889/a/` (v4.22.0) | 社区专栏分享、分级阅读资源、AES 对称加密 LRC 解密、分段断点下载 |
| **应用商店** | App Store | `8001657592345846` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001657592345846/a/` (v4.22.0) | 官方软件源拉取、AMR 校验、`JQuick::Updater` 与 PMS 进程间通信 |
| **个人中心** | User Center | `8080282263329158` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8080282263329158/a/` (v4.22.0) | URS 扫码登录长轮询、全局状态广播、学段动态配置、统一用户信息持久化 |
| **家长管控** | Parental Controls | `8001671616562847` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001671616562847/a/` (v4.22.0) | 后台常驻 Service、`FalconStack::startApp` 拦截链、WebSocket 远程管控 |
| **Youdao OpenEar** | Bluetooth Peripheral | `8001736586947101` | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001736586947101/a/` (v4.22.0) | 蓝牙 BLE/A2DP 链路管理、电池电量遥测、EQ 音效控制、BlueZ 适配 |

```
┌────────────────────────────────────────────────────────────────────────┐
│                        前端视图层 (Vue 2.x SFC)                         │
│  词典释义排版  云笔记编辑器  云盘资源列表  应用商店界面  家长锁与个人中心  │
├────────────────────────────────────────────────────────────────────────┤
│                       QuickJS 2020-07-05 运行时                        │
│  $falcon / $service_proxy / JQSignal / EventBus / Falcon UI Components │
├────────────────────────────────────────────────────────────────────────┤
│                   C++ JSAPI 桥接代理层 (/usr/lib)                      │
│ libjsapi_lookup │ libjsapi_appstore │ libjsapi_parentcontrol │ libfalcon  │
├────────────────────────────────────────────────────────────────────────┤
│                     C++ 业务逻辑与后台守护进程                         │
│ YDictQueryManager │ YAppStoreControl │ YParentControlPrivate │ SoundPlayer  │
├────────────────────────────────────────────────────────────────────────┤
│                       持久化数据与硬件抽象层                           │
│ history.db │ parentcontrol.db │ clouddisk.db │ draft.db │ libydhal_devices  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 重点攻关课题一：有道词典核心释义排版与查词引擎架构

有道词典（AppID: `8080252464522508`）是有道词典笔最核心的基石微应用，包含复杂的离线词典索引解析、屏幕宽度自适应排版及手势控制系统。

### 1. C++ 查词内核架构与源码拓扑
词典模块通过内部私有动态库 `libbusiness_lookup_967644665.so` 与 `libjsapi_lookup_967644665.so` 实现查词管线：
- 源码工程路径（编译符号证据）：
  `/data1/hardware/Package_Backup_1/workspace/APP_Package/app/yd-smarthardware-app/yd-self-app/scantrans/`
  - `business/YDictQueryMananger.cpp`: 多词典联合检索调度器，管理本地词典与在线词典的并发查询。
  - `business/YDictSetManager.cpp`: 词典库优先级调度与用户自定义词典勾选开关。
  - `business/apollo/YApolloLookUp.cpp`: 针对 Apollo 平台（1020x240 宽屏）专属裁剪的词典数据序列化管道。
  - `business/dictquery/YStemmer.cpp`: 英语形态学词干还原器（Porter Stemmer），支持屈折变化词（如 running -> run, better -> good）的原型反查。
  - `business/YSeparatorSelectWords.cpp`: 句子与例句内的分词器与单词边界检测引擎，支持屏幕点击取词。
  - `business/YStrokeManager.cpp`: 汉字笔画顺序与矢量轨迹生成器。
  - `business/leftpage/YCurlSSE.cpp`: 基于 libcurl 实现的 SSE（Server-Sent Events）长连接流式 AI 释义传输。
  - `jsapi/jsapi_lookup_word_module.cpp`: QuickJS C++ JSAPI 绑定层。

### 2. 本地离线词库与多媒体资源包
设备将数以 GB 计的离线数据直接挂载在 `/userdisk/uresource/localdict/` 与 `/userdisk/uresource/localsound/`：
- 牛津高阶英汉双解词典第 9 版：`dictpen-oxfordAdvance-nineV2.dat` (30MB) + 增量补丁 `dictpen-oxfordAdvance-nineV2-patchV2.dat`
- 牛津高阶英汉双解词典第 10 版：`dictpen-oxfordAdvance-tenV2.dat` (27MB) + 增量补丁 `dictpen-oxfordAdvance-tenV2-patchV2.dat`
- 柯林斯 COBUILD 初阶/高阶词典：`dictpen-collins-primaryV2.dat` (1.7MB)
- 英汉汉英大词典：`dictpen-dict-ecV2.dat` (151MB)、`dictpen-dict-ceV2.dat` (62MB)
- 汉字笔顺动画与矢量轮廓：`dictpen-common-strokesV2.dat` (143MB)、`dictpen-svg-strokesV2.dat` (13MB)
- 离线原声音频库：
  - 美音真人口型库：`dictpen-us-voiceV2.dat` (482MB)
  - 英音真人口型库：`dictpen-uk-voiceV2.dat` (489MB)
  - 中文标准朗读库：`dictpen-zh-voiceV2.dat` (127MB)
  - 牛津专有词条音频库：`dictpen-oxfordAdvance-nine-word-voiceV2.dat` (392MB)
  - 柯林斯例句发音库：`dictpen-collins-primary-voiceV2.dat` (53MB)

### 3. JSAPI 导出接口与原生信号流转
`libjsapi_lookup_967644665.so` 向前端暴露模块 `lookup_word`（类名 `JSLookupWordProxy`）：
```javascript
// QuickJS 原生绑定导出接口
const lookupModule = require('lookup_word');

// 1. 核心查词方法
lookupModule.lookup(jsonParams);              // 发起多词典查词请求
lookupModule.otherAppIndexLookup(appName);     // 跨应用查词调起（如生词本、输入法）
lookupModule.getMoreDictWordResult(key, type); // 异步按需拉取指定词典扩展卡片
lookupModule.backDictWordResult(key);          // 查词栈返回上一词条
lookupModule.querySpellDict(key);             // 自然拼读与音节切分查询
lookupModule.queryPhoneticDict(key);          // 国际音标与重音查询
lookupModule.queryWbSingleExample(word);       // 单句例句快速点读检索

// 2. 原生 C++ 事件通知 (JQSignal)
lookupModule.on('onScanWordResultChanged', (resultJson) => {
  // 硬件扫描笔头触发或屏幕输入词条后的实时结果回调
});
lookupModule.on('onBreakListChanged', (breakList) => {
  // 整句拆词分段边界变更
});
```

### 4. 1020 × 240 极窄横屏排版架构
1020 × 240 的物理屏幕比例高达 4.25:1，高度极为受限。官方有道词典采用了“**左侧纵向长滚动区 + 右侧常驻词典导轨**”的复合视口结构：

```
┌────────────────────────────────────────────────────────────┬─────────────┐
│                       左侧主内容视口 (flex: 1)             │ 右侧导轨    │
│  [词头与音标栏: dictHeader] (含英/美发音按钮与 CEFR 徽章)  │ (w: 120px)  │
├────────────────────────────────────────────────────────────┤ ┌─────────┐ │
│  ▼ 牛津高阶词典卡片 (ApolloOxfordResg.vue)                 │ │ 牛津    │ │
│    ├─ 义项群 1 (ApolloOxfordSnGsDivDetail.vue)             │ ├─────────┤ │
│    │    ├─ 释义与语法标签 (ApolloOxfordMeanDivDetail.vue)   │ │ 柯林斯  │ │
│    │    └─ 双语例句 (可点击发音 + 单词点击取词)             │ ├─────────┤ │
│    ├─ 短语动词 (ApolloOxfordPvGsDiv.vue)                   │ │ 汉英    │ │
│    └─ 习语群 (ApolloOxfordIdmGsDivDetail.vue)              │ ├─────────┤ │
├────────────────────────────────────────────────────────────┤ │ 笔顺    │ │
│  ▼ 柯林斯词典卡片 (DtCollins.vue)                          │ ├─────────┤ │
│    ├─ 词频星级 (1~5星) 与 语法分类 (gramcat)               │ │ 现代汉语│ │
│    └─ 英文整句释义与例句                                   │ └─────────┘ │
└────────────────────────────────────────────────────────────┴─────────────┘
```

#### (1) 右侧词典导航导轨 (`DictRightNav.vue`)
- 实现文件：`/userdata/miniapp/data/mini_app/pkg/8080252464522508/b/DictRightNav-5c9a7979.js.bin`
- 核心逻辑：右侧列表渲染已命中当前词条的词典图标集合（牛津、柯林斯、教材、古代汉语等）。
- 点击交互：
  ```javascript
  guideClickToElement: function(dictItem) {
    var targetOffsetTop = this.getDictAnchorOffset(dictItem.type);
    // 驱动主滚动容器平滑跳跃至对应词典区块
    this.$refs.verticalScroller.jumptoVticalScroY(targetOffsetTop);
    this.currentActiveDict = dictItem.type;
  }
  ```

#### (2) 牛津词典（Oxford）多层嵌套渲染树
- 视图组件：`ApolloDtOxfordDetail.vue` 与 `ApolloOxfordSnGsDivDetail.vue`
- 树形拆解与标签映射：
  - `Oxford_hg`: Headword group（词头组）
  - CEFR 等级角标：`isOxfordA1`、`isOxfordA2`、`isOxfordB1`、`isOxfordB2`、`isOxfordC1`、`isOxford5000`
  - `ApolloOxfordSnGsDivDetail`: Sense group（义项群）
  - `ApolloOxfordMeanDivDetail`: 核心释义单元。通过 `OxfordBase.processGl` 提取 Gloss（释义引导词），通过 `OxfordBase.processLabelGText` 渲染语域与语法标签
  - `ApolloOxfordIdmGsDivDetail`: Idiom group（习语单元）
  - `ApolloOxfordPvGsDiv`: Phrasal verb group（动词短语）
  - `ApolloOxfordDrgsMeanDivDetail`: Derivative group（派生词）
  - `ApolloOxfordUnDiv`: Usage Note（用法说明小黑板 `OxfordUnboxDiv`）

#### (3) 柯林斯词典（Collins）与中文词典排版
- 柯林斯组件：`DtCollins.vue`。支持 `gramcat`（语法类别徽章）、`definition`（英文释义）、`transList`（中文释义）以及 `examples`（例句组）。
- 现代汉语与古汉语：`DtChCELarge.vue`。
  - 多音字切换栏：`chPinYinList`，横向排列各读音胶囊标签，点击后局部刷新下方释义与例证。
  - 汉字笔顺动画：`HanziRender-5c0a25c4.js.bin`。加载 `/userdisk/uresource/localdict/dictpen-svg-strokesV2.dat` 中的 SVG 笔画骨骼数据，通过轻量级 Canvas 逐步绘制汉字笔画顺序。

### 5. 音标显示与多档发音交互
- 音标显示：`dictHeader-e75c1554.js.bin`。
  英式（`ukphone`）与美式（`usphone`）音标并列排布，采用特制国际音标矢量字体 `OPPOSans` 与 `fontFamilyEnSymbol`。
- 点读发音：
  点击音标扬声器图标触发 `SoundButton-40502dae.js.bin`，调用 `soundPlayerManager-a18b95e5.js.bin`，向设备独立常驻后台进程 `/oem/YoudaoDictPen/output/SoundPlayer` 发起 IPC 播放请求。
- 变速连读（三击手势）：
  在 `dictHeader` 中绑定 `detail_continuous_three_click`，连续三次点击发音按钮，音源在 1.0x（原速）、0.8x（慢速研读）及 1.2x（快速跟读）之间循环切换。
- 例句整句点读与跟读打分：
  例句右侧常驻 `SoundPlayIcon-e0eec4d4.js.bin`，点击后直接串流播放本地例句语音包；长按触发 `recordManager-7eab9aae.js.bin` 录音并上传评测打分。

---

## 三、 重点攻关课题二：应用商店（App Store）下载、验证与安装全流程

应用商店（AppID: `8001657592345846`）负责词典笔全生命周期的官方微应用检索、静默安装、升级与卸载。

### 1. 架构模块与 C++ 原生服务
- 物理路径：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001657592345846/a/`
- 原生模块：
  `libs/libbusiness_appstore_1622780910.so`（C++ 业务引擎）
  `libs/libjsapi_appstoreIndependent_1622780910.so`（QuickJS JSAPI 桥接层）
- C++ 核心类（源码符号证据）：
  `/build/hardware/workspace/Y08_Package/app/yd-smarthardware-app/yd-self-app/appstore/business/`
  - `YAppStoreControl.cpp`: 负责 HTTP 网络请求封装与设备签名鉴权。
  - `YAppStoreModule.cpp`: 负责下载任务调度、安装回调监听与包管理器通信。

### 2. 云端应用列表拉取与协议格式
应用商店前端 `apolloIndex.js.bin` 启动时，调用 `JSAppStoreIndependentProxy::getRequestCloudAppList` 发起网络请求：
- 官方接口地址：
  `https://dictpen-appstore.youdao.com/front/control_page_s`
  （内网调试环境：`https://dictpen-appstore.inner.youdao.com/front/control_page_s`）
- 请求方式：HTTP POST（由 `YAppStoreControl::httpPost` 基于 `cpr::Payload` 执行）
- 请求核心字段：
  ```json
  {
    "deviceSku": "OVERHEAD_Y08_SKU_CHN_PLUS",
    "platform": "y08_platform",
    "otaVersion": "4.22.0",
    "hardwareVersion": "Y08_CV1813_V0",
    "userId": "urs-phoneyd.d7fb6a06e4e445f7a@163.com",
    "serialNumber": "7F91700011101536",
    "installedApps": [
      {"appid": "8080252464522508", "version": "4.22.0"},
      {"appid": "8001656491465980", "version": "2.22.0"}
    ]
  }
  ```
- 云端返回清单数据格式：
  ```json
  {
    "code": 0,
    "data": {
      "categories": [
        {
          "categoryId": 101,
          "categoryName": "效率工具",
          "appList": [
            {
              "appid": "8001667273038889",
              "appName": "有道云盘",
              "versionName": "2.22.0",
              "versionCode": 22200,
              "packageUrl": "https://hardware-app.youdao.com/amr/8001667273038889_v22200.amr",
              "packageMd5": "a8f7c9e1...",
              "packageSize": 12582912,
              "iconUrl": "https://...",
              "description": "专属于你的云端学习资产库"
            }
          ]
        }
      ]
    }
  }
  ```

### 3. AMR 包下载与安全校验
用户点击“安装”或“更新”后，执行以下链条：
1. `JSAppStoreIndependentProxy::addUpdatingApp(appid, state)` 通知界面置为下载状态。
2. `YDALAPI::YAppStoreModule::downloadApp(appid)` 调用 Falcon 底层升级器：
   `libfalcon.so` 中的 `JQuick::Updater::AppUpdateManager::getInstance()->pushTask(...)`。
3. 状态回调驱动：
   - 监听 `EVT_DOWNLOAD_DONE`、`EVT_DOWNLOAD_PAUSED`、`downloadPercent`。
4. 完整性与安全防篡改校验：
   - 校验下载文件 MD5 散列值与云端清单 `packageMd5` 是否完全吻合。
   - 校验 AMR 头部数字证书签名（Falcon 原生签名校验），若签名损坏则直接抛出 C++ 异常代码：
     `INS_ERROR_FAILED_INVALID_AMR`（非法 AMR 包格式）或 `INS_ERROR_FILE_NOT_EXIST`。

### 4. 安装执行机制与双通道 IPC 通信
在 S7 Pro 系统中，应用安装存在两种不同的实现路径：

```
                    ┌──────────────────────────────────────────────┐
                    │  通道 A: 进程内 C++ 动态链接 (原生应用商店)  │
                    │  YAppStoreModule::installApp                 │
                    │         │                                    │
                    │         ▼                                    │
                    │  AppUpdateManager::installUpdate             │
                    │         │                                    │
┌───────────────────┼─────────┼────────────────────────────────────┼───────────────────┐
│ miniapp (运行时)  │         ▼                                    │                   │
│                   │  pm::PackageManager::installPackage          │                   │
│                   │         ▲                                    │                   │
│                   │         │                                    │                   │
│                   │  HTTP POST /install {"path": "..."}          │                   │
│                   │         ▲                                    │                   │
│                   └─────────┼────────────────────────────────────┘                   │
│                             │                                                        │
│                    ┌────────┴───────────────────────────────────┐                    │
│                    │  通道 B: Unix Domain Socket IPC (CLI/外部) │                    │
│                    │  /var/run/miniapp-dbg.socket               │                    │
│                    │         ▲                                  │                    │
│                    │         │                                  │                    │
│                    │  miniapp_cli install <package.amr>         │                    │
│                    └────────────────────────────────────────────┘                    │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

#### 通道 A：应用商店内部直通安装（进程内调用）
`libbusiness_appstore_1622780910.so` 在应用下载完成后，直接调用：
```cpp
// 符号：_ZN7YDALAPI15YAppStoreModule10installAppERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEE
YAppStoreModule::installApp(const std::string& appid) {
    AppUpdateManager::getInstance()->installUpdate(appid, [](InstallResult result) {
        if (result == InstallResult::SUCCESS) {
            // 回调通知 JS 层
        }
    });
}
```
`AppUpdateManager` 最终调用 `pm::PackageManager::installPackage`。

#### 通道 B：外部调试工具链安装（Unix Domain Socket HTTP 协议）
逆向 `/Users/daniel/youdao-dictpen-s7pro-guide/reverse_dump/miniapp_cli` 发现其本质是一个轻量级 C 语言编写的 HTTP-over-UDS 客户端：
- 套接字路径：`AF_LOCAL` / `AF_UNIX` 直连 `/var/run/miniapp-dbg.socket`。
- 请求格式：
  ```http
  POST /install HTTP/1.1
  Host: 127.0.0.1
  Content-Type: application/json
  Content-Length: 48
  Connection: close

  {"path":"/tmp/my_app.amr"}
  ```
- 运行时响应：
  `miniapp` 主进程内嵌的高性能微型 HTTP 服务器接收该请求，将解压任务分发给后台线程池：
  1. 解压 `.amr` 压缩包至目标存储分区（预装应用落盘在 `/userdata/miniapp/data/mini_app/pkg/<appid>/`，第三方或扩展应用落盘在 `/userdisk/secondary/miniapp/data/mini_app/pkg/<appid>/`）。
  2. 解构内部目录：
     `libs/` 存放针对 ARMv7-A 编译的 `.so`。
     `assets/` 存放界面切图与本地音频。
     根目录放置 `app.js.bin` 与 `index.js.bin` 字节码。
  3. 更新系统应用清单文件：`/oem/secondary/etc/miniapp/resources/local_packages.json`。
  4. 触发全局广播信号 `installed`，桌面启动器（Launcher）捕获事件并动态增补应用图标。

---

## 四、 重点攻关课题三：家长管控（Parental Controls）的安全拦截架构

家长管控（AppID: `8001671616562847`）旨在限制学生过度沉迷或绕过词典笔的学习属性。其安全拦截模型呈现出独特的**双重纵深防御（Defense-in-Depth）**特征。

### 1. 双重安全拦截架构模型
通过逆向 `libfalcon.so`、`parentcontrol-service.js.bin` 与桌面 `indexPage-085a554f.js.bin`，证实系统在 **UI 准入层**与 **C++ 核心生命周期层**实行双保险拦截：

```
                           用户点击桌面图标 / CLI 命令启动
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │   门禁 1: 前端 UI / Launcher 预检     │
                   │   (indexPage-085a554f.js.bin)         │
                   └───────────────────┬───────────────────┘
                                       │
                       是否在 parentControlMap 中且受控？
                                ├── 是 ──> 弹出“该功能已被家长锁定”Toast / 跳转密码页
                                │
                                └── 否
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │   $falcon.navTo('falcon://<appid>')   │
                   └───────────────────┬───────────────────┘
                                       │
                                       ▼
                   ┌───────────────────────────────────────┐
                   │   门禁 2: 系统底层 C++ 启动拦截器      │
                   │   FalconStack::startApp (libfalcon.so)│
                   └───────────────────┬───────────────────┘
                                       │
                     遍历 StartAppInterceptor 链表检查权限
                                ├── 拦截 ──> 日志: "FalconStack::startApp intercepted"
                                │            终止启动，销毁目标栈帧
                                │
                                └── 放行
                                       │
                                       ▼
                              FalconApp::start()
                          加载 app.js.bin 并进入首屏
```

#### 门禁 1：前端 UI / Launcher 预检（即时交互反馈）
- 桌面启动器载入 `parentrcontrolManager-9e89c317.js`，通过 `$service_proxy` 与后台常驻常开的 `falcon://8001671616562847/parentcontrol-service` 建立通信，获取全局管控字典：
  `$falcon.env.custom.parentControlMap`
- 桌面在渲染各卡片时执行 `checkParentControl`：
  若受控应用（如网易云音乐、第三方网盘、部分游戏类应用）处于锁定状态，桌面上直接叠加锁头图标（`/listening-lock.png`, `/hi-echo-lock.png`）。
- 用户点击时，桌面拦截在 `navTo` 之前，触发 `showFunctionLockedToast()`，彻底阻止页面路由。

#### 门禁 2：Falcon 核心 C++ 栈拦截（底层防越狱/防深层链接）
在 `libfalcon.so` 中，存在导出的拦截器注册函数：
- `falcon::FalconStack::addStartAppInterceptor(...)`
- `falcon::FalconStack::removeStartAppInterceptor(...)`
在 `FalconStack::startAppInternal` 执行容器初始化前，强制触发拦截器：
```cpp
// 反编译还原自 libfalcon.so
bool FalconStack::startAppInternal(const std::string& appid, const std::string& page, ...) {
    for (auto& interceptor : m_startAppInterceptors) {
        if (interceptor(appid, page, params)) {
            // 确凿符号日志证据
            FALCON_LOG("FalconStack::startApp(%s, %s) intercepted", appid.c_str(), page.c_str());
            return false; // 强行中断创建
        }
    }
    // 正常启动容器
    FalconApp* app = new FalconApp(appid);
    app->start(...);
}
```
此机制保证了无论黑客通过 UDS 发送 `miniapp_cli start <appid>`，还是通过应用间深层链接 `falcon://` 尝试跳转，只要底层拦截器判定该应用被封禁，进程即被阻断。

### 2. 后台守护服务与 C++ 业务层
- 后台服务文件：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001671616562847/a/services/parentcontrol-service.js.bin`
  该文件继承自 `falcon.Service`，由系统在开机阶段通过 `runDictPen` 自动载入后台执行。
- 底层实现库：
  `libbusiness_parentcontrol_361723320.so`
  源码路径：`/build/hardware/workspace/Y08_Package/app/yd-smarthardware-app/yd-self-app/parentcontrol-service/business/`
  - `YParentControlPrivate.cpp`: 管理 WebSocket 长连接、HTTP 同步与 SQLite 操作。
  - `YParentControlModule.cpp`: 暴露业务控制 API。

### 3. 手机 App 远程管控实时下发协议
家长通过手机端“有道智慧学习”App 下达的管控指令通过 WebSocket 实时推送到词典笔端：
- WebSocket 服务器连接点：
  `wss://hardware-push-server.youdao.com/device_socket/`
  （测试环境：`wss://hardware-push-server-test.youdao.com/device_socket/`）
- 鉴权认证：基于 `wstoken` 与设备唯一硬件标识。
- 下发消息解析（`YParentControlPrivate::onTextMessageReceived`，基于 RapidJSON 解析）：
  ```json
  {
    "message_id": "msg_98234710293",
    "businessId": "websocket_module",
    "functionId": "appStoreInstall",
    "sceneId": "scene_store_lock",
    "sceneName": "应用商店安装限制",
    "operationEnabled": 0,
    "status": 1
  }
  ```
- 常见受控业务标识符（从二进制中提取）：
  - `appStoreInstall`: 禁止通过应用商店下载或安装任何新应用。
  - `neteaseMusic`: 禁用网易云音乐播放与听歌功能。
  - `wisdom`: 限制 AI 答疑与小 P 智能助手的直接给出答案。
  - `expertQnA`: 限制名师专家问答功能。
  - `REPEATER`: 复读机娱乐管控。

### 4. 本地管控数据库与同步队列
- 数据库物理路径：`/userdisk/database/parentcontrol.db`
- 表结构定义（SQLite DDL）：
  ```sql
  CREATE TABLE table_parent_control (
      user_id TEXT DEFAULT '',         -- URS 绑定的家长用户 ID
      sceneId TEXT DEFAULT '',         -- 管控场景 ID (如 'scene_store_lock')
      sceneName TEXT DEFAULT '',       -- 场景展示名称
      status INTEGER DEFAULT 0,        -- 0: 开启管控 / 1: 放行
      sceneData TEXT DEFAULT '',       -- 附加控制规则 (JSON 字符串)
      appid TEXT DEFAULT '',           -- 绑定的目标微应用 AppID
      CONSTRAINT user_id_sceneId PRIMARY KEY (user_id, sceneId)
  );
  ```
- 状态回执与离线补偿：
  1. 笔端收到控制消息并落盘 `parentcontrol.db` 后，立即通过 HTTP POST 发送 ACK 回执：
     `https://hardware-push-server.youdao.com/hardware/control/controlCallback`
  2. 设备断网重启后，连网瞬间触发 `pullSceneListRequest()`，通过：
     `https://hardware-push-server.youdao.com/hardware/control/pullSceneList`
     全量拉取最新的云端策略，覆盖本地缓存，杜绝学生利用飞行模式篡改本地配置。

---

## 四、 重点攻关课题四：云端服务同步（云笔记、云盘）协议

有道云笔记与有道云盘承担着用户个人知识资产与音视频学习材料的云端同步使命。

### 1. 统一身份鉴权体系（URS Token 体系）
所有云端同步的前提是统一身份凭证。负责全笔登录态的核心中枢是**个人中心（User Center, AppID: `8080282263329158`）**：
- 扫码登录协议：
  1. 个人中心请求：`https://hardware-app.youdao.com/hardware/mbind/getBindQRCode` 生成绑定二维码。
  2. 轮询登录状态：高频请求 `https://dict.youdao.com/login/acc/loginstat`，等待手机端授权。
- 凭证持久化：
  登录成功后，用户凭证与 profile 信息被写入物理持久化路径 `/userdata/DictPenData/`：
  - `/userdata/DictPenData/userId`: 存放 URS 账号（如 `urs-phoneyd.d7fb6a06e4e445f7a@163.com`）。
  - `/userdata/DictPenData/userName`: 存放昵称。
  - `/userdata/DictPenData/userTag`: 存放学生年级画像（如 `learner_senior_one`）。
  - `/userdata/DictPenData/userAvatarPath`: 本地缓存的用户头像 JPG。
- 跨应用共享机制：
  个人中心注册服务 `falcon://8080282263329158/userCenter`，其他微应用通过 `$service_proxy.connect(...)` 订阅 `onIsLoginChanged`、`onUserIdChanged` 等事件，实现免密单点登录（SSO）。

---

### 2. 有道云笔记（Youdao Note）增量同步协议
- 模块路径：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001656491465980/a/`
- 原生驱动库：`libbusiness_ynote_1580514214.so`（源码路径：`.../ynote/business/common/networker/YNNetworkManager.cpp`）
- 本地暂存数据库：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001656491465980/data/draft/draft.db`

#### (1) 本地离线草稿表结构（DDL）
```sql
-- 笔记元数据与同步状态表
CREATE TABLE note (
    fileId CHAR(100) PRIMARY KEY,      -- 云端唯一文件标识 (UUID)
    createTime INT,                    -- 创建时间戳 (ms)
    modifyTime INT,                    -- 修改时间戳 (ms)
    domain INT,                        -- 租户域 (默认 0)
    title TEXT,                        -- 笔记标题
    entryType INT,                     -- 笔记类型 (0: 纯文本, 1: 扫描摘抄, 2: 录音笔录)
    transactionId TEXT,                -- 云端最后事务版本号
    transactionTime INT,               -- 云端最后事务时间
    localModified INT,                 -- 本地修改标记 (0: 已同步, 1: 待同步)
    contentChanged INT,                -- 内容变更标记 (0: 未变, 1: 需推流)
    resources TEXT                     -- 关联附件 ID 数组 (JSON)
);

-- 笔记正文物理表
CREATE TABLE content (
    fileId CHAR(100) PRIMARY KEY,      -- 对应 note 表的 fileId
    content TEXT                       -- 笔记 HTML / 富文本正文
);
```

#### (2) 票据换取与三步增量同步流程
1. 票据换取（`exchangeCookie`）：
   由于云笔记服务属于 `note.youdao.com` 体系，客户端调用 `note.server-06752a99.js.bin` 中的 `exchangeCookie`，使用 URS Token 兑换云笔记专有的 Session Cookie。
2. 增量拉取（Delta Download）：
   向网关发起 GET 请求：
   `https://note.youdao.com/yws/api/personal/sync?method=download&fileId=<id>`
   携带本地记录的 `transactionId`。服务器返回增量差异包，本地直接合并并更新 `transactionTime`。
3. 增量推送（Delta Push）：
   若检测到本地 `localModified == 1` 或 `contentChanged == 1`：
   向服务器发起 POST 请求：
   `https://note.youdao.com/yws/api/personal/sync?method=push`
   请求体携带本地被修改笔记的序列化数据。云端写入成功后返回最新的 `newTransactionId`，本地将 `localModified` 重置为 0。
4. 多媒体与音频附件上传：
   扫描或录音生成的 `.pcm` / `.mp3` 存储在 `data/draft/resourceFile/`，通过独立接口分块上传：
   `POST /yws/api/personal/sync/upload`

---

### 3. 有道云盘（Youdao Cloud Drive）资源同步与加密 LRC 保护
- 模块路径：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001667273038889/a/`
- 原生驱动库：`libbusiness_clouddisk_1558737903.so`
- 本地数据库：`/userdisk/secondary/miniapp/data/mini_app/pkg/8001667273038889/data/database/clouddisk.db` (容量约 815KB)

#### (1) 云盘数据库多租户结构（DDL）
```sql
-- 在线专栏与文章映射表
CREATE TABLE table_cloud_disk_online_article (
    user_id TEXT DEFAULT '',           -- 用户唯一隔离 ID
    id_primary_key TEXT DEFAULT '',    -- 复合主键标识
    column_key TEXT DEFAULT '',        -- 专栏 ID (如 'C_52F941FE94A1475F87B24BD16CE50B69')
    article_key TEXT DEFAULT '',       -- 文章唯一 ID
    title TEXT DEFAULT '',             -- 标题 (如 '林则徐禁烟')
    audio_url TEXT DEFAULT '',         -- 音频 CDN 下载地址
    audio_file TEXT DEFAULT '',        -- 本地落盘音频文件路径
    audio_lrc_url TEXT DEFAULT '',     -- 歌词/文稿字幕 URL
    audio_lrc_file TEXT DEFAULT '',    -- 本地解密后歌词路径
    encrypt_lrc_content TEXT DEFAULT '',-- 对称加密的 LRC 密文
    download_status INTEGER DEFAULT 0, -- 下载状态
    CONSTRAINT user_id_item PRIMARY KEY (user_id, column_key, article_key)
);

-- 云端断点续传任务队列
CREATE TABLE table_cloud_disk_download_task (
    user_id TEXT DEFAULT '',
    column_key TEXT DEFAULT '',
    article_key TEXT DEFAULT '',
    download_flag INTEGER DEFAULT 0,
    download_status INTEGER DEFAULT 0,
    CONSTRAINT task_pk PRIMARY KEY (user_id, column_key, article_key)
);
```

#### (2) 云盘核心 API 与提取码转存流程
- 云盘主机端点：`https://hardware-cloud-disk.youdao.com`
- 请求时附带官方专属签名头（Base64 标识）：
  `aGFyZHdhcmUtY2xvdWQtZGlzay1hcG9sbG8=`（解码即 `hardware-cloud-disk-apollo`）
- 业务接口矩阵：
  - `/apollo/article/list`: 获取用户当前订阅的所有专栏与音频文件。
  - `/cloud/column/struct`: 递归获取专栏目录树结构。
  - `/cloud/share/column/code/check`: 验证提取码或口令分享。
  - `/cloud/share/column/batchDump`: 批量将社区资源转存至个人网盘空间。
  - `/cloud/share/column/batchDumpResult`: 异步轮询转存进度。

#### (3) 核心字幕资产安全保护：AES 对称解密机制
官方为了防止教材与名师讲座的 LRC 字幕文稿被直接提取，采取了加密存储策略：
1. 客户端从接口 `/apollo/lrc/articleKey` 获取字幕密文，保存在 `encrypt_lrc_content` 字段。
2. 播放音频时，C++ 引擎通过调用静态方法解密：
   ```cpp
   // 确凿符号证据：libbusiness_clouddisk_1558737903.so
   _ZN14YAESEncryption7DecryptENS_3AesENS_4ModeERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEES9_S9_NS_7PaddingE
   // 即：YAESEncryption::Decrypt(Aes, Mode, key, iv, cipherText, Padding)
   ```
3. 解密后的标准 LRC 歌词实时输出到本地应用沙盒：
   `/userdisk/secondary/miniapp/data/mini_app/pkg/8001667273038889/data/resource/youdaoclouddisk/<userId>/article/<columnId>/<articleId>_<title>.lrc`
   播放器据此实现词曲同步滚动。

---

## 五、 辅助核心微应用深度剖析

### 1. 历史记录 (Search History, AppID: `8080292157485624`)
- 本地数据库路径：`/userdisk/database/history.db`
- 原生模块：`libbusiness_history_520728159.so`（源码路径：`.../history/business/YHistoryDatabase.cpp`）
- 核心表结构（DDL）：
  ```sql
  CREATE TABLE table_history (
      word TEXT,                       -- 查词原词
      translate TEXT,                  -- 核心释义快照
      dict_type SMALLINT,              -- 命中词典类型 (牛津/柯林斯/汉英)
      src_lang TEXT,                   -- 源语言 (如 'en')
      dst_lang TEXT,                   -- 目标语言 (如 'zh')
      wordgroup_type TINYINT,          -- 词条形态 (单词/短语/整句)
      timestamp BIGINT,                -- 查词时间戳
      uploaded TINYINT DEFAULT 0,      -- 离线增量标记 (0: 待同步, 1: 已上传)
      PRIMARY KEY (word, src_lang, dst_lang)
  );
  ```
- 架构策略：
  - **去重与置顶策略**：执行 `REPLACE INTO table_history VALUES(...)`。若用户二次扫描同一词汇，直接更新释义并刷新最新时间戳，避免历史记录臃肿。
  - **分页与虚拟滚动**：通过 `SELECT * FROM table_history WHERE timestamp < :timestamp ORDER BY timestamp DESC LIMIT :pagesize` 进行游标式分页，降低 128MB 物理内存的 DOM 占用。
  - **静默后台云同步**：后台服务轮询 `SELECT count(*) FROM table_history WHERE uploaded = 0`，若有离线未同步词条，批量上传至有道生词本云端，成功后执行 `UPDATE table_history SET uploaded=1 WHERE timestamp <= :startTimestamp`。

---

### 2. 个人中心 (User Center, AppID: `8080282263329158`)
- 核心定位：全笔的身份管理枢纽与学情画像提供方。
- 原生模块：`libbusiness_user_center_1078774407.so`（源码路径：`.../user-center/business/YUserCenterManager.cpp`）
- 学段与年级映射引擎：
  个人中心维护详细的年级学段枚举表：
  - 小学：`learner_pupil_one` 至 `learner_pupil_six`（一年级至六年级）
  - 初中：`learner_junior_one` 至 `learner_junior_three`（初一至初三）
  - 高中：`learner_senior_one` 至 `learner_senior_three`（高一至高三）
- 跨应用动态驱动能力：
  用户在个人中心修改年级后，触发 `onUserGradeKeyChanged` 广播。词典应用根据该广播自动重排词典优先级（如小学生优先展示少儿彩图词典，高中生优先展示高考高频与牛津高阶词典）。

---

### 3. Youdao OpenEar (蓝牙外设连接, AppID: `8001736586947101`)
- 核心定位：管理网易有道官方开放式气传导学习耳机（OpenEar）的外设连接与专属控制。
- 原生模块：`libbusiness_youdao_openear_975393783.so` 与 `libjsapi_youdao_openear_975393783.so`
- 系统底层适配：
  硬件抽象层通过动态加载 `/usr/lib/libydhal_devices.so` 与 Linux BlueZ 守护进程（`/usr/libexec/bluetooth/bluetoothd` 及 `bluealsa`）通信。
- 专属控制特性：
  - 电池电量多级遥测（`requestEarphoneInfo`）：通过自定义 BLE GATT 特征值实时获取左右耳与充电盒独立剩余电量。
  - 佩戴检测响应：检测到耳机摘下时，立即向媒体中心广播挂起播放，实现摘下即停、戴上续播。
  - 听力保护声压控制：根据学生年龄设定最大分贝门限，防止长时间大音量损害听力。

---

## 六、 架构逆向总结与开发者设计建议

通过对上述 8 款核心微应用的彻底逆向，有道词典笔 S7 Pro 官方团队在极低硬件规格（CV1813H 单核 A7、128MB RAM、1020x240 超长异形屏）下的工程设计智慧值得高度借鉴：

1. **界面排版极致优化**：针对 1020x240 极扁平画幅，果断舍弃传统手机纵向流水瀑布流，采用“**左滚动主视口 + 右侧锚点吸顶导航条**”的横向分栏布局，辅以 CEFR 徽章内嵌与折叠卡片，确保信息密度适中而不产生压迫感。
2. **离线先行（Offline-First）数据闭环**：无论是历史记录、生词本、家长管控还是云笔记，所有业务无一例外采用本地 SQLite 3 数据落盘先行，网络就绪后由后台线程通过增量标记（`uploaded=0`, `localModified=1`）静默同步，彻底解决弱网和离线环境下的功能可用性问题。
3. **分层立体安全防御**：家长管控在 UI 层（桌面直接锁图标）与底层运行时（`FalconStack::addStartAppInterceptor` 阻断容器实例化）协同防御，构建了严密的操作权限护城河。
4. **原生 C++ 与 JS 的职责边界**：网络协议解包、大数据量 JSON 解析（RapidJSON）、SQLite 读写、AES 加解密与媒体解码全部下沉至 C++ 原生库，QuickJS 仅负责处理组件声明与数据绑定，最大限度避免垃圾回收（GC）引发的界面掉帧卡顿。
