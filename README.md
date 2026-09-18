# 自动识别压枪控制台

Windows 桌面程序，在独立窗口中显示 WebUI，不会打开浏览器。支持 KMBOXNET、马克盒子 MAKCU 和本机 DD 驱动。

## 启动

双击 `OfficeLogoDrag.exe`，在软件窗口中选择：

- **内核驱动**：便携版 EXE 内含本机已授权的 `dd63330.dll`，选择后尝试连接并初始化 DD。
- **硬件设备**：再选 KMBOXNET 或 MAKCU。此模式不加载 DD DLL。

连接成功后可测试移动，确认鼠标实际移动。然后启动识别；识别到模板图案时，按住右键和左键执行对应轨迹。“试运行”只识别、不发送移动。窗口右上角有“退出程序”，关闭软件窗口也会结束程序。

DD DLL 在进程内保持加载，选择过内核模式后若要保证纯硬件运行，请退出并重新打开 EXE，再选择硬件模式。

## 模板

在 WebUI 中点击“导入本机 Vector 模板”，选择已购买软件的根目录。程序读取 `config/weapons.json`，并把 `ModPic/<分辨率>/*.bmp` 复制到本机 `CONFIG`。每个模板可分别调总力度、水平/垂直力度、下压力度、持续时间、延迟、初始下压及分段方向和强度。识别图片必须与模板 `key` 同名。缺图模板会在列表标示，需自行提供对应 BMP。编辑后重启识别生效。

导入同时读取 Vector 的识别区域、匹配阈值、检测间隔和全局力度；Vector 模板使用整块 ROI 的组合评分以及 `legacy` 轨迹参数（`level`、`frequency`、`decline`、`initial_drop`、`adjustments`）。原项目自己的逐步 `path` 轨迹仍可用。图像缩放及随机数的底层实现与 Vector 进程不同，实际识别和位移仍应在目标分辨率上测试后微调。

本机导入的 `CONFIG/profiles.json` 和 BMP 不提交到 GitHub。便携版首次启动会从 EXE 内的本机模板自动提取到旁边的 `CONFIG`，后续编辑不会被覆盖。仓库不包含第三方 WebUI 源码或 DD 二进制。

## 构建

使用 Python 3.12，因为仓库中的 `kmNet.cp312-win_amd64.pyd` 绑定该版本：

```powershell
python -m pip install -r requirements.txt
.\build_exe.bat
```

主程序在 `dist/OfficeLogoDrag/OfficeLogoDrag.exe`，同目录的 `WEBUI` 和 `CONFIG` 文件夹要一同保留。`--nogui` 可以从命令行运行识别；加 `--execute` 才向配置的设备发送移动。

需要单 EXE 时，用 `python build_portable.py`。脚本会从本机已购买的 Vector 目录读取 DD DLL 和模板，构建 `dist/OfficeLogoDrag-Desktop-v2.exe`；这个 EXE 仅供授权范围内使用。运行后可编辑的数据会存放在 EXE 旁边的 `CONFIG`。Vector 导入的识别区域会按当前屏幕分辨率自动换算。
