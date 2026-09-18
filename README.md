# Automatic game recoil identification
# 支持 KMBOXNET 和马克盒子 MAKCU。由于每个人分辨率以及后坐力不同，建议自己配置。
# 理论上适配所有的游戏，但是由于PUBG，以及三角洲为非实时识别游戏，所以后续我会更新一个新版，增加缓存识别功能，来适配PUBG以及三角洲。
BMP目前可以自己截图然后去网上转成BMP，后续我会更新：实现软件内针对对应区域一键截图（因为目前的方式太麻烦了）。软件内可以设置识别区域，不知道自己像素点的，可以看这个网站：https://screencoordinates.com/zh/#:~:text=%E5%AE%9E%E6%97%B6%E8%BF%BD%E8%B8%AA%E9%BC%A0%E6%A0%87%20X%2FY%20%E5%B1%8F%E5%B9%95%E5%9D%90%E6%A0%87%E5%B9%B6%E7%B2%BE%E7%A1%AE%E6%B5%8B%E9%87%8F%E5%83%8F%E7%B4%A0%E4%BD%8D%E7%BD%AE%E3%80%82%20%E5%85%8D%E8%B4%B9%E5%9C%A8%E7%BA%BF%E5%B7%A5%E5%85%B7%EF%BC%8C%E6%97%A0%E9%9C%80%E5%AE%89%E8%A3%85%E3%80%82%20%F0%9F%92%A1%20%E6%8F%90%E7%A4%BA%EF%BC%9A%E5%9C%A8%E6%A1%8C%E9%9D%A2%E6%8C%89%20PrtSc%20%E6%88%AA%E5%9B%BE%EF%BC%8C%E7%84%B6%E5%90%8E%E5%9C%A8%E6%AD%A4%E5%A4%84,%E5%AE%9E%E6%97%B6%E8%BF%BD%E8%B8%AA%20%E9%BC%A0%E6%A0%87%E4%BD%8D%E7%BD%AE%20%E5%B9%B6%E6%B5%8B%E9%87%8F%20%E7%B2%BE%E7%A1%AE%E5%83%8F%E7%B4%A0%E4%BD%8D%E7%BD%AE%E3%80%82%20%E5%89%8D%E7%AB%AF%E5%BC%80%E5%8F%91%E4%BA%BA%E5%91%98%E3%80%81UI%2FUX%20%E8%AE%BE%E8%AE%A1%E5%B8%88%E5%92%8C%20QA%20%E6%B5%8B%E8%AF%95%E4%BA%BA%E5%91%98%E7%9A%84%E5%BF%85%E5%A4%87%E5%B7%A5%E5%85%B7%E3%80%82

用于游戏自动压枪：

1. 使用 DXGI Desktop Duplication 截图识别指定屏幕区域。
2. 识别 `CONFIG` 里的 `.bmp` 图片。
3. 图片名和轨迹名对应，例如 `ASD.bmp` 对应 `ASD.json` 或轨迹里的 `key/name == "ASD"`。
4. 识别成功后，等待你自己按住右键进入待激活。
5. 右键按住期间，再按住左键，程序通过所选设备执行轨迹。
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

主界面分为“设备与运行”和“识别与轨迹设置”两页。先从下拉框选择 `KMBOXNET` 或 `MAKCU`，填写对应参数并点击“连接设备”；状态会显示连接成功或失败。连接成功后可填入 X/Y 位移，点击“测试移动并返回”。运行时点击“停止”，关闭程序可点右上角“退出程序”、窗口关闭按钮，或按 `Esc`。

可以填写：

- `IP`
- `UID`
- `PORT`
- 设备类型：`KMBOXNET` 或 `MAKCU`
- 马克 COM 口（例如 `COM3`）
- 马克波特率（`115200` 或 `4000000`，须与设备当前波特率一致）
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

选择 `KMBOXNET` 时，`IP / UID / PORT` 用于 `kmNet.init(ip, port, uid)`。选择 `MAKCU` 时，连接马克盒子 USB 2 对应的 COM 口；`IP / UID / PORT` 不参与连接。左右键状态由 Windows 本机检测，不使用设备按键监听。马克盒子使用 [官方传统 ASCII API](https://makcu.com/cn/api/) 的 `.version()` 和 `.move(dx,dy)` 命令。打开设备管理器查看 COM 口；若连接后无响应，请检查实际波特率。

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

使用 Python 3.12（仓库内的 `kmNet.cp312-win_amd64.pyd` 仅兼容该版本），先安装 `requirements.txt`。打包脚本会把 `pyserial` 一起打入主程序。

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
