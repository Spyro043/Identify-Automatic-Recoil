import time
import tempfile
from pathlib import Path

import main
from ui import App


class FakeMouse:
    def __init__(self, *args):
        self.moves = []
        self.closed = False

    def connect(self):
        pass

    def move_relative(self, dx, dy):
        self.moves.append((dx, dy))

    def close(self):
        self.closed = True


def wait_for(app, condition):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.root.update()
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("UI action timed out")


if __name__ == "__main__":
    main.MakcuMouse = FakeMouse
    with tempfile.TemporaryDirectory() as folder:
        main.app_dir = lambda: Path(folder)
        app = App(main)
        app.vars["device"].set("MAKCU")
        app._device_changed()
        app.connect()
        wait_for(app, lambda: app.status.get() == "连接成功")
        mouse = app.device
        app.test_move()
        wait_for(app, lambda: len(mouse.moves) == 2)
        assert mouse.moves == [(10, 0), (-10, 0)]
        app.close()
        assert mouse.closed
