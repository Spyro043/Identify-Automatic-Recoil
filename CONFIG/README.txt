把文件放在这个目录：

1. 轨迹库固定命名为 1.json
2. 识别图片使用 bmp，例如 1.bmp、2.bmp
3. 图片文件名必须能在 1.json 里找到同名轨迹

示例：
识别到 1.bmp 后，程序会在 1.json 中寻找 key/name/id/image/template 等于 "1" 的轨迹。
