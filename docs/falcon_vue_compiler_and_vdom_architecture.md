# Falcon Vue SFC 编译器、Virtual DOM 与 QuickJS 字节码架构手册
## (Falcon Vue 2.6 NVue Compiler, AST Transformations & QuickJS Bytecode Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **前端内核**: Alibaba Weex NVue (Native Vue 2.6.12 生产环境模式)  
> **底层执行**: QuickJS 2020-07-05 (`BC_VERSION = 1`, `libquickjs.so`) + GreenUI C++ View Tree  
> **配套工具**: `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/falcon_vue_compiler.js` / `compile_js_bin.py`

---

## 目录索引

1. [Falcon 前端运行时架构与 Weex NVue 本质](#1-falcon-前端运行时架构与-weex-nvue-本质)
2. [Vue 组件对象属性契约与 VNode 生成规范](#2-vue-组件对象属性契约与-vnode-生成规范)
   - 2.1 [组件对象属性规范 (`_withStripped`, `style`, `themes`)](#21-组件对象属性规范)
   - 2.2 [VNode 生成规范与 `staticClass` 数组化底层真相](#22-vnode-生成规范与-staticclass-数组化底层真相)
3. [官方构建流水线反向工程与两阶段编译](#3-官方构建流水线反向工程与两阶段编译)
   - 3.1 [`vue-template-compiler` 定制 AST 转换插件](#31-vue-template-compiler-定制-ast-转换插件)
   - 3.2 [`weex-styler` 样式预处理器与简写展开](#32-weex-styler-样式预处理器与简写展开)
   - 3.3 [页面注册双架构：直接导出与 `$falcon.Page` 继承](#33-页面注册双架构直接导出与-falconpage-继承)
4. [独立本地编译工具链使用指南 (`falcon_vue_compiler`)](#4-独立本地编译工具链使用指南)
   - 4.1 [工具链架构拓扑](#41-工具链架构拓扑)
   - 4.2 [CLI 命令行调用与参数详解](#42-cli-命令行调用与参数详解)
5. [生产级代码样例：原生全特性组件与页面](#5-生产级代码样例原生全特性组件与页面)

---

## 1. Falcon 前端运行时架构与 Weex NVue 本质

通过反编译 `libquickjs.so` 与提取官方微应用字节码，证实有道 S7 Pro 词典笔的 MiniApp 框架并非传统 Webview 渲染，而是**深度定制的阿里巴巴 Weex NVue (Native Vue) 2.6.12 架构**：

```
                    .vue 单文件组件 (SFC)
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
          <template>                     <style>
       AST 转换与类名数组化        weex-styler 预编译
       _withStripped 严格模式     CSS 展开为嵌套 JSON 字典
                │                           │
                └─────────────┬─────────────┘
                              ▼
                  合并生成 ESM JavaScript 源码
                              │
                  qjsc -m (QuickJS 2020-07-05)
                              │
                              ▼
                   .js.bin (原生模块字节码)
                              │ (部署至词典笔)
                              ▼
                  libquickjs.so 执行虚拟机
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
         _c() VNode 虚拟树          component.style
                │                           │
                └─────────────┬─────────────┘
                              ▼
            libfalcon.so 原生 C++ 组件反射与 Yoga 排版
                              │
                              ▼
                     Skia 2D 硬件光栅化直绘
```

- **JavaScript 引擎**: QuickJS 2020-07-05 版本，固定 Atom 偏移截断（Predefined Atoms = 209）。
- **C++ 原生视图反射**: Falcon 的 C++ 组件（`_DivView`、`_TextView`、`_ScrollerView`）直接监听 VNode 变更。

---

## 2. Vue 组件对象属性契约与 VNode 生成规范

### 2.1 组件对象属性规范

编译后的 Vue 组件在运行时导出时必须携带如下关键属性，否则 Falcon 无法挂载：

| 属性名 | 类型 | 严格取值 | 作用与系统底层约束 |
| :--- | :--- | :--- | :--- |
| `_withStripped` | `boolean` | `true` (`!0`) | **强制开启**。声明渲染函数已去除 `with(this)` 包装，适配严格模式与 QuickJS ESM 模块 |
| `render` | `Function` | `function() { ... }` | 编译后的 VNode 根节点生成函数 |
| `staticRenderFns`| `Array` | `[]` | 静态子树渲染缓存函数数组 |
| `_compiled` | `boolean` | `true` (`!0`) | 告知 Vue 运行时该组件模板已被预编译，无需在端侧动态解析 |
| `_scopeId` | `string` | `"data-v-xxxxxx"` | 作用域样式唯一哈希隔离标识符 |
| `style` | `Object` | `{ greeting: { ... } }` | 由 `<style>` 预编译转换后的 JSON 样式字典，供 C++ 布局引擎直读 |
| `themes` | `Object` | `{}` | 预留的多主题/高对比度色彩覆写映射表 |
| `__file` | `string` | `"src/xxx.vue"` | 调试路径元数据 |

---

### 2.2 VNode 生成规范与 `staticClass` 数组化底层真相

#### 核心断层：Web Vue 与 Falcon Native Vue 的 `staticClass` 差异

在标准 Web 版 Vue 中，静态类名被序列化为字符串：
```javascript
// Web Vue 编译结果 (在 Falcon 运行时报错无法加载样式)
_c("text", { staticClass: "btn primary" }, [_vm._v("确定")])
```

在 Falcon (Weex NVue) 架构中，静态类名**必须被编译为字符串数组（Array of Strings）**：
```javascript
// Falcon Native Vue 官方严格标准 (100% 匹配 libfalcon.so)
_c("text", { staticClass: ["btn", "primary"] }, [_vm._v("确定")])
```

#### 为什么必须是字符串数组？
1. **零开销样式遍历**：Falcon 的 C++ 原生排版引擎在创建 `greenui::View` 时，无需在内存中运行复杂的 CSS 选择器计算引擎或正则表达式拆解类名。
2. **直接字典寻址**：引擎直接遍历 `staticClass` 数组的每一个元素（如 `"btn"`），在组件导出的 `component.style["btn"]` 中进行 $O(1)$ 的哈希查找，快速将 `fontSize`、`color` 等属性注入 Yoga Flexbox 布局节点与 Skia 画笔。

---

## 3. 官方构建流水线反向工程与两阶段编译

### 3.1 `vue-template-compiler` 定制 AST 转换插件

为了在 Node.js 环境下生成与官方完全一致的 VNode 字节码，必须配置 `vue-template-compiler` (2.6.12) 并注入自定义 AST 模块：

```javascript
const compiler = require('vue-template-compiler');
const transpile = require('vue-template-es2015-compiler');

const falconClassModule = {
  transformNode(el) {
    if (el.attrsMap && el.attrsMap.class) {
      // 提取 class 属性并切分为数组
      const classes = el.attrsMap.class.trim().split(/\s+/).filter(Boolean);
      // 关键：将 staticClass 序列化为 JSON 数组字符串，例如 '["btn", "primary"]'
      el.staticClass = JSON.stringify(classes);
    }
  }
};

const compiled = compiler.compile(templateCode, {
  modules: [falconClassModule],
  preserveWhitespace: false
});

// 使用 vue-template-es2015-compiler 剔除 with(this)
const renderFn = transpile(`function render() { ${compiled.render} }`, {
  transforms: { stripWith: true }
});
```

---

### 3.2 `weex-styler` 样式预处理器与简写展开

Falcon 不支持在运行时解析 CSS 文件，所有的 `<style>` 必须由构建工具转换为原生字典。
样式转换核心规范：
1. **属性驼峰化**：`background-color` $\rightarrow$ `backgroundColor`，`font-size` $\rightarrow$ `fontSize`。
2. **四向简写展开（Shorthand Expansion）**：
   - `margin: 10px;` 必须展开为：
     ```json
     { "marginTop": "10px", "marginRight": "10px", "marginBottom": "10px", "marginLeft": "10px" }
     ```
   - `padding: 0 20px;` 必须展开为：
     ```json
     { "paddingTop": 0, "paddingRight": "20px", "paddingBottom": 0, "paddingLeft": "20px" }
     ```
3. **注入组件对象**：
   ```javascript
   component.style = Object.assign({}, {}, jsonStyle);
   ```

---

### 3.3 页面注册双架构：直接导出与 `$falcon.Page` 继承

Falcon 运行时支持两种页面导出模式：

#### 范式 A：直接导出组件对象 (Direct Component Export)
适用于无复杂原生页面生命周期拦截的普通页面（如子页面、设置项页）：
```javascript
export default component;
```
运行时在加载模块时，自动为其套上默认的 Native BasePage 壳。

#### 范式 B：显式继承 `$falcon.Page` 类 (Explicit Subclassing)
适用于主页面、启动入口页以及需要深度监听系统事件（如物理键、新路由传参、全屏手势开关）的高级页面：
```javascript
class IndexPage extends $falcon.Page {
  onLoad(options) {
    super.onLoad(options);
    // 关键门禁：必须在此处将根组件注入 Native 视图树！
    this.setRootComponent(component);
  }
  onNewOptions(options) {
    super.onNewOptions(options);
  }
  onShow() {
    super.onShow();
  }
  onHide() {
    super.onHide();
  }
  onUnload() {
    super.onUnload();
  }
}
export default IndexPage;
```

---

## 4. 独立本地编译工具链使用指南 (`falcon_vue_compiler`)

我们已在工程中逆向实现了完整的单文件编译器，位于 `/Users/daniel/youdao-dictpen-s7pro-guide/host_tools/`：

### 4.1 工具链架构拓扑

```
[MyPage.vue] 
      │
      ▼ (python3 falcon_vue_compiler.py)
[falcon_vue_compiler.js]
      ├── 1. 提取 <template> -> vue-template-compiler (classModule 数组化) -> stripWith
      ├── 2. 提取 <style> -> weex-styler (4向展开为 JSON)
      ├── 3. 提取 <script> -> 合并组件元数据与 $falcon.Page 壳
      └── 4. 输出 intermediate.js
      │
      ▼
[compile_js_bin.py (qjsc -m)]
      │ (QuickJS 2020-07-05 编译)
      ▼
[MyPage.js.bin] (首字节为 0x01，符合 Falcon 运行时的二进制字节码)
```

### 4.2 CLI 命令行调用与参数详解

#### 1. 直接编译 `.vue` 为 QuickJS 字节码 (`.js.bin`)：
```bash
python3 /Users/daniel/youdao-dictpen-s7pro-guide/host_tools/falcon_vue_compiler.py MyPage.vue MyPage.js.bin
```

#### 2. 以 `$falcon.Page` 页面包装模式编译入口主页面：
```bash
python3 /Users/daniel/youdao-dictpen-s7pro-guide/host_tools/falcon_vue_compiler.py Index.vue index.js.bin --page
```

#### 3. 仅输出转译后的纯 ES6 JavaScript 源码以便审查代码：
```bash
python3 /Users/daniel/youdao-dictpen-s7pro-guide/host_tools/falcon_vue_compiler.py MyPage.vue output.js --js-only
```

#### 4. 对生成的 `.js.bin` 执行反汇编校验：
```bash
python3 /Users/daniel/youdao-dictpen-s7pro-guide/host_tools/qjs_disasm.py MyPage.js.bin
```

---

## 5. 生产级代码样例：原生全特性组件与页面

以下为 100% 兼容 Falcon 编译器的完整生产级单文件组件示例：

```html
<template>
  <div class="wrapper">
    <div class="header">
      <text class="title">{{ pageTitle }}</text>
      <text class="subtitle">Vue 2.6 Native Weex on CV1813H</text>
    </div>

    <scroller class="content-scroll" scroll-direction="horizontal">
      <div v-for="(item, index) in cardList" :key="index" class="card-item" @click="handleCardClick(item)">
        <text class="card-title">{{ item.name }}</text>
        <text class="card-desc">{{ item.desc }}</text>
      </div>
    </scroller>

    <div class="footer">
      <div class="btn primary" @click="handleAction">
        <text class="btn-text">确定执行</text>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      pageTitle: "Native Falcon SFC",
      cardList: [
        { name: "高性能", desc: "60FPS 硬件渲染" },
        { name: "低功耗", desc: "1.0GHz 锁定低发热" },
        { name: "双列流", desc: "极致带鱼屏体验" }
      ]
    };
  },
  mounted() {
    console.log("[SFC] Native Component Mounted");
  },
  methods: {
    handleCardClick(item) {
      console.log("[SFC] Clicked card:", item.name);
    },
    handleAction() {
      if (this.$page && this.$page.finish) {
        this.$page.finish();
      }
    }
  }
};
</script>

<style scoped>
.wrapper {
  width: 1020px;
  height: 240px;
  background-color: #121418;
  flex-direction: column;
  padding: 8px 16px;
}
.header {
  height: 36px;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}
.title {
  color: #00E676;
  font-size: 18px;
  font-weight: bold;
}
.subtitle {
  color: #90A4AE;
  font-size: 12px;
}
.content-scroll {
  width: 988px;
  height: 120px;
  flex-direction: row;
  margin-top: 8px;
}
.card-item {
  width: 220px;
  height: 110px;
  background-color: #1E222B;
  border-radius: 8px;
  margin-right: 12px;
  padding: 12px;
  justify-content: center;
}
.card-title {
  color: #40C4FF;
  font-size: 16px;
  font-weight: bold;
}
.card-desc {
  color: #78909C;
  font-size: 12px;
  margin-top: 6px;
}
.footer {
  height: 48px;
  justify-content: center;
  align-items: flex-end;
}
.btn {
  width: 120px;
  height: 32px;
  border-radius: 6px;
  background-color: #00E676;
  justify-content: center;
  align-items: center;
}
.btn-text {
  color: #121418;
  font-size: 14px;
  font-weight: bold;
}
</style>
```
