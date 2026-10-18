#!/usr/bin/env python3
import http.server
import socketserver
import ssl
import threading
import socket
import struct
import json
import re
import os
import sys
import subprocess
import atexit
import signal
import hashlib
import requests
import urllib3
from urllib.parse import parse_qs, unquote

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HTTP_PORT = 8080
HTTPS_PORT = 8443
FILE_PORT = 14514

LOCAL_IP = "192.168.2.1"
AMR_PATH = "/private/tmp/custom_app.amr"
ICON_PATH = "/private/tmp/app_icon.png"
CERT_PATH = "/private/tmp/appstore.crt"
KEY_PATH = "/private/tmp/appstore.key"

APP_ID = "8888000188880001"
APP_NAME = "极客工具箱"
AMR_SIZE = os.path.getsize(AMR_PATH) if os.path.exists(AMR_PATH) else 0

with open(AMR_PATH, "rb") as f:
    AMR_MD5 = hashlib.md5(f.read()).hexdigest()

# --- 0. Packet Filter (PF) Redirection ---
def setup_pf_redirect():
    rule = (
        f"rdr pass on bridge100 proto tcp from any to any port 80 -> {LOCAL_IP} port {HTTP_PORT}\n"
        f"rdr pass on bridge100 proto tcp from any to any port 443 -> {LOCAL_IP} port {HTTPS_PORT}\n"
    )
    try:
        p = subprocess.Popen(
            ["pfctl", "-a", "com.apple/appstore", "-f", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        _, err = p.communicate(input=rule.encode())
        if p.returncode == 0:
            subprocess.run(["pfctl", "-e"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[PF] >>> Packet redirection ACTIVE (80->{HTTP_PORT}, 443->{HTTPS_PORT})")
        else:
            print(f"[PF] Warning setting PF rule: {err.decode(errors='ignore').strip()}")
    except Exception as e:
        print(f"[PF] Error configuring pfctl: {e}")

def teardown_pf_redirect():
    try:
        subprocess.run(
            ["pfctl", "-a", "com.apple/appstore", "-F", "all"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("[PF] Cleaned up redirection rules cleanly.")
    except Exception:
        pass

atexit.register(teardown_pf_redirect)

def sig_handler(sig, frame):
    print("\nStopping App Store Server...")
    teardown_pf_redirect()
    sys.exit(0)

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

# --- 1. Forwarding to Upstream Cloud ---
def forward_to_upstream(method, host, path, headers_in, body_bytes):
    headers = {}
    for k, v in headers_in.items():
        if k.lower() not in ["content-length", "connection", "accept-encoding"]:
            headers[k] = v
    headers["Host"] = host

    if any(h in host for h in ["connectivitycheck", "connect.rom.miui.com", "wifi.vivo.com.cn", "abupdate.com"]):
        url = f"http://{host}{path}"
    else:
        url = f"https://{host}{path}"

    try:
        req_kwargs = {
            "headers": headers,
            "data": body_bytes,
            "timeout": 8,
            "verify": False
        }
        resp = requests.request(method, url, **req_kwargs)
        return resp.status_code, dict(resp.headers), resp.content
    except Exception as e:
        print(f"      [UPSTREAM ERROR] {url}: {e}")
        return None, None, None

def build_custom_app_object():
    dl_url = f"http://{LOCAL_IP}:{FILE_PORT}/custom_app.amr"
    icon_url = f"http://{LOCAL_IP}:{FILE_PORT}/app_icon.png"

    app = {
        "create_time": "2026-10-18 12:00:00",
        "appName": APP_NAME,
        "remark": "极客工具箱：包含网页浏览器、命令行终端及多功能系统工具。",
        "version": "1.0.1",
        "url": dl_url,
        "downloadUrl": dl_url,
        "needRestart": 0,
        "column_id_list": [1, 2, 3, 75, 76, 77],
        "coverUrl": icon_url,
        "appIcon": icon_url,
        "logtagEnumsList": [],
        "update_time": "2026-10-18 12:00:00",
        "online_state": 1,
        "size": AMR_SIZE,
        "install": False,
        "appId": APP_ID,
        "sceneId": "s202",
        "md5": AMR_MD5
    }
    return app

def serve_file_range(handler, filepath, content_type):
    if not os.path.exists(filepath):
        handler.send_error(404, "File not found")
        return

    total_size = os.path.getsize(filepath)
    range_header = handler.headers.get("Range")

    start = 0
    end = total_size - 1

    if range_header:
        m = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if m:
            start = int(m.group(1))
            if m.group(2):
                end = int(m.group(2))
        print(f"[FILE] Range ({os.path.basename(filepath)}): {start}-{end}/{total_size} from {handler.client_address[0]}")
        handler.send_response(206)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
        content_len = end - start + 1
        handler.send_header("Content-Length", str(content_len))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Connection", "close")
        handler.end_headers()

        with open(filepath, "rb") as f:
            f.seek(start)
            remaining = content_len
            chunk_sz = 1024 * 64
            while remaining > 0:
                to_read = min(remaining, chunk_sz)
                data = f.read(to_read)
                if not data:
                    break
                try:
                    handler.wfile.write(data)
                    remaining -= len(data)
                except (BrokenPipeError, ConnectionResetError):
                    break
    else:
        print(f"[FILE] Full file ({os.path.basename(filepath)}): {total_size} bytes from {handler.client_address[0]}")
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(total_size))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Connection", "close")
        handler.end_headers()

        with open(filepath, "rb") as f:
            chunk_sz = 1024 * 64
            while True:
                data = f.read(chunk_sz)
                if not data:
                    break
                try:
                    handler.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    break

# --- 2. Mock & Injection API Handler ---
class AppStoreApiHandler(http.server.BaseHTTPRequestHandler):
    def send_raw(self, status, content, content_type="application/json;charset=UTF-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len) if content_len > 0 else b""
        host = self.headers.get("Host", "dictpen-appstore.youdao.com")
        proto = "HTTPS" if isinstance(self.connection, ssl.SSLSocket) else "HTTP"

        if any(p in self.path for p in ["generate_204", "gen_204", "connecttest.txt"]):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        print(f"\n[{proto}] >>> POST {self.path} (Host: {host}) from {self.client_address[0]}")

        # 优先转发至真实云端
        status, resp_headers, resp_content = forward_to_upstream("POST", host, self.path, self.headers, post_body)

        if resp_content:
            try:
                resp_text = resp_content.decode("utf-8")
                print(f"[{proto}] <<< UPSTREAM RESP ({status}): {resp_text[:200]}")
            except Exception:
                print(f"[{proto}] <<< UPSTREAM RESP ({status}): [Binary {len(resp_content)} bytes]")
        else:
            print(f"[{proto}] <<< Upstream request timed out or unavailable.")

        # A. 家长管控与下载权限接口 (pullSceneList)
        if "pullSceneList" in self.path:
            target_scene = {
                "sceneName": "应用下载",
                "sceneId": "s202",
                "sceneData": {
                    "sceneType": "COMMON",
                    "status": 1,
                    "online_status": 1
                },
                "operation": {
                    "sceneType": "COMMON",
                    "status": 1,
                    "online_status": 1
                }
            }

            if resp_content:
                try:
                    upstream_data = json.loads(resp_content.decode("utf-8"))
                    if upstream_data.get("code") == 0 and "data" in upstream_data:
                        scenes = upstream_data["data"].get("list", [])
                        has_s202 = False
                        for sc in scenes:
                            if "sceneData" in sc and isinstance(sc["sceneData"], dict):
                                sc["sceneData"]["status"] = 1
                            if "operation" in sc and isinstance(sc["operation"], dict):
                                sc["operation"]["status"] = 1
                            if sc.get("sceneId") == "s202":
                                sc["sceneData"] = {"sceneType": "COMMON", "status": 1, "online_status": 1}
                                sc["operation"] = {"sceneType": "COMMON", "status": 1, "online_status": 1}
                                has_s202 = True
                        if not has_s202:
                            scenes.append(target_scene)
                        upstream_data["data"]["list"] = scenes
                        resp_content = json.dumps(upstream_data, ensure_ascii=False).encode("utf-8")
                        self.send_raw(200, resp_content)
                        print(f"[{proto}] +++ Injected parental authority (s202 status=1)")
                        return
                except Exception as e:
                    print(f"[{proto}] Error patching upstream sceneList: {e}")

            fallback_auth = {
                "code": 0,
                "msg": "success",
                "data": {
                    "list": [
                        target_scene,
                        {"sceneName": "翻译", "sceneId": "s102", "sceneData": {"sceneType": "COMMON", "status": 1}, "operation": {"sceneType": "COMMON", "status": 1}},
                        {"sceneName": "应用市场", "sceneId": "s125", "sceneData": {"sceneType": "COMMON", "status": 1}, "operation": {"sceneType": "COMMON", "status": 1}}
                    ]
                }
            }
            self.send_raw(200, json.dumps(fallback_auth, ensure_ascii=False).encode("utf-8"))
            print(f"[{proto}] <<< Served fallback parental authority (s202 status=1)")
            return

        # B. 应用分类栏目接口 (store_column_s)
        if "store_column_s" in self.path:
            if resp_content and status == 200:
                self.send_raw(status, resp_content)
                print(f"[{proto}] <<< Passed through official categories directly (热门推荐, 学习, 工具)")
                return

            mock_data = {
                "code": 0,
                "msg": "成功",
                "data": [
                    {"columnId": 1, "columnName": "热门推荐", "columnOrder": 1},
                    {"columnId": 2, "columnName": "学习", "columnOrder": 2},
                    {"columnId": 3, "columnName": "工具", "columnOrder": 3}
                ]
            }
            resp_content = json.dumps(mock_data, ensure_ascii=False).encode("utf-8")
            self.send_raw(200, resp_content)
            print(f"[{proto}] <<< Served official fallback categories")
            return

        # C. 栏目下应用列表接口 (store_column_app_s)
        if "store_column_app_s" in self.path:
            if resp_content and status == 200:
                try:
                    data = json.loads(resp_content.decode("utf-8"))
                    if data.get("code") == 0 and "data" in data:
                        d_val = data["data"]
                        if isinstance(d_val, dict):
                            apps = d_val.get("appList", [])
                            our_app = build_custom_app_object()
                            apps = [a for a in apps if str(a.get("appId")) != APP_ID]
                            apps.insert(0, our_app)
                            d_val["appList"] = apps
                            data["data"] = d_val
                            resp_content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                            self.send_raw(200, resp_content)
                            print(f"[{proto}] +++ Injected '{APP_NAME}' into upstream appList (total: {len(apps)})")
                            return
                except Exception as e:
                    print(f"[{proto}] Error parsing upstream app list json: {e}")

            our_app = build_custom_app_object()
            fallback_data = {
                "code": 0,
                "msg": "成功",
                "data": {
                    "appList": [our_app]
                }
            }
            resp_content = json.dumps(fallback_data, ensure_ascii=False).encode("utf-8")
            self.send_raw(200, resp_content)
            print(f"[{proto}] <<< Served fallback appList with '{APP_NAME}'")
            return

        # D. 云端应用白名单许可接口 (control_page_s)
        if "control_page_s" in self.path:
            if resp_content and status == 200:
                try:
                    data = json.loads(resp_content.decode("utf-8"))
                    if data.get("code") == 0 and "data" in data and isinstance(data["data"], list):
                        apps = data["data"]
                        our_app = build_custom_app_object()
                        apps = [a for a in apps if str(a.get("appId")) != APP_ID]
                        apps.insert(0, our_app)
                        data["data"] = apps
                        resp_content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                        self.send_raw(200, resp_content)
                        print(f"[{proto}] +++ Injected '{APP_NAME}' into control_page_s whitelist (total: {len(apps)})")
                        return
                except Exception as e:
                    print(f"[{proto}] Error patching control_page_s: {e}")

            our_app = build_custom_app_object()
            fallback_control = {
                "code": 0,
                "msg": "成功",
                "data": [our_app]
            }
            self.send_raw(200, json.dumps(fallback_control, ensure_ascii=False).encode("utf-8"))
            print(f"[{proto}] <<< Served fallback control_page_s with '{APP_NAME}'")
            return

        # E. 应用版本检查与下载门禁接口 (version/info/batch)
        # Falcon (0x28fb20) 要求 rollingBack <= 200 且 url 非空才会触发 startDownload，否则判为 markInstallError ("安装失败")
        if "version/info/batch" in self.path:
            dl_url = f"http://{LOCAL_IP}:{FILE_PORT}/custom_app.amr"
            target_app_info = {
                "appId": APP_ID,
                "env": "release",
                "rollingBack": 0,
                "version": "1.0.1",
                "url": dl_url,
                "md5": AMR_MD5,
                "size": AMR_SIZE,
                "needRestart": 0,
                "remark": APP_NAME
            }

            if resp_content and status == 200:
                try:
                    data = json.loads(resp_content.decode("utf-8"))
                    if data.get("code") == 0 and "data" in data and isinstance(data["data"], dict):
                        apps = data["data"].get("app", [])
                        found = False
                        for a in apps:
                            if str(a.get("appId")) == APP_ID:
                                a["rollingBack"] = 0
                                a["version"] = "1.0.1"
                                a["url"] = dl_url
                                a["md5"] = AMR_MD5
                                a["size"] = AMR_SIZE
                                a["needRestart"] = 0
                                a["remark"] = APP_NAME
                                a["env"] = "release"
                                found = True
                        if not found:
                            apps.append(target_app_info)
                        data["data"]["app"] = apps
                        data["data"]["appUpdateCount"] = max(1, data["data"].get("appUpdateCount", 0))
                        resp_content = json.dumps(data, ensure_ascii=False).encode("utf-8")
                        self.send_raw(200, resp_content)
                        print(f"[{proto}] +++ Patched version/info/batch (rollingBack=0, url={dl_url})")
                        return
                except Exception as e:
                    print(f"[{proto}] Error patching version/info/batch: {e}")

            fallback_version = {
                "code": 0,
                "msg": "OK",
                "data": {
                    "app": [target_app_info],
                    "appUpdateCount": 1
                },
                "errorData": None
            }
            resp_content = json.dumps(fallback_version, ensure_ascii=False).encode("utf-8")
            self.send_raw(200, resp_content)
            print(f"[{proto}] <<< Served fallback version/info/batch with rollingBack=0")
            return

        # F. 其他上报与统计接口
        if resp_content:
            self.send_raw(status, resp_content)
        else:
            self.send_raw(200, b'{"code":0,"msg":"success","data":{}}')

    def do_GET(self):
        host = self.headers.get("Host", "dictpen-appstore.youdao.com")
        proto = "HTTPS" if isinstance(self.connection, ssl.SSLSocket) else "HTTP"

        if any(p in self.path for p in ["generate_204", "gen_204", "connecttest.txt"]):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        print(f"[{proto}] >>> GET {self.path} (Host: {host}) from {self.client_address[0]}")

        if "custom_app.amr" in self.path:
            serve_file_range(self, AMR_PATH, "application/octet-stream;charset=UTF-8")
            return
        elif "app_icon.png" in self.path:
            serve_file_range(self, ICON_PATH, "image/png")
            return

        # 转发官方资源（例如官方应用封面图 ydhardwarecommon.nosdn.127.net）
        status, resp_headers, resp_content = forward_to_upstream("GET", host, self.path, self.headers, b"")
        if resp_content:
            ct = None
            for k, v in resp_headers.items():
                if k.lower() == "content-type":
                    ct = v
                    break
            if not ct:
                ct = "image/png" if any(self.path.endswith(ext) for ext in [".png", ".jpg", ".jpeg"]) else "application/octet-stream"
            self.send_raw(status, resp_content, ct)
        else:
            self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        pass

def run_http_api():
    try:
        httpd = socketserver.ThreadingTCPServer(("0.0.0.0", HTTP_PORT), AppStoreApiHandler)
        httpd.serve_forever()
    except Exception as e:
        print(f"[HTTP API] Error binding port {HTTP_PORT}: {e}")

def run_https_api():
    try:
        httpd = socketserver.ThreadingTCPServer(("0.0.0.0", HTTPS_PORT), AppStoreApiHandler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        print(f"[HTTPS API] Listening on 0.0.0.0:{HTTPS_PORT} (TLS Proxy Active with Extended SANs)")
        httpd.serve_forever()
    except Exception as e:
        print(f"[HTTPS API] Error binding port {HTTPS_PORT}: {e}")

# --- 3. Static AMR & Icon File Server (Port 14514) ---
class FileHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if "app_icon.png" in self.path:
            serve_file_range(self, ICON_PATH, "image/png")
        else:
            serve_file_range(self, AMR_PATH, "application/octet-stream;charset=UTF-8")

    def log_message(self, format, *args):
        pass

def run_file_server():
    try:
        httpd = socketserver.ThreadingTCPServer(("0.0.0.0", FILE_PORT), FileHandler)
        print(f"[FILE SERVER] Listening on 0.0.0.0:{FILE_PORT} (Serving AMR & Icons)")
        httpd.serve_forever()
    except Exception as e:
        print(f"[FILE SERVER] Error binding port {FILE_PORT}: {e}")

def main():
    print("==========================================================")
    print("   NetEase Youdao Dictionary Pen S7 Pro Transparent Proxy")
    print(f"   Target Device: S7 Pro (192.168.2.x)")
    print(f"   Gateway: {LOCAL_IP}")
    print(f"   Custom App: {APP_NAME} (ID: {APP_ID})")
    print(f"   Package: {AMR_PATH} ({AMR_SIZE:,} bytes, MD5: {AMR_MD5})")
    print("==========================================================")

    setup_pf_redirect()

    t_http = threading.Thread(target=run_http_api, daemon=True)
    t_https = threading.Thread(target=run_https_api, daemon=True)
    t_file = threading.Thread(target=run_file_server, daemon=True)

    t_http.start()
    t_https.start()
    t_file.start()

    print("\n[READY] Transparent Proxy is actively forwarding & intercepting!")
    print("        Open the '应用商店' (App Store) on your S7 Pro screen.")

    try:
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        pass
    finally:
        teardown_pf_redirect()

if __name__ == "__main__":
    main()
