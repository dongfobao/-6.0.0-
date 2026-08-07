"""将新版单体 STL 拆分成独立实体，并按旧总装零件命名导出 GLB。"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "3D数字孪生资料" / "05_模型源文件_如有" / "吸湿器5.0.stl"
REFERENCE = ROOT / "app" / "web" / "assets" / "yldq-5-single-pipe.glb"
OUTPUT = ROOT / "app" / "web" / "assets" / "yldq-5-single-pipe-v2.glb"
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


def read_glb_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if raw[:4] != b"glTF":
        raise RuntimeError(f"不是有效 GLB：{path}")
    chunk_length, chunk_type = struct.unpack_from("<I4s", raw, 12)
    if chunk_type != b"JSON":
        raise RuntimeError(f"GLB 首块不是 JSON：{path}")
    return json.loads(raw[20 : 20 + chunk_length].decode("utf-8"))


def reference_parts() -> list[dict[str, Any]]:
    document = read_glb_json(REFERENCE)
    parts: list[dict[str, Any]] = []
    for node in document.get("nodes", []):
        mesh_index = node.get("mesh")
        if mesh_index is None:
            continue
        primitive = document["meshes"][mesh_index]["primitives"][0]
        accessor = document["accessors"][primitive["attributes"]["POSITION"]]
        extras = node.get("extras") or {}
        low = np.asarray(accessor["min"], dtype=np.float32)
        high = np.asarray(accessor["max"], dtype=np.float32)
        parts.append({
            "name": node.get("name") or "未命名零件",
            "source_file": extras.get("source_file") or node.get("name") or "未命名零件",
            "role": extras.get("digital_twin_role") or "structure",
            "low": low,
            "high": high,
            "center": (low + high) / 2,
            "size": np.maximum(high - low, 0.01),
        })
    return parts


def split_triangle_components(vertices: np.ndarray, attributes: np.ndarray) -> list[np.ndarray]:
    """按共享顶点拆分 STL 独立实体；颜色属性参与键值，避免接触零件被粘连。"""
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
    groups.sort(key=len, reverse=True)
    return groups


def match_reference(low: np.ndarray, high: np.ndarray, references: list[dict[str, Any]]) -> dict[str, Any]:
    center = (low + high) / 2
    size = np.maximum(high - low, 0.005)
    best_part, best_score = references[0], float("inf")
    for part in references:
        outside = np.maximum(part["low"] - center, 0) + np.maximum(center - part["high"], 0)
        outside_score = float(np.linalg.norm(outside / np.maximum(part["size"], 0.08)))
        center_score = float(np.linalg.norm((center - part["center"]) / np.maximum(part["size"], 0.12)))
        size_score = float(np.linalg.norm(np.log((size + 0.02) / (part["size"] + 0.02))))
        score = outside_score * 5 + center_score + size_score * 0.18
        if score < best_score:
            best_part, best_score = part, score
    if best_score > 7:
        return {"name": "新增旁路或结构实体", "source_file": "新版总装新增实体", "role": "structure"}
    return best_part


def material_definitions() -> list[dict[str, Any]]:
    return [
        {"name": "金属结构", "pbrMetallicRoughness": {"baseColorFactor": [0.34, 0.43, 0.50, 1], "metallicFactor": 0.86, "roughnessFactor": 0.24}},
        {"name": "阀门与传感器", "pbrMetallicRoughness": {"baseColorFactor": [0.12, 0.34, 0.48, 1], "metallicFactor": 0.76, "roughnessFactor": 0.20}},
        {"name": "加热组件", "pbrMetallicRoughness": {"baseColorFactor": [0.55, 0.24, 0.09, 1], "metallicFactor": 0.68, "roughnessFactor": 0.29}},
        {"name": "支撑与绝缘件", "pbrMetallicRoughness": {"baseColorFactor": [0.42, 0.48, 0.53, 1], "metallicFactor": 0.40, "roughnessFactor": 0.44}},
        {"name": "硅胶与干燥剂", "pbrMetallicRoughness": {"baseColorFactor": [0.22, 0.66, 0.48, 0.24], "metallicFactor": 0.04, "roughnessFactor": 0.62}, "alphaMode": "BLEND", "doubleSided": True},
        {"name": "透明观察件", "pbrMetallicRoughness": {"baseColorFactor": [0.22, 0.76, 0.82, 0.14], "metallicFactor": 0.03, "roughnessFactor": 0.08}, "alphaMode": "BLEND", "doubleSided": True},
    ]


def main() -> None:
    raw = SOURCE.read_bytes()
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    if len(raw) != 84 + triangle_count * 50:
        raise RuntimeError("STL 三角面数量与文件长度不匹配")
    triangle_dtype = np.dtype([("normal", "<f4", (3,)), ("vertices", "<f4", (3, 3)), ("attribute", "<u2")])
    triangles = np.frombuffer(raw, dtype=triangle_dtype, count=triangle_count, offset=84)
    raw_vertices = triangles["vertices"]
    bounds_min = raw_vertices.min(axis=(0, 1))
    bounds_max = raw_vertices.max(axis=(0, 1))
    center_xy = (bounds_min[:2] + bounds_max[:2]) / 2

    converted = np.empty_like(raw_vertices)
    converted[:, :, 0] = (raw_vertices[:, :, 0] - center_xy[0]) * SCALE
    converted[:, :, 1] = (raw_vertices[:, :, 2] - bounds_min[2]) * SCALE
    converted[:, :, 2] = -(raw_vertices[:, :, 1] - center_xy[1]) * SCALE
    normals = np.empty_like(triangles["normal"])
    normals[:, 0] = triangles["normal"][:, 0]
    normals[:, 1] = triangles["normal"][:, 2]
    normals[:, 2] = -triangles["normal"][:, 1]
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-7)

    groups = split_triangle_components(raw_vertices, triangles["attribute"])
    references = reference_parts()
    document: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "YLDQ 分件总装 STL 转换器"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "materials": material_definitions(),
        "buffers": [],
        "bufferViews": [],
        "accessors": [],
    }
    binary = bytearray()
    role_counts: dict[str, int] = {}
    for component_index, triangle_indices in enumerate(groups, start=1):
        positions = converted[triangle_indices].reshape(-1, 3).astype("<f4", copy=False)
        component_normals = np.repeat(normals[triangle_indices], 3, axis=0).astype("<f4", copy=False)
        low, high = positions.min(axis=0), positions.max(axis=0)
        matched = match_reference(low, high, references)
        role = str(matched.get("role") or "structure")
        role_counts[role] = role_counts.get(role, 0) + 1

        position_offset = len(binary)
        position_data = align4(positions.tobytes())
        binary.extend(position_data)
        normal_offset = len(binary)
        normal_data = align4(component_normals.tobytes())
        binary.extend(normal_data)
        position_view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": position_offset, "byteLength": len(position_data), "target": 34962})
        normal_view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": normal_offset, "byteLength": len(normal_data), "target": 34962})
        position_accessor = len(document["accessors"])
        document["accessors"].append({"bufferView": position_view, "componentType": 5126, "count": len(positions), "type": "VEC3", "min": low.tolist(), "max": high.tolist()})
        normal_accessor = len(document["accessors"])
        document["accessors"].append({"bufferView": normal_view, "componentType": 5126, "count": len(component_normals), "type": "VEC3"})
        mesh_index = len(document["meshes"])
        node_name = f"replacement_{component_index:04d}_{role}"
        document["meshes"].append({"name": node_name, "primitives": [{"attributes": {"POSITION": position_accessor, "NORMAL": normal_accessor}, "material": ROLE_MATERIAL.get(role, 0)}]})
        node_index = len(document["nodes"])
        document["nodes"].append({"name": node_name, "mesh": mesh_index, "extras": {"digital_twin_role": role, "source_file": matched.get("source_file", "新版总装新增实体")}})
        document["scenes"][0]["nodes"].append(node_index)

    document["buffers"] = [{"byteLength": len(binary)}]
    json_bytes = align4(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), b" ")
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    with OUTPUT.open("wb") as target:
        target.write(struct.pack("<4sII", b"glTF", 2, total_length))
        target.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        target.write(json_bytes)
        target.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        target.write(binary)
    print(f"已拆分 {len(groups)} 个独立实体，三角面 {triangle_count}，角色统计 {role_counts}")


if __name__ == "__main__":
    main()
