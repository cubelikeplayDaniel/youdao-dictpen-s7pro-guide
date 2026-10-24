# Falcon 原生 `<image>` 组件底层架构、解码流水线与内存优化指南

## 1. 架构总览与组件拓扑 (Architecture Overview)

在网易有道词典笔（S7 Pro、S6、Y-series 等，基于 Cvitek CV1813H SoC，128MB RAM，运行 Linux + Falcon/QuickJS 运行时）中，Falcon 采用基于阿里 Weex / JQuick 衍生的 C++ 跨平台渲染引擎，结合 GreenUI 图形系统与 Skia 2D 绘图后端。

Vue 模板中声明的 `<image>` 组件并非直接映射为系统的原生 View，而是构建了一条严密的 C++ 组件拓扑链条：

```
+---------------------------------------------------------------+
|                      Vue / QuickJS Template                   |
|                   <image src="..." resize="..." />            |
+---------------------------------------------------------------+
                               |
                               v
+---------------------------------------------------------------+
|              JQuick::WXImage (libfalcon.so)                   |
|  - 继承自 JQuick::Component                                    |
|  - 管理组件属性: src, resize, cacheDir, scale                  |
|  - 管理生命周期: onRecycleResource(), tryLazyLoad()           |
+---------------------------------------------------------------+
                               |
                               v
+---------------------------------------------------------------+
|             JQuick::WXImageView (libfalcon.so)                |
|  - 继承自 greenui::ImageView -> greenui::View                  |
|  - 承载具体渲染逻辑: onDraw(), drawWithBorder()               |
|  - 持有 greenui::Drawable (BitmapDrawable / GifDrawable)      |
+---------------------------------------------------------------+
                               |
             +-----------------+-----------------+
             |                                   |
             v                                   v
+--------------------------+       +--------------------------+
|   JQuick::XImageLoader   |       |  greenui::SkiaCanvas     |
| - 调度 LoadTask (本地/B64) |       | - 对接 SkCanvas          |
| - 调度 DownloadTask(网络) |       | - 软光栅/硬件渲染提交    |
| - BitmapCache (4MB LRU)  |       +--------------------------+
+--------------------------+
             |
             v
+---------------------------------------------------------------+
|                  greenui::doLoadBitmap                        |
|  - SkImageDecoder::decode() -> SkPNG / SkJPEG / SkBMP         |
|  - 输出: SkBitmap (RGB565 或 ARGB8888)                         |
+---------------------------------------------------------------+
```

### 1.1 核心 C++ 类与职责划分

| C++ 类名 | 符号 / 虚表地址 | 核心职责 |
| :--- | :--- | :--- |
| `JQuick::WXImage` | 虚表 `0x7d1a38` | Weex `<image>` 节点映射。负责解析 `src`/`resize`，触发布局计算与延迟加载。 |
| `JQuick::WXImageView` | 虚表 `0x7d1b14` | 具体的 GreenUI 视图对象。处理缩放模式 (`cover`/`contain`/`stretch`) 与边界绘制。 |
| `JQuick::WXImageFrame`| 虚表 `0x7d1c24` | 序列帧与精灵图帧驱动组件。 |
| `falcon::JSImageTag`  | `0x323e00` 系列 | JS 端 `new Image()` 或 `<canvas>` 图像标签的绑定对象。 |
| `JQuick::XImageLoader`| 虚表 `0x7cb5f0` | 图像加载中枢单例，统一调度异步解码线程池与 LRU 缓存。 |
| `JQuick::BitmapCache` | `0x239dc0` 系列 | 基于 `std::map` 与 `std::list` 实现的 4MB 内存位图池。 |
| `greenui::ImageView`  | `0x446000` 系列 | 基础视图层，持有 `greenui::Drawable` 指针。 |

### 1.2 `JQuick::WXImage::setProperty` 反汇编关键逻辑

反汇编地址 `0x38f110` 显示，Falcon 在解析 `<image>` 属性时：
1. **`src` 属性**：若当前视图尺寸为 0（尚未经历 Flexbox 布局阶段），`WXImage` 将标记延迟加载标志，推迟至 `onPostLayout` 完成后再加载；若视图已有确定尺寸，则立刻触发加载。
2. **`resize` 属性**：
   - `"contain"` $\rightarrow$ ScaleType 1（保持宽高比居中完整显示）；
   - `"cover"` $\rightarrow$ ScaleType 2（保持宽高比充满视口并裁剪溢出）；
   - `"stretch"` $\rightarrow$ ScaleType 0（拉伸填充宽高，默认模式）。
3. **`scale` 属性**：解析自定义图像缩放因子，存入 `WXImageView + 0x1f0`。
4. **`cacheDir` 属性**：设置该图片请求的本地缓存目录，若未指定则默认进入系统应用沙箱临时目录。

---

## 2. 资源路径解析机制与寻址流水线 (Asset Path Resolution)

开发者在使用 Falcon 时经常遇到 `'assets/...'` 能加载，但 `'/userdisk/...'` 找不到文件的现象。通过逆向分析 `JQuick::WXInstance::rewriteUrl`（`0x3cbc94`）与 `JQuick::buildBundleUrl`（`0x3ca7f0`），其底层寻址逻辑如下：

### 2.1 寻址全流程决策树

```
                         输入路径 src
                              |
     +------------------------+------------------------+
     |                                                 |
以协议头开头?                                      不以协议头开头
(file://, http://, https://,                           |
 data:image/, ftp://)                                  |
     |                                                 |
     | (匹配)                                           | (不匹配)
     v                                                 v
原样保留 (不重写)                                以 '/' 根路径开头?
     |                                                 |
     |                              +------------------+------------------+
     |                              |                                     |
     |                           是 (如 '/userdisk/...')               否 (如 'assets/...' 或 './assets/...')
     |                              |                                     |
     |                              v                                     v
     |                      剥离前导 '/' 字符                      剥离可选的前导 './'
     |                              |                                     |
     |                              +------------------+------------------+
     |                                                 |
     |                                                 v
     |                                       拼接到 m_baseDir 之后
     |                               (如 'file:///userdisk/app/80016.../a/')
     |                                                 |
     +------------------------+------------------------+
                              |
                              v
                      标准化后的规范 URL
              (如 'file:///userdisk/app/.../assets/logo.png')
                              |
                              v
                 分发给 JQuick::LoadTask
                              |
                 剥离前导 7 字节 ('file://')
                              |
                              v
                 直接调用底层 POSIX open()
                    读取 Linux 真实文件路径
```

### 2.2 路径行为对照表 (Path Resolution Matrix)

假设当前小程序 `appid` 为 `8001678699362882`（背诵），其主 JS Bundle 路径为：
`file:///userdisk/app/8001678699362882/a/index.js`
则 `m_baseDir` 被初始化为：
`file:///userdisk/app/8001678699362882/a/`

| 传入路径形态 | `rewriteUrl` 判定规则 | 最终重写后的 URL | 实际访问的文件系统 POSIX 路径 | 结果与判定 |
| :--- | :--- | :--- | :--- | :--- |
| `'assets/logo.png'` | 相对路径 | `file:///userdisk/app/.../a/assets/logo.png` | `/userdisk/app/.../a/assets/logo.png` | **成功**（相对于 `app_dir`） |
| `'./assets/logo.png'`| 相对路径（剥离 `./`） | `file:///userdisk/app/.../a/assets/logo.png` | `/userdisk/app/.../a/assets/logo.png` | **成功**（相对于 `app_dir`） |
| `'images/icon.png'` | 相对路径 | `file:///userdisk/app/.../a/images/icon.png` | `/userdisk/app/.../a/images/icon.png` | **成功**（官方 App 最常用方式） |
| `'/userdisk/data.png'`| **以 `/` 开头（根路径陷阱）** | `file:///userdisk/app/.../a/userdisk/data.png` | `/userdisk/app/.../a/userdisk/data.png` | **致命错误**（404 Not Found） |
| `'file:///userdisk/d.png'`| 绝对 URI 协议头 | `file:///userdisk/d.png` (原样保留) | `/userdisk/d.png` | **成功**（访问外部磁盘绝对路径） |
| `'data:image/png;base64,...'`| 内联 Data URI | `data:image/...` (原样保留) | 无（由 `mbedtls` 内存解码） | **成功** |

### 2.3 关键结论与避坑守则

1. **绝对相对化陷阱**：在 Web 思想中，`'/image.png'` 代表从根域名出发。在 Falcon 中，以 `/` 开头的字符串会被当成相对于当前 App 沙箱根目录 `m_baseDir` 的相对路径，并在内部被粗暴地执行 `path = m_baseDir + src.substr(1)`！因此，开发者绝对不能使用 `/userdisk/...` 来访问外置文件。
2. **访问外部用户磁盘的标准语法**：若需要访问由下载器或录音服务保存在 `/userdisk/` 根目录下的文件，必须显式附加 `file:///` 三斜杠协议头：
   ```html
   <!-- 正确：访问用户磁盘外置图片 -->
   <image src="file:///userdisk/download/cover.png" />

   <!-- 错误：会被重写为 app_dir/userdisk/download/cover.png 导致加载失败 -->
   <image src="/userdisk/download/cover.png" />
   ```

---

## 3. 图像解码流水线与像素格式内幕 (Decoding Pipeline & Pixel Formats)

### 3.1 图像解码链与支持格式

在 `JQuick::ImageLoader::loadDrawable`（`0x3654a0`）中，Falcon 构筑了三层回退的解码体系：

```
[原始二进制流 InputStream / FileStream]
                |
                +---> 1. 尝试 LunaSVG 矢量引擎 (greenui::loadSvg)
                |        - 成功: 返回 SvgDrawable
                |        - 失败: 进入下一阶段
                |
                +---> 2. 尝试 GIF 动画解码器 (greenui::GifDecoder::decode)
                |        - 成功: 返回 greenui::GifDrawable
                |        - 失败: 进入下一阶段
                |
                +---> 3. 提交 Skia 栅格解码器 (greenui::BitmapFactory::decodeFile)
                         - 成功: 返回 greenui::BitmapDrawable
                         - 失败: 触发 onError 回调
```

#### 解码器注册验证 (`greenui_init_imagedecoder`, 0x42bc88)
反汇编分析证实，`libfalcon.so` 中仅注册了以下三个 Skia 解码器：
```arm
0x42bc88:  push  {r4, lr}
0x42bc8c:  bl    sk_init_imagedecoder_png()   ; 注册 PNG 解码器
0x42bc90:  bl    sk_init_imagedecoder_jpeg()  ; 注册 JPEG 解码器
0x42bc94:  pop   {r4, lr}
0x42bc98:  b     sk_init_imagedecoder_bmp()   ; 注册 BMP 解码器
```

#### WebP 格式的缺失
在全二进制文本与动态符号表中，检索 `webp`、`WebP`、`libwebp`、`VP8` 结果均为 **0 个符号**。Falcon 运行时**完全不具备 WebP 解码能力**。如果在工程中使用 `.webp` 资源，解码器链遍历耗尽后将抛出空指针，导致图片白屏。

### 3.2 像素格式仲裁：RGB565 vs ARGB8888

对于资源受限的嵌入式设备，显存和内存分配是决定系统流畅度的生命线。Falcon 在像素色彩深度上的选择呈现出“激进压缩与条件降级”并存的特征：

#### 默认偏好配置 (`getPreferredConfig`)
在 `JQuick::ImageLoader::getPreferredConfig()` 中，系统默认硬编码返回枚举值 `2`：
* `1` $\rightarrow$ `SkBitmap::kARGB_8888_Config`（4 字节/像素）
* `2` $\rightarrow$ `SkBitmap::kRGB_565_Config`（2 字节/像素，16位色，无透明度通道）

对于所有标准 JPEG 图片与不带透明通道的 BMP，Falcon 强制使用 `RGB565` 解码，显存开销立刻缩减 50%。

#### PNG 的 Alpha 强制提升逻辑 (`SkPNGImageDecoder::getBitmapConfig`)
反汇编 `0x22e8e0`（`SkPNGImageDecoder::getBitmapConfig`）揭示了至关重要的内存膨胀根源：
```arm
=== 0x22e8e0: SkPNGImageDecoder::getBitmapConfig ===
0x22e8e0:  ldr      r3, [r0, #0x28]        ; 获取用户配置的 preferredConfig (2 = RGB565)
0x22e8e4:  ldrb     r2, [r1, #0x19]        ; 读取 PNG 头部 color_type 与透明标志
0x22e8e8:  tst      r2, #4                 ; 检查是否存在 ALPHA 通道 (PNG_COLOR_MASK_ALPHA)
0x22e8ec:  bne      #0x22e904              ; 存在 Alpha，跳转到强制覆盖分支！
0x22e8f0:  ldrb     r2, [r1, #0x1a]        ; 检查是否存在 tRNS 透明分块
0x22e8f4:  cmp      r2, #0
0x22e8f8:  bne      #0x22e904              ; 存在 tRNS，跳转到强制覆盖分支！
...
0x22e904:  mov      r0, #1                 ; 强制覆盖为 1: kARGB_8888_Config (4 字节/像素)
0x22e908:  bx       lr
```

这意味着：
1. **只要 PNG 带有任何透明信息**（包括哪怕完全不透明的 RGBA PNG，或者带 1 字节透明度标记的索引 PNG）：`SkPNGImageDecoder` 将无视 Falcon 的全局 `RGB565` 偏好，**强制将位图格式拉升为 `ARGB8888`**。
2. **内存消耗瞬间翻倍**：每个像素从 2 字节激增到 4 字节。

---

## 4. 内存缓存架构：JQuick::BitmapCache

### 4.1 缓存池内部实现与限制

Falcon 的图片缓存在 `XImageLoader`（`0x2349bc`）初始化阶段创建，为一个特化的 LRU 缓存模板类 `JQuick::BitmapCache<JQuick::ImageKey>`：
* **数据结构**：采用 `std::map<ImageKey, Entry>`（红黑树快速查找）配合 `std::list<Entry>`（双向链表维护最近最少使用顺序）。
* **容量上限**：在构造函数中，读取配置 `imageloader.image_cache_size`；若无配置，**默认硬编码上限为 4 MB**（`0x400000` = 4,194,304 字节）。

### 4.2 缓存准入与驱逐淘汰反汇编 (`BitmapCache::putCache`)

在 `0x239dc0`（`JQuick::BitmapCache::putCache`）的汇编逻辑中，存在一个极其危险的“大图绝杀分支”：

```arm
=== 0x239dc0: BitmapCache::putCache ===
0x239dcc:  ldr      r5, [r4, #0x28]        ; r5 = m_maxByteCount (默认 0x400000 / 4MB)
0x239dd0:  ldr      r6, [sp, #0x14]        ; r6 = new_bitmap_byte_count (新位图解码字节数)
0x239dd4:  cmp      r6, r5                 ; 检查单个图片是否超过了 4MB！
0x239dd8:  bhi      #0x239e50              ; 超过 4MB，直接跳出并返回 false (拒绝加入缓存！)
...
; 正常的 LRU 淘汰循环
0x239dec:  ldr      r2, [r4, #0x24]        ; 当前缓存总字节数 m_currentByteCount
0x239df0:  add      r3, r2, r6             ; 预测加入后的总字节数
0x239df4:  cmp      r3, r5                 ; 是否超过 4MB?
0x239df8:  bls      #0x239e24              ; 未超过，完成插入
; 超过阈值，从双向链表尾部弹出最旧的 Bitmap 并释放显存
0x239dfc:  ldr      r0, [r4, #0x18]        ; list.tail
0x239e00:  bl       evictEntry()
0x239e04:  b        #0x239dec              ; 循环检查直到空间充裕
```

### 4.3 致命陷阱：超大图片单图拒签 (Oversized Rejection Trap)

当开发者引入一张未经裁剪的背景图（例如 $852 \times 1815$ 的 RGBA PNG，解码尺寸为 $852 \times 1815 \times 4 = 6.04\text{ MB}$）：
1. 由于 $6.04\text{ MB} > 4\text{ MB}$，`putCache` **直接将其拒之门外**，根本不会将其收录到 LRU 链表。
2. **缓存穿透常态化**：该图片在界面中每次重新显示、每次重绘、每次从滚动列表进出视口时，**都必须重新经历一次闪存 IO 读取与完整的 Skia 软解计算**！
3. 在单核/低功耗的 CV1813H SoC 上，一次 6MB 的 PNG 软解需要消耗 180ms ~ 320ms 的 CPU 绝对时间，导致 UI 产生剧烈顿挫（Jank）。

---

## 5. `<scroller>` 滚动容器与图像回收流水线 (Scroller Lifecycle & Virtualization)

长列表渲染是嵌入式设备 OOM（Out Of Memory）崩溃的第一高发区。Falcon 在底层为滚动列表设计了双缓冲式的视图回收机制。

### 5.1 滚动视口回收机制 (`WXScrollView::tryRecycleResources`)

在 `WXScrollView`（`0x396850`）创建时：
* 默认初始化标志位 `m_recyclable = true`（存储在 `WXScrollView + 0x240`）。
* 在用户滑动屏幕、滚动停止（`WXScrollView::onScrollStateChanged`，`0x396db8` 接收到状态值 `0` 即 `SCROLL_STATE_IDLE`）时，立即触发 `WXScrollView::tryRecycleResources()`。

```arm
=== 0x396db8: WXScrollView::onScrollStateChanged(int state) ===
0x396db8:  cmp      r1, #0                 ; state == 0 (SCROLL_STATE_IDLE)
0x396dbc:  bxne     lr                     ; 仍在滚动中则不回收，避免滚动画帧撕裂
0x396dc0:  b        JQuick::WXScrollView::tryRecycleResources()
```

### 5.2 视口外缓冲几何边界 (Recycling Geometry)

反汇编 `0x396b9c`（`WXScrollView::tryRecycleResource(View* child, int offset)`）证实了其边界判定准则：

```
                [上方向缓冲区: 1 个视口高度]
                [-1 * ViewportHeight, 0)
    +------------------------------------------------+
    |                                                |
    |               当前屏幕可见区域 (Viewport)        |  <-- 必须保持渲染
    |                 [0, ViewportHeight]            |
    |                                                |
    +------------------------------------------------+
                [下方向预加载缓冲区: 1 个视口高度]
                (ViewportHeight, 2 * ViewportHeight]
    --------------------------------------------------
                 【回收警戒线: > 2 * ViewportHeight】
                          |
                          v
         触发 dispatchRecycleResource() -> 彻底回收
```

* **安全边界**：$[-1 \times \text{Viewport}, +2 \times \text{Viewport}]$（保留上 1 屏、下 1 屏作为预加载和回滚缓冲）。
* **超出边界**：当子视图完全越过下边界或上边界时，立即调用子视图虚表 `0x4c` 处的 `greenui::View::dispatchRecycleResource()`。

### 5.3 资源回收完整调用链与内存释放

```
WXScrollView::onScrollStateChanged(0)
    |
    v
WXScrollView::tryRecycleResources()
    |
    +-> (遍历子节点, 距离超出 2 倍视口)
    |
    v
greenui::View::dispatchRecycleResource()
    |
    v
greenui::RecycleListener::onRecycle(View*)
    |
    v
JQuick::Component::onRecycle(View*)
    |
    v
JQuick::Component::recycleUnsafe()  (0x37ab5c)
    |  - 递归遍历释放所有子 Component
    |
    v
JQuick::WXImage::onRecycleResource() (0x38eeec)
    |
    +-- 1. m_isLoaded = 0 (重置加载状态)
    +-- 2. m_loadTask.cancel() (取消仍在执行的后台解码线程)
    +-- 3. greenui::ImageView::setImageDrawable(NULL) (剥离底层 BitmapDrawable)
    |
    v
引用计数清零?
    +--> 若该 Bitmap 仍在 4MB BitmapCache 中: 显存保留在缓存池，下次进视口秒开
    +--> 若该 Bitmap 已被挤出 4MB 缓存池: 底层 SkBitmap 内存立即 munmap / free！
```

### 5.4 延迟重新加载 (`tryLazyLoad`)

当用户反向滑动，使先前被回收的 `<image>` 重新切入屏幕时：
1. GreenUI 发起绘制调用链：`greenui::View::draw()` $\rightarrow$ `JQuick::WXImageView::onDraw(Canvas*)`（`0x38bf3c`）。
2. `WXImageView::onDraw` 检测到自身绑定的 `Drawable` 为空（或 `m_isLoaded == 0`），触发 `JQuick::WXImage::tryLazyLoad()`（`0x38bd5c`）。
3. `tryLazyLoad` 请求 `XImageLoader`：
   * **情况 A（缓存命中）**：4MB `BitmapCache` 仍然持有该位图，直接 `setImageDrawable`，0ms 无缝呈现。
   * **情况 B（缓存脱靶 / 滚动雪崩）**：由于滚动列表中包含了数十张大图，总内存轻易撑破 4MB 限制，旧图已在 LRU 队列中被销毁。此时系统必须在主线程/工作线程重新开启闪存读盘和 Skia 软解，导致滑动帧率暴跌至 10~15 fps。

---

## 6. 官方内置小程序静态资产审计 (Official Apps Static Asset Audit)

对有道词典笔原厂固件提取出的真实 App 资源进行深度扫描，全面印证了上述逆向分析成果：

### 6.1 五大核心内置应用资产统计表

| 应用程序 (AppID) | 图像总数 | PNG (带 Alpha) | PNG (不带 Alpha) | JPEG | 磁盘占用 | Falcon 解码后 RAM (实测算法) | 典型超规单图 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Reciter 背诵** (`8001678699362882`) | 300 | **299 (99.7%)** | 1 | 0 | 12.77 MB | **116.02 MB** | `39b46082...png` ($568\times 1210$, 2.68MB) |
| **Launcher 桌面** (`8080222437664451`) | 1002 | **896 (89.4%)** | 104 | 0 | 66.12 MB | **546.31 MB** | `1945c234...png` ($568\times 1210$, 2.68MB) |
| **Shadowing 跟读** (`8080212693101341`) | 373 | **367 (98.4%)** | 0 | 5 | 4.14 MB | **114.54 MB** | `3549e99a...png` ($540\times 1080$, 2.28MB) |
| **Dictation 听写** (`8001679380845889`) | 313 | **308 (98.4%)** | 0 | 5 | 7.55 MB | **165.07 MB** | `countDown01.png` ($852\times 1815$, **6.04MB**) |
| **Settings 设置** (`8080272425914438`) | 1 | 0 | 0 | 0 (1 GIF) | 0.66 MB | **0.00 MB** (动态解) | 无静态常驻大图 |

*(注：系统物理内存仅 128MB，解码内存若大于 128MB 意味着如果将该 App 全部资产一次性放入 DOM 树，将导致 Linux OOM Killer 强杀进程。)*

### 6.2 典型资产解剖与惊人膨胀比

#### 案例 1：听写应用的倒计时大图 (`countDown01.png`)
* **物理分辨率**：$852 \times 1815$（极可能是为平板或手机端设计的资产，未针对词典笔裁剪）。
* **像素格式**：带 Alpha 通道，被强制提升为 `ARGB8888`（4 字节/像素）。
* **单图内存**：$852 \times 1815 \times 4 = 6,185,520\text{ 字节} \approx \mathbf{6.04\text{ MB}}$。
* **致命影响**：单张图片即突破了 Falcon 运行时硬编码的 4MB `BitmapCache` 阈值，**完全无法进入缓存**。倒计时每切换一次数字，CPU 就必须重新解压一次 6MB 的位图。

#### 案例 2：桌面 Launcher 的纯色渐变背景 (`1945c234838103643e02b228e18bf924.png`)
* **物理分辨率**：$568 \times 1210$。
* **磁盘文件大小**：仅 **2.4 KB**（PNG 压缩算法在压缩纯色块时效率极高）。
* **Falcon 解码内存**：$568 \times 1210 \times 4 = \mathbf{2,749,120\text{ 字节}} \approx \mathbf{2.68\text{ MB}}$。
* **膨胀倍率**：**1,130 倍！** 开发者以为引入了一个只有 2KB 的小文件，实际在设备中霸占了近 3MB 的宝贵 RAM。

#### 案例 3：全屏背景与设备视口的悬殊反差
* **S7 Pro 硬件屏幕实际分辨率**：主屏通常为 $240 \times 536$ 或 $172 \times 640$ 级别（超窄长条屏）。
* **官方资产常规分辨率**：普遍采用 $568 \times 1210$（正好是 $284 \times 605$ 的 2 倍视网膜图）。
* **显存浪费率**：$568 \times 1210$ 相比 $240 \times 536$，像素面积高达 5.3 倍！这意味着超过 80% 的内存消耗是无效的下采样冗余。

---

## 7. 内存安全数学模型与开发者终极优化指南 (Optimization Guidelines)

### 7.1 内存开销精确计算公式

在进行 Falcon 小程序架构设计时，必须严格执行位图内存估算：

$$Memory_{\text{Bitmap}} = Width_{\text{pixel}} \times Height_{\text{pixel}} \times Bpp + 64\text{ 字节 (SkBitmap 对象结构体)}$$

其中每像素字节数（$Bpp$）：
* **PNG 带 Alpha 标志 / 带透明块**：$Bpp = 4$（`ARGB8888`）
* **PNG 完全不带 Alpha 块**：$Bpp = 2$（`RGB565`）
* **JPEG 格式**：$Bpp = 2$（`RGB565`）
* **BMP 格式**：$Bpp = 2$（`RGB565`，无透明度时）

### 7.2 针对 CV1813H（128MB RAM）的性能准则

```
+------------------------------------------------------------------+
|                    Falcon 图像优化“五必须五严禁”                   |
+------------------------------------------------------------------+
| 【必须】所有全屏背景严格按目标屏幕物理像素输出 (如 240x536)，禁止 2x/3x  |
| 【必须】不透明图片统一采用 JPEG 或 24 位无 Alpha PNG，享受 RGB565 减半  |
| 【必须】单张图片解码尺寸严格控制在 1MB 以内，绝对禁止单图突破 4MB 缓存线    |
| 【必须】访问 /userdisk/ 绝对路径强制书写 'file:///userdisk/...' 前缀     |
| 【必须】滚动列表必须维持 <scroller> 默认的 recyclable 回收特性            |
+------------------------------------------------------------------+
| 【严禁】严禁在工程中引入 .webp 格式（Falcon 底层无 WebP 解码器）         |
| 【严禁】严禁直接使用以 '/' 开头的绝对路径（会触发根路径重写沙箱陷阱）       |
| 【严禁】严禁在单屏中同时实例化超过 4 张全屏 ARGB8888 背景图 (瞬间挤爆缓存)  |
| 【严禁】严禁在长列表中使用纯 CSS background-image 堆砌大量非回收大图    |
| 【严禁】严禁使用内联巨型 Base64 DataURI（避免 mbedtls 与 JS 堆内存二次翻倍）|
+------------------------------------------------------------------+
```

### 7.3 工程实战：构建期自动降级脚本推荐

建议在前端工程（Vite / Rollup）构建流程中，增加自动处理流水线：
1. **自动剔除 Alpha 通道**：使用 `sharp` 或 `imagemin` 检查，若 Alpha 通道完全为 `255`（不透明），自动导出为无 Alpha 的 24位 PNG 或标准 JPEG。
2. **尺寸规格对齐**：根据词典笔机型（Apollo / Hermes / Olive 等）物理规格，将超过布局宽度 1.2 倍以上的资产自动下采样。

```javascript
// vite.config.js 插件示例片段
import sharp from 'sharp';

function falconImageOptimizer() {
  return {
    name: 'falcon-image-optimizer',
    async transform(code, id) {
      if (/\.(png|jpg|jpeg)$/.test(id)) {
        const image = sharp(id);
        const metadata = await image.metadata();
        // 1. 拦截超出 4MB 缓存红线的大图
        const rawBytes = metadata.width * metadata.height * (metadata.hasAlpha ? 4 : 2);
        if (rawBytes >= 4 * 1024 * 1024) {
          throw new Error(`[Falcon 安全警报] 图片 ${id} 解码尺寸达 ${(rawBytes/1024/1024).toFixed(2)}MB，超出底层 4MB LRU 缓存上限！`);
        }
        // 2. 检查是否有假 Alpha 通道并剥离
        // ...
      }
    }
  };
}
```

---

## 8. 生产实战：WebP 外部转码守护进程与 474px 硬件点对点直通渲染架构

### 8.1 1020×240 超宽带鱼屏物理点对点直通契约 (474px Pixel Mapping)

在有道 S7 Pro（物理面板 240×1020 逆时针旋转 270° 映射为 1020×240 逻辑视口）的实际图文与漫画阅读场景中，图像渲染面临两大硬件级挑战：
1. **摩尔纹（Moiré Pattern）干涉**：嵌入式低 PPI（~110-120 DPI）液晶屏在渲染具有密集排线、网点阴影的漫画原稿时，若以非整数倍比例缩放（如动态根据容器宽度压缩 60%~75%），像素栅格与网点会产生严重的低频干涉波纹；
2. **Skia 线性重采样（Bilinear Resampling）虚边**：低算力 Cortex-A7 处理器在实时执行浮点缩放时，Skia 的线性插值会导致对白文字和高频墨线发虚发灰，且极大消耗 CPU 时间片。

#### 474px 硬件级点对点几何推导：
- 屏幕总宽度：$1020\text{px}$
- 左侧超窄固定功能侧边栏：$48\text{px}$（屏占比 95.3%）
- 剩余有效画卷视口：$1020 - 48 = 972\text{px}$
- 左右边距各保留 $12\text{px}$：$972 - 24 = 948\text{px}$
- 双列并排排版时，单卡片物理宽度锁定为严格的 **474px**：
  $$W_{\text{card}} = \frac{948}{2} = 474\text{px}$$
- **直通渲染铁律**：所有呈现于双列画卷的图像，其物理存储宽度必须预先离线/后台直接采样为 **474px**，`<image>` 组件样式严格指定 `resize: 'cover'`，将 Skia 内部的重采样矩阵退化为单位矩阵（Identity Matrix），实现显存直通硬件 Framebuffer，文字墨迹达到物理视网膜级锐度。

### 8.2 端侧 Linux 后台守护进程与 ARM NEON WebP 转码管线

由于 Falcon 引擎剥离了 WebP 解码器，而用户常通过 USB MTP 导入大量的 `.webp` 格式画集，若在前端处理必然导致页数为 0 或主线程严重假死。为此，必须构建端侧多进程协作转码管线：

#### 1. 后台守护脚本 `/userdisk/bin/webp_daemon.sh`
```bash
#!/bin/sh
# High-Performance WebP Decoder & 474px Point-to-Point Image Optimizer
TARGET_DIRS="/userdisk/Favorite /userdisk/Music /userdisk/skip_re /userdisk/Comics /userdisk/manga"

while true; do
  for root in $TARGET_DIRS; do
    if [ -d "$root" ]; then
      # 第一阶段：发现并转码 WebP
      find "$root" -type f -name "*.webp" 2>/dev/null | while read -r webp_file; do
        target_jpg="${webp_file%.webp}.jpg"
        target_thumb="${webp_file%.webp}_thumb.jpg"
        if [ ! -f "$target_jpg" ]; then
          # 借力 ARM NEON 优化的 ffmpeg 执行高质量转码
          ffmpeg -y -i "$webp_file" -q:v 3 "$target_jpg" -loglevel error </dev/null
          ffmpeg -y -i "$target_jpg" -vf 'scale=474:-1' -q:v 4 "$target_thumb" -loglevel error </dev/null
          if [ -s "$target_jpg" ]; then
            chmod 666 "$target_jpg" "$target_thumb" 2>/dev/null
            rm -f "$webp_file"
          fi
        fi
      done

      # 第二阶段：为已有 JPG/PNG 补齐 474px 点对点直通图
      find "$root" -type f \( -name "*.jpg" -o -name "*.png" \) ! -name "*_thumb.jpg" 2>/dev/null | while read -r img_file; do
        thumb_file="${img_file%.*}_thumb.jpg"
        if [ ! -f "$thumb_file" ]; then
          ffmpeg -y -i "$img_file" -vf 'scale=474:-1' -q:v 4 "$thumb_file" -loglevel error </dev/null
          [ -s "$thumb_file" ] && chmod 666 "$thumb_file" 2>/dev/null
        fi
      done
    fi
  done
  sleep 2
done
```

#### 2. 双转换进度条（Dual Progress Bars）前端可视化
在应用 UI 层建立双独立进度条：
- **WebP 转码进度条**（青蓝 `#38BDF8` $\to$ 翠绿 `#10B981`）：监控 `.webp` 向原生格式转码的张数（如 `54/120`）与百分比；
- **474px 点对点优化进度条**（琥珀 `#F59E0B` $\to$ 翠绿 `#10B981`）：监控硬件点对点直通图生成的张数与百分比。
通过 2 秒增量文件系统签名探测，既不阻塞前端 60FPS 渲染，又让转码与优化过程 100% 透明可视化。

---

## 9. 总结与架构全景结论

1. **组件实现**：Falcon 的 `<image>` 底层由 `JQuick::WXImage` 驱动 `JQuick::WXImageView`，通过 `XImageLoader` 实现异步调度与基于 `SkImageDecoder` 的光栅化绘制。
2. **寻址规则**：相对路径 `'assets/...'` 严格基于 `m_baseDir` 寻址，属于官方推荐的标准写法；前导斜杠 `'/'` 会被解析为沙箱根相对路径，切勿用来寻址磁盘根目录；访问系统真实物理路径必须携带 `file:///`。
3. **格式与色彩深度**：Falcon 仅支持 PNG、JPEG、BMP、SVG 与 GIF，**绝不支持 WebP**。系统默认以 `RGB565` 进行高效解码，但**任何带有 Alpha 通道的 PNG 都会被 Skia 底层强制拉升为 `ARGB8888`**，内存消耗翻倍。
4. **缓存与回收瓶颈**：内置位图缓存池为固定的 4MB LRU 结构，**单图超过 4MB 永远无法被缓存**；`<scroller>` 具备双倍视口边界回收机制，超出视口的子节点会被剥离 Drawable，但当列表中大图总尺寸撑破 4MB 缓存后，用户回滚列表将不可避免地遭遇严重的闪存 IO 与软解性能骤降。
5. **最佳实践**：针对 128MB 嵌入式设备，开发者应严格遵守“精简尺寸、剔除冗余 Alpha、控制单屏总像素、善用 `file:///` 协议”的铁律，方能保障应用 60fps 丝滑运行且永不 OOM。
