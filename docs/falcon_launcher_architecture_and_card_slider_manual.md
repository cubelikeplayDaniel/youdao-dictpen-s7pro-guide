# 有道词典笔 S7 Pro 系统桌面启动器 (Launcher)、PagesSlider 多屏滑动与卡片管理深度逆向分析
## (Falcon System Launcher, PagesSlider Multi-Page Architecture, and Card Management Engineering Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB RAM, Linux 5.10.4)  
> **核心组件**: 系统桌面 (`8080222437664451`), `libfalcon.so` (`greenui::SliderView`), `BaseCardsList.vue`, `PagesSlider.vue`

---

## 目录索引

1. [桌面双架构分流与多屏拓扑模型](#1-桌面双架构分流与多屏拓扑模型)
   - 1.1 [主题代号动态分发 (`theme-y08`)](#11-主题代号动态分发-theme-y08)
   - 1.2 [Page 0 系统核心屏与 Page 1 微应用卡片屏职责划分](#12-page-0-系统核心屏与-page-1-微应用卡片屏职责划分)
   - 1.3 [`<slider>` (PagesSlider) vs `<scroller>` 核心组件边界](#13-slider-pagesslider-vs-scroller-核心组件边界)
   - 1.4 [C++ 动力学与手势拦截底层阈值 (`libfalcon.so`)](#14-c-动力学与手势拦截底层阈值-libfalconso)
2. [微应用动态发现与卡片生命周期管理](#2-微应用动态发现与卡片生命周期管理)
   - 2.1 [包管理器 (`pm`) 动态注册表拓扑清单](#21-包管理器-pm-动态注册表拓扑清单)
   - 2.2 [`checkAddDesktopIcon` 核心过滤算法反编译剖析](#22-checkadddesktopicon-核心过滤算法反编译剖析)
   - 2.3 [新安装应用插槽算法 (Slot Assignment: 设置项前插规则)](#23-新安装应用插槽算法-slot-assignment-设置项前插规则)
   - 2.4 [桌面图标与标题多主题解析规范 (S7 Pro 138px × 138px 标杆)](#24-桌面图标与标题多主题解析规范-s7-pro-138px--138px-标杆)
3. [卡片交互、应用拉起与生命周期返回状态机](#3-卡片交互应用拉起与生命周期返回状态机)
   - 3.1 [`onClickItem` 与 `$falcon.navTo` 跨应用调度协议](#31-onclickitem-与-falconnavto-跨应用调度协议)
   - 3.2 [子应用销毁 (`$page.finish`) 与桌面唤醒 (`pageShowing`) 状态机](#32-子应用销毁-pagefinish-与桌面唤醒-pageshowing-状态机)
4. [第三方微应用生产级上屏适配工程规范](#4-第三方微应用生产级上屏适配工程规范)
   - 4.1 [标准双槽位 A/B 目录架构](#41-标准双槽位-ab-目录架构)
   - 4.2 [生产级 `manifest.json` 黄金模板](#42-生产级-manifestjson-黄金模板)
   - 4.3 [系统注册表写入标准 (`packages.json`)](#43-系统注册表写入标准-packagesjson)
   - 4.4 [桌面即时热重载通知技术实现](#44-桌面即时热重载通知技术实现)

---

## 1. 桌面双架构分流与多屏拓扑模型

### 1.1 主题代号动态分发 (`theme-y08`)

有道词典笔桌面系统（AppID: `8080222437664451`，路径 `/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/`）在根页面初始化时，通过底层 HAL 导出的 `globalManager.themeName()` 查询当前硬件平台的主题代号：

```javascript
// 反编译还原自 8080222437664451/a/index.js.bin
var theme = globalManager.themeName();
console.warn("dictpenHome===loadRootPage themeName=", theme);
if (theme === 'theme-y03' || theme === 'theme-y05' || theme === 'theme-y07') {
    // 竖屏产品线 (Y03/Y05/Y07 等)
    this.rootPage = (await import('./vScreenIndex-2df5199e.js')).default;
} else {
    // 横屏/宽屏产品线 (S7 Pro 对应的 theme-y08, theme-coco, theme-olive 等)
    this.rootPage = (await import('./index-05aa98d6.js')).default;
}
```

在 S7 Pro (`Y08_CV1813_V0`) 上，`themeName()` 严格返回 `'theme-y08'`，系统加载标准横屏页面流水线 `index-05aa98d6.js.bin`（编译自 `src/pages/index/index.vue`）与通用组件库 `indexPage-085a554f.js.bin`。

---

### 1.2 Page 0 系统核心屏与 Page 1 微应用卡片屏职责划分

在横屏架构根容器 `src/pages/entrance/Entrances.vue` 中，桌面由专有的多屏滑动器包装：

```javascript
// 反编译自 index-05aa98d6.js.bin 渲染函数
_c('PagesSlider', {
  on: { currentIndexChanged: this.currentIndexChanged }
}, [
  _c('HomePage', { // Page 0: 系统主屏
    attrs: { globalThemeName: this.entranceGlobalThemeName },
    on: {
      scanTranslClicked: this.scanTranslClicked,
      voiceAssistantClicked: this.voiceAssistantClicked,
      listeningClicked: this.listeningClicked,
      cameraClicked: this.cameraClicked,
      onImageLoadFinished: this.onInitFinished
    }
  }),
  this.isBeginLoad ? _c('CardsList', { // Page 1: 应用卡片屏
    ref: 'cards',
    attrs: { homeModeIconShow: this.entranceHomeModeIconShow },
    on: {
      sendLogFromHome: this.sendLogFromHome,
      haveNewEditCardListUpdate: this.haveNewEditCardListUpdate
    }
  }) : this._e()
])
```

- **Page 0 (`<HomePage>`)**：系统常驻核心交互层。
  - 核心功能：全屏数字时钟、扫查翻译快捷大卡片 (`scanTranslClicked`)、小P语音助手快速入口 (`voiceAssistantClicked`，分发至 `8001707294117702`)、英语听力入口 (`listeningClicked`) 与摄像头取景入口 (`cameraClicked`)。
  - 特性：不可编辑、不可卸载，布局硬编码。
- **Page 1 (`<CardsList>`)**：微应用矩阵与服务扩展屏。
  - 由 `BaseCardsList.vue` 驱动，动态渲染所有包管理器 (`pm`) 导出的已安装卡片。
  - 支持长按卡片拖拽重排，排序结果持久化至本地存储键名 `dictpenHomeSortedItems`。

---

### 1.3 `<slider>` (PagesSlider) vs `<scroller>` 核心组件边界

逆向字节码确认：**多屏之间的整屏切换由原生 `<slider>` 组件驱动，绝对禁止使用 `<scroller>` 进行多屏翻页！**

#### (1) `<slider>`（`PagesSlider.vue`）
`PagesSlider.vue` 封装了 C++ 底层的 `greenui::SliderView` (`JQuick::WXSlider`)：
```javascript
props: {
  currentIndex: { type: Number, default: 0 },
  isVerticalSwipe: { type: Boolean, default: false }, // S7 Pro 横屏模式下为 false
  infinite: { type: Boolean, default: false }         // 禁止循环首尾回滚，提供弹性阻尼边界
}

// 模板定义
_c('slider', {
  ref: 'slider',
  staticClass: ['slider-outer'],
  attrs: {
    autoPlay: false,
    showIndicators: false,
    infinite: this.infinite,
    vertical: this.isVerticalSwipe,
    index: this.selectedIndex
  },
  on: { change: this.change }
}, [this._t('default')])
```
- **尺寸与视口定位**：
  CSS 样式将 `.slider-outer` 绝对定位于屏幕：`position: absolute; left: 0px; top: 0px; width: 800px; height: 254px;`（或 `960px × 254px`）。
- **翻页事件链**：
  触摸滑动触发 C++ `SliderView::onPageSelected(index)` -> JS `@change` -> `PagesSlider.change(e)` 触发 `this.$emit('currentIndexChanged', e.index)` 更新桌面全局索引状态。

#### (2) `<scroller>`（`VerticalScroller.vue` / `HorizontalScroller.vue`）
- 映射至底层 C++ `greenui::ScrollView` (`JQuick::WXScrollView`)。
- **职责范围**：仅用于 Page 1 内部卡片过多时的横向/纵向平滑滚动，以及单卡片内的长文本局部滚动。不具备整屏磁吸吸附（Paging Snap）能力。

---

### 1.4 C++ 动力学与手势拦截底层阈值 (`libfalcon.so`)

在 `/usr/lib/libfalcon.so` 中，`greenui::SliderView` 实现了严密的触摸拦截与手势动力学判决：

1. **防抖触摸阈值 (`touchSlop`)**:
   - 符号：`greenui::SliderView::setTouchSlop(int)`（地址 `0x0043df30`）。
   - 汇编反编译确认构造函数将 `touchSlop` 严格初始化为 **`8px`**。触摸移动位移小于 8 像素时，视为点击或静止触摸，不触发页面拖拽。
2. **防误触方向判定门**:
   在 `SliderView::onTouchEvent` (`0x0043f760`) 的 `ACTION_MOVE` 中：
   - 横向滑动模式（`isVertical == false`）：
     计算位移 $\Delta X = |x - startX|$ 与 $\Delta Y = |y - startY|$。
     触发拖拽开始的严格条件为：
     $$\Delta X > \text{touchSlop}\ (8\text{px}) \quad \text{且} \quad \Delta X > \Delta Y$$
     满足条件后，置位内部标志 `isDragging = true`，并立即调用 `parent->requestDisallowInterceptTouchEvent(true)` 锁定事件流，阻止下拉通知栏或其他父组件抢夺手势。
3. **翻页与回弹临界判断 (`SliderView::dragFling` / `accelerationFling`)**:
   手指抬起（`ACTION_UP`）时，读取 `VelocityTracker` 收集的滑动速度 $V_x$（单位：像素/秒）及当前拖拽偏移量 $X_{\text{offset}}$：
   - **快速滑动手势 (Fling)**：若 $|V_x| \ge 400\text{px/s}$，无论位移多小，直接沿滑动方向翻至相邻页面（$V_x < 0$ 翻向下一页，$V_x > 0$ 翻向上一页）。
   - **慢速拖拽手势 (Drag Snap)**：若未达到甩动手势速度，则检查页面位移占比：
     若 $|X_{\text{offset}}| > \frac{\text{PageWidth}}{2}$（即位移超过半屏，S7 Pro 上约为 400px），则完成翻页；否则触发阻尼物理回弹至原页面。

---

## 2. 微应用动态发现与卡片生命周期管理

### 2.1 包管理器 (`pm`) 动态注册表拓扑清单

桌面本身不维护本地应用二进制，而是通过 Falcon 平台层提供的 `pm` 原生服务代理 (`getPmModule()`) 实现应用发现：

```
[磁盘应用注册表]
  ├── /userdata/miniapp/data/mini_app/pkg/packages.json (动态安装/OTA注册表)
  ├── /userdata/miniapp/data/mini_app/pkg/local_packages_thirdparty.json (第三方扩展清单)
  └── /oem/secondary/etc/miniapp/resources/local_packages.json (OEM系统预装包)
                           │
                           ▼
[Package Management Service (PMS) 守护进程]
                           │  暴露 QuickJS C++ JSAPI: 'pm'
                           ▼
[桌面启动器 BaseCardsList.vue]
  const packages = await this.getPmModule().getInstalledPackages();
```

---

### 2.2 `checkAddDesktopIcon` 核心过滤算法反编译剖析

桌面在呈现每个微应用卡片前，必须经过 `checkAddDesktopIcon` 校验：

```javascript
// 反编译自 indexPage-085a554f.js.bin
async checkAddDesktopIcon(packageInfo) {
  if (!packageInfo || !packageInfo.props || !packageInfo.props.addDesktop) {
    return true; // 若未配置 addDesktop，默认允许显示
  }
  
  // 1. 全局显式禁用校验
  if (packageInfo.props.addDesktop === false || packageInfo.props.addDesktop === "false") {
    return false; // 明确隐藏（如后台无界面服务 SERVICE、输入法 IM_PANEL 等）
  }

  // 2. 硬件主题平台映射表
  const themeMap = {
    'theme-exam':        'exam_platform',
    'theme-almond':      'almond_platform',
    'theme-x3s':         'x3s_platform',
    'theme-coco':        'coco_platform',
    'theme-hermes':      'hermes_platform',
    'theme-apollo':      'apollo_platform',
    'theme-plum':        'plum_platform',
    'theme-melon':       'melon_platform',
    'theme-olive':       'olive_platform',
    'theme-popcorn':     'popcorn_platform',
    'theme-y03':         'y03_platform',
    'theme-y07':         'y07_platform',
    'theme-y08':         'y08_platform', // 有道词典笔 S7 Pro 匹配键
    'theme-y06':         'y06_platform',
    'theme-y05':         'y05_platform'
  };

  const platformKey = themeMap[this.globalThemeName];
  if (platformKey && typeof packageInfo.props.addDesktop === 'object') {
    const isAdd = packageInfo.props.addDesktop[platformKey];
    if (isAdd !== undefined && !isAdd) {
      return false; // 该硬件平台显式标记为 false，不予显示
    }
  }

  return true;
}
```

#### S7 Pro 判定准则
S7 Pro 的 `globalThemeName` 为 `'theme-y08'`，对应匹配键为 **`y08_platform`**。
- 若 `manifest.json` 的 `props.addDesktop` 为布尔值 `false`，应用被隐藏。
- 若 `props.addDesktop` 为对象，且包含 `"y08_platform": false`，应用在 S7 Pro 桌面上被过滤。
- **第三方应用必须声明 `"addDesktop": { "y08_platform": true }` 或 `"addDesktop": true` 才能正常出现在桌面上。**

---

### 2.3 新安装应用插槽算法 (Slot Assignment: 设置项前插规则)

当用户通过 PMS 安装了新的 MiniApp，或者桌面首次刷新应用列表时，新卡片插入 `this.items` 数组的算法具有严谨的插槽规则：

```javascript
// 反编译还原自 BaseCardsList.vue 的 refreshApps 与 pm.on('package')
const targetIndex = this.items.findIndex(item => item.appid === packageInfo.appid);

if (targetIndex > -1) {
  // 应用已存在：就地更新名称、图标
  this.items[targetIndex].icon = this.getDesktopAppIcon(packageInfo);
  this.items[targetIndex].text = this.getDesktopAppTitle(packageInfo);
  this.items.splice(targetIndex, 1, this.items[targetIndex]);
} else {
  // 应用为新安装：构造新卡片对象
  const newItem = {
    text: this.getDesktopAppTitle(packageInfo),
    icon: this.getDesktopAppIcon(packageInfo),
    appid: packageInfo.appid,
    visible: true,
    isShowPointTip: false
  };

  // 核心插槽策略：寻找“系统设置 (Settings)”所在的索引
  const settingIndex = this.items.findIndex(item => item.appid === SettingsAppID);
  console.log("pm package+++ settingIndex=", settingIndex);

  if (settingIndex > -1) {
    // 强制插入到系统设置之前！
    this.items.splice(settingIndex, 0, newItem);
  } else {
    // 未找到设置项时插入到末尾
    this.items.splice(this.items.length, 0, newItem);
  }
}
```

- **插槽定律**：官方将“系统设置 (`Settings`, AppID: `8080272425914438`)”固定锚定为卡片列表的终末项。所有新增安装的应用均通过 `splice(settingIndex, 0, newItem)` **插入到“系统设置”正前方**。
- **持久化序列**：随后桌面触发 `this.$emit('haveNewEditCardListUpdate', this.sortedAppids)`，将更新后的 AppID 排列序列存入 LocalStorage 键名 `dictpenHomeSortedItems`。下次桌面启动时优先按照该序列对 `this.items` 重新排序。

---

### 2.4 桌面图标与标题多主题解析规范 (S7 Pro 138px × 138px 标杆)

#### (1) 图标 URL 解析与多主题回退 (`getDesktopAppIcon`)
```javascript
getDesktopAppIcon: function(packageInfo) {
  if (packageInfo.props != null && packageInfo.props.Icons != null) {
    let iconRelativePath = packageInfo.props.Icons[this.globalThemeName] || packageInfo.icon;
    return "file://".concat(packageInfo.installPath, iconRelativePath);
  }
  return "file://".concat(packageInfo.installPath, packageInfo.icon);
}
```
- **S7 Pro 路径寻址**：桌面优先读取 `packageInfo.props.Icons['theme-y08']`。若未指定，回退到根字段 `packageInfo.icon`（如 `"/app_icon.png"`）。
- **绝对协议前缀**：最终拼接为完整本地文件协议 URI：  
  `file:///userdata/miniapp/data/mini_app/pkg/<AppID>/a/app_icon.png`。

#### (2) 图标物理渲染尺寸 (`Card-66980c69.js.bin`)
在 `Card.vue` 的计算属性 `iconStyle` 中，针对各硬件屏幕有严苛的像素级设定：

| 硬件主题代号 | 适配机型 | 图标物理尺寸 (width × height) |
| :--- | :--- | :--- |
| **`theme-y08`** | **有道词典笔 S7 Pro (本设备)** | **`138px × 138px`** |
| `theme-y09p` | 词典笔 Y09 Pro | `138px × 138px` |
| `theme-y05` | 词典笔 Y05 (竖屏) | `122px × 122px` |
| `theme-exam` | 考试版专用机 | `68px × 68px` |
| `theme-popcorn` | 宽屏学习机 | `156px × 160px` |
| 默认缺省 | 未知新设备 | `120px × 120px` |

---

## 3. 卡片交互、应用拉起与生命周期返回状态机

### 3.1 `onClickItem` 与 `$falcon.navTo` 跨应用调度协议

卡片点击事件流在 `BaseCardsList.vue` 的 `onClickItem` 中集中处理：

```javascript
async onClickItem(item) {
  // 1. 系统冷启动与二次加载完备性锁
  if (globalManager.isSurpportSecondaryStartup && 
      globalManager.isSurpportSecondaryStartup() && 
      !globalManager.fileExists('/tmp/SecondaryStartupReady')) {
    console.warn("SecondaryStartup not ready, drop click");
    return;
  }

  // 2. 通用微应用标准启动协议
  const appid = item.appid;
  const targetUrl = 'falcon://' + appid + '/index';
  
  $falcon.navTo(targetUrl, {
    from: 'index',
    launchMode: 'multi-instance',
    inAnimation: 'none',
    outAnimation: 'none'
  });

  // 3. 埋点上报与桌面状态追踪
  this.sendLogFromHome(appid);
  globalManager.setNavToAppId(appid);
}
```

#### 底层 C++ 调度时序
1. JS 端调用 `$falcon.navTo("falcon://<appid>/index", options)`。
2. 进入 `/usr/lib/libfalcon.so` 中的 `falcon::JSNavigatorHandler::wrap_navToApp`。
3. 调用 `falcon::FalconStack::instance()->startApp(appid, page, query, anim)`。
4. 检查当前是否已有该 AppID 的活跃实例：
   - 若存在且为 `single-instance`：调度 `FalconStack::appResumed(pApp)`，唤醒上下文并触发 JS 层 `App.onShow()`。
   - 若为 `multi-instance`：读取目标应用目录的 `manifest.json`，创建全新 QuickJS 执行上下文，执行目标应用的 `app.js.bin`，并构建 GreenUI 渲染树覆盖于桌面之上。
5. 桌面触发应用级 `App.onHide()` 与页面级 `pageHidden()` 钩子，挂起定时器与后台动画。

---

### 3.2 子应用销毁 (`$page.finish`) 与桌面唤醒 (`pageShowing`) 状态机

```
[子应用页面栈顶]
        │
        │ 用户点击返回按钮 或 执行左滑返回手势
        ▼
   this.$page.finish()
        │
        ▼  (C++ falcon::JSPageInstance::finish -> falcon::FalconApp::popPage)
[子应用页面出栈]
        │
        ├── 栈内仍有上一级页面 ──► 恢复子应用上一页面 (Page.pageShowing)
        │
        └── 栈内已无其他页面 (栈空)
                 │
                 ▼  (C++ falcon::FalconStack::closeApp)
          [子应用容器销毁]
                 │
                 ├── 1. 触发子应用 App.onHide() -> App.onDestroy()
                 ├── 2. 释放子应用绑定的 QuickJS 上下文与 GreenUI 控件
                 │
                 ▼  (恢复底层栈底应用：桌面启动器 8080222437664451)
          [桌面启动器唤醒]
                 │
                 ├── 3. 触发桌面 App.onShow()
                 └── 4. 触发桌面 Entrances.vue 的 pageShowing() 专有生命周期钩子
```

#### 桌面端返回恢复动作（`pageShowing`）
当焦点交还给桌面启动器时，`Entrances.vue` 执行以下恢复逻辑：
1. **静默刷新卡片列表**：调用 `refreshApps()`。若用户在刚才的应用中进行了安装/卸载，桌面重新读取 `pm.getInstalledPackages()` 完成卡片热增删。
2. **硬件监听重启**：重启 Wi-Fi 信号质量轮询定时器（`startWifiQualTimer`，2 秒间隔）和电量广播监听。
3. **保持滑动位置**：桌面 `<slider>` 维持离开前的 `selectedIndex`（Page 0 或 Page 1），不会发生重置或闪烁跳跃。

---

## 4. 第三方微应用生产级上屏适配工程规范

### 4.1 标准双槽位 A/B 目录架构
```
/userdata/miniapp/data/mini_app/pkg/<YourAppID>/
├── a/                                    <-- 激活槽位 A
│   ├── app.js.bin                        <-- 应用入口字节码 (QuickJS 2020-07-05)
│   ├── indexPage-<hash>.js.bin           <-- 首页字节码
│   ├── manifest.json                     <-- 核心元数据配置
│   ├── app_icon.png                      <-- 默认图标 (138x138 像素 PNG)
│   └── assets/
│       └── images/
│           └── app_icon/
│               └── theme-y08/
│                   └── app_icon.png      <-- S7 Pro 专用图标 (138x138 像素 PNG)
└── b/                                    <-- 备份与升级槽位 B
```

---

### 4.2 生产级 `manifest.json` 黄金模板

```json
{
  "name": "第三方科学计算器",
  "package": "com.developer.calc",
  "version": "1.0.0",
  "otaVersion": "1.0.0",
  "minPlatformVersion": "1.0.0",
  "quickjsVersion": "20200705",
  "icon": "/app_icon.png",
  "main": "app.js.bin",
  "props": {
    "addDesktop": {
      "y08_platform": true
    },
    "Icons": {
      "theme-y08": "/assets/images/app_icon/theme-y08/app_icon.png"
    },
    "AppTitle": {
      "theme-y08": "科学计算器"
    },
    "page_rotation": "portrait",
    "theme": "theme-y08"
  },
  "router": {
    "entry": "pages/index",
    "pages": {
      "pages/index": {
        "component": "indexPage"
      }
    }
  }
}
```

#### 关键字段硬性指标：
- `quickjsVersion`：必须为 `"20200705"`。
- `props.addDesktop.y08_platform`：**必须明确为 `true`**。
- `props.Icons.theme-y08`：指向 `138px × 138px` 视网膜 PNG 图标。
- `props.AppTitle.theme-y08`：卡片标题（建议不超过 5 个汉字）。

---

### 4.3 系统注册表写入标准 (`packages.json`)

```json
{
  "8080999912345678": {
    "appid": "8080999912345678",
    "name": "第三方科学计算器",
    "version": "1.0.0",
    "otaVersion": "1.0.0",
    "icon": "/app_icon.png",
    "installPath": "/userdata/miniapp/data/mini_app/pkg/8080999912345678/a",
    "category": "TOOL",
    "SystemApp": false,
    "b": false,
    "props": {
      "addDesktop": {
        "y08_platform": true
      },
      "Icons": {
        "theme-y08": "/assets/images/app_icon/theme-y08/app_icon.png"
      },
      "AppTitle": {
        "theme-y08": "科学计算器"
      }
    }
  }
}
```

---

### 4.4 桌面即时热重载通知技术实现

#### 方式 A：通过 PMS 广播触发桌面 `refreshApps()`
```bash
miniapp_cli emit_event pm '{"type":"installed","info":{"appid":"8080999912345678","name":"第三方科学计算器","installPath":"/userdata/miniapp/data/mini_app/pkg/8080999912345678/a","props":{"addDesktop":{"y08_platform":true}}}}'
```

#### 方式 B：杀掉桌面进程自愈热重启
```bash
# 杀掉桌面进程，守护进程会在 500ms 内重新拉起，全量扫描 packages.json 并完成前置插槽
kill -9 $(pgrep -f "8080222437664451")
```
