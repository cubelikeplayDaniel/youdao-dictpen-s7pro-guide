# 官方原生 MiniApp 前端组件与工程开发规范报告

---

## 1. 核心架构与运行机制

有道词典笔 S7 Pro（硬件平台：`Y08_CV1813_V0`，SoC：Cvitek CV1813H ARMv7-A Cortex-A7 hard-float，Linux 5.10.4，128MB RAM，1020x240 横向逻辑画布）上的所有官方应用（包括桌面启动器 Launcher、百度网盘、网易云音乐、系统设置、官方输入法等）均基于**阿里 HaaS UI / Falcon 深度定制的轻量级原生渲染框架**开发。

### 1.1 框架本质与渲染管线
系统 UI 绝非基于浏览器内核或 WebView（如 Chromium、WebKit），系统固件中无任何浏览器进程，而是直接由轻量级 C++ 渲染管线驱动：
1. **源码语言层**：标准 Vue.js 2.x 单文件组件（SFC，`.vue`），采用 Weex 风格的原生标签（`div`, `text`, `image`, `scroller`, `slider`, `list`, `cell` 等）。
2. **构建编译层**：通过 Webpack 与 `vue-loader` 将 `.vue` 编译为原生渲染函数（包含 `_c`、`_v`、`_s`、`_m`、`_e` 等标准 Vue 运行时指令），打包为 ESM/CommonJS 格式的 JavaScript 文件。
3. **字节码编译层**：使用 QuickJS 2020-07-05 编译链（`qjsc -m -c`），将 `.js` 转为 QuickJS 模块字节码（`.js.bin`，首字节必须为 `0x3f`，对应常量 `DUMP_BYTECODE = 63`）。
4. **原生运行时层**：宿主程序 `/usr/bin/miniapp` 加载 `/usr/lib/libfalcon.so`，利用内置 QuickJS 引擎执行字节码，通过 C++ 类 `_ZN3Vue12createElmApi`、`JQuick::ComponentRegistry` 将 Vue VNode 节点映射为底层 `greenui::View` 原生视图树，最终通过 Skia 2D 图形库或 DirectFB 提交到 `/dev/fb0`（Linux Framebuffer）。

```
.vue 单文件组件 (Vue 2 SFC)
         │
         ▼ (Webpack + vue-loader)
.js 打包文件 (包含 _c() 原生节点渲染函数)
         │
         ▼ (host_tools/qjsc -m -c)
.js.bin (QuickJS 2020-07-05 模块字节码, 0x3f 魔数)
         │
         ▼ (/usr/bin/miniapp + /usr/lib/libfalcon.so)
VNode 树 (Vue::createElmApi) ──► C++ BaseElmApi ──► greenui::View ──► Linux /dev/fb0
```

---

## 2. 官方应用工程解构与逆向分析

设备上官方应用持久化存储并挂载在 `/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/a/`。通过解包分析百度网盘（`8001661310449825`）、网易云音乐（`8001649731775833`）及官方输入法（`8001666679481944`），其工程拓扑高度一致。

### 2.1 官方应用包文件拓扑结构
```
/userdisk/secondary/miniapp/data/mini_app/pkg/8001661310449825/a/
├── manifest.json              # 应用核心元数据、平台显示配置、文件 cert 校验表
├── app_icon.png               # 应用默认桌面图标 (240x240 或更大尺寸 PNG)
├── app.js.bin                 # 全局入口生命周期与主样式注入模块
├── index.js.bin               # 根路由与主页面容器模块
├── BasePage-42d28a45.js.bin   # 页面基础模板组件 (抽离的公共代码分包)
└── assets/                    # 静态资源目录
    └── images/
        └── app_icon/
            ├── theme-popcorn/app_icon.png
            └── theme-y03/app_icon.png
```

### 2.2 入口文件与组件加载链
1. **`app.js.bin`（应用生命周期与初始化）**：
   - 导出一个继承自 Vue 实例的根对象。
   - 包含应用的生命周期钩子：`onLaunch`、`onShow`、`onHide`、`onError`。
   - 注入全局 CSS 规则表（通过 `VComponent::setClassJson` 将样式解析为 JSON 格式的属性树）。
2. **`index.js.bin`（路由与视图入口）**：
   - 包含主视图组件 `IndexPage` 的渲染逻辑。
   - 通过 Webpack 的 `__webpack_require__` 与动态 import 语法按需加载页面分包（如 `BasePage-xxxx.js.bin`）。
3. **渲染函数特征（验证前端框架为 Vue 2.x）**：
   - 在官方输入法 `InputPage-38d8bb4d.js` 的 QuickJS 逆向反编译中，获取到如下典型的 Vue 2.x 渲染树调用：
     ```javascript
     var e = this;
     var t = e.$createElement;
     var i = e._self._c || t;
     return i("div", {
       staticClass: ["input-page"],
       style: e.keyBoardBgStyle,
       on: {
         click: function($event) { ... }
       }
     }, [
       e.inputPageBgVisible ? i("div", { staticClass: ["input-page-bg"] }) : e._e(),
       i(e.wordsPanelComponent, {
         tag: "component",
         words: e.words,
         moreWordsShowing: e.moreWordsShowing
       })
     ]);
     ```
   - 结构清晰表明：官方应用使用标准 Vue 2.x 的 `render(h)` 函数结构，使用数组传递 children，使用 `_e()` 生成空节点，使用 `_v()` 生成纯文本。

---

## 3. 桌面启动器（Launcher）主屏幕显示判定机制

许多自研应用安装后未在主屏幕显示，原因在于桌面启动器通过白名单与黑名单机制对应用列表进行了严格过滤。

### 3.1 启动器识别流程
系统桌面启动器 App ID 为 `8080222437664451`（挂载于 `/userdisk/secondary/miniapp/data/mini_app/pkg/8080222437664451/a/`），主页面逻辑位于 `indexPage-085a554f.js.bin`。

启动器通过扫描系统注册表 `/oem/secondary/etc/miniapp/resources/local_packages.json` 与 `/userdisk/secondary/miniapp/data/mini_app/pkg/` 下的应用，调用内部方法 `checkAddDesktopIcon(packageInfo)`。

### 3.2 平台代号映射表与显示逻辑
通过对 `indexPage-085a554f.js.bin` 进行 QuickJS 字节码逆向，提取出确切判定代码（对应字节码偏移 15341–15407）：

```javascript
const platformMap = {
  "theme-exam": "exam_platform",
  "theme-almond": "almond_platform",
  "theme-x3s": "x3s_platform",
  "theme-coco": "coco_platform",
  "theme-hermes": "hermes_platform",
  "theme-hermes-plus": "hermes_plus_platform",
  "theme-apollo": "apollo_platform",
  "theme-plum": "plum_platform",
  "theme-melon": "melon_platform",
  "theme-olive": "olive_platform",
  "theme-popcorn": "popcorn_platform",
  "theme-y03": "y03_platform",
  "theme-y07": "y07_platform",
  "theme-pear": "pear_platform",
  "theme-pineapple": "pineapple_platform",
  "theme-peach": "peach_platform",
  "theme-y09": "y09_platform",
  "theme-y09p": "y09p_platform",
  "theme-y11": "y11_platform",
  "theme-y08": "y08_platform",       // S7 Pro (Y08) 硬件映射项
  "theme-y06": "y06_platform",
  "theme-y05": "y05_platform",
  "theme-y02-1": "y02_1_platform"
};

function checkAddDesktopIcon(packageInfo) {
  const targetPlatformKey = platformMap[this.globalThemeName]; // 在 S7 Pro 上固定为 "y08_platform"
  if (!targetPlatformKey) {
    return true;
  }
  // 如果 packageInfo.props.addDesktop 中显式设置了目标平台为 false，则启动器直接剔除该图标
  if (packageInfo.props && packageInfo.props.addDesktop) {
    const isAllowed = packageInfo.props.addDesktop[targetPlatformKey];
    if (isAllowed !== undefined && !isAllowed) {
      return false; // 严禁显示在桌面上
    }
  }
  return true; // 允许显示在桌面卡片流中
}
```

### 3.3 桌面图标与标题解析规则
桌面启动器解析应用卡片资源的方法：
- **图标解析 (`getDesktopAppIcon`)**：
  ```javascript
  let iconRel = packageInfo.props && packageInfo.props.Icons && packageInfo.props.Icons[this.globalThemeName];
  if (!iconRel) {
    iconRel = packageInfo.icon; // 回退到根字段 icon
  }
  return "file://" + packageInfo.installPath + iconRel;
  ```
- **标题解析 (`getDesktopAppTitle`)**：
  ```javascript
  let title = packageInfo.props && packageInfo.props.AppTitle && packageInfo.props.AppTitle[this.globalThemeName];
  if (!title) {
    title = packageInfo.appName; // 回退到根字段 appName
  }
  return title;
  ```

**在 S7 Pro 主屏幕显示的必要条件**：
1. `manifest.json` 中必须具备 `"props": { "addDesktop": { "y08_platform": true } }`。
2. 确保 `icon` 指向应用包内的有效 PNG 图标文件（如 `"icon": "app_icon.png"`）。
3. 应用包必须通过 `manifest.json` 内的 `cert` 哈希校验，否则 Falcon 加载器在解压后会拒绝初始化。

---

## 4. 系统原生组件与事件体系规范（`/usr/lib/libfalcon.so`）

运行时原生组件由 `/usr/lib/libfalcon.so` 的 `JQuick::ComponentRegistry` 与 `_ZN3Vue12createElmApi` 注册。

### 4.1 支持的原生 UI 组件与属性列表

| 原生组件标签 | 底层 C++ 实现类 | 支持的关键属性 (Attributes) | 支持的特定方法 (Methods) | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `<div />` | `DivElmApi` / `greenui::View` | `style` (flex, width, height, background, border, etc.) | `setStyle()`, `clearTouchTargets()` | 基础弹性容器，无默认文本换行 |
| `<text />` | `TextElmApi` / `greenui::TextView` | `value`, `lines`, `text-overflow`, `font-size`, `font-weight`, `color`, `text-align` | `setText()` | 原生文本渲染节点，不支持子节点嵌套 |
| `<image />` | `ImageElmApi` / `greenui::ImageView`| `src` (`file://`, `http://`), `resize` (`cover`, `contain`, `stretch`) | `reload()` | 原生图片解码显示组件，带图片异步缓存池 |
| `<scroller />`| `ScrollerElmApi` / `greenui::ScrollView` | `scroll-direction` (`horizontal`, `vertical`), `show-scrollbar` | `scrollTo(x, y)`, `scrollLeft`, `scrollTop` | 原生滑动视图，超长内容视口容器 |
| `<slider />` | `SliderElmApi` / `greenui::SliderView` | `auto-play`, `interval`, `index`, `infinite` | `slideTo(index)` | 滑块容器（桌面启动器的左右滑块即此组件） |
| `<list />` | `ListElmApi` / `greenui::ListView` | `loadmoreoffset` | `resetLoadmore()` | 高性能虚拟化列表，仅循环渲染可见单元格 |
| `<cell />` | `CellElmApi` / `greenui::CellView` | 无 | 无 | 必须作为 `<list />` 的唯一直系子容器 |
| `<waterfall />`| `WaterfallElmApi` | `column-count`, `column-gap` | 无 | 瀑布流自适应布局容器 |
| `<input />` | `InputElmApi` / `greenui::EditView` | `type` (`text`, `number`, `password`), `value`, `placeholder`, `maxlength` | `focus()`, `blur()`, `setSelectionRange()` | 单行文本输入框，自动调起底层软键盘 |
| `<textarea />`| `TextareaElmApi` | `rows`, `value`, `placeholder`, `maxlength` | `focus()`, `blur()` | 多行文本输入框 |
| `<canvas />` | `CanvasElmApi` / `greenui::CanvasView` | `width`, `height` | `getContext("2d")` | 原生硬件加速 2D 绘图画布 |
| `<richtext />`| `RichtextElmApi` | `value` | 无 | 支持图文混排的富文本显示控件 |

### 4.2 原生支持的样式与布局系统
Falcon 实现了基于 Flexbox（类似 Facebook Yoga 引擎）的纯原生布局：
- **布局属性**：`display: flex`、`flex-direction: row | column`、`justify-content: flex-start | center | flex-end | space-between | space-around`、`align-items: flex-start | center | flex-end | stretch`、`flex: <number>`。
- **定位属性**：`position: relative | absolute`、`top`, `left`, `right`, `bottom`。
- **盒模型**：`width`, `height`, `min-width`, `min-height`, `margin`, `padding`, `border-width`, `border-color`, `border-radius`, `border-style`。
- **视觉样式**：`background-color` (支持 `#RRGGBB`、`#RRGGBBAA`、`rgb()`、`rgba()`)、`opacity` (0.0–1.0)。
- **字体排版**：`font-size`, `font-weight` (`normal`, `bold`, `100`~`900`), `color`, `text-align` (`left`, `center`, `right`), `lines` (限制最大行数), `text-overflow: ellipsis`。
- **重要限制**：
  - 词典笔屏幕物理分辨率为 1020 × 240（系统逆时针旋转 270 度排版），设计稿基准逻辑宽度必须为 1020px，高度必须为 240px。
  - 不支持 CSS 伪类（`:hover`, `:active`），样式变化需通过 Vue 数据绑定 `:class` 或 `:style` 实现。

### 4.3 原生事件与手势模型
所有原生组件统一派发以下 DOM 事件：
- **点击与触摸事件**：`click`, `touchstart`, `touchmove`, `touchend`, `touchcancel`。
- **滚动专用事件**：`scroll`（携带当前 `contentOffset` 坐标）、`scrollstart`、`scrollend`。
- **表单输入事件**：`input`（携带输入字符）、`change`、`focus`、`blur`、`return`。
- **底层拦截控制**：
  - `disallowInterceptTouch(bool)`：阻止外层 `scroller` 或 `slider` 拦截当前组件的触摸事件。
  - `clearTouchTargets()`：立即释放当前手指的触控事件派发链。

---

## 5. QuickJS 编译与打包规范

### 5.1 QuickJS 字节码编译规范
宿主 MiniApp 容器只加载 `.js.bin` 二进制字节码，不加载纯文本 `.js`。
1. **编译器要求**：必须使用 QuickJS 2020-07-05 版本的定制编译器，使用仓库内的 `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/qjsc`。
2. **编译参数**：
   - 必须启用 ES 模块标志 `-m`。
   - 必须通过 `-c` 输出 C 结构体数组，再解析提取出纯字节码二进制流。
   - 转换脚本见 `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/compile_js_bin.py`：
     ```bash
     python3 host_tools/compile_js_bin.py input.js output.js.bin --module
     ```
3. **字节码有效性检查**：
   编译生成的 `.js.bin` 文件第 1 个字节必须是 `0x3f`（十六进制，十进制 63）。若首字节不是 `0x3f`，Falcon 运行库会报错 `Invalid bytecode signature`。

### 5.2 `manifest.json` 规范定义
`manifest.json` 必须位于应用包根目录。以下为完全符合 S7 Pro 规范的模板：

```json
{
  "appName": "自研原生应用",
  "version": "1.0.0",
  "appid": "8888000288880002",
  "icon": "app_icon.png",
  "quickjs": {
    "version": "20200705",
    "bigNum": false
  },
  "meta": {
    "otaVersion": "1.0.0"
  },
  "props": {
    "supportUnInstall": true,
    "addDesktop": {
      "y08_platform": true
    },
    "AppTitle": {
      "theme-y08": "自研原生应用"
    },
    "Icons": {
      "theme-y08": "app_icon.png"
    }
  },
  "cert": {
    "app.js.bin": {
      "size": 1248,
      "md5": "0123456789abcdef0123456789abcdef"
    },
    "index.js.bin": {
      "size": 5678,
      "md5": "abcdef0123456789abcdef0123456789"
    }
  }
}
```

### 5.3 `cert` 完整性校验哈希表生成规范
Falcon 引擎在加载应用前，会逐一核对 `cert` 字典中列出的所有 `.js.bin` 文件的精确字节大小（`size`）与 32 位小写 MD5（`md5`）。任何字节偏差都会导致容器拒绝加载应用。

Python 自动计算 `cert` 代码范式：
```python
import hashlib
import json
import os

def update_manifest_cert(pkg_dir):
    manifest_path = os.path.join(pkg_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cert_table = {}
    for root, _, files in os.walk(pkg_dir):
        for file in files:
            if file.endswith(".js.bin"):
                rel_path = os.path.relpath(os.path.join(root, file), pkg_dir)
                full_path = os.path.join(root, file)
                size = os.path.getsize(full_path)
                with open(full_path, "rb") as bf:
                    md5_hash = hashlib.md5(bf.read()).hexdigest()
                cert_table[rel_path] = {"size": size, "md5": md5_hash}

    manifest["cert"] = cert_table
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
```

### 5.4 `.amr` 应用包生成规范
- `.amr` 文件是标准的 ZIP 压缩归档格式（等同于 `.zip` 重命名）。
- **打包边界**：`manifest.json`、`app_icon.png`、`app.js.bin` 等文件必须直接置于压缩包根目录，严禁在外层包裹一层父级目录。

---

## 6. 原生 MiniApp 前端工程脚手架（生产可用标准）

本节提供一套无需复杂 Webpack 工具链即可直接构建、能在 S7 Pro 主屏幕（1020x240）显示的极简原生应用生产脚手架。

### 6.1 目录结构
```
my_native_app/
├── manifest.json
├── app_icon.png
├── app.js               # 编译前的 JS 源码
├── index.js             # 编译前的主视图 JS 源码
├── app.js.bin           # 编译后的 QuickJS 模块字节码
└── index.js.bin         # 编译后的 QuickJS 模块字节码
```

### 6.2 应用全局入口：`app.js`
```javascript
// app.js - 官方原生 MiniApp 应用入口
export default {
  onLaunch(options) {
    console.log("[MyNativeApp] Application Launched with options:", JSON.stringify(options));
  },
  onShow() {
    console.log("[MyNativeApp] Application Foreground Visible");
  },
  onHide() {
    console.log("[MyNativeApp] Application Background Hidden");
  },
  onDestroy() {
    console.log("[MyNativeApp] Application Destroyed");
  }
};
```

### 6.3 主视图渲染入口：`index.js`
利用 Falcon 原生实现的 Vue `_c` 创建元素语法，构建一个适配 1020x240 横屏的主界面，包含顶栏、横向滑动列表卡片与交互按钮：

```javascript
// index.js - 适配 1020x240 物理屏幕的原生视图定义
export default {
  data() {
    return {
      appName: "自研原生应用",
      statusText: "系统运行正常",
      counter: 0,
      cardList: [
        { id: 1, title: "系统监控", desc: "CPU: CV1813 / RAM: 128MB" },
        { id: 2, title: "硬件信息", desc: "屏幕: 1020x240 IPS" },
        { id: 3, title: "网络状态", desc: "Wi-Fi: 已连接 (192.168.2.2)" },
        { id: 4, title: "存储空间", desc: "/userdisk: 正常读写" }
      ]
    };
  },
  methods: {
    handleBtnClick() {
      this.counter++;
      this.statusText = "已触发原生点击 " + this.counter + " 次";
      console.log("[MyNativeApp] Button clicked, current count:", this.counter);
    },
    handleCardClick(item) {
      this.statusText = "选中卡片: " + item.title;
      console.log("[MyNativeApp] Card selected:", item.title);
    }
  },
  render(h) {
    const _vm = this;
    const _c = _vm._self._c || h;

    return _c("div", {
      staticStyle: {
        width: "1020px",
        height: "240px",
        backgroundColor: "#121212",
        flexDirection: "column",
        overflow: "hidden"
      }
    }, [
      // 1. 顶部状态栏
      _c("div", {
        staticStyle: {
          width: "1020px",
          height: "44px",
          backgroundColor: "#1f1f1f",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingLeft: "24px",
          paddingRight: "24px"
        }
      }, [
        _c("text", {
          staticStyle: {
            color: "#ffffff",
            fontSize: "20px",
            fontWeight: "bold"
          },
          attrs: { value: _vm.appName }
        }),
        _c("text", {
          staticStyle: {
            color: "#00e676",
            fontSize: "16px"
          },
          attrs: { value: _vm.statusText }
        })
      ]),

      // 2. 主内容区：左侧控制按钮 + 右侧横向滚动卡片
      _c("div", {
        staticStyle: {
          width: "1020px",
          height: "196px",
          flexDirection: "row",
          alignItems: "center",
          paddingLeft: "24px",
          paddingRight: "24px"
        }
      }, [
        // 左侧互动操作按钮
        _c("div", {
          staticStyle: {
            width: "180px",
            height: "140px",
            backgroundColor: "#2979ff",
            borderRadius: "16px",
            justifyContent: "center",
            alignItems: "center",
            marginRight: "20px"
          },
          on: {
            click: _vm.handleBtnClick
          }
        }, [
          _c("text", {
            staticStyle: {
              color: "#ffffff",
              fontSize: "20px",
              fontWeight: "bold"
            },
            attrs: { value: "点击测试" }
          }),
          _c("text", {
            staticStyle: {
              color: "#bbdefb",
              fontSize: "14px",
              marginTop: "8px"
            },
            attrs: { value: "计数值: " + _vm.counter }
          })
        ]),

        // 右侧水平原生滑动容器 (scroller)
        _c("scroller", {
          staticStyle: {
            width: "772px",
            height: "140px",
            flexDirection: "row"
          },
          attrs: {
            "scroll-direction": "horizontal",
            "show-scrollbar": false
          }
        }, _vm.cardList.map(function(item) {
          return _c("div", {
            key: item.id,
            staticStyle: {
              width: "220px",
              height: "140px",
              backgroundColor: "#242424",
              borderRadius: "16px",
              padding: "16px",
              marginRight: "16px",
              flexDirection: "column",
              justifyContent: "space-between"
            },
            on: {
              click: function() {
                _vm.handleCardClick(item);
              }
            }
          }, [
            _c("text", {
              staticStyle: {
                color: "#ffab00",
                fontSize: "18px",
                fontWeight: "bold"
              },
              attrs: { value: item.title }
            }),
            _c("text", {
              staticStyle: {
                color: "#e0e0e0",
                fontSize: "14px",
                lines: 2,
                textOverflow: "ellipsis"
              },
              attrs: { value: item.desc }
            })
          ]);
        }))
      ])
    ]);
  }
};
```

### 6.4 自动化构建与打包发布脚本：`build_app.py`
创建脚本执行编译字节码、计算 `cert` MD5、打包 `.amr` 并通过 SSH 安装到设备的完整自动化链路：

```python
#!/usr/bin/env python3
import hashlib
import json
import os
import shutil
import subprocess
import zipfile

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
QJSC_PATH = "/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/qjsc"
COMPILE_TOOL = "/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/compile_js_bin.py"
PEN_SSH = "/tmp/pen_ssh"

APP_ID = "8888000288880002"
AMR_NAME = f"{APP_ID}.amr"
OUTPUT_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_PKG_DIR = os.path.join(OUTPUT_DIR, "pkg")

def build():
    # 1. 准备目录
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(BUILD_PKG_DIR, exist_ok=True)

    # 2. 编译 JS 为 QuickJS 字节码 (.js.bin)
    src_files = ["app.js", "index.js"]
    for src in src_files:
        src_path = os.path.join(PROJECT_DIR, src)
        bin_path = os.path.join(BUILD_PKG_DIR, src + ".bin")
        cmd = ["python3", COMPILE_TOOL, src_path, bin_path, "--module"]
        print(f"[*] 编译字节码: {src} -> {src}.bin")
        subprocess.run(cmd, check=True)

    # 3. 复制图标与基础清单
    shutil.copy(os.path.join(PROJECT_DIR, "app_icon.png"), os.path.join(BUILD_PKG_DIR, "app_icon.png"))

    manifest = {
        "appName": "自研原生应用",
        "version": "1.0.0",
        "appid": APP_ID,
        "icon": "app_icon.png",
        "quickjs": {
            "version": "20200705",
            "bigNum": False
        },
        "meta": {
            "otaVersion": "1.0.0"
        },
        "props": {
            "supportUnInstall": True,
            "addDesktop": {
                "y08_platform": True
            },
            "AppTitle": {
                "theme-y08": "自研原生应用"
            },
            "Icons": {
                "theme-y08": "app_icon.png"
            }
        },
        "cert": {}
    }

    # 4. 计算 cert 表
    for file in os.listdir(BUILD_PKG_DIR):
        if file.endswith(".js.bin"):
            f_path = os.path.join(BUILD_PKG_DIR, file)
            size = os.path.getsize(f_path)
            with open(f_path, "rb") as bf:
                md5_val = hashlib.md5(bf.read()).hexdigest()
            manifest["cert"][file] = {
                "size": size,
                "md5": md5_val
            }

    with open(os.path.join(BUILD_PKG_DIR, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # 5. 打包为 .amr (标准 zip)
    amr_path = os.path.join(OUTPUT_DIR, AMR_NAME)
    with zipfile.ZipFile(amr_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(BUILD_PKG_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BUILD_PKG_DIR)
                zipf.write(full_path, rel_path)
    print(f"[+] 应用包生成成功: {amr_path}")

    # 6. 推送到设备并安装
    print("[*] 正在传输并安装到有道词典笔 S7 Pro...")
    remote_tmp = f"/tmp/{AMR_NAME}"
    subprocess.run(["scp", "-i", os.path.expanduser("~/.ssh/id_ed25519"), "-o", "StrictHostKeyChecking=no", amr_path, f"root@192.168.2.2:{remote_tmp}"], check=True)
    subprocess.run([PEN_SSH, f"/usr/bin/miniapp_cli install {remote_tmp}"], check=True)
    print("[+] 应用安装完毕！主屏幕桌面卡片已成功载入该应用。")

if __name__ == "__main__":
    build()
```

---

## 7. 必须掌握的核心文件清单

以下文件是深入理解与维护 S7 Pro 原生 MiniApp 前端体系的绝对关键文件：

| 绝对路径 | 作用与职责 |
| :--- | :--- |
| `/usr/lib/libfalcon.so` | 系统的 C++ 原生渲染引擎核心库，包含 `JQuick::ComponentRegistry`、`greenui::View` 视图类、`Vue::createElmApi` 桥接层与 QuickJS C++ 原生绑定。 |
| `/etc/miniapp/resources/cfg.json` | 系统级屏幕旋转与设备画布配置（定义了 240x1020 物理屏逆时针 270 度旋转为 1020x240 逻辑屏）。 |
| `/oem/secondary/etc/miniapp/resources/local_packages.json` | 官方预装服务包与应用包注册清单，记录所有 App ID、类别与预置路径。 |
| `/userdisk/secondary/miniapp/data/mini_app/pkg/8080222437664451/a/indexPage-085a554f.js.bin` | 桌面启动器 Launcher 的主逻辑，包含控制应用是否在桌面显示的 `checkAddDesktopIcon` 过滤算法。 |
| `/userdisk/secondary/miniapp/data/mini_app/pkg/8001661310449825/a/manifest.json` | 百度网盘官方应用的元数据声明与完整 `cert` 校验表示例。 |
| `/userdisk/secondary/miniapp/data/mini_app/pkg/8001666679481944/a/InputPage-38d8bb4d.js.bin` | 官方输入法主面板字节码，包含完整的 Vue 2.x `render(h)` 原生组件调用链路。 |
| `/usr/bin/miniapp_cli` | 系统应用容器进程管理 CLI，支持 `install`、`uninstall`、`start`、`capture`（截屏）等调试操作。 |
| `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/qjsc` | QuickJS 2020-07-05 原生字节码编译工具（可执行二进制）。 |
| `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/compile_js_bin.py` | 主机端将 JavaScript 脚本编译为 `.js.bin` 模块字节码的自动化 Python 封装。 |