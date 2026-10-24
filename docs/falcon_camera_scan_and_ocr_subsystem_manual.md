# 有道词典笔 S7 Pro 笔尖扫描与 OCR 视觉子系统开发者手册
## (Falcon OCR Vision Pipeline, Camera Capture & Hardware Scanning Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, Cvitek TPU, Linux 5.10.4)  
> **底层驱动与中台**: `/usr/bin/CaptureFrame`, `libyocr.so` (本地 TPU 推理), `libYoudaoStitch.so` (图像拼接), `libjsapi_export_core.so`

---

## 目录索引

1. [端到端硬件-软件架构与数据流](#1-端到端硬件-软件架构与数据流)
2. [MiniApp OCR 接入与所有权抢占机制](#2-miniapp-ocr-接入与所有权抢占机制)
3. [核心 C++ 代理类与方法字典 (`global`, `buttonEvent`, `headCamera`)](#3-核心-c-代理类与方法字典)
4. [实时流式与完整识别数据载荷规范 (Data Payloads)](#4-实时流式与完整识别数据载荷规范)
5. [生产级自研扫描应用完整实现 (Vue SFC)](#5-生产级自研扫描应用完整实现)
6. [生命周期陷阱与关键防御准则](#6-生命周期陷阱与关键防御准则)

---

## 1. 端到端硬件-软件架构与数据流

词典笔的 OCR 识别并不是调用普通的手机摄像头或外部云端 API，而是一套紧密耦合的**嵌入式本地 TPU 硬件加速流式视觉流水线**：

```
[笔尖压在纸面]
      │
      ▼ (弹簧受压闭合光学微动)
[/dev/input/event0 (led_control)] (Linux evdev 发出 EV_KEY: KEY_CAMERA = 212, value = 1)
      │
      ▼
[/usr/bin/CaptureFrame 实时守护进程 (SCHED_FIFO 50)]
      ├── 1. 点亮笔尖高显色补光 LED (GPIO 输出高电平)
      ├── 2. 唤醒 CV1813H 硬件 ISP/VPSS DMA 控制器以 60~100 FPS 捕获 320×152 8位灰度图像
      └── 3. 将原始视频帧写入 96 槽物理连续共享环形缓冲区 (Physical Address: 0x9e556a40)
      │
      ▼ (UBus / IPC 通知)
[Falcon 原生运行时桥接: libjsapi_export_core.so]
      ├── 触发 JSButtonEventModuleProxy::headButtonPress (派发信号至前端)
      └── 触发 YDALAPI::YOCRManager::startScan()
            ├── libYoudaoStitch.so: 实时拼接多帧为带状长图
            ├── libyocr.so + libcviruntime.so: CV1813H 硬件 TPU 执行本地神经网络推断
            └── 持续派发中间识别结果: onScanning(partialResult)
      │
[笔尖离开纸面]
      │
      ▼ (微动开关弹开, KEY_CAMERA = 212, value = 0)
[/usr/bin/CaptureFrame]
      ├── 笔尖 LED 熄灭
      ├── 触发 headButtonRelese 信号 (注意底层拼写无 a!)
      └── 完成全量离线精细 OCR 推理与分词
            ├── ocrStopChanged(result, scanType)
            ├── ocrCompleteChanged(result, scanType)
            └── ocrResultChanged(result)
```

---

## 2. MiniApp OCR 接入与所有权抢占机制

在 Falcon 运行时中，前端自研应用**绝不能**通过 `import ocr from 'ocr'` 或网络请求调用识别。正确的接入方式是通过内建的 `global` 和 `buttonEvent` 代理：

### 2.1 OCR 所有权声明 (`addUseOcrAppId`)
系统通过 `YDALAPI::YGlobalLookupWordModule` 维护了一个 OCR 监听者白名单：
- **注册**: `globalMgr.addUseOcrAppId(currentAppId)`
- **注销**: `globalMgr.deleteUseOcrAppId(currentAppId)`（**必须在页面退出时注销，否则整机系统扫描无法恢复！**）

### 2.2 运行模式控制
- **独立拦截模式 (`setAloneScanMode(true)`)**:
  默认情况下，若不开启此模式，系统识别出文字后会强制通过 `$app.navTo("falcon://8080252464522508/index")` 跳转到系统查词应用。第三方应用欲在当前页面自主处理文字，**必须显式调用 `setAloneScanMode(true)`**！
- **长图拼接模式 (`setShowImgScanMode(true)`)**:
  开启后，底层拼接引擎会将扫描走过的完整文字图片生成 Base64 JPEG 并随结果返回，可直接显示在 `<image>` 组件中。
- **扫描开关控制 (`setIsOpenScan(true)`)**:
  确保底层 OCR 引擎处于使能状态。

---

## 3. 核心 C++ 代理类与方法字典

### 3.1 `JSGlobalProxy` (原生模块: `'global'`)
| 方法名 | 参数 | 说明 |
| :--- | :--- | :--- |
| `addUseOcrAppId(appId)` | `String` | 声明当前应用抢占 OCR 识别事件监听权 |
| `deleteUseOcrAppId(appId)`| `String` | 释放 OCR 监听权，归还系统查词与桌面 |
| `setAloneScanMode(enable)` | `Boolean` | `true` 为应用内拦截；`false` 为允许系统跳转 |
| `setShowImgScanMode(enable)`| `Boolean` | `true` 为在结果中携带 Base64 拼接切片图 |
| `setIsOpenScan(enable)` | `Boolean` | 全局开启/关闭扫读能力 |
| `disableCapAndOcr(appId, page, disable)` | `(String, String, Boolean)` | 在视频播放或弹窗时临时屏蔽笔尖触碰响应 |

#### 信号列表 (Signals)
- `ocrStartChanged(bool isStart)`: 扫描开始
- `onScanning(String partialJson)`: 笔尖滑动过程中的实时流式字词更新
- `ocrCompleteChanged(String resultJson, int scanType)`: 完整扫描结束与最终结果包
- `ocrResultChanged(String resultJson)`: 识别结果变更
- `scanErrorChanged(String err, int code)`: 扫描异常（过快、倾角过大、过暗）

### 3.2 `JSButtonEventModuleProxy` (原生模块: `'buttonEvent'`)
| 方法 / 信号 | 参数 | 说明 |
| :--- | :--- | :--- |
| `setButtonEventReady(true)` | `Boolean` | **必须在 `mounted` 后调用，通知底层就绪！** |
| `isHeadButtonPressed()` | 无 | 同步读取笔尖当前是否物理压在纸面上 |
| `headButtonPress` | 信号 `(unsigned int code)` | 笔尖压下触发 (`code: 212`) |
| `headButtonRelese` | 信号 `(unsigned int code)` | 笔尖松开抬起触发 (**注意拼写缺少字母 a**) |

---

## 4. 实时流式与完整识别数据载荷规范

### 4.1 笔尖滑动中实时流式载荷 (`onScanning`)
```json
{
  "status": "update",
  "text": "comprehen",
  "isFailed": 0,
  "scanType": 0
}
```

### 4.2 最终识别结果包 (`ocrCompleteChanged`)
```json
{
  "status": "end",
  "isFailed": 0,
  "scanType": 0,
  "lang": "en",
  "confidence": 0.985,
  "text": "The quick brown fox jumps over the lazy dog.",
  "lines": [
    {
      "line_id": 0,
      "text": "The quick brown fox jumps over the lazy dog.",
      "confidence": 0.985,
      "box": [12, 18, 920, 48],
      "words": [
        {
          "word": "The",
          "lookup_key": "the",
          "confidence": 0.99,
          "box": [12, 18, 45, 48],
          "char_boxes": [[12, 18, 28, 48], [29, 22, 38, 48], [39, 22, 45, 48]]
        },
        {
          "word": "quick",
          "lookup_key": "quick",
          "confidence": 0.98,
          "box": [55, 18, 120, 48],
          "char_boxes": [[55, 24, 68, 48], [69, 22, 75, 48], [76, 22, 82, 48], [83, 22, 95, 48], [96, 18, 120, 48]]
        }
      ]
    }
  ],
  "spliced_image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "multiline": false
}
```

---

## 5. 生产级自研扫描应用完整实现

```html
<template>
  <div class="ocr-container">
    <!-- 顶部状态栏 -->
    <div class="top-bar">
      <div class="back-btn" @click="handleBack"><text class="btn-text">❮ 退出</text></div>
      <text class="status-indicator">{{ statusText }}</text>
      <text class="lang-tag">{{ currentLang }}</text>
    </div>

    <!-- 实时文字展示区域 -->
    <div class="result-box">
      <text class="ocr-text">{{ recognizedText || '请用笔尖紧贴纸面平稳滑过文字...' }}</text>
    </div>

    <!-- 拼接的长条图片预览 (开启 setShowImgScanMode 时生效) -->
    <div v-if="splicedImage" class="img-preview">
      <image class="preview-img" :src="splicedImage" resize="contain" />
    </div>

    <!-- 单词分词列表与查词交互 -->
    <div class="words-scroller-wrap">
      <scroller scroll-direction="horizontal" class="words-scroller">
        <div v-for="(item, idx) in wordTokens" :key="idx" class="word-card" @click="lookupWord(item)">
          <text class="word-text">{{ item.word }}</text>
          <text class="key-text">{{ item.lookup_key }}</text>
        </div>
      </scroller>
    </div>
  </div>
</template>

<script>
import globalModule from 'global';
import buttonEventModule from 'buttonEvent';

export default {
  data() {
    return {
      appId: '8080999900000001',
      statusText: '就绪 (请滑动笔尖)',
      currentLang: 'AUTO',
      recognizedText: '',
      splicedImage: '',
      wordTokens: []
    };
  },
  created() {
    try {
      this.globalMgr = new globalModule.Global();
      this.buttonMgr = new buttonEventModule.ButtonEvent();

      // 1. 注册应用为 OCR 监听者
      if (this.globalMgr.addUseOcrAppId) {
        this.globalMgr.addUseOcrAppId(this.appId);
      }
      // 2. 锁定独立拦截模式 (禁止系统查词应用弹窗抢夺)
      if (this.globalMgr.setAloneScanMode) {
        this.globalMgr.setAloneScanMode(true);
      }
      // 3. 允许生成拼接图片
      if (this.globalMgr.setShowImgScanMode) {
        this.globalMgr.setShowImgScanMode(true);
      }
      // 4. 打开扫描
      if (this.globalMgr.setIsOpenScan) {
        this.globalMgr.setIsOpenScan(true);
      }
    } catch (e) {
      console.log('[OCR Init Error]', e);
    }
  },
  mounted() {
    try {
      if (this.buttonMgr && this.buttonMgr.setButtonEventReady) {
        this.buttonMgr.setButtonEventReady(true);
      }

      // 笔尖下压
      this.buttonMgr.headButtonPress.connect(() => {
        this.statusText = '正在扫描纸面...';
        this.recognizedText = '';
        this.splicedImage = '';
        this.wordTokens = [];
      });

      // 笔尖抬起 (注意底层拼写无 a)
      const rel = this.buttonMgr.headButtonRelese || this.buttonMgr.headButtonRelease;
      if (rel && rel.connect) {
        rel.connect(() => {
          this.statusText = '识别完成，正在解析...';
        });
      }

      // 监听滑动中实时流式文字
      if (this.globalMgr.onScanning && this.globalMgr.onScanning.connect) {
        this.globalMgr.onScanning.connect((raw) => {
          try {
            const data = JSON.parse(raw);
            if (data && data.text) this.recognizedText = data.text;
          } catch (_) {
            this.recognizedText = raw;
          }
        });
      }

      // 监听最终完整识别结果包
      if (this.globalMgr.ocrCompleteChanged && this.globalMgr.ocrCompleteChanged.connect) {
        this.globalMgr.ocrCompleteChanged.connect((rawResult, scanType) => {
          this.statusText = '识别就绪';
          this.parseOcrResult(rawResult);
        });
      }
    } catch (e) {
      console.log('[OCR Listener Error]', e);
    }
  },
  beforeDestroy() {
    this.cleanupOcr();
  },
  methods: {
    parseOcrResult(raw) {
      if (!raw) return;
      try {
        const res = typeof raw === 'string' ? JSON.parse(raw) : raw;
        this.recognizedText = res.text || this.recognizedText;
        this.currentLang = (res.lang || 'AUTO').toUpperCase();
        if (res.spliced_image) {
          this.splicedImage = res.spliced_image;
        }

        const tokens = [];
        if (Array.isArray(res.lines)) {
          res.lines.forEach((line) => {
            if (Array.isArray(line.words)) {
              line.words.forEach((w) => {
                tokens.push({
                  word: w.word,
                  lookup_key: w.lookup_key || w.word.toLowerCase()
                });
              });
            }
          });
        }
        this.wordTokens = tokens;
      } catch (e) {
        console.log('[Parse OCR JSON Error]', e);
      }
    },
    lookupWord(token) {
      console.log('查询单词原形:', token.lookup_key);
    },
    handleBack() {
      if (this.$page && typeof this.$page.finish === 'function') {
        this.$page.finish();
      }
    },
    cleanupOcr() {
      // 极其重要：退出前必须释放 OCR 所有权！
      if (this.globalMgr) {
        if (this.globalMgr.deleteUseOcrAppId) {
          this.globalMgr.deleteUseOcrAppId(this.appId);
        }
        if (this.globalMgr.setAloneScanMode) {
          this.globalMgr.setAloneScanMode(false);
        }
      }
    }
  }
};
</script>

<style scoped>
.ocr-container {
  width: 1020px;
  height: 240px;
  background-color: #121418;
  flex-direction: column;
  padding: 8px 16px;
}
.top-bar {
  width: 988px;
  height: 34px;
  flex-direction: row;
  justify-content: space-between;
  align-items: center;
}
.back-btn {
  width: 80px;
  height: 28px;
  background-color: #37474F;
  border-radius: 6px;
  justify-content: center;
  align-items: center;
}
.btn-text {
  color: #ECEFF1;
  font-size: 14px;
  font-weight: bold;
}
.status-indicator {
  color: #00E676;
  font-size: 16px;
  font-weight: bold;
}
.lang-tag {
  color: #90A4AE;
  font-size: 14px;
}
.result-box {
  width: 988px;
  height: 72px;
  background-color: #1E222B;
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 6px;
}
.ocr-text {
  color: #FFFFFF;
  font-size: 20px;
  line-height: 28px;
}
.img-preview {
  width: 988px;
  height: 38px;
  margin-top: 6px;
}
.preview-img {
  width: 988px;
  height: 38px;
}
.words-scroller-wrap {
  width: 988px;
  height: 54px;
  margin-top: 6px;
}
.words-scroller {
  flex-direction: row;
}
.word-card {
  height: 46px;
  background-color: #263238;
  border-radius: 6px;
  padding: 4px 12px;
  margin-right: 8px;
  justify-content: center;
  align-items: center;
}
.word-text {
  color: #40C4FF;
  font-size: 16px;
  font-weight: bold;
}
.key-text {
  color: #78909C;
  font-size: 12px;
}
</style>
```

---

## 6. 生命周期陷阱与关键防御准则

1. **OCR 所有权遗忘注销导致系统查词瘫痪**:
   若自研应用调用了 `addUseOcrAppId(appId)` 和 `setAloneScanMode(true)`，但在退出（`beforeDestroy` / `onDestroy`）时忘记调用 `deleteUseOcrAppId(appId)` 和 `setAloneScanMode(false)`，系统桌面与全局扫词守护进程将永久认为当前有私有应用在独占拦截扫描，**导致整机在桌面扫任何单词均不再弹出释义卡片**！
2. **高频数据流导致的 GC 假死**:
   笔尖快速划过文本时，`onScanning` 信号可以高达 30~50 次/秒。如果在 `onScanning` 回调函数中频繁创建大对象或频繁 `JSON.parse` 包含几百个字符点位的大数据结构，会瞬间塞满 QuickJS 堆内存诱发 GC 停顿。
   - **防御方案**：在 `onScanning` 中仅做简易字符串提取；待笔尖抬起收到 `ocrCompleteChanged` 时再统一进行完整的对象解析。
3. **笔头微动事件拼写陷阱**:
   务必牢记底层的硬件松开信号为 **`headButtonRelese`**（中间缺少字母 `a`）。
