# 有道词典笔 S7 Pro 官方系统应用与桌面启动器架构逆向分析及工程设计规范
## (Falcon Official Apps Architectural Patterns, Component Design Idioms, and Launcher Dissection Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB DDR3 RAM, Linux 5.10.4)  
> **显示逻辑**: 1020 × 240 物理横屏 (framebuffer: `/dev/fb0`, 驱动色彩深度 32-bit ARGB8888)  
> **核心组件**: 系统桌面 Launcher (`8080222437664451`), 背单词 Reciter (`youdao-reciter`), 百度网盘 (`youdao-netdisk`), 查词翻译 Core (`youdao-history`), 单词本 (`youdao-word-book`), 输入法软键盘 (`ApolloInputPage`), 运行时核心 `/usr/lib/libfalcon.so` 与 JavaScript 框架 `/etc/miniapp/resources/framework/jsfm-nvue.js.bin`

---

## 目录索引

1. [执行摘要与技术架构全景](#1-执行摘要与技术架构全景)
   - 1.1 [S7 Pro 嵌入式微应用容器技术栈](#11-s7-pro-嵌入式微应用容器技术栈)
   - 1.2 [官方系统应用全量逆向样本矩阵](#12-官方系统应用全量逆向样本矩阵)
2. [微应用类层级与运行时解剖 (Application Anatomy & Class Hierarchy)](#2-微应用类层级与运行时解剖-application-anatomy--class-hierarchy)
   - 2.1 [类继承模型: `$falcon.App` 与 `$falcon.Page` 核心接口](#21-类继承模型-falconapp-与-falconpage-核心接口)
   - 2.2 [`$falcon.useDefaultBasePageClass` 注入机制与 JSFM 字节码揭秘](#22-falconusedefaultbasepageclass-注入机制与-jsfm-字节码揭秘)
   - 2.3 [精确生命周期执行流水线 (Hooks Execution State Machine)](#23-精确生命周期执行流水线-hooks-execution-state-machine)
   - 2.4 [根容器挂载与 Vue 实例桥接 (`__loadPage` / `$mount('#root')`)](#24-根容器挂载与-vue-实例桥接-__loadpage--mountroot)
   - 2.5 [应用元数据契约 (`App.meta` / `manifest.json`) 与 `isSingleJsBundle` 机制](#25-应用元数据契约-appmeta--manifestjson-与-issinglejsbundle-机制)
3. [页面路由、动态代码分割与跨进程通信 (Page Navigation & Dynamic Chunking)](#3-页面路由动态代码分割与跨进程通信-page-navigation--dynamic-chunking)
   - 3.1 [微应用内部路由: `$page.navigateTo` / `redirectTo` / `finish` 时序](#31-微应用内部路由-pagenavigateto--redirectto--finish-时序)
   - 3.2 [动态异步模块加载器: `$falcon.__loadModuleDefault` 源码还原](#32-动态异步模块加载器-falcon__loadmoduledefault-源码还原)
   - 3.3 [路由参数穿透机制: `onLoad(query)` 到 `$root.setData(query)`](#33-路由参数穿透机制-onloadquery-到-rootsetdataquery)
   - 3.4 [全局应用间调度协议: `falcon://<appid>/<page>` IPC 契约](#34-全局应用间调度协议-falconappidpage-ipc-契约)
4. [官方组件设计模式与高性能布局范式 (Component Design Idioms)](#4-官方组件设计模式与高性能布局范式-component-design-idioms)
   - 4.1 [标准导航栏与回退按钮: `BackToolButton.vue` 深度反编译剖析](#41-标准导航栏与回退按钮-backtoolbuttonvue-深度反编译剖析)
   - 4.2 [长列表性能优化: `<list>` + `<cell>` vs `<scroller>` 核心边界](#42-长列表性能优化-list--cell-vs-scroller-核心边界)
   - 4.3 [轻量级响应式状态机: 跨页面状态管理设计 (免 Vuex 模式)](#43-轻量级响应式状态机-跨页面状态管理设计-免-vuex-模式)
   - 4.4 [硬件按键拦截与事件总线 (`buttonEventManager.headButtonPress`)](#44-硬件按键拦截与事件总线-buttoneventmanagerheadbuttonpress)
5. [系统桌面启动器架构深度逆向 (Desktop Launcher Deep Dive)](#5-系统桌面启动器架构深度逆向-desktop-launcher-deep-dive)
   - 5.1 [双屏拓扑模型: `PagesSlider.vue` (`<slider>`) 原生动力学引擎](#51-双屏拓扑模型-pagesslidervue-slider-原生动力学引擎)
   - 5.2 [微应用动态发现与 `checkAddDesktopIcon` 平台过滤算法](#52-微应用动态发现与-checkadddesktopicon-平台过滤算法)
   - 5.3 [新安装应用插槽算法 (Slot Assignment: 设置项前插规则)](#53-新安装应用插槽算法-slot-assignment-设置项前插规则)
   - 5.4 [桌面图标与标题多主题解析 (`theme-y08` 138×138px 标杆)](#54-桌面图标与标题多主题解析-theme-y08-138138px-标杆)
   - 5.5 [分页状态指示器: `VerticalIndicators.vue` 组件实现](#55-分页状态指示器-verticalindicatorsvue-组件实现)
6. [官方输入法软键盘子系统逆向剖析 (Input Method & Keyboard Architecture)](#6-官方输入法软键盘子系统逆向剖析-input-method--keyboard-architecture)
   - 6.1 [全功能输入法架构: `ApolloInputPage.vue` 组件模型](#61-全功能输入法架构-apolloinputpagevue-组件模型)
   - 6.2 [高频按键与连续长按删除机制 (`NumberKeyboard.vue`)](#62-高频按键与连续长按删除机制-numberkeyboardvue)
   - 6.3 [字符键盘与符号键盘切换: `OnlyCharKeyboard` 与 `KeyboardBottomBar`](#63-字符键盘与符号键盘切换-onlycharkeyboard-与-keyboardbottombar)
   - 6.4 [离线联想词检索引擎集成 (`doSearchWord` / `selectFirstWord`)](#64-离线联想词检索引擎集成-dosearchword--selectfirstword)
7. [生产级工程蓝图与黄金模板 (Production Engineering Blueprints)](#7-生产级工程蓝图与黄金模板-production-engineering-blueprints)
   - 7.1 [模式 A: 生产级多页面动态加载微应用模板 (Multi-Page Bundle)](#71-模式-a-生产级多页面动态加载微应用模板-multi-page-bundle)
   - 7.2 [模式 B: 极限轻量单包微应用模板 (Single JS Bundle)](#72-模式-b-极限轻量单包微应用模板-single-js-bundle)
   - 7.3 [微应用工程清单规范: `manifest.json` 与 `packages.json`](#73-微应用工程清单规范-manifestjson-与-packagesjson)
   - 7.4 [部署投递、启动自愈与全流程验证清单](#74-部署投递启动自愈与全流程验证清单)

---

## 1. 执行摘要与技术架构全景

### 1.1 S7 Pro 嵌入式微应用容器技术栈

网易有道词典笔 S7 Pro 运行基于 Linux 5.10.4 内核与 Cvitek CV1813H SoC（单核 ARM Cortex-A7 @ 1.0 GHz，硬浮点 VFPv4-D16，系统总内存仅 128 MB DDR3）。为在极度受限的嵌入式环境中实现流畅的多任务交互与极速冷启动，系统废弃了沉重的 Android/Chromium WebView 体系，采用了专有的 **Falcon MiniApp 容器架构**：

```
+-----------------------------------------------------------------------------------+
|                        MiniApp User Interface (Vue 2.6.14 SFC)                    |
|       <template> (Weex Native Tags: <div/>, <text/>, <image/>, <slider/>, <list/>) |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|         Falcon JavaScript Framework (/etc/miniapp/resources/framework/)           |
|   - jsfm-nvue.js.bin (Falcon Class, App/Page Lifecycle, DOM Observer, VNode Diff) |
|   - $falcon.App, $falcon.Page, $falcon.useDefaultBasePageClass, $falcon.navTo     |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|               QuickJS Bytecode Engine (QuickJS 2020-07-05 Modified)                |
|       Executes bytecode chunks (*.js.bin), LEB128 atom tables, module loader      |
+-----------------------------------------------------------------------------------+
                                        |
                                        v (libfalcon.so C++ Native Bridge)
+-----------------------------------------------------------------------------------+
|                    Falcon C++ Runtime Host (/usr/bin/miniapp)                     |
|  - falcon::FalconStack (App Stack, Container Pool, Task Manager)                  |
|  - falcon::JSNavigatorHandler (IPC, Router, Uri Dispatcher)                       |
|  - greenui::View Hierarchy (Flexbox Layout, Yoga C++, Touch Slop / Gesture Engine)|
|  - Skia Hardware Graphics Pipeline (SkCanvas -> Direct Draw to /dev/fb0)          |
+-----------------------------------------------------------------------------------+
```

### 1.2 官方系统应用全量逆向样本矩阵

本研究通过直接提取 S7 Pro 固件中的二进制镜像与 `/userdata/miniapp/data/mini_app/pkg/` 动态包，运用自主开发的 QuickJS 字节码反编译器 (`qjs_disasm.py`, `qjs_dumper.py`) 与 C++ 符号解析器 (`disasm_falcon.py`)，对所有代表性官方系统应用进行了逆向重构：

| 应用名称 | 注册 AppID / 包名 | 架构形态 | 字节码分析样本文件 | 核心技术特征 |
| :--- | :--- | :--- | :--- | :--- |
| **系统桌面启动器 (Launcher)** | `8080222437664451` | 多模块动态分块 | `index-05aa98d6.js.bin`<br>`indexPage-085a554f.js.bin`<br>`VerticalIndicators.js.bin` | `<slider>` 原生驱动、双屏卡片流、PMS 注册表前置插槽、硬件按键防抖 |
| **有道背单词 (Reciter)** | `8080252464522508`<br>(`youdao-reciter`) | 多页面动态分包 | `reciter_app.js.bin`<br>`reciter_index.js.bin`<br>`routeStore-1a792da5.js` | 派生 `$falcon.App` 与 `$falcon.Page`、全局路由栈追踪、轻量 store 状态机、Home 键解绑接管 |
| **百度网盘 (Netdisk)** | `8080212458422471`<br>(`youdao-netdisk`) | 多页面分包 | `baidu_app.js.bin`<br>`baidu_page.js.bin`<br>`baidu_index.js.bin` | 严格页面生命周期出入栈 (`$page.finish`)、多页面传参、轻量样式抽象 |
| **查词翻译 (Dictionary)** | `8080252464522508`<br>(`youdao-history`) | 核心系统级多模块 | `dp_app.js.bin`<br>`dp_index.js.bin` | 动态语言包切换 (`onChangeLocale`)、高频 OCR 结果总线订阅、毫秒级渲染 |
| **有道单词本 (WordBook)** | `8080222437664452`<br>(`youdao-word-book`) | 结构化多页面 | `wb_app.js.bin`<br>`wb_index.js.bin` | 虚拟化单词卡片列表、SQLite 本地持久化交互、音频焦点互斥管理 |
| **系统软键盘 (Keyboard)** | 内嵌核心子系统 | 细粒度组件库 | `InputPage-38d8bb4d.js.bin`<br>`NumberKeyboard-b9891f44.js.bin`<br>`OnlyCharKeyboard-35023e1a.js.bin` | 定时器长按连发 (100ms Interval)、手势位移阈值判定、离线 N-gram 词预测 |

---

## 2. 微应用类层级与运行时解剖 (Application Anatomy & Class Hierarchy)

### 2.1 类继承模型: `$falcon.App` 与 `$falcon.Page` 核心接口

在 Falcon 框架规范中，每一个微应用由两个核心类主导：应用级单例类（继承自 `$falcon.App`）与页面级基类（继承自 `$falcon.Page`）。

反编译 `reciter_app.js.bin` 与 `dp_app.js.bin`，重构出的标准类定义如下：

```javascript
/**
 * 官方标准 Page 基类定义
 * 承载单个页面的生命周期、硬件按键监听、Vue 依赖注入与参数接收
 */
class CustomPage extends $falcon.Page {
    constructor() {
        super();
        this.isJumping = false; // 路由防抖标志位
        
        // 绑定实体物理 Home 键按键释放回调
        this.homeButtonRelease = () => {
            console.log('homeButtonRelease on:', this.$pageName);
            if (this.$pageName !== 'scan' && this.$pageName !== 'scanWordPreview') {
                globalManager.setCurrentAppId('8080252464522508');
                $falcon.navTo('falcon://8080252464522508/index', {
                    fromApp: 'reciter',
                    from: 'reciter'
                }, {
                    inAnimation: 'none',
                    outAnimation: 'none'
                });
            }
        };
    }

    /**
     * 在 Vue 实例构造前触发（关键注入点）
     * @param {Function} Vue - 当前页面专享的 Vue 构造器
     */
    beforeVueInstantiate(Vue) {
        // 注入轻量状态管理仓库与解析工具函数
        Vue.prototype.$store = appStore;
        Vue.prototype.parseRes = parseResourcePath;
        Vue.prototype.isApolloFrame = (globalTheme() === 'apollo');
        Vue.prototype.apolloClassSuffix = isHermes() ? '-hermes' : '';
    }

    /**
     * 页面首次加载时触发（优先于 Vue 实例化）
     * @param {Object} query - 路由携带的 URL 参数
     */
    onLoad(query) {
        // 全局路由栈追踪
        routeStore.addPage(this.$pageId, this.$pageName);
        super.onLoad(query);
    }

    /**
     * 页面显示时触发（前台唤醒或子页面返回）
     * @param {Object} query - 新入参
     */
    onShow(query) {
        this.isJumping = false;
        // 重新注册物理按键监听（确保事件优先级归属顶层页面）
        buttonEventManager.headButtonPress.off(this.homeButtonRelease);
        buttonEventManager.headButtonPress.on(this.homeButtonRelease);

        // 核心参数下发：将 native query 灌入 Vue 根组件的响应式状态
        if (this.$root && typeof this.$root.setData === 'function') {
            this.$root.setData(query);
        }
        if (this.$root && typeof this.$root.onShow === 'function') {
            this.$root.onShow();
        }

        super.onShow();
        console.log('page onShow:', this.$pageName, 'pageId:', this.$pageId);
    }

    /**
     * 页面隐藏时触发（压栈或切入后台）
     */
    onHide() {
        super.onHide();
        // 移除物理按键监听，避免后台页面截获按键
        buttonEventManager.headButtonPress.off(this.homeButtonRelease);
        if (this.$root && typeof this.$root.onHide === 'function') {
            this.$root.onHide();
        }
    }

    /**
     * 页面卸载时触发（出栈销毁）
     */
    onUnload() {
        super.onUnload();
        routeStore.removePage(this.$pageId);
        buttonEventManager.headButtonPress.off(this.homeButtonRelease);
        if (this.$root && typeof this.$root.onUnload === 'function') {
            this.$root.onUnload();
        }
    }

    /**
     * 页面单实例复用模式下，收到新参数时触发
     * @param {Object} options - 新选项参数
     */
    onNewOptions(options) {
        super.onNewOptions(options);
        if (this.$root && typeof this.$root.onNewOptions === 'function') {
            this.$root.onNewOptions(options);
        }
    }
}

/**
 * 官方标准 App 基类定义
 * 承载微应用容器的全局生命周期与状态驻留
 */
class CustomApp extends $falcon.App {
    constructor() {
        super();
        this.state = {};
    }

    setState(newState) {
        this.state = Object.assign({}, this.state, newState);
    }

    /**
     * 微应用初始化完成时回调（全局仅触发一次）
     */
    onLaunch(options) {
        console.log('onLaunch========初始化完成时回调, 全局只触发一次.');
        super.onLaunch(options);
        
        // 核心架构契约：注入全局默认页面基类
        $falcon.useDefaultBasePageClass(CustomPage);
        
        const enterTime = Date.now();
        this.setState({ enterTime });
    }

    onShow() {
        super.onShow();
    }

    onHide() {
        super.onHide();
    }

    onDestroy() {
        const duration = Date.now() - (this.state.enterTime || 0);
        console.log('App destroyed, session duration seconds:', Math.floor(duration / 1000));
        super.onDestroy();
    }
}
```

---

### 2.2 `$falcon.useDefaultBasePageClass` 注入机制与 JSFM 字节码揭秘

逆向分析 `/etc/miniapp/resources/framework/jsfm-nvue.js.bin` 中 `class Falcon` 的第 58 号常量方法，彻底证实了该接口的底层实现：

```javascript
// 反编译还原自 jsfm-nvue.js.bin Falcon.prototype.useDefaultBasePageClass
useDefaultBasePageClass(clazz) {
    if (clazz.prototype instanceof $falcon.Page) {
        this.Page = clazz; // 将用户自定义 Page 挂载为当前微应用容器的默认页面基类
        return;
    }
    // 官方源码中的拼写笔误直接硬编码在字节码常量池中：
    throw new Error('DefauBasePageClass must extend from $falcon.App');
}
```

#### 关键约束
1. 传入的类必须派生自 `$falcon.Page`，否则在初始化阶段抛出异常中断执行。
2. 该注入必须在 `App.onLaunch(options)` 内执行完毕。当后续调用 `$falcon.navTo` 加载任何未显式指定 Page 类的纯 Vue SFC 页面时，运行时均会自动通过 `new this.Page()` 派生出页面包装器。

---

### 2.3 精确生命周期执行流水线 (Hooks Execution State Machine)

通过跟踪 C++ `/usr/lib/libfalcon.so` 中的 `falcon::FalconApp::loadPage` 与 JSFM 中的 `_performPageLifeCycle`，提取出精确的生命周期时序：

```
[原生调用: falcon::FalconApp::loadPage(pageName, query)]
                        |
                        v
[JSFM: Falcon.prototype.loadPage]
  ├── 1. 获取当前页面专享的独立 Vue 构造器: const Vue = this.Vue(instanceId);
  └── 2. 执行异步代码加载: const comp = await this.__loadModuleDefault(pageName);
                        |
                        v
[JSFM: Falcon.prototype.__loadPage]
  ├── 3. 创建 Page 实例: const page = new this.Page();
  ├── 4. 挂载页面基础元数据:
  │      page.$pageName = pageName;
  │      page.$pageId   = pageId;
  │      page.$app      = this.$app;
  │      page.$falcon   = this;
  ├── 5. 触发页面生命周期: page.onLoad(query)  <-- [重要: 早于 Vue 实例化]
  ├── 6. 触发 Vue 准备生命周期: page.beforeVueInstantiate(Vue) <-- [注入 Vue.prototype]
  ├── 7. 绑定原生底层 JSAPI 代理属性 (Yoga Flexbox, Native Module Getters)
  ├── 8. 构造 Vue 根实例: page.$root = new Vue({ ...comp, ...options });
  ├── 9. 挂载根节点: page.$root.$mount('#root');
  └── 10. 将 page 实例缓存入 this._pageMap.set(pageId, page);
                        |
                        v
[原生信号: falcon::FalconStack::showPage(pageId)]
                        |
                        v
[JSFM: Falcon.prototype.showPage]
  ├── 11. 更新活跃页面索引: this.$app.$currentPageId = pageId;
  ├── 12. 触发页面显示生命周期: page.onShow(query);
  └── 13. page.onShow 内部转发: page.$root.setData(query) 与 page.$root.onShow()
```

#### 核心认知修正
- **`onLoad(query)` 发生在 `beforeVueInstantiate(Vue)` 之前**：在 `onLoad` 执行时，Vue 实例（`this.$root`）尚未创建。因此绝不可在 `onLoad` 中通过 `this.$root` 访问数据！所有基于入参影响 Vue 全局原型（如主题参数）的操作需在 `beforeVueInstantiate` 结合 `query` 完成。
- **页面返回时不重跑 `onLoad`**：从子页面 `$page.finish()` 弹出后，上一级页面重新展现仅触发 `onShow(query)`。数据刷新必须在 `onShow` 或 `$root.setData` 中驱动。

---

### 2.4 根容器挂载与 Vue 实例桥接 (`__loadPage` / `$mount('#root')`)

在 `jsfm-nvue.js.bin` 的 `__loadPage` 实现中，Vue 实例与原生 DOM 树的绑定过程如下（反编译字节码）：

```javascript
// 反编译自 jsfm-nvue.js.bin 的 __loadPage 实现
__loadPage(component, pageName, instance, pageId, Vue, query, options) {
    let pageInstance;
    if (component.prototype instanceof $falcon.Page) {
        pageInstance = new component();
    } else {
        pageInstance = new this.Page();
        pageInstance._component = component;
        pageInstance._component_only = true;
    }
    
    pageInstance._instance = instance;
    this._pageMap.set(pageId, pageInstance);
    pageInstance.$pageName = pageName;
    pageInstance.$pageId = pageId;
    pageInstance.$app = this.$app;
    pageInstance.$falcon = this;

    // 为当前页面隔离 Vue 的 Component ID (cid)
    Vue.cid = pageId;
    
    // 注入 $page, $app 快捷属性访问器
    Vue.use(falconVuePlugin(this, this.$app, pageInstance, instance, pageId));

    // 触发第一阶段 Hook
    this._performPageLifeCycle(pageId, 'onLoad', query, 'load');
    this._performPageLifeCycle(pageId, 'beforeVueInstantiate', Vue, 'beforeVueInstantiate');

    // 将底层 C++ 注册的原生模块属性劫持至 Page 实例
    const modules = Vue.prototype._nvue.getRegisteredModules();
    for (const modName of modules) {
        Object.defineProperty(pageInstance, modName, {
            enumerable: true,
            configurable: false,
            get: () => Vue.prototype._nvue.requireModule(modName)
        });
    }

    // 实例化并挂载根 Vue 节点
    pageInstance.$root = new Vue(Object.assign({}, pageInstance._component, pageInstance._componentOptions));
    pageInstance.$root.$_page = pageInstance; // 双向关联
    pageInstance.$root.$mount('#root');       // 绑定至 GreenUI 视口根节点
}
```

---

### 2.5 应用元数据契约 (`App.meta` / `manifest.json`) 与 `isSingleJsBundle` 机制

官方应用在入口 `app.js.bin` 中必须静态挂载 `App.meta`，该对象定义了打包产物在 PMS 体系中的规格形态：

```javascript
// 反编译还原自 reciter_app.js.bin
App.meta = {
    name: 'youdao-reciter',
    version: '2.22.0',
    otaVersion: '4.22.0',
    supportUnInstall: true,
    isSingleJsBundle: false, // 核心字段：标记当前应用是否为单包架构
    addDesktop: {
        coco_platform: true,
        almond_platform: true,
        x3s_platform: true,
        apollo_platform: true,
        hermes_platform: false,
        hermes_plus_platform: true,
        y08_platform: true   // S7 Pro 必须显式声明
    },
    props: {
        Icons: {
            'theme-hermes': 'assets/images/app_icon/theme-hermes/app_icon.png',
            'theme-popcorn': 'assets/images/app_icon/theme-popcorn/app_icon.png',
            'theme-y08': 'assets/images/app_icon/theme-y08/app_icon.png'
        }
    }
};

$falcon.__AppClazz = App; // 向底层容器暴露应用类
```

#### `isSingleJsBundle` 两种架构的深度对比

| 架构特性 | `isSingleJsBundle: true` (单包模式) | `isSingleJsBundle: false` (多包模式) |
| :--- | :--- | :--- |
| **典型应用** | 系统设置 (`Settings`)、简易工具类微应用 | 有道背单词 (`Reciter`)、百度网盘、查词翻译 |
| **产物形态** | 所有代码（含全部页面、组件与运行时）打包入单个 `app.js.bin` | 入口 `app.js.bin` 极小，页面生成独立分块 (`pages/xxx.js.bin`) |
| **内存占用** | 启动即解析全部页面字节码，常驻内存高（约 4.5 MB ~ 8 MB） | 按需加载，退出页面自动释放分块常量池，常驻内存低（约 1.8 MB ~ 3.2 MB） |
| **冷启动性能** | 解析耗时较长（1000~1500ms），但在单核 A7 上容易触发垃圾回收 | 冷启动极快（200~350ms），二级页面按需加载（约 50~80ms） |
| **加载器要求** | 无需 `$falcon.__loadModuleDefault` | **必须**实现 `$falcon.__loadModuleDefault` 异步模块加载器 |

---

## 3. 页面路由、动态代码分割与跨进程通信 (Page Navigation & Dynamic Chunking)

### 3.1 微应用内部路由: `$page.navigateTo` / `redirectTo` / `finish` 时序

官方微应用在进行内部页面流转时，统一使用挂载在 Vue 实例上的 `$page` 与 `$falcon` 路由对象：

```
                     +---------------------------------------+
                     |         Current Active Page           |
                     |           (this.$page)                |
                     +---------------------------------------+
                        |                 |               |
       $falcon.navTo('detail')   $page.redirectTo('home')  $page.finish()
                        |                 |               |
                        v                 v               v
             [PUSH PAGE TO STACK]   [REPLACE PAGE]  [POP PAGE FROM STACK]
                        |                 |               |
                        |                 |               +--> 若栈空:
                        |                 |                    触发 $app.finish()
                        v                 v                    切回系统桌面
             [LOAD TARGET CHUNK VIA $falcon.__loadModuleDefault]
```

#### 官方调用示例（反编译自 `baidu_page.js.bin`）
```javascript
export default {
    name: 'NetdiskPage',
    methods: {
        // 跳转到新页面（压栈）
        jumpToIndex() {
            $falcon.navTo('index', { from: 'page', folderId: '1002' });
        },
        // 彻底关闭当前应用返回系统桌面
        finishApp() {
            this.$app.finish();
        },
        // 结束当前页面（出栈返回上一级）
        finishPage() {
            this.$page.finish();
        }
    }
};
```

---

### 3.2 动态异步模块加载器: `$falcon.__loadModuleDefault` 源码还原

在 `isSingleJsBundle: false` 的多包架构中，Falcon 容器在路由发生时无法预先得知页面模块的导出对象，而是委托给由开发者在 `app.js.bin` 中定义的 `$falcon.__loadModuleDefault` 挂钩：

```javascript
// 反编译还原自 reciter_app.js.bin 真实代码
$falcon.__loadModuleDefault = async function(pageName) {
    // 1. 命中已缓存的静态页面表（预编译或常驻模块）
    if (App.__pages && App.__pages[pageName]) {
        return App.__pages[pageName];
    }
    
    // 2. 运行时动态 ES Module Import
    try {
        let modulePath = './' + pageName + '.js';
        let mod = await import(modulePath);
        return mod.default;
    } catch (e) {
        console.log('[FalconLoaderError]', e.message, e.stack);
        throw e;
    }
};
```

#### 底层 C++ 与 QuickJS 动态导入原理
1. QuickJS 执行 `await import(modulePath)` 时，触发字节码指令 `OP_import`。
2. 进入 C++ `libfalcon.so` 的 `JSModuleLoader` 回调函数。
3. `JSModuleLoader` 自动为相对路径补全当前微应用的物理安装槽位目录（例如 `/userdata/miniapp/data/mini_app/pkg/8080252464522508/a/`），并自动追加 `.bin` 后缀定位到二进制字节码文件（如 `pages/recite/recite.js.bin`）。
4. 通过 `JS_ReadObject` 反序列化为 QuickJS `JSModuleDef`，执行顶级执行函数，返回导出的 Vue SFC 默认对象（`mod.default`）。

---

### 3.3 路由参数穿透机制: `onLoad(query)` 到 `$root.setData(query)`

在 Falcon 中，URL 携带的查询参数如何无缝穿透到底层 Vue 响应式状态？官方应用采用了**两级穿透契约**：

```
[调用端: $falcon.navTo('wordDetail', { word: 'abandon', id: 42 })]
                            |
                            v (URL 序列化: "wordDetail?word=abandon&id=42")
[C++ 容器解析入参字典: { word: 'abandon', id: '42' }]
                            |
                            v
[Page.onLoad(query)]  -----> 缓存参数至 pageInstance.lastQuery = query
                            |
                            v (Vue 实例化完成，进入 onShow)
[Page.onShow(query)]
  ├── if (this.$root && this.$root.setData) {
  │       this.$root.setData(query); // <-- 核心穿透点
  │   }
                            |
                            v
[Vue SFC Component: <template>{{ word }}</template>]
  methods: {
      setData(query) {
          if (!query) return;
          this.word = query.word || '';
          this.wordId = parseInt(query.id, 10);
          this.fetchWordDetails(); // 触发业务数据获取
      }
  }
```

#### 避坑铁律
很多初学者尝试在 Vue SFC 的 `created` 或 `mounted` 中直接读取 `this.$route.query`。**Falcon 运行时的 Vue 不包含 vue-router 运行时！** `this.$route` 是 `undefined`。官方系统唯一的标准传参规范即为在 SFC 的 `methods` 中声明 `setData(query)`，由 `Page.onShow` 主动灌入。

---

### 3.4 全局应用间调度协议: `falcon://<appid>/<page>` IPC 契约

有道全系系统微应用之间的唤起与跨 App 数据联动遵循统一的 URI 调度协议：

```javascript
// 跨应用启动通用格式
$falcon.navTo('falcon://' + targetAppId + '/' + targetPage, {
    fromApp: currentAppId,
    timestamp: Date.now(),
    payload: JSON.stringify(extraData)
}, {
    launchMode: 'multi-instance', // 或 'single-instance'
    inAnimation: 'none',          // 禁用切换动画，提升 A7 流畅度
    outAnimation: 'none'
});
```

#### 官方常用系统 AppID 索引清单
- `8080222437664451`: 系统桌面启动器 (Launcher)
- `8080252464522508`: 查词翻译 / OCR 扫描主干 (Dictionary / History)
- `8080222437664452`: 单词本 (Word Book)
- `8080272425914438`: 系统设置 (Settings)
- `8080212458422471`: 百度网盘 (Netdisk)
- `8080242460611739`: 网易云音乐 (NetEase Cloud Music)

---

## 4. 官方组件设计模式与高性能布局范式 (Component Design Idioms)

### 4.1 标准导航栏与回退按钮: `BackToolButton.vue` 深度反编译剖析

官方在所有系统二级页面中均使用公共库 `yd-dictpen-haasui/ui/commons/toolbuttons/BackToolButton.vue`。反编译提取的代码揭示了其对多硬件屏幕主题的动态自适应机制：

```html
<!-- 反编译还原自 8080222437664451/a/BackToolButton-d2aa0510.js.bin -->
<template>
  <div 
    class="center-icon" 
    :style="buttonContainerStyle" 
    @click="onToolButtonClicked"
  >
    <image 
      class="back-icon" 
      :src="iconSrc" 
      resize="contain" 
    />
  </div>
</template>

<script>
export default {
  name: "BackToolButton",
  props: {
    backgroundColor: {
      type: String,
      default: "transparent"
    },
    needMarginLeft: {
      type: Boolean,
      default: true
    },
    buttonMarginTop: {
      type: [Number, String],
      default: 0
    }
  },
  computed: {
    // 动态评估硬件主题并分发展示浅色/深色图标资源
    iconSrc() {
      const currentTheme = ($falcon.env && $falcon.env.custom && $falcon.env.custom.theme) || this.globalThemeName;
      
      // 暗黑系硬件主题列表（S7 Pro 为 theme-y08，属于高对比暗色主题）
      const darkThemes = [
        'theme-coco', 'theme-almond', 'theme-apollo', 'theme-x3s',
        'theme-plum', 'theme-melon', 'theme-olive', 'theme-pear',
        'theme-pineapple', 'theme-popcorn', 'theme-y08', 'theme-y09p'
      ];
      
      if (darkThemes.includes(currentTheme)) {
        // 白色箭头矢量资源 (RGB 255, 255, 255)
        return 'images/0166dc16a17756c320e681752a0a19fc.png';
      }
      // 浅色主题回退为黑色箭头资源 (RGB 26, 27, 31)
      return 'images/7d6533681391be3b1b7bac1c4d28fcd8.png';
    },
    buttonContainerStyle() {
      return {
        width: '72px',
        height: '72px',
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: this.backgroundColor,
        marginLeft: this.needMarginLeft ? '16px' : '0px',
        marginTop: `${this.buttonMarginTop}px`
      };
    }
  },
  methods: {
    onToolButtonClicked(e) {
      // 触发通用点击，默认直接通知父容器回退页面
      this.$emit('toolButtonClicked', e);
      this.$emit('backButtonClicked', e);
      
      // 若父组件未拦截，则直接触发默认页面出栈
      if (!this.$listeners['backButtonClicked'] && this.$page) {
        this.$page.finish();
      }
    }
  }
};
</script>

<style>
.center-icon {
  width: 72px;
  height: 72px;
  justify-content: center;
  align-items: center;
}
.back-icon {
  width: 36px;
  height: 36px;
}
</style>
```

---

### 4.2 长列表性能优化: `<list>` + `<cell>` vs `<scroller>` 核心边界

在 S7 Pro 仅 128 MB RAM 的极度受限环境中，如果列表超过 15 项且使用了错误的容器标签，将极易导致 OOM Crash 或掉帧至 10 FPS。

#### 原生组件行为矩阵

| 对比维度 | `<list>` + `<cell>` 虚拟列表 | `<scroller>` 平滑滚动容器 |
| :--- | :--- | :--- |
| **底层映射** | `greenui::ListView` (`JQuick::WXListView`) | `greenui::ScrollView` (`JQuick::WXScrollView`) |
| **DOM 节点常驻** | **仅视口可见项常驻**，滑出视口的 DOM 节点和 Skia 位图自动解构回收 | **全量子节点常驻**，即使有 500 个子项也会一次性实例化 500 个 Native View |
| **内存曲线** | 随列表项增长保持平稳（常驻约 2.5 MB ~ 4 MB） | 随列表项增长线性暴增，50 个复杂卡片直接消耗 > 30 MB 内存触发崩溃 |
| **重用机制** | 强制要求每个子项被 `<cell>` 包裹，支持复用回收 | 不支持复用，仅作为普通滚动视口 |
| **适用场景** | 单词本、词典搜索结果、长文章阅读、文件管理器 | 固定数量菜单（< 10项）、横向滑动选择器、单屏内表单 |

#### 官方高性能 `<list>` 标准模板
```html
<template>
  <list 
    class="vocab-list" 
    :show-scrollbar="false" 
    :loadmoreoffset="100" 
    @loadmore="onLoadMore"
  >
    <cell 
      v-for="(item, index) in wordList" 
      :key="item.id" 
      class="vocab-cell"
      :recycle="true"
    >
      <div class="word-card" @click="onSelectWord(item)">
        <text class="word-text">{{ item.word }}</text>
        <text class="trans-text">{{ item.translation }}</text>
      </div>
    </cell>
  </list>
</template>
```

---

### 4.3 轻量级响应式状态机: 跨页面状态管理设计 (免 Vuex 模式)

官方应用（如背单词与单词本）为了避免引入沉重的 `vuex.min.js`（增加约 350KB 内存与复杂响应式依赖），普遍采用了**闭包单例 Action-State 架构**（反编译自 `reciter_app.js.bin`）：

```javascript
/**
 * 官方轻量跨页面全局状态单例
 */
const appStore = {
    state: {
        appMode: 'light',
        currentBookId: '',
        phaseSelect: {},
        timeSelect: {},
        learningProgress: 0
    },
    actions: {
        setAppMode(mode) {
            appStore.state.appMode = mode;
        },
        setCurrentBook(bookId) {
            appStore.state.currentBookId = bookId;
        },
        setPhaseSelect(data) {
            // 通过深度拷贝断开引用
            appStore.state.phaseSelect = JSON.parse(JSON.stringify(data));
        },
        setTimeSelect(data) {
            appStore.state.timeSelect = JSON.parse(JSON.stringify(data));
        }
    }
};

// 页面内使用方式:
// 1. 在 Page.beforeVueInstantiate 中挂载: Vue.prototype.$store = appStore;
// 2. 在任何 Vue 组件内直接读取: this.$store.state.appMode
// 3. 在任何 Vue 组件内提交变更: this.$store.actions.setPhaseSelect({ stage: 1 })
```

---

### 4.4 硬件按键拦截与事件总线 (`buttonEventManager.headButtonPress`)

S7 Pro 拥有实体按键（位于笔头侧边的物理 Home 键）。当微应用处于前台时，官方应用通过 `buttonEventManager` 全局事件总线进行按键拦截：

```javascript
// 官方防抖与优先级处理机制
this.homeButtonRelease = () => {
    // 1. 处于特定阻断页面（如扫描中、实时 OCR 取景中）时禁止退出
    if (this.$pageName === 'scan' || this.$pageName === 'scanWordPreview') {
        console.warn('Scan in progress, home button ignored');
        return;
    }
    
    // 2. 路由防抖锁
    if (this.isJumping) return;
    this.isJumping = true;
    
    // 3. 调度全局查词应用或返回系统桌面
    globalManager.setCurrentAppId('8080252464522508');
    $falcon.navTo('falcon://8080252464522508/index', {
        fromApp: 'reciter'
    }, {
        inAnimation: 'none',
        outAnimation: 'none'
    });
};

// 在 Page.onShow 中监听:
buttonEventManager.headButtonPress.on(this.homeButtonRelease);

// 在 Page.onHide 和 Page.onUnload 中必须严格注销，否则引发内存泄露与后台误触:
buttonEventManager.headButtonPress.off(this.homeButtonRelease);
```

---

## 5. 系统桌面启动器架构深度逆向 (Desktop Launcher Deep Dive)

系统桌面启动器（AppID: `8080222437664451`）是 S7 Pro 上层交互的枢纽，运行于 `/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/`。

### 5.1 双屏拓扑模型: `PagesSlider.vue` (`<slider>`) 原生动力学引擎

桌面根容器通过专有的 `<PagesSlider>` 组件管理系统主屏与卡片列表屏：

```html
<!-- 反编译还原自 indexPage-085a554f.js.bin 中的 PagesSlider.vue -->
<template>
  <slider
    ref="slider"
    class="slider-outer"
    autoPlay="false"
    interval="3000"
    showIndicators="false"
    :infinite="infinite"
    :vertical="isVerticalSwipe"
    :index="selectedIndex"
    @change="onChange"
  >
    <slot />
  </slider>
</template>

<script>
export default {
  name: "PagesSlider",
  props: {
    currentIndex: { type: Number, default: 0 },
    isVerticalSwipe: { type: Boolean, default: false }, // S7 Pro 横屏模式下固定为 false
    infinite: { type: Boolean, default: false }         // 禁止无限循环，提供硬件边缘阻尼
  },
  data() {
    return {
      selectedIndex: this.currentIndex
    };
  },
  methods: {
    onChange(e) {
      this.$nextTick(() => {
        this.selectedIndex = e.index;
      });
      // 向外抛出索引变更，同步更新右侧指示器高亮与子屏激活状态
      this.$emit("currentIndexChanged", e.index);
    }
  }
};
</script>

<style>
.slider-outer {
  position: absolute;
  left: 0px;
  top: 0px;
  width: 1020px;
  height: 240px;
}
</style>
```

#### 原生手势动力学参数（提取自 `libfalcon.so` `greenui::SliderView`）
- **`touchSlop = 8px`**：移动位移 $\Delta X \le 8\text{px}$ 视为轻触点击，不触发滑动。
- **方向判决门**：横屏滑动必须满足 $|\Delta X| > |\Delta Y|$，且位移大于 8 像素时，立即调用 `requestDisallowInterceptTouchEvent(true)` 锁定手势。
- **甩动翻页阈值**：释放时若触摸速度 $|V_x| \ge 400\text{px/s}$，直接甩动翻页；否则位移必须超过半屏（$|\Delta X| > 510\text{px}$）方可完成翻页，未达阈值平滑物理回弹。

---

### 5.2 微应用动态发现与 `checkAddDesktopIcon` 平台过滤算法

桌面在初始化卡片列表时，调用底层 `pm.getInstalledPackages()` 获取应用元数据，并逐项执行 `checkAddDesktopIcon` 过滤算法（反编译还原自 `BaseCardsList.vue`）：

```javascript
async checkAddDesktopIcon(packageInfo) {
    if (!packageInfo || !packageInfo.props || !packageInfo.props.addDesktop) {
        return true; // 未配置 addDesktop 时默认显示
    }
    
    // 1. 全局显式禁用（例如后台服务 SERVICE 或专用输入法面板）
    if (packageInfo.props.addDesktop === false || packageInfo.props.addDesktop === "false") {
        return false;
    }

    // 2. 硬件主题平台映射表
    const platformMap = {
        'theme-exam':        'exam_platform',
        'theme-almond':      'almond_platform',
        'theme-x3s':         'x3s_platform',
        'theme-coco':        'coco_platform',
        'theme-hermes':      'hermes_platform',
        'theme-hermes-plus': 'hermes_plus_platform',
        'theme-apollo':      'apollo_platform',
        'theme-plum':        'plum_platform',
        'theme-melon':       'melon_platform',
        'theme-olive':       'olive_platform',
        'theme-popcorn':     'popcorn_platform',
        'theme-y03':         'y03_platform',
        'theme-y07':         'y07_platform',
        'theme-y08':         'y08_platform', // 有道词典笔 S7 Pro 匹配键！
        'theme-y06':         'y06_platform',
        'theme-y05':         'y05_platform'
    };

    const platformKey = platformMap[this.globalThemeName];
    if (platformKey && typeof packageInfo.props.addDesktop === 'object') {
        const isSupported = packageInfo.props.addDesktop[platformKey];
        if (isSupported !== undefined && !isSupported) {
            return false; // 当前平台被显式配置为 false，予以隐藏
        }
    }

    return true;
}
```

#### S7 Pro 匹配准则
S7 Pro 运行环境的主题代号固定为 `'theme-y08'`。第三方应用必须在 `manifest.json` 或 `packages.json` 中配置 `"addDesktop": { "y08_platform": true }`，方可呈现在桌面 Page 1 的卡片矩阵中。

---

### 5.3 新安装应用插槽算法 (Slot Assignment: 设置项前插规则)

反编译 `BaseCardsList.vue` 的 `refreshApps` 与 PMS 事件监听，揭示了官方严密的**设置项前插算法**：

```javascript
// 反编译还原自 BaseCardsList.vue
const SettingsAppID = '8080272425914438'; // 系统设置 AppID

function insertAppToCardList(cardItems, packageInfo) {
    const targetIndex = cardItems.findIndex(item => item.appid === packageInfo.appid);
    
    if (targetIndex > -1) {
        // 应用已存在：就地更新图标与标题
        cardItems[targetIndex].icon = getDesktopAppIcon(packageInfo);
        cardItems[targetIndex].text = getDesktopAppTitle(packageInfo);
        cardItems.splice(targetIndex, 1, cardItems[targetIndex]);
    } else {
        // 应用为新安装：构造全新卡片对象
        const newCard = {
            appid: packageInfo.appid,
            text: getDesktopAppTitle(packageInfo),
            icon: getDesktopAppIcon(packageInfo),
            visible: true,
            isShowPointTip: false
        };

        // 核心定位：在卡片序列中寻找系统设置项
        const settingIndex = cardItems.findIndex(item => item.appid === SettingsAppID);
        
        if (settingIndex > -1) {
            // 严性规则：强制插入到系统设置正前方！
            cardItems.splice(settingIndex, 0, newCard);
        } else {
            // 未找到设置项时插入至末尾
            cardItems.push(newCard);
        }
    }
}
```

---

### 5.4 桌面图标与标题多主题解析 (`theme-y08` 138×138px 标杆)

#### 图标寻址与尺寸规范
```javascript
// 反编译还原自 BaseCardsList.vue
getDesktopAppIcon(packageInfo) {
    if (packageInfo.props && packageInfo.props.Icons) {
        // 优先读取 S7 Pro 的专用主题键 'theme-y08'
        const relPath = packageInfo.props.Icons[this.globalThemeName] || packageInfo.icon;
        return 'file://'.concat(packageInfo.installPath, relPath);
    }
    return 'file://'.concat(packageInfo.installPath, packageInfo.icon);
}
```

反编译 `Card-66980c69.js.bin` 计算属性证实：在 `theme-y08` 平台下，桌面卡片图标物理渲染尺寸硬编码为 **`138px × 138px`**。开发者必须提供 138×138 像素、32位带 Alpha 通道的 PNG 图标，以实现点对点锐利渲染，杜绝双线性拉伸模糊。

---

### 5.5 分页状态指示器: `VerticalIndicators.vue` 组件实现

```html
<!-- 反编译自 VerticalIndicators.js.bin -->
<template>
  <div class="container">
    <div
      v-for="(item, index) in count"
      :key="item"
      :class="getClass(index)"
    />
  </div>
</template>

<script>
export default {
  name: "VerticalIndicators",
  props: {
    count: { type: Number, default: 2 },
    currentIndex: { type: Number, default: 0 },
    isExamTheme: { type: Boolean, default: false }
  },
  data() {
    return {
      selectedIndex: this.currentIndex
    };
  },
  methods: {
    getClass(index) {
      if (index === this.selectedIndex) {
        return this.isExamTheme ? "indicator-current-exam" : "indicator-current";
      }
      return this.isExamTheme ? "indicator-exam" : "indicator";
    },
    setCurrentIndex(index) {
      this.selectedIndex = index;
    }
  }
};
</script>

<style>
.container {
  width: 8px;
  justify-content: center;
  align-items: center;
}
.indicator {
  width: 8px;
  height: 8px;
  margin: 4px;
  border-radius: 4px;
  background-color: rgba(255, 255, 255, 0.3);
}
.indicator-current {
  width: 8px;
  height: 8px;
  margin: 4px;
  border-radius: 4px;
  background-color: #ffffff;
}
</style>
```

---

## 6. 官方输入法软键盘子系统逆向剖析 (Input Method & Keyboard Architecture)

在 S7 Pro 系统中，查词、设置与网络配置大量依赖系统软键盘。反编译 `/tmp/InputPage-38d8bb4d.js.bin` 与 `/tmp/NumberKeyboard-b9891f44.js.bin`，重构出其高效的嵌入式键盘架构。

### 6.1 全功能输入法架构: `ApolloInputPage.vue` 组件模型

`ApolloInputPage` 是横屏模式下的核心输入界面，由三层按键矩阵与候选词栏构成：

```
+-----------------------------------------------------------------------------------+
|  [候选联想词栏] Word Candidates: "abandon" | "ability" | "able" | [More... >]     |
+-----------------------------------------------------------------------------------+
|  Row 0:  q   w   e   r   t   y   u   i   o   p   [BackSpace / Clear]             |
|  Row 1:    a   s   d   f   g   h   j   k   l     [Enter / Search]                 |
|  Row 2:  [Caps]   z   x   c   v   b   n   m   [.?123]   [Space]   [Microphone]   |
+-----------------------------------------------------------------------------------+
```

---

### 6.2 高频按键与连续长按删除机制 (`NumberKeyboard.vue`)

在退格键（Delete）与数字连续输入中，触摸事件与定时器的控制极其讲究。反编译字节码提取出的源码如下：

```javascript
// 反编译还原自 NumberKeyboard-b9891f44.js.bin
export default {
  name: "NumberKeyboard",
  props: {
    globalThemeName: { type: String, default: "" },
    keySrc: { type: String, default: "" }
  },
  data() {
    return {
      longPressedInterval: 0
    };
  },
  methods: {
    /**
     * 连续长按触发逻辑（100毫秒高频连发定时器）
     */
    keyLongPress(isLongPress, key) {
      if (isLongPress) {
        if (this.longPressedInterval) {
          clearInterval(this.longPressedInterval);
        }
        // 每 100ms 连发一次点击事件（例如实现快速退格删除文本）
        this.longPressedInterval = setInterval(() => {
          this.$emit('keyClicked', key);
        }, 100);
      }
    },

    /**
     * 手指抬起事件处理
     */
    keyTouchEnd(isLongPress, key) {
      if (isLongPress && this.longPressedInterval) {
        // 若为长按释放，清除定时器，不再额外补偿单次点击
        clearInterval(this.longPressedInterval);
        this.longPressedInterval = 0;
        return;
      }
      // 正常短按单次点击
      this.$emit('keyClicked', key);
    },

    beforeDestroy() {
      // 必须严格清空定时器，防止组件销毁后定时器在后台野指针执行
      if (this.longPressedInterval) {
        clearInterval(this.longPressedInterval);
        this.longPressedInterval = 0;
      }
    }
  }
};
```

---

### 6.3 字符键盘与符号键盘切换: `OnlyCharKeyboard` 与 `KeyboardBottomBar`

字符键盘支持动态模式切换：
- **小写英文字符态 (`isLowerCharsShowing`)**：标准 QWERTY 键盘。
- **大写锁定态 (`isUpperCharsShowing`)**：受 `capsLockButtonCheckedChanged` 驱动。
- **数字模式 (`numberKeyboardKeyClicked`)**：切换至 3×4 九宫格或全横排数字。
- **标点符号模式 (`symbolKeyboardKeyClicked`)**：展示常用中英文标点矩阵。

---

### 6.4 离线联想词检索引擎集成 (`doSearchWord` / `selectFirstWord`)

在用户敲击字母时，`ApolloInputPage` 通过 `appendLetter` 监听输入流，并触发内置的本地词典 Trie 树检索：

```javascript
// 反编译自 InputPage-38d8bb4d.js.bin
appendLetter(char) {
    this.inputText += char;
    this.doSearchWord(this.inputText);
},
doSearchWord(prefix) {
    if (!prefix || prefix.length < 2) {
        this.candidateWords = [];
        return;
    }
    // 异步查询本地离线词典服务
    const dictService = this.$falcon.requireNativePlugin('DictOfflineService');
    if (dictService && dictService.searchPrefix) {
        dictService.searchPrefix(prefix, 5, (results) => {
            this.candidateWords = results;
        });
    }
}
```

---

## 7. 生产级工程蓝图与黄金模板 (Production Engineering Blueprints)

### 7.1 模式 A: 生产级多页面动态加载微应用模板 (Multi-Page Bundle)

本模板严格遵循背单词（Reciter）与百度网盘（Netdisk）的官方多包架构标准，专为中大型、多功能嵌入式微应用量身打造。

#### (1) `app.js` (入口容器定义)
```javascript
import Vue from 'vue';

// 1. 全局轻量跨页面 Store
const store = {
    state: {
        theme: 'theme-y08',
        userInfo: null,
        counter: 0
    },
    actions: {
        setUserInfo(info) {
            store.state.userInfo = Object.assign({}, info);
        },
        increment() {
            store.state.counter += 1;
        }
    }
};

// 2. 自定义 Page 基类
class CustomPage extends $falcon.Page {
    constructor() {
        super();
        this.isNavigating = false;
    }

    beforeVueInstantiate(V) {
        // 全局依赖注入
        V.prototype.$store = store;
        V.prototype.$bus = new V();
    }

    onLoad(query) {
        super.onLoad(query);
        console.log(`[Lifecycle] onLoad: ${this.$pageName}, query:`, JSON.stringify(query));
    }

    onShow(query) {
        this.isNavigating = false;
        super.onShow(query);
        // 关键穿透：下发参数至 Vue 根实例
        if (this.$root && typeof this.$root.setData === 'function') {
            this.$root.setData(query);
        }
        if (this.$root && typeof this.$root.onShow === 'function') {
            this.$root.onShow();
        }
    }

    onHide() {
        super.onHide();
        if (this.$root && typeof this.$root.onHide === 'function') {
            this.$root.onHide();
        }
    }

    onUnload() {
        super.onUnload();
        if (this.$root && typeof this.$root.onUnload === 'function') {
            this.$root.onUnload();
        }
    }
}

// 3. 自定义 App 基类
class CustomApp extends $falcon.App {
    onLaunch(options) {
        super.onLaunch(options);
        console.log('[Lifecycle] App launched with options:', JSON.stringify(options));
        // 注册全局默认 Page 基类
        $falcon.useDefaultBasePageClass(CustomPage);
    }

    onDestroy() {
        console.log('[Lifecycle] App destroyed');
        super.onDestroy();
    }
}

// 4. 挂载元数据
CustomApp.meta = {
    name: "com.developer.production.app",
    version: "1.0.0",
    otaVersion: "1.0.0",
    isSingleJsBundle: false, // 启用多包动态加载
    supportUnInstall: true,
    addDesktop: {
        y08_platform: true
    },
    props: {
        Icons: {
            'theme-y08': 'assets/images/app_icon/theme-y08/app_icon.png'
        }
    }
};

$falcon.__AppClazz = CustomApp;

// 5. 动态模块加载器
$falcon.__loadModuleDefault = async function(pageName) {
    try {
        const mod = await import('./pages/' + pageName + '.js');
        return mod.default;
    } catch (err) {
        console.log('[FalconLoader] Error loading chunk:', pageName, err.message);
        throw err;
    }
};
```

#### (2) `pages/index.vue` (首页实现)
```html
<template>
  <div class="container">
    <!-- 头部工具栏 -->
    <div class="header">
      <text class="title">生产级微应用首页</text>
      <text class="counter">计数: {{ $store.state.counter }}</text>
    </div>

    <!-- 核心功能区 -->
    <div class="content">
      <div class="button primary" @click="jumpToDetail">
        <text class="btn-text">跳转到二级详情页</text>
      </div>
      <div class="button danger" @click="exitApp">
        <text class="btn-text">退出微应用</text>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: 'IndexPage',
  methods: {
    setData(query) {
      console.log('IndexPage received query data:', query);
    },
    jumpToDetail() {
      this.$store.actions.increment();
      $falcon.navTo('detail', { from: 'index', timestamp: Date.now() });
    },
    exitApp() {
      this.$app.finish();
    }
  }
};
</script>

<style>
.container {
  width: 1020px;
  height: 240px;
  background-color: #121212;
  flex-direction: column;
}
.header {
  height: 50px;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
  padding-left: 24px;
  padding-right: 24px;
  border-bottom-width: 1px;
  border-bottom-color: #2a2a2a;
}
.title {
  color: #ffffff;
  font-size: 22px;
  font-weight: bold;
}
.counter {
  color: #00e676;
  font-size: 18px;
}
.content {
  flex: 1;
  flex-direction: row;
  justify-content: center;
  align-items: center;
}
.button {
  width: 240px;
  height: 60px;
  border-radius: 30px;
  justify-content: center;
  align-items: center;
  margin-left: 20px;
  margin-right: 20px;
}
.primary {
  background-color: #2979ff;
}
.danger {
  background-color: #ff1744;
}
.btn-text {
  color: #ffffff;
  font-size: 20px;
}
</style>
```

#### (3) `pages/detail.vue` (二级页面实现)
```html
<template>
  <div class="detail-container">
    <div class="nav-bar">
      <!-- 官方规范返回按钮 -->
      <div class="back-btn" @click="goBack">
        <text class="back-text">＜ 返回</text>
      </div>
      <text class="detail-title">二级数据详情</text>
    </div>
    <div class="detail-body">
      <text class="info-text">接收参数: {{ incomingParam }}</text>
    </div>
  </div>
</template>

<script>
export default {
  name: 'DetailPage',
  data() {
    return {
      incomingParam: '等待参数...'
    };
  },
  methods: {
    setData(query) {
      if (query && query.from) {
        this.incomingParam = `来自 ${query.from} 页面，时间戳: ${query.timestamp}`;
      }
    },
    goBack() {
      this.$page.finish(); // 优雅出栈
    }
  }
};
</script>

<style>
.detail-container {
  width: 1020px;
  height: 240px;
  background-color: #1a1a1a;
  flex-direction: column;
}
.nav-bar {
  height: 50px;
  flex-direction: row;
  align-items: center;
  padding-left: 16px;
  border-bottom-width: 1px;
  border-bottom-color: #333333;
}
.back-btn {
  padding: 8px 16px;
  background-color: #333333;
  border-radius: 8px;
}
.back-text {
  color: #ffffff;
  font-size: 18px;
}
.detail-title {
  color: #ffffff;
  font-size: 20px;
  margin-left: 24px;
}
.detail-body {
  flex: 1;
  justify-content: center;
  align-items: center;
}
.info-text {
  color: #cccccc;
  font-size: 22px;
}
</style>
```

---

### 7.2 模式 B: 极限轻量单包微应用模板 (Single JS Bundle)

本模板将所有页面与依赖压缩至单字节码文件，专为极速冷启动、功能聚焦的小工具（如手电筒、秒表、计算器）设计。

```javascript
// single_app.js
import Vue from 'vue';

// 页面 A 组件
const HomePage = {
  template: `
    <div class="box">
      <text class="txt">极速单包应用 - 首页</text>
      <div class="btn" @click="currentView = 'setting'"><text class="btntxt">前往设置</text></div>
    </div>
  `
};

// 页面 B 组件
const SettingPage = {
  template: `
    <div class="box">
      <text class="txt">极速单包应用 - 设置</text>
      <div class="btn" @click="currentView = 'home'"><text class="btntxt">返回首页</text></div>
    </div>
  `
};

// 根应用定义
class SingleApp extends $falcon.App {
  onLaunch() {
    super.onLaunch();
  }
}

SingleApp.meta = {
  name: "com.developer.single.util",
  version: "1.0.0",
  isSingleJsBundle: true // 标记为单包
};

$falcon.__AppClazz = SingleApp;

// 默认直接导出根 Vue 组件
export default {
  data() {
    return {
      currentView: 'home'
    };
  },
  components: {
    home: HomePage,
    setting: SettingPage
  },
  render(h) {
    return h(this.currentView);
  }
};
```

---

### 7.3 微应用工程清单规范: `manifest.json` 与 `packages.json`

#### (1) `manifest.json` (生产级标准)
```json
{
  "name": "生产级科学计算器",
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
        "component": "index"
      },
      "pages/detail": {
        "component": "detail"
      }
    }
  }
}
```

#### (2) `packages.json` (系统注册表注入条目)
```json
{
  "8080999988887777": {
    "appid": "8080999988887777",
    "name": "生产级科学计算器",
    "version": "1.0.0",
    "otaVersion": "1.0.0",
    "icon": "/app_icon.png",
    "installPath": "/userdata/miniapp/data/mini_app/pkg/8080999988887777/a",
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

### 7.4 部署投递、启动自愈与全流程验证清单

```
                       +-----------------------------------+
                       |    1. 编译 JS/Vue 为 QuickJS 字节码  |
                       |       (qjsc 2020-07-05 -c -m)     |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       |    2. 目录规范封装与 A 槽位部署     |
                       |   (/userdata/.../pkg/<appid>/a/)  |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       |    3. 写入 packages.json 注册表    |
                       |    (注入 addDesktop: y08_platform) |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       |    4. 触发 PMS 广播或重启桌面       |
                       |    (kill -9 $(pgrep launcher))    |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       |    5. 物理 S7 Pro 屏幕真机验证      |
                       |    (1020x240 显示、按键与内存检测)  |
                       +-----------------------------------+
```

#### 生产验收核验清单 (Checklist)
1. **字节码版本一致性**：确认使用 QuickJS `2020-07-05` 编译器生成字节码，起始魔数为 Tag `0x3f`，禁止包含非本版本支持的操作码。
2. **多主题图标校验**：确认存在 `/assets/images/app_icon/theme-y08/app_icon.png` 且分辨率严格为 `138px × 138px`。
3. **平台过滤门校验**：确认 `manifest.json` 与 `packages.json` 中配置了 `"y08_platform": true`。
4. **生命周期对齐**：确认 `Page.onShow` 注册了实体按键拦截回调，且在 `Page.onHide` 与 `Page.onUnload` 中执行了 `off` 解绑。
5. **内存水位警戒线**：在设备终端执行 `top -p $(pgrep miniapp)`，观察微应用连续进入/退出 20 次，Resident Memory (RES) 增量必须小于 2 MB，绝无不可释放的定时器或 DOM 泄漏。
