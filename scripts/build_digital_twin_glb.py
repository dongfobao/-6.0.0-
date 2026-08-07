"""将本地单管吸湿器 STL 总装导出为 Web 可加载的 GLB。

本脚本仅读取 ``3D数字孪生资料`` 内的源模型，产物写入前端静态目录。
STL 已保留总装坐标，因此逐件导入后不重新装配。
"""
from __future__ import annotations

from pathlib import Path

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "3D数字孪生资料" / "05_模型源文件_如有" / "吸湿器5.0(1)"
OUTPUT_PATH = ROOT / "app" / "web" / "assets" / "yldq-5-single-pipe.glb"
SCALE = 0.008


def make_material(name: str, color: tuple[float, float, float, float], metallic: float = 0.0, roughness: float = 0.55) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        if color[3] < 1:
            bsdf.inputs["Alpha"].default_value = color[3]
            material.surface_render_method = "DITHERED"
    return material


MATERIALS = {
    "metal": make_material("金属外壳", (0.31, 0.41, 0.49, 1.0), 0.75, 0.3),
    "valve": make_material("阀门与传感器", (0.06, 0.16, 0.27, 1.0), 0.7, 0.28),
    "glass": make_material("透明观察件", (0.16, 0.75, 0.72, 0.22), 0.05, 0.1),
    "silica": make_material("干燥剂", (0.28, 0.66, 0.47, 0.58), 0.05, 0.62),
    "heater": make_material("加热组件", (0.57, 0.22, 0.08, 1.0), 0.6, 0.35),
    "plastic": make_material("绝缘结构件", (0.62, 0.40, 0.20, 1.0), 0.05, 0.55),
}


def choose_style(filename: str) -> tuple[str, str]:
    if any(word in filename for word in ("玻璃", "透明", "观察罐", "罩子")):
        return "glass", "outer_shell"
    if any(word in filename for word in ("硅胶", "干燥剂")):
        return "silica", "desiccant"
    if any(word in filename for word in ("电磁阀", "阀主体", "压力", "流量", "温湿度", "传感器")):
        return "valve", "valve_or_sensor"
    if any(word in filename for word in ("三脚架", "金属网", "顶起板", "圆顶")):
        return "heater", "heater_frame"
    if any(word in filename for word in ("橡胶", "塑料", "盒子")):
        return "plastic", "support"
    return "metal", "structure"


def world_bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    return (
        Vector((min(point[i] for point in points) for i in range(3))),
        Vector((max(point[i] for point in points) for i in range(3))),
    )


def main() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    imported: list[bpy.types.Object] = []
    sources = sorted(SOURCE_DIR.rglob("*.STL"))
    if not sources:
        raise RuntimeError(f"未找到 STL 源文件：{SOURCE_DIR}")

    for index, source in enumerate(sources, start=1):
        before = set(bpy.context.scene.objects)
        bpy.ops.wm.stl_import(filepath=str(source))
        created = [obj for obj in set(bpy.context.scene.objects) - before if obj.type == "MESH"]
        style, role = choose_style(source.stem)
        for object_index, obj in enumerate(created, start=1):
            obj.name = f"component_{index:02d}_{object_index}_{role}"
            obj["source_file"] = source.name
            obj["digital_twin_role"] = role
            obj.data.materials.clear()
            obj.data.materials.append(MATERIALS[style])
            imported.append(obj)

    low, high = world_bounds(imported)
    center = (low + high) / 2
    offset = Vector((-center.x, -center.y, -low.z))
    # 先减去 CAD 原点，再统一缩放；矩阵从右向左应用。
    model_transform = Matrix.Diagonal((SCALE, SCALE, SCALE, 1.0)) @ Matrix.Translation(offset)
    for obj in imported:
        # 有些 STL 的总装位置在 object.matrix_world，有些在顶点坐标中。
        # 统一先应用其世界矩阵，再做总装归一化，不能直接丢弃 object location。
        obj.data.transform(model_transform @ obj.matrix_world)
        obj.location = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)

    # STL 通常保留了大量重复小面。仅对超大零件做温和简化，保证装配轮廓。
    for obj in imported:
        if len(obj.data.polygons) > 18_000:
            modifier = obj.modifiers.new("Web 网格简化", "DECIMATE")
            modifier.ratio = 0.58
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        for polygon in obj.data.polygons:
            polygon.use_smooth = True

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(OUTPUT_PATH),
        export_format="GLB",
        use_selection=True,
        export_materials="EXPORT",
        export_extras=True,
        export_apply=True,
    )
    print(f"已导出 {len(imported)} 个零件到 {OUTPUT_PATH}，模型尺寸约 {((high - low) * SCALE)[:]}")


if __name__ == "__main__":
    main()
