# 有道词典笔 S7 Pro 语音评测、发音互动与写作训练底层逆向分析报告

---

## 一、 架构总览与执行拓扑

网易有道词典笔 S7 Pro（硬件平台代号：`Y08_CV1813_V0`，SoC：Cvitek CV1813H 单核 ARM Cortex-A7 @ 1.0GHz，Linux 5.10.4 内核，128MB 物理内存，1020 × 240 极窄横屏）内置的 6 款核心语音评测、发音互动与写作训练官方微应用，均构建于阿里 HaaS UI / Falcon 渲染引擎与 QuickJS 2020-07-05 二进制字节码（`.js.bin`）运行时之上。

### 1. 目标微应用清单与包拓扑

| 应用名称 | 英文标识 (AppID) | 物理包路径 (`/userdisk/secondary/miniapp/data/mini_app/pkg/`) | 架构定位与核心特征 |
| :--- | :--- | :--- | :--- |
| **跟读 (Follow Read)** | `RepeatAfter`<br>(`8080212693101341`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8080212693101341/a/` | 纯前端轻量化应用，依托系统级录音服务 IPC 桥接离线评测引擎；多维打分（准确度/流利度/完整度） |
| **拼读 (Phonics)** | `Spell`<br>(`8080262605498742`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8080262605498742/a/` | 搭载原生 C++ 自然拼读引擎库，拥有 139 个系统预置单音标音频资产，多线程逐音节高亮 |
| **背诵 (Recitation)** | `TextMemory`<br>(`8001678699362882`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001678699362882/a/` | 课文分句背诵与整篇背诵，静音自动断句（VAD 800ms），3星级阶梯评分与提示词追踪 |
| **听写 (Dictation)** | `Dictation`<br>(`8001679380845889`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001679380845889/a/` | 拥有完整 SQLite 3 教材与单元词库，报读语速调节，自动批改与本地练习历史存盘 |
| **语文写作 (Chinese Writing)** | `ChineseArticle`<br>(`8001733817189797`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8001733817189797/a/` | 支持光学笔尖扫描与虚拟全键盘输入；基于 CPR HTTP SSE 长连接流式接收 AI 评测；富文本行内标记 |
| **英语写作 (English Writing)** | `EasayChecker`<br>(`8080212680903142`) | `/userdisk/secondary/miniapp/data/mini_app/pkg/8080212680903142/a/` | 多学段（小学/初中/高中/四六级/考研/雅思托福）动态提示；语法病句高亮标记与词汇替换升级 |

---

### 2. 跨进程微服务 IPC 拓扑结构

在 128MB 严苛内存限制下，官方没有让每个前端应用重复打包底层的音频采集与离线打分引擎，而是采用了**微服务化跨进程代理架构**：

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              前端应用层 (Vue 2.x SFC)                             │
│   跟读 (RepeatAfter)       背诵 (TextMemory)        自然拼读 (Spell)              │
├─────────────────────────────────────────────────────────────────────────────────┤
│                               QuickJS 运行时桥接                                 │
│  $service_proxy.sendCommand()  │  falcon://8001670668055425/record-service      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                     系统中心录音服务 (RecordService: 8001670668055425)           │
│   libbusiness_record.so / libjsapi_record.so (JSCaptProxy, JSRecordProxy)       │
├─────────────────────────────────────────────────────────────────────────────────┤
│           Linux 音频子系统 (ALSA / AFE)          │      离线口语评测引擎 (CAPT)       │
│  SoundRecord 守护进程 (PID 603)                   │  /oem/.../libcapt.so            │
│  Hardware Beamforming (libbf.cv1826.so)         │  Kaldi Chain Acoustic Model     │
│  Audio Front End (libyoudao_afe_lim.so)         │  OpenFst Lattice Rescorer       │
│  writeShm (POSIX 共享内存零拷贝直通) ───────────────┴─► capt_push_wav() (16kHz PCM)       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 语音录音与智能评测全链路深度剖析

### 1. 前端录音与评测管理 API

在跟读（`RepeatAfter`）与背诵（`TextMemory`）中，前端通过引入 `globalManager` / `recordManager` 与底层建立会话：
- **服务定位器**：前端向 Falcon 运行时请求服务代理：
  ```javascript
  const serviceProxy = $falcon.service_proxy;
  serviceProxy.connect("falcon://8001670668055425/record-service");
  ```
- **核心控制契约**：
  ```javascript
  // 启动跟读口语评测
  serviceProxy.sendCommand({
      action: "startCapt",
      params: {
          text: "An apple a day keeps the doctor away.", // 目标参考文本
          pron: "æ n  ˈæ p l  ə  d eɪ...",               // 目标音标音素链 (选填)
          accent: "us",                                  // 目标口音: "us" (美音) | "uk" (英音)
          thresholdScore: 60                             // 及格阈值分
      }
  });

  // 停止跟读评测并落盘临时音频
  serviceProxy.sendCommand({
      action: "stopCapt",
      params: {
          saveAudioFileName: "/tmp/user_follow_record.wav"
      }
  });
  ```

---

### 2. 底层 Linux ALSA 采集与共享内存（Zero-Copy）直通管线

1. **硬件与音频前端采集**：
   - 词典笔采用双数字硅麦组成的线形麦克风阵列，采样率固定为 **16000Hz**，位深 **16-bit Mono PCM**。
   - 音频采集硬件抽象层由系统级守护进程 `/oem/YoudaoDictPen/output/SoundRecord`（系统常驻 PID 603）独占控制，底层加载声学前处理算法库：
     - `libbf.v1.0.1.cv1826_release.so`：硬件波束成形（Beamforming），增强笔尖朝向声源；
     - `libyoudao_afe_lim.so`：自适应回声消除（AEC）、非平稳噪声抑制（ANS）与动态增益控制（AGC）。
2. **POSIX 共享内存零拷贝传输**：
   在 `YDALCOMMONAPI::Internal::YSoundRecordInterfacePrivate` 中，音频流由采集进程通过 POSIX Shared Memory 写入环形缓冲区：
   ```cpp
   // SoundRecord 共享内存接口签名
   int writeShm(const void* pcm_data, size_t len);
   ```
   评测模块 `YCaptModulePrivate` 直接映射同一块共享物理内存，将 16kHz 16-bit PCM 音频块通过 `capt_push_wav()` 直接投递至评测引擎，规避了 Linux 传统管道（pipe）或套接字（socket）在 Cortex-A7 处理器上的多次内存拷贝与上下文切换开销。

---

### 3. C++ 离线口语评测引擎（`libcapt.so`）逆向揭秘

离线评测引擎驻留于 `/oem/YoudaoDictPen/output/libs/libcapt.so`（ELF 32-bit LSB shared object, ARM EABI5, 动态库体积约 8.5MB），底层采用 **Kaldi Chain 声学模型** 与 **OpenFst 有限状态机解码网络**。

#### (1) 导出符号与生命周期控制接口
```cpp
extern "C" {
    // 1. 初始化评测引擎并载入声学模型、音素字典 (FST Table)
    void capt_init();

    // 2. 注入评测参考文本 (自动执行文本正则化 Text Normalization 与 G2P 音素音标映射)
    void capt_set_reftext(const char* text);

    // 3. 开启单次评测会话 (flag = true: 启用基于能量与后验概率的 VAD 自动端点检测)
    void capt_begin(bool flag);

    // 4. 流式推入 PCM 音频帧 (单帧长通常为 480~960 字节, 即 15~30ms 音频)
    void capt_push_wav(short* pcm_data, int len, bool is_end);

    // 5. 结束音频推流，触发强制解码与后验概率晶格重打分
    void capt_end();

    // 6. 获取 JSON 格式的全文综合评测报告
    char* get_capt_result();

    // 7. 查询指定单词在当前口音参考下的标准发音细节分
    char* get_word_score(const std::string& word, const std::string& pron);

    // 8. 提取当前句子中严重失真发音的薄弱词列表 (低于设定的阈值分数)
    char* get_badwords_sent(const std::string& sentence, float threshold);
}
```

#### (2) 核心 C++ 解码类结构
- `OfflineCAPTer` / `OfflineCAPT`：
  - `OfflineCAPTer::asr_init(int sample_rate, const char* model_dir, string config)`：初始化声学网络；
  - `OfflineCAPTer::set_vad_break_params(float silence_threshold, float min_speech, float max_silence, float margin)`：配置端点检测停顿时间；
- `LatticeRescorer`（基于 Kaldi Lattice 晶格重打分）：
  - `LatticeRescorer::GetPhoneTimes(...)`：对齐音素级物理起始与截止时间戳；
  - `LatticeRescorer::GetWordTimes(...)`：对齐单词级时间跨度；
  - `LatticeRescorer::Rescore(...)`：结合声学打分（Acoustic Score）与语言模型先验概率进行加权归一化。

---

### 4. 智能评测结果数据结构与前端评分呈现

评测引擎通过 `get_capt_result()` 输出的 JSON 经由 C++ `JSCaptProxy::onCaptResult()` 上报至前端，其标准数据格式如下：

```json
{
  "integrityScore": 95,          // 完整度得分 (0-100): 衡量漏读、漏词比例
  "pronunciationScore": 88,      // 准确度得分 (0-100): 衡量音素发音精度
  "fluencyScore": 82,            // 流利度得分 (0-100): 衡量语速平稳度与不自然停顿
  "totalScore": 88,              // 综合总得分 (加权计算值)
  "words": [
    {
      "word": "apple",
      "score": 92,               // 单词总得分
      "integrity": 100,
      "pronunciation": 92,
      "fluency": 90,
      "accent": "us",            // 口音匹配度
      "phonemes": [
        { "phoneme": "æ", "score": 95, "status": 1 },
        { "phoneme": "p", "score": 90, "status": 1 },
        { "phoneme": "l", "score": 82, "status": 1 }
      ]
    },
    {
      "word": "doctor",
      "score": 45,               // 发音错误单词 (< 60分)
      "integrity": 100,
      "pronunciation": 42,
      "fluency": 70,
      "accent": "us",
      "phonemes": [
        { "phoneme": "d", "score": 85, "status": 1 },
        { "phoneme": "ɒ", "score": 30, "status": 2 }, // 发音错误音素
        { "phoneme": "k", "score": 78, "status": 1 },
        { "phoneme": "t", "score": 80, "status": 1 },
        { "phoneme": "ə", "score": 40, "status": 2 }
      ]
    }
  ]
}
```

#### (1) 前端单词行内三色状态渲染机制
在 `ScoreAndLabel.vue` 与 `Sentence.vue` 中，系统对每个单词匹配三档色彩并赋予动态交互：
- **良好发音 (Good, 得分 >= 80)**：
  - CSS 类名：`.word-read-good`
  - 颜色值：`#28C7B2`（薄荷青翠）
- **发音尚可 (Bad / Warning, 60 <= 得分 < 80)**：
  - CSS 类名：`.word-read-bad`
  - 颜色值：`#F19824`（金橙色）
- **发音错误 (Error, 得分 < 60)**：
  - CSS 类名：`.word-read-error`
  - 颜色值：`#F9532F`（警示亮红）
- **交互纠音**：用户直接点击红色/黄色单词，触发 `@click="sentenceCorrectClicked"`，弹出 `AICorrectList.vue` 展开该词的音素柱状分解与发音对比示范。

#### (2) 背诵星级分档算法（`ScoreResult.vue`）
在课文背诵与整篇跟读结束弹窗中，依据综合得分自动进入三档评星模型：
- **三星（卓越，Score >= 80）**：
  - 展示文案：`"背诵分数总分大于80分"`
  - 资产挂载：`images/819ccabbe99486850ee09b66c3dc23e4.png`（3 颗金星）
- **二星（良好，60 <= Score < 80）**：
  - 展示文案：`"背诵分数介于60到80之间"`
  - 资产挂载：`images/4237993607f8ac7e87033dd8f85e307b.png`（2 颗金星）
- **一星（薄弱，Score < 60）**：
  - 展示文案：`"背诵分数小于60"`
  - 资产挂载：`images/b491debd68944fed3ca1db7b2e910049.png`（1 颗金星）

---

## 三、 自然拼读音标教学与发音动效渲染机制

### 1. 音标组合与 139 个单音标音频资产库

自然拼读（`Spell`, AppID: `8080262605498742`）依赖嵌入式固件系统预置的单音素音频资产，位于系统只读分区：
`/oem/YoudaoDictPen/output/localsound/phonic/`

系统内置了严格涵盖国际音标体系（IPA）及双字母辅音连缀组合的 **139 个 MP3 高质量发音文件**：
- **元音与双元音**：`a.mp3`、`aɪ.mp3`、`aɪə.mp3`、`aʊ.mp3`、`aʊə.mp3`、`e.mp3`、`eə.mp3`、`eɪ.mp3`、`iː.mp3`、`uː.mp3`、`ɔː.mp3`、`ʌ.mp3` 等；
- **辅音与连缀辅音**：`b.mp3`、`bl.mp3`、`br.mp3`、`d.mp3`、`dr.mp3`、`dz.mp3`、`dʒ.mp3`、`dʌbljuː.mp3`、`f.mp3`、`fl.mp3`、`fr.mp3`、`gl.mp3`、`gr.mp3`、`pl.mp3`、`pr.mp3`、`str.mp3`、`tr.mp3` 等；
- **音素名称读音**：如字母本身的读音 `ef.mp3` (`F`), `eks.mp3` (`X`), `el.mp3` (`L`), `eɪtʃ.mp3` (`H`) 等。

---

### 2. C++ 多线程拼读引擎与任务队列状态机

拼读的核心逻辑位于该应用私有动态库：
`/userdisk/secondary/miniapp/data/mini_app/pkg/8080262605498742/a/libs/libbusiness_spell_1241802718.so`（工程源路径：`app/yd-smarthardware-app/yd-self-app/spell/business/`）。

#### (1) 线程与任务模型
`YSpellTaskManager` 维护一个独立的后台 Worker 线程与先进先出（FIFO）任务队列 `YSpellTaskQuene`。拼读一个单词（如 `"cat"` 拆解为 `/k/` - `/æ/` - `/t/`）时，系统自动生成由若干子任务构成的复合任务序列：

```cpp
// 子任务基类与实现类
class YSpellSubTask;
class YWordSpellSubTask : public YSpellSubTask {
    // 携带元组数据: <音节文本, 字符在原词的索引位置范围, 音频文件路径, 是否为末尾音节, 音标文本>
    std::tuple<std::string, std::vector<int>, std::string, bool, std::string> m_data;
};
class YWaitSpellSubTask : public YSpellSubTask {
    int m_delayMs; // 音节之间的停顿等待 (默认 150ms ~ 250ms)
};
```

#### (2) 帧级同步高亮流水线
1. `YSpellTaskManager` 依次取出 `YWordSpellSubTask`；
2. 调度 `libyddal_common_soundplayer.so` 异步播放 `/oem/YoudaoDictPen/output/localsound/phonic/<phoneme>.mp3`；
3. 紧接着向前端派发 `onRichContentChanged(jsonContent)` 事件；
4. 当音频底层产生播放完成中断（`YPlayerError::NoError`）时，触发 Callback，队列自动推进至 `YWaitSpellSubTask`；
5. 全部音节朗读完毕后，调用全词发音，最后派发 `onSpellFinished(true)`。

---

### 3. 前端逐音节高亮色阶与动态波形渲染

在 `SpellWidget.vue` 中，`<richtext>` 负责接收并渲染底层下发的 HTML Span 片段：

#### (1) 色阶定义
```css
/* SpellWidget.vue 核心样式 */
.spell-word {
    color: #FFFFFF;       /* 单词基础未高亮色 (纯白) */
    font-size: 48px;
    font-weight: bold;
}
.high_A {
    color: #008CFF;       /* 主音节正在发音色 (有道科技蓝) */
    font-weight: bold;
}
.high_B {
    color: #FF7300;       /* 关联辅音/连缀辅助高亮色 (活力橙) */
    font-weight: bold;
}
.spell-phonics-inactive {
    color: #B6BFC9;       /* 音标未读状态 (浅蓝灰) */
}
```

#### (2) 录音波形图的双模渲染实现
词典笔在录音状态下展示跳动的声波图，系统针对不同算力模式实现了两套方案：
1. **Bodymovin Lottie 矢量动画方案**：
   - 系统级 Lottie 资源文件：`/oem/YoudaoDictPen/output/localres/recording.json`（Bodymovin 5.9.2 导出，60fps，7 个波形柱图层，宽高 180×80）。
   - 渲染底层：`/usr/lib/libfalcon.so` 内部直接内嵌了 Samsung **rlottie** 矢量引擎，导出 `LottieElmApi` 与 `JQuick::WXLottie`，前端直接声明 `<lottie src="/oem/YoudaoDictPen/output/localres/recording.json" autoplay="true" loop="true" />`，无需 JS 介入逐帧计算。
2. **轻量 PNG 帧序列轮播方案（`ApolloSoundPlayAnimationIcon.vue`）**：
   - 为避免在极低电量或高负荷下的 Lottie 贝塞尔曲线光栅化开销，组件内置了从 1 帧到 9 帧的轻量 PNG 序列图（`images/...`），使用 `setInterval` 每 80ms 递增轮换索引，CPU 占用率低于 0.5%。

---

## 四、 写作批改与富文本标注呈现机制

### 1. 双输入通道：连续光学扫描与系统输入法

写作类应用（语文写作 `8001733817189797` 与英语写作 `8080212680903142`）在 `Edit.vue` 中支持两种输入媒介的无缝融合：

```
┌────────────────────────────────────────────────────────────────────────┐
│                        输入方式 1: 光学笔尖连续扫描                      │
│ 笔尖压敏开关 -> 摄像头连续采图 -> 本地/云端 OCR -> appendText 流式上屏   │
├────────────────────────────────────────────────────────────────────────┤
│                        输入方式 2: 软键盘虚拟编辑                       │
│ 点击编辑框 -> 呼出系统级 IM_PANEL_DICT -> C++ InputConnection 字符上屏   │
└────────────────────────────────────────────────────────────────────────┘
```

- **多行连续扫描支持**：
  在光学笔扫描作文时，系统派发 `ocrStartChanged` 与 `scanArticleResultChanged` 事件。前端调用 `$updateOcrMultilineConfig` 开启多行拼接模式，并激活 `AlmondMultiScanResultDisplay.vue` 实时展示扫入的行文本；若连续两行语义未断，底层自动拼接空格或换行符。

---

### 2. 云端 AI 批改与 HTTP SSE（Server-Sent Events）长连接

词典笔本地不具备运行数十亿参数大语言模型的能力，作文批改全部依托网易有道云端大模型服务：
- **生产服务器**：`https://write-server.youdao.com`
- **语文综合评价接口**：`/writing/chinese/comprehensive/evaluation/sse`
- **网络传输协议**：基于 CPR（`libcpr.so`）与 cURL 封装的 `YDALBASEAPI::httpSSE2v0::YHttpSSE`，采用 HTTP/1.1 `text/event-stream` 格式持续推送分块解析流：

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: begin
data: {"code": 0, "requestId": "req_essay_98214"}

event: message
data: {"type": "score", "totalScore": 86, "dimensions": {"content": 88, "expression": 84, "structure": 86}}

event: message
data: {"type": "clause", "index": 0, "original": "他跑的飞快。", "errorType": "typo", "errorWord": "的", "suggestWord": "得", "reason": "在动词'跑'后面表示程度，应使用助词'得'。"}

event: end
data: {"status": "finished"}
```

---

### 3. Falcon 原生 `FlRichText` 与 `:pseudoRef` 交互机制

这是有道词典笔在极窄屏幕上实现**富文本词句交互与气泡批注（Popover）的核心底层秘籍**。

#### (1) `:pseudoRef` 属性的工作原理
在传统的 Web 开发中，行内给某几个字绑定独立点击事件需要渲染大量的 `<span>` 并挂载原生 DOM EventListener，这在嵌入式 QuickJS 上会消耗巨额内存。
Falcon 引擎在其底层的 C++ HTML 解析器（`richtext::HtmlNode`）中直接支持了 `:pseudoRef` 特殊属性：

```html
<!-- 批改结果页面 resultDetail.vue 生成的 RichText 片段 -->
<richtext class="content-text" @textClick="onTextClick">
  <span style="margin-left: 60px"></span>
  <span>昨天的天气晴朗，我和小明去公园踢足球。</span>
  <span style="color: #F9532F; font-weight: bold" :pseudoRef="'err_0'">他跑的飞快</span>
  <span>，一下就追上了足球。我们玩的非常</span>
  <span style="color: #28C7B2; font-weight: bold" :pseudoRef="'highlight_0'">兴高采烈</span>
  <span>。</span>
</richtext>
```

#### (2) C++ 事件派发与坐标命中测试（Hit-Testing）
1. C++ 类 `greenui::RichTextView` 与 `richtext::Layout` 在排版布局时，为带有 `pseudoRef` 属性的文本节点单独记录包围盒（Bounding Box：`x, y, w, h`）；
2. 当用户手指在屏幕上点击（`ACTION_UP`）时，C++ 层的 `RichTextView::onTouchEvent` 执行几何点选测试；
3. 一旦落入带有 `pseudoRef` 的矩形区域内，直接提取属性字符串（如 `"err_0"`），并以事件参数形式上报给 JS 层的 `@textClick` 回调函数：
   ```javascript
   onTextClick(event) {
       const refId = event.detail.pseudoRef; // 获取 "err_0"
       this.activeErrorItem = this.sentenceAnalysisList[refId];
       this.analysisDialogVisible = true;    // 激活气泡弹窗
   }
   ```

---

### 4. 1020 × 240 极窄横屏上的气泡弹窗与排版适配技巧

1020 × 240 的横向视野极为修长，但纵向仅有 240 物理像素（扣除状态栏 24px 后仅余 216px）。若直接居中弹出对话框，会导致背景文字被完全遮挡，用户失去对照上下文。

#### (1) 侧边双栏抽屉式弹窗（`AnalysisDataDialog.vue`）
- 官方摒弃了传统移动端的底部 ActionSheet 或正中央浮层，采用了**横向左右并列分栏布局**：
  - **左侧栏（宽度 520px - 580px）**：保留作文正文，将高亮选中的词句自动通过 `<scroller>` 滚动至视口中部偏左位置；
  - **右侧栏（宽度 420px - 460px）**：呼出 `AnalysisDataDialog`。弹窗固定高度为 `216px`，右侧贴边滑入，内含：
    - 错误分类标签（如 `[错别字]`、`[动宾搭配不当]`）；
    - 原始词与替换建议词对比卡片；
    - 修改原由（`detailReason`）精简展开。
- **两字首行缩进技巧**：
  由于嵌入式 Falcon 富文本排版引擎不支持 CSS `text-indent: 2em`，官方通过行内注入 `<span style="margin-left: 60px"></span>` 强行撑开 60px（每字 30px × 2），严丝合缝达成中文正文标准首行缩进。

---

## 五、 听写应用与本地教材库数据架构

听写应用（`Dictation`, AppID: `8001679380845889`）是 6 款应用中唯一具备深度本地 SQLite 3 关系型数据库结构的应用。

### 1. C++ 数据持久化驱动（`libbusiness_dictation_612993608.so`）
应用启动时，C++ 业务层自动在 `/userdisk/database/dictation.db` 建立结构化表：

```sql
-- 1. 听写教材包总表
CREATE TABLE IF NOT EXISTS table_book (
    id TEXT PRIMARY KEY,             -- 教材唯一 ID (如 "book_pep_en_3a")
    grade TEXT,                      -- 年级代码 (如 "grade_3")
    title TEXT,                      -- 短标题 (如 "三年级上册")
    full_title TEXT,                 -- 完整书名
    subject TEXT,                    -- 学科 ("english" | "chinese")
    publisher TEXT,                  -- 出版社 ("人教PEP" / "苏教版")
    book_key TEXT,                   -- 词书检索键
    pack_url TEXT,                   -- 远端离线下载包 CDN 地址
    local_file TEXT,                 -- 离线资源包本地解压路径
    cover_url TEXT,                  -- 封面图片网络地址
    cover_local TEXT,                -- 封面图片本地缓存路径
    download_state TINYINT DEFAULT 0 -- 0: 未下载, 1: 下载中, 2: 已解压可用
);

-- 2. 单元与课次表
CREATE TABLE IF NOT EXISTS table_unit (
    unit_id TEXT PRIMARY KEY,
    book_id TEXT,                    -- 所属教材外键
    unit_name TEXT,                  -- 单元名称 (如 "Unit 1 Hello!")
    word_count INTEGER DEFAULT 0     -- 本单元应听写词汇总量
);

-- 3. 词汇明细与发音映射表
CREATE TABLE IF NOT EXISTS table_word (
    word_id TEXT PRIMARY KEY,
    unit_id TEXT,                    -- 所属单元外键
    word TEXT,                       -- 单词文本
    phonetic TEXT,                   -- 音标
    translation TEXT,                -- 中文释义
    audio_path TEXT,                 -- 本地发音音频绝对路径
    sort_order INTEGER               -- 默认报读次序
);

-- 4. 听写练习历史记录表
CREATE TABLE IF NOT EXISTS table_exercise_history_record (
    id TEXT PRIMARY KEY,             -- 记录 UUID
    book_key TEXT,
    unit_key TEXT,
    unit_title TEXT,
    correct_rate INTEGER DEFAULT -1, -- 正确率百分比 (0-100)
    word_count INTEGER DEFAULT 0,    -- 实际听写词汇数
    wrong_words TEXT,                -- 错误单词列表 (JSON 序列化存储)
    local_result_file TEXT,          -- 详细手写/输入结果存盘路径
    timestamp INTEGER                -- 听写完成时间戳
);
```

### 2. 离线教材包的分发与解包机制
- 教材资源包从 CDN 下载为加密 ZIP 包，放置于 `/userdisk/resource/Dictation/`；
- C++ 业务层调用 `JSDictationProxy::resumeUnzip()` 执行后台多线程解压，解压完成后自动扫描清单文件并将单词元数据灌入 `table_word`，实现**零网络完全离线报读**。

---

## 六、 官方 UI 设计规范与极窄屏动效度量指南

在 **1020 × 240** 的极限视口约束下，官方在 6 款应用中总结出一套严密的工程设计度量体系：

### 1. 字体阶梯规范（Typography Hierarchy）

| 字号 | 行高 | 字重 | 典型应用场景 | 代表组件 |
| :--- | :--- | :--- | :--- | :--- |
| **48px** | 56px | Bold | 自然拼读单音标 Hero 字母、背诵总分大数字 | `SpellWidget.vue`, `ScoreResult.vue` |
| **34px** | 42px | Medium | 弹窗主标题、作文批改综合得分、听写单词报读主词 | `DialogTitle.vue`, `ResultDetail.vue` |
| **28px** | 34px | Normal | 课文背诵正文文字、作文分句点评段落正文 | `Sentence.vue`, `AICorrectList.vue` |
| **20px** | 26px | Normal | 音标音素标注、批注气泡次级说明、错误原因提示 | `AnalysisDataDialog.vue`, `ScoreAndLabel.vue` |
| **16px** | 20px | Light | 时间戳、年级版本标签、免责声明等弱化辅助文本 | `History.vue`, `BasePage.vue` |

---

### 2. 容器与圆角规约（Border Radius）
- **0px**：全屏 Root 容器、底板背景层；
- **8px**：微型操作按钮、分词点击热区、词性胶囊徽标；
- **14px - 16px**：批改错误弹出气泡、评分规则说明卡片单元；
- **20px**：模态确认弹窗外壳；
- **999px（全圆角胶囊）**：听写“开始练习”、跟读“再练一次”、“完成”等主行动召唤（CTA）按钮。

---

### 3. 色彩体系基准（Color Palette）

```
+-------------------------------------------------------------------------+
| 背景主基调 (Dark Surface)                 #151515 / #1A1B1F (深灰极暗底)    |
| 抽屉/浮层容器 (Elevated Surface)          #202024 / #2D2E33 (微亮容器灰)    |
| 分割线/弱化边框 (Border & Divider)        rgba(255, 255, 255, 0.08) ~ 0.16 |
+-------------------------------------------------------------------------+
| 正向成功/良好发音 (Correct / Good)        #28C7B2 / #1BA292 (薄荷青翠绿)    |
| 警告提示/轻度发音偏离 (Warning / Notice)   #F19824 / #FF7300 (金橙色)        |
| 严重错误/语法病句 (Error / Danger)        #F9532F / #FF3333 (警示亮红)      |
| 官方焦点/主音节强调 (Accent / Brand Blue)  #008CFF / #4086FF (有道科技蓝)    |
| 未读/次级文本 (Muted / Subtitle)          #A8AAB3 / #909199 (中灰阶)        |
+-------------------------------------------------------------------------+
```

---

## 七、 总结与第三方开发者架构启示

通过对有道词典笔 S7 Pro 上 6 款语音评测、发音互动与写作训练微应用的底层逆向剖析，可以提炼出如下极具参考价值的嵌入式架构设计启示：

1. **避免重复造轮，拥抱微服务 IPC 共享**：
   在资源受限设备上，严禁在每个 MiniApp 内静态链接大型语音评测或 OCR 库。将高负载引擎沉淀为单实例系统级 Daemon（如 `RecordService` 与 `SoundRecord`），各应用通过 `$service_proxy` 轻量挂载，是维持 128MB 物理内存稳定的关键。
2. **零拷贝（Zero-Copy）保障实时音频流稳定性**：
   Linux ALSA 采集通过 POSIX 共享内存直通 C++ 评测库，省去 Socket 序列化，使得在 Cortex-A7 单核 1.0GHz 下实现 16kHz 实时端点检测（VAD）与音素对齐成为可能。
3. **利用 `:pseudoRef` 攻克富文本复杂交互难题**：
   长文本批改若使用海量虚拟 DOM 节点监听点击，会导致严重的掉帧与 GC 抖动。Falcon 原生 `FlRichText` 结合 `:pseudoRef` 属性，将命中测试完全下沉至 C++ 几何层处理，兼顾了极高的渲染帧率与灵活的业务逻辑。
4. **适配 1020 × 240 极限横屏的交互范式**：
   横向充足、纵向紧俏。弹窗应优先采用“右侧并列抽屉”而非“居中模态遮罩”；长文本中文排版善用 60px 行内占位达成标准两字缩进；密集按键配合原生 CSS `:active`，以最小的代码体积提供媲美原生系统的操作手感。
