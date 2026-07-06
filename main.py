import argparse
import ctypes
import json
import math
import queue
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import mss
import numpy as np

try:
    import dxcam
except Exception:
    dxcam = None


DIRECTION_MAP = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, -1.0),
    "down": (0.0, 1.0),
    "down_left": (-0.707, 0.707),
    "down_right": (0.707, 0.707),
    "up_left": (-0.707, -0.707),
    "up_right": (0.707, -0.707),
}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin_if_needed() -> bool:
    if is_admin():
        return False
    if not getattr(sys, "frozen", False):
        return False

    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if result <= 32:
        raise RuntimeError("无法申请管理员权限，请右键以管理员身份运行。")
    return True


def tune_process_for_capture() -> None:
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    try:
        HIGH_PRIORITY_CLASS = 0x00000080
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), HIGH_PRIORITY_CLASS)
    except Exception:
        pass


@dataclass(frozen=True)
class Template:
    key: str
    path: Path
    image_gray: np.ndarray


@dataclass(frozen=True)
class MatchResult:
    template: Template
    score: float
    location: tuple[int, int]


class DryRunMouse:
    def connect(self) -> None:
        pass

    def right_down(self) -> None:
        pass

    def right_up(self) -> None:
        pass

    def move_relative(self, dx: int, dy: int) -> None:
        pass

    def is_left_down(self) -> bool:
        return False

    def close(self) -> None:
        self.right_up()


class KmboxNetMouse:
    def __init__(self, ip: str, port: str, uid: str) -> None:
        self.ip = ip
        self.port = port
        self.uid = uid
        self.kmnet: Any | None = None

    def connect(self) -> None:
        import kmNet

        self.kmnet = kmNet
        result = self.kmnet.init(self.ip, self.port, self.uid)
        if result != 0:
            raise RuntimeError(f"KMBOXNET connection failed: {result}")

    def right_down(self) -> None:
        pass

    def right_up(self) -> None:
        pass

    def move_relative(self, dx: int, dy: int) -> None:
        if dx or dy:
            self.kmnet.move(int(dx), int(dy))

    def is_left_down(self) -> bool:
        return is_left_down()

    def close(self) -> None:
        pass


class Settings:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.path = config_dir / "settings.json"
        self.data = {
            "ip": "192.168.2.188",
            "uid": "",
            "port": "8338",
            "threshold": 0.86,
            "region_left": 1518,
            "region_top": 926,
            "region_right": 1871,
            "region_bottom": 1032,
            "scan_interval": 0.2,
            "lost_after_seconds": 0.8,
            "tick_ms": 10,
            "scale": 1.0,
            "sensitivity": 1.0,
        }

    def load(self) -> dict[str, Any]:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        else:
            self.save()
        return dict(self.data)

    def save(self, values: dict[str, Any] | None = None) -> None:
        if values:
            self.data.update(values)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


class OfficeLogoDragEngine:
    def __init__(self, config_dir: Path, settings: dict[str, Any], logger: Callable[[str], None]) -> None:
        self.config_dir = config_dir
        self.settings = settings
        self.log = logger
        self.stop_event = threading.Event()
        self.mouse: DryRunMouse | KmboxNetMouse | None = None
        self.trajectories: list[dict[str, Any]] = []
        self.templates: list[Template] = []

    def status(self, message: str) -> None:
        self.log("STATUS|" + message)

    def stop(self) -> None:
        self.stop_event.set()

    def run(self, execute: bool) -> None:
        self.templates = load_templates(self.config_dir)
        self.trajectories = load_trajectories(self.config_dir)
        self.mouse = KmboxNetMouse(ip=str(self.settings["ip"]), port=str(self.settings["port"]), uid=str(self.settings["uid"])) if execute else DryRunMouse()
        self.mouse.connect()
        self.log(f"已加载 {len(self.templates)} 张识别图片，{len(self.trajectories)} 条轨迹。")
        self.status("已启动，等待识别右下角 Logo")

        active_key: str | None = None
        active_steps: list[tuple[int, int, float]] = []
        last_seen = 0.0
        ready_reported = False
        try:
            with ScreenCapture(self.settings, self.log) as capture:
                self.log(f"截图后端：{capture.backend_name}")
                while not self.stop_event.is_set():
                    screen_gray = capture.grab_gray()
                    match = find_best_match(screen_gray, self.templates)
                    now = time.perf_counter()
                    threshold = float(self.settings["threshold"])

                    if match and match.score >= threshold:
                        last_seen = now
                        if active_key != match.template.key:
                            trajectory = find_trajectory(self.trajectories, match.template.key)
                            if trajectory is None:
                                self.log(f"识别到 {match.template.path.name}，但 CONFIG 内没有同名轨迹。")
                                self.status(f"识别到 {match.template.path.name}，缺少同名轨迹")
                                active_key = None
                                active_steps = []
                                self.mouse.right_up()
                            else:
                                active_key = match.template.key
                                active_steps = build_steps(trajectory, self.settings)
                                ready_reported = False
                                self.log(f"识别到 {match.template.path.name}，匹配分数 {match.score:.3f}，已读取对应轨迹。")
                                self.status(f"已识别 {match.template.path.name}，请按住右键进入待激活")
                    elif active_key and now - last_seen > float(self.settings["lost_after_seconds"]):
                        self.log(f"Logo 消失：{active_key}。")
                        self.status("Logo 消失，等待重新识别")
                        active_key = None
                        active_steps = []
                        ready_reported = False

                    if active_key and active_steps and is_right_down():
                        if not ready_reported:
                            self.log(f"检测到右键按住，进入待激活状态：{active_key}")
                            self.status(f"右键按住，待激活：{active_key}，再按住左键开始")
                            ready_reported = True
                    elif active_key and active_steps and ready_reported:
                        self.status(f"已识别 {active_key}，请按住右键进入待激活")
                        ready_reported = False

                    if active_key and active_steps and is_right_down() and is_left_down():
                        self.log(f"检测到左键按住，正在执行轨迹：{active_key}")
                        self.status(f"左键已按住，轨迹执行中：{active_key}")
                        play_while_buttons_down(self.mouse, active_steps, self.stop_event)
                        self.log("左键已松开，轨迹停止。")
                        self.status(f"轨迹停止，右键按住时可再次按左键执行：{active_key}")

                    self.stop_event.wait(float(self.settings["scan_interval"]))
        finally:
            if self.mouse:
                self.mouse.close()


def load_templates(config_dir: Path) -> list[Template]:
    config_dir.mkdir(parents=True, exist_ok=True)
    templates: list[Template] = []
    for path in sorted(config_dir.glob("*.bmp")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is not None:
            templates.append(Template(key=path.stem, path=path, image_gray=image))
    if not templates:
        raise RuntimeError(f"No bmp templates found in {config_dir}")
    return templates


def load_trajectories(config_dir: Path) -> list[dict[str, Any]]:
    trajectories: list[dict[str, Any]] = []
    for path in sorted(config_dir.glob("*.json")):
        if path.name.lower() == "settings.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    trajectories.append(item)
        elif isinstance(data, dict):
            trajectories.append(data)
        else:
            raise RuntimeError(f"{path.name} 必须是轨迹对象或轨迹数组。")
    if not trajectories:
        raise RuntimeError("CONFIG 内没有轨迹 JSON。")
    return trajectories


def find_trajectory(trajectories: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    key_lower = key.lower()
    for item in trajectories:
        values = [item.get("key"), item.get("name"), item.get("id"), item.get("image"), item.get("template")]
        if any(str(value).lower() == key_lower for value in values if value is not None):
            return item
    return None


class ScreenCapture:
    def __init__(self, settings: dict[str, Any], logger: Callable[[str], None]) -> None:
        self.settings = settings
        self.log = logger
        self.camera: Any | None = None
        self.region: tuple[int, int, int, int] | None = None
        self.backend_name = "DXGI"
        self.none_count = 0

    def __enter__(self) -> "ScreenCapture":
        if dxcam is None:
            raise RuntimeError("DXGI 截图模块 dxcam 不可用，无法启动。")

        left = int(self.settings["region_left"])
        top = int(self.settings["region_top"])
        right = int(self.settings["region_right"])
        bottom = int(self.settings["region_bottom"])
        if right <= left or bottom <= top:
            raise RuntimeError("识别区域坐标无效，请确认右侧坐标大于左侧、下方坐标大于上方。")
        self.region = (left, top, right, bottom)

        self._start_camera()
        first_frame = self._wait_for_frame(timeout_seconds=2.0)
        if first_frame is None:
            self._restart_camera("DXGI 启动后 2 秒内没有返回画面帧，正在重启。")
            first_frame = self._wait_for_frame(timeout_seconds=2.0)
        if first_frame is None:
            raise RuntimeError("DXGI 已启动，但持续没有返回画面帧。")

        return self

    def _start_camera(self) -> None:
        if self.region is None:
            raise RuntimeError("截图区域未初始化。")
        try:
            self.camera = dxcam.create(output_idx=0, output_color="BGR")
            self.camera.start(region=self.region, target_fps=60, video_mode=True)
            self.none_count = 0
        except Exception as exc:
            self.camera = None
            raise RuntimeError(f"DXGI 初始化失败：{exc}") from exc

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self._release_camera()

    def _release_camera(self) -> None:
        if self.camera is not None:
            try:
                if getattr(self.camera, "is_capturing", False):
                    self.camera.stop()
            except Exception:
                pass
            try:
                self.camera.release()
            except Exception:
                pass
            self.camera = None

    def _restart_camera(self, reason: str) -> None:
        self.log(reason)
        self._release_camera()
        time.sleep(0.08)
        self._start_camera()

    def _wait_for_frame(self, timeout_seconds: float) -> np.ndarray | None:
        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            if self.camera is None:
                return None
            frame = self.camera.get_latest_frame(copy=False)
            if frame is not None:
                self.none_count = 0
                return frame
            time.sleep(0.01)
        return None

    def grab_gray(self) -> np.ndarray:
        if self.region is None:
            raise RuntimeError("截图区域未初始化。")

        if self.camera is None:
            raise RuntimeError("DXGI 截图器未初始化。")

        frame = self.camera.get_latest_frame(copy=False)
        if frame is None:
            self.none_count += 1
            if self.none_count >= 30:
                self._restart_camera("DXGI 连续没有返回画面帧，已自动重启截图。")
                self.none_count = 0
            frame = self._wait_for_frame(timeout_seconds=0.5)
        if frame is None:
            self._restart_camera("DXGI 当前仍未返回画面帧，继续重启截图。")
            frame = self._wait_for_frame(timeout_seconds=0.5)
        if frame is None:
            raise RuntimeError("DXGI 重启后仍没有返回画面帧。")
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def capture_bottom_right(sct: mss.mss, settings: dict[str, Any]) -> np.ndarray:
    monitor = sct.monitors[1]
    width = int(settings["region_width"])
    height = int(settings["region_height"])
    left = monitor["left"] + monitor["width"] - width
    top = monitor["top"] + monitor["height"] - height
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2GRAY)


def find_best_match(screen_gray: np.ndarray, templates: list[Template]) -> MatchResult | None:
    best: MatchResult | None = None
    for template in templates:
        th, tw = template.image_gray.shape[:2]
        sh, sw = screen_gray.shape[:2]
        if th > sh or tw > sw:
            continue
        result = cv2.matchTemplate(screen_gray, template.image_gray, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if best is None or score > best.score:
            best = MatchResult(template=template, score=float(score), location=location)
    return best


def build_steps(trajectory: dict[str, Any], settings: dict[str, Any]) -> list[tuple[int, int, float]]:
    sensitivity = float(settings.get("sensitivity", 1.0))
    if isinstance(trajectory.get("path"), list):
        return [
            (
                int(round(float(step.get("dx", step.get("x", 0))) * sensitivity)),
                int(round(float(step.get("dy", step.get("y", 0))) * sensitivity)),
                float(step.get("delay", 0.01)),
            )
            for step in trajectory["path"]
        ]

    duration = infer_duration(trajectory)
    tick = max(1, int(settings["tick_ms"])) / 1000.0
    scale = float(settings["scale"])
    steps: list[tuple[int, int, float]] = []
    previous_x = 0.0
    previous_y = 0.0
    carry_x = 0.0
    carry_y = 0.0
    ticks = max(1, math.ceil(duration / tick))

    for index in range(1, ticks + 1):
        elapsed = min(duration, index * tick)
        x, y = pattern_at(trajectory, elapsed, scale)
        raw_dx = x - previous_x + carry_x
        raw_dy = y - previous_y + carry_y
        dx = round(raw_dx)
        dy = round(raw_dy)
        carry_x = raw_dx - dx
        carry_y = raw_dy - dy
        previous_x = x
        previous_y = y
        steps.append((int(round(dx * sensitivity)), int(round(dy * sensitivity)), tick))
    return steps


def infer_duration(trajectory: dict[str, Any]) -> float:
    duration = float(trajectory.get("duration") or 0.0)
    for adjustment in trajectory.get("adjustments") or []:
        end = float(adjustment.get("start_time") or 0.0) + float(adjustment.get("duration") or 0.0)
        duration = max(duration, end)
    return max(duration, 1.0)


def pattern_at(trajectory: dict[str, Any], seconds: float, scale: float) -> tuple[float, float]:
    seconds = max(0.0, seconds - float(trajectory.get("start_delay") or 0.0))
    x = 0.0
    y = float(trajectory.get("initial_drop") or 0.0)
    y += seconds * float(trajectory.get("decline") or 0.0)

    for adjustment in trajectory.get("adjustments") or []:
        if not adjustment.get("enabled", True):
            continue
        start = float(adjustment.get("start_time") or 0.0)
        duration = float(adjustment.get("duration") or 0.0)
        active = min(max(seconds - start, 0.0), duration)
        if active <= 0:
            continue
        dx, dy = DIRECTION_MAP.get(str(adjustment.get("direction") or ""), (0.0, 0.0))
        intensity = float(adjustment.get("intensity") or 0.0)
        x += dx * intensity * active
        y += dy * intensity * active
    return x * scale, y * scale


def play_while_buttons_down(mouse: KmboxNetMouse | DryRunMouse, steps: list[tuple[int, int, float]], stop_event: threading.Event) -> None:
    index = 0
    while not stop_event.is_set() and is_right_down() and is_left_down():
        dx, dy, delay = steps[index]
        mouse.move_relative(dx, dy)
        end = time.perf_counter() + max(delay, 0.001)
        while time.perf_counter() < end:
            if stop_event.is_set() or not is_right_down() or not is_left_down():
                return
            time.sleep(0.001)
        index = (index + 1) % len(steps)


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_CLOSE = 0x0010
WM_SETFONT = 0x0030
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_BORDER = 0x00800000
WS_VSCROLL = 0x00200000
WS_TABSTOP = 0x00010000
ES_AUTOHSCROLL = 0x0080
ES_AUTOVSCROLL = 0x0040
ES_MULTILINE = 0x0004
ES_READONLY = 0x0800
BS_PUSHBUTTON = 0x00000000
SW_SHOW = 5
COLOR_WINDOW = 5
IDC_ARROW = 32512
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02

ID_SAVE = 1001
ID_REFRESH = 1002
ID_DRY = 1003
ID_START = 1004
ID_STOP = 1005
ID_RECORD = 1006


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def is_left_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def is_right_down() -> bool:
    return bool(user32.GetAsyncKeyState(VK_RBUTTON) & 0x8000)


def get_cursor_pos() -> tuple[int, int]:
    point = POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def safe_trajectory_filename(name: str) -> str:
    forbidden = '<>:"/\\|?*'
    cleaned = "".join("_" if char in forbidden else char for char in name).strip()
    if not cleaned:
        raise RuntimeError("轨迹名不能为空。")
    return cleaned


def export_recorded_trajectory(config_dir: Path, name: str, path_steps: list[dict[str, float]]) -> Path:
    safe_name = safe_trajectory_filename(name)
    json_path = config_dir / f"{safe_name}.json"
    item = {"key": name, "name": name, "path": path_steps}
    json_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class NativeApp:
    def __init__(self) -> None:
        self.config_dir = app_dir() / "CONFIG"
        self.settings_store = Settings(self.config_dir)
        self.settings = self.settings_store.load()
        self.engine: OfficeLogoDragEngine | None = None
        self.worker: threading.Thread | None = None
        self.record_worker: threading.Thread | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.hwnd: int | None = None
        self.edits: dict[str, int] = {}
        self.files_box: int | None = None
        self.log_box: int | None = None
        self.status_box: int | None = None
        self._wndproc = WNDPROC(self._handle_message)

    def run(self) -> None:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "OfficeLogoDragWindow"
        wc = WNDCLASS()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = COLOR_WINDOW + 1
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "公司 Logo 自动拖动工具",
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            180,
            120,
            780,
            740,
            None,
            None,
            hinstance,
            None,
        )
        self._create_controls()
        user32.SetTimer(self.hwnd, 1, 200, None)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        self.refresh_files()
        self.log("程序已就绪，请把轨迹 JSON 和 bmp 图片放入 CONFIG。")
        self.log("当前权限：" + ("管理员" if is_admin() else "普通用户"))

        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _handle_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM_COMMAND:
            command_id = int(wparam) & 0xFFFF
            if command_id == ID_SAVE:
                self.save_settings()
            elif command_id == ID_REFRESH:
                self.refresh_files()
            elif command_id == ID_DRY:
                self.start(False)
            elif command_id == ID_START:
                self.start(True)
            elif command_id == ID_STOP:
                self.stop()
            elif command_id == ID_RECORD:
                self.start_recording()
            return 0
        if msg == WM_TIMER:
            self._drain_logs()
            return 0
        if msg in (WM_CLOSE, WM_DESTROY):
            self.stop()
            user32.DestroyWindow(hwnd)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _create_controls(self) -> None:
        self._label("KMBOXNET 连接", 20, 14, 160, 22)
        self._entry("IP", "ip", 20, 44)
        self._entry("UID", "uid", 390, 44)
        self._entry("PORT", "port", 20, 82)

        self._label("识别与轨迹", 20, 126, 160, 22)
        self._entry("匹配阈值", "threshold", 20, 156)
        self._entry("左X", "region_left", 390, 156)
        self._entry("上Y", "region_top", 20, 194)
        self._entry("右X", "region_right", 390, 194)
        self._entry("下Y", "region_bottom", 20, 232)
        self._entry("轨迹缩放", "scale", 390, 232)
        self._entry("轨迹间隔ms", "tick_ms", 20, 270)
        self._entry("灵敏度", "sensitivity", 390, 270)

        self._button("保存配置", ID_SAVE, 20, 314, 100, 30)
        self._button("刷新CONFIG", ID_REFRESH, 130, 314, 120, 30)
        self._button("试运行", ID_DRY, 260, 314, 90, 30)
        self._button("连接并启动", ID_START, 360, 314, 130, 30)
        self._button("停止", ID_STOP, 500, 314, 90, 30)

        self._label("轨迹录制", 20, 356, 120, 20)
        self._entry("轨迹名", "record_name", 20, 380)
        self._button("开始录制", ID_RECORD, 390, 380, 110, 28)

        self._label("当前状态", 20, 422, 120, 20)
        self.status_box = self._text_box(20, 446, 720, 34, readonly=True)
        self._set_text(self.status_box, "未启动")

        self._label("CONFIG 文件", 20, 490, 140, 20)
        self.files_box = self._text_box(20, 514, 720, 58, readonly=True)
        self._label("运行日志", 20, 582, 100, 20)
        self.log_box = self._text_box(20, 606, 720, 42, readonly=True)

    def _label(self, text: str, x: int, y: int, w: int, h: int) -> int:
        return user32.CreateWindowExW(0, "STATIC", text, WS_CHILD | WS_VISIBLE, x, y, w, h, self.hwnd, None, None, None)

    def _entry(self, label: str, key: str, x: int, y: int) -> None:
        self._label(label, x, y + 4, 105, 22)
        hwnd = user32.CreateWindowExW(
            0,
            "EDIT",
            str(self.settings.get(key, "")),
            WS_CHILD | WS_VISIBLE | WS_BORDER | WS_TABSTOP | ES_AUTOHSCROLL,
            x + 110,
            y,
            220,
            24,
            self.hwnd,
            None,
            None,
            None,
        )
        self.edits[key] = hwnd

    def _button(self, text: str, command_id: int, x: int, y: int, w: int, h: int) -> int:
        return user32.CreateWindowExW(
            0,
            "BUTTON",
            text,
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
            x,
            y,
            w,
            h,
            self.hwnd,
            command_id,
            None,
            None,
        )

    def _text_box(self, x: int, y: int, w: int, h: int, readonly: bool) -> int:
        style = WS_CHILD | WS_VISIBLE | WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL
        if readonly:
            style |= ES_READONLY
        return user32.CreateWindowExW(0, "EDIT", "", style, x, y, w, h, self.hwnd, None, None, None)

    def _get_text(self, hwnd: int) -> str:
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _set_text(self, hwnd: int, text: str) -> None:
        user32.SetWindowTextW(hwnd, text)

    def _append_text(self, hwnd: int, text: str) -> None:
        length = user32.GetWindowTextLengthW(hwnd)
        user32.SendMessageW(hwnd, EM_SETSEL, length, length)
        user32.SendMessageW(hwnd, EM_REPLACESEL, False, text)

    def read_settings(self) -> dict[str, Any]:
        values = {key: self._get_text(hwnd).strip() for key, hwnd in self.edits.items() if key != "record_name"}
        for key in ("threshold", "scale", "sensitivity"):
            values[key] = float(values[key])
        for key in ("region_left", "region_top", "region_right", "region_bottom", "tick_ms"):
            values[key] = int(values[key])
        values["scan_interval"] = float(self.settings.get("scan_interval", 0.2))
        values["lost_after_seconds"] = float(self.settings.get("lost_after_seconds", 0.8))
        return values

    def save_settings(self) -> None:
        try:
            self.settings = self.read_settings()
            self.settings_store.save(self.settings)
            self.log("Settings saved.")
        except Exception as exc:
            self.error(str(exc))

    def refresh_files(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        bmps = sorted(path.name for path in self.config_dir.glob("*.bmp"))
        jsons = sorted(path.name for path in self.config_dir.glob("*.json") if path.name.lower() != "settings.json")
        lines = [
            f"目录：{self.config_dir}",
            "轨迹JSON：" + (", ".join(jsons) if jsons else "暂无轨迹 JSON"),
            "识别图片：" + (", ".join(bmps) if bmps else "暂无 bmp 图片"),
        ]
        if self.files_box:
            self._set_text(self.files_box, "\r\n".join(lines))

    def start(self, execute: bool) -> None:
        if self.worker and self.worker.is_alive():
            self.log("Already running.")
            return
        try:
            self.save_settings()
            self.refresh_files()
            self.engine = OfficeLogoDragEngine(self.config_dir, self.settings, self.log)
            self.worker = threading.Thread(target=self._run_engine, args=(execute,), daemon=True)
            self.worker.start()
            self.log("已连接 KMBOXNET 并启动。" if execute else "已启动试运行模式。")
            self.set_status("已启动，等待识别右下角 Logo")
        except Exception as exc:
            self.error(str(exc))

    def _run_engine(self, execute: bool) -> None:
        try:
            if self.engine:
                self.engine.run(execute)
        except Exception as exc:
            self.log(f"错误：{exc}")
            self.set_status(f"错误：{exc}")

    def stop(self) -> None:
        if self.engine:
            self.engine.stop()
        self.log("正在停止。")
        self.set_status("已停止")

    def start_recording(self) -> None:
        if self.record_worker and self.record_worker.is_alive():
            self.log("录制已经在进行中。")
            return
        name_hwnd = self.edits.get("record_name")
        name = self._get_text(name_hwnd).strip() if name_hwnd else ""
        if not name:
            self.error("请先填写轨迹名，例如 ASD。")
            return
        self.record_worker = threading.Thread(target=self._record_trajectory, args=(name,), daemon=True)
        self.record_worker.start()

    def _record_trajectory(self, name: str) -> None:
        try:
            self.log(f"准备录制轨迹：{name}。请按住左键开始拖动，松开左键自动保存。")
            self.set_status(f"录制准备中：{name}，等待左键按下")

            while not is_left_down():
                time.sleep(0.005)

            previous_x, previous_y = get_cursor_pos()
            previous_time = time.perf_counter()
            steps: list[dict[str, float]] = []
            self.log(f"开始录制：{name}")
            self.set_status(f"正在录制：{name}，松开左键保存")

            while is_left_down():
                time.sleep(0.005)
                current_x, current_y = get_cursor_pos()
                now = time.perf_counter()
                dx = current_x - previous_x
                dy = current_y - previous_y
                delay = max(0.001, now - previous_time)
                if dx or dy:
                    steps.append({"dx": dx, "dy": dy, "delay": round(delay, 4)})
                    previous_x, previous_y = current_x, current_y
                    previous_time = now

            if not steps:
                self.log(f"录制取消：{name}，没有检测到鼠标移动。")
                self.set_status("录制取消，没有检测到鼠标移动")
                return

            saved_path = export_recorded_trajectory(self.config_dir, name, steps)
            self.log(f"录制完成：{name}，已保存 {len(steps)} 步到 {saved_path.name}。")
            self.set_status(f"录制完成：{name}，已导出 {saved_path.name}")
            self.refresh_files()
        except Exception as exc:
            self.log(f"录制错误：{exc}")
            self.set_status(f"录制错误：{exc}")

    def log(self, message: str) -> None:
        if message.startswith("STATUS|"):
            self.log_queue.put(message)
        else:
            self.log_queue.put(f"[{time.strftime('%H:%M:%S')}] {message}\r\n")

    def set_status(self, message: str) -> None:
        self.log_queue.put("STATUS|" + message)

    def _drain_logs(self) -> None:
        if not self.log_box:
            return
        while True:
            try:
                message = self.log_queue.get_nowait()
                if message.startswith("STATUS|"):
                    if self.status_box:
                        self._set_text(self.status_box, message.removeprefix("STATUS|"))
                else:
                    self._append_text(self.log_box, message)
            except queue.Empty:
                break

    def error(self, message: str) -> None:
        user32.MessageBoxW(self.hwnd, message, "公司 Logo 自动拖动工具", 0x10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nogui", action="store_true", help="run without UI")
    parser.add_argument("--execute", action="store_true", help="connect to KMBOXNET in nogui mode")
    return parser.parse_args()


def main() -> None:
    tune_process_for_capture()
    try:
        if relaunch_as_admin_if_needed():
            return
    except Exception:
        pass

    args = parse_args()
    if args.nogui:
        config_dir = app_dir() / "CONFIG"
        settings = Settings(config_dir).load()
        engine = OfficeLogoDragEngine(config_dir, settings, print)
        engine.run(args.execute)
    else:
        NativeApp().run()


if __name__ == "__main__":
    main()
