import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk


class App:
    def __init__(self, core):
        self.core = core
        self.config_dir = core.app_dir() / "CONFIG"
        self.store = core.Settings(self.config_dir)
        self.settings = self.store.load()
        self.root = tk.Tk()
        self.vars = {key: tk.StringVar(value=str(value)) for key, value in self.settings.items()}
        self.vars["record_name"] = tk.StringVar()
        self.vars["test_x"] = tk.StringVar(value="10")
        self.vars["test_y"] = tk.StringVar(value="0")
        self.events = queue.Queue()
        self.device = None
        self.engine = None
        self.worker = None
        self.record_worker = None
        self.busy = False

        self.root.title("自动压枪 · 设备控制台")
        self.root.geometry("900x760")
        self.root.minsize(790, 690)
        self.root.configure(bg="#0b1220")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Escape>", lambda _: self.close())
        self.status = tk.StringVar(value="未连接")
        self._style()
        self._build()
        self._device_changed()
        self.refresh_files()
        self.log("就绪。先选择设备并连接，再测试移动或启动识别。")
        self.root.after(100, self._drain)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TNotebook", background="#0b1220", borderwidth=0)
        style.configure("TNotebook.Tab", background="#192538", foreground="#b9c6d7", padding=(22, 10), font=("Microsoft YaHei UI", 10))
        style.map("TNotebook.Tab", background=[("selected", "#29415c")], foreground=[("selected", "#ffffff")])
        style.configure("Device.TCombobox", fieldbackground="#18263a", background="#18263a", foreground="#ffffff", arrowcolor="#ffffff", padding=6)
        style.map("Device.TCombobox", fieldbackground=[("readonly", "#18263a")], foreground=[("readonly", "#ffffff")])

    def _label(self, parent, text, size=10, color="#b9c6d7", bold=False, **pack):
        widget = tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                          font=("Microsoft YaHei UI", size, "bold" if bold else "normal"), anchor="w")
        widget.pack(**pack)
        return widget

    def _card(self, parent, title, subtitle=None):
        outer = tk.Frame(parent, bg="#172338", padx=20, pady=16)
        outer.pack(fill="x", pady=(0, 14))
        self._label(outer, title, 13, "#ffffff", True, pady=(0, 4))
        if subtitle:
            self._label(outer, subtitle, 9, "#8394aa", pady=(0, 12))
        return outer

    def _field(self, parent, title, key, width=16):
        cell = tk.Frame(parent, bg=parent["bg"])
        cell.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self._label(cell, title, 9, pady=(0, 5))
        entry = tk.Entry(cell, textvariable=self.vars[key], width=width, bg="#0e1a2c", fg="#ffffff",
                         insertbackground="#ffffff", relief="flat", font=("Microsoft YaHei UI", 10))
        entry.pack(fill="x", ipady=7)
        return entry

    def _button(self, parent, title, command, primary=False):
        button = tk.Button(parent, text=title, command=command, bg="#258bda" if primary else "#263a53",
                           fg="#ffffff", activebackground="#3b9fea", activeforeground="#ffffff",
                           relief="flat", padx=15, pady=8, cursor="hand2", font=("Microsoft YaHei UI", 10, "bold"))
        button.pack(side="left", padx=(0, 9))
        return button

    def _build(self):
        shell = tk.Frame(self.root, bg="#0b1220", padx=24, pady=18)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg="#0b1220")
        header.pack(fill="x", pady=(0, 16))
        self._label(header, "自动压枪控制台", 20, "#ffffff", True, side="left")
        self._button(header, "退出程序", self.close).pack_configure(side="right", padx=0)

        tabs = ttk.Notebook(shell)
        tabs.pack(fill="both", expand=True)
        def scroll_tab(title):
            panel = tk.Frame(tabs, bg="#0b1220")
            canvas = tk.Canvas(panel, bg="#0b1220", highlightthickness=0)
            scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            scrollbar.pack(side="right", fill="y")
            canvas.pack(side="left", fill="both", expand=True)
            content = tk.Frame(canvas, bg="#0b1220", padx=3, pady=16)
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind("<Configure>", lambda _: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
            tabs.add(panel, text=title)
            return content, canvas

        dashboard, dashboard_canvas = scroll_tab("设备与运行")
        settings_tab, settings_canvas = scroll_tab("识别与轨迹设置")
        tabs.bind_all("<MouseWheel>", lambda event: (dashboard_canvas if tabs.index(tabs.select()) == 0 else settings_canvas).yview_scroll(-int(event.delta / 120), "units"))

        card = self._card(dashboard, "01  连接设备", "选择设备后只显示对应的连接参数。连接成功后可先做小幅移动测试。")
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x", pady=(0, 12))
        selector = tk.Frame(row, bg=row["bg"])
        selector.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self._label(selector, "设备类型", 9, pady=(0, 5))
        self.device_select = ttk.Combobox(selector, textvariable=self.vars["device"], values=("KMBOXNET", "MAKCU"), state="readonly", style="Device.TCombobox")
        self.device_select.pack(fill="x")
        self.device_select.bind("<<ComboboxSelected>>", lambda _: self._device_changed())
        self._label(row, "连接状态", 9, side="left", padx=(10, 8))
        self.status_label = tk.Label(row, textvariable=self.status, bg="#344154", fg="#ffffff", padx=12, pady=7,
                                     font=("Microsoft YaHei UI", 10, "bold"))
        self.status_label.pack(side="left")
        self.connection_fields = tk.Frame(card, bg=card["bg"])
        self.connection_fields.pack(fill="x", pady=(0, 14))
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x")
        self.connect_button = self._button(row, "连接设备", self.connect, True)
        self.disconnect_button = self._button(row, "断开连接", self.disconnect)

        card = self._card(dashboard, "02  自动识别与压枪", "将同名 BMP 图片和轨迹 JSON 放入 CONFIG，连接后启动。按住右键再按左键执行轨迹。")
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x")
        self._button(row, "保存配置", self.save_settings)
        self._button(row, "试运行", lambda: self.start(False))
        self._button(row, "启动压枪", lambda: self.start(True), True)
        self._button(row, "停止", self.stop)
        self._button(row, "打开 CONFIG", self.open_config)

        card = self._card(dashboard, "03  测试移动", "测试时鼠标会移动指定距离，随后返回。请先连接设备。")
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x", pady=(0, 12))
        self._field(row, "水平 X", "test_x")
        self._field(row, "垂直 Y", "test_y")
        self.test_button = self._button(card, "测试移动并返回", self.test_move)

        card = self._card(dashboard, "运行状态与日志")
        self.detail = self._label(card, "等待操作", 10, "#66c6ff", pady=(0, 9))
        self.log_box = tk.Text(card, height=7, bg="#0e1a2c", fg="#cbd7e5", insertbackground="#ffffff",
                               relief="flat", state="disabled", font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)

        card = self._card(settings_tab, "识别区域", "填写屏幕坐标：左上角和右下角。")
        for fields in (("左 X", "region_left", "上 Y", "region_top"), ("右 X", "region_right", "下 Y", "region_bottom")):
            row = tk.Frame(card, bg=card["bg"])
            row.pack(fill="x", pady=(0, 10))
            self._field(row, fields[0], fields[1])
            self._field(row, fields[2], fields[3])
        card = self._card(settings_tab, "匹配与轨迹")
        for fields in (("匹配阈值", "threshold", "轨迹缩放", "scale"), ("轨迹间隔 ms", "tick_ms", "灵敏度", "sensitivity")):
            row = tk.Frame(card, bg=card["bg"])
            row.pack(fill="x", pady=(0, 10))
            self._field(row, fields[0], fields[1])
            self._field(row, fields[2], fields[3])
        self._button(card, "保存配置", self.save_settings, True)
        card = self._card(settings_tab, "轨迹录制", "填写轨迹名，点击开始录制；按住左键拖动，松开后自动保存。")
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x")
        self._field(row, "轨迹名", "record_name")
        self._button(row, "开始录制", self.start_recording)
        card = self._card(settings_tab, "CONFIG 文件")
        self.files_label = self._label(card, "", 9, "#cbd7e5", pady=(0, 10))
        row = tk.Frame(card, bg=card["bg"])
        row.pack(fill="x")
        self._button(row, "刷新文件", self.refresh_files)
        self._button(row, "打开文件夹", self.open_config)

    def _device_changed(self):
        if self.busy:
            return
        if self.device:
            self.disconnect()
        for child in self.connection_fields.winfo_children():
            child.destroy()
        row = tk.Frame(self.connection_fields, bg=self.connection_fields["bg"])
        row.pack(fill="x")
        if self.vars["device"].get() == "MAKCU":
            self._field(row, "COM 串口", "makcu_port")
            self._field(row, "波特率 115200 / 4000000", "makcu_baudrate")
        else:
            for title, key in (("IP 地址", "ip"), ("端口", "port"), ("UID", "uid")):
                self._field(row, title, key)

    def _read_settings(self):
        values = {key: self.vars[key].get().strip() for key in self.settings}
        for key in ("threshold", "scale", "sensitivity"):
            values[key] = float(values[key])
        for key in ("region_left", "region_top", "region_right", "region_bottom", "tick_ms"):
            values[key] = int(values[key])
        if values["region_right"] <= values["region_left"] or values["region_bottom"] <= values["region_top"]:
            raise ValueError("识别区域的右/下坐标必须大于左/上坐标。")
        return values

    def save_settings(self):
        try:
            self.settings = self._read_settings()
            self.store.save(self.settings)
            self.log("配置已保存。")
            return True
        except Exception as exc:
            self.error(str(exc))
            return False

    def _make_mouse(self):
        if self.settings["device"] == "MAKCU":
            return self.core.MakcuMouse(self.settings["makcu_port"], int(self.settings["makcu_baudrate"]))
        return self.core.KmboxNetMouse(self.settings["ip"], self.settings["port"], self.settings["uid"])

    def connect(self):
        if self.busy or (self.worker and self.worker.is_alive()):
            return
        if not self.save_settings():
            return
        self.disconnect()
        self.busy = True
        self.device_select.configure(state="disabled")
        self._connection_status("连接中…", "#935f20")

        def work():
            mouse = None
            try:
                mouse = self._make_mouse()
                mouse.connect()
                self.events.put(("connected", mouse))
            except Exception as exc:
                if mouse:
                    mouse.close()
                self.events.put(("connection_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def disconnect(self):
        if self.busy:
            return
        if self.device:
            self.device.close()
            self.device = None
        self._connection_status("未连接", "#344154")

    def _connection_status(self, message, color):
        self.status.set(message)
        self.status_label.configure(bg=color)

    def test_move(self):
        if self.busy or not self.device or (self.worker and self.worker.is_alive()):
            self.error("请先连接设备，并停止正在运行的压枪任务。")
            return
        try:
            dx, dy = int(self.vars["test_x"].get()), int(self.vars["test_y"].get())
            if not (dx or dy) or max(abs(dx), abs(dy)) > 100:
                raise ValueError("测试移动请输入 -100 到 100 的非零距离。")
        except ValueError as exc:
            self.error(str(exc))
            return
        self.busy = True
        self.device_select.configure(state="disabled")
        self.detail.configure(text="正在测试移动…")

        def work():
            try:
                self.device.move_relative(dx, dy)
                time.sleep(0.25)
                self.device.move_relative(-dx, -dy)
                self.events.put(("test_ok", f"测试成功：({dx}, {dy})，已发送返回移动。"))
            except Exception as exc:
                self.events.put(("test_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def start(self, execute):
        if self.busy or (self.worker and self.worker.is_alive()):
            self.error("任务仍在运行，请先停止。")
            return
        if not self.save_settings():
            return
        self.disconnect()
        self.engine = self.core.OfficeLogoDragEngine(self.config_dir, self.settings, self.log)
        engine = self.engine
        self.detail.configure(text="启动中…")

        def work():
            try:
                engine.run(execute)
            except Exception as exc:
                self.log(f"错误：{exc}")
                self.log("STATUS|" + f"错误：{exc}")
            finally:
                self.events.put(("finished", engine))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.log("正在启动压枪任务。" if execute else "试运行已启动，不向设备发送移动。")

    def stop(self):
        if self.engine:
            self.engine.stop()
            self.log("正在停止任务。")
            self.detail.configure(text="正在停止…")

    def refresh_files(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        bmps = sorted(p.name for p in self.config_dir.glob("*.bmp"))
        jsons = sorted(p.name for p in self.config_dir.glob("*.json") if p.name.lower() != "settings.json")
        self.files_label.configure(text=f"轨迹 JSON：{', '.join(jsons) or '暂无'}\n识别 BMP：{', '.join(bmps) or '暂无'}")

    def open_config(self):
        self.config_dir.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(self.config_dir)

    def start_recording(self):
        if self.record_worker and self.record_worker.is_alive():
            return
        name = self.vars["record_name"].get().strip()
        if not name:
            self.error("请填写轨迹名。")
            return
        self.record_worker = threading.Thread(target=self._record, args=(name,), daemon=True)
        self.record_worker.start()

    def _record(self, name):
        try:
            self.log(f"等待左键开始录制：{name}")
            while self.root.winfo_exists() and not self.core.is_left_down():
                time.sleep(0.005)
            previous_x, previous_y = self.core.get_cursor_pos()
            previous_time = time.perf_counter()
            steps = []
            while self.core.is_left_down():
                time.sleep(0.005)
                x, y = self.core.get_cursor_pos()
                now = time.perf_counter()
                if x != previous_x or y != previous_y:
                    steps.append({"dx": x - previous_x, "dy": y - previous_y, "delay": round(max(0.001, now - previous_time), 4)})
                    previous_x, previous_y, previous_time = x, y, now
            if steps:
                path = self.core.export_recorded_trajectory(self.config_dir, name, steps)
                self.log(f"录制完成：{path.name}，共 {len(steps)} 步。")
                self.events.put(("refresh", None))
            else:
                self.log("录制取消：没有鼠标移动。")
        except Exception as exc:
            self.log(f"录制错误：{exc}")

    def log(self, message):
        kind = "connected_running" if message == "DEVICE|CONNECTED" else "status" if message.startswith("STATUS|") else "log"
        self.events.put((kind, message))

    def _drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", f"[{time.strftime('%H:%M:%S')}] {value}\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "status":
                    self.detail.configure(text=value.removeprefix("STATUS|"))
                elif kind == "connected_running":
                    self._connection_status("已连接 · 运行中", "#176b54")
                elif kind == "connected":
                    self.device = value
                    self.busy = False
                    self.device_select.configure(state="readonly")
                    self._connection_status("连接成功", "#176b54")
                    self.log(f"{self.settings['device']} 连接成功。")
                elif kind == "connection_error":
                    self.busy = False
                    self.device_select.configure(state="readonly")
                    self._connection_status("连接失败", "#913b48")
                    self.error(value)
                elif kind == "test_ok":
                    self.busy = False
                    self.device_select.configure(state="readonly")
                    self.detail.configure(text=value)
                    self.log(value)
                elif kind == "test_error":
                    self.busy = False
                    self.device_select.configure(state="readonly")
                    self.disconnect()
                    self.error(value)
                elif kind == "finished":
                    if value is self.engine:
                        self.engine = None
                        self._connection_status("任务已停止", "#344154")
                        self.log("任务已停止。")
                elif kind == "refresh":
                    self.refresh_files()
        except queue.Empty:
            pass
        self.root.after(100, self._drain)

    def error(self, message):
        self.log("错误：" + message)
        messagebox.showerror("自动压枪控制台", message, parent=self.root)

    def close(self):
        if self.engine:
            self.engine.stop()
        if self.device:
            self.device.close()
            self.device = None
        self.root.destroy()

    def run(self):
        self.root.mainloop()
