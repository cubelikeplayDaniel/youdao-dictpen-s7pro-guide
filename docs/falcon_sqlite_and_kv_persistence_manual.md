# 有道词典笔 S7 Pro SQLite3 数据库、KV 存储与持久化子系统深度逆向分析
## (Falcon SQLite3 Database, KV Storage, and Persistence Subsystem Deep-Dive Engineering Manual)

> **适用固件**: NetEase Youdao Dictionary Pen S7 Pro (`YDPS7-2`, 固件 4.22.0+)  
> **芯片平台**: Cvitek CV1813H SoC (Single ARM Cortex-A7 @ 1.0 GHz, 128 MB RAM, Linux 5.10.4)  
> **核心组件**: `libfalcon.so` (静态嵌入 SQLite 3.32.3), `libquickjs.so`, `jq::JSDatabase`, `jq::JSStorage`, `JQuick::SharedPreferences`

---

## 目录索引

1. [持久化存储引擎全景拓扑与运行时架构](#1-持久化存储引擎全景拓扑与运行时架构)
   - 1.1 [多层持久化存储架构模型](#11-多层持久化存储架构模型)
   - 1.2 [物理分区表与存储拓扑路径标准](#12-物理分区表与存储拓扑路径标准)
   - 1.3 [固件实测数据库与配置尸检剖析](#13-固件实测数据库与配置尸检剖析)
2. [底层二进制符号反汇编与执行流逆向](#2-底层二进制符号反汇编与执行流逆向)
   - 2.1 [`jq::JSDatabase` 异步工作线程模型 (`JSDatabase<p>%ld`)](#21-jqjsdatabase-异步工作线程模型-jsdatabasepld)
   - 2.2 [`jq::JSStatement` 语句编译与结果集提取机制](#22-jqjsstatement-语句编译与结果集提取机制)
   - 2.3 [原生行解包关键约束：纯索引数组输出陷阱](#23-原生行解包关键约束纯索引数组输出陷阱)
   - 2.4 [`jq::JSStorage` 与 `JQuick::SharedPreferences` 原生映射](#24-jqjsstorage-与-jquicksharedpreferences-原生映射)
3. [嵌入式并发控制、锁竞争与回滚日志分析](#3-嵌入式并发控制锁竞争与回滚日志分析)
   - 3.1 [回滚日志 (Rollback Journal: DELETE) vs WAL 模式深度抉择](#31-回滚日志-rollback-journal-delete-vs-wal-模式深度抉择)
   - 3.2 [跨进程 POSIX fcntl 建议锁与并发互斥](#32-跨进程-posix-fcntl-建议锁与并发互斥)
   - 3.3 [致命的 `SQLITE_BUSY` (Code 5) 陷阱与零毫秒超时根因](#33-致命的-sqlite_busy-code-5-陷阱与零毫秒超时根因)
4. [Falcon JavaScript API 全量接口字典](#4-falcon-javascript-api-全量接口字典)
   - 4.1 [`sqlite3` 模块 (`sqlite3.Database` & `sqlite3.Statement`)](#41-sqlite3-模块-sqlite3database--sqlite3statement)
   - 4.2 [`storage` 模块 (`setStorage`, `getStorage`, `removeStorage`)](#42-storage-模块-setstorage-getstorage-removestorage)
   - 4.3 [AliOS 兼容层 `my.getStorage` / `setGlobalStorage`](#43-alios-兼容层-mygetstorage--setglobalstorage)
5. [生产级开发规范与全功能实现代码](#5-生产级开发规范与全功能实现代码)
   - 5.1 [企业级高可靠 SQLite 封装库 (`FalconDatabase.js`)](#51-企业级高可靠-sqlite-封装库-falcondatabasejs)
   - 5.2 [生词本/字典库高并发事务实战案例](#52-生词本字典库高并发事务实战案例)
   - 5.3 [生产级 KV 存储管理器 (`FalconKV.js`)](#53-生产级-kv-存储管理器-falconvkjs)
6. [128MB 严苛内存预算与 eMMC 闪存防磨损指南](#6-128mb-严苛内存预算与-emmc-闪存防磨损指南)
   - 6.1 [QuickJS 延迟 GC 引发的 C++ 语句句柄泄漏死锁](#61-quickjs-延迟-gc-引发的-c-语句句柄泄漏死锁)
   - 6.2 [原生线程池饥饿与单例范式要求](#62-原生线程池饥饿与单例范式要求)
   - 6.3 [嵌入式 SQLite 核心 PRAGMA 调优矩阵](#63-嵌入式-sqlite-核心-pragma-调优矩阵)
   - 6.4 [eMMC 写入放大抑制与批量事务最佳实践](#64-emmc-写入放大抑制与批量事务最佳实践)

---

## 1. 持久化存储引擎全景拓扑与运行时架构

### 1.1 多层持久化存储架构模型

NetEase Youdao Dictionary Pen S7 Pro（硬件平台代码 `theme-y08`）搭载了一颗单核 ARM Cortex-A7 处理器与 128MB DDR3 共享内存。在这一受限的嵌入式环境下，平台并未运行任何独立的数据库守护进程（如 `mysqld`），而是基于嵌入式原生 C++ 实现了多层次的无服务（In-Process）持久化体系：

```
+----------------------------------------------------------------------------------+
|                              Falcon MiniApp 应用层                               |
|    import sqlite3 from 'sqlite3'              import storage from 'storage'       |
|    const db = new sqlite3.Database()          await storage.setStorage({...})    |
+----------------------------------------------------------------------------------+
                                        │ (QuickJS 原生 C++ 桥接层: jqutil_v2)
+---------------------------------------▼------------------------------------------+
|                     libfalcon.so 原生持久化绑定框架                              |
|                                                                                  |
|   +------------------------------------+   +---------------------------------+   |
|   |          jq::JSDatabase            |   |         jq::JSStorage           |   |
|   |         jq::JSStatement            |   |   sharedpreferences::register   |   |
|   +------------------------------------+   +---------------------------------+   |
|                     │                                       │                    |
|          线程调度 (专有 I/O 线程)                           │                    |
|       ("JSDatabase<p>%ld", priority 0)                      │                    |
|                     ▼                                       ▼                    |
|   +------------------------------------+   +---------------------------------+   |
|   |    静态编译 SQLite 3.32.3 引擎     |   |    JQuick::SharedPreferences    |   |
|   |   sqlite3_open, prepare_v2, step   |   |     spMap 内存缓存 & JSON 文件  |   |
|   +------------------------------------+   +---------------------------------+   |
+----------------------------------------------------------------------------------+
                                        │ (POSIX 文件系统调用: open, read, write, fcntl)
+---------------------------------------▼------------------------------------------+
|                       CV1813H Linux Kernel 5.10.4 VFS 层                         |
|                    POSIX 建议锁 (F_SETLK), ext4 / userdisk                       |
+----------------------------------------------------------------------------------+
                                        │
+---------------------------------------▼------------------------------------------+
|                            物理硬件存储 (eMMC 闪存)                              |
|   /userdata/miniapp/data/mini_app/pkg/<appid>/data/database/<name>.db            |
|   /userdata/miniapp/data/mini_app/pkg/<appid>/data/sharedpreferences/preferences.json|
+----------------------------------------------------------------------------------+
```

---

### 1.2 物理分区表与存储拓扑路径标准

系统将内置 eMMC 划分为多个逻辑挂载区：
- `/usr/`: 只读系统镜像，存放系统核心动态库（`libfalcon.so`, `libquickjs.so`）。
- `/userdata/`: 可读写应用配置主分区，存放已安装 MiniApp、用户配置及活跃数据库。
- `/userdisk/`: 大容量持久化数据分区，存放离线本地词典（数万词条音标/释义）、离线 TTS 音频库（`.dat` 文件，单文件达 489MB）以及电子扫描绘本。

当 MiniApp（以应用 ID `appid` 标识）访问相对路径时，Falcon 的沙箱隔离机制 `jq::Sandbox::changePath()` 会自动将其重定向至私有目录：

```
/userdata/miniapp/data/mini_app/pkg/<appid>/
├── data/
│   ├── database/
│   │   ├── dicts.db                    <-- 核心业务 SQLite 数据库
│   │   └── dicts.db-journal            <-- 事务回滚日志 (写入时短暂产生)
│   ├── sharedpreferences/
│   │   └── preferences.json            <-- AliOS 兼容层 (my.getStorage)
│   ├── storage/
│   │   └── preferences.json            <-- 原生模块 (import storage)
│   └── temp/                           <-- 临时文件目录
└── app/                                <-- 解包后的前端工程资源
```

---

### 1.3 固件实测数据库与配置尸检剖析

从设备真实抽取的字典数据库 `/userdata/miniapp/data/mini_app/pkg/8080272425914438/data/database/dicts.db` 进行底层头部分析，揭示了官方固件的底层配置参数：

```
文件尺寸: 16,384 字节 (16 KB)
SQLite 格式: SQLite 3.x
页尺寸 (Page Size): 4,096 字节
文件变更计数器 (File Change Counter): 3
用户版本号 (User Version): 0
文本编码 (Default Encoding): 1 (UTF-8)
Schema 格式版本: 4
```

#### 官方词库表 DDL 结构:
```sql
CREATE TABLE table_dicts (
    size INT,
    wordNumber INT,
    updateTimestamp BIGINT,
    key TEXT,
    type TEXT,
    version TEXT,
    grade TEXT,
    path TEXT,
    md5 TEXT,
    url TEXT,
    coverUrl TEXT,
    fileName TEXT,
    title TEXT,
    subject TEXT,
    description TEXT,
    PRIMARY KEY (key)
);
```

#### 官方 Launcher 配置 (`preferences.json`) 格式:
```json
{
  "dictpenHomeSortedItems": "[\"8001680085293935\", \"8001888800000001\", \"8080232418330628\", \"8001712908385557\", \"8001725935438060\", \"8001654057944134\", \"8080212246010681\", \"8001747311818360\"]"
}
```
**关键发现**: `preferences.json` 采用扁平单层结构，若存储复杂数组或嵌套对象，必须进行 `JSON.stringify()` 二次字符串转义存储。

---

## 2. 底层二进制符号反汇编与执行流逆向

所有函数地址与指令均直接反汇编自目标设备 `/usr/lib/libfalcon.so` (ELF 32-bit ARM, EABI5)。

### 2.1 `jq::JSDatabase` 异步工作线程模型 (`JSDatabase<p>%ld`)

SQLite 模块初始化入口为 `jq::sqlite3_init(jqutil_v2::JQModuleEnv*)`，虚拟地址 `0x006bd498`（长度 7,648 字节）。

| 虚拟地址 | 尺寸 | 函数符号 (C++ Demangled) | 详细功能说明 |
| :--- | :--- | :--- | :--- |
| `0x006bb930` | 860 B | `jq::JSDatabase::open` | 解析沙箱路径，创建所需目录，底层调用 `sqlite3_open()`。 |
| `0x006bb374` | 444 B | `jq::JSDatabase::close` | 终结所有子 Statement，调用 `sqlite3_close()`，返回 `"OK"`。 |
| `0x006bc370` | 604 B | `jq::JSDatabase::exec` | 将 DDL/SQL 字符串投递至后台线程执行 `sqlite3_exec()`。 |
| `0x006bc6b4` | 1,512 B | `jq::JSDatabase::prepare` | 调用 `sqlite3_prepare_v2()` 编译生成 `JSStatement` 对象。 |
| `0x006c1404` | 76 B | `jq::JSDatabase::pathGetter` | 属性读取器，返回已打开数据库的规范化绝对物理路径。 |
| `0x006c1d04` | 852 B | `jq::JSDatabase::OnGCCollect`| QuickJS 垃圾回收析构钩子，在后台线程安全关闭未显式关闭的句柄。 |

#### 工作线程派发反汇编分析:
在 `jq::JSDatabase::open` 内部，Falcon 针对每一个独立的数据库连接创建一条专属后台工作线程：
```arm
0x006bbbb8: ldr r1, [pc, #0x234]    ; 加载格式化字符串 "JSDatabase<p>%ld"
0x006bbbc0: bl  snprintf
0x006bbbd4: bl  jqutil_v2::JQThreadRegistry::postNamedThread(...)
```
所有后续的 `exec`、`prepare`、`step`、`run` 等操作均以 C++ Lambda 闭包的形式封装，投递至该专属后台线程执行，彻底避免磁盘 I/O 阻塞 QuickJS 主 UI 渲染循环。当操作完成时，结果通过 `postJSThread()` 封送回 JS 主事件循环并触发 Promise 决议。

---

### 2.2 `jq::JSStatement` 语句编译与结果集提取机制

`jq::JSStatement` 封装了原生 `sqlite3_stmt*` 预编译游标。

| 虚拟地址 | 尺寸 | 函数符号 (C++ Demangled) | 详细功能说明 |
| :--- | :--- | :--- | :--- |
| `0x006bd178` | 800 B | `jq::JSStatement::bind` | 绑定参数。同时支持按位置绑定（数组）与按名称绑定（键值对象）。 |
| `0x006c017c` | 444 B | `jq::JSStatement::step` | 推进游标。若命中行数据（`100: SQLITE_ROW`）则返回解包后的数组；遍历结束（`101: SQLITE_DONE`）返回 `null`。 |
| `0x006c0338` | 828 B | `jq::JSStatement::all` | 循环执行 `step` 直至 `SQLITE_DONE`，返回二维结果数组 `Array<Array<any>>`。 |
| `0x006bafe4` | 312 B | `jq::JSStatement::run` | 仅执行语句至完成，不解包数据列（专为 `INSERT`/`UPDATE` 优化）。 |
| `0x006bf6c0` | 1,096 B| `jq::JSStatement::columnNameList` | 调用 `sqlite3_column_name()` 返回所有查询字段名称字符串数组。 |
| `0x006bcdc4` | 632 B | `jq::JSStatement::finalize` | 从数据库连接池中解绑并调用 `sqlite3_finalize()` 释放原生内存。 |

---

### 2.3 原生行解包关键约束：纯索引数组输出陷阱

在反汇编 `jq::JSStatement::_getRowBSON`（`0x006c0fb4`，1,104 字节）时发现：
- 底层按列遍历 `sqlite3_column_type(stmt, i)`（`INTEGER`, `FLOAT`, `TEXT`, `BLOB`, `NULL`）；
- 解包后的字段**并未附带列名**，而是直接按索引插入 QuickJS 数组（`Array[0] = val0, Array[1] = val1, ...`）！

> ⚠️ **开发致命陷阱**:  
> 调用 `await stmt.step()` 或 `await stmt.all()` 返回的结果是**纯数组**（`["algorithm", "n. 算法"]`），**绝非键值对象**（`{ word: "algorithm", trans: "..." }`）！  
> 若直接按照对象访问 `row.word`，将会取得 `undefined`！  
> **生产标准解法**: 必须调用 `await stmt.columnNameList()` 获取列名数组，在 JS 层组装为对象映射。

---

### 2.4 `jq::JSStorage` 与 `JQuick::SharedPreferences` 原生映射

- **模块注册**: `jq::storage_init`（`0x006c34f4`）导出原生 `storage` 模块。
- **数据落地**: 经由 `JQuick::SharedPreferences`（`0x0056d3f8`）在内存中维护全局哈希表 `spMap`（`0x007eeabc`）。读取时命中缓存极快，写入时触发全文件 JSON 序列化落地，并使用 POSIX 文件排他锁防冲撞。

---

## 3. 嵌入式并发控制、锁竞争与回滚日志分析

### 3.1 回滚日志 (Rollback Journal: DELETE) vs WAL 模式深度抉择

逆向分析表明，有道固件出厂数据库全量运行于经典**回滚日志模式 (`PRAGMA journal_mode = DELETE;`)**，而非现代数据库常见的 WAL（Write-Ahead Logging）模式。

#### 为什么官方严禁 WAL 模式？
1. **128MB 物理内存红线限制**:
   WAL 模式必须依赖共享内存索引文件（`dicts.db-shm`），该文件需要通过 Linux `mmap()` 系统调用映射入内核虚拟空间。在只有 128MB RAM 且需运行 OCR 神经网络推理的硬件上，多个 MiniApp 频繁创建 `mmap` 区域会导致严重的外碎片化并诱发内核 OOM Killer。
2. **Flash 闪存防异常掉电**:
   词典笔电池容量小（通常仅 300~500 mAh），极易在低电量或快速插拔时发生非预期断电。WAL 模式需要后台定时 Checkpoint 合并，若断电发生在 Checkpoint 期间，可能导致页映射关系破坏。经典 Rollback Journal 在事务提交后直接将 `-journal` 文件解除链接，断电恢复极为确定。

---

### 3.2 跨进程 POSIX fcntl 建议锁与并发互斥

有道词典笔运行多个独立 Linux 进程：
- 系统桌面 (`dictpen-home`)
- 扫描划词守护进程 (`scand`)
- 语音与录音后台服务 (`RecordService`)
- 当前活跃的前台 MiniApp

所有进程访问 SQLite 均受到 Linux 内核 `fcntl(fd, F_SETLK, &fl)` 建议锁保护。多个进程可同时持有 `SHARED`（共享读）锁，但任何进程发起写入请求时，必须独占获取 `EXCLUSIVE` 锁，此时其它一切读写请求均被内核挂起。

---

### 3.3 致命的 `SQLITE_BUSY` (Code 5) 陷阱与零毫秒超时根因

在对 `jq::JSDatabase::open`（`0x006bb930`）的深度反汇编中发现：
Falcon 底层在调用 `sqlite3_open()` 之后，**完全没有调用 `sqlite3_busy_timeout()`**！
这意味着 SQLite 引擎的**默认锁等待超时时间是 0 毫秒**！

```
当扫描后台进程正在向词库写入新词 (持有 EXCLUSIVE 锁):
前台 MiniApp 执行 db.prepare("SELECT ...") -> 立即报错:
Error: sqlite3_step failure: database is locked (error code 5: SQLITE_BUSY)
```

> 🔥 **生产铁律：所有数据库连接初始化后必须首选注入 busy_timeout**  
> 打开数据库后，必须第一时间执行：  
> `await db.exec("PRAGMA busy_timeout = 3000;");`  
> 赋予引擎最多 3000ms 的自旋等待重试窗口，彻底化解并发锁冲突崩溃！

---

## 4. Falcon JavaScript API 全量接口字典

### 4.1 `sqlite3` 模块 (`import sqlite3 from 'sqlite3'`)

#### `sqlite3.Database` 原型方法:
- `open(filePath: string): Promise<void>`: 打开沙箱内数据库（支持相对路径如 `"words.db"` 或 `":memory:"`）。
- `close(): Promise<string>`: 关闭数据库并批量销毁内部全部未释放的 Statement。返回 `"OK"`。
- `exec(sql: string): Promise<void>`: 直接执行 SQL 语句字符串（支持分号拼接的建表、索引或事务指令）。
- `prepare(sql: string): Promise<sqlite3.Statement>`: 预编译 SQL 并生成 Statement 实例。
- `path: string` (只读属性): 获取数据库物理完整路径。

#### `sqlite3.Statement` 原型方法:
- `bind(params: Array<any> | Record<string, any>): Promise<void>`:
  - 数组参数（问号占位符 `?`）：`[1, "hello"]`（内部按 1-based 绑定）。
  - 对象参数（命名占位符 `:key` 或 `@key`）：`{ ":word": "test" }`。
- `step(): Promise<Array<any> | null>`: 推进游标至下一行。有数据返回列值数组，到达末尾返回 `null`。
- `all(): Promise<Array<Array<any>>>`: 批量提取所有剩余行，返回二维数组。
- `run(): Promise<void>`: 高效执行完成，不提取任何结果数据（专用于 `INSERT`/`UPDATE`/`DELETE`）。
- `columnNameList(): Promise<Array<string>>`: 获取所有列名称列表。
- `bindParameterList(): Promise<Array<string>>`: 获取当前语句所需占位符参数名。
- `finalize(): Promise<void>`: 释放底层 C++ `sqlite3_stmt*` 句柄（**必调**）。

---

### 4.2 `storage` 模块 (`import storage from 'storage'`)

- `storage.setStorage({ key: string, data: any }): Promise<void>`: 存储键值。
- `storage.getStorage({ key: string }): Promise<{ data: any }>`: 读取键值。若不存在，返回 `null`。
- `storage.removeStorage({ key: string }): Promise<void>`: 删除单个键。
- `storage.clearStorage(): Promise<void>`: 清空当前应用全部键值数据。
- `storage.getStorageKeys(): Promise<{ keys: string[] }>`: 获取当前应用全部持久化键名。

---

### 4.3 AliOS 兼容层 `my.getStorage` / `setGlobalStorage`

- `my.setStorage({ key, data, success, fail })`
- `my.getStorage({ key, success: (res) => { ... }, fail })`
- `my.setGlobalStorage({ key, data })`: 写入全设备全局共享区（所有 MiniApp 均可互通访问）。
- `my.getGlobalStorage({ key, success: (res) => { ... } })`: 读取全局共享区。

---

## 5. 生产级开发规范与全功能实现代码

### 5.1 企业级高可靠 SQLite 封装库 (`FalconDatabase.js`)

该封装库解决了：
1. 自动注入 `PRAGMA busy_timeout = 3000;` 解决锁冲突崩溃；
2. 调优 128MB 嵌入式内存预算；
3. 将原生行数组自动转换为 JavaScript Object；
4. 保证 `finally` 阶段 100% 释放 Statement 防止 C++ 句柄泄漏；
5. 完备的事务支持与异常自动回滚。

```javascript
/**
 * FalconDatabase.js - 针对有道词典笔 S7 Pro 优化的企业级 SQLite3 客户端
 */
import sqlite3 from 'sqlite3';

export class FalconDatabase {
    constructor(dbName = 'app_data.db') {
        this.dbName = dbName;
        this.db = null;
        this.isOpen = false;
    }

    async open() {
        if (this.isOpen) return;

        this.db = new sqlite3.Database();
        await this.db.open(this.dbName);

        // 1. 解决 SQLITE_BUSY 锁冲突崩溃 (自旋等待最多 3000ms)
        await this.db.exec("PRAGMA busy_timeout = 3000;");

        // 2. 128MB RAM 内存预算硬约束: 限制页缓存为 2MB (-2048 KiB)
        await this.db.exec("PRAGMA cache_size = -2048;");

        // 3. 临时索引与排列表放入内存，彻底减少 eMMC 闪存磨损
        await this.db.exec("PRAGMA temp_store = MEMORY;");

        // 4. 采用 NORMAL 同步模式兼顾性能与异常掉电安全
        await this.db.exec("PRAGMA synchronous = NORMAL;");

        this.isOpen = true;
    }

    async execute(sql) {
        if (!this.isOpen) await this.open();
        return await this.db.exec(sql);
    }

    async run(sql, params = []) {
        if (!this.isOpen) await this.open();
        const stmt = await this.db.prepare(sql);
        try {
            if (params && (Array.isArray(params) ? params.length > 0 : Object.keys(params).length > 0)) {
                await stmt.bind(params);
            }
            await stmt.run();
        } finally {
            // 铁律: 无论执行成功还是报错，必须显式释放底层 Statement 句柄
            await stmt.finalize();
        }
    }

    async queryOne(sql, params = []) {
        if (!this.isOpen) await this.open();
        const stmt = await this.db.prepare(sql);
        try {
            if (params && (Array.isArray(params) ? params.length > 0 : Object.keys(params).length > 0)) {
                await stmt.bind(params);
            }
            const columns = await stmt.columnNameList();
            const rowArray = await stmt.step();
            if (!rowArray) return null;

            // 转换纯索引数组为 JavaScript 键值对象
            const rowObj = {};
            for (let i = 0; i < columns.length; i++) {
                rowObj[columns[i]] = rowArray[i];
            }
            return rowObj;
        } finally {
            await stmt.finalize();
        }
    }

    async queryAll(sql, params = []) {
        if (!this.isOpen) await this.open();
        const stmt = await this.db.prepare(sql);
        try {
            if (params && (Array.isArray(params) ? params.length > 0 : Object.keys(params).length > 0)) {
                await stmt.bind(params);
            }
            const columns = await stmt.columnNameList();
            const allRows = await stmt.all(); // 二维数组 Array<Array<any>>
            if (!allRows || !Array.isArray(allRows)) return [];

            return allRows.map(rowArray => {
                const rowObj = {};
                for (let i = 0; i < columns.length; i++) {
                    rowObj[columns[i]] = rowArray[i];
                }
                return rowObj;
            });
        } finally {
            await stmt.finalize();
        }
    }

    /**
     * 具备排他锁保障的原子事务执行器
     */
    async transaction(action) {
        if (!this.isOpen) await this.open();
        // 使用 IMMEDIATE 防止在事务中间发生死锁
        await this.db.exec("BEGIN IMMEDIATE TRANSACTION;");
        try {
            const result = await action(this);
            await this.db.exec("COMMIT;");
            return result;
        } catch (err) {
            await this.db.exec("ROLLBACK;");
            throw err;
        }
    }

    async close() {
        if (!this.isOpen || !this.db) return;
        await this.db.close();
        this.db = null;
        this.isOpen = false;
    }
}
```

---

### 5.2 生词本/字典库高并发事务实战案例

```javascript
import { FalconDatabase } from './FalconDatabase.js';

export async function initWordbookDatabase() {
    const db = new FalconDatabase('wordbook.db');
    await db.open();

    // 1. 结构化建表与覆盖索引设计
    await db.execute(`
        CREATE TABLE IF NOT EXISTS user_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            phonetic TEXT,
            translation TEXT NOT NULL,
            mastery_level INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            last_review_time INTEGER,
            created_at INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_words_mastery ON user_words(mastery_level, last_review_time);
    `);

    // 2. 批量事务插入 (一次性提交，将 100 次磁盘写入降为 1 次)
    const newWords = [
        { word: 'synchronous', pho: "['sɪŋkrənəs]", trans: 'adj. 同步的；同时存在的' },
        { word: 'asynchronous', pho: "[eɪ'sɪŋkrənəs]", trans: 'adj. 异步的；不同时的' },
        { word: 'persistence', pho: "[pə'zɪstəns]", trans: 'n. 坚持；持久存在' }
    ];

    await db.transaction(async (tx) => {
        for (const item of newWords) {
            await tx.run(
                `INSERT OR REPLACE INTO user_words 
                 (word, phonetic, translation, created_at) 
                 VALUES (?, ?, ?, ?);`,
                [item.word, item.pho, item.trans, Date.now()]
            );
        }
    });

    // 3. 命名参数化精准查询
    const wordInfo = await db.queryOne(
        "SELECT * FROM user_words WHERE word = :target LIMIT 1;",
        { ":target": "persistence" }
    );
    console.log("查询到单词详情:", JSON.stringify(wordInfo));

    return db;
}
```

---

### 5.3 生产级 KV 存储管理器 (`FalconKV.js`)

```javascript
/**
 * FalconKV.js - 快速键值持久化组件
 */
import storage from 'storage';

export class FalconKV {
    static async set(key, value) {
        if (!key || typeof key !== 'string') throw new Error("Invalid storage key");
        const serialized = JSON.stringify(value);
        await storage.setStorage({ key, data: serialized });
    }

    static async get(key, defaultValue = null) {
        try {
            const res = await storage.getStorage({ key });
            if (!res || res.data === undefined || res.data === null || res.data === "__null__") {
                return defaultValue;
            }
            try {
                return JSON.parse(res.data);
            } catch (_) {
                return res.data;
            }
        } catch (_) {
            return defaultValue;
        }
    }

    static async remove(key) {
        await storage.removeStorage({ key });
    }

    static async clear() {
        await storage.clearStorage();
    }

    static async keys() {
        const res = await storage.getStorageKeys();
        return (res && res.keys) ? res.keys : [];
    }
}
```

---

## 6. 128MB 严苛内存预算与 eMMC 闪存防磨损指南

### 6.1 QuickJS 延迟 GC 引发的 C++ 语句句柄泄漏死锁

在 QuickJS 运行时中，JSValue 变量在超出局部作用域后并不会立即析构，而是等待下一次垃圾回收轮次。
- 若开发者在循环中大量调用 `await db.prepare(sql)` 却未调用 `await stmt.finalize()`；
- 原生 C++ 堆中分配的 `sqlite3_stmt*` 仍将保持存活，并锁定底层 B-Tree 数据页；
- 后续同数据库的写入事务会因无法提升排他锁而永久报出 `SQLITE_BUSY`。
- **强制规范**: 编写任何 Statement 查询，必须将其置于 `try { ... } finally { await stmt.finalize(); }` 中！

### 6.2 原生线程池饥饿与单例范式要求

如前所述，每次 `new sqlite3.Database()` 均会拉起一个名为 `JSDatabase<p>%ld` 的底层 POSIX 线程（消耗独立的线程栈空间）。
- 若在页面组件内无节制地创建数据库实例，多条线程频繁抢占单核 Cortex-A7 CPU 时间片，导致系统音频卡顿甚至重启。
- **强制规范**: 应用内部必须采用单例模式，全局仅维持一个数据库连接实例。

### 6.3 嵌入式 SQLite 核心 PRAGMA 调优矩阵

```sql
-- 1. 严格限制缓存大小 (2MB)，防范 Linux OOM 强杀进程
PRAGMA cache_size = -2048;

-- 2. 将排序与临时表强制放入 RAM，避免闪存反复产生临时小文件
PRAGMA temp_store = MEMORY;

-- 3. 关闭 mmap 避免虚拟地址空间碎片
PRAGMA mmap_size = 0;

-- 4. 页对齐设为 4KB (匹配 eMMC Flash 物理扇区)
PRAGMA page_size = 4096;

-- 5. 跨进程并发锁等待设为 3000ms
PRAGMA busy_timeout = 3000;
```

### 6.4 eMMC 写入放大抑制与批量事务最佳实践

词典笔使用 eMMC 介质，随机单次 4KB 写入会导致内部 FTL 严重的写放大与垃圾回收损耗：
1. **坚决杜绝在循环中单条 `INSERT`**:  
   100 次独立的 `INSERT` 会引发 100 次 `fsync()`，在 eMMC 上需要消耗数秒时间并产生界面无响应（ANR）。将它们合并入 `db.transaction()` 中，100 次插入仅产生 1 次磁盘刷盘，速度提升 50 倍以上。
2. **区分存储介质与业务体量**:  
   - 纯配置项（屏幕亮度档位、音量状态、阅读器书签）总大小 $< 32\text{ KB}$，使用 `FalconKV`；
   - 超过 50 条记录的列表型数据（历史记录、收藏夹、划词生词库），必须使用 `FalconDatabase`。
