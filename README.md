# Automatic game recoil identification

用于游戏自动压枪：

1. 使用 DXGI Desktop Duplication 截图识别指定屏幕区域。
2. 识别 `CONFIG` 里的 `.bmp` 图片。
3. 图片名和轨迹名对应，例如 `ASD.bmp` 对应 `ASD.json` 或轨迹里的 `key/name == "ASD"`。
4. 识别成功后，等待你自己按住右键进入待激活。
5. 右键按住期间，再按住左键，程序通过 KMBOXNET 执行轨迹。
6. 松开左键或右键，轨迹立即停止。

## CONFIG 规则

推荐结构：

```text
OfficeLogoDrag.exe
CONFIG/
  ASD.bmp
  ASD.json
  ASD_back.bmp
  ASD_back.json
  1.json
```

`1.json` 仍兼容旧的总轨迹库；同时程序会读取 `CONFIG` 下所有 `.json` 轨迹文件，自动跳过 `settings.json`。

单独轨迹文件示例：

```json
{
  "key": "ASD",
  "name": "ASD",
  "path": [
    { "dx": 2, "dy": 0, "delay": 0.01 },
    { "dx": 2, "dy": 1, "delay": 0.01 }
  ]
}
```

## UI 配置

可以填写：

- `IP`
- `UID`
- `PORT`
- 匹配阈值
- 识别区域坐标：左X、上Y、右X、下Y
- 轨迹缩放
- 灵敏度
- 轨迹间隔 ms

默认识别区域：

```text
左X=1518
上Y=926
右X=1871
下Y=1032
```

`IP / UID / PORT` 用于 `kmNet.init(ip, port, uid)`。左右键状态由 Windows 本机检测，不使用 `kmNet.monitor()`。

截图固定使用 DXGI，不回退 MSS。若 DXGI 持续无画面，程序会自动重启 DXGI 截图器。

## 鼠标轨迹录制

在“轨迹录制”里填写轨迹名，例如：

```text
ASD
```

点击“开始录制”后，按住左键拖动鼠标，松开左键自动保存为：

```text
CONFIG/ASD.json
```

录制功能只会写对应的单独轨迹文件，不会覆盖 `CONFIG/1.json`。

## 反向轨迹工具

另有一个小工具：

```text
ReverseTrajectory.exe
```

用法：

1. 双击后输入轨迹 JSON 路径。
2. 或把 JSON 文件拖到 EXE 上。
3. 默认生成 `原文件名_reverse.json`。

反向规则：`path` 倒序，并且每一步 `dx/dy` 取反。

## 打包

```powershell
cd "C:\Users\13284\Documents\New project\office-logo-drag"
.\build_exe.bat
```

主程序：

```text
dist/OfficeLogoDrag/OfficeLogoDrag.exe
```

反向工具：

```text
dist/ReverseTrajectory/ReverseTrajectory.exe
```
