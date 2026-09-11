from __future__ import annotations


def encode_polyline(points: list[tuple[float, float]]) -> str:
    def encode_signed(value: int) -> str:
        value = ~(value << 1) if value < 0 else value << 1
        chunks: list[str] = []
        while value >= 0x20:
            chunks.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chunks.append(chr(value + 63))
        return "".join(chunks)

    parts: list[str] = []
    prev_lat = 0
    prev_lng = 0
    for lat, lng in points:
        lat_i = round(lat * 1e5)
        lng_i = round(lng * 1e5)
        parts.append(encode_signed(lat_i - prev_lat))
        parts.append(encode_signed(lng_i - prev_lng))
        prev_lat, prev_lng = lat_i, lng_i
    return "".join(parts)
