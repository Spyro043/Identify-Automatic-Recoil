import sys
from types import SimpleNamespace

from main import MakcuMouse


class FakeSerial:
    def __init__(self, port, baudrate, timeout, write_timeout):
        self.writes = []
        self.closed = False

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.writes.append(data)

    def read_until(self, marker):
        return b"km.version(3.9)\r\n>>> " if len(self.writes) == 1 else b"km.move(2,-3)\r\n>>> "

    def close(self):
        self.closed = True


def test_makcu_commands():
    fake = FakeSerial("COM3", 115200, 1, 1)
    sys.modules["serial"] = SimpleNamespace(Serial=lambda *args, **kwargs: fake)
    mouse = MakcuMouse("COM3", 115200)
    mouse.connect()
    mouse.move_relative(0, 0)
    mouse.move_relative(2, -3)
    mouse.close()
    assert fake.writes == [b".version()\r", b".move(2,-3)\r"]
    assert fake.closed


if __name__ == "__main__":
    test_makcu_commands()
