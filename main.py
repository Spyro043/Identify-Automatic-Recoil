import argparse
import ctypes
import json
import math
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import mss
import numpy as np
import vector_compat

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


def bundle_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", app_dir()))


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


class MakcuMouse:
    def __init__(self, port: str, baudrate: int) -> None:
        self.port = port
        self.baudrate = baudrate
        self.serial: Any | None = None

    def connect(self) -> None:
        import serial

        if not self.port.upper().startswith("COM") or not self.port[3:].isdigit():
            raise ValueError("马克盒子串口应填写 COM 号，例如 COM3。")
        if self.baudrate not in (115200, 4000000):
            raise ValueError("马克盒子波特率应为 115200 或 4000000。")
        try:
            self.serial = serial.Serial(self.port, self.baudrate, timeout=1, write_timeout=1)
            self.serial.reset_input_buffer()
            self.serial.write(b".version()\r")
            if b"km." not in self.serial.read_until(b">>> "):
                raise RuntimeError("马克盒子没有响应，请检查 COM 口及设备波特率。")
        except Exception:
            self.close()
            raise

    def right_down(self) -> None:
        pass

    def right_up(self) -> None:
        pass

    def move_relative(self, dx: int, dy: int) -> None:
        if dx or dy:
            self.serial.write(f".move({int(dx)},{int(dy)})\r".encode("ascii"))
            if not self.serial.read_until(b">>> ").endswith(b">>> "):
                raise RuntimeError("马克盒子移动命令无响应，请检查串口连接。")

    def is_left_down(self) -> bool:
        return is_left_down()

    def close(self) -> None:
        if self.serial is not None:
            self.serial.close()
            self.serial = None


class DdMouse:
    def __init__(self, dll_path: str) -> None:
        self.dll_path = dll_path
        self.dll: Any | None = None

    def connect(self) -> None:
        global _DD_DLL, _DD_INITIALIZED
        path = Path(self.dll_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"DD DLL 不存在：{path}")
        if _DD_DLL is None:
            _DD_DLL = ctypes.WinDLL(str(path.resolve()))
            _DD_DLL.DD_btn.argtypes = [ctypes.c_int]
            _DD_DLL.DD_btn.restype = ctypes.c_int
            _DD_DLL.DD_movR.argtypes = [ctypes.c_int, ctypes.c_int]
            _DD_DLL.DD_movR.restype = ctypes.c_int
        self.dll = _DD_DLL
        if not _DD_INITIALIZED and self.dll.DD_btn(0) != 1:
            raise RuntimeError("DD 初始化失败。请检查驱动和授权状态。")
        _DD_INITIALIZED = True

    def right_down(self) -> None:
        pass

    def right_up(self) -> None:
        pass

    def move_relative(self, dx: int, dy: int) -> None:
        if dx or dy:
            if self.dll is None:
                raise RuntimeError("DD 尚未连接")
            self.dll.DD_movR(int(dx), int(dy))

    def is_left_down(self) -> bool:
        return is_left_down()

    def close(self) -> None:
        self.dll = None


_DD_DLL = None
_DD_INITIALIZED = False


def dd_loaded() -> bool:
    return _DD_DLL is not None


def make_mouse(settings: dict[str, Any]) -> KmboxNetMouse | MakcuMouse | DdMouse:
    device = str(settings["device"]).upper()
    if device == "MAKCU":
        return MakcuMouse(str(settings["makcu_port"]), int(settings["makcu_baudrate"]))
    if device == "KMBOXNET":
        return KmboxNetMouse(str(settings["ip"]), str(settings["port"]), str(settings["uid"]))
    if device == "DD":
        bundled = bundle_dir() / "dd" / "dd63330.dll"
        path = bundled if bundled.is_file() else Path(str(settings.get("dd_dll_path") or ""))
        return DdMouse(str(path))
    raise ValueError("设备类型应为 KMBOXNET、MAKCU 或 DD。")


class Settings:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.path = config_dir / "settings.json"
        self.data = {
            "device": "KMBOXNET",
            "ip": "192.168.2.188",
            "uid": "",
            "port": "8338",
            "makcu_port": "COM3",
            "makcu_baudrate": "115200",
            "dd_dll_path": "",
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
            "match_mode": "original",
            "reference_width": 2560,
            "reference_height": 1440,
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
        self.mouse: DryRunMouse | KmboxNetMouse | MakcuMouse | DdMouse | None = None
        self.trajectories: list[dict[str, Any]] = []
        self.templates: list[Template] = []

    def status(self, message: str) -> None:
        self.log("STATUS|" + message)

    def stop(self) -> None:
        self.stop_event.set()

    def run(self, execute: bool) -> None:
        self.templates = load_templates(self.config_dir)
        self.trajectories = load_trajectories(self.config_dir)
        if not execute:
            self.mouse = DryRunMouse()
        else:
            self.mouse = make_mouse(self.settings)
        self.mouse.connect()
        if execute:
            self.log("DEVICE|CONNECTED")
        self.templates = [t for t in self.templates if (p := find_trajectory(self.trajectories, t.key)) and p.get("enabled", True)]
        self.log(f"已加载 {len(self.templates)} 张识别图片，{len(self.trajectories)} 条轨迹。")
        self.status("已启动，等待识别右下角 Logo")

        active_key: str | None = None
        active_steps: list[tuple[int, int, float]] = []
        active_trajectory: dict[str, Any] | None = None
        last_seen = 0.0
        ready_reported = False
        try:
            with ScreenCapture(self.settings, self.log) as capture:
                self.log(f"截图后端：{capture.backend_name}")
                while not self.stop_event.is_set():
                    screen_gray = capture.grab_gray()
                    match = find_best_match(screen_gray, self.templates, self.settings.get("match_mode") == "vector")
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
                                active_trajectory = None
                                self.mouse.right_up()
                            else:
                                active_key = match.template.key
                                active_trajectory = trajectory
                                active_steps = [(0, 0, .01)] if trajectory.get("engine") == "vector_legacy" else build_steps(trajectory, self.settings)
                                ready_reported = False
                                self.log(f"识别到 {match.template.path.name}，匹配分数 {match.score:.3f}，已读取对应轨迹。")
                                self.status(f"已识别 {match.template.path.name}，请按住右键进入待激活")
                    elif active_key and now - last_seen > float(self.settings["lost_after_seconds"]):
                        self.log(f"Logo 消失：{active_key}。")
                        self.status("Logo 消失，等待重新识别")
                        active_key = None
                        active_steps = []
                        active_trajectory = None
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
                        if active_trajectory and active_trajectory.get("engine") == "vector_legacy":
                            vector_compat.play(self.mouse, active_trajectory, self.settings, self.stop_event, lambda: is_right_down() and is_left_down())
                        else:
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
        raw = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
        image = vector_compat.gray(raw) if raw is not None else None
        if image is not None:
            templates.append(Template(key=path.stem, path=path, image_gray=image))
    if not templates:
        raise RuntimeError(f"No bmp templates found in {config_dir}")
    return templates


def load_trajectories(config_dir: Path) -> list[dict[str, Any]]:
    trajectories: list[dict[str, Any]] = []
    paths = sorted(config_dir.glob("*.json"), key=lambda p: (p.name.lower() != "profiles.json", p.name.lower()))
    for path in paths:
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


def capture_region(settings: dict[str, Any], screen_width: int, screen_height: int) -> tuple[int, int, int, int]:
    region = tuple(int(settings[f"region_{side}"]) for side in ("left", "top", "right", "bottom"))
    if settings.get("match_mode") == "vector":
        reference_width = int(settings.get("reference_width", 2560))
        reference_height = int(settings.get("reference_height", 1440))
        if reference_width <= 0 or reference_height <= 0:
            raise RuntimeError("Vector 参考分辨率无效。")
        region = (round(region[0] * screen_width / reference_width),
                  round(region[1] * screen_height / reference_height),
                  round(region[2] * screen_width / reference_width),
                  round(region[3] * screen_height / reference_height))
    left, top, right, bottom = region
    if not (0 <= left < right <= screen_width and 0 <= top < bottom <= screen_height):
        raise RuntimeError(f"识别区域 {region} 超出当前屏幕 {screen_width}x{screen_height}，请调整识别区域。")
    return region


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

        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        self.region = capture_region(self.settings, width, height)
        if self.settings.get("match_mode") == "vector" and (width, height) != (
            int(self.settings.get("reference_width", 2560)), int(self.settings.get("reference_height", 1440))
        ):
            self.log(f"识别区域已适配当前屏幕 {width}x{height}：{self.region}")

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
        return vector_compat.gray(frame) if self.settings.get("match_mode") == "vector" else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def capture_bottom_right(sct: mss.mss, settings: dict[str, Any]) -> np.ndarray:
    monitor = sct.monitors[1]
    width = int(settings["region_width"])
    height = int(settings["region_height"])
    left = monitor["left"] + monitor["width"] - width
    top = monitor["top"] + monitor["height"] - height
    shot = sct.grab({"left": left, "top": top, "width": width, "height": height})
    return cv2.cvtColor(np.asarray(shot), cv2.COLOR_BGRA2GRAY)


def find_best_match(screen_gray: np.ndarray, templates: list[Template], vector_mode: bool = False) -> MatchResult | None:
    best: MatchResult | None = None
    for template in templates:
        th, tw = template.image_gray.shape[:2]
        sh, sw = screen_gray.shape[:2]
        if not vector_mode and (th > sh or tw > sw):
            continue
        if vector_mode:
            score, location = vector_compat.score(screen_gray, template.image_gray), (0, 0)
        else:
            result = cv2.matchTemplate(screen_gray, template.image_gray, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
        if best is None or score > best.score:
            best = MatchResult(template=template, score=float(score), location=location)
    return best


def build_steps(trajectory: dict[str, Any], settings: dict[str, Any]) -> list[tuple[int, int, float]]:
    sensitivity = float(settings.get("sensitivity", 1.0)) * float(trajectory.get("power", 100)) / 100
    x_power = sensitivity * float(trajectory.get("x_power", 100)) / 100
    y_power = sensitivity * float(trajectory.get("y_power", 100)) / 100
    if isinstance(trajectory.get("path"), list):
        return [
            (
                int(round(float(step.get("dx", step.get("x", 0))) * x_power)),
                int(round(float(step.get("dy", step.get("y", 0))) * y_power)),
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
        steps.append((int(round(dx * x_power)), int(round(dy * y_power)), tick))
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


def play_while_buttons_down(mouse: KmboxNetMouse | MakcuMouse | DdMouse | DryRunMouse, steps: list[tuple[int, int, float]], stop_event: threading.Event) -> None:
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

VK_LBUTTON = 0x01
VK_RBUTTON = 0x02


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

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nogui", action="store_true", help="run without UI")
    parser.add_argument("--execute", action="store_true", help="connect to configured device in nogui mode")
    parser.add_argument("--driver", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    tune_process_for_capture()
    args = parse_args()
    if args.nogui:
        config_dir = app_dir() / "CONFIG"
        settings = Settings(config_dir).load()
        if args.execute and settings["device"] == "DD" and not args.driver:
            raise RuntimeError("命令行使用 DD 须显式添加 --driver")
        engine = OfficeLogoDragEngine(config_dir, settings, print)
        engine.run(args.execute)
    else:
        from webui import App

        App(sys.modules[__name__], startup_driver=args.driver).run()


if __name__ == "__main__":
    main()
