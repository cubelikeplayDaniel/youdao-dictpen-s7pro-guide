# 有道词典笔 S7 Pro 虚拟键盘、输入法（IME）与软输入面板（SIP）运行时逆向工程深度分析报告
## (Falcon Virtual Keyboard, System IME Panel, InputConnection SPI & 1020x240 Viewport Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Linux 5.10.4)  
> **核心组件**: `im::FalconIMPanel` (Layer 10200), `greenui::InputConnection`, `im::FalconIMApp` (`8001666679481944`), QuickJS `"im"` C-Module, `InputElmApi`

---

## 目录索引

1. [系统架构总览与核心组件拓扑](#1-系统架构总览与核心组件拓扑)
2. [核心 C++ 类结构、内存布局与逆向反汇编](#2-核心-c-类结构内存布局与逆向反汇编)
   - 2.1 [`im::FalconIMPanel`（虚拟键盘宿主窗口）](#21-imfalconimpanel虚拟键盘宿主窗口)
   - 2.2 [`greenui::EditText` 与 `greenui::Textarea`（输入控件实体）](#22-greenuiedittext-与-greenuitextarea输入控件实体)
   - 2.3 [QuickJS 原生 C-Module `"im"`](#23-quickjs-原生-c-module-im)
   - 2.4 [DOM 前端桥接：`InputElmApi`](#24-dom-前端桥接inputelmapi)
3. [虚拟键盘在 1020 × 240 屏幕上的唤醒、布局与几何定位](#3-虚拟键盘在-1020--240-屏幕上的唤醒布局与几何定位)
   - 3.1 [物理尺寸约束与双窗口叠加模型](#31-物理尺寸约束与双窗口叠加模型)
   - 3.2 [非阻塞透明区域触控穿透机制（Hit-Testing）](#32-非阻塞透明区域触控穿透机制hit-testing)
4. [IME 完整事件分发链与输入引擎交互](#4-ime-完整事件分发链与输入引擎交互)
   - 4.1 [拼音检索与候选词上屏链路（Trie 树加速）](#41-拼音检索与候选词上屏链路trie-树加速)
   - 4.2 [连续退格与长按阶梯加速算法](#42-连续退格与长按阶梯加速算法)
   - 4.3 [文本光学导入机制 (OCR 扫描替代键盘)](#43-文本光学导入机制-ocr-扫描替代键盘)
   - 4.4 [完成/确认与后退物理键拦截](#44-完成确认与后退物理键拦截)
5. [焦点生命周期、选择区控制与 WindowManager Z-Order 仲裁](#5-焦点生命周期选择区控制与-windowmanager-z-order-仲裁)
   - 5.1 [WindowManager 全局 Z-Order 深度分布](#51-windowmanager-全局-z-order-深度分布)
   - 5.2 [焦点流转与属性约束状态机](#52-焦点流转与属性约束状态机)
6. [生产级高可用 JavaScript / Vue 工程实现方案](#6-生产级高可用-javascript--vue-工程实现方案)
   - 6.1 [方案 1：全功能防遮挡表单页面 (`CustomInputPage.vue`)](#61-方案-1全功能防遮挡表单页面-custominputpagevue)
   - 6.2 [方案 2：基于 `softInputEnable: false` 的轻量级 PIN 码键盘 (`SecurePinInput.vue`)](#62-方案-2基于-softinputenable-false-的轻量级-pin-码键盘-securepininputvue)
   - 6.3 [方案 3：底层原生 `InputElmApi` 控制器 (`IMEController.js`)](#63-方案-3底层原生-inputelmapi-控制器-imecontrollerjs)
7. [逆向结论与开发关键准则](#7-逆向结论与开发关键准则)

---

## 1. 系统架构总览与核心组件拓扑

在网易有道词典笔 S7 Pro 上，输入法子系统采用**双窗口隔离架构**：应用程序视图树与虚拟键盘渲染树完全隔离，由 Falcon `WindowManager` 在底层进行 Z-Order 仲裁、触控穿透调度与 C++ `InputConnection` 管道通信。

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   WindowManager 图层栈与事件流                                    │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Layer 10200 / 0x27d8] im::FalconIMPanel (全屏 1020x240 容器, 可视键盘区位于底部 240-H ~ 240)    │
│  ├─ 宿主: im::FalconIMApp (系统小程序, AppID: 8001666679481944, category: "IM_PANEL_DICT")       │
│  ├─ 命中测试: Y < 240 - H (透明区) ──自动穿透转发──> WindowManager::getWindowBehind(this)        │
│  └─ 按键动作: QuickJS "im" C-Module (append, delete, clear, confirm, searchWord)                 │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                ▲ C++ InputConnection SPI 通信管道                 │
│                                                ▼ (commitText / popBack / onInputHeight / blur)    │
├──────────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Layer 0 ~ 100]        应用程序顶层窗口 (FalconVWindow)                                           │
│  ├─ greenui::EditText / greenui::Textarea (+0x12c 实现 InputConnection 接口)                    │
│  ├─ 自动视口滚动补偿: bringToScreen(H) -> rootView->scrollTo(0, (viewBottom - (240 - H)))       │
│  └─ 前端 DOM 绑定: InputElmApi (focus(), unFocus(), inputMethod(), softInputEnable)              │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 核心 C++ 类结构、内存布局与逆向反汇编

### 2.1 `im::FalconIMPanel`（虚拟键盘宿主窗口）
`FalconIMPanel` 继承自 `greenui::NWindow` / `FalconVWindow`，是承载整个输入法前端页面的独立系统顶层窗口。

#### 内存关键字段偏移：
- `[this + 0x28]` (`uint32_t`): 窗口 Z-Order 层级，硬编码为 `0x27d8`（十进制 **10200**）。
- `[this + 0x2c]` (`uint32_t`): 窗口特性标志位，`OR 0x01`（系统级常驻窗口，不参与常规页面切换）。
- `[this + 0xdc]` (`greenui::InputConnection*`): 当前处于活跃编辑态的输入连接指针。
- `[this + 0xe0]` (`int`): 当前软键盘高度 `panelHeight`（默认 0，激活时上报为 160 ~ 180px）。
- `[this + 0xe4]` (`uint8_t`): 命中状态标志（`0`: 落在键盘区；`1`: 落在键盘上方透明区）。

#### 动态高度上报与级联通知 (`0x2b149c`)
当键盘 MiniApp 渲染完成并计算出自身高度后，调用 `im::FalconIMPanel::onInputHeight(int h)`：
- 取出当前激活的 `InputConnection*`，并调用其虚函数表中的 `onInputHeight(int)` 级联通知当前输入框 `EditText`。

---

### 2.2 `greenui::EditText` 与 `greenui::Textarea`（输入控件实体）
`greenui::EditText` 在**偏移 `+0x12c`**（十进制 300 字节）处多重继承了 `greenui::InputConnection` 纯虚接口。

#### `bringToScreen(int height)` 核心坐标防遮挡算法 (`0x434dfc`)
```arm
0x434e54:  bl       greenui::View::getLocationInWindow(greenui::PointF&) ; s17 = pt.y
0x434e60:  bl       greenui::View::getHeight() const                    ; s16 = inputHeight
0x434e70:  bl       greenui::View::getHeight() const                    ; r0 = 根窗口高度 (240px)
0x434e74:  sub      r0, r0, r5                                          ; r0 = 240 - keyboardHeight (可视底边界)
0x434e80:  vadd.f32 s16, s16, s17                                       ; s16 = pt.y + inputHeight (输入框下底坐标)
0x434e84:  vcmpe.f32 s16, s15                                           ; 比较 输入框底边界 与 可视底边界
0x434e8c:  ble      done                                                ; 若未被遮挡，直接返回
0x434ecc:  vsub.f32 s15, s16, s15                                       ; 计算遮挡高度 delta = bottom - visibleBottom
0x434ed8:  blx      r6                                                  ; 调用 rootView->scrollTo(0, delta)
```

---

### 2.3 QuickJS 原生 C-Module `"im"`

| 导出函数名 | 底层地址 | 参数 | 行为与底层 C++ 路由 |
| :--- | :--- | :--- | :--- |
| `append` | `0x2b2088` | `(str: string)` | 调用 `InputConnection::appendText` 注入字符 |
| `delete` | `0x2b1a64` | `()` | 调用 `InputConnection::popBack()` 退格单字符 |
| `clear` | `0x2b1a1c` | `()` | 调用 `InputConnection::commitText(0, 0)` 清空 |
| `confirm` | `0x2b19c8` | `()` | 调用 `InputConnection::commitComplete()` 解绑并隐藏键盘 |
| `searchWord` | `0x2b1dc8` | `(pinyin, cb)` | 调用嵌入式 `ime_pinyin::MatrixSearch::search` 查询候选词 |
| `supportChinese` | 变量 | `boolean` | 导出当前字库状态（判断 `/etc/.../dict_pinyin.dat` 是否存在） |

---

### 2.4 DOM 前端桥接：`InputElmApi`

| API 方法 | 作用描述 |
| :--- | :--- |
| `el.focus()` | 使控件获焦，若 `softInputEnable=true` 则拉起虚拟键盘 |
| `el.unFocus()` | 释放焦点，隐式触发 `hideSoftInput()` 并复位视口滚动 |
| `el.inputMethod(show, type)` | 手动强制显示 (`true`) 或隐藏 (`false`) 软键盘 |
| `el.getCursorPosition()` | 获取当前光标字符索引偏移（从 0 开始） |
| `el.setCursorPosition(pos)` | 设置当前光标定位 |
| `el.commitText(str)` | 代码直接向编辑器注入字符 |
| `el.popBack()` | 代码直接执行单字符退格 |
| `el.commitComplete()` | 代码模拟键盘按下 Enter/完成 |

---

## 3. 虚拟键盘在 1020 × 240 屏幕上的唤醒、布局与几何定位

### 3.1 物理尺寸约束与双窗口叠加模型
- 词典笔屏幕物理分辨率为 **1020 (W) × 240 (H)**，物理长宽比达到极端的 17:4。
- 全键盘 26 键布局采用两段式横向展开：
  - **顶部候选词条 (WordsPanel)**：高 **38px**，全宽横向滚动容器。
  - **底部按键区 (Keyboards)**：高 **132px**，三行排列（单键高 **40px - 42px**，行间距 **4px**）。
  - **总高度**：`panelHeight` 恒定为 **170px**。
  - **留白视口**：顶部仅保留 **70px**（`240 - 170 = 70px`）有效可见高度。

```
0px ─────────────────────────────────────────────────────────────────── 1020px
 │  [透明可穿透区 / 业务视口: 70px]                                      │
 │  业务应用输入框通过 bringToScreen(170) 滚动锁定在该区域 (Y: 10 ~ 60px)   │
70px ├───────────────────────────────────────────────────────────────────┤
 │  [候选词横向滚动条 WordsPanel: 38px] [当前拼音] [候选字 1] [候选字 2]... │
108px├───────────────────────────────────────────────────────────────────┤
 │  [全键盘/九宫格/符号面板: 132px]                                        │
 │  Row 1: [ Q ] [ W ] [ E ] [ R ] [ T ] [ Y ] [ U ] [ I ] [ O ] [ P ]  │
 │  Row 2: [ A ] [ S ] [ D ] [ F ] [ G ] [ H ] [ J ] [ K ] [ L ]        │
 │  Row 3: [Caps] [ Z ] [ X ] [ C ] [ V ] [ B ] [ N ] [ M ] [  Del  ]  │
240px└───────────────────────────────────────────────────────────────────┘
```

### 3.2 非阻塞透明区域触控穿透机制（Hit-Testing）
在 Falcon 框架中，`FalconIMPanel` 窗口的大小实际上是 **1020 × 240 全屏**。
在 `im::FalconIMPanel::dispatchTouchEvent` (`0x2b0d8c`) 中：
- 比较触控点 Y 坐标与 `240 - panelHeight`（即 70px）。
- 若 $Y < 70\text{px}$，判定落在透明区域，调用 `WindowManager::getWindowBehind(this)`，将事件无损穿透转发至下层业务应用窗口！
- **用户可以直接在键盘开启时点击顶部“保存”或“返回”，无需先行点击空白处关闭键盘。**

---

## 4. IME 完整事件分发链与输入引擎交互

### 4.1 拼音检索与候选词上屏链路（Trie 树加速）
- 前端输入拼音串，通过 `im.searchWord(pinyin, callback)` 触发 C++ `ime_pinyin::MatrixSearch`。
- 查询系统词库 `/etc/miniapp/resources/ime_res/lib/dict_pinyin.dat` 与用户词库 `/userdisk/secondary/miniapp/data/mini_app/user_dict.dat`。
- 用户选中候选词后调用 `im.append(text)`，直接写入 `InputConnection`。

### 4.2 连续退格与长按阶梯加速算法
- 首次轻触立即触发一次 `im.delete()`。
- 长按超过 400ms 启动循环加速定时器，间隔从 120ms 逐步递减至极限 40ms/字符。

### 4.3 文本光学导入机制 (OCR 扫描替代键盘)
- 词典笔支持提笔扫描录入：调起 `CameraManager`，识别后的结果通过 `el.commitText(scannedText)` 批量填入输入框。

### 4.4 完成/确认与后退物理键拦截
- 点击键盘“完成”调用 `im.confirm()`，解绑连接并触发 `@finishEdit`。
- 物理返回键由 `FalconIMPanel::handleBackPress()` 拦截，优先收起键盘，向外返回消费事件，**阻止业务页面退出**。

---

## 5. 焦点生命周期、选择区控制与 WindowManager Z-Order 仲裁

### 5.1 WindowManager 全局 Z-Order 深度分布

| 图层值 (Z-Order) | 16进制 | 对应窗口类 | 说明 |
| :--- | :--- | :--- | :--- |
| **0 ~ 100** | `0x0000 ~ 0x0064` | `FalconVWindow` | 业务应用主窗口（背单词、单词本、自研应用） |
| **10001** | `0x2711` | `falcon::SettingPanel` | 顶部状态栏与下拉全局控制中心 |
| **10200** | `0x27d8` | `im::FalconIMPanel` | **虚拟键盘与软输入法面板（系统最顶层）** |

---

## 6. 生产级高可用 JavaScript / Vue 工程实现方案

### 6.1 方案 1：全功能防遮挡表单页面 (`CustomInputPage.vue`)

```html
<template>
  <div class="page-container">
    <div class="header-bar">
      <div class="nav-btn" @click="handleBack">
        <text class="btn-text">返回</text>
      </div>
      <text class="header-title">{{ keyboardActive ? '编辑中...' : '系统表单' }}</text>
      <div class="nav-btn confirm" @click="handleSave">
        <text class="btn-text confirm-text">保存</text>
      </div>
    </div>

    <!-- 必须使用 scroller 作为外层容器以支撑 bringToScreen 平滑滚动 -->
    <scroller class="form-scroller" ref="mainScroller" :scrollable="true">
      <div class="form-body">
        <div class="input-card">
          <text class="field-label">设备名称</text>
          <input
            ref="inputName"
            class="native-input"
            type="text"
            v-model="formData.name"
            placeholder="请输入设备名称"
            placeholderColor="#666666"
            @focus="onFocus('inputName')"
            @blur="onBlur('inputName')"
            @finishEdit="onFinish"
          />
        </div>

        <div class="input-card">
          <text class="field-label">连接密码</text>
          <input
            ref="inputPassword"
            class="native-input"
            type="password"
            v-model="formData.password"
            placeholder="请输入密码"
            placeholderColor="#666666"
            @focus="onFocus('inputPassword')"
            @blur="onBlur('inputPassword')"
            @finishEdit="onFinish"
          />
        </div>

        <!-- 键盘垫块：防止最后一行控件被 170px 键盘遮挡无法上滑 -->
        <div class="scroll-pad" v-if="keyboardActive"></div>
      </div>
    </scroller>
  </div>
</template>

<script>
export default {
  data() {
    return {
      keyboardActive: false,
      activeField: null,
      formData: { name: "", password: "" }
    };
  },
  methods: {
    onFocus(field) {
      this.keyboardActive = true;
      this.activeField = field;
    },
    onBlur(field) {
      setTimeout(() => {
        if (this.activeField === field) {
          this.keyboardActive = false;
          this.activeField = null;
          this.resetScroll();
        }
      }, 50);
    },
    onFinish() {
      this.keyboardActive = false;
      this.activeField = null;
      this.resetScroll();
    },
    resetScroll() {
      if (this.$refs.mainScroller && this.$refs.mainScroller.scrollTo) {
        this.$refs.mainScroller.scrollTo(0, 0);
      }
    },
    handleBack() {
      if (this.keyboardActive && this.activeField) {
        const el = this.$refs[this.activeField];
        if (el && el.unFocus) el.unFocus();
        this.keyboardActive = false;
        return;
      }
      if (this.$router) this.$router.back();
    },
    handleSave() {
      if (this.activeField && this.$refs[this.activeField]) {
        this.$refs[this.activeField].unFocus();
      }
      console.log("[Form] Saved:", JSON.stringify(this.formData));
    }
  }
};
</script>

<style scoped>
.page-container {
  width: 1020px;
  height: 240px;
  background-color: #121316;
  flex-direction: column;
}
.header-bar {
  width: 1020px;
  height: 38px;
  background-color: #1A1B1F;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}
.header-title { color: #FFFFFF; font-size: 18px; }
.nav-btn {
  height: 28px;
  padding: 0 14px;
  background-color: #2D2E33;
  border-radius: 14px;
  justify-content: center;
  align-items: center;
}
.confirm { background-color: #008CFF; }
.btn-text { color: #FFFFFF; font-size: 14px; }
.confirm-text { color: #FFFFFF; font-weight: bold; }
.form-scroller { width: 1020px; height: 202px; }
.form-body { width: 1020px; padding: 10px 32px; }
.input-card {
  width: 956px;
  height: 60px;
  background-color: #1E2024;
  border-radius: 10px;
  margin-bottom: 10px;
  flex-direction: row;
  align-items: center;
  padding: 0 20px;
}
.field-label { width: 120px; color: #A8AAB3; font-size: 16px; }
.native-input {
  flex: 1;
  height: 40px;
  background-color: #141518;
  border-radius: 6px;
  color: #FFFFFF;
  font-size: 16px;
  padding: 0 12px;
}
.scroll-pad { width: 956px; height: 180px; }
</style>
```

---

### 6.2 方案 2：基于 `softInputEnable: false` 的轻量级 PIN 码键盘 (`SecurePinInput.vue`)

设置 `:softInputEnable="false"` 可以禁止拉起系统全键盘，直接在页面上内嵌高响应的数字网格：

```html
<template>
  <div class="pin-container">
    <div class="display-panel">
      <text class="title">输入解锁 PIN 码</text>
      <input
        ref="pinInputRef"
        class="hidden-input"
        type="password"
        v-model="pinValue"
        :maxLength="6"
        :softInputEnable="false"
      />
      <div class="dots-wrapper">
        <div v-for="i in 6" :key="i" class="dot" :class="{ 'filled': i <= pinValue.length }"></div>
      </div>
    </div>

    <div class="numpad-grid">
      <div class="num-row" v-for="(row, r) in keyRows" :key="r">
        <div v-for="btn in row" :key="btn.val" class="key-btn" :class="btn.type" @touchstart="onPress(btn)">
          <text class="key-text">{{ btn.text }}</text>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      pinValue: "",
      keyRows: [
        [
          { text: "1", val: "1", type: "num" },
          { text: "2", val: "2", type: "num" },
          { text: "3", val: "3", type: "num" },
          { text: "4", val: "4", type: "num" },
          { text: "5", val: "5", type: "num" }
        ],
        [
          { text: "6", val: "6", type: "num" },
          { text: "7", val: "7", type: "num" },
          { text: "8", val: "8", type: "num" },
          { text: "9", val: "9", type: "num" },
          { text: "0", val: "0", type: "num" }
        ],
        [
          { text: "清空", val: "CLR", type: "fn action-clear" },
          { text: "退格", val: "DEL", type: "fn action-del" },
          { text: "确认", val: "OK", type: "fn action-ok" }
        ]
      ]
    };
  },
  methods: {
    onPress(btn) {
      const el = this.$refs.pinInputRef;
      if (btn.val === "CLR") {
        this.pinValue = "";
        if (el && el.commitText) el.commitText("");
      } else if (btn.val === "DEL") {
        if (this.pinValue.length > 0) {
          this.pinValue = this.pinValue.slice(0, -1);
          if (el && el.popBack) el.popBack();
        }
      } else if (btn.val === "OK") {
        if (this.pinValue.length === 6) this.$emit("submit", this.pinValue);
      } else {
        if (this.pinValue.length < 6) {
          this.pinValue += btn.val;
          if (el && el.commitText) el.commitText(btn.val);
        }
      }
    }
  }
};
</script>

<style scoped>
.pin-container {
  width: 1020px;
  height: 240px;
  background-color: #121316;
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
}
.display-panel { width: 380px; align-items: center; }
.title { color: #FFFFFF; font-size: 20px; margin-bottom: 16px; }
.hidden-input { width: 1px; height: 1px; opacity: 0; position: absolute; }
.dots-wrapper { flex-direction: row; }
.dot {
  width: 16px;
  height: 16px;
  border-radius: 8px;
  border-width: 2px;
  border-color: #40424A;
  margin: 0 8px;
}
.filled { background-color: #008CFF; border-color: #008CFF; }
.numpad-grid { width: 530px; height: 200px; justify-content: space-between; }
.num-row { flex-direction: row; justify-content: space-between; }
.key-btn {
  height: 60px;
  background-color: #1E2024;
  border-radius: 10px;
  justify-content: center;
  align-items: center;
}
.key-btn:active { background-color: #32353D; opacity: 0.6; }
.num { width: 98px; }
.action-clear, .action-del { width: 130px; background-color: #26282E; }
.action-ok { width: 250px; background-color: #008CFF; }
.key-text { color: #FFFFFF; font-size: 22px; font-weight: 500; }
</style>
```

---

### 6.3 方案 3：底层原生 `InputElmApi` 控制器 (`IMEController.js`)

```javascript
export class IMEController {
  static getNativeElement(vmComponent) {
    if (!vmComponent) return null;
    return vmComponent.$el || vmComponent;
  }

  static showSoftInput(inputRef, inputType = 0) {
    const el = this.getNativeElement(inputRef);
    if (!el) return;
    if (typeof el.inputMethod === "function") el.inputMethod(true, inputType);
    else if (typeof el.focus === "function") el.focus();
  }

  static hideSoftInput(inputRef) {
    const el = this.getNativeElement(inputRef);
    if (!el) return;
    if (typeof el.unFocus === "function") el.unFocus();
    else if (typeof el.blur === "function") el.blur();
    if (typeof el.inputMethod === "function") el.inputMethod(false, 0);
  }

  static append(inputRef, text) {
    const el = this.getNativeElement(inputRef);
    if (el && typeof el.appendText === "function") el.appendText(String(text));
  }

  static backspace(inputRef) {
    const el = this.getNativeElement(inputRef);
    if (el && typeof el.popBack === "function") el.popBack();
  }

  static getCursorIndex(inputRef) {
    const el = this.getNativeElement(inputRef);
    if (el && typeof el.getCursorPosition === "function") return el.getCursorPosition();
    return -1;
  }

  static setCursorIndex(inputRef, index) {
    const el = this.getNativeElement(inputRef);
    if (el && typeof el.setCursorPosition === "function") {
      el.setCursorPosition(Math.max(0, parseInt(index, 10)));
    }
  }

  static commitComplete(inputRef) {
    const el = this.getNativeElement(inputRef);
    if (el && typeof el.commitComplete === "function") el.commitComplete();
  }
}
```

---

## 7. 逆向结论与开发关键准则

1. **窗口层级绝不可僭越**：业务 MiniApp 最大 Z-Order 为 100；键盘窗口 `im::FalconIMPanel` 固定为 `10200`（`0x27d8`）。不要尝试在业务应用内创建大于 `10000` 的浮层，否则会破坏 WindowManager 的命中测试与穿透机制。
2. **根容器必须具备滚动能力**：底层 `bringToScreen(int height)` 防遮挡机制严重依赖于 `View::getRootView()->scrollTo(0, delta)`。若页面根节点为固定不可滚动的绝对定位 `div`，输入框依然会被底部 170px 键盘严重遮挡。所有包含输入框的页面，**外层必须包裹 `<scroller>` 并在底部留足 180px 的可滚动行程缓冲**。
3. **触控与性能优化准则**：在 1020 × 240 极窄画布上，必须避免在键盘交互中触发繁重的 QuickJS 运行时 VNode Patch。按键高亮响应完全交由 CSS `:active` 伪类驱动，实现小于 3ms 的原生级按键反馈。
4. **后退按键双重处理**：`FalconIMPanel::handleBackPress()` 已经对物理 Back 键进行了接管：第一按收起键盘，第二按退出页面。业务应用无需在键盘展开时手动拦截物理返回键，只需处理好 `@finishEdit` 与页面的数据持久化即可。
