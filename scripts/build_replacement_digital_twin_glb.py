"""将新版单体 STL 转换为网页可加载的 GLB。

新版总装已包含真实旁路通气管，因此仅导出实体网格；工艺粒子仍由前端的
不可见定位总装提供坐标，不再额外生成旁路管实体。
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "3D数字孪生资料" / "05_模型源文件_如有" / "吸湿器5.0.stl"
OUTPUT = ROOT / "app" / "web" / "assets" / "yldq-5-single-pipe-v2.glb"
SCALE = 0.008


def align4(data: bytes) -> bytes:
    return data + b"\x00" * ((-len(data)) % 4)


def main() -> None:
    raw = SOURCE.read_bytes()
    if len(raw) < 84:
        raise RuntimeError(f"STL 文件损坏：{SOURCE}")
    triangle_count = struct.unpack_from("<I", raw, 80)[0]
    expected_size = 84 + triangle_count * 50
    if len(raw) != expected_size:
        raise RuntimeError(f"STL 三角面数量不匹配：期望 {expected_size} 字节，实际 {len(raw)} 字节")

    triangle_dtype = np.dtype([
        ("normal", "<f4", (3,)),
        ("vertices", "<f4", (3, 3)),
        ("attribute", "<u2"),
    ])
    triangles = np.frombuffer(raw, dtype=triangle_dtype, count=triangle_count, offset=84)
    raw_vertices = triangles["vertices"]
    bounds_min = raw_vertices.min(axis=(0, 1))
    bounds_max = raw_vertices.max(axis=(0, 1))
    center_xy = (bounds_min[:2] + bounds_max[:2]) / 2

    # STL 的 Z 轴为设备高度；glTF 导出使用 Y 轴向上，保持旧总装的坐标基准。
    positions = raw_vertices.reshape(-1, 3).copy()
    converted_positions = np.empty_like(positions)
    converted_positions[:, 0] = (positions[:, 0] - center_xy[0]) * SCALE
    converted_positions[:, 1] = (positions[:, 2] - bounds_min[2]) * SCALE
    converted_positions[:, 2] = -(positions[:, 1] - center_xy[1]) * SCALE

    normals = np.repeat(triangles["normal"], 3, axis=0)
    converted_normals = np.empty_like(normals)
    converted_normals[:, 0] = normals[:, 0]
    converted_normals[:, 1] = normals[:, 2]
    converted_normals[:, 2] = -normals[:, 1]
    normal_length = np.linalg.norm(converted_normals, axis=1, keepdims=True)
    converted_normals /= np.maximum(normal_length, 1e-7)

    position_bytes = align4(converted_positions.astype("<f4", copy=False).tobytes())
    normal_bytes = align4(converted_normals.astype("<f4", copy=False).tobytes())
    binary = position_bytes + normal_bytes
    position_max = converted_positions.max(axis=0).tolist()
    position_min = converted_positions.min(axis=0).tolist()
    vertex_count = len(converted_positions)
    document = {
        "asset": {"version": "2.0", "generator": "YLDQ 新版总装 STL 转换器"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "新版吸湿器总装（含真实旁路通气管）", "mesh": 0}],
        "meshes": [{"name": "新版吸湿器总装", "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "material": 0}]}],
        "materials": [{
            "name": "金属总装",
            "pbrMetallicRoughness": {"baseColorFactor": [0.25, 0.38, 0.48, 1.0], "metallicFactor": 0.88, "roughnessFactor": 0.24},
        }],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(position_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(position_bytes), "byteLength": len(normal_bytes), "target": 34962},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": vertex_count, "type": "VEC3", "min": position_min, "max": position_max},
            {"bufferView": 1, "componentType": 5126, "count": vertex_count, "type": "VEC3"},
        ],
    }
    json_bytes = align4(json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("wb") as target:
        target.write(struct.pack("<4sII", b"glTF", 2, total_length))
        target.write(struct.pack("<I4s", len(json_bytes), b"JSON"))
        target.write(json_bytes)
        target.write(struct.pack("<I4s", len(binary), b"BIN\x00"))
        target.write(binary)
    print(f"已生成 {OUTPUT.name}：{triangle_count} 个三角面，尺寸 {np.round(np.array(position_max) - np.array(position_min), 4).tolist()}")


if __name__ == "__main__":
    main()
