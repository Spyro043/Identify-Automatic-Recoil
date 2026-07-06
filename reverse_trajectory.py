import argparse
import json
from pathlib import Path
from typing import Any


def reverse_step(step: dict[str, Any]) -> dict[str, Any]:
    reversed_step = dict(step)
    if "dx" in reversed_step:
        reversed_step["dx"] = -float(reversed_step["dx"])
    elif "x" in reversed_step:
        reversed_step["dx"] = -float(reversed_step.pop("x"))
    else:
        reversed_step["dx"] = 0

    if "dy" in reversed_step:
        reversed_step["dy"] = -float(reversed_step["dy"])
    elif "y" in reversed_step:
        reversed_step["dy"] = -float(reversed_step.pop("y"))
    else:
        reversed_step["dy"] = 0

    if float(reversed_step["dx"]).is_integer():
        reversed_step["dx"] = int(reversed_step["dx"])
    if float(reversed_step["dy"]).is_integer():
        reversed_step["dy"] = int(reversed_step["dy"])
    return reversed_step


def reverse_path(path: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reverse_step(step) for step in reversed(path)]


def reverse_trajectory(item: dict[str, Any], new_name: str | None = None) -> dict[str, Any]:
    if not isinstance(item.get("path"), list):
        raise ValueError("只支持带 path 数组的录制轨迹 JSON。")
    reversed_item = dict(item)
    if new_name:
        reversed_item["key"] = new_name
        reversed_item["name"] = new_name
    else:
        for field in ("key", "name", "id", "image", "template"):
            if field in reversed_item:
                reversed_item[field] = f"{reversed_item[field]}_reverse"
    reversed_item["path"] = reverse_path(item["path"])
    return reversed_item


def reverse_json(data: Any, new_name: str | None = None) -> Any:
    if isinstance(data, dict):
        return reverse_trajectory(data, new_name)
    if isinstance(data, list):
        if data and all(isinstance(step, dict) and ("dx" in step or "dy" in step or "x" in step or "y" in step) for step in data):
            return reverse_path(data)
        result = []
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("path"), list):
                result.append(reverse_trajectory(item))
        if result:
            return result
    raise ValueError("JSON 格式不支持。请传入 {key,name,path:[...]} 或 path 步骤数组。")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成反向鼠标轨迹 JSON。")
    parser.add_argument("input", nargs="?", help="输入轨迹 JSON 文件。")
    parser.add_argument("output", nargs="?", help="输出 JSON 文件。默认：输入文件名_reverse.json")
    parser.add_argument("--name", help="新的轨迹名，例如 ASD_BACK。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_text = args.input or input("请输入轨迹 JSON 路径：").strip().strip('"')
    input_path = Path(input_text)
    if not input_path.exists():
        raise SystemExit(f"文件不存在：{input_path}")

    output_path = Path(args.output) if args.output else input_path.with_name(f"{input_path.stem}_reverse.json")
    new_name = args.name
    if args.input is None:
        typed_name = input(f"请输入反向轨迹名（留空默认 {output_path.stem}）：").strip()
        new_name = typed_name or output_path.stem

    data = json.loads(input_path.read_text(encoding="utf-8"))
    reversed_data = reverse_json(data, new_name)
    output_path.write_text(json.dumps(reversed_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{output_path}")
    if args.input is None:
        input("按回车退出...")


if __name__ == "__main__":
    main()
