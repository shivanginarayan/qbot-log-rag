#!/usr/bin/env python3
"""Convert a pixel in a ROS occupancy-grid image to map coordinates."""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import yaml


def pgm_dimensions(pgm_path: Path) -> tuple[int, int]:
    """Return the width and height from a P2 or P5 PGM header."""
    tokens: list[bytes] = []

    with pgm_path.open("rb") as pgm:
        while len(tokens) < 3:
            line = pgm.readline()
            if not line:
                raise ValueError(f"Incomplete PGM header: {pgm_path}")
            line = line.split(b"#", 1)[0]
            tokens.extend(line.split())

    if tokens[0] not in {b"P2", b"P5"}:
        raise ValueError(f"Unsupported PGM format {tokens[0]!r}; expected P2 or P5")

    return int(tokens[1]), int(tokens[2])


def pixel_to_coordinates(
    pixel_x: float,
    pixel_y: float,
    *,
    image_height: int,
    resolution: float,
    origin: tuple[float, float, float],
) -> tuple[float, float]:
    """Convert a top-left-origin image pixel to ROS map-frame coordinates."""
    local_x = pixel_x * resolution
    local_y = (image_height - pixel_y) * resolution
    origin_x, origin_y, origin_yaw = origin

    cos_yaw = math.cos(origin_yaw)
    sin_yaw = math.sin(origin_yaw)
    map_x = origin_x + cos_yaw * local_x - sin_yaw * local_y
    map_y = origin_y + sin_yaw * local_x + cos_yaw * local_y
    return map_x, map_y


def coordinates_from_map(
    map_yaml: Path, pixel_x: float, pixel_y: float
) -> tuple[float, float]:
    """Load a ROS map YAML and convert one image pixel to map coordinates."""
    metadata = yaml.safe_load(map_yaml.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError(f"Invalid map metadata: {map_yaml}")

    image_value = metadata.get("image")
    if not image_value:
        raise ValueError(f"Map YAML has no image entry: {map_yaml}")

    image_path = Path(str(image_value)).expanduser()
    if not image_path.is_absolute():
        image_path = map_yaml.parent / image_path

    width, height = pgm_dimensions(image_path)
    if not 0 <= pixel_x < width or not 0 <= pixel_y < height:
        raise ValueError(
            f"Pixel ({pixel_x}, {pixel_y}) is outside the {width} x {height} map"
        )

    resolution = float(metadata["resolution"])
    raw_origin = metadata.get("origin", [0.0, 0.0, 0.0])
    if not isinstance(raw_origin, list) or len(raw_origin) < 3:
        raise ValueError(f"Invalid map origin in {map_yaml}: {raw_origin!r}")
    origin = (float(raw_origin[0]), float(raw_origin[1]), float(raw_origin[2]))

    return pixel_to_coordinates(
        pixel_x,
        pixel_y,
        image_height=height,
        resolution=resolution,
        origin=origin,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a top-left-origin PGM pixel to ROS map coordinates."
    )
    parser.add_argument("map_yaml", type=Path, help="Path to the ROS map YAML")
    parser.add_argument("pixel_x", type=float, help="Pixel x measured from the left")
    parser.add_argument("pixel_y", type=float, help="Pixel y measured from the top")
    args = parser.parse_args()

    map_x, map_y = coordinates_from_map(
        args.map_yaml.expanduser().resolve(), args.pixel_x, args.pixel_y
    )
    print(f"map_x: {map_x:.3f}")
    print(f"map_y: {map_y:.3f}")


if __name__ == "__main__":
    main()
# Run from ~/qbot-log-rag with the following command to convert pixel coordinates to map coordinates:
# python3 robot_navigation/tools/pixel_to_coordinates.py robot_navigation/maps/lab_map_new.yaml 5259.6 262.6