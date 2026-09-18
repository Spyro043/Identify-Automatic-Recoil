import json
import ctypes
import math
import shutil
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


VECTOR_HOME = Path.home() / "Documents" / "Vector2.1弹道版"


class App:
    def __init__(self, core, startup_driver=False):
        self.core = core
        self.config_dir = core.app_dir() / "CONFIG"
        self.store = core.Settings(self.config_dir)
        self.settings = self.store.load()
        self.mode = "driver" if startup_driver else None
        self.device = None
        self.engine = None
        self.worker = None
        self.status = "等待选择运行模式"
        self.logs = deque(maxlen=120)
        self.lock = threading.RLock()
        bundled_vector = core.bundle_dir() / "vector"
        if not (self.config_dir / "profiles.json").exists() and (bundled_vector / "config" / "weapons.json").is_file():
            self.action("/api/import", {"path": str(bundled_vector)})
        if startup_driver:
            self.settings["device"] = "DD"

    def log(self, message):
        with self.lock:
            if message.startswith("STATUS|"):
                self.status = message[7:]
            elif message == "DEVICE|CONNECTED":
                self.status = "设备已连接，正在识别"
            else:
                self.logs.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    def profiles(self):
        path = self.config_dir / "profiles.json"
        own = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        found = {str(p.get("key", "")).lower() for p in own}
        paths = [p for p in self.config_dir.glob("*.json") if p.name.lower() != "settings.json"]
        for item in self.core.load_trajectories(self.config_dir) if paths else []:
            if str(item.get("key", "")).lower() not in found:
                own.append(item)
                found.add(str(item.get("key", "")).lower())
        return own

    def save_profiles(self, profiles):
        path = self.config_dir / "profiles.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def state(self):
        with self.lock:
            profiles = self.profiles()
            bmps = {p.stem.lower() for p in self.config_dir.glob("*.bmp")}
            return {"mode": self.mode, "settings": self.settings, "connected": self.device is not None,
                    "running": bool(self.worker and self.worker.is_alive()), "status": self.status,
                    "profiles": [{**p, "image_ready": str(p.get("key", "")).lower() in bmps} for p in profiles],
                    "logs": list(self.logs)}

    def disconnect(self):
        if self.device:
            self.device.close()
            self.device = None

    def connect(self):
        if self.worker and self.worker.is_alive():
            raise RuntimeError("请先停止识别")
        self.disconnect()
        if self.mode == "driver":
            if sys.platform == "win32" and not ctypes.windll.shell32.IsUserAnAdmin():
                if not getattr(sys, "frozen", False):
                    raise RuntimeError("内核模式需要管理员权限，请以管理员身份运行程序")
                result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, "--driver", None, 1)
                if result <= 32:
                    raise RuntimeError("未获得管理员权限，DD 驱动未加载")
                if hasattr(self, "server"):
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.relaunched = True
                return
            self.settings["device"] = "DD"
        elif self.mode == "hardware":
            if self.settings["device"] not in ("KMBOXNET", "MAKCU"):
                self.settings["device"] = "KMBOXNET"
        else:
            raise RuntimeError("请先选择运行模式")
        mouse = self.core.make_mouse(self.settings)
        try:
            mouse.connect()
        except Exception:
            mouse.close()
            raise
        self.device = mouse
        self.status = f"{self.settings['device']} 连接成功"
        self.log(self.status)

    def start(self, execute):
        if self.worker and self.worker.is_alive():
            raise RuntimeError("识别任务已在运行")
        if self.mode is None:
            raise RuntimeError("请先选择运行模式")
        if execute and self.device is None:
            self.connect()
        self.disconnect()
        self.engine = self.core.OfficeLogoDragEngine(self.config_dir, dict(self.settings), self.log)
        engine = self.engine

        def work():
            try:
                engine.run(execute)
            except Exception as exc:
                self.log(f"错误：{exc}")
                self.log(f"STATUS|错误：{exc}")
            finally:
                self.log("识别已停止")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.status = "正在启动识别"

    def action(self, route, data):
        with self.lock:
            if route == "/api/mode":
                mode = data.get("mode")
                if mode not in ("driver", "hardware"):
                    raise ValueError("运行模式无效")
                if self.worker and self.worker.is_alive():
                    raise RuntimeError("请先停止识别")
                if mode == "hardware" and self.core.dd_loaded():
                    raise RuntimeError("DD 已在本进程加载。请退出程序后重新打开，再选择硬件设备。")
                self.disconnect()
                self.mode = mode
                if mode == "driver":
                    self.settings["device"] = "DD"
                    if not self.settings.get("dd_dll_path"):
                        self.settings["dd_dll_path"] = str(VECTOR_HOME / "dd" / "dd63330.dll")
                else:
                    self.settings["device"] = "KMBOXNET"
                self.store.save(self.settings)
                self.status = "已选择内核驱动" if mode == "driver" else "已选择硬件设备"
            elif route == "/api/settings":
                allowed = {"ip", "uid", "port", "makcu_port", "makcu_baudrate", "dd_dll_path", "threshold",
                           "region_left", "region_top", "region_right", "region_bottom", "tick_ms", "scale", "sensitivity", "device", "match_mode"}
                changed = {k: v for k, v in data.items() if k in allowed}
                if "device" in changed:
                    choices = ("DD",) if self.mode == "driver" else ("KMBOXNET", "MAKCU") if self.mode == "hardware" else ()
                    if changed["device"] not in choices:
                        raise ValueError("当前模式不能选择此设备")
                for key in ("region_left", "region_top", "region_right", "region_bottom", "tick_ms"):
                    if key in changed:
                        changed[key] = int(changed[key])
                for key in ("threshold", "scale", "sensitivity"):
                    if key in changed:
                        changed[key] = float(changed[key])
                        if not math.isfinite(changed[key]):
                            raise ValueError(f"{key} 必须是有限数字")
                merged = {**self.settings, **changed}
                if merged["region_right"] <= merged["region_left"] or merged["region_bottom"] <= merged["region_top"]:
                    raise ValueError("识别区域坐标无效")
                if not 0 < float(merged["threshold"]) <= 1 or not 1 <= int(merged["tick_ms"]) <= 100:
                    raise ValueError("阈值或轨迹间隔无效")
                if self.device and any(k in changed for k in ("device", "ip", "port", "uid", "makcu_port", "makcu_baudrate", "dd_dll_path")):
                    self.disconnect()
                self.settings = merged
                self.store.save(merged)
                self.log("设置已保存")
            elif route == "/api/connect":
                self.connect()
            elif route == "/api/disconnect":
                if self.worker and self.worker.is_alive():
                    raise RuntimeError("请先停止识别")
                self.disconnect()
                self.status = "设备已断开"
            elif route == "/api/test":
                if not self.device or (self.worker and self.worker.is_alive()):
                    raise RuntimeError("请先连接设备并停止识别")
                dx, dy = int(data.get("dx", 0)), int(data.get("dy", 0))
                if not (dx or dy) or max(abs(dx), abs(dy)) > 100:
                    raise ValueError("测试位移须在 -100 到 100 之间且不能都为零")
                self.device.move_relative(dx, dy)
                time.sleep(0.2)
                self.device.move_relative(-dx, -dy)
                self.log(f"已发送测试位移 ({dx}, {dy}) 并返回。请观察鼠标是否移动。")
            elif route == "/api/start":
                self.start(bool(data.get("execute", True)))
            elif route == "/api/stop":
                if self.engine:
                    self.engine.stop()
                self.status = "正在停止识别"
            elif route == "/api/profile":
                if self.worker and self.worker.is_alive():
                    raise RuntimeError("请先停止识别再修改模板")
                item = data.get("profile", {})
                key = str(item.get("key", "")).strip()
                if not key or any(c in key for c in '<>:"/\\|?*') or key in (".", ".."):
                    raise ValueError("模板标识无效")
                for field in ("power", "x_power", "y_power"):
                    item[field] = float(item.get(field, 100))
                    if not math.isfinite(item[field]) or not 0 <= item[field] <= 300:
                        raise ValueError(f"{field} 须在 0 到 300 之间")
                for field in ("level", "frequency", "decline", "duration", "start_delay", "initial_drop"):
                    if field in item:
                        item[field] = float(item[field])
                        if not math.isfinite(item[field]):
                            raise ValueError(f"{field} 必须是有限数字")
                if not isinstance(item.get("adjustments", []), list) or any(not isinstance(part, dict) for part in item.get("adjustments", [])):
                    raise ValueError("分段参数须为数组")
                profiles = self.profiles()
                profiles = [p for p in profiles if str(p.get("key", "")).lower() != key.lower()]
                if "engine" not in item and self.settings.get("match_mode") == "vector":
                    item["engine"] = "vector_legacy"
                profiles.append(item)
                self.save_profiles(profiles)
                self.log(f"已保存模板 {key}")
            elif route == "/api/import":
                root = Path(str(data.get("path") or VECTOR_HOME)).expanduser().resolve()
                source = root / "config" / "weapons.json"
                if not source.is_file():
                    raise FileNotFoundError(f"找不到 {source}")
                items = json.loads(source.read_text(encoding="utf-8"))
                if not isinstance(items, list):
                    raise ValueError("武器数据格式无效")
                profiles = self.profiles()
                existing = {str(p.get("key", "")).lower(): p for p in profiles}
                images = next(iter(sorted((root / "ModPic").glob("*"))), None)
                count = 0
                for item in items:
                    key = str(item.get("key", ""))
                    if not key or any(c in key for c in '<>:"/\\|?*'):
                        continue
                    if key.lower() not in existing:
                        profile = {**item, "power": 100, "x_power": 100, "y_power": 100, "enabled": True, "engine": "vector_legacy"}
                        profiles.append(profile)
                        existing[key.lower()] = profile
                        count += 1
                    else:
                        existing[key.lower()]["engine"] = "vector_legacy"
                    bmp = images / f"{key}.bmp" if images else None
                    target = self.config_dir / f"{key}.bmp"
                    if bmp and bmp.is_file() and not target.exists():
                        shutil.copy2(bmp, target)
                self.save_profiles(profiles)
                app_settings = root / "config" / "app_settings.json"
                if app_settings.is_file():
                    original = json.loads(app_settings.read_text(encoding="utf-8"))
                    width, height = int(original.get("gameResW", 2560)), int(original.get("gameResH", 1440))
                    x, y = round(float(original.get("roiX", .791)) * width), round(float(original.get("roiY", .866)) * height)
                    self.settings.update({"region_left": x, "region_top": y,
                                          "region_right": x + round(float(original.get("roiW", .11)) * width),
                                          "region_bottom": y + round(float(original.get("roiH", .09)) * height),
                                          "threshold": float(original.get("matchThreshold", .55)),
                                          "scan_interval": float(original.get("detectInterval", .083333333)),
                                          "tick_ms": 4, "scale": float(original.get("scaleFactor", 1)), "match_mode": "vector"})
                    self.store.save(self.settings)
                self.log(f"从本机 Vector 目录导入 {count} 个新模板")
            elif route == "/api/exit":
                if self.engine:
                    self.engine.stop()
                self.disconnect()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                raise ValueError("未知操作")
            return self.state()

    def run(self):
        if self.mode == "driver":
            try:
                self.connect()
            except Exception as exc:
                self.log(f"DD 连接失败：{exc}")
            if getattr(self, "relaunched", False):
                return
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def local_host(self):
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    self.reply(403, {"error": "仅允许本机访问"})
                    return False
                return True

            def reply(self, code, value):
                body = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if not self.local_host():
                    return
                path = urlparse(self.path).path
                if path == "/api/state":
                    try:
                        self.reply(200, app.state())
                    except Exception as exc:
                        self.reply(400, {"error": str(exc)})
                    return
                if path != "/":
                    self.send_error(404)
                    return
                page = app.core.bundle_dir() / "WEBUI" / "index.html"
                if not page.is_file():
                    page = app.core.app_dir() / "WEBUI" / "index.html"
                body = page.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if not self.local_host():
                    return
                origin = self.headers.get("Origin", "")
                if origin and origin != f"http://127.0.0.1:{self.server.server_port}":
                    self.reply(403, {"error": "来源无效"})
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.reply(415, {"error": "仅接受 JSON"})
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length > 1_000_000:
                    self.reply(413, {"error": "请求过大"})
                    return
                try:
                    data = json.loads(self.rfile.read(length))
                    if not isinstance(data, dict):
                        raise ValueError("参数格式无效")
                    self.reply(200, app.action(urlparse(self.path).path, data))
                except Exception as exc:
                    self.reply(400, {"error": str(exc)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        url = f"http://127.0.0.1:{self.server.server_port}/"
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        try:
            self.server.serve_forever()
        finally:
            if self.engine:
                self.engine.stop()
            self.disconnect()
            self.server.server_close()
