"""Read-only DDS header parser.

This module never converts, resizes, flips, or rewrites a texture. It unpacks
the 128-byte DirectDraw surface header (and the 20-byte DX10 extension when
the FourCC is ``DX10``) and returns the fields the ModHub texture matrix needs.

The expected Block Compression choice for each suffix comes from
``Documentation/All compression types.pdf``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

_MAGIC = b"DDS "
_HEADER_SIZE = 128
_DX10_SIZE = 20

_DDPF_ALPHAPIXELS = 0x1
_DDPF_FOURCC = 0x4
_DDPF_RGB = 0x40

# FourCC values that are Block Compression without a DX10 header.
_FOURCC_FORMATS: dict[str, str] = {
    "DXT1": "BC1",
    "DXT2": "BC2",
    "DXT3": "BC2",
    "DXT4": "BC3",
    "DXT5": "BC3",
    "ATI1": "BC4",
    "BC4U": "BC4",
    "BC4S": "BC4",
    "ATI2": "BC5",
    "BC5U": "BC5",
    "BC5S": "BC5",
}

# DXGI_FORMAT values used by the DX10 extension. Ranges are inclusive.
_DXGI_FORMATS: tuple[tuple[int, int, str], ...] = (
    (70, 72, "BC1"),
    (73, 75, "BC2"),
    (76, 78, "BC3"),
    (79, 81, "BC4"),
    (82, 84, "BC5"),
    (95, 96, "BC6H"),
    (97, 99, "BC7"),
)

# Formats whose header means a color alpha channel is part of the file.
# BC1 is the no-alpha row unless the alpha-pixel flag is set.
_ALPHA_FORMATS = frozenset({"BC2", "BC3", "BC7"})


class DdsHeaderError(Exception):
    """The bytes are not a readable DDS header."""


@dataclass(frozen=True, slots=True)
class DdsHeader:
    """Fields unpacked from a DDS header. Pixel blocks are not decoded."""

    width: int
    height: int
    mipmap_count: int
    fourcc: str
    format_name: str
    has_alpha: bool
    dxgi_format: int | None = None

    @property
    def mipmaps_present(self) -> bool:
        """True when the header declares a mip chain (count greater than 1)."""
        return self.mipmap_count > 1

    @property
    def power_of_two(self) -> bool:
        return _is_power_of_two(self.width) and _is_power_of_two(self.height)


def read_dds_header(data: bytes) -> DdsHeader:
    """Unpack a DDS header from the start of ``data``.

    Raises:
        DdsHeaderError: the magic, declared sizes, or DX10 tail are not usable.
    """
    if len(data) < _HEADER_SIZE:
        raise DdsHeaderError(
            f"DDS header is {len(data)} bytes; a DDS file starts with {_HEADER_SIZE} header bytes."
        )
    magic = data[:4]
    if magic != _MAGIC:
        raise DdsHeaderError("File does not start with the DDS magic ('DDS ').")

    size, _flags, height, width, _pitch, _depth, mip_count = struct.unpack_from("<7I", data, 4)
    if size != 124:
        raise DdsHeaderError(f"DDS dwSize is {size}; the standard header size is 124.")

    pf_size, pf_flags = struct.unpack_from("<II", data, 76)
    fourcc_raw = data[84:88]
    rgb_bits, _r_mask, _g_mask, _b_mask, a_mask = struct.unpack_from("<5I", data, 88)
    if pf_size != 32:
        raise DdsHeaderError(f"DDS pixel-format size is {pf_size}; the standard size is 32.")

    fourcc = _decode_fourcc(fourcc_raw)
    dxgi: int | None = None
    if fourcc == "DX10":
        if len(data) < _HEADER_SIZE + _DX10_SIZE:
            raise DdsHeaderError("FourCC is DX10 but the 20-byte DX10 extension is missing.")
        dxgi = struct.unpack_from("<I", data, _HEADER_SIZE)[0]

    format_name = _format_name(fourcc, dxgi, pf_flags, rgb_bits)
    has_alpha = _header_has_alpha(format_name, fourcc, pf_flags, a_mask)
    return DdsHeader(
        width=width,
        height=height,
        mipmap_count=mip_count,
        fourcc=fourcc,
        format_name=format_name,
        has_alpha=has_alpha,
        dxgi_format=dxgi,
    )


def _decode_fourcc(raw: bytes) -> str:
    if raw == b"\x00\x00\x00\x00":
        return ""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        return raw.hex()
    if text.isprintable():
        return text
    return raw.hex()


def _format_name(fourcc: str, dxgi: int | None, pf_flags: int, rgb_bits: int) -> str:
    if fourcc == "DX10":
        if dxgi is None:
            return "DX10"
        for start, end, name in _DXGI_FORMATS:
            if start <= dxgi <= end:
                return name
        return f"DXGI_{dxgi}"
    mapped = _FOURCC_FORMATS.get(fourcc)
    if mapped is not None:
        return mapped
    if fourcc:
        return fourcc
    if pf_flags & _DDPF_RGB:
        return f"RGB{rgb_bits}"
    return "UNKNOWN"


def _header_has_alpha(format_name: str, fourcc: str, pf_flags: int, alpha_mask: int) -> bool:
    """Decide alpha from header flags only. Pixel blocks are not inspected."""
    if format_name in _ALPHA_FORMATS:
        return True
    if fourcc == "DXT1" or format_name == "BC1":
        return bool(pf_flags & _DDPF_ALPHAPIXELS)
    if pf_flags & _DDPF_FOURCC:
        return bool(pf_flags & _DDPF_ALPHAPIXELS)
    return bool(pf_flags & _DDPF_ALPHAPIXELS) or alpha_mask != 0


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0
