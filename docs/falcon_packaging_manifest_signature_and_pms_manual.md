# NetEase Youdao Dictionary Pen S7 Pro: Falcon Application Packaging, Manifest Schema, Cryptographic Integrity & PMS Subsystem Technical Reference Manual

---

## 1. Architectural Overview & Threat Model Analysis

### 1.1 Target Hardware & Operating System Topology
The NetEase Youdao Dictionary Pen S7 Pro (Hardware Identifier: `YDP072` / `y08_platform` / `coco_platform`) runs an embedded Linux operating system on a heterogeneous dual-core Cvitek CV1813H System-on-Chip (SoC). The primary execution environment is an ARM Cortex-A7 32-bit core executing in little-endian mode (`armv7l`, ARMv7-A architecture with VFPv4 and NEON SIMD extensions) running Linux kernel version 5.10.4.

Application execution on the device is governed by the **Falcon Runtime Engine** (`libfalcon.so` and the `miniapp` host daemon). Falcon provides an event-driven, reactive UI and component subsystem layered on top of an embedded **QuickJS bytecode virtual machine** and a 2D rendering graphics pipeline.

```
+-----------------------------------------------------------------------------------+
|                           Linux Userspace Runtime Model                           |
+-----------------------------------------------------------------------------------+
|  [ miniapp_cli ] (CLI client)                 [ Launcher: 8080222437664451 ]      |
|         |                                                    ^                    |
|    UNIX Domain Socket                                   JQPublishObject           |
|  (/var/run/miniapp-dbg.socket)                       ("package" JSON IPC)         |
|         v                                                    |                    |
|  +-----------------------------------------------------------------------------+  |
|  | miniapp Daemon (Host Process / PID owner)                                   |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  |  | libfalcon.so (Falcon Engine Core)                                     |  |  |
|  |  |  * PkgUploadViews (Embedded HTTP REST API Router)                     |  |  |
|  |  |  * JQuick::IotPackageManager (PMS Engine & Worker Thread)             |  |  |
|  |  |  * pm::JSPackageManager (JS Binding Bridge to QuickJS)                |  |  |
|  |  |  * patchelf_rpath_deps / chrpathSoFiles (Dynamic Linker Rewriter)     |  |  |
|  |  |  * QuickJS Engine (Bytecode VM & Module Loader)                       |  |  |
|  |  +-----------------------------------------------------------------------+  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### 1.2 Component Boundaries & Partition Layout
The filesystem architecture separates read-only system firmware, factory assets, user application binaries, and persistent storage into distinct mount points:

| Partition / Mount Point | Access Type | Filesystem Type | Purpose |
|:---|:---|:---|:---|
| `/` (Rootfs) | Read-Only | SquashFS / ext4 | Core Linux utilities, `miniapp`, system shared libraries |
| `/etc/miniapp/` | Read-Only | Rootfs symlink | System runtime configs, default fonts, framework bytecode (`jsfm`) |
| `/oem/` | Read-Only | ext4 / squashfs | OEM vendor assets, factory calibration, secondary packages |
| `/userdata/` | Read-Write | ext4 | Primary writable partition: app data, PMS registry, package slots |
| `/userdisk/` | Read-Write | FAT32 / ext4 | Mass storage partition (accessible via USB MTP/Mass Storage) |
| `/var/run/` | Read-Write | tmpfs (RAM) | Ephemeral IPC domain sockets (`miniapp-dbg.socket`) |

The Package Management Service (PMS) maintains all installed applications under:
```
/userdata/miniapp/data/mini_app/pkg/
```
Each installed miniapp resides in a directory named after its numeric 16-digit Application ID (`<appid>`), containing alternating execution slots (`a/` or `b/`) and a sandbox data directory (`data/`).

---

## 2. Package Archive File Format (.amr) & Low-Level Extraction Pipeline

### 2.1 File Container Format & Magic Byte Signatures
Despite the `.amr` file extension—which normally denotes Adaptive Multi-Rate speech audio files—Falcon miniapp installation packages are standard **PKZIP 2.0 archives**. There is **no outer cryptographic container, proprietary wrapper header, or symmetric encryption envelope**.

The binary signature of an `.amr` package begins directly with the standard ZIP Local File Header magic bytes:
```hex
50 4B 03 04 14 00 00 00 08 00 ...  (PK\x03\x04, version 20, Deflate)
```

```
+-----------------------------------------------------------------------------+
|                     Falcon .amr Package Binary Layout                       |
+-----------------------------------------------------------------------------+
| Offset | Field                         | Value / Content                    |
+--------+-------------------------------+------------------------------------+
| 0x0000 | Magic Header                  | 0x04034B50 ("PK\x03\x04")          |
| 0x0004 | Version Needed to Extract     | 0x0014 (2.0)                       |
| 0x0006 | General Purpose Bit Flag      | 0x0000 or 0x0800 (UTF-8 filenames) |
| 0x0008 | Compression Method            | 0x0008 (Deflate) or 0x0000 (Store) |
| 0x000A | Last Mod File Time / Date     | DOS 16-bit packed timestamp        |
| 0x000E | CRC-32 Checksum               | Uncompressed data CRC-32           |
| 0x0012 | Compressed Size               | Size in archive                    |
| 0x0016 | Uncompressed Size             | Size on disk                       |
| 0x001A | File Name Length (n)          | Length of path string              |
| 0x001C | Extra Field Length (m)        | Length of extra metadata           |
| 0x001E | File Name                     | "manifest.json", "app.js.bin", etc |
| ...    | File Data Payload             | Deflated / Stored file bytes       |
| ...    | Central Directory Header      | 0x02014B50 ("PK\x01\x02")          |
| End    | End of Central Directory      | 0x06054B50 ("PK\x05\x06")          |
+-----------------------------------------------------------------------------+
```

### 2.2 Unpacking Engine Disassembly: `miniUnzip`
Package extraction is handled by `miniUnzip` located at virtual address `0x579950` in `libfalcon.so`, which compiles in an embedded version of the Info-ZIP `minizip` library:

```armasm
; Disassembly: miniUnzip in libfalcon.so (0x579950)
0x579950:  push     {r4, r5, r6, r7, r8, sb, sl, fp, lr}
0x579954:  mov      r7, r1                   ; r7 = Destination extraction directory
0x579958:  mov      r4, r0                   ; r4 = Path to .amr package file
0x57995c:  sub      sp, sp, #0x2c
0x579960:  bl       #0x1db904                ; PLT: unzOpen64(amrPath)
0x579964:  subs     r6, r0, #0               ; Check if zip handle is valid
0x579968:  beq      0x579a40                 ; If NULL, branch to error exit (-1)
0x57996c:  mov      r1, r7                   ; Target destination directory
0x579970:  mov      r0, r6                   ; Zip archive handle
0x579974:  bl       #0x5797f0                ; Call internal do_extract(unzFile, destDir)
0x579978:  mov      r4, r0                   ; r4 = extract result status (0 = success)
0x57997c:  mov      r0, r6
0x579980:  bl       #0x1db71c                ; PLT: unzClose(unzFile)
0x579984:  mov      r0, r4
0x579988:  add      sp, sp, #0x2c
0x57998c:  pop      {r4, r5, r6, r7, r8, sb, sl, fp, pc}
```

The extraction routine iterates sequentially through each file in the ZIP central directory using `unzGoToFirstFile` and `unzGoToNextFile`. For each entry:
1. `unzGetCurrentFileInfo64` reads the stored relative pathname.
2. A sanitization check verifies that the relative path does not escape the destination directory (preventing directory traversal attacks like `../../`).
3. Directories are created via `mkdir(path, 0755)`.
4. File payloads are uncompressed via zlib's `inflate()` and streamed into the target directory.

---

## 3. Application Manifest Schema: Comprehensive Specification

### 3.1 Parser Disassembly: `IotPackageManager::executeInstallPackage`
Immediately after `miniUnzip` extracts the archive to a temporary staging directory (typically under `/userdata/miniapp/data/mini_app/pkg/temp_<pid>/` or `/tmp/`), Falcon parses `/manifest.json`:

```armasm
; Disassembly: Manifest Extraction in executeInstallPackage (0x25f62c - 0x25f880)
0x25f62c:  bl   FileUtil::ReadFileAsString(tmpDir + "/manifest.json")
0x25f660:  bl   JQuick::Json::parse(content, error_str, JSON_PARSE_STANDARD)
0x25f738:  bl   JQuick::Json::operator[]("appid")      ; Look up appid
0x25f744:  bl   JQuick::Json::string_value()
0x25f774:  bl   JQuick::Json::operator[]("appName")    ; Look up appName
0x25f780:  bl   JQuick::Json::string_value()
0x25f7b0:  bl   JQuick::Json::operator[]("props")      ; Look up props object
0x25f800:  bl   JQuick::Json::operator[]("version")    ; Look up version string
0x25f80c:  bl   JQuick::Json::string_value()
0x25f83c:  bl   JQuick::Json::operator[]("icon")       ; Look up icon file path
0x25f848:  bl   JQuick::Json::string_value()
0x25f860:  ldr  r3, [sp, #appid_len]                   ; Verify appid is not empty
0x25f864:  cmp  r3, #0
0x25f868:  beq  0x25fef0                               ; Abort if appid missing!
0x25f870:  ldr  r3, [sp, #version_len]                 ; Verify version is not empty
0x25f874:  cmp  r3, #0
0x25f878:  beq  0x25fef0                               ; Abort if version missing!
```

### 3.2 Canonical `manifest.json` Data Dictionary

The manifest defines runtime metadata, window parameters, platform targeting, dynamic cleanup rules, and cryptographic checksum declarations:

| JSON Key | Type | Required | Description | Default / Example |
|:---|:---|:---|:---|:---|
| `appid` | String | **Yes** | 16-digit unique numeric package identifier | `"8080999900000001"` |
| `appName` | String | **Yes** | Human-readable application title | `"CustomApp"` |
| `version` | String | **Yes** | Semantic version string (`MAJOR.MINOR.PATCH`) | `"1.0.0"` |
| `versionCode` | Integer | No | Numeric incremental version counter | `100` |
| `icon` | String | **Yes** | Path to default app icon relative to package root | `"icon.png"` |
| `main` | String | No | Application entrypoint script | `"app.js.bin"` |
| `window` | Object | No | Root viewport and window framing parameters | `{ ... }` |
| `props` | Object | No | Platform, lifecycle, and desktop integration rules | `{ ... }` |
| `cert` | Object | **Yes\*** | File integrity verification map (\*can be empty `{}`) | `{ ... }` |

#### The `window` Configuration Object
Governs the framebuffer viewport rendering for the primary application window:

```json
"window": {
  "navigationBarTitleText": "App Window Title",
  "navigationBarBackgroundColor": "#FFFFFF",
  "navigationBarTextStyle": "black",
  "navigationStyle": "custom",
  "fullscreen": true,
  "orientation": "portrait"
}
```

* `navigationBarTitleText` (String): Default window title displayed in the system status bar.
* `navigationBarBackgroundColor` (String): Hex RGB color of the navigation bar background.
* `navigationStyle` (String): `"default"` renders system header bar; `"custom"` renders borderless canvas for full-screen UI.
* `fullscreen` (Boolean): If `true`, the application window takes over the complete display (1440x720 or 800x480).
* `orientation` (String): Screen orientation mode (`"portrait"`, `"landscape"`, `"auto"`).

#### The `props` Metadata Object
The `props` dictionary controls installation behavior, desktop visibility, theme-adaptive icons, and filesystem cleanup hooks:

| Subkey | Type | Purpose & Behavior |
|:---|:---|:---|
| `supportUnInstall` | Boolean | If `false`, PMS rejects uninstallation requests (marks package as system-protected). |
| `supportCleanUp` | Boolean | If `true`, PMS triggers cleanup routines when uninstalled or reset. |
| `extraCleanupDirectories` | Array of Strings | Directory paths purged from flash storage upon package removal. |
| `extraCleanupFiles` | Array of Strings | Explicit file paths purged from flash storage upon package removal. |
| `addDesktop` | Object | Platform whitelist controlling launcher desktop visibility. |
| `Icons` | Object | Map of theme IDs to customized icon resource paths. |
| `AppTitle` | Object | Map of theme IDs to localized/customized application display titles. |
| `page_rotation` | Object | Page-level rotation settings (`{"index": "inherit"}`). |
| `Invisible` | Boolean | If `true`, forces the launcher desktop to hide the app icon regardless of `addDesktop`. |
| `isSystem` | Boolean | Declares whether the application runs with elevated system manager privileges. |

#### Platform Whitelisting (`addDesktop`)
The Falcon launcher queries `props.addDesktop` to determine if an icon card should be created on the home desktop:

```json
"addDesktop": {
  "y08_platform": true,
  "coco_platform": true,
  "orange_platform": false
}
```
* `y08_platform`: Youdao Dictionary Pen S7 Pro hardware revision.
* `coco_platform`: S7 Pro international / educational firmware variant.
* `orange_platform`: Previous generation hardware (Dictionary Pen P6 / X6). Setting this to `false` disables rendering on older platforms.

#### Theme-Adaptive Icon Resolution (`Icons`)
The launcher dynamically adapts to the user's active desktop theme by resolving icons declared in `props.Icons`:

```json
"Icons": {
  "theme-popcorn": "assets/images/app_icon/theme-popcorn/app_icon.png",
  "theme-y06": "assets/images/app_icon/theme-y06/app_icon.png",
  "theme-hermes": "assets/images/app_icon/theme-hermes/app_icon.png",
  "theme-exam": "assets/images/app_icon/theme-exam/app_icon.png"
}
```
If the active system theme matches a key in `Icons`, the launcher loads that specialized asset; otherwise, it falls back to the top-level `"icon"` path.

---

## 4. Cryptographic Verification & Integrity Auditing Subsystem

### 4.1 Disassembly of `verifyAmrContent`
Package integrity verification is performed by `JQuick::IotPackageManager::verifyAmrContent` located at virtual address `0x258934` in `libfalcon.so`:

```armasm
; Disassembly: JQuick::IotPackageManager::verifyAmrContent (0x258934)
; Arguments:
;   r0: Pointer to destination return value / this
;   r1: std::string const& stagingDir (Path where archive was unpacked)
;   r2: JQuick::Json const& manifestJson (Parsed manifest.json DOM)

0x258934:  push     {r4, r5, r6, r7, r8, sb, sl, fp, lr}
0x258938:  mov      r8, r2                   ; r8 = manifestJson
0x25893c:  mov      r7, r1                   ; r7 = stagingDir
0x258940:  sub      sp, sp, #0xec
0x258968:  ldr      r1, =aCert               ; Literal: "cert"
0x25896c:  mov      r0, r8
0x258970:  bl       JQuick::Json::operator[] ; r0 = manifest["cert"]
0x258974:  bl       JQuick::Json::object_items ; Extract std::map<string, Json>
0x258988:  ldr      r0, [sp, #map_begin]
0x25898c:  ldr      r3, [sp, #map_end]
0x258990:  cmp      r0, r3                   ; IS CERT MAP EMPTY?
0x258994:  beq      0x258be0                 ; IF EMPTY: JUMP TO SUCCESS (RETURN 1)!

; --- Integrity Validation Loop for declared entries ---
0x2589b0:  ; Loop over each key-value pair in manifest["cert"]
0x2589f0:  bl   std::string::append          ; filePath = stagingDir + "/" + relativePath
0x258a4c:  bl   FileUtil::FileExists         ; Verify file existence on disk
0x258a50:  cmp  r0, #0
0x258a54:  beq  0x258d40                     ; Abort if file does not exist!
0x258ac8:  bl   FileUtil::GetFileSize        ; Query actual file size
0x258b00:  ldr  r2, [certEntry_size]         ; Compare with declared size
0x258b04:  cmp  r0, r2
0x258b08:  bne  0x258d40                     ; Abort if file size mismatches!
0x258b40:  bl   FileUtil::ReadFileAsString   ; Read file content into RAM
0x258b4c:  bl   md5()                        ; Compute 128-bit MD5 hash
0x258c14:  bl   memcmp                       ; Compare calculated MD5 with cert["md5"]
0x258c18:  cmp  r0, #0
0x258c1c:  bne  0x258d40                     ; Abort if hash does not match!
0x258c40:  ; Advance to next map entry...
0x258c70:  bne  0x2589b0

; --- Verification Success Exit ---
0x258be0:  mov  r4, #1                       ; Return 1 (Verification Success)
0x258be4:  b    0x258d50

; --- Verification Failure Exit ---
0x258d40:  mov  r4, #0                       ; Return 0 (Verification Failed)
0x258d50:  mov  r0, r4
0x258d54:  add  sp, sp, #0xec
0x258d58:  pop  {r4, r5, r6, r7, r8, sb, sl, fp, pc}
```

### 4.2 Structural Manifestation of the `cert` Object
When non-empty, the `"cert"` object maps individual relative file paths to their expected sizes and MD5 checksum strings:

```json
"cert": {
  "app.js.bin": {
    "size": 48292,
    "md5": "d41d8cd98f00b204e9800998ecf8427e"
  },
  "indexPage.js.bin": {
    "size": 118826,
    "md5": "7b8b965ad4bca0e41ab51de7b31363a1"
  },
  "icon.png": {
    "size": 8192,
    "md5": "9e107d9d372bb6826bd81d3542a419d6"
  }
}
```

### 4.3 Vulnerability Audit & Architectural Verification Flaws

#### Vulnerability 1: The Empty `cert` Bypass (`0x258990`)
At instruction `0x258990`, the comparator evaluates whether the iterator `begin()` equals `end()` for the `cert` JSON object. If `manifest.json` contains:
```json
"cert": {}
```
The comparison evaluates as true, immediately branching to `0x258be0` which loads `r4 = #1` and returns **SUCCESS**.
* **Impact**: No file hashes, signatures, or sizes are checked. Any arbitrary QuickJS bytecode, JavaScript, assets, or native shared libraries inside the `.amr` package are accepted and installed without cryptographic checks.

#### Vulnerability 2: Whitelist Map Traversal Flaw
Even when `"cert"` is populated with valid entries, the verification loop strictly iterates across the keys present in the `manifest.json["cert"]` map:
```cpp
// Decompiled representation of verification loop
for (auto const& [file_path, meta] : manifest["cert"].object_items()) {
    if (!verify_single_file(stagingDir + "/" + file_path, meta)) {
        return 0; // Fail
    }
}
return 1; // Success!
```
At no point does the verification routine call `opendir()` or `readdir()` to enumerate files actually extracted from the archive onto disk.
* **Impact**: An attacker can provide a valid `"cert"` block verifying a benign file (e.g. `"icon.png"`), while bundling unlisted executable files (such as malicious native shared libraries under `libs/` or supplementary JS modules). These unlisted files are completely ignored by `verifyAmrContent`, extracted, dynamic-linker patched, and executed.

### 4.4 Cryptographic Symbol Audit: Absence of Asymmetric Signatures
An exhaustive audit of the dynamic symbol table (`.dynsym`) and relocation table (`.rel.dyn`) of both `/usr/bin/miniapp` and `/usr/lib/libfalcon.so` confirms:

1. **Zero Public-Key Signatures**: There are **no references** to RSA, ECDSA, Ed25519, or PKCS#7 verification routines anywhere in the packaging pipeline. Symbols like `mbedtls_rsa_pkcs1_verify`, `mbedtls_ecdsa_verify`, `RSA_verify`, or `EVP_DigestVerifyFinal` are entirely nonexistent in the package management code path.
2. **mbedTLS Scope Restriction**: The `mbedtls_*` functions present in `libfalcon.so` belong exclusively to the network client stack (used by `libcurl`, `cpr`, and WebSocket clients for HTTPS connections).
3. **No Secondary Storage Discrimination**: There are no signature checks or cryptographic gates differentiating internal flash storage (`/userdata/`) from external secondary mass storage (`/userdisk/secondary/miniapps/`). Both locations use the exact same `verifyAmrContent` routine.

---

## 5. Package Management Service (PMS) Subsystem Architecture

### 5.1 Process Model & Dedicated Looper Thread
PMS is initialized during Falcon engine startup via `JQuick::IotPackageManager::init` (`0x25dc3c`). Rather than processing I/O on the main rendering loop, PMS runs on a dedicated background worker thread:

```armasm
; Disassembly: IotPackageManager::init (0x25dc3c)
0x25dc3c:  push    {r4, r5, lr}
0x25dc40:  mov     r4, r0                        ; r4 = this (IotPackageManager)
0x25dc48:  bl      JQuick::IotPackageManager::loadInstalledPackages()
0x25dc4c:  bl      JQuick::IotPackageManager::checkAppsInstallFinished()
0x25dc54:  ldr     r1, =aPm                      ; "pm"
0x25dc58:  mov     r0, #0x28                     ; sizeof(HandlerThread)
0x25dc5c:  bl      operator new(unsigned int)
0x25dc60:  bl      JQuick::HandlerThread::HandlerThread("pm", Priority::NORMAL)
0x25dc64:  mov     r5, r0                        ; r5 = HandlerThread*
0x25dc68:  ldr     r3, [r0]
0x25dc6c:  ldr     r3, [r3, #8]                  ; Start looper thread
0x25dc70:  blx     r3
0x25dc74:  ldr     r3, [r5]
0x25dc78:  mov     r0, r5
0x25dc7c:  ldr     r3, [r3, #0xc]                 ; GetLooper()
0x25dc80:  blx     r3
0x25dc84:  mov     r1, r0                        ; r1 = Looper*
0x25dc88:  mov     r0, #0x18                     ; sizeof(Handler)
0x25dc8c:  bl      operator new(unsigned int)
0x25dc90:  bl      JQuick::Handler::Handler(Looper*)
0x25dc94:  str     r0, [r4, #8]                  ; this->mHandler = new Handler
0x25dc98:  pop     {r4, r5, pc}
```

All asynchronous install and uninstall tasks are posted via `mHandler->post()` to the `pm` looper thread, guaranteeing thread safety during flash filesystem updates.

### 5.2 A/B Slot Allocation Engine
Falcon implements an atomic dual-slot (A/B) deployment architecture per application. This guarantees atomic updates: if power is lost during package extraction or library rewriting, the previously running slot remains intact.

```
/userdata/miniapp/data/mini_app/pkg/<appid>/
├── a/                         <-- Slot A (Version 1.0.0 - Inactive)
│   ├── manifest.json
│   ├── app.js.bin
│   └── libs/
│       ├── libbusiness_app_1234567890.so
│       └── libjsapi_app_1234567890.so
├── b/                         <-- Slot B (Version 1.0.1 - Active)
│   ├── manifest.json
│   ├── app.js.bin
│   └── libs/
│       ├── libbusiness_app_9876543210.so
│       └── libjsapi_app_9876543210.so
└── data/                      <-- Persistent sandbox storage
    ├── kv_store.db
    └── cache/
```

#### Slot Rotation Algorithm
During installation in `executeInstallPackage`, Falcon determines the target slot directory by evaluating existing installations via `getPackageInfo2`:

```armasm
; Disassembly: A/B Slot Selection (0x25fa28 - 0x25fa3c)
0x25fa28:  ldr     r3, [r4, #current_slot]       ; 0 for 'a', 1 for 'b'
0x25fa2c:  eor     r3, r3, #1                    ; new_slot = current_slot ^ 1
0x25fa30:  cmp     r3, #1
0x25fa34:  ldreq   r1, =aSlotB                   ; String literal: "b"
0x25fa38:  ldrne   r1, =aSlotA                   ; String literal: "a"
0x25fa3c:  bl      std::string::append           ; appDir + "/" + slot
```

1. If the app is freshly installed (no prior record in `packages.json`), Falcon assigns slot `a`.
2. If the app is already installed in slot `a`, Falcon installs the new version into slot `b`.
3. If the app is currently active in slot `b`, Falcon installs into slot `a`.
4. Staging files are moved into the newly selected slot using `rename()` (`0x25fdb0`). If cross-filesystem boundaries are encountered, it falls back to `FileUtil::CopyDir` (`0x25fddc`).

### 5.3 Dynamic Linker Path Patching Engine (`chrpathSoFiles`)
Applications bundling native C++ plugins place their shared objects under the `libs/` directory. If multiple apps load libraries named `libjsapi.so`, the Linux runtime dynamic linker (`ld-linux.so`) would experience namespace collisions or load cached symbols from previous apps.

To solve this, Falcon incorporates an in-process ELF rewriting engine (`chrpathSoFiles` at `0x25c3cc` and `patchelf_rpath_deps` at `0x26ff58`):

```
+-----------------------------------------------------------------------------+
|               PMS Native Shared Library Rewriting Pipeline                  |
+-----------------------------------------------------------------------------+
| 1. Scan target directory: <installPath>/libs/                               |
| 2. Generate random 10-digit salt: salt = rand() (e.g. 1650062498)           |
| 3. Rename libraries:                                                        |
|    libjsapi_sample.so    -> libjsapi_sample_1650062498.so                   |
|    libbusiness_sample.so -> libbusiness_sample_1650062498.so                |
| 4. Invoke patchelf_rpath_deps:                                              |
|    * Rewrite DT_SONAME: libjsapi_sample_1650062498.so                      |
|    * Rewrite DT_NEEDED: libbusiness_sample_1650062498.so                    |
|    * Inject DT_RUNPATH: /userdata/miniapp/data/mini_app/pkg/<appid>/<a>/libs|
+-----------------------------------------------------------------------------+
```

#### Inspection of Rewritten ELF Dynamic Header
Running an ELF tag inspection on an officially installed native plugin (`8080222437664451/a/libs/libjsapi_dictpen_home_1650062498.so`) confirms the rewritten tags:

```
DT_NEEDED       : libbusiness_dictpen_home_1650062498.so
DT_NEEDED       : libyddal_business.so
DT_NEEDED       : libquickjs.so
DT_NEEDED       : libfalcon.so
DT_SONAME       : libjsapi_dictpen_home_1650062498.so
DT_RUNPATH      : /userdata/miniapp/data/mini_app/pkg/8080222437664451/a/libs/
```

### 5.4 Registry Persistence: `packages.json`
Once extraction, integrity validation, slot rotation, and library patching complete successfully, Falcon updates the system application database at:
```
/userdata/miniapp/data/mini_app/pkg/packages.json
```

#### Schema of `packages.json`
```json
{
  "packages": [
    {
      "appid": "8080222437664451",
      "name": "Launcher",
      "version": "2.4.0",
      "category": "system",
      "packageDir": "8080222437664451",
      "installPath": "/userdata/miniapp/data/mini_app/pkg/8080222437664451",
      "section": "a",
      "props": {
        "supportUnInstall": false,
        "supportCleanUp": false,
        "isSystem": true,
        "addDesktop": {
          "y08_platform": true,
          "coco_platform": true
        }
      }
    },
    {
      "appid": "8080999900000001",
      "name": "CustomUtility",
      "version": "1.0.0",
      "category": "user",
      "packageDir": "8080999900000001",
      "installPath": "/userdata/miniapp/data/mini_app/pkg/8080999900000001",
      "section": "b",
      "props": {
        "supportUnInstall": true,
        "supportCleanUp": true,
        "addDesktop": {
          "y08_platform": true,
          "coco_platform": true
        }
      }
    }
  ]
}
```

The database is written via `IotPackageManager::sync()` (`0x25eec8`) followed by `IotPackageManager::persist()` (`0x25e1b0`). Persistence uses atomic file swapping: writing to `packages.json.tmp` followed by `rename()` to prevent database corruption.

---

## 6. Daemon IPC & Launcher Desktop Integration Subsystem

### 6.1 `miniapp_cli` Subsystem Architecture
`miniapp_cli` is a standalone C ELF executable (`/usr/bin/miniapp_cli`) that interfaces with the running `miniapp` daemon.

```
+-----------------------------------------------------------------------------+
|                          miniapp_cli Communication                          |
+-----------------------------------------------------------------------------+
|  miniapp_cli install /tmp/app.amr                                           |
|         |                                                                   |
|  1. socket(AF_LOCAL, SOCK_STREAM, 0)                                        |
|  2. connect(fd, sun_path="/var/run/miniapp-dbg.socket")                     |
|  3. HTTP POST /install HTTP/1.1\r\n                                         |
|     Host: 127.0.0.1\r\n                                                     |
|     Content-Type: application/json\r\n                                      |
|     Content-Length: 26\r\n\r\n                                              |
|     {"path":"/tmp/app.amr"}                                                 |
|         |                                                                   |
|         v                                                                   |
|  miniapp Daemon (PkgUploadViews::install Handler)                           |
|         |                                                                   |
|  4. JQuick::IotPackageManager::installPackageSync("/tmp/app.amr", ...)      |
+-----------------------------------------------------------------------------+
```

#### Complete `miniapp_cli` Command Specification Table

| Command Syntax | HTTP Verb & Path | Request JSON Payload | Functional Description |
|:---|:---|:---|:---|
| `install {amrPath}` | `POST /install` | `{"path":"{amrPath}"}` | Install or upgrade an application from a local `.amr` package file. |
| `uninstall {appid}` | `POST /uninstall` | `{"appid":"{appid}"}` | Remove an application and delete its active slots. |
| `start {appId} --{page}` | `POST /start` | `{"appID":"{appId}","page":"{page}"}` | Launch an application directly, optionally navigating to `{page}`. |
| `startService {appId} {service}` | `POST /startService` | `{"appID":"{appId}","service":"{service}"}` | Launch a headless background service component declared by the app. |
| `debugApp {appid}` | `POST /debugApp` | `{"appID":"{appid}"}` | Attach devtool debugger and target app for profiling. |
| `debugService {appid}` | `POST /debugService` | `{"appID":"{appid}"}` | Target a specific background service for debugging. |
| `memoryApp` | `GET /memoryApp` | _None_ | Print native userspace RAM utilization of the `miniapp` process. |
| `trimImageCache` | `POST /trimImageCache` | `{"appID":""}` | Flush cached Skia bitmap textures and decoded image buffers. |
| `memoryUsage` | `GET /memoryUsage` | _None_ | Query QuickJS runtime memory heap statistics. |
| `memoryUsageGC` | `GET /memoryUsageGC` | _None_ | Trigger QuickJS garbage collection and report post-GC heap size. |
| `dumpMemory` | `POST /dumpMemory` | _None_ | Dump QuickJS heap snapshot to `/tmp/httpdump.snapshot`. |
| `capture {path}` | `POST /capture` | `{"path":"{path}"}` | Capture current screen composition to a PNG image file. |
| `captureFB {path}` | `POST /captureFB` | `{"path":"{path}"}` | Direct capture of raw Linux framebuffer `/dev/fb0`. |
| `beginMonkey` | `POST /beginMonkey` | _None_ | Start automated pseudo-random stress UI testing. |
| `stopMonkey` | `POST /stopMonkey` | _None_ | Terminate active monkey test. |
| `injectKey {keyCode}` | `POST /injectKey` | `{"keyCode":{keyCode}}` | Inject a virtual hardware key event (e.g. Back, Home, Power). |
| `setRenderConfig {k} {v}`| `POST /setRenderConfig` | `{"key":"{k}","val":"{v}"}`| Modify Falcon graphics rendering engine configuration. |

### 6.2 Event Bus Dispatch: `JQPublishObject::publishJSON`
When installation concludes in `IotPackageManager::executeInstallPackage`, the PMS worker thread triggers `notifyPackageInstalled` (`0x259e44`), which invokes `pm::JSPackageManager::packageInstalled` (`0x268634`):

```armasm
; Disassembly: Event Bus Notification in JSPackageManager (0x268634 - 0x268950)
0x26866c:  bl   pm::serialize2JSON(PackageInfo const&)    ; Serialize metadata
0x268924:  ldr  r0, =aPackage                             ; Literal: "package"
0x268938:  bl   JQPublishObject::publishJSON("package", json_payload, JQPublishType)
```

The broadcast payload contains the event type and full package descriptor:
```json
{
  "type": "installed",
  "info": {
    "appid": "8080999900000001",
    "name": "CustomUtility",
    "version": "1.0.0",
    "icon": "icon.png",
    "installPath": "/userdata/miniapp/data/mini_app/pkg/8080999900000001",
    "section": "a",
    "props": {
      "supportUnInstall": true,
      "addDesktop": {
        "y08_platform": true,
        "coco_platform": true
      }
    }
  }
}
```

### 6.3 Launcher Integration & Desktop Rendering Pipeline
The official desktop launcher application (`8080222437664451`) listens to the `"package"` broadcast channel to dynamically update the home screen:

```
+-----------------------------------------------------------------------------+
|                      Launcher Desktop Card Pipeline                         |
+-----------------------------------------------------------------------------+
| 1. PMS Event Broadcast                                                      |
|    JQPublishObject::publishJSON("package", {"type":"installed", ...})       |
|                                                                             |
| 2. Launcher JS Event Handler                                                |
|    pm.on('package', (event) => refreshApps(event))                          |
|                                                                             |
| 3. Eligibility Gate (checkAddDesktopIcon)                                   |
|    if (packageInfo.props.Invisible === true) return;                        |
|    if (!packageInfo.props.addDesktop[currentPlatform]) return;              |
|                                                                             |
| 4. Icon & Title Resolution                                                  |
|    icon  = getDesktopAppIcon(packageInfo, currentTheme)                     |
|    title = getDesktopAppTitle(packageInfo, currentTheme)                    |
|                                                                             |
| 5. DOM Component Instantiation                                              |
|    createCardComponent(appid, title, icon)                                  |
|    -> Push into MovingStatusCardsList / this.items grid                     |
+-----------------------------------------------------------------------------+
```

1. **Event Reception**: The launcher's `appStoreManager` and `indexPage` register an observer on `pm`.
2. **Filtering (`checkAddDesktopIcon`)**:
   - Evaluates `packageInfo.props.Invisible`. If `true`, the package is ignored.
   - Evaluates `packageInfo.props.addDesktop`. If `packageInfo.props.addDesktop.y08_platform` is not `true`, it is ignored.
3. **Theming (`getDesktopAppIcon` & `getDesktopAppTitle`)**:
   - Queries `packageInfo.props.Icons[currentTheme]` (e.g. `theme-popcorn`). If found, uses that icon path; otherwise, defaults to `packageInfo.icon`.
   - Queries `packageInfo.props.AppTitle[currentTheme]`. If found, overrides the display name.
4. **Card Instantiation (`createCardComponent`)**:
   - Instantiates a desktop app card component and injects it into `MovingStatusCardsList`.
   - Binds the click gesture to trigger:
     ```js
     pm.startApp(appid);
     ```

---

## 7. The Authoritative Developer Manual & Production Packaging Toolkit

### 7.1 Golden Packaging Checklist
Before generating an `.amr` package, developers must ensure the following criteria are met:

- [ ] **Numeric AppID**: The `appid` MUST be a 16-character string containing only digits (`0`-`9`).
- [ ] **Semantic Version**: `version` MUST be formatted as `X.Y.Z` (e.g., `"1.0.0"`).
- [ ] **Root-Level `manifest.json`**: The manifest MUST reside in the root directory of the archive (not nested inside a subfolder).
- [ ] **Platform Target**: `props.addDesktop.y08_platform` MUST be set to `true` to display on the S7 Pro launcher.
- [ ] **Icon Resource**: The image referenced by `"icon"` (e.g. `icon.png`) MUST exist in the archive. Recommended resolution: **100x100 PNG**.
- [ ] **Empty Cert Allowed**: Set `"cert": {}` in `manifest.json` to bypass MD5 and size checks.
- [ ] **Archive Format**: MUST be standard PKZIP created with deflate or store compression. DO NOT apply tar or 7z compression.

---

### 7.2 Minimalist Manifest Template

```json
{
  "appid": "8080999900000001",
  "appName": "HelloFalcon",
  "version": "1.0.0",
  "versionCode": 1,
  "icon": "assets/icon.png",
  "main": "app.js.bin",
  "window": {
    "navigationBarTitleText": "Hello Falcon",
    "navigationBarBackgroundColor": "#000000",
    "fullscreen": true,
    "orientation": "portrait"
  },
  "props": {
    "supportUnInstall": true,
    "supportCleanUp": true,
    "addDesktop": {
      "y08_platform": true,
      "coco_platform": true
    },
    "Invisible": false
  },
  "cert": {}
}
```

---

### 7.3 Automated Packaging Script (`build_falcon_package.py`)
This standalone Python 3 utility automatically generates compliant Falcon `.amr` packages, with support for both bypassed (`--bypass-cert`) and verified (`--strict-cert`) modes:

```python
#!/usr/bin/env python3
"""
Falcon Application Packaging Tool for NetEase Youdao Dictionary Pen S7 Pro
Generates compliant .amr (PKZIP) packages with valid manifest schemas.
"""

import os
import sys
import json
import zipfile
import hashlib
import argparse

def compute_file_md5(file_path):
    hasher = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def build_package(src_dir, output_path, bypass_cert=True):
    src_dir = os.path.abspath(src_dir)
    manifest_path = os.path.join(src_dir, "manifest.json")

    if not os.path.exists(manifest_path):
        print(f"[-] Error: manifest.json not found in {src_dir}")
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Validate essential fields
    appid = manifest.get("appid")
    version = manifest.get("version")
    if not appid or not version:
        print("[-] Error: manifest.json must declare 'appid' and 'version'")
        sys.exit(1)

    print(f"[*] Packaging AppID: {appid} (Version: {version})")

    # Generate or bypass cert
    if bypass_cert:
        print("[+] Utilizing empty cert bypass (cert = {})")
        manifest["cert"] = {}
    else:
        print("[+] Calculating MD5 hash map for cert...")
        cert_map = {}
        for root, _, files in os.walk(src_dir):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), src_dir)
                if rel_path == "manifest.json":
                    continue
                full_path = os.path.join(root, file)
                cert_map[rel_path] = {
                    "size": os.path.getsize(full_path),
                    "md5": compute_file_md5(full_path)
                }
        manifest["cert"] = cert_map

    # Write updated manifest temporarily
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Build PKZIP archive
    out_file = output_path or f"{appid}_{version}.amr"
    with zipfile.ZipFile(out_file, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(src_dir):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, src_dir)
                zipf.write(full_path, rel_path)

    print(f"[+] Package successfully built: {out_file} ({os.path.getsize(out_file)} bytes)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Falcon .amr Packager")
    parser.add_argument("src", help="Path to source application directory")
    parser.add_argument("-o", "--output", help="Output .amr filename")
    parser.add_argument("--strict-cert", action="store_true", help="Generate full MD5 cert map")
    args = parser.parse_args()

    build_package(args.src, args.output, bypass_cert=(not args.strict_cert))
```

---

### 7.4 Installation & Deployment Methods

#### Method 1: Sideloading via `miniapp_cli` (Recommended)
This method utilizes the live PMS daemon over the UNIX domain socket:

1. Push the compiled `.amr` package to device temporary storage via ADB:
   ```bash
   adb push CustomApp.amr /tmp/CustomApp.amr
   ```
2. Execute the install command via `miniapp_cli`:
   ```bash
   adb shell miniapp_cli install /tmp/CustomApp.amr
   ```
3. Check command status:
   ```
   install:
   installed successfully: 8080999900000001
   ```
4. Start the application:
   ```bash
   adb shell miniapp_cli start 8080999900000001 --index
   ```

#### Method 2: Offline Manual Deployment (Direct Flash Injection)
If the PMS daemon or socket is unavailable, applications can be deployed manually by writing directly to the filesystem:

1. Create application directories under `/userdata/miniapp/data/mini_app/pkg/<appid>/`:
   ```bash
   mkdir -p /userdata/miniapp/data/mini_app/pkg/8080999900000001/a
   mkdir -p /userdata/miniapp/data/mini_app/pkg/8080999900000001/data
   ```
2. Unpack the application files directly into slot `a`:
   ```bash
   unzip -q /tmp/CustomApp.amr -d /userdata/miniapp/data/mini_app/pkg/8080999900000001/a/
   ```
3. If the application contains native `.so` files in `libs/`, patch their `DT_RUNPATH`:
   ```bash
   patchelf --set-rpath /userdata/miniapp/data/mini_app/pkg/8080999900000001/a/libs \
            /userdata/miniapp/data/mini_app/pkg/8080999900000001/a/libs/*.so
   ```
4. Append the application entry to `/userdata/miniapp/data/mini_app/pkg/packages.json`:
   ```json
   {
     "appid": "8080999900000001",
     "name": "CustomApp",
     "version": "1.0.0",
     "category": "user",
     "packageDir": "8080999900000001",
     "installPath": "/userdata/miniapp/data/mini_app/pkg/8080999900000001",
     "section": "a",
     "props": {
       "supportUnInstall": true,
       "supportCleanUp": true,
       "addDesktop": {
         "y08_platform": true,
         "coco_platform": true
       }
     }
   }
   ```
5. Restart the `miniapp` daemon to reload the registry:
   ```bash
   killall -9 miniapp
   ```

---

### 7.5 PMS Error Codes & Diagnostics Reference

| Internal Error Code | Log String Constant | Root Cause Analysis | Remediation Action |
|:---|:---|:---|:---|
| `-1` (`0xFFFFFFFF`) | `INS_ERROR_NO_INSTALL_PACKAGE` | Target `.amr` file does not exist or cannot be read. | Check file path and filesystem permissions. |
| `-2` (`0xFFFFFFFE`) | `INS_ERROR_EXTRACT_FAILED` | `miniUnzip` failed to parse ZIP headers. | Verify archive is a valid PKZIP (`PK\x03\x04`). |
| `-3` (`0xFFFFFFFD`) | `INS_ERROR_MANIFEST_INVALID` | `manifest.json` missing or invalid JSON format. | Validate JSON syntax with `jq` or `json.tool`. |
| `-4` (`0xFFFFFFFC`) | `INS_ERROR_MISSING_APPID_OR_VER`| Manifest lacks `appid` or `version` string keys. | Populate required top-level manifest keys. |
| `-5` (`0xFFFFFFFB`) | `INS_ERROR_VERIFY_CONTENT_FAILED`| Hash/size mismatch in non-empty `cert` block. | Update MD5 hashes or use empty cert bypass `{}`. |
| `-6` (`0xFFFFFFFA`) | `INS_ERROR_DOWNGRADE_FORBIDDEN` | New version <= currently installed version. | Increment `version` in `manifest.json`. |
| `-7` (`0xFFFFFFF9`) | `INS_ERROR_INSTALL_ALREADY_ON_GOING`| Another install task is active on `pm` thread. | Wait for active operation to complete. |
| `-8` (`0xFFFFFFF8`) | `INS_ERROR_INSUFFICIENT_STORAGE`| Available space on `/userdata` is insufficient. | Run `miniapp_cli trimImageCache` or remove files. |
| `-9` (`0xFFFFFFF7`) | `INS_ERROR_RENAME_SLOT_FAILED` | `rename()` failed during atomic slot swap. | Check write permissions on target directory. |
