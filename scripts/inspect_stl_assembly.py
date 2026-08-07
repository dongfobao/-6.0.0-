"""仅检查本地 STL 零件是否保留了总装坐标，不写入源资料。"""

from __future__ import annotations

import json
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "3D数字孪生资料" / "05_模型源文件_如有" / "吸湿器5.0(1)"


def bounds(objects: list[bpy.types.Object]) -> dict[str, list[float]]:
    points: list[Vector] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points:
        return {"min": [0, 0, 0], "max": [0, 0, 0], "size": [0, 0, 0]}
    low = [min(point[index] for point in points) for index in range(3)]
    high = [max(point[index] for point in points) for index in range(3)]
    return {"min": low, "max": high, "size": [high[index] - low[index] for index in range(3)]}


for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

imported: list[bpy.types.Object] = []
for source in sorted(SOURCE_DIR.rglob("*.STL")):
    before = set(bpy.context.scene.objects)
    bpy.ops.wm.stl_import(filepath=str(source))
    for obj in set(bpy.context.scene.objects) - before:
        obj.name = source.stem[:60]
        imported.append(obj)

payload = {
    "files": len(list(SOURCE_DIR.rglob("*.STL"))),
    "objects": len(imported),
    "bounds": bounds(imported),
}
print(json.dumps(payload, ensure_ascii=False))
