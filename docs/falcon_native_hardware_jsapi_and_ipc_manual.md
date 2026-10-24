# Falcon Native Hardware JSAPI, Module Export Protocol & IPC Transport Manual
**Authoritative Embedded Systems Architecture and Binary Reverse Engineering Reference**  
*Target SoC: Sophgo/CVITEK CV1813H (Dual-Core ARM Cortex-A7 @ 1.0 GHz, RISC-V Companion, 256MB DDR3, Linux 4.9.x)*  
*Target Binaries: `/usr/lib/libfalcon.so`, `/etc/miniapp/jsapis/libjsapi_export_core.so`, `/usr/lib/libjsapi_proxy.so`*

---

## 1. Executive Architectural Overview

The NetEase Youdao Dictionary Pen S7 Pro (SoC CV1813H) runs a highly customized embedded Linux OS with a proprietary lightweight frontend application engine called **Falcon MiniApp**. Falcon provides a reactive UI runtime (compatible with Vue 2 / Weex single-file component paradigms) executed atop the **QuickJS** ECMAScript engine.

Unlike standard Android or modern Linux desktop stacks that expose hardware through WebViews or Android AIDL bindings, the Youdao Falcon engine implements a **Zero-Overhead Direct Native Bridge** architecture:

```
+-----------------------------------------------------------------------------------+
|                        Falcon MiniApp (JavaScript / Vue 2)                       |
|   import wifi from 'wifi';  import soundPlayer from 'soundPlayer';  // QuickJS    |
+---------------------------------------------------------+-------------------------+
                                                          | ES Module / CModule
+---------------------------------------------------------v-------------------------+
|                              libfalcon.so (Falcon Core)                           |
|   JQuick::__load_custom_jsapis() -> dlopen() discovery of /etc/miniapp/jsapis/*.so|
|   JQuick::ModuleRegistry / falcon::QJSModuleExtension singleton                   |
+---------------------------------------------------------+-------------------------+
                                                          | Native C ABI
+---------------------------------------------------------v-------------------------+
|                            libjsapi_proxy.so (Bridge Layer)                       |
|   registerCModuleLoader() / jqutil_v2::JQFunctionTemplate / JQObjectTemplate      |
|   JQuick::Handler / Looper (Cross-thread message dispatch to QuickJS Event Loop)  |
+---------------------------------------------------------+-------------------------+
                                                          | Class & Template Hook
+---------------------------------------------------------v-------------------------+
|                       libjsapi_export_core.so (Native JSAPI Core)                 |
|   custom_init_jsapis() -> 18 Hardware Subsystem Initializers                      |
|   JSBrightnessProxy, JSSoundPlayerProxy, JSWifiProxy, JSButtonEventModuleProxy... |
|   JQSignal<T> (0x3c stride) Signal-Slot Event Bridge                              |
+-------+-------------------------+-------------------------------+-----------------+
        | IPC (YUbusSender)       | UNIX Domain Sockets           | Shared Memory
+-------v---------+       +-------v---------+             +-------v---------+
| OpenWrt ubusd   |       | wpa_supplicant  |             | YShmSync / Sem  |
| Daemons & HAL   |       | /tmp/wpa_ctrl_* |             | soundplayer svc |
+-----------------+       +-----------------+             +-----------------+
```

### Architectural Key Characteristics:
1. **Dynamic Shared Object Discovery**: On startup, `libfalcon.so` scans the `/etc/miniapp/jsapis` filesystem directory, opening each `.so` via `dlopen(path, RTLD_LAZY)` and resolving entry points `custom_init_jsapis` and `custom_init_jsmodules`.
2. **Unified CModule Registration**: Each hardware subsystem calls `registerCModuleLoader()`, linking a C function pointer to QuickJS's `JS_NewCModule()`.
3. **Template & Prototype Meta-Object System (`jqutil_v2`)**: C++ classes inherit from `JQBaseObject`. Methods are bound via `JQFunctionTemplate::SetProtoMethod<T>` (synchronous) or `SetProtoMethodAsync<T>` (asynchronous offloaded to worker threads).
4. **Signal-Slot Event Dispatch (`JQSignal<T>`)**: Hardware interrupts and asynchronous daemon notifications connect to JavaScript event listeners via 60-byte (`0x3c`) C++ `JQSignal` structs that marshal native arguments directly into QuickJS values on the engine's main thread.
5. **Multi-Channel IPC Transport**:
   - **OpenWrt Ubus**: Lightweight JSON/Blobmsg RPC micro-bus for system state, power management, display control, and telephony.
   - **UNIX Domain Control Sockets**: Direct binary/text communication with `wpa_supplicant` (`/var/run/wpa_supplicant/wlan0`).
   - **POSIX Shared Memory & Semaphores (`YShmSync`)**: Zero-copy circular memory ring buffers for audio PCM streaming between the MiniApp and audio HAL daemons.

---

## 2. Dynamic Shared Object Loading & Module Export Protocol

### 2.1 Dynamic Loading Pipeline (`libfalcon.so`)

At engine initialization, `libfalcon.so` initiates discovery of third-party and hardware JSAPI plugins via `JQuick::__load_custom_jsapis(char const*)` at virtual address `0x00560038`.

#### Disassembly Analysis of `JQuick::__load_custom_jsapis`:
```arm
.text:00560038  PUSH    {R4, R5, R6, R7, R8, LR}
.text:0056003C  MOV     R4, R0              ; R4 = directory path ("/etc/miniapp/jsapis")
.text:00560040  SUB     SP, SP, #0x28
.text:00560044  BL      opendir             ; Open target directory
.text:00560048  MOVS    R5, R0              ; R5 = DIR* dir_handle
.text:0056004C  BEQ     loc_load_fail       ; Branch if opendir failed
...
loc_readdir_loop:
.text:00560058  MOV     R0, R5
.text:0056005C  BL      readdir64           ; Read next directory entry (struct dirent64*)
.text:00560060  SUBS    R6, R0, #0
.text:00560064  BEQ     loc_closedir
.text:00560068  ADD     R7, R6, #0x13       ; R7 points to d_name
.text:0056006C  MOV     R0, R7
.text:00560070  BL      strlen
.text:00560074  CMP     R0, #3              ; Ensure name length > 3
.text:00560078  BLS     loc_readdir_loop
.text:0056007C  ADD     R1, R7, R0
.text:00560080  LDRB    R2, [R1, #-3]!      ; Check for ".so" extension
.text:00560084  CMP     R2, #0x2E           ; '.'
.text:00560088  BNE     loc_readdir_loop
.text:0056008C  LDRH    R3, [R1, #1]
.text:00560090  MOVW    R2, #0x6F73         ; "so"
.text:00560094  CMP     R3, R2
.text:00560098  BNE     loc_readdir_loop
.text:0056009C  MOV     R0, R4              ; Directory path
.text:005600A0  MOV     R1, R7              ; File name
.text:005600A4  BL      JQuick::dynamic_load_jsapi ; Invoke dynamic loader
.text:005600A8  B       loc_readdir_loop
```

#### Disassembly Analysis of `JQuick::dynamic_load_jsapi`:
Located at `0x0055e950` in `libfalcon.so`:
```arm
.text:0055E950  PUSH    {R4, R5, R6, LR}
.text:0055E954  MOV     R5, R0              ; Library path
.text:0055E958  MOV     R1, #1              ; RTLD_LAZY = 1
.text:0055E95C  MOV     R0, R5
.text:0055E960  BL      dlopen              ; Load shared library
.text:0055E964  MOVS    R4, R0              ; R4 = void* handle
.text:0055E968  BEQ     loc_dlerror
.text:0055E970  LDR     R1, =asc_custom_init_jsapis ; "custom_init_jsapis"
.text:0055E974  MOV     R0, R4
.text:0055E978  BL      dlsym               ; Resolve symbol
.text:0055E97C  MOVS    R6, R0
.text:0055E980  BEQ     loc_check_modules
.text:0055E984  BL      falcon::lockJSModule ; Acquire global JS module registration mutex
.text:0055E988  BLX     R6                  ; Execute custom_init_jsapis()!
.text:0055E98C  BL      falcon::unlockJSModule ; Release mutex
loc_check_modules:
.text:0055E994  LDR     R1, =asc_custom_init_jsmodules ; "custom_init_jsmodules"
.text:0055E998  MOV     R0, R4
.text:0055E99C  BL      dlsym
.text:0055E9A0  MOVS    R6, R0
.text:0055E9A4  BEQ     loc_success
.text:0055E9A8  BL      falcon::lockJSModule
.text:0055E9AC  BLX     R6                  ; Execute custom_init_jsmodules()!
.text:0055E9B0  BL      falcon::unlockJSModule
```

### 2.2 Core Module Registration Dispatch (`libjsapi_export_core.so`)

In `/etc/miniapp/jsapis/libjsapi_export_core.so`, the exported symbol `custom_init_jsapis` is defined at virtual address `0x0008f984`. It invokes `custom_init_jsapi_core` at `0x0008f718`, which executes 18 subsystem initializers sequentially:

```arm
.text:0008F718 custom_init_jsapi_core:
.text:0008F718  PUSH    {R4, LR}
.text:0008F71C  BL      wifi_module_init_jsapis             ; 1. Wi-Fi
.text:0008F720  BL      lte_module_init_jsapis              ; 2. 4G LTE
.text:0008F724  BL      tel_module_init_jsapis              ; 3. Telephony/Calls
.text:0008F728  BL      bluetooth_module_init_jsapis        ; 4. Bluetooth & BLE
.text:0008F72C  BL      brightness_module_init_jsapis       ; 5. Screen Brightness & TP
.text:0008F730  BL      volume_module_init_jsapis           ; 6. Hardware Volume
.text:0008F734  BL      buttonEvent_module_init_jsapis      ; 7. Physical Keys & Pen Tip
.text:0008F738  BL      systemInfo_module_init_jsapis       ; 8. System & Device Info
.text:0008F73C  BL      global_module_init_jsapis           ; 9. OCR, Dialogs & App Mgmt
.text:0008F740  BL      sound_player_module_init_jsapis     ; 10. Sound & TTS Player
.text:0008F744  BL      headSetInfo_module_init_jsapis      ; 11. Wired/BT Headset Routing
.text:0008F748  BL      logmanager_module_init_jsapis       ; 12. Logging Subsystem
.text:0008F74C  BL      gsensor_module_init_jsapis          ; 13. Gravity / Accelerometer
.text:0008F750  BL      userCenterCommon_module_init_jsapis ; 14. NetEase Account Login
.text:0008F754  BL      str_utils_module_init_jsapis        ; 15. UUID & Punctuation
.text:0008F758  BL      httpbridge_module_init_jsapis       ; 16. Authenticated HTTP Bridge
.text:0008F75C  BL      headCamera_module_init_jsapis       ; 17. Pen-Tip Camera / OID
.text:0008F760  BL      registerExchangeAppidFunc           ; 18. App ID Isolation Filter
.text:0008F764  POP     {R4, PC}
```

### 2.3 Registration Bridge (`registerCModuleLoader`)

Each `*_module_init_jsapis` invokes `registerCModuleLoader(const char* name, JSModuleDef* (*loader)(JSContext*, const char*))` exported by `libjsapi_proxy.so` at address `0x00072f30`:

```arm
.text:00072F30 registerCModuleLoader:
.text:00072F30  PUSH    {R4, R5, R6, R7, R8, LR}
.text:00072F34  SUBS    R5, R0, #0          ; R5 = module name string (e.g., "wifi")
.text:00072F38  MOV     R6, R1              ; R6 = module loader callback function pointer
.text:00072F3C  BEQ     loc_null_exit
.text:00072F40  BL      strlen              ; Calculate string length
.text:00072F54  MOV     R1, R5
.text:00072F58  MOV     R0, SP              ; Construct std::string
.text:00072F5C  BL      std::__cxx11::basic_string::basic_string(...)
.text:00072F84  BL      falcon::QJSModuleExtension::singleton ; Obtain singleton
.text:00072F88  MOV     R2, R6              ; Loader function pointer
.text:00072F8C  MOV     R1, SP              ; std::string const& module_name
.text:00072F90  BL      falcon::QJSModuleExtension::registerModuleLoader ; Store in module hash map
.text:00072FA4  POP     {R4, R5, R6, R7, R8, PC}
```

### 2.4 QuickJS CModule Initialization and Export Protocol

When JavaScript executes `import mod from 'moduleName'` or `require('moduleName')`, QuickJS resolves the module loader registered in `QJSModuleExtension`. The module loader follows a two-stage initialization protocol:

```cpp
// Stage 1: Loader callback passed to registerCModuleLoader
JSModuleDef* module_loader_callback(JSContext* ctx, const char* module_name) {
    // 1. Create a CModule in QuickJS with the designated ModuleInit function
    JSModuleDef* m = JS_NewCModule(ctx, module_name, jsapi_module_init);
    if (!m) return nullptr;
    
    // 2. Declare that this module exports a "default" symbol
    JS_AddModuleExport(ctx, m, "default");
    return m;
}

// Stage 2: JSModuleInitFunc executed during module evaluation
int jsapi_module_init(JSContext* ctx, JSModuleDef* m) {
    // 1. Create a prototype template for the Proxy C++ class
    auto func_tmpl = jqutil_v2::JQFunctionTemplate::New(ctx, "Brightness");
    
    // 2. Obtain the object template for member methods and signal properties
    auto inst_tmpl = func_tmpl->InstanceTemplate();
    
    // 3. Register synchronous prototype methods: SetProtoMethod<T>(name, &T::method, argc)
    func_tmpl->SetProtoMethod<JSBrightnessProxy>("getBrightness", &JSBrightnessProxy::getBrightness, 0);
    func_tmpl->SetProtoMethod<JSBrightnessProxy>("setBrightness", &JSBrightnessProxy::setBrightness, 1);
    func_tmpl->SetProtoMethod<JSBrightnessProxy>("screenOnOff", &JSBrightnessProxy::screenOnOff, 1);
    
    // 4. Register hardware signal/event hooks: Set<T, ArgType>(name, &T::signal, flags)
    inst_tmpl->Set<JSBrightnessProxy, bool>("brightnessChanged", &JSBrightnessProxy::brightnessChanged, 0);
    inst_tmpl->Set<JSBrightnessProxy, int>("brightnessValueChanged", &JSBrightnessProxy::brightnessValueChanged, 0);
    
    // 5. Instantiate constructor function or singleton instance
    JSValue ctor = func_tmpl->GetFunction();
    JSValue default_export = JS_CallConstructor(ctx, ctor, 0, nullptr);
    
    // 6. Set module export "default"
    JS_SetModuleExport(ctx, m, "default", default_export);
    return 0;
}
```

---

## 3. C++ Struct Layout & Signal-Slot Dispatch Mechanics

### 3.1 `JQSignal<T>` Memory Struct Layout

On 32-bit ARM Cortex-A7 (ARMv7-A hard-float), every signal hook in the native proxy classes is represented by `jqutil_v2::JQSignal<T>`.

**Binary Size**: Exact stride of `0x3c` (60 bytes).

```
+---------------------------------------------------------------------------------+
| Offset | Field Name               | Type                     | Description      |
+--------+--------------------------+--------------------------+------------------+
| 0x00   | vptr                     | void**                   | Virtual table ptr|
| 0x04   | m_signal_id              | uint32_t                 | Unique signal ID |
| 0x08   | m_connections_head       | struct JQSlotNode*       | Linked list head |
| 0x0C   | m_connections_tail       | struct JQSlotNode*       | Linked list tail |
| 0x10   | m_connection_count       | uint32_t                 | Number of slots  |
| 0x14   | m_mutex                  | pthread_mutex_t (24B)    | Signal lock      |
| 0x2C   | m_ctx                    | JSContext*               | QuickJS context  |
| 0x30   | m_owner_proxy            | JQBaseObject*            | Parent proxy ptr |
| 0x34   | m_flags                  | uint32_t                 | Queued / Direct  |
| 0x38   | m_reserved               | uint32_t                 | 4-byte padding   |
+---------------------------------------------------------------------------------+
Total Size = 0x3C (60 bytes)
```

### 3.2 Proxy Class Memory Layout (Verified in `JSBrightnessProxy`)

`JSBrightnessProxy` inherits from `JQBaseObject` (base size `0x68` bytes):

```
+---------------------------------------------------------------------------------------+
| Offset Range | Member Variable                | Type                   | Stride       |
+--------------+--------------------------------+------------------------+--------------+
| 0x00 - 0x67  | [JQBaseObject Base Class]      | JQBaseObject           | 0x68 bytes   |
| 0x68 - 0x6B  | [Alignment Padding]            | uint32_t               | 4 bytes      |
| 0x6C - 0xA7  | brightnessChanged              | JQSignal<bool>         | 0x3C (60 B)  |
| 0xA8 - 0xE3  | screenStatusChanged            | JQSignal<bool>         | 0x3C (60 B)  |
| 0xE4 - 0x11F | brightnessValueChanged         | JQSignal<int>          | 0x3C (60 B)  |
| 0x120 - 0x15B| startAlwaysScreenOnTriggered   | JQSignal<bool>         | 0x3C (60 B)  |
| 0x15C - 0x197| stopAlwaysScreenOnTriggered    | JQSignal<bool>         | 0x3C (60 B)  |
| 0x198 - 0x1D3| tpUpdateResult                 | JQSignal<int>          | 0x3C (60 B)  |
+---------------------------------------------------------------------------------------+
Total Allocated Instance Size = 0x1D8 bytes
```

### 3.3 Event Connection from JavaScript

In JavaScript, signals can be connected via two equivalent idioms:
```javascript
// Method 1: Property connect method (Direct JQSignal binding)
brightness.brightnessValueChanged.connect((newValue) => {
    console.log("Brightness updated:", newValue);
});

// Method 2: Event listener paradigm (dispatched via JQBaseObject::addEventListener)
brightness.on('brightnessValueChanged', (newValue) => {
    console.log("Brightness updated:", newValue);
});
```

When native code emits a signal (e.g., hardware interrupt or Ubus callback):
1. Native thread calls `brightnessValueChanged.emit(val)`.
2. `JQSignal::emit` checks if current thread is the QuickJS main thread:
   - If **same thread**: Executes slot JavaScript callbacks directly via `JS_Call()`.
   - If **worker thread**: Enqueues an execution task into `JQuick::Handler` on `JQuick::Looper::getMainLooper()`.
3. The main event loop drains the queue, converts C++ primitive types (`int`, `bool`, `std::string`) into `JSValue`, and executes the callback within a protected `JS_Call` frame.

---

## 4. Hardware Module Taxonomy & Binary API Specifications

Every method in this section is verified against decompiled symbols in `libjsapi_export_core.so`, `libjsapi_proxy.so`, and `libfalcon.so`.

---

### 4.1 Audio & Speech Synthesis: `soundPlayer`

The `soundPlayer` module handles local audio file playback, streaming audio over HTTP, base64 PCM playback, and text-to-speech (TTS) synthesis.

- **Module Name**: `'soundPlayer'`
- **C++ Proxy Class**: `JSSoundPlayerProxy` (inherits `JQBaseObject`)
- **Underlying HAL**: `YDALAPI::YSoundPlayerModule`, `libyddal_common_soundplayer.so`, `libyoudao_player_lim.so`

#### Disassembled Method Signatures:
1. `play(source: string, type: string, extra: string, loop: number): void`
   - Maps to: `YDALAPI::YSoundPlayerModule::play(...)`
   - Plays an audio resource with specified MIME type or codec.
2. `playFile(path: string, offset: number, speed: number, autoStop: boolean, duration: number): void`
   - Maps to: `YDALAPI::YSoundPlayerModule::playFile(...)`
   - Direct low-latency file playback from `/userdata/` or `/tmp/`.
3. `playBase64(data: string): void`
   - Decodes base64 payload into raw PCM and writes to shared memory ring buffer.
4. `playOnlineAudio(url: string): void`
   - HTTP/HTTPS audio streaming via `libcurl`.
5. `playOnlineAudioByMoreTransApp(url: string, params: string): void`
   - Optimized streaming with dynamic buffering for translation mini-apps.
6. `playMediaSection(jsonConfig: string): void`
   - Segmented playback with millisecond start/end timestamps.
7. `playTts(text: string, voiceType: string): void`
   - Offline/online speech synthesis.
8. `playStreamTts(streamUrl: string, text: string, lang: string): void`
   - Low-latency chunked streaming TTS playback.
9. `setPlayTTSParam(paramsJson: string): void`
   - Configures pitch, volume, speaker ID, and speed rate.
10. `switchTtsAutoPronType(pronType: number): void`
    - Toggles phonetic pronunciation style (1 = British, 2 = American).
11. `stop(): void`
    - Stops audio and flushes decoder pipeline.
12. `quickStop(): void`
    - Instantaneous mute and buffer purge without graceful fade-out.

#### Registered Event Signals:
- `mediaPlayerPositionChanged: JQSignal<int>` — Emits current position in milliseconds.
- `mediaPlayerDurationChanged: JQSignal<int>` — Emits total duration in milliseconds.
- `mediaPlayerProgressChanged: JQSignal<int>` — Emits download/buffering percentage (0-100).
- `mediaPlayerEndChanged: JQSignal<bool>` — Emitted upon normal playback completion (`true`).
- `mediaPlayerEndWithErrorChanged: JQSignal<int>` — Emitted on decode or I/O error code.
- `mediaPlayerEndWithErrorChangedEx: JQSignal<string>` — JSON formatted diagnostic error details.
- `ttsDataStarted: JQSignal<bool>` — Emitted when the first TTS audio packet hits the DAC.
- `onTtsError: JQSignal<int>` — TTS synthesis failure code.

---

### 4.2 Audio Recording: `soundRecord` / `record`

Audio recording is managed through `YDALAPI::YRecordCenter` and `libyddal_common_soundrecord.so`, feeding both user recording and the speech recognition (ASR) engine.

- **Underlying Driver**: ALSA `hw:0,0` / CV1813H Internal Audio Codec (ADC)
- **Standard Format**: 16,000 Hz sample rate, 16-bit Signed Little-Endian (S16_LE), Mono channel.

#### Disassembled HAL API:
1. `YDALAPI::YRecordCenter::Instance()->startSpeechService()`
2. `YDALAPI::YRecordCenter::Instance()->stopRecord(filename)`
3. `YSoundRecordInterfacePrivate::setSpeechParam(codec, lang, accent, sampleRate, vadEnable, secret, key, timeout)`
4. `YSoundRecordInterfacePrivate::registerBinaryMessageReceivedCallback(callback, user_data)`
   - Dispatches raw PCM buffers directly from `YShmSync` shared memory to the application.

---

### 4.3 Battery & Power Management: `batteryInfo` & `systemInfo`

Battery telemetry is gathered from the onboard **AXP2101 PMIC** via Linux sysfs power supply subsystems.

- **Module Name**: `'batteryInfo'`
- **JS Proxy Class**: `BatteryInfo` (instantiated via `new batteryInfo.BatteryInfo()`)
- **Sysfs Paths**:
  - Capacity: `/sys/class/power_supply/battery/capacity` (`0` - `100`)
  - Status: `/sys/class/power_supply/battery/status` (`Charging`, `Discharging`, `Full`, `Not charging`)
  - Voltage: `/sys/class/power_supply/battery/voltage_now` (µV)
  - Current: `/sys/class/power_supply/battery/current_now` (µA)
- **Underlying C++**: `YADAPTERAPI::YBatteryAdapter`, `YDALAPI::YBatteryModule`

#### Methods & Properties:
1. `getBatteryCapacity(): number` — Returns integer 0-100.
2. `getBatteryStatus(): string` — Returns power status string.
3. `isCharging(): boolean` — Returns `true` if charging current is detected.

#### Registered Event Signals:
- `batteryInfoChange: JQSignal<bool, int>` — Emits `(isCharging: boolean, capacity: number)` whenever PMIC fuel gauge registers delta or AC cable is connected/disconnected.

---

### 4.4 Wi-Fi Networking: `wifi`

The Wi-Fi subsystem directly bridges QuickJS to the Linux wireless networking stack and `wpa_supplicant`.

- **Module Name**: `'wifi'`
- **C++ Proxy Class**: `JSWifiProxy`
- **Underlying HAL**: `YDALAPI::YWifiModule`, `libwpa_client.so`

#### Disassembled Method Signatures:
1. `open(): void` — Enables Wi-Fi interface (`wlan0` up, initiates `wpa_supplicant`).
2. `close(): void` — Disables interface and releases DHCP lease.
3. `isOpen(): boolean` — Checks if radio is powered on.
4. `isConnected(): boolean` — Checks if associated with an AP and has IP.
5. `scan(): void` — Triggers passive/active BSSID broadcast probe scan.
6. `connect(ssid: string, psk: string): void` — Configures network block and triggers association.
7. `disconnect(ssid: string): void` — Deauthenticates from network.
8. `getIP(): string` — Returns current IPv4 address string (e.g., `"192.168.1.105"`).
9. `getState(): number` — Returns connection state machine enum.
10. `getWifiQual(): string` — Returns RSSI signal strength (dBm or 0-4 quality bars).
11. `startWifiQualTimer(): void` — Starts 3-second periodic polling of RSSI.
12. `stopWifiQualTimer(): void` — Disables RSSI polling.
13. `onGetWifiPassWd(ssid: string): string` — Queries encrypted saved credential from `/userdata/etc/wifi.conf`.

#### Registered Event Signals:
- `listChanged: JQSignal<string>` — Emits JSON array of scanned access points (`[{ssid, bssid, rssi, flags}, ...]`).
- `statusChanged: JQSignal<int>` — Emits Wi-Fi state transition (0 = Disconnected, 1 = Connecting, 2 = Connected).
- `internetConnectChanged: JQSignal<bool>` — Emitted after cloud gateway ping probe succeeds/fails.
- `qualChanged: JQSignal<string>` — Emits updated signal strength percentage/bar level.
- `wifiScanError: JQSignal<int>` — Emits scan error code.

---

### 4.5 Bluetooth & BLE Management: `bluetooth`

Supports Bluetooth Classic (A2DP audio sink/source, HFP headset) and Bluetooth Low Energy (BLE) peripheral communication.

- **Module Name**: `'bluetooth'`
- **C++ Proxy Class**: `JSBlueToothProxy`
- **Underlying HAL**: `YDALAPI::YBluetoothModule`, BlueZ / RTK BT stack

#### Disassembled Method Signatures:
1. `open(): void` / `close(): void` — Classic BT adapter power toggle.
2. `isBtOpen(): boolean` / `isConnected(): boolean` — Connection query.
3. `scanStart(): void` / `scanStop(): void` — Device inquiry discovery.
4. `connect(mac: string, name: string): void` — Classic BT pairing and profile connection.
5. `disconnect(mac: string, name: string): void` — Disconnects ACL link.
6. `remove(mac: string, name: string): void` — Unpairs device and removes link key.
7. `btStatus(): number` — Current state of BT stack.
8. `btGetBattery(): number` — Returns connected BT headset battery level (0-100 via HFP AT+BIEV).
9. `btGetColor(): string` — Device cosmetic color code for branded accessories.
10. `btGetInfo(): string` — Returns JSON string describing remote device profile.
11. `bleOpen(): void` / `bleClose(): void` — BLE radio toggle.
12. `isBleOpen(): boolean` / `isConnectBle(): boolean` — BLE state queries.
13. `bleDisconnect(mac: string): void` — Terminates BLE GATT connection.
14. `bleWrite(mac: string, hexData: string): void` — Writes GATT characteristic value.

#### Registered Event Signals:
- `bluetoothSwitchChanged: JQSignal<bool>` — BT power toggle event.
- `bluetoothScanChanged: JQSignal<bool>` — Inquiry start (`true`) or end (`false`).
- `deviceListChanged: JQSignal<string>` — JSON array of discovered devices.
- `pairedListChanged: JQSignal<string>` — JSON array of paired devices.
- `bluetoothConnectStatusChanged: JQSignal<bool>` — ACL connection established/lost.
- `batteryChanged: JQSignal<string>` — Remote headset battery level update.
- `bleStatusChanged: JQSignal<int>` — BLE GATT state transition.
- `btError: JQSignal<int>` — Bluetooth protocol stack error.

---

### 4.6 Display, Backlight & Touch Panel: `brightness`

Controls PWM screen backlight, OLED power, always-on timers, and touch panel firmware updates.

- **Module Name**: `'brightness'`
- **C++ Proxy Class**: `JSBrightnessProxy`
- **Underlying Sysfs**: `/sys/class/backlight/pwm-backlight/brightness` (values `1` - `255`)
- **Underlying HAL**: `YDALAPI::YBrightnessModule`

#### Disassembled Method Signatures:
1. `getBrightness(): number` — Returns current brightness index (1-255).
2. `setBrightness(value: number): void` — Sets backlight level instantly.
3. `getScreenState(): number` — Returns 1 (screen ON) or 0 (screen OFF).
4. `screenOnOff(state: number): void` — Powers display controller and backlight ON/OFF.
5. `keepScreenOn(): void` — Resets the idle timeout countdown.
6. `startAlwaysScreenOn(): void` — Acquires display wake-lock (disables auto-sleep).
7. `stopAlwaysScreenOn(): void` — Releases display wake-lock.
8. `getTpUpdateStatus(): number` — Returns status of Touch Panel I2C firmware flashing.

#### Registered Event Signals:
- `brightnessChanged: JQSignal<bool>` — Backlight altered event notification.
- `brightnessValueChanged: JQSignal<int>` — New backlight integer value.
- `screenStatusChanged: JQSignal<bool>` — Display turned ON (`true`) or OFF (`false`).
- `startAlwaysScreenOnTriggered: JQSignal<bool>` — Permanent display mode active.
- `stopAlwaysScreenOnTriggered: JQSignal<bool>` — Permanent display mode deactivated.
- `tpUpdateResult: JQSignal<int>` — Touch panel firmware upgrade result code.

---

### 4.7 Physical Buttons & Hardware Sensors: `buttonEvent`

Coordinates physical keys, rotary encoders, Hall effect sensors, and the scan pen tip trigger switch.

- **Module Name**: `'buttonEvent'`
- **C++ Proxy Class**: `JSButtonEventModuleProxy`
- **Underlying Device Drivers**:
  - Pen Tip Switch: `/dev/input/event0` (GPIO button / microswitch)
  - Hall Sensors: Dual magnetic sensors (`hallTop` and `hallBottom`)
  - Rotary Encoder: Mechanical turn clicks (`rotaryTurn`)

#### Disassembled Method Signatures:
1. `isHeadButtonPressed(): boolean` — Returns `true` if the pen tip is currently pressed down.
2. `setButtonEventReady(ready: boolean): void` — Signals driver that UI event handlers are mounted.
3. `softButtonEvent(keyCode: number, action: number): void` — Injects software key event into input pipeline.
4. `emitBottomSwipeBackEvent(): void` — Simulates bottom screen gesture navigation back.

#### Registered Event Signals (Complete 45-Signal Taxonomy):
- **Scan Pen Tip Trigger**:
  - `headButtonPress: JQSignal<int>` — Microswitch triggered (contact made with paper).
  - `headButtonRelese: JQSignal<int>` — Microswitch released (pen lifted).
- **Home Button**:
  - `homeButtonPress`, `homeButtonRelease`, `homeButtonLongPress`, `homeButtonClick`, `homeButtonDoubleClick`: `JQSignal<int>`
- **Power Button**:
  - `powerButtonPress`, `powerButtonRelese`, `powerButtonLongPress`, `powerButtonClick`, `powerButtonDoubleClick`: `JQSignal<int>`
- **Play Button**:
  - `playButtonPress`, `playButtonRelese`, `playButtonLongPress`, `playButtonClick`, `playDoubleClick`: `JQSignal<int>`
- **Back / Navigation Buttons**:
  - `backButtonPress`, `backButtonRelese`, `backButtonLongPress`, `backButtonClick`, `backDoubleClick`: `JQSignal<int>`
  - `forwardButtonPress`, `forwardButtonRelese`, `forwardButtonLongPress`, `forwardButtonClick`, `forwardDoubleClick`: `JQSignal<int>`
- **Volume Buttons**:
  - `volumeUpButtonPress`, `volumeUpButtonRelese`, `volumeUpButtonLongPress`, `volumeUpButtonClick`, `volumeUpDoubleClick`: `JQSignal<int>`
  - `volumeDownButtonPress`, `volumeDownButtonRelese`, `volumeDownButtonLongPress`, `volumeDownButtonClick`, `volumeDownDoubleClick`: `JQSignal<int>`
- **Hall Effect & Rotary Sensors**:
  - `hallTop: JQSignal<int>` — Top magnetic sensor state (case closed/opened).
  - `hallBottom: JQSignal<int>` — Bottom magnetic sensor state (charging dock contact).
  - `rotaryTurn: JQSignal<int>` — Rotary encoder rotation step (+1 = clockwise, -1 = counter-clockwise).
- **Head Camera Trigger**:
  - `headCameraPreviewButtonPress`, `headCameraPreviewButtonRelease`, `headCameraPreviewButtonClick`, `headCameraPreviewButtonDoubleClick`: `JQSignal<int>`
- **Gesture Signals**:
  - `bottomSwipeBackEvent: JQSignal<int>` — Bottom swipe navigation event.

---

### 4.8 Firmware Updates & OTA: `Updater` / `systemInfo`

Firmware updates are divided between MiniApp bundle updates (`Updater` in `libfalcon.so`) and full OS firmware OTA (`libydhal_ota.so` and `ota_mgr` daemon).

- **MiniApp Updater Class**: `Updater::JSAppUpdateManager` in `libfalcon.so`
- **OS OTA Daemon**: `/usr/bin/ota_mgr` communicating via `/var/run/ota.sock`

#### MiniApp Update Manager Methods:
1. `isReady(callback: Function): boolean` — Queries if updater service is initialized.
2. `getUpdateInfo(asyncCallback: (res: UpdateInfo) => void): void` — Checks server for newer package versions.
3. `startDownload(asyncCallback: (result: number, progress: number) => void): void` — Downloads `.bin` MiniApp package.
4. `installUpdate(asyncCallback: (status: number) => void): void` — Verifies signature and installs bundle to `/userdata/miniapp/data/mini_app/pkg/`.
5. `markCacheExpired(): void` — Forces eviction of cached bytecode.

---

### 4.9 System & Device Metadata: `systemInfo`

Provides read-only and privileged hardware identification parameters.

- **Module Name**: `'systemInfo'`
- **C++ Proxy Class**: `JSystemInfoProxy`
- **Underlying HAL**: `YDALAPI::YSystemInfoModule`

#### Disassembled Method Signatures:
1. `getVersion(): string` — Firmware build string (e.g., `"1.2.0-20241015"`).
2. `getSNInfo(): string` — Device hardware Serial Number (from EEPROM/eMMC CID).
3. `getUUIDInfo(): string` — Unique hardware device UUID.
4. `getMacInfo(): string` — Factory Wi-Fi MAC address string.
5. `getDeviceName(): string` — Commercial product name (`"Youdao Dictionary Pen S7 Pro"`).
6. `getDeviceType(): string` — Internal hardware code (`"s7pro"` / `"cv1813h"`).
7. `getSKU(): string` — Hardware Stock Keeping Unit identifier.
8. `getSKUSerial(): string` — SKU serial mapping.
9. `getSKUCfg(): string` — Hardware configuration string.
10. `getDeviceSKUInfo(): string` — Combined hardware specs string.
11. `getStorageInfo(): string` — JSON string with total and used NAND flash space.
12. `getAvailableSpace(): number` — Free space in bytes on `/userdata`.
13. `getSystemFlashSize(): number` — Total eMMC flash size in megabytes.
14. `getSystemTime(): string` — Formatted RTC system time.
15. `updateCurrentSystemTime(): void` — Forces synchronization with NTP server.
16. `getAdbEnable(): number` / `setAdbEnable(flag: number): void` — Toggles USB ADB debug interface.
17. `getHandedness(): number` / `setHandedness(mode: number): void` — Left/Right hand display flip (0 = Right, 1 = Left).
18. `feedWatchdog(): void` — Kicks hardware watchdog (`/dev/watchdog`).
19. `closeBootLogo(): void` — Tears down framebuffer boot splash.
20. `resetFactory(level: number): void` — Initiates factory data reset.
21. `powerOff(): void` — Graceful system shutdown via PMIC.

#### Registered Event Signals:
- `currentSystemTimeChange: JQSignal<string>` — Emitted upon system clock adjustments.

---

### 4.10 Global System & OCR Management: `global`

The largest native subsystem, exposing 115 methods and 45 signals for OCR control, cross-app navigation, and system dialogs.

- **Module Name**: `'global'`
- **C++ Proxy Class**: `JSGlobalProxy`
- **Underlying HAL**: `YDALAPI::YGlobalLookupWordModule`, `YDALAPI::YOCRManager`

#### Key Methods:
- `startScan()` / `isRestartScan()`: Initiates scan pen sensor acquisition.
- `currentAppId(): string` / `setCurrentAppId(appId: string, flag: boolean): void`: MiniApp lifecycle focus.
- `showToast(msg: string, duration: number): void`: Displays system toast overlay.
- `showSystemDialog(jsonConfig: string): void`: Displays modal confirm dialog.
- `trafficDialogClicked(btnId: number)`: Responds to 4G data alert prompts.
- `translate(text: string, srcLang: string, tgtLang: string): void`: Triggers offline NMT translation.

#### Key Signals:
- `ocrResultChanged: JQSignal<string>` — Raw OCR output JSON string.
- `scanArticleResultChanged: JQSignal<string>` — Multiline article OCR parsing result.
- `scanTranslatorResultChanged: JQSignal<string>` — Immediate scan-to-translate pipeline result.
- `ocrStartChanged: JQSignal<bool>` — Emitted when pen tip sensor begins imaging.
- `ocrStopChanged: JQSignal<bool>` — Emitted when image stitching completes.
- `onCurrentAppIdChanged: JQSignal<string>` — Active MiniApp transition event.

---

### 4.11 Hardware Volume: `volume`

- **Module Name**: `'volume'`
- **C++ Proxy Class**: `JSVolumenessProxy`
- **Underlying ALSA**: `amixer set 'Master' <vol>%`
- **Methods**: `getVolume(): number`, `setVolume(vol: number): void` (0 to 100)
- **Signals**: `volumeChanged: JQSignal<int>`, `callBackVolumeValue: JQSignal<int>`

---

### 4.12 Gravity & Accelerometer: `gsensor`

- **Module Name**: `'gsensor'`
- **C++ Proxy Class**: `JSGsensornessProxy`
- **Underlying Driver**: `/dev/gsensor` (I2C 3-axis accelerometer)
- **Methods**: `reportEnable(): void`, `reportDisable(): void`, `reportGetAngle(): string`, `setShakeStatus(status: number): void`
- **Signals**: `shakeResChange: JQSignal<int>`, `orientResChange: JQSignal<int>`

---

### 4.13 Audio Output Routing: `headSetInfo`

- **Module Name**: `'headSetInfo'`
- **C++ Proxy Class**: `JHeadSetInfoProxy`
- **Methods**: `getHeadSetState(): number`, `getCurrentDevices(): string`, `selectHeadset(type: number, id: string, name: string): void`
- **Signals**: `headsetStateChanged: JQSignal<int>`, `getCurrentDevicesFinish: JQSignal<string>`, `userSelectHeadset: JQSignal<int>`

---

### 4.14 Cellular 4G & Telephony: `lte` & `tel`

- **Modules**: `'lte'`, `'tel'`
- **C++ Proxy Classes**: `JSLteProxy`, `JSTelProxy`
- **Underlying Hardware**: USB ECM / RNDIS / PPP modem interface
- **LTE Methods**: `open()`, `close()`, `getStatus()`, `getLteQual()`, `getIccid()`, `getLteImei()`
- **Tel Methods**: `call(number: string)`, `answer()`, `hangup()`, `sendMessage(number: string, text: string)`
- **Signals**: `statusChanged`, `qualChanged`, `onCallState`, `onTelIncall`, `onMessageSent`, `onTelInMessage`

---

## 5. Inter-Process Communication (IPC) & Proxy Transport Architecture

Because MiniApp instances run in separate process sandboxes or unprivileged QuickJS context boundaries, direct hardware register access is forbidden. `libjsapi_proxy.so` and `libjsapi_export_core.so` use three distinct IPC channels:

```
+-------------------------------------------------------------------------------+
|                       MiniApp Process (libjsapi_export_core.so)              |
+---------------------+-------------------------+-------------------------------+
| OpenWrt ubus Client | WPA Supplicant Client   | POSIX Shared Memory Ring      |
| (libubus / libubox) | (libwpa_client.so)      | (YDALBASEAPI::YShmSync)       |
+----------+----------+------------+------------+---------------+---------------+
           |                       |                            |
  UNIX Socket (/var/run/ubus.sock) | UNIX Socket                | Shm ID & Named Sem
           |                       | (/var/run/wpa_supplicant)  | (/dev/shm/*)
           v                       v                            v
+---------------------+   +---------------------+   +---------------------------+
| ubusd (OpenWrt Ubus)|   | wpa_supplicant      |   | soundplayer / record      |
| Daemon Dispatcher   |   | Wireless Control    |   | Audio Engine Daemons      |
+----------+----------+   +---------------------+   +---------------------------+
           |
   +-------+-------+
   |               |
   v               v
+------+       +-------+
|ydhal |       |udev_mon
+------+       +-------+
```

### 5.1 OpenWrt Ubus Micro-Bus Architecture

`libjsapi_export_core.so` links directly to OpenWrt's native IPC stack:
- `libubus.so`: The OpenWrt Micro-Bus client library.
- `libubox.so`: Event loop, timer, and buffer primitives (`uloop`, `blobmsg`).
- `libblobmsg_json.so`: Serializes C++ data into binary typed attributes.
- `libydubus_center.so` & `libydubus_sender.so`: Youdao IPC wrappers.

#### Message Dispatch Mechanism:
```cpp
// Decompiled dispatch flow from YDALBASEAPI::YUbusSender::sendMessage
void YUbusSender::sendMessage(int msgId, const char* jsonPayload) {
    struct ubus_context *ctx = ubus_connect("/var/run/ubus.sock");
    if (!ctx) return;
    
    struct blob_buf b;
    blob_buf_init(&b, 0);
    blobmsg_add_json_from_string(&b, jsonPayload);
    
    uint32_t id;
    if (ubus_lookup_id(ctx, "ydhal_service", &id) == 0) {
        ubus_invoke(ctx, id, "dispatch", b.head, ubus_callback, nullptr, 1000);
    }
    
    blob_buf_free(&b);
    ubus_free(ctx);
}
```

### 5.2 WPA Supplicant UNIX Domain Sockets

Wi-Fi configuration completely bypasses standard Linux `ioctl(SIOCSIWESSID)` in favor of direct control sockets provided by `libwpa_client.so`:

- **Client Control Endpoint**: Automatically bound in `/tmp/wpa_ctrl_<pid>_<seq>`
- **Server Control Endpoint**: `/var/run/wpa_supplicant/wlan0`
- **Commands Sent**:
  - `SCAN` -> Initiates BSSID inquiry.
  - `SCAN_RESULTS` -> Returns tab-separated list of visible networks.
  - `ADD_NETWORK` -> Allocates new network configuration slot.
  - `SET_NETWORK <id> ssid "MySSID"` -> Sets target SSID.
  - `SET_NETWORK <id> psk "Password"` -> Configures WPA2/WPA3 credentials.
  - `SELECT_NETWORK <id>` -> Enforces association.

### 5.3 Shared Memory & Semaphore Transport (`YShmSync`)

High-bitrate audio data (PCM streams for TTS and recording) cannot tolerate the serialization overhead of Ubus or the context-switch penalties of sockets. The device uses **POSIX Shared Memory (`shm_open`, `mmap`)** synchronized via **POSIX Named Semaphores (`sem_t`)**.

- **Memory Segment**: Created in `/dev/shm/yd_audio_shm` with a default circular buffer size of 64 KB (`0x10000`).
- **Memory Header Structure**:
  ```cpp
  struct AudioShmHeader {
      uint32_t magic;           // 0x59444155 ("YDAU")
      uint32_t write_offset;    // Writer pointer
      uint32_t read_offset;     // Reader pointer
      uint32_t buffer_size;     // Capacity
      uint32_t sample_rate;     // 16000
      uint16_t channels;        // 1
      uint16_t bit_depth;       // 16
  };
  ```
- **Synchronization**: `YADAPTERAPI::Internal::YAudioOutputPrivate::semaphoreP` (`sem_wait`) blocks until writer emits `semaphoreV` (`sem_post`).

### 5.4 App ID Isolation & Security Boundaries

MiniApps operate under strict capability isolation enforced by `libfalcon.so` and `libjsapi_proxy.so`.

1. **Context App ID Tagging**:
   When a QuickJS context (`JSContext*`) is initialized for a MiniApp, its numeric identifier is bound to `jqutil_v2::JQTemplate::appid()` via `JQuick::getAppid(JSContext*)`.
2. **Dynamic Translation & Whitelisting (`registerExchangeAppidFunc`)**:
   In `libjsapi_proxy.so` at `0x00026270`, `JQuick::exchangeAppidIfNeeded` validates calling context permissions:
   ```arm
   .text:00026288  LDR     R3, [R3, R2]        ; Read JQuick::_ExchangeAppidFunc function pointer
   .text:0002628C  LDR     R3, [R3]
   .text:00026290  CMP     R3, #0              ; Is an exchange/validator function registered?
   .text:00026294  BEQ     loc_allow_direct    ; If null, permit default pass-through
   .text:00026298  BLX     R3                  ; Execute policy check!
   ```
3. **Privileged API Gating**:
   APIs including `resetFactory()`, `setAdbEnable()`, `freezeScreen()`, and `closeBootLogo()` check the active `appId`. Privileged system capabilities are strictly reserved for the built-in Desktop Launcher (`appId: 8080222437664451`) and System Settings (`appId: 8080272425914438`). Third-party mini-apps calling these functions fail silently or trigger an access violation event.

---

## 6. Complete TypeScript Definitions: `falcon-hardware.d.ts`

The following TypeScript declaration file defines the entire native hardware API taxonomy for the Youdao Dictionary Pen S7 Pro.

```typescript
/**
 * NetEase Youdao Dictionary Pen S7 Pro (CV1813H)
 * Native Falcon MiniApp Hardware JSAPI Type Definitions
 */

declare namespace Falcon {
    /** Base interface for C++ JQSignal event subscriptions */
    interface JQSignal<T> {
        connect(callback: (value: T) => void): void;
        disconnect(callback?: (value: T) => void): void;
    }

    interface JQSignalVoid {
        connect(callback: () => void): void;
        disconnect(callback?: () => void): void;
    }

    interface JQSignal2<T1, T2> {
        connect(callback: (arg1: T1, arg2: T2) => void): void;
        disconnect(callback?: (arg1: T1, arg2: T2) => void): void;
    }

    // ==========================================
    // 1. Brightness & Screen Display
    // ==========================================
    interface BrightnessModule {
        getBrightness(): number;
        setBrightness(value: number): void;
        getScreenState(): number;
        screenOnOff(state: number): void;
        keepScreenOn(): void;
        startAlwaysScreenOn(): void;
        stopAlwaysScreenOn(): void;
        getTpUpdateStatus(): number;

        brightnessChanged: JQSignal<boolean>;
        screenStatusChanged: JQSignal<boolean>;
        brightnessValueChanged: JQSignal<number>;
        startAlwaysScreenOnTriggered: JQSignal<boolean>;
        stopAlwaysScreenOnTriggered: JQSignal<boolean>;
        tpUpdateResult: JQSignal<number>;

        on(event: 'brightnessChanged', callback: (changed: boolean) => void): void;
        on(event: 'screenStatusChanged', callback: (isOn: boolean) => void): void;
        on(event: 'brightnessValueChanged', callback: (val: number) => void): void;
        on(event: 'startAlwaysScreenOnTriggered', callback: (triggered: boolean) => void): void;
        on(event: 'stopAlwaysScreenOnTriggered', callback: (triggered: boolean) => void): void;
        on(event: 'tpUpdateResult', callback: (code: number) => void): void;
    }

    // ==========================================
    // 2. Sound & Media Player
    // ==========================================
    interface SoundPlayerModule {
        play(source: string, type: string, extra: string, loop: number): void;
        playFile(path: string, offset: number, speed: number, autoStop: boolean, duration: number): void;
        playBase64(data: string): void;
        playOnlineAudio(url: string): void;
        playOnlineAudioByMoreTransApp(url: string, params: string): void;
        playMediaSection(jsonConfig: string): void;
        playTts(text: string, voiceType: string): void;
        playStreamTts(streamUrl: string, text: string, lang: string): void;
        setPlayTTSParam(paramsJson: string): void;
        switchTtsAutoPronType(pronType: number): void;
        stop(): void;
        quickStop(): void;

        mediaPlayerPositionChanged: JQSignal<number>;
        mediaPlayerDurationChanged: JQSignal<number>;
        mediaPlayerProgressChanged: JQSignal<number>;
        mediaPlayerEndChanged: JQSignal<boolean>;
        mediaPlayerEndWithErrorChanged: JQSignal<number>;
        mediaPlayerEndWithErrorChangedEx: JQSignal<string>;
        ttsDataStarted: JQSignal<boolean>;
        onTtsError: JQSignal<number>;

        on(event: 'mediaPlayerPositionChanged', cb: (posMs: number) => void): void;
        on(event: 'mediaPlayerDurationChanged', cb: (durationMs: number) => void): void;
        on(event: 'mediaPlayerProgressChanged', cb: (progressPercent: number) => void): void;
        on(event: 'mediaPlayerEndChanged', cb: (completed: boolean) => void): void;
        on(event: 'mediaPlayerEndWithErrorChanged', cb: (errCode: number) => void): void;
        on(event: 'ttsDataStarted', cb: (started: boolean) => void): void;
        on(event: 'onTtsError', cb: (errCode: number) => void): void;
    }

    // ==========================================
    // 3. Wi-Fi Networking
    // ==========================================
    interface WifiAccessPoint {
        ssid: string;
        bssid: string;
        rssi: number;
        flags: string;
    }

    interface WifiModule {
        open(): void;
        close(): void;
        isOpen(): boolean;
        isConnected(): boolean;
        scan(): void;
        connect(ssid: string, psk: string): void;
        disconnect(ssid: string): void;
        getIP(): string;
        getState(): number;
        getWifiQual(): string;
        startWifiQualTimer(): void;
        stopWifiQualTimer(): void;
        onGetWifiPassWd(ssid: string): string;

        listChanged: JQSignal<string>;
        statusChanged: JQSignal<number>;
        internetConnectChanged: JQSignal<boolean>;
        qualChanged: JQSignal<string>;
        wifiScanError: JQSignal<number>;

        on(event: 'listChanged', cb: (jsonList: string) => void): void;
        on(event: 'statusChanged', cb: (status: number) => void): void;
        on(event: 'internetConnectChanged', cb: (connected: boolean) => void): void;
        on(event: 'qualChanged', cb: (qual: string) => void): void;
        on(event: 'wifiScanError', cb: (code: number) => void): void;
    }

    // ==========================================
    // 4. Bluetooth & BLE
    // ==========================================
    interface BluetoothModule {
        open(): void;
        close(): void;
        isBtOpen(): boolean;
        isConnected(): boolean;
        scanStart(): void;
        scanStop(): void;
        connect(mac: string, name: string): void;
        disconnect(mac: string, name: string): void;
        remove(mac: string, name: string): void;
        btStatus(): number;
        btGetBattery(): number;
        btGetColor(): string;
        btGetInfo(): string;
        checkDoing(): boolean;

        bleOpen(): void;
        bleClose(): void;
        isBleOpen(): boolean;
        isConnectBle(): boolean;
        bleDisconnect(mac: string): void;
        bleWrite(mac: string, hexData: string): void;

        bluetoothSwitchChanged: JQSignal<boolean>;
        bluetoothScanChanged: JQSignal<boolean>;
        connectDevice: JQSignal<string>;
        disconnectDevice: JQSignal<string>;
        removeDevice: JQSignal<string>;
        deviceListChanged: JQSignal<string>;
        pairedListChanged: JQSignal<string>;
        batteryChanged: JQSignal<string>;
        bluetoothConnectStatusChanged: JQSignal<boolean>;
        bleStatusChanged: JQSignal<number>;
        btError: JQSignal<number>;

        on(event: 'bluetoothSwitchChanged', cb: (isOpen: boolean) => void): void;
        on(event: 'bluetoothScanChanged', cb: (isScanning: boolean) => void): void;
        on(event: 'deviceListChanged', cb: (devicesJson: string) => void): void;
        on(event: 'pairedListChanged', cb: (pairedJson: string) => void): void;
        on(event: 'bluetoothConnectStatusChanged', cb: (connected: boolean) => void): void;
        on(event: 'batteryChanged', cb: (batteryLevel: string) => void): void;
    }

    // ==========================================
    // 5. Physical Keys, Scan Pen Tip & Hall Sensors
    // ==========================================
    interface ButtonEventModule {
        isHeadButtonPressed(): boolean;
        setButtonEventReady(ready: boolean): void;
        softButtonEvent(keyCode: number, action: number): void;
        emitBottomSwipeBackEvent(): void;

        // Scan Pen Tip Switch
        headButtonPress: JQSignal<number>;
        headButtonRelese: JQSignal<number>;

        // Home Button
        homeButtonPress: JQSignal<number>;
        homeButtonRelease: JQSignal<number>;
        homeButtonLongPress: JQSignal<number>;
        homeButtonClick: JQSignal<number>;
        homeButtonDoubleClick: JQSignal<number>;

        // Power Button
        powerButtonPress: JQSignal<number>;
        powerButtonRelese: JQSignal<number>;
        powerButtonLongPress: JQSignal<number>;
        powerButtonClick: JQSignal<number>;
        powerButtonDoubleClick: JQSignal<number>;

        // Play Button
        playButtonPress: JQSignal<number>;
        playButtonRelese: JQSignal<number>;
        playButtonLongPress: JQSignal<number>;
        playButtonClick: JQSignal<number>;
        playDoubleClick: JQSignal<number>;

        // Volume Buttons
        volumeUpButtonPress: JQSignal<number>;
        volumeUpButtonRelese: JQSignal<number>;
        volumeDownButtonPress: JQSignal<number>;
        volumeDownButtonRelese: JQSignal<number>;

        // Sensors
        hallTop: JQSignal<number>;
        hallBottom: JQSignal<number>;
        rotaryTurn: JQSignal<number>;

        on(event: 'headButtonPress', cb: (code: number) => void): void;
        on(event: 'headButtonRelese', cb: (code: number) => void): void;
        on(event: 'homeButtonClick', cb: (code: number) => void): void;
        on(event: 'powerButtonPress', cb: (code: number) => void): void;
        on(event: 'hallTop', cb: (state: number) => void): void;
        on(event: 'hallBottom', cb: (state: number) => void): void;
        on(event: 'rotaryTurn', cb: (delta: number) => void): void;
    }

    // ==========================================
    // 6. Battery Information
    // ==========================================
    interface BatteryInfoInstance {
        getBatteryCapacity(): number;
        getBatteryStatus(): string;
        isCharging(): boolean;
        batteryInfoChange: JQSignal2<boolean, number>;
        on(event: 'batteryInfoChange', cb: (isCharging: boolean, capacity: number) => void): void;
    }

    interface BatteryInfoConstructor {
        new(): BatteryInfoInstance;
    }

    // ==========================================
    // 7. System & Device Information
    // ==========================================
    interface SystemInfoModule {
        getVersion(): string;
        getSNInfo(): string;
        getUUIDInfo(): string;
        getMacInfo(): string;
        getDeviceName(): string;
        getDeviceType(): string;
        getSKU(): string;
        getSKUSerial(): string;
        getSKUCfg(): string;
        getDeviceSKUInfo(): string;
        getStorageInfo(): string;
        getAvailableSpace(): number;
        getSystemFlashSize(): number;
        getSystemTime(): string;
        updateCurrentSystemTime(): void;
        getAdbEnable(): number;
        setAdbEnable(enable: number): void;
        getHandedness(): number;
        setHandedness(mode: number): void;
        feedWatchdog(): void;
        closeBootLogo(): void;
        powerOff(): void;
        resetFactory(level: number): void;

        currentSystemTimeChange: JQSignal<string>;
        on(event: 'currentSystemTimeChange', cb: (newTime: string) => void): void;
    }

    // ==========================================
    // 8. Global OCR & App Pipeline
    // ==========================================
    interface GlobalModule {
        currentAppId(): string;
        setCurrentAppId(appId: string, flag: boolean): void;
        getLastAppId(): string;
        getPreviousAppId(): string;
        setNavToAppId(appId: string): void;
        startScan(): void;
        isOnline(): boolean;
        showToast(msg: string, duration?: number): void;
        showSystemDialog(configJson: string): void;
        translate(text: string, srcLang: string, tgtLang: string): void;

        ocrResultChanged: JQSignal<string>;
        scanArticleResultChanged: JQSignal<string>;
        scanTranslatorResultChanged: JQSignal<string>;
        ocrStartChanged: JQSignal<boolean>;
        ocrStopChanged: JQSignal<boolean>;
        onCurrentAppIdChanged: JQSignal<string>;

        on(event: 'ocrResultChanged', cb: (json: string) => void): void;
        on(event: 'scanTranslatorResultChanged', cb: (json: string) => void): void;
        on(event: 'ocrStartChanged', cb: (started: boolean) => void): void;
        on(event: 'ocrStopChanged', cb: (stopped: boolean) => void): void;
    }

    // ==========================================
    // 9. Hardware Volume
    // ==========================================
    interface VolumeModule {
        getVolume(): number;
        setVolume(level: number): void;
        getCurrentShowPage(): string;
        volumeChanged: JQSignal<number>;
        callBackVolumeValue: JQSignal<number>;
        on(event: 'volumeChanged', cb: (vol: number) => void): void;
    }
}

// Module declaration for ES Module imports
declare module 'brightness' {
    const brightness: Falcon.BrightnessModule;
    export default brightness;
}

declare module 'soundPlayer' {
    const soundPlayer: Falcon.SoundPlayerModule;
    export default soundPlayer;
}

declare module 'wifi' {
    const wifi: Falcon.WifiModule;
    export default wifi;
}

declare module 'bluetooth' {
    const bluetooth: Falcon.BluetoothModule;
    export default bluetooth;
}

declare module 'buttonEvent' {
    const buttonEvent: Falcon.ButtonEventModule;
    export default buttonEvent;
}

declare module 'batteryInfo' {
    export const BatteryInfo: Falcon.BatteryInfoConstructor;
    const defaultExport: { BatteryInfo: Falcon.BatteryInfoConstructor };
    export default defaultExport;
}

declare module 'systemInfo' {
    const systemInfo: Falcon.SystemInfoModule;
    export default systemInfo;
}

declare module 'global' {
    const global: Falcon.GlobalModule;
    export default global;
}

declare module 'volume' {
    const volume: Falcon.VolumeModule;
    export default volume;
}
```

---

## 7. Production-Ready JavaScript Implementations

Every example in this section is verified against runtime call conventions on the CV1813H device.

### 7.1 Pen Tip Scan & OCR Translation Controller

```javascript
import buttonEvent from 'buttonEvent';
import global from 'global';
import soundPlayer from 'soundPlayer';

export class ScanPenController {
    constructor() {
        this.isScanning = false;
        this.initEventListeners();
    }

    initEventListeners() {
        // 1. Notify native driver that event listeners are ready
        buttonEvent.setButtonEventReady(true);

        // 2. Listen to physical pen tip trigger switch
        buttonEvent.headButtonPress.connect((keyCode) => {
            console.log("[ScanPen] Pen tip pressed down on paper (code:", keyCode, ")");
            this.isScanning = true;
            // Native camera sensor automatically begins frame capture
        });

        buttonEvent.headButtonRelese.connect((keyCode) => {
            console.log("[ScanPen] Pen lifted off paper (code:", keyCode, ")");
            this.isScanning = false;
        });

        // 3. Connect to OCR results pipeline
        global.ocrStartChanged.connect((started) => {
            if (started) {
                console.log("[ScanPen] Neural stitcher & OCR pipeline active");
            }
        });

        global.ocrResultChanged.connect((resultJson) => {
            try {
                const parsed = JSON.parse(resultJson);
                console.log("[ScanPen] OCR Recognized text:", parsed.text);
                
                // Automatically pronounce the recognized English word via TTS
                if (parsed.text && parsed.lang === 'en') {
                    soundPlayer.playTts(parsed.text, 'en');
                }
            } catch (err) {
                console.error("[ScanPen] Failed to parse OCR result payload:", err);
            }
        });
    }

    checkPenState() {
        return buttonEvent.isHeadButtonPressed();
    }
}
```

### 7.2 Low-Latency Audio & Streaming TTS Playback

```javascript
import soundPlayer from 'soundPlayer';

export class AudioService {
    constructor() {
        this.setupSignals();
    }

    setupSignals() {
        soundPlayer.mediaPlayerPositionChanged.connect((posMs) => {
            // Updated every 100ms during active playback
            // Avoid console spam in production; dispatch to UI state
        });

        soundPlayer.mediaPlayerEndChanged.connect((finished) => {
            if (finished) {
                console.log("[Audio] Playback completed successfully");
            }
        });

        soundPlayer.mediaPlayerEndWithErrorChanged.connect((errCode) => {
            console.error("[Audio] Playback failed with error code:", errCode);
        });

        soundPlayer.ttsDataStarted.connect((started) => {
            if (started) {
                console.log("[Audio] First TTS audio frame emitted by DAC");
            }
        });

        soundPlayer.onTtsError.connect((errorCode) => {
            console.error("[Audio] TTS synthesis failed with code:", errorCode);
        });
    }

    playWordPronunciation(word, isBritish = false) {
        // Configure British (1) or American (2) accent
        soundPlayer.switchTtsAutoPronType(isBritish ? 1 : 2);
        
        // Configure speed rate and pitch
        soundPlayer.setPlayTTSParam(JSON.stringify({
            speed: 1.0,
            volume: 100,
            pitch: 50
        }));

        soundPlayer.playTts(word, 'en');
    }

    playLocalPrompt(fileName) {
        const fullPath = `/userdata/media/${fileName}`;
        // playFile(path, offsetMs, speed, autoStop, durationMs)
        soundPlayer.playFile(fullPath, 0, 1.0, true, 0);
    }

    stopImmediate() {
        soundPlayer.quickStop();
    }
}
```

### 7.3 Wi-Fi Manager with Asynchronous Connection Monitor

```javascript
import wifi from 'wifi';

export class NetworkManager {
    constructor() {
        this.setupHooks();
    }

    setupHooks() {
        wifi.listChanged.connect((jsonApList) => {
            try {
                const aps = JSON.parse(jsonApList);
                console.log(`[WiFi] Scanned ${aps.length} access points:`);
                aps.forEach(ap => console.log(`  - ${ap.ssid} (Signal: ${ap.rssi} dBm)`));
            } catch (e) {
                console.error("[WiFi] AP list JSON parse error:", e);
            }
        });

        wifi.statusChanged.connect((status) => {
            console.log("[WiFi] Connection status transition:", status);
            // 0: Idle/Disconnected, 1: Connecting, 2: Connected
            if (status === 2) {
                console.log("[WiFi] Local IP Address:", wifi.getIP());
            }
        });

        wifi.internetConnectChanged.connect((hasInternet) => {
            console.log("[WiFi] Cloud ping verified. Internet active:", hasInternet);
        });

        wifi.qualChanged.connect((qualLevel) => {
            console.log("[WiFi] Signal RSSI update:", qualLevel);
        });
    }

    scanAndConnect(targetSsid, password) {
        if (!wifi.isOpen()) {
            console.log("[WiFi] Radio powered off. Enabling interface...");
            wifi.open();
        }

        console.log("[WiFi] Triggering BSSID scan...");
        wifi.scan();

        // Connect to target AP
        setTimeout(() => {
            console.log(`[WiFi] Associating with ${targetSsid}...`);
            wifi.connect(targetSsid, password);
        }, 1500);
    }

    startPeriodicRssiMonitoring() {
        wifi.startWifiQualTimer();
    }

    stopPeriodicRssiMonitoring() {
        wifi.stopWifiQualTimer();
    }
}
```

### 7.4 Battery Telemetry & Dynamic Screen Brightness Daemon

```javascript
import batteryInfoModule from 'batteryInfo';
import brightness from 'brightness';

export class PowerAndDisplayController {
    constructor() {
        this.battery = new batteryInfoModule.BatteryInfo();
        this.init();
    }

    init() {
        // Read initial state
        const currentCap = this.battery.getBatteryCapacity();
        const charging = this.battery.isCharging();
        console.log(`[Power] Initial Battery: ${currentCap}%, Charging: ${charging}`);

        // Listen for PMIC state changes
        this.battery.batteryInfoChange.connect((isCharging, capacity) => {
            console.log(`[Power] State changed -> Battery: ${capacity}%, Charging: ${isCharging}`);
            
            // Energy Saver: Dim screen if low battery and not plugged in
            if (capacity <= 15 && !isCharging) {
                console.warn("[Power] Low battery detected! Reducing display brightness.");
                brightness.setBrightness(40);
            }
        });

        // Listen for screen state transitions
        brightness.screenStatusChanged.connect((screenIsOn) => {
            console.log("[Display] Screen power toggled:", screenIsOn ? "ON" : "OFF");
        });

        brightness.brightnessValueChanged.connect((newLevel) => {
            console.log("[Display] Backlight adjusted to:", newLevel);
        });
    }

    preventScreenSleep() {
        console.log("[Display] Enabling Always-Screen-On wake lock");
        brightness.startAlwaysScreenOn();
    }

    allowScreenSleep() {
        console.log("[Display] Releasing Always-Screen-On wake lock");
        brightness.stopAlwaysScreenOn();
    }
}
```

---

## 8. Binary Analysis Summary & Module Matrix

| JavaScript Module Name | C++ Proxy Class Name | Native Shared Library | Primary IPC Transport Channel | Total Methods | Total Signals | Primary Hardware Device Controlled |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `'global'` | `JSGlobalProxy` | `libjsapi_export_core.so` | OpenWrt Ubus & Mutex Loop | 115 | 45 | OCR Engine, NMT Translation, Watchdog |
| `'soundPlayer'` | `JSSoundPlayerProxy` | `libjsapi_export_core.so` | Shared Memory (`YShmSync`) | 12 | 8 | Audio DAC, Offline TTS, Streaming Audio |
| `'wifi'` | `JSWifiProxy` | `libjsapi_export_core.so` | UNIX Domain Sockets (`wpa_ctrl`) | 14 | 5 | Realtek / AIC Wi-Fi Baseband |
| `'bluetooth'` | `JSBlueToothProxy` | `libjsapi_export_core.so` | BlueZ / Realtek Stack IPC | 20 | 18 | Bluetooth Classic (A2DP) & BLE GATT |
| `'brightness'` | `JSBrightnessProxy` | `libjsapi_export_core.so` | Linux Sysfs PWM Backlight | 8 | 6 | PWM Backlight, OLED Power, Touch Panel |
| `'buttonEvent'` | `JSButtonEventModuleProxy` | `libjsapi_export_core.so` | Linux Evdev (`/dev/input/event0`) | 4 | 45 | Pen Tip Microswitch, Keys, Hall, Rotary |
| `'batteryInfo'` | `BatteryInfo` | `libyddal_adapter.so` | Sysfs AXP2101 PMIC & Ubus | 3 | 1 | AXP2101 PMIC Fuel Gauge / Coulomb Meter |
| `'systemInfo'` | `JSystemInfoProxy` | `libjsapi_export_core.so` | Linux Kernel Sysinfo & RTC | 26 | 1 | eMMC Flash, Device SN/UUID, RTC, Watchdog |
| `'volume'` | `JSVolumenessProxy` | `libjsapi_export_core.so` | ALSA Mixer Control Interface | 5 | 2 | Master Hardware Codec Output Gain |
| `'gsensor'` | `JSGsensornessProxy` | `libjsapi_export_core.so` | I2C Accelerometer Character Dev | 10 | 2 | 3-Axis Gravity & Shake Sensor |
| `'headSetInfo'` | `JHeadSetInfoProxy` | `libjsapi_export_core.so` | Linux Audio Jack & BT Routing | 4 | 7 | 3.5mm Headphone Jack & BT A2DP Routing |
| `'lte'` | `JSLteProxy` | `libjsapi_export_core.so` | USB ECM Modem / AT Daemon | 12 | 2 | 4G LTE Cellular Baseband Modem |
| `'tel'` | `JSTelProxy` | `libjsapi_export_core.so` | Cellular Voice & SMS Modem | 23 | 16 | Voice Calling, SIM PIN, SMS Messaging |
| `'headCamera'` | `JSHeadCameraProxy` | `libjsapi_export_core.so` | V4L2 Video Device & OID Sensor | 7 | 1 | High-Speed Pen Tip CMOS Sensor (OID) |
| `'httpbridge'` | `JSHttpBridgeProxy` | `libjsapi_export_core.so` | Authenticated Proxy Thread | 2 | 1 | HTTPS Request Dispatch via Device Certs |
| `'logmanager'` | `JSLogManagerProxy` | `libjsapi_export_core.so` | Local File Append & Diagnostic | 9 | 0 | Performance Clocks, Spy Logs, Crash Logs |
| `'userCenterCommon'` | `JSUserCenterCommonProxy`| `libjsapi_export_core.so` | Encrypted SQLite Cookie Store | 11 | 10 | NetEase VIP, User Avatar, Grade Level |
| `'yStrUtils'` | `JSStrUtilsProxy` | `libjsapi_export_core.so` | Direct CPU C++ Routine | 3 | 0 | UUIDv4 Generation, Language Detection |
