"""将带中文部件名的双通道 STL 总装导出为 Web 可加载的 GLB。

源 STL 由带中文部件名的 STEP 总装导出，每个连通实体保留总装坐标。
脚本只读取源资料，不改写 CAD 源文件。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE_STL = ROOT / "3D数字孪生资料" / "05_模型源文件_如有" / "双筒吸湿器2有名字.stl"
OUTPUT = ROOT / "app" / "web" / "assets" / "yldq-5-double-pipe.glb"
SCALE = 0.008

ROLE_MATERIAL = {
    "structure": 0,
    "valve_or_sensor": 1,
    "heater_frame": 2,
    "support": 3,
    "desiccant": 4,
    "outer_shell": 5,
}


def align4(data: bytes, padding: bytes = b"\x00") -> bytes:
    return data + padding * ((-len(data)) % 4)


def read_binary_stl(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    raw = path.read_bytes()
    if len(raw) < 84:
        raise RuntimeError(f"STL 文件过短：{path}")
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    if len(raw) != 84 + triangle_count * 50:
        raise RuntimeError(f"仅支持 SolidWorks 导出的二进制 STL：{path}")
    triangle_dtype = np.dtype(
        [("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")]
    )
    triangles = np.frombuffer(raw, dtype=triangle_dtype, count=triangle_count, offset=84)
    return triangles["vertices"], triangles["normal"], triangles["attribute"]


def split_triangle_components(vertices: np.ndarray, attributes: np.ndarray) -> list[np.ndarray]:
    """按共享顶点拆分 STL 实体，同时使用颜色属性避免接触零件被粘连。"""
    flat = vertices.reshape(-1, 3)
    quantized = np.rint(flat * 10000).astype(np.int64)
    color_key = np.repeat(attributes.astype(np.int64), 3)[:, None]
    keys = np.concatenate((quantized, color_key), axis=1)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    triangle_vertices = inverse.reshape(-1, 3)
    triangle_count = len(vertices)
    parent = np.arange(triangle_count, dtype=np.int32)
    rank = np.zeros(triangle_count, dtype=np.uint8)
    first_triangle = np.full(int(inverse.max()) + 1, -1, dtype=np.int32)

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = int(parent[index])
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        if rank[left_root] < rank[right_root]:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root
        if rank[left_root] == rank[right_root]:
            rank[left_root] += 1

    for triangle_index, vertex_ids in enumerate(triangle_vertices):
        for vertex_id in vertex_ids:
            previous = int(first_triangle[vertex_id])
            if previous < 0:
                first_triangle[vertex_id] = triangle_index
            else:
                union(triangle_index, previous)
    roots = np.fromiter((find(index) for index in range(triangle_count)), dtype=np.int32, count=triangle_count)
    order = np.argsort(roots, kind="stable")
    boundaries = np.flatnonzero(np.diff(roots[order])) + 1
    groups = [group for group in np.split(order, boundaries) if len(group) >= 4]
    groups.sort(key=lambda group: int(group.min()))
    return groups


def materials() -> list[dict[str, Any]]:
    return [
        {"name": "金属结构", "pbrMetallicRoughness": {"baseColorFactor": [0.34, 0.43, 0.50, 1], "metallicFactor": 0.86, "roughnessFactor": 0.24}},
        {"name": "阀门与传感器", "pbrMetallicRoughness": {"baseColorFactor": [0.12, 0.34, 0.48, 1], "metallicFactor": 0.76, "roughnessFactor": 0.20}},
        {"name": "加热组件", "pbrMetallicRoughness": {"baseColorFactor": [0.55, 0.24, 0.09, 1], "metallicFactor": 0.68, "roughnessFactor": 0.29}},
        {"name": "支撑与绝缘件", "pbrMetallicRoughness": {"baseColorFactor": [0.42, 0.48, 0.53, 1], "metallicFactor": 0.40, "roughnessFactor": 0.44}},
        {"name": "干燥剂", "pbrMetallicRoughness": {"baseColorFactor": [0.22, 0.66, 0.48, 0.24], "metallicFactor": 0.04, "roughnessFactor": 0.62}, "alphaMode": "BLEND", "doubleSided": True},
        {"name": "透明观察件", "pbrMetallicRoughness": {"baseColorFactor": [0.22, 0.76, 0.82, 0.14], "metallicFactor": 0.03, "roughnessFactor": 0.08}, "alphaMode": "BLEND", "doubleSided": True},
    ]


def classify_part(low: np.ndarray, high: np.ndarray) -> tuple[str, str | None, int | None]:
    """依据总装坐标与外形标注可动作部件。

    源 RAR 中的中文文件名不含 Unicode 编码声明，因此这里不把文件名
    当作业务标识，避免受 Windows 系统代码页影响。
    """
    size = high - low
    center = (low + high) / 2
    sx, sy, sz = (float(value) for value in size)
    cx, cy, cz = (float(value) for value in center)
    # 统一以人站在设备正面、面对控制盒为观察基准。当前三维相机看到的是
    # 控制盒背向视角，因此模型画面左右与人员面对控制盒时左右镜像：源模型
    # X=-63.37 mm 的画面左筒是右路（通道 2），X=136.63 mm 的画面右筒
    # 才是左路（通道 1）。协议仍保持 T1/HTC1/左排水阀=左路，
    # T2/HTC2/右排水阀=右路。
    channel = 2 if abs(cx + 63.37) <= abs(cx - 136.63) else 1

    cylindrical = abs(sx - sy) <= 8
    # 中文 STEP 中的右玻璃罩、上变色硅胶罩、油杯，以及传感器仓外壳。
    main_glass = cylindrical and 172 <= sx <= 188 and 250 <= sz <= 270
    upper_glass = cylindrical and 172 <= sx <= 188 and 105 <= sz <= 120
    upper_desiccant_cover = cylindrical and 172 <= sx <= 188 and 55 <= sz <= 70 and cz < -120
    oil_cup = cylindrical and 70 <= sx <= 80 and 75 <= sz <= 85 and cz > 300
    sensor_chamber_shell = 108 <= sx <= 120 and 108 <= sy <= 120 and 48 <= sz <= 60 and cz < -120
    if oil_cup:
        return "outer_shell", f"oil_cup_{channel}", channel
    if sensor_chamber_shell:
        return "outer_shell", "sensor_chamber_shell", None
    if upper_glass:
        return "outer_shell", "central_upper_desiccant_chamber", None
    if main_glass:
        return "outer_shell", f"main_process_glass_{channel}", channel
    if upper_desiccant_cover:
        return "outer_shell", "transparent_process_shell", None
    # 中文 STEP 中“呼吸传感器:1”的实体。旁边较小的圆件是通气孔，
    # 流量标签必须锚定传感器本体，不能锚定通气孔或连接管道。
    flow_sensor = (
        35 <= sx <= 45
        and 55 <= sy <= 68
        and 32 <= sz <= 42
        and -20 <= cx <= 0
        and 35 <= cy <= 60
        and cz <= -130
    )
    if flow_sensor:
        return "valve_or_sensor", "flow_sensor", None

    # 中文 STEP 中“上温湿度传感器”由相邻的传感头和底座两个实体组成。
    # 单独标注它们，前端标签不能再使用上部玻璃罩附近的经验坐标。
    upper_humidity_sensor = (
        20 <= sx <= 32
        and 28 <= sy <= 38
        and 15 <= sz <= 23
        and 70 <= cx <= 95
        and -20 <= cy <= 20
        and cz <= -130
    )
    if upper_humidity_sensor:
        return "valve_or_sensor", "upper_humidity_sensor", None

    # 中文 STEP 中“压力传感器”对应上传感器仓前侧的独立模块。
    # 必须单独标注，不能把仓内其余接头、支架和走线件全部当作压力模块闪烁。
    pressure_sensor = (
        46 <= sx <= 54
        and 38 <= sy <= 45
        and 26 <= sz <= 32
        and 40 <= cx <= 55
        and -35 <= cy <= -18
        and -170 <= cz <= -155
    )
    if pressure_sensor:
        return "valve_or_sensor", "pressure_sensor", None

    column_distance = min(abs(cx + 63.37), abs(cx - 136.63))
    upper_valve_housing = 380 <= sx <= 400 and 180 <= sy <= 200 and 70 <= sz <= 82 and -45 <= cz <= -15
    if upper_valve_housing:
        return "outer_shell", "upper_valve_housing", None
    # 左右排水阀舱最下方的薄盖板，各有三组三孔，共九个真实进气孔。
    drain_inlet_plate = (
        cylindrical
        and 178 <= sx <= 186
        and 3 <= sz <= 7
        and 304 <= cz <= 311
        and column_distance <= 5
    )
    if drain_inlet_plate:
        return "support", f"drain_inlet_plate_{channel}", channel
    drain_chamber_shell = (
        cylindrical
        and 178 <= sx <= 190
        and 3 <= sz <= 60
        and 275 <= cz <= 312
        and column_distance <= 5
    )
    if drain_chamber_shell:
        return "outer_shell", f"drain_chamber_shell_{channel}", channel
    lower_leak_plate = (
        cylindrical
        and 155 <= sx <= 162
        and 7 <= sz <= 14
        and 248 <= cz <= 262
        and column_distance <= 5
    )
    if lower_leak_plate:
        return "support", f"lower_silica_leak_plate_{channel}", channel
    upper_fixed_plate = (
        cylindrical
        and 126 <= sx <= 134
        and sz <= 4
        and 5 <= cz <= 12
        and column_distance <= 5
    )
    if upper_fixed_plate:
        return "support", f"upper_fixed_plate_{channel}", channel
    # 两筒内部直径约 153 mm、高约 250 mm 的圆筒是“硅胶固定罩”。
    # 数字孪生中按用户要求隐藏该罩，直接露出内部加热三角架。
    silica_retaining_cover = (
        cylindrical
        and 148 <= sx <= 158
        and 245 <= sz <= 255
        and 120 <= cz <= 140
        and column_distance <= 5
    )
    if silica_retaining_cover:
        return "support", f"silica_retaining_cover_{channel}", channel
    # 三角架包含 220 mm 立柱及上下薄板；79 mm 高的小管是控制盒走线槽，
    # 只能按普通结构显示，不能随加热状态一起高亮。
    heater_triangle = sz <= 5 or sz >= 200
    if 5 <= cz <= 260 and column_distance <= 58 and max(sx, sy) <= 145 and heater_triangle:
        return "heater_frame", f"heat_channel_{channel}", channel

    # STEP 中的“左右堵塞子:1/:2”沿用了旧单管总装的“传感器堵头-1/-2”结构。
    # 画面左右与面对控制盒的实物左右镜像：较小 X 的实体对应右温湿度 T2，
    # 较大 X 的实体对应左温湿度 T1。它们不是上阀的阀位限位点。
    if 10 <= sx <= 13 and 15 <= sy <= 20 and 15 <= sz <= 20 and -30 <= cz <= -15:
        if cx < 40:
            return "valve_or_sensor", "right_humidity_sensor", 2
        return "valve_or_sensor", "left_humidity_sensor", 1
    # 上阀双向电磁阀壳体；阀位指示应覆盖在该壳体中心，而不是右侧的横向移动阀芯上。
    if 35 <= sx <= 43 and 18 <= sy <= 24 and 34 <= sz <= 42 and -35 <= cz <= -24:
        return "valve_or_sensor", "upper_valve_solenoid", None
    if 48 <= sx <= 60 and 13 <= sy <= 20 and 13 <= sz <= 20 and -32 <= cz <= -15:
        return "valve_or_sensor", "upper_valve", None
    if cz <= -115 and max(sx, sy, sz) <= 100:
        return "valve_or_sensor", "upper_sensor_component", None
    if cz >= 275 and max(sx, sy) <= 110:
        return "valve_or_sensor", f"drain_channel_{channel}", channel
    return "structure", None, None


def build_glb(raw_parts: list[tuple[np.ndarray, np.ndarray]]) -> None:
    global_low = np.full(3, np.inf, dtype=np.float32)
    global_high = np.full(3, -np.inf, dtype=np.float32)
    for vertices, _normals in raw_parts:
        global_low = np.minimum(global_low, vertices.min(axis=(0, 1)))
        global_high = np.maximum(global_high, vertices.max(axis=(0, 1)))

    center_xy = (global_low[:2] + global_high[:2]) / 2
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "YLDQ 双通道 STL 总装转换器"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": materials(),
        "buffers": [],
        "bufferViews": [],
        "accessors": [],
    }
    binary = bytearray()
    role_counts: dict[str, int] = {}
    triangle_total = 0

    for index, (raw_vertices, raw_normals) in enumerate(raw_parts, start=1):
        triangle_total += len(raw_vertices)
        raw_low = raw_vertices.min(axis=(0, 1))
        raw_high = raw_vertices.max(axis=(0, 1))
        role, function, channel = classify_part(raw_low, raw_high)
        role_counts[role] = role_counts.get(role, 0) + 1

        positions = np.empty_like(raw_vertices)
        positions[:, :, 0] = (raw_vertices[:, :, 0] - center_xy[0]) * SCALE
        positions[:, :, 1] = (raw_vertices[:, :, 2] - global_low[2]) * SCALE
        positions[:, :, 2] = -(raw_vertices[:, :, 1] - center_xy[1]) * SCALE
        positions = positions.reshape(-1, 3).astype("<f4", copy=False)

        transformed_normals = np.empty_like(raw_normals)
        transformed_normals[:, 0] = raw_normals[:, 0]
        transformed_normals[:, 1] = raw_normals[:, 2]
        transformed_normals[:, 2] = -raw_normals[:, 1]
        transformed_normals /= np.maximum(np.linalg.norm(transformed_normals, axis=1, keepdims=True), 1e-7)
        normal_values = np.repeat(transformed_normals, 3, axis=0).astype("<f4", copy=False)
        low, high = positions.min(axis=0), positions.max(axis=0)

        position_offset = len(binary)
        position_data = align4(positions.tobytes())
        binary.extend(position_data)
        normal_offset = len(binary)
        normal_data = align4(normal_values.tobytes())
        binary.extend(normal_data)
        position_view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": position_offset, "byteLength": len(position_data), "target": 34962})
        normal_view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": normal_offset, "byteLength": len(normal_data), "target": 34962})
        position_accessor = len(document["accessors"])
        document["accessors"].append({"bufferView": position_view, "componentType": 5126, "count": len(positions), "type": "VEC3", "min": low.tolist(), "max": high.tolist()})
        normal_accessor = len(document["accessors"])
        document["accessors"].append({"bufferView": normal_view, "componentType": 5126, "count": len(normal_values), "type": "VEC3"})
        node_name = f"double_component_{index:03d}_{role}"
        mesh_index = len(document["meshes"])
        document["meshes"].append({"name": node_name, "primitives": [{"attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor}, "material": ROLE_MATERIAL[role]}]})
        extras: dict[str, Any] = {"digital_twin_role": role, "source_part_index": index}
        if function:
            extras["digital_twin_function"] = function
        if channel:
            extras["digital_twin_channel"] = channel
        node_index = len(document["nodes"])
        document["nodes"].append({"name": node_name, "mesh": mesh_index, "extras": extras})
        document["scenes"][0]["nodes"].append(node_index)

    document["buffers"] = [{"byteLength": len(binary)}]
    json_bytes = align4(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), b" ")
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as target:
        target.write(struct.pack("<4sII", b"glTF", 2, total_length))
        target.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        target.write(json_bytes)
        target.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        target.write(binary)
    model_size = (global_high - global_low) * SCALE
    print(f"已导出 {len(raw_parts)} 个双通道实体，共 {triangle_total} 个三角面，尺寸约 {model_size.tolist()}，角色统计 {role_counts}")


def main() -> None:
    if not SOURCE_STL.exists():
        raise RuntimeError(f"未找到带中文部件名的双通道 STL：{SOURCE_STL}")
    vertices, normals, attributes = read_binary_stl(SOURCE_STL)
    groups = split_triangle_components(vertices, attributes)
    build_glb([(vertices[group], normals[group]) for group in groups])


if __name__ == "__main__":
    main()
