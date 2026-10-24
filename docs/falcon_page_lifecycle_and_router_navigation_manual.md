# Falcon Page Lifecycle, Router Navigation & Exit Contracts Manual
**Textbook-Grade Binary Reverse-Engineering & Native Implementation Guide**
**Target Platform: NetEase Youdao Dictionary Pen S7 Pro (CV1813H ARM Cortex-A7 32-bit SoC)**

---

## 1. Executive Summary & Multi-Tier Runtime Architecture

The NetEase Youdao Dictionary Pen S7 Pro runs embedded Linux on a CV1813H (ARMv7-A Cortex-A7 32-bit Little-Endian) SoC. Applications on this platform execute inside **Falcon MiniApp**, a proprietary multi-tier hybrid application runtime developed by NetEase Youdao. Rather than launching each application as an isolated Linux OS process, Falcon hosts multiple concurrent applications as isolated stateful containers inside a single persistent host executable (`/usr/bin/miniapp`).

The Falcon architecture spans three distinct runtime boundaries:
1. **JavaScript & Vue Framework Layer**: QuickJS 2020-07-05 executing precompiled ES module bytecode (`.js.bin`, tag `BC_TAG_MODULE`). The framework runtime (`js-framework.min.bin`) implements a customized Weex / Vue 2.6 virtual DOM engine and the `$_Falcon` master controller.
2. **C++ Native Engine Layer (`libfalcon.so`)**: Coordinates application isolation, window attachment, view hierarchy manipulation, and transition animations through `FalconStack`, `FalconApp`, `FalconPage`, and `FalconPageAnimator`.
3. **JSAPI Proxy & GUI Window Layer (`libjsapi_proxy.so`, `greenui`)**: Manages hardware events, QuickJS C-function bindings, and direct framebuffer surface rendering onto the S7 Pro's 2.98-inch 800×480 landscape display.

```
+----------------------------------------------------------------------------------------------------+
|                                    JavaScript Application Layer                                    |
|   Vue 2.6 Component Hierarchy ($page.finish(), this.$app, this.$page, this.backButtonFunction)     |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                           JS Framework Layer (js-framework.min.bin)                                |
|   $_Falcon Engine: __loadPage, showPage, hidePage, unloadPage, _performPageLifeCycle, Page, App    |
+----------------------------------------------------------------------------------------------------+
                                                  │  QuickJS C-Bindings
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                     Native JSAPI Layer (libfalcon.so / libjsapi_proxy.so)                          |
|   falcon::JSNavigatorHandler (wrap_closePageById: 0x309794, wrap_closeApp: 0x30a1d8)              |
|   JQuick::closeAppForce (0x25d04)                                                                  |
+----------------------------------------------------------------------------------------------------+
                                                  │  JQuick::Looper::getMainLooper()->post()
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                           Native Application Container (libfalcon.so)                              |
|   falcon::FalconApp (closePageById: 0x2f297c, popPage: 0x2f27b4, finish: 0x2ef638)                 |
|   falcon::FalconPageAnimator (launchPage: 0x304c78, popPage: 0x304ed0)                             |
|   falcon::FalconPage (onDestroy: 0x3009a4) -> JQuick::WXInstance::destroy (0x1e3e78)               |
+----------------------------------------------------------------------------------------------------+
                                                  │
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                            Global System Window & Process Stack                                    |
|   falcon::FalconStack (closeApp: 0x23cedc, appDestroyed: 0x23c780, safeGetTopApp: 0x23ce80)        |
|   greenui::NWindow / ViewGroup / DecorView -> DirectFB / /dev/fb0                                  |
|   Launcher Notification: 'app.appFinsih' + caputureImage snapshot                                 |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Core C++ Class Hierarchy & Memory Topologies

Every application running in Falcon is represented as an instance of `falcon::FalconApp`, which is held by the singleton application stack manager `falcon::FalconStack`. Within each `FalconApp`, a navigation history is maintained as an ordered stack of `falcon::FalconPage*` pointers.

### 2.1 Class Virtual Method Tables & Relocations

The virtual tables in `libfalcon.so` dictate the native lifecycle dispatch:

| Class Symbol | Vtable Virtual Address | Relocation Section | Key Methods |
|:---|:---|:---|:---|
| `falcon::FalconApp` | `0x007cfd74` | `.data.rel.ro` | `vtable[2]`: `finish()` (`0x002ef638`)<br>`vtable[4]`: `onAttachToNWindow()` (`0x002ef4a4`)<br>`vtable[8]`: `onStart()` (`0x002f3668`)<br>`vtable[9]`: `onStop()` (`0x002f3814`)<br>`vtable[10]`: `onDestroy()` (`0x002ef648`) |
| `falcon::FalconPage` | `0x007cf850` | `.data.rel.ro` | `vtable[3]`: `onDestroy()` (`0x003009a4`) |
| `falcon::FalconStack::Callback` | `0x007cf268` | `.data.rel.ro` | `appCreated`, `appResumed`, `appPaused`, `appAttached`, `appDetached`, `appDestroyed` |
| `falcon::FalconPageAnimator` | `0x007cff20` | `.data.rel.ro` | `launchPage`, `popPage`, `animationEnd`, `emptyAnimation` |

### 2.2 Reconstructed Memory Layouts

#### `falcon::FalconApp` Memory Layout (Size: ~0x190 bytes)
```cpp
namespace falcon {

class FalconApp : public JQuick::Object {
public:
    void* vptr;                               // +0x00: vtable -> 0x007cfd74
    std::string mAppId;                       // +0x04: Application ID (e.g. "8080272425914438")
    std::string mAppName;                     // +0x1c: Application Name / Title
    std::string mAppPath;                     // +0x34: Absolute filesystem path
    std::string mDataDir;                     // +0x4c: /userdisk/secondary/miniapp/data/mini_app/pkg/<id>/
    std::string mVersion;                     // +0x64: Version string
    std::string mCategory;                    // +0x7c: Category string
    std::string mNickName;                    // +0x94: Localized display name
    uint32_t mFlags;                          // +0xac: App capability bitmask
    bool mIsSystemApp;                        // +0xb0: System app privilege flag
    bool mIsStarted;                          // +0xb1: Set true after start() completes
    bool mIsShowing;                          // +0xb2: Visible in foreground
    bool mDisableLeftSwipeBack;               // +0xb3: If true, suppresses edge swipe gesture
    bool mSupportBack;                        // +0xb4: If true, handles hardware back key
    bool mSupportTopPanel;                    // +0xb5: If true, top status bar can pull down
    bool mIsDestroyed;                        // +0xb6: Guard against double-destruction
    uint8_t mPad0[5];                         // +0xb7
    bool mIsAttached;                         // +0xbc: NWindow attachment status
    uint8_t mPad1[3];                         // +0xbd
    FalconJSBridge* mJSBridge;                // +0xc0: Pointer to QuickJS bridge container
    greenui::NWindow* mWindow;                // +0xc8: Embedded GUI native window
    std::vector<FalconPage*> mPages;          // +0xcc: Begin pointer
                                              // +0xd0: End pointer
                                              // +0xd4: Capacity pointer
    FalconPageAnimator mPageAnimator;         // +0xd8: Transition animation manager (size ~0x60)
    // ... remaining private fields and callback lists
};

} // namespace falcon
```

#### `falcon::FalconPage` Memory Layout (Size: ~0x110 bytes)
```cpp
namespace falcon {

class FalconPage : public JQuick::Object {
public:
    void* vptr;                               // +0x00: vtable -> 0x007cf850
    JQuick::WXInstance* mWXInstance;          // +0x04: Weex / VDOM instance handle
    std::string mPageId;                      // +0x08: Unique UUID / string ID
    std::string mPageName;                    // +0x20: Page relative path (e.g. "pages/index/index")
    std::string mUrl;                         // +0x38: Full bundle URI
    std::string mTemplate;                    // +0x50: VDOM template source
    std::string mOptions;                     // +0x68: JSON stringified launch options
    greenui::ViewGroup* mRootView;            // +0x80: Native UI view tree container
    FalconApp* mApp;                          // +0xfc: Back-pointer to parent FalconApp
    // ...
};

} // namespace falcon
```

---

## 3. Exhaustive Reverse-Engineering of `this.$page.finish()`

`this.$page.finish()` is the foundational primitive for closing a screen. Its end-to-end execution path crosses four execution contexts: JavaScript Vue component, QuickJS JSAPI wrapper, Main Native UI Looper, and Window Hierarchy Manager.

### 3.1 Step 1: Component Invocation & `Page.prototype.finish`

In official miniapps (e.g. `BasePage-ae78eaab.js.bin`), clicking the navigation bar back arrow triggers:
```javascript
backButtonClicked() {
    this.backButtonFunction() || this.$page.finish();
}
```
In `js-framework.min.bin`, `Page` is a class whose prototype contains the `finish` method (QuickJS constant pool entry 145):
```javascript
// Disassembled from js-framework.min.bin cpool[145]
Page.prototype.finish = function() {
    this.$falcon.closePageById(this.$pageId);
};
```
Here, `this.$pageId` is the string ID assigned during page creation (e.g. `"1"`), and `this.$falcon` is the native bridge bound to the global JS context.

### 3.2 Step 2: Native QuickJS Binding: `wrap_closePageById`

`$falcon.closePageById` is registered as a QuickJS native C-function wrapper:
- **Symbol**: `falcon::JSNavigatorHandler::wrap_closePageById(JSContext*, uint64_t, int, uint64_t*)`
- **Virtual Address**: `0x00309794` in `libfalcon.so`

#### Disassembled ARM Assembly (`0x00309794`):
```armasm
00309794 <_ZN6falcon18JSNavigatorHandler18wrap_closePageByIdEP9JSContextyRxPy>:
  309794: e92d4df0     push    {r4, r5, r6, r7, r8, sb, sl, fp, lr}
  309798: e1a06000     mov     r6, r0              @ r6 = JSContext*
  30979c: e59fa2bc     ldr     sl, [pc, #0x2bc]    @ GOT offset
  3097a0: e24dd044     sub     sp, sp, #68
  3097a4: e08fa00a     add     sl, pc, sl          @ Relocate GOT base
  3097a8: e3520000     cmp     r2, #0              @ Check argc > 0
  3097ac: 0a000010     beq     0x3097f4            @ If argc == 0, abort with error
  3097b0: e5930000     ldr     r0, [r3]            @ r0 = argv[0] (JSValue pageId)
  3097b4: e5931004     ldr     r1, [r3, #4]        @ Tag of argv[0]
  3097b8: e1a02006     mov     r2, r6
  3097bc: e28d7028     add     r7, sp, #40         @ Local std::string for pageId
  3097c0: e1a00007     mov     r0, r7
  3097c4: ebfb5883     bl      0x1dfe38 <JSValueToString> @ Convert JSValue to C++ std::string
  ...
  309830: ebfb6540     bl      0x1e2d38 <JQuick::Looper::getMainLooper> @ Get UI thread looper
  309834: e1a04000     mov     r4, r0              @ r4 = MainLooper*
  309838: e28d1018     add     r1, sp, #24         @ Bind arguments
  30983c: ebfb5d21     bl      0x1e0cc8 <JQuick::bind<closePage>>
  309840: e1a00004     mov     r0, r4
  309844: ebfb5e00     bl      0x1e104c <JQuick::Looper::postTask> @ Post task to Main Thread
  309848: e8bd8df0     pop     {r4, r5, r6, r7, r8, sb, sl, fp, pc}
```

The function performs three essential tasks:
1. Validates that `argc >= 1` and extracts `pageId` from `argv[0]`.
2. Inspects `argv[1]` (if present) to deserialize navigation animation options from a JS Object into `std::map<std::string, std::string>`.
3. Binds the invocation to `falcon::closePage` and posts it via `JQuick::Looper::getMainLooper()->postTask()`, guaranteeing that UI modifications execute exclusively on the main UI thread.

### 3.3 Step 3: Thread Dispatch to `falcon::closePage`

The posted task executes `falcon::closePage`:
- **Symbol**: `falcon::closePage(JQuick::sp<falcon::FalconApp>, std::string const&, bool)`
- **Virtual Address**: `0x003083a0` in `libfalcon.so`

```armasm
003083a0 <_ZN6falcon9closePageEN6JQuick2spINS_9FalconAppEEERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEb>:
  3083a0: e92d41f0     push    {r4, r5, r6, r7, r8, lr}
  3083a4: e1a04000     mov     r4, r0              @ r4 = sp<FalconApp>
  3083a8: e1a05001     mov     r5, r1              @ r5 = pageId string reference
  3083ac: e5940000     ldr     r0, [r4]            @ r0 = FalconApp*
  3083b0: e3500000     cmp     r0, #0
  3083b4: 0a000010     beq     0x3083fc            @ Null-pointer check
  3083b8: e1a01005     mov     r1, r5              @ arg1 = pageId
  3083bc: e28d2008     add     r2, sp, #8          @ arg2 = empty options map
  3083c0: ebfba96d     bl      0x2f297c <_ZN6falcon9FalconApp13closePageByIdERKNSt7__cxx11...Ev>
  3083c4: e8bd81f0     pop     {r4, r5, r6, r7, r8, pc}
```

### 3.4 Step 4: Native Core Execution: `FalconApp::closePageById`

- **Symbol**: `falcon::FalconApp::closePageById(std::string const&, std::map<std::string, std::string> const&)`
- **Virtual Address**: `0x002f297c` in `libfalcon.so`

```armasm
002f297c <_ZN6falcon9FalconApp13closePageByIdERKNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEERKSt3map...>:
  2f297c: e92d4ff0     push    {r4, r5, r6, r7, r8, r9, sl, fp, lr}
  2f2980: e1a04000     mov     r4, r0              @ r4 = this (FalconApp*)
  2f2984: e59480cc     ldr     r8, [r4, #0xcc]     @ r8 = mPages.begin()
  2f2988: e59470d0     ldr     r7, [r4, #0xd0]     @ r7 = mPages.end()
  2f298c: e0479008     sub     r9, r7, r8          @ r9 = byte count of vector
  2f2990: e1b09149     asrs    r9, r9, #2          @ r9 = page_count = count / 4
  2f2994: 0a000030     beq     0x2f2a5c            @ If mPages is empty, exit
  2f2998: e3590001     cmp     r9, #1              @ Check page_count == 1
  2f299c: 0a000045     beq     0x2f2ab8            @ CRITICAL: Jump to Finish App!
  ... (Multi-page pop logic)
  2f2ab8: e1a00004     mov     r0, r4              @ r0 = FalconApp*
  2f2abc: e5943000     ldr     r3, [r4]            @ r3 = vtable
  2f2ac0: e5933008     ldr     r3, [r3, #8]        @ vtable[2] = FalconApp::finish()
  2f2ac4: e12fff33     blx     r3                  @ Call finish()!
```

#### The Architectural Fork:
At offset `0x2f2998`, the ARM assembly computes the size of `mPages` (`(end - begin) / 4`):
- **Branch A (`page_count > 1`)**:
  1. The target page is located in `mPages`.
  2. The target page and the underlying page are passed to `FalconPageAnimator::popPage(target, prev, animParam)` (`0x00304ed0`).
  3. The underlying page is made visible, has its touch handlers restored, and receives `FalconPage::onStart()`.
  4. The target page is popped from `mPages`.
  5. The target page view is detached from `greenui::NWindow`.
  6. `FalconPage::onDestroy()` (`0x003009a4`) is invoked on the popped page.
- **Branch B (`page_count == 1`)**:
  1. The assembly explicitly jumps to `0x2f2ab8`.
  2. Loads `vtable[2]` from the `FalconApp` vtable (`0x007cfd74`).
  3. Executes `FalconApp::finish()` (`0x002ef638`).
  4. Triggers global application termination, window release, and launcher resumption!

---

## 4. Native Page Transitions, Animations & Stack Orchestration

Falcon utilizes a dedicated animation controller: `falcon::FalconPageAnimator`.

### 4.1 Page Push Pipeline: `FalconApp::launchPage`

When navigating to a new page (`$falcon.navToPage(pageName, params)`):
1. **Instantiation**: `FalconApp::launchPage` (`0x002f645c`) allocates a new `FalconPage`, creates a dedicated `JQuick::WXInstance`, and pushes it to `mPages`.
2. **Animation Setup**: Invokes `FalconPageAnimator::launchPage` (`0x00304c78`).
3. **Transition Coordinates**:
   - The outgoing page (current top) animates from `X = 0` to `X = -display_width` (leftward slide).
   - The incoming page animates from `X = display_width` to `X = 0` (slide in from right).
4. **Lifecycle Triggering**:
   - Incoming page: `$_Falcon.loadPage()` -> `onLoad` -> `beforeVueInstantiate` -> `$mount('#root')` -> `onShow`.
   - Outgoing page: `$_Falcon.hidePage()` -> `onHide`.

### 4.2 Page Pop Pipeline: `FalconApp::popPage`

When popping a page (`FalconApp::popPage` at `0x002f27b4`):
1. **Animator Invocation**:
   - `FalconPageAnimator::popPage(FalconPage* outPage, FalconPage* inPage, AnimationParam const&)` (`0x00304ed0`).
2. **Coordinate Physics**:
   - Outgoing page animates from `X = 0` to `X = display_width` (slide out to right).
   - Incoming underlying page animates from `X = -display_width` back to `X = 0`.
3. **Animation Completion Callback**:
   - Bound to `FalconPageAnimator::animationEnd(bool)` (`0x00304574`).
   - Upon completion, the animator drops the outgoing page's native view reference.

### 4.3 Native Destruction: `FalconPage::onDestroy`

- **Symbol**: `falcon::FalconPage::onDestroy()`
- **Virtual Address**: `0x003009a4` in `libfalcon.so`

```armasm
003009a4 <_ZN6falcon10FalconPage9onDestroyEv>:
  ...
  300b00: e2840004     add     r0, r4, #4          @ r0 = &this->mWXInstance
  300b04: e3a01000     mov     r1, #0              @ Clear context pointer
  300b08: ebfb759c     bl      0x1de180 <JQuick::WXInstance::setContext>
  300b0c: e59400d0     ldr     r0, [r4, #0xd0]     @ Check JSBridge
  300b10: e3500000     cmp     r0, #0
  300b14: 0a000011     beq     0x300b60
  300b18: e2841010     add     r1, r4, #16         @ r1 = &this->mPageId
  300b20: e8bd41f0     pop     {r4, r5, r6, r7, r8, lr}
  300b24: eafb610d     b       0x1d8f60 <_ZN6falcon14FalconJSBridge10unloadPage...Ev>
```

At `0x300b24`, `FalconPage::onDestroy` tails directly into `FalconJSBridge::unloadPage(std::string const& pageId)` (`0x002fad24`), which posts an asynchronous message to the QuickJS thread:
```javascript
// Disassembled from js-framework.min.bin cpool[179]
unloadPage(pageId) {
    this._performPageLifeCycle(pageId, 'onUnload', null, 'unload');
    this._pageMap.delete(pageId);
}
```
Finally, native execution calls `JQuick::WXInstance::destroy()` (`0x1e3e78`), destroying the VDOM tree, detaching all GreenUI views, and freeing associated graphic buffers.

---

## 5. The Falcon Exit & Back-Navigation Taxonomy

A major source of developer confusion on the NetEase S7 Pro is distinguishing between the various exit and navigation contracts. The following matrix summarizes their exact native mechanisms:

### 5.1 Contract Comparison Matrix

| Method | Invocation Signature | Native Function / Vtable Slot | Stack Scope | Process Impact | Screen / Transition Result |
|:---|:---|:---|:---|:---|:---|
| **Page Finish** | `this.$page.finish()` | `FalconApp::closePageById` (`0x2f297c`) | Single Page (or App if last page) | Preserves `miniapp` process | If `stack > 1`: Animates back to previous page.<br>If `stack == 1`: Exits to Launcher. |
| **Hardware Back** | Hardware Back Button / Edge Swipe | `FalconApp::handleBackPress` (`0x2f2f80`) | Single Page | Preserves `miniapp` process | Calls `BasePage.backButtonClicked()` -> `this.$page.finish()`. Suppressed if `disableLeftSwipeBack` is set. |
| **Close App** | `$falcon.closeApp()` / `this.$app.finish()` | `JSNavigatorHandler::wrap_closeApp` (`0x30a1d8`) -> `JQuick::closeAppForce` (`0x25d04`) | Entire App Container | Preserves `miniapp` process | Immediately destroys all pages in `mPages`, executes `FalconApp::onDestroy()`, returns to Launcher. |
| **Exit App** | `$falcon.exitApp()` | Alias for `closeApp()` | Entire App Container | Preserves `miniapp` process | Identical to `closeApp()`. |
| **Weex Router Back** | `router.back()` / `navigator.pop()` | Weex Navigator JS Wrapper | Current Page | Preserves `miniapp` process | Maps internally to `closePageById(currentPageId)`. |
| **Move To Back** | `$falcon.moveToBack()` | `FalconApp::moveToBack` (`0x2f44bc`) | Preserves Stack | Preserves `miniapp` process | App is hidden (`app.appHide`); underlying app is brought to front. App state is retained in RAM. |
| **System Exit** | `process.exit()` / `system.exit()` | Native libc `exit(0)` / `_exit(0)` | Entire System Subsystem | **KILLS ENTIRE PROCESS** | **FATAL**: Terminates the host `/usr/bin/miniapp` process! Kills Launcher, System UI, and Topbar. Causes watchdogs to reboot or crash the device! |

---

### 5.2 Deep-Dive: Hardware Back Key & Edge Swipe Gesture

The S7 Pro features a capacitive touch screen supporting edge-swipe navigation, as well as a physical return button.
1. When a back event arrives, the input subsystem invokes `falcon::FalconApp::handleBackPress()` (`0x002f2f80`).
2. `handleBackPress` inspects:
   - `mDisableLeftSwipeBack` (offset `0xb3` in `FalconApp`).
   - If disabled (`setDisableLeftSwipeBack(true)` called via `$falcon.setDisableLeftSwipeBack(true)`), the gesture is consumed and ignored.
   - If enabled, native evaluates whether the active Vue component has registered an interception hook.
3. In Vue standard templates, `BasePage-ae78eaab.js.bin` exposes:
   ```javascript
   props: {
       backButtonFunction: {
           type: Function,
           default: null
       }
   },
   methods: {
       backButtonClicked() {
           if (this.backButtonFunction) {
               const handled = this.backButtonFunction();
               if (handled) return;
           }
           this.$page.finish();
       }
   }
   ```
   If `backButtonFunction` returns `true`, the default exit is intercepted. If it returns falsy or is undefined, `this.$page.finish()` is executed.

---

### 5.3 Deep-Dive: Direct App Termination (`$falcon.closeApp()`)

When an application decides to terminate completely regardless of navigation history (e.g., in `homeModel.js.bin` or settings reset), it calls `$falcon.closeApp()`.

#### Assembly Breakdown of `JSNavigatorHandler::wrap_closeApp` (`0x0030a1d8`):
```armasm
0030a1d8 <_ZN6falcon18JSNavigatorHandler13wrap_closeAppEP9JSContextyRxPy>:
  30a1d8: e92d41f0     push    {r4, r5, r6, lr}
  30a1dc: e1a04000     mov     r4, r0              @ r4 = JSContext*
  30a1e0: e59fa044     ldr     sl, [pc, #0x44]     @ GOT offset
  30a1e4: e24dd010     sub     sp, sp, #16
  30a1e8: e08fa00a     add     sl, pc, sl          @ Relocate GOT base
  ...
  30a200: ebfb5883     bl      0x1e03a0 <falcon::FalconApp::safeGet> @ Retrieve active FalconApp
  30a204: e1a05000     mov     r5, r0              @ r5 = FalconApp*
  30a208: e3550000     cmp     r5, #0
  30a20c: 0a000006     beq     0x30a22c
  30a210: e5950004     ldr     r0, [r5, #4]        @ r0 = mAppId
  30a214: e3a01001     mov     r1, #1              @ force = true
  30a218: ebfb53a0     bl      0x1df0a0 <JQuick::closeAppForce> @ Cross-boundary proxy call
  30a21c: e8bd81f0     pop     {r4, r5, r6, pc}
```

`JQuick::closeAppForce` in `libjsapi_proxy.so` (`0x00025d04`) dispatches to `falcon::FalconStack::closeApp(appId, bool)` (`0x0023cedc`), which unconditionally executes:
1. `FalconApp::finish()` (`0x002ef4d4`).
2. Iterates over all pages in `mPages` and calls `FalconPage::onDestroy()` for each page.
3. Invokes `FalconApp::onDestroy()` (`0x002ef648`), destroying the JS bridge and Weex instances.
4. Invokes `FalconStack::appDestroyed(FalconApp*)` (`0x0023c780`).
5. `FalconStack` removes the app from the active container list and raises the underlying application (or Launcher).

---

### 5.4 Deep-Dive: Launcher Notification & Transition Animation

When an app finishes or is sent to the background, `FalconStack` and `FalconApp` notify the Launcher. In `libfalcon.so`:
- At `0x00734b60`: Literal string `"app.appFinsih"` (note the vendor typo in the symbol).
- At `0x00734b70`: Literal string `"app.appHide"`.

When `FalconApp::onDestroy` completes, `FalconStack` dispatches a global broadcast event:
```cpp
JQuick::Json eventData;
eventData["caputureImage"] = capturedSnapshotPath; // e.g. "/tmp/snapshot_last.png"
FalconStack::sendAppEvent("app.appFinsih", eventData);
```

In the Launcher (`8080222437664451/a/vScreenIndex-2df5199e.js.bin`):
```javascript
// Disassembled from Launcher vScreenIndex
data: {
    exitAppAnimationComponent: '',
    caputureImage: '',
    appFinishEvent: 'app.appFinsih',
    appHideEvent: 'app.appHide'
},
// Event listener callback
onAppFinish(event) {
    this.caputureImage = event.caputureImage;
    this.exitAppAnimationComponent = 'ExitAppAnimation';
},
onExitAppAnimationFinished() {
    this.exitAppAnimationComponent = '';
    this.caputureImage = '';
}
```
The Launcher dynamically mounts `ExitAppAnimation`, renders the captured snapshot of the exiting app, scales it down into the launcher card slot, and restores full interactive touch to the desktop.

---

## 6. Vue Runtime Injection Mechanics (`$page`, `$app`, `$falcon`)

A crucial architectural feature of Falcon is how `$page` and `$app` become accessible within Vue component methods (`this.$page`, `this.$app`, `this.$falcon`).

### 6.1 Bootstrapping: `$_Falcon.__loadPage`

In `js-framework.min.bin` (cpool[174]), `$_Falcon.__loadPage` executes when a page is initialized:

```javascript
__loadPage(component, pageName, instance, pageId, Vue, options, extra) {
    let page;
    if (component.prototype instanceof Page) {
        page = new component();
    } else {
        page = new this.Page();
        page._component = component;
        page._component_only = true;
    }

    page._instance = instance;
    this._pageMap.set(pageId, page);
    page.$pageName = pageName;
    page.$pageId = pageId;
    page.$app = this.$app;
    page.$falcon = this;

    // 1. Register Native Weex Modules onto Page
    const modules = instance.getRegisteredModules();
    for (const modName in modules) {
        const propName = '$' + modName;
        if (!page[propName]) {
            page[propName] = instance.requireModule(modName);
        }
    }

    // 2. Install Falcon Plugin into Vue
    Vue.cid = pageId;
    Vue.use(function(VueConstructor) {
        VueConstructor.prototype.$instanceId = pageId;
        VueConstructor.prototype.$document = (typeof weex !== 'undefined') ? weex.document : document;
        VueConstructor.prototype.$requireWeexModule = instance.requireModule.bind(instance);
        VueConstructor.prototype.$falcon = this;         // Reference to $_Falcon
        VueConstructor.prototype.$app = this.$app;       // Reference to App instance
        VueConstructor.prototype.$page = page;           // Reference to Page instance
    }.bind(this));

    // 3. Configure Global Error Handler
    Vue.config.errorHandler = this._vueErrorHandler.bind(this);

    // 4. Trigger Early Lifecycles
    this._performPageLifeCycle(pageId, 'onLoad', options, 'load');
    this._performPageLifeCycle(pageId, 'beforeVueInstantiate', Vue, 'beforeVueInstantiate');

    // 5. Mount Root Component
    page.$root = new Vue(page._component);
    page.$root.$_page = page;
    page.$root.$mount('#root');
}
```

### 6.2 Injection Breakdown & Scoping Rules

1. **Vue Prototype Inheritance**: Because `Vue.use()` modifies `Vue.prototype`, every single Vue component instance created within that page inherits `this.$page`, `this.$app`, and `this.$falcon` through the standard JavaScript prototype chain.
2. **Page Isolation**: Because each page executes in its own scope with a unique `pageId` and `page` instance, `Vue.prototype.$page` is bound to that specific page's `FalconPage` container.
3. **App Singleton**: All pages within the same mini-app reference the exact same `this.$app` singleton, allowing cross-page state sharing via `this.$app.globalData`.

---

## 7. Complete C++ to JS Lifecycle Pipeline

The Falcon lifecycle consists of coordinated handshakes between the C++ engine and the JavaScript runtime.

```
       Native C++ Layer                            JavaScript Framework Layer
+-----------------------------+               +----------------------------------+
|  FalconApp::launchPage()    |               |                                  |
|  0x002f645c                 |               |                                  |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconPage::FalconPage()   |               |                                  |
|  Allocates WXInstance       |               |                                  |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconJSBridge::loadPage() |──────────────>|  $_Falcon.loadPage()             |
|  Dispatches to JS Thread    |               |  Creates Page instance           |
|                             |               |             │                    |
|                             |               |             ▼                    |
|                             |               |  Page.onLoad(options)            |
|                             |               |             │                    |
|                             |               |             ▼                    |
|                             |               |  Page.beforeVueInstantiate(Vue)  |
|                             |               |  Vue.$mount('#root')             |
|                             |               |             │                    |
|                             |               |             ▼                    |
|  FalconPageAnimator::       |<──────────────|  Mount Complete / DOM Ready      |
|  launchPage() (0x304c78)    |               |                                  |
|  Slides views into display  |               |                                  |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconApp::onStart()       |──────────────>|  $_Falcon.showPage()             |
|  0x002f3668                 |               |  Page.onShow()                   |
|                             |               |                                  |
|   === PAGE ACTIVE ===       |               |   === COMPONENT INTERACTION ===  |
|                             |               |                                  |
|  User invokes $page.finish()|<──────────────|  this.$page.finish()             |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconApp::closePageById() |               |                                  |
|  0x002f297c                 |               |                                  |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconPageAnimator::       |               |                                  |
|  popPage() (0x304ed0)       |               |                                  |
|             │               |               |                                  |
|             ▼               |               |                                  |
|  FalconPage::onDestroy()    |──────────────>|  $_Falcon.hidePage()             |
|  0x003009a4                 |               |  Page.onHide()                   |
|             │               |               |             │                    |
|             │               |               |             ▼                    |
|  FalconJSBridge::unloadPage |──────────────>|  $_Falcon.unloadPage()           |
|  0x002fad24                 |               |  Page.onUnload()                 |
|             │               |               |  _pageMap.delete(pageId)         |
|             ▼               |               +----------------------------------+
|  WXInstance::destroy()      |
|  0x001e3e78                 |
|  Frees native views & DOM   |
+-----------------------------+
```

### 7.1 State Machine Matrix

| Lifecycle Hook | Trigger Event | Context / Thread | Valid Operations | Invalid Operations |
|:---|:---|:---|:---|:---|
| **`onLoad(options)`** | Page script evaluated, before DOM mount | JS Thread | Read route parameters, initialize state, fetch local storage data | Interacting with DOM/refs (`this.$refs` is undefined) |
| **`beforeVueInstantiate(Vue)`**| Immediately prior to `new Vue()` | JS Thread | Install local Vue mixins, components, or filters | Calling `$page.finish()` |
| **`onShow()`** | Page becomes visible / transitions in | Main UI Thread + JS | Start timers, register hardware listeners (audio/MIC), update UI | Blocking heavy sync operations (stalls animation) |
| **`onHide()`** | Page covered by new page or minimized | Main UI Thread + JS | Pause timers, pause audio playback, release camera handle | Modifying VDOM layout |
| **`onUnload()`** | Page popped from stack / destroyed | JS Thread | Cancel network requests, release subscriptions, clear intervals | Starting new asynchronous navigation |
| **`onDestroy()`** | Entire App container terminating | Native C++ + JS | Release database handles, finalize persistent files | Attempting to navigate or open new pages |

---

## 8. Production Code Examples & Developer Patterns

### 8.1 Pattern 1: Multi-Page Navigation with Parameter Passing

#### Source Page (`pages/index/index.vue`):
```vue
<template>
  <div class="container">
    <text class="title">Main Dashboard</text>
    <div class="button" @click="openDetail">
      <text class="btn-text">Open Item 42</text>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    openDetail() {
      // In Falcon, navigation is invoked via $falcon.navToPage
      this.$falcon.navToPage('pages/detail/detail', {
        itemId: '42',
        from: 'dashboard'
      });
    }
  }
};
</script>
```

#### Destination Page (`pages/detail/detail.vue`):
```vue
<template>
  <div class="container">
    <div class="header">
      <div class="back-btn" @click="goBack">
        <text class="back-text">Back</text>
      </div>
      <text class="title">Item: {{ itemId }}</text>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      itemId: ''
    };
  },
  onLoad(options) {
    // Parameters passed in navToPage arrive in onLoad
    if (options && options.itemId) {
      this.itemId = options.itemId;
    }
  },
  methods: {
    goBack() {
      // Cleanly pop this page from the stack
      this.$page.finish();
    }
  }
};
</script>
```

---

### 8.2 Pattern 2: Custom Hardware & Edge-Swipe Interception

Use this pattern when user confirmation (e.g. unsaved changes dialog) is required before exiting:

```vue
<template>
  <div class="container">
    <!-- Embed standard BasePage for navigation and hardware handling -->
    <base-page :back-button-function="handleBack">
      <div class="content">
        <text>Form Editor</text>
      </div>
    </base-page>

    <!-- Modal Dialog -->
    <div v-if="showExitDialog" class="dialog-mask">
      <div class="dialog-box">
        <text class="dialog-text">Discard unsaved changes?</text>
        <div class="dialog-buttons">
          <div class="btn cancel" @click="showExitDialog = false">
            <text>Cancel</text>
          </div>
          <div class="btn confirm" @click="confirmExit">
            <text>Discard & Exit</text>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      isDirty: true,
      showExitDialog: false
    };
  },
  methods: {
    handleBack() {
      // Intercept back button if dirty
      if (this.isDirty) {
        this.showExitDialog = true;
        // Return true to signal that back navigation is consumed!
        return true;
      }
      // Return false to allow default this.$page.finish()
      return false;
    },
    confirmExit() {
      this.isDirty = false;
      this.showExitDialog = false;
      // Explicitly exit now that user has confirmed
      this.$page.finish();
    }
  }
};
</script>
```

---

### 8.3 Pattern 3: Explicit Clean App Exit

Use this pattern on the primary root page or when implementing a settings exit button:

```javascript
export default {
  methods: {
    exitApplication() {
      // 1. Perform component-level cleanup
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }

      // 2. Terminate the application container
      // If stack depth is 1, $page.finish() triggers FalconApp::finish()
      if (this.$page) {
        this.$page.finish();
      } else if (this.$falcon && this.$falcon.closeApp) {
        // Fallback: Force unconditional app close
        this.$falcon.closeApp();
      }
    }
  }
};
```

---

### 8.4 Pattern 4: Resource-Safe Audio Lifecycle Mixin

On the S7 Pro, failing to release audio handles when pages hide or unload causes system-wide audio pipeline freezes:

```javascript
// lifecycle-audio-mixin.js
export default {
  data() {
    return {
      audioPlayer: null,
      isPlaying: false
    };
  },
  onLoad() {
    // Acquire native media player service
    if (this.$requireWeexModule) {
      this.audioPlayer = this.$requireWeexModule('mediaPlayerService');
    }
  },
  onHide() {
    // Pause playback when page is obscured or screen turns off
    if (this.audioPlayer && this.isPlaying) {
      this.audioPlayer.pause();
      this.isPlaying = false;
    }
  },
  onUnload() {
    // Completely stop and release hardware audio focus on destroy
    if (this.audioPlayer) {
      this.audioPlayer.stop();
      this.audioPlayer.release();
      this.audioPlayer = null;
    }
  }
};
```

---

## 9. Pitfalls, Diagnostic Checklists & Edge-Case Runbook

### 9.1 The Top 5 Navigation Pitfalls

1. **Invoking `process.exit(0)` or `system.exit()`**:
   - *Symptom*: Dictionary pen screen flashes black; dictionary pen locks up or restarts to splash screen.
   - *Cause*: Terminates `/usr/bin/miniapp`, destroying the entire GUI system server.
   - *Remedy*: Never call process-level exit. Always call `this.$page.finish()` or `this.$falcon.closeApp()`.

2. **Calling `this.$page.finish()` inside `onLoad()`**:
   - *Symptom*: Crash or undefined behavior during `FalconPageAnimator::launchPage`.
   - *Cause*: In `libfalcon.so`, the incoming page is still transitioning onto the screen. Calling `finish()` before `animationEnd()` executes corrupts the animator state machine.
   - *Remedy*: Delay early finish calls until `onShow()` or inside `this.$nextTick()`.

3. **Memory Leaks via Persistent Singletons in `this.$app`**:
   - *Symptom*: S7 Pro RAM exhaustion (total RAM is constrained to 512MB/1GB).
   - *Cause*: Attaching large object arrays or event callbacks to `this.$app` prevents garbage collection when individual pages unload.
   - *Remedy*: Explicitly purge page-specific state in `onUnload()`.

4. **Confusing `$falcon.moveToBack()` with `$page.finish()`**:
   - *Symptom*: Application stays alive in RAM and continues running timers or battery drain.
   - *Cause*: `moveToBack()` hides the window and fires `app.appHide`, but does **not** call `FalconPage::onDestroy()`.
   - *Remedy*: Use `moveToBack()` only for background audio players. For exiting, use `finish()`.

5. **Missing `Vue.cid` Isolation in Dynamic Component Chunks**:
   - *Symptom*: Mixins or components from Page B leak into Page A.
   - *Cause*: Vue plugins installed via `Vue.use()` are globally registered if the module bundler does not isolate the `Vue` constructor per page.
   - *Remedy*: Respect the Falcon framework's scoped `Vue` constructor passed in `beforeVueInstantiate(Vue)`.

---

## 10. Binary Offset & Symbol Quick-Reference Table

For reverse engineers verifying patches or writing dynamic hooks (e.g. Frida or LD_PRELOAD):

| Target Symbol | Library | Virtual Address | File Offset |
|:---|:---|:---|:---|
| `falcon::JSNavigatorHandler::wrap_closePageById` | `libfalcon.so` | `0x00309794` | `0x00309794` |
| `falcon::JSNavigatorHandler::wrap_closeApp` | `libfalcon.so` | `0x0030a1d8` | `0x0030a1d8` |
| `falcon::JSNavigatorHandler::wrap_navToPage` | `libfalcon.so` | `0x00309320` | `0x00309320` |
| `falcon::JSNavigatorHandler::wrap_navToApp` | `libfalcon.so` | `0x00309540` | `0x00309540` |
| `falcon::closePage` | `libfalcon.so` | `0x003083a0` | `0x003083a0` |
| `falcon::FalconApp::closePageById` | `libfalcon.so` | `0x002f297c` | `0x002f297c` |
| `falcon::FalconApp::closePage` | `libfalcon.so` | `0x002f2d1c` | `0x002f2d1c` |
| `falcon::FalconApp::popPage` | `libfalcon.so` | `0x002f27b4` | `0x002f27b4` |
| `falcon::FalconApp::finish` | `libfalcon.so` | `0x002ef638` | `0x002ef638` |
| `falcon::FalconApp::onDestroy` | `libfalcon.so` | `0x002ef648` | `0x002ef648` |
| `falcon::FalconApp::onStart` | `libfalcon.so` | `0x002f3668` | `0x002f3668` |
| `falcon::FalconApp::onStop` | `libfalcon.so` | `0x002f3814` | `0x002f3814` |
| `falcon::FalconApp::launchPage` | `libfalcon.so` | `0x002f645c` | `0x002f645c` |
| `falcon::FalconApp::handleBackPress` | `libfalcon.so` | `0x002f2f80` | `0x002f2f80` |
| `falcon::FalconPage::onDestroy` | `libfalcon.so` | `0x003009a4` | `0x003009a4` |
| `falcon::FalconJSBridge::unloadPage` | `libfalcon.so` | `0x002fad24` | `0x002fad24` |
| `falcon::FalconPageAnimator::popPage` | `libfalcon.so` | `0x00304ed0` | `0x00304ed0` |
| `falcon::FalconPageAnimator::launchPage` | `libfalcon.so` | `0x00304c78` | `0x00304c78` |
| `falcon::FalconStack::closeApp` | `libfalcon.so` | `0x0023cedc` | `0x0023cedc` |
| `falcon::FalconStack::appDestroyed` | `libfalcon.so` | `0x0023c780` | `0x0023c780` |
| `JQuick::closeAppForce` | `libjsapi_proxy.so`| `0x00025d04` | `0x00025d04` |
| `falcon::FalconApp` vtable | `libfalcon.so` | `0x007cfd74` | `0x007bfd74` |
| `falcon::FalconPage` vtable | `libfalcon.so` | `0x007cf850` | `0x007bf850` |
