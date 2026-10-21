# 有道词典笔 S7 Pro 学习与工具类应用前端架构深度分析报告

---

## 一、 架构总览与执行环境

网易有道词典笔 S7 Pro（硬件平台代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813H ARMv7-A 平台，Linux 5.10.4 内核，128MB 物理内存，1020 × 240 极窄横向逻辑画布）上的所有官方原生应用均构建于**阿里 HaaS UI / Falcon 轻量级渲染框架**之上，JS 运行环境为 QuickJS 2020-07-05 编译的二进制字节码（`.js.bin`）。

针对四款具有代表性的核心学习与工具类应用的包拓扑与职责划分：
1. **背单词 (Reciter, AppID: `8001654057944134`)**
   - 路径: `/userdisk/secondary/miniapp/data/mini_app/pkg/8001654057944134/a/`
   - 核心特征: SuperMemo-2 记忆曲线算法、卡片拖拽与翻转动效、TTS 与本地音频发音流、SQLite 本地词库。
2. **单词本 (Wordbook, AppID: `8080212246010681`)**
   - 路径: `/userdisk/secondary/miniapp/data/mini_app/pkg/8080212246010681/a/`
   - 核心特征: 虚拟滚动长列表、URS 账号多租户分表隔离、离线增量同步闭环（Offline-First）。
3. **有道输入法 (Input Method, AppID: `8001666679481944`)**
   - 路径: `/userdisk/secondary/miniapp/data/mini_app/pkg/8001666679481944/a/`
   - 核心特征: 全键盘 26 键高密排布、原生 `:active` 零开销响应、底层 C++ Trie 拼音检索引擎、InputConnection 上屏通信。
4. **百度网盘 (Baidu Netdisk, AppID: `8001661310449825`)**
   - 路径: `/userdisk/secondary/miniapp/data/mini_app/pkg/8001661310449825/a/`
   - 核心特征: 二维码跨端扫码登录、递归文件目录树、多级页面导航与物理返回键拦截、下拉刷新（PullRefresh）。

```
┌────────────────────────────────────────────────────────────────────────┐
│                        前端视图层 (Vue 2.x SFC)                         │
│  背单词 (apolloRecite)  单词本 (apolloIndex)  输入法 (InputPage)  网盘  │
├────────────────────────────────────────────────────────────────────────┤
│                      QuickJS 2020-07-05 运行时                         │
│  $falcon / $service_proxy / JQSignal / EventBus / Falcon-UI Components │
├────────────────────────────────────────────────────────────────────────┤
│                   C++ JSAPI 桥接代理层 (/usr/lib)                      │
│ libjsapi_reciter.so │ libjsapi_wordbook.so │ libfalcon.so (GreenUI)    │
├────────────────────────────────────────────────────────────────────────┤
│                   C++ 业务逻辑与系统底层服务 (/oem)                    │
│ libbusiness_reciter │ libbusiness_wordbook │ libyddal_common_soundplayer│
├────────────────────────────────────────────────────────────────────────┤
│                       持久化数据层 (/userdisk)                          │
│ memwords.db (SQLite) │ wordbook.db (SQLite) │ preferences.json (KV)    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 重点调研 1：学习类应用的本地数据管理

系统严格按照数据形态分为三层存储体系：

### 1. SQLite 3 关系型核心数据库
词典笔的核心单词与背诵数据**全部由 SQLite 3 驱动**，而非通过 JS 层的 local storage 或粗糙的文件读写：

#### (1) 背单词应用数据库 (`memwords.db`)
- 物理路径：`/userdisk/miniapp/data/mini_app/pkg/8001654057944134/data/memwords.db`
- 对应 C++ 业务层：`/usr/lib/libfalcon.so` 动态加载该应用私有目录下的 `libs/libbusiness_reciter_2051832498.so`（源工程路径：`app/yd-smarthardware-app/yd-self-app/reciter/business/YMemWordBookDownloader.cpp`）。
- 核心表结构（SQLite DDL）：
  ```sql
  -- 词书计划与总体进度表
  CREATE TABLE wordbooktable (
      book_key TEXT PRIMARY KEY,       -- 词书唯一标识
      book_name TEXT,                  -- 词书名 (如 "人教版高中必修一")
      book_cover_url TEXT,             -- 封面图片
      completed_num INTEGER,           -- 已背完词汇数
      uword_number INTEGER,            -- 词汇总量
      percent TEXT,                    -- 进度百分比
      consecutive_day INTEGER DEFAULT 0, -- 连续打卡天数
      mastered INTEGER DEFAULT 0,      -- 熟练掌握数
      unfinished INTEGER DEFAULT 0,    -- 剩余词汇数
      review INTEGER DEFAULT 0,        -- 今日待复习词汇数
      plan_num INTEGER DEFAULT 0,      -- 每日目标数
      is_download TINYINT,             -- 离线包下载完成标志
      ext TEXT
  );

  -- 单词明细与 SuperMemo-2 记忆算法状态表
  CREATE TABLE wordtag_table (
      word TEXT,                       -- 单词
      paraphrase TEXT,                 -- 中文释义
      paraphrase_type INTEGER,
      phonetic TEXT,                   -- 国际音标
      example TEXT,                    -- 典型例句
      book_key TEXT,                   -- 所属词书外键
      new_recite_status INTEGER,       -- 学习状态: 0未学, 1在学, 2已掌握
      new_correct_times INTEGER,       -- 连续记对次数
      new_wrong_times INTEGER,         -- 累计记错次数
      super_memo_n INTEGER,            -- SM-2 连续重复周期次数 N
      super_memo_interval INTEGER,     -- SM-2 下次复习间隔天数 Interval
      super_memo_time INTEGER,         -- 下次应复习目标时间戳
      super_memo_ef double,            -- SM-2 难度因子 (Easiness Factor, 默认 2.5)
      new_review_time INTEGER,         -- 上次复习时间戳
      new_remembered_time INTEGER,     -- 掌握达标时间戳
      PRIMARY KEY(word, book_key)
  );
  ```

#### (2) SuperMemo-2 (SM-2) 艾宾浩斯复习算法逆向解密
在 `YMemWordBookDownloader.cpp` 中，单词记忆曲线严格遵循 SM-2 算法实现：
- 评分等级：用户点击“认识”评分为 4-5；点击“不认识”评分为 0-2。
- 难度因子更新公式：
  $$EF' = EF + (0.1 - (5 - q) \times (0.08 + (5 - q) \times 0.02))$$
  系统设定 $EF'$ 下限截断为 `1.3`。
- 间隔天数计算：
  $$I(1) = 1 \text{ 天}, \quad I(2) = 6 \text{ 天}, \quad I(n) = I(n-1) \times EF \quad (n \ge 3)$$
- 答错惩罚：一旦评分为“不认识”，`super_memo_n` 重置为 0，`super_memo_interval` 降为 1 天，当天强制重复巩固。

#### (3) 单词本应用数据库 (`wordbook.db`) 与多租户分表
- 物理路径：`/userdisk/database/wordbook.db`
- 对应 C++ 业务层：`libs/libbusiness_wordbook_1199370887.so`（源工程路径：`app/yd-smarthardware-app/yd-self-app/wordbook/business/YWordBookDatabase.cpp`）。
- 多用户隔离与软删除机制：
  单词本根据登录用户 URS 账号 ID 动态建表：
  未登录态使用 `table_wordbook_InvalidId`；登录后自动派生 `table_wordbook_<UserId>`，并启动静默数据合并。
  ```sql
  CREATE TABLE table_wordbook_<UserId> (
      word VARCHAR(2048),
      translate TEXT,                  -- 释义 JSON
      dict_type SMALLINT,              -- 词典分类来源代码
      src_lang VARCHAR(16),
      dst_lang VARCHAR(16),
      item_state TINYINT DEFAULT 1,    -- 1: 正常, 0: 软删除 (Soft Delete, 离线优先核心)
      sync_state TINYINT DEFAULT 0,    -- 0: 本地改动未同步, 1: 已与云端对齐
      timestamp INTEGER,               -- 毫秒时间戳 (更新依据)
      example TEXT,
      PRIMARY KEY (word, src_lang, dst_lang)
  );

  CREATE TABLE table_syncInfo_<UserId> (
      tagid TEXT PRIMARY KEY,
      tag INTEGER,                     -- 服务端下发的增量同步游标 (Sync Tag)
      timestamp INTEGER
  );
  ```

### 2. 轻量级 Key-Value 存储 (`sharedpreferences`)
- 引擎：`/usr/lib/libfalcon.so` 中的 `sharedpreferences` 模块（JS 层对应 `$falcon.storage` / `storage`）。
- 存储路径：`/userdisk/secondary/miniapp/data/mini_app/pkg/<AppID>/data/sharedpreferences/preferences.json`。
- 作用：保存用户个人 Profile、登录 Cookie/Token、界面视图选项（如网盘的列表视图/宫格视图切换、音量设置）。

### 3. 文件系统（`fs` 模块 / 原生二进制包）
- 词书离线内容（如近反义词库、高频真题例句）以加密 `.bin` 或压缩 `.amr` 格式存放于 `/userdisk/miniapp/data/mini_app/pkg/<AppID>/data/`。
- 词典笔本地发音库驻留于系统分区，由 C++ 服务 `/oem/YoudaoDictPen/output/libs/libyddal_common_soundplayer.so` 直接流式读取原生语音包（如 `dictpen-zh-voice`、`dictpen-us-voice`、`dictpen-uk-voice`），无需 MiniApp 自身占用运存缓存。

---

## 三、 重点调研 2：输入法与系统文本控件通信机制

有道输入法（AppID: `8001666679481944`）是系统级独立的 `IM_PANEL_DICT` 应用，与业务 MiniApp 通过操作系统级管道及 C++ `InputConnection` 协作。

### 1. 唤醒与面板加载机制
1. **系统注册**：
   在 `/oem/secondary/etc/miniapp/resources/local_packages.json` 中配置为 `category: "IM_PANEL_DICT"`。在 `manifest.json` 中声明 `"props": { "addDesktop": false, "page_rotation": "inherit" }`，对桌面启动器隐藏。
2. **底层焦点感知**：
   业务应用中的 `<input />` 或 `<textarea />`（底层对应 GreenUI 的 `greenui::EditText` / `greenui::Textarea`）在捕获触控并获取焦点时，自动调用 C++ `greenui::InputMethodImpl::showSoftInput()`。
3. **独立渲染层载入**：
   Falcon 创建一个独立的 `im::FalconIMApp` / `greenui::IMPanel` 视图树，将根节点绑定为 `im-root`，置于系统最顶层。
4. **参数注入与事件广播**：
   系统向输入法派发 `pageShowing` 事件，并注入环境参数：
   - `inputType`: `"text"` | `"number"` | `"symbol"`
   - `globalThemeName`: `"theme-y08"`（通知输入法当前为 S7 Pro 横屏模式）

### 2. 拼音分词与检索树引擎（MatrixSearch）
输入法前端按键通过底层绑定的 `im.searchWord` 直接调用 C++ 硬件检索库：
- 检索库：`/usr/lib/libfalcon.so` 内置的 `ime_pinyin::MatrixSearch`（Google Pinyin / AOSP Trie 核心）。
- 词典数据源：
  - 固件只读字库：`/etc/miniapp/resources/ime_res/lib/dict_pinyin.dat`
  - 用户自学习词库：`/userdisk/secondary/miniapp/data/mini_app/user_dict.dat`
- 前端交互：
  ```javascript
  // OnlyCharKeyboard 收集拼音字符
  this.searchWordChars += 'a';
  // 调用底层 Trie 树极速检索
  im.searchWord(this.searchWordChars, (candidateList) => {
      // 候选词直接分发至 WordsPanel.vue (横向滚动条)
      this.words = candidateList;
  });
  ```

### 3. 字符上屏与编辑器通信契约
- **字符上屏**：
  用户在 `WordsPanel` 中点击候选字词或按下空格，调用：
  ```javascript
  $falcon.im.commitText(selectedWord);
  ```
  底层对应 `_ZN7greenui8EditText10commitTextEPtj`，直接注入处于编辑态的 `InputConnection`，光标向后推移。
- **退格删除**：
  ```javascript
  $falcon.im.deleteSurroundingText(1, 0); // 或调用 im.delete()
  ```
- **动作执行与键盘收起**：
  按下回车或完成按钮时：
  ```javascript
  $falcon.im.sendEditorAction(6); // ACTION_DONE
  this.sendTextEditFinishedSignal();
  this.requestCloseIMApp();
  ```
  触发 `InputMethodImpl::hideSoftInput()`，面板隐藏并释放编辑焦点。

---

## 四、 重点调研 3：触控手势在密集排布下的事件分发与防抖

S7 Pro 高度仅 240px，全键盘 26 键单键高度仅 48px - 56px，宽度仅 64px - 86px，极易发生误触与手势冲突。

### 1. 事件分发链与滑动拦截控制
- **阻止滑动拦截**：
  在 `OnlyCharButton.vue` 与 `NumberKeyboard.vue` 中，根容器在 `touchstart` 发生时执行：
  ```javascript
  event.disallowInterceptTouch(true);
  ```
  该命令直达底层 `greenui::ScrollView`，立即阻断外层滚动容器对手势的判定窃取。
- **触控作用域释放**：
  组件挂载时调用 `clearTouchTargets()`，杜绝多点触控（Multi-touch）在狭小间距下导致两个邻近按键同时触发高亮。

### 2. 零 JS 开销的 `:active` 伪类动态反馈
Falcon 引擎底层实现了 `greenui::OnActiveChangeListener`，完整支持 CSS `:active`：
```css
/* OnlyCharKeyboard 内部样式表 */
.symbol-button {
    background-color: #2D2E33;
    border-radius: 8px;
    opacity: 1;
}
/* 当底层产生 ACTION_DOWN 时，由 C++ 渲染管线直接在 Framebuffer 合成时调整透明度/色彩 */
.symbol-button:active {
    opacity: 0.6;
    background-color: #40424A;
}
```
**技术优势**：传统 Vue 应用通过 `@touchstart="isDown=true"` 会触发 QuickJS 字节码解释 -> VNode Patch -> 更新 DOM，产生 15-30ms 延迟；而官方采用原生 `:active` 响应时延低于 3ms，手感清脆。

### 3. 退格键长按加速与阶梯式退格算法
`DeleteButton-14a255da.js` 还原出的经典加速算法实现：
```javascript
export default {
    data() {
        return {
            deleteButtonPressed: false,
            longPressedTimer: null,
            delCharInterval: null,
            continueDelCharCount: 0
        };
    },
    methods: {
        deleteButtonTouchStart(e) {
            this.deleteButtonPressed = true;
            this.continueDelCharCount = 0;
            // 立即触发单次退格
            this.$emit("deleteButtonClicked");
            
            // 400ms 阈值判断长按
            this.longPressedTimer = setTimeout(() => {
                this.loopDelete();
            }, 400);
        },
        loopDelete() {
            const step = () => {
                this.continueDelCharCount++;
                this.$emit("deleteButtonClicked");
                
                // 动态加速曲线：间隔从 120ms 阶梯加速压缩至 40ms 极速退格
                const nextInterval = Math.max(40, parseInt(120 - this.continueDelCharCount * 4));
                this.delCharInterval = setTimeout(step, nextInterval);
            };
            step();
        },
        deleteButtonTouchEnd() {
            this.deleteButtonPressed = false;
            if (this.longPressedTimer) clearTimeout(this.longPressedTimer);
            if (this.delCharInterval) clearTimeout(this.delCharInterval);
        }
    }
};
```

### 4. 背单词卡片拖拽与滑动手势（ReciteDrag.vue）
在背单词中，`ReciteDrag.vue` 实现了微阻尼卡片滑动：
- 监听 `@touchstart="dragStart"`, `@touchmove="draging"`, `@touchend="dragEnd"`。
- 位移衰减算法：
  $$\Delta X = touch.clientX - startX$$
  $$\text{translateX} = \Delta X \times 0.65 \quad (\text{阻尼衰减系数})$$
- 状态判定：若位移超过 `120px` 且松手速度超过 `0.5px/ms`，则派发状态转换事件，配合 CSS 3D `transform: translate3d(...)` 平滑滑出屏幕；否则触发弹性恢复。

---

## 五、 重点调研 4：二维码展示与渲染机制

系统中存在两套截然不同的二维码展示方案：

### 1. 系统原生 `<qrcode />` 组件
- **C++ 底层类**：`/usr/lib/libfalcon.so` 中的 `greenui::QRCodeView`（注册类 `JQuick::WXQRCode`），内嵌 `libqrencode`。
- **模板使用范式**：
  ```html
  <qrcode 
      class="qrcode-container"
      :text="qrTextUrl"
      :size="180"
      :color="'#000000'"
      :level="'M'"
  />
  ```
- **核心属性支持**：
  - `text` / `value` (String): 编码内容（如 `https://smart.youdao.com/m/...`）。
  - `size` / `qrsize` (Number): 物理像素宽高（如 `180`、`230`、`307`），必须通过属性赋值，不能仅写在 CSS。
  - `color` (String): 前景十六进制颜色（缺省 `#000000`）。
  - `level` (String): 容错等级（`"L"`, `"M"`, `"Q"`, `"H"`）。
- **样式最佳实践**：外层必须包裹白色圆角底板，防止在暗色背景下扫描仪无法识别寻像图形（Position Pattern）：
  ```css
  .qrcode-wrapper {
      display: flex;
      justify-content: center;
      align-items: center;
      background-color: #FFFFFF;
      border-radius: 18px;
      padding: 16px;
  }
  ```

### 2. 百度网盘服务端 Base64 图片流方案
百度网盘（`scanSign.vue`）为了确保统一扫码登录验证协议，避免在嵌入式设备端进行矩阵编码计算，采用云端生成方案：
1. 前端获取设备 SN 号：`getSNInfo()`。
2. 请求 API：`GET_LOGIN_QR_CODE`，接口直接下发 Base64 编码的 JPEG 字符串：
   `qrcode: "data:image/jpeg;base64,/9j/4AAQSkZJRg..."`。
3. 前端直接通过原生 `<image />` 标签承载：
   ```html
   <image class="scan-code" :src="codeUrl" />
   ```
4. 随后开启轮询计时器：以 `codeTime` 为间隔调用 `CHECK_LOGIN`，获取到 `hasLogin: true` 后持久化 Token 并跳转。

---

## 六、 重点调研 5：官方 UI 设计规范与视觉度量标杆

在 **1020 × 240** 的极窄横屏比例下，官方提炼的设计度量基准如下：

### 1. 字体阶梯规范（Typography Hierarchy）
系统首选无衬线屏显字体：中文字体 `"HarmonyOS Sans SC"`，英文字体 `"OPPOSans"`。

| 字号 (Font Size) | 行高 (Line Height) | 字重 | 典型应用场景 | 代表组件 |
| :--- | :--- | :--- | :--- | :--- |
| **48px / 40px** | 56px / 48px | Bold | 核心单词 Hero 级大标题、大型数值展示 | `WordSimple.vue`、背词卡片 |
| **34px / 28px** | 40px / 34px | Medium | 全键盘字母按键、主 Tab 导航、弹窗标题 | `OnlyCharButton.vue`、`WordsPanel.vue` |
| **24px / 20px** | 30px / 26px | Normal | 列表条目、中文释义主文、常规按钮 | `wordItem.vue`、`WordBookCard.vue` |
| **18px / 16px** | 24px / 20px | Normal | 辅助说明文字、国际音标、词性标签（POS）、文件大小 | 词性 Badge、百度网盘列表副标题 |
| **14px / 12px** | 18px / 16px | Light | 极小微标、版本信息、网络重连小字 | 列表底部重试提示 |

### 2. 容器圆角规范（Border Radius）
- **0px**：全屏容器、底部状态底板。
- **8px - 10px**：键盘单个按键、词性 Badge、复选框。
- **14px - 16px**：列表卡片单元、普通对话框、功能按钮。
- **18px - 20px**：二维码白底面板、模态弹窗外框。
- **999px / 半高胶囊**：核心操作按钮（如“认识/不认识”、“开始背单词”）。

### 3. 布局间距与安全边距
- **屏幕横向安全边距**：左右各留白 **24px - 40px**，避免用户握持笔身边缘产生物理手遮挡。
- **按键间隙**：全键盘行距 **4px**，按键水平间距 **6px - 8px**。
- **列表项内边距**：Padding 统一为 **16px**，上下项外间距 Margin 为 **8px - 12px**。

### 4. 经典深色主题配色体系（Color Palette）
```
+-------------------------------------------------------------------------+
| 背景主色 (Primary Background)             #1A1B1F / #18191B (深度深灰)     |
| 卡片层级背景 (Secondary Surface)          #202024 / #282C37 (容器灰)       |
| 按键活动态背景 (Active Surface)           #2D2E33 / #40424A (微亮灰)       |
+-------------------------------------------------------------------------+
| 前景主文字 (Primary Text)                 #FFFFFF           (纯白高亮)     |
| 次级辅助文字 (Secondary Text)             #A8AAB3 / #909199 (中灰)         |
| 弱化标签文字 (Tertiary Text)              rgba(255, 255, 255, 0.6)         |
| 极细分割线 (Dividers)                     rgba(255, 255, 255, 0.08) / 0.5px|
+-------------------------------------------------------------------------+
| 学习功能绿色 (Learn Accent / Correct)     #28C7B2 / #1BA292 (薄荷青翠)     |
| 系统焦点蓝色 (Focus Accent / Active)      #008CFF / #4086FF (有道深海蓝)   |
| 告警星标橙色 (Warning / Favorite / VIP)   #F19824           (金橙色)       |
| 危险错误红色 (Danger / Wrong / Delete)    #FF3333           (警示亮红)     |
+-------------------------------------------------------------------------+
```

---

## 七、 学习与工具类 MiniApp 自研最佳工程实践

1. **存储架构解耦**：
   - 严禁把大量结构化数据直接塞入 `storage`（`preferences.json`），频繁触发整文件 JSON 序列化会引起 Framebuffer 掉帧与 Flash 磨损。
   - 学习记录与长列表应优先使用 SQLite，结合 `item_state = 0` 的软删除设计实现离线优先。
2. **软键盘交互规范**：
   - 避免在业务应用内重写全键盘。应使用标准 `<input />` 控件或 `$falcon.showSoftInput()` 唤起系统输入法。
   - 键盘弹出占高约 **160px - 180px**，有效视口仅剩 60px - 80px，页面必须包裹在 `<scroller>` 内并在获焦时执行滚动防遮挡。
3. **触控与反馈性能**：
   - 密集网格按键强制使用 CSS `:active` 伪类（依托 `greenui::OnActiveChangeListener`），避免依赖 Vue 状态重渲染带来迟滞感。
   - 必须在密集点击与滑动手势上设置 `400ms` 冷却锁，过滤嵌入式电容屏的边缘抖动双击。
4. **二维码展示选型**：
   - 设备配网、账号绑定首选原生 `<qrcode :size="180" />` 标签。
   - 第三方带时效的扫码登录，推荐由服务端直发 Base64 图片，交由 `<image />` 渲染并配合状态轮询。

---

## 八、 总结

通过对背单词、单词本、输入法及百度网盘四款核心官方应用的深度逆向与分析，全面理清了有道词典笔 S7 Pro 在极窄物理屏幕与有限嵌入式算力下的架构哲学：
- **数据层**：以 SQLite 3 配合 SuperMemo-2 算法支撑离线核心学习流，以 `sharedpreferences` 支撑轻量状态，以多用户分表与软删除确保云端协同。
- **系统层**：输入法以独立 MiniApp + 全局 `IM_PANEL_DICT` 驻留，依托 AOSP `ime_pinyin::MatrixSearch` C++ 字典树引擎保障极速检索与精准上屏。
- **视图层**：充分利用 Falcon 原生组件（`<qrcode>`、`<scroller>`、`OnActiveChangeListener`），在 1020 × 240 画布下构建出深色高反差、阶梯式字号与毫秒级反馈的轻量级前端体验。
