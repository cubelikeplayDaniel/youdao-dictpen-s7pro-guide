# 有道词典笔 S7 Pro 系统桌面、下拉菜单与系统设置深度逆向架构报告

针对有道词典笔 S7 Pro（硬件平台 `Y08_CV1813_V0`，SoC Cvitek CV1813H ARMv7-A Cortex-A7 hard-float，Linux 5.10.4 内核，HaaS UI / Falcon 运行时）的系统桌面启动器、下拉控制菜单及系统设置三大核心微应用，逆向分析结论与关键技术规格如下：

---

## 一、 核心应用定位与绝对路径

- 桌面启动器 (Launcher, AppID: `8080222437664451`):
  `/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/`
  核心字节码文件：`app.js.bin`, `indexPage-085a554f.js.bin`, `vScreenIndex-2df5199e.js.bin`, `PagesSlider.vue`
- 下拉控制面板 (Dropdown / Top Panel, AppID: `8080222501178405`):
  `/userdata/miniapp/data/mini_app/pkg/8080222501178405/a/`
  核心字节码文件：`app.js.bin`, `indexPage-3ef349ba.js.bin`, `hvScreenBasePage-bcbc1026.js.bin`
- 系统设置 (Settings, AppID: `8080272425914438`):
  `/userdata/miniapp/data/mini_app/pkg/8080272425914438/b/`
  核心字节码文件：`BasePage-ae78eaab.js.bin`, `SettingManager-41d1e6fb.js.bin`, `brightnessMixin-a66e1e5e.js.bin`, `volumeMixin-57386e26.js.bin`
- 底层运行库与 HAL：
  `/usr/lib/libfalcon.so`（Falcon C++ 核心引擎与导航调度器）
  `/etc/miniapp/jsapis/libjsapi_export_core.so`（QuickJS 原生 C 扩展模块导出层）
  `/usr/lib/libydhal_devices.so`（硬件抽象层，直接对接 Linux Sysfs / ALSA / wpa_supplicant）

---

## 二、 课题一：桌面启动其他应用的调用机制与参数格式

### 1. 路由协议与 JSAPI
桌面启动应用统一使用 Falcon 全局运行时提供的 `$falcon.navTo`，基于 `falcon://<appid>/<page>` 协议进行应用间寻址定位。

反编译还原代码（来源：`/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/indexPage-085a554f.js.bin`）：

```javascript
navToOtherApp: function(item) {
  console.log("navToOtherApp,appid:", item.appid);
  this.setNavToAppId(item.appid);
  var targetUrl = 'falcon://' + item.appid + (item.page ? ('/' + item.page) : '/index');
  $falcon.navTo(targetUrl, {
    launchMode: item.launchMode || 'single-instance',
    inAnimation: item.inAnimation || 'none',
    outAnimation: item.outAnimation || 'none',
    fromApp: 'desktop'
  });
}
```

### 2. 参数规范定义
- `launchMode`: `'single-instance'`（默认）或 `'standard'`。单实例模式下若应用已在栈中，直接恢复到前台触发 `onShow`，避免重复创建；标准模式每次新建应用栈。
- `inAnimation`: 转场进入动画，取值 `'none'`（默认，即时显示）、`'slide-left'`、`'fade'`。
- `outAnimation`: 转场退出动画，取值 `'none'`、`'slide-right'`。
- `fromApp`: 来源标识（如 `'desktop'`），作为入参注入目标应用的 `onLaunch(options)` / `onShow()`。

### 3. 底层 C++ 调度链路
1. `$falcon.navTo` 命中 QuickJS 绑定函数 `falcon::JSNavigatorHandler::wrap_navToApp`。
2. 内部调用 `falcon::FalconStack::instance()->startApp(appid, page, query_map, anim_id)`。
3. 应用栈管理器检查目标实例：
   - 若已存在且为单实例：调用 `FalconStack::appResumed(pApp)`，触发 JS 层 `App.onShow` 与 `Page.pageShowing`。
   - 若不存在：调用 `FalconStack::startAppInternal` 读取目标应用 `manifest.json`，初始化新 `FalconApp` 与 QuickJS 上下文，加载 `app.js.bin` 并调度 GreenUI 进行视口渲染。

---

## 三、 课题二：应用退出自身返回桌面的实现机制

系统依据场景划分为“页面栈回退（Page Finish）”与“应用级销毁（App Close）”两套体系：

### 1. 页面回退与退出自身：`this.$page.finish()`
通用基础页面（`/userdata/miniapp/data/mini_app/pkg/8080272425914438/b/BasePage-ae78eaab.js.bin`）的反编译实现：

```javascript
backButtonClicked: function() {
  if (typeof this.backButtonFunction === 'function') {
    this.backButtonFunction();
  } else {
    this.$page.finish();
  }
}
```

- **底层调用**：`this.$page.finish()` 对应 C++ `falcon::JSPageInstance::finish()` -> `falcon::FalconApp::popPage()`。
- **自动级联退出桌面**：当应用页面栈弹出后栈内无页面时，Falcon 框架自动执行 `falcon::FalconStack::closeApp()`，将焦点恢复到底层桌面启动器（`8080222437664451`）。
- **物理按键/手势拦截**：底层物理返回键和左滑退出手势由 `falcon::JSPageInstance::onBackPressed()` 捕获；可通过 `this.$page.setDisableLeftSwipeBack(true)` 禁用手势。

### 2. 显式关闭应用自身：`$falcon.closeApp()`
用于无页面栈的顶层控制中心或浮层窗口（如 `/userdata/miniapp/data/mini_app/pkg/8080222501178405/a/indexPage-3ef349ba.js.bin` 下拉菜单与 `/userdata/miniapp/data/mini_app/pkg/8080272425914438/b/homeModel.js.bin`）：

```javascript
closeTopPanel: function() {
  $falcon.closeApp();
}
```

- **底层调用**：`$falcon.closeApp()` 绑定至 `falcon::JSNavigatorHandler::wrap_closeApp`，直接执行 `falcon::FalconStack::closeApp(appid, true)`。
- **资源清理**：触发 `App.onHide` -> `App.onDestroy`，释放 GreenUI 节点及 QuickJS 上下文，恢复桌面运行态。

---

## 四、 课题三：桌面卡片滑动组件与指示器联动

### 1. 原生组件判定
桌面主屏卡片滑动采用 **原生 `<slider>` 组件**（封装在 `src/components/PagesSlider.vue`），而非 `<scroller>`。`<scroller>` 仅用于单张卡片内或列表子页面的长文本滚动。

### 2. 模板结构与滑动属性
反编译还原结构（`/userdata/miniapp/data/mini_app/pkg/8080222437664451/a/vScreenIndex-2df5199e.js.bin`）：

```html
<slider
  ref="slider"
  class="slider-outer"
  :selectedIndex="currentIndex"
  :showIndicators="false"
  :infinite="false"
  :vertical="false"
  @change="currentIndexChanged"
>
  <slider-item v-for="(screen, sIdx) in appScreens" :key="'screen_' + sIdx">
    <v-screen-card-list :items="screen.items" @cardClicked="onCardClicked" />
  </slider-item>
</slider>

<horizontal-indicators :count="totalScreenCount" :current="currentIndex" />
```

- `:selectedIndex="currentIndex"`：双向绑定当前活动屏索引。
- `:showIndicators="false"`：关闭底层系统默认圆点，由上层自定义组件渲染。
- `:infinite="false"`：禁止无限循环滚动，首尾页具有物理阻尼回弹。
- `:vertical="false"`：限定横向卡片轮播。
- `@change="currentIndexChanged"`：滑动翻页事件，回调参数为 `{ index: number }`。

### 3. 指示器实现
独立组件 `HorizontalIndicators.vue` 置于 `<slider>` 同级，通过 `calculateScreens()` 根据已安装应用总数与每屏容量（如 4 或 6 个应用）动态生成 `totalScreenCount`，在 `@change` 中实时更新高亮圆点样式（`indicator-current` / `indicator-current-y05`）。

---

## 五、 课题四：下拉控制菜单底层硬件交互全链路

下拉面板（`8080222501178405`）采用典型的三层软硬件交互架构：

```
[UI 表现层 (Vue SFC)]
  hvScreenBasePage.vue / indexPage.vue
      │  调用 JS Manager
      ▼
[JS 原生扩展接入层 (ES6 Modules)]
  import { Brightness } from "brightness";
  import { Volume }     from "volume";
  import { Wifi }       from "wifi";
  import { BatteryInfo } from "batteryInfo";
      │  QuickJS 原生 C++ 模块桥接
      ▼
[C++ 代理层 (/etc/miniapp/jsapis/libjsapi_export_core.so)]
  JSBrightnessProxy / JSVolumenessProxy / JSWifiProxy / JSBatteryInfoProxy
      │  调用 C++ HAL
      ▼
[硬件抽象层 (/usr/lib/libydhal_devices.so & Linux Kernel Sysfs)]
  Linux Sysfs / ALSA Mixer / wpa_supplicant 进程
```

### 1. 背光亮度 (Brightness)
- **UI 组件与调用**：`<adjust-seekbar>` 触发 `brightnessChanging(e)` / `brightnessFinish(e)`，调用 `brightnessManager.setBrightness(val)`（取值范围 0-100）。
- **C++ 代理与 HAL**：`JSBrightnessProxy::setBrightness` -> `YDALAPI::YBrightnessModule::setBrightness`。
- **底层设备节点**：
  `/sys/devices/platform/backlight/backlight/backlight/brightness`
  `/sys/class/backlight/backlight/bl_power`
  HAL 内部通过计算公式 `map2brightness` 将 0-100 映射为内核 PWM 背光占空比。支持 `onBrightnessChanged` 异步通知。

### 2. 系统音量 (Volume)
- **UI 组件与调用**：`<adjust-seekbar>` 触发 `volumeChanging(e)` / `volumeFinish(e)`，调用 `volumeManager.setVolume(val)`（取值范围 0-15）。
- **C++ 代理与 HAL**：`JSVolumenessProxy::setVolume` -> `YDALAPI::YVolumeModule::set_volume`。
- **底层设备控制**：调用 ALSA 混音器接口：
  `amixer cset numid=... value=...`（针对声卡节点 `Playback Volume` 与 `spk_volume`）。
  同时前端调用 `volumeManager.startVolumeThread()` 拦截物理侧键按压，通过 `JSVolumenessProxy::onNotifyVolumeValue` 向上抛出信号并实时刷新 UI。

### 3. Wi-Fi 控制与状态 (Wi-Fi)
- **UI 操作**：
  - 点击开关：`wifiManager.isOpen() ? wifiManager.close() : wifiManager.open()`。
  - 长按按钮：`$falcon.navTo('falcon://8080272425914438/wifi')` 直接跳转设置。
- **C++ 代理与 HAL**：`JSWifiProxy::open()`, `close()`, `isOpen()`, `getWifiQual()` -> `YDALAPI::YWifiModule`。
- **底层网络通信**：通过 `/usr/lib/libwpa_client.so` 与系统 `wpa_supplicant` 本地套接字交互；执行系统级指令 `sys_config wifi 1/0`。定时器 `startWifiQualTimer()` 每隔 2 秒读取信号强度并触发 `onWifiQualChanged` 信号，前端动态切换 4 档信号图标。

### 4. 电池电量与充放电 (Battery)
- **数据读取**：`batteryInfoManager.getBatteryCapacity()` 获取百分比，`getBatteryStatus()` 获取充放电状态。
- **事件监听**：`batteryInfoManager.on('batteryInfoChange', cb)`。
- **底层 Sysfs 节点**：`/usr/lib/libydhal_devices.so` 直接读取：
  `/sys/class/power_supply/battery/capacity`（电量）
  `/sys/class/power_supply/battery/voltage_now`（当前电压）
  `/sys/class/power_supply/battery/status`（状态：`Charging` / `Discharging` / `Full`）

---

## 六、 课题五：系统应用与页面全生命周期流程

Falcon 运行时严格区分应用级与页面级生命周期，并在页面级扩展了专有的视口可见性控制：

### 1. 应用级生命周期 (`app.js.bin` 中的 `App({...})`)
- `onLaunch(options)`：微应用实例冷启动时触发一次。解析启动来源（`fromApp`）与启动模式，初始化 `globalManager`，依据主板硬件代号绑定皮肤主题路径（如 `assets/images/y03`）。
- `onShow()`：应用从后台切回前台或启动呈现时触发。桌面在此阶段检查二级启动信息（`handleSecStartupInfoChange`）、校验家长管控服务状态，并恢复轮播动画。
- `onHide()`：打开其他应用覆盖当前界面或下拉控制面板弹出时触发。暂停界面动画，停止高功耗传感器轮询，提交日志。
- `onDestroy()`：调用 `$falcon.closeApp()` 退出或系统释放时触发。解绑底层服务代理与事件监听，QuickJS 执行 Full GC 回收内存。

### 2. 页面级生命周期 (`Page({...})` 与 Vue 组件)
- `created()` / `mounted()`：构建 Vue 响应式数据与 GreenUI 视图树节点。
- `onLoad(query)`：注入 URL 携带的查询参数。
- `pageShowing()`（**Falcon 专有钩子**）：
  页面物理呈现在屏幕上（包括从下级页面返回）时立即触发。
  桌面在此钩子中调用 `calculateScreens()`、启动 Wi-Fi 信号轮询定时器 `startWifiQualTimer()` 并同步电量；设置与下拉面板在此钩子中通过 `brightnessManager.getBrightness()` 同步硬件实际数值并开启监听。
- `pageHidden()`（**Falcon 专有钩子**）：
  页面被遮挡或退入后台时立即触发。
  系统在此钩子中执行 `stopWifiQualTimer()`、`stopVolumeThread()` 并通过 `off(...)` 解绑硬件变更监听，杜绝后台无谓空转与电池损耗。
- `beforeDestroy()` / `destroyed()`：组件注销，释放所有闭包与原生回调引用。
