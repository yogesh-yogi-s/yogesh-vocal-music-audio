"""Fixed binary constants for the VMA v2 format."""

from __future__ import annotations

import struct

MAGIC = b"VMAF"
VERSION_V2 = 2

# Section 3.1: <4s HH I I Q Q Q Q I I>
HEADER_STRUCT_V2 = struct.Struct("<4sHHIIQQQQII")
HEADER_SIZE_V2 = HEADER_STRUCT_V2.size  # 56 bytes

# Section 4: <I H H H H q Q Q Q I>
DESCRIPTOR_STRUCT_V2 = struct.Struct("<IHHHHqQQQI")
DESCRIPTOR_FIXED_SIZE_V2 = DESCRIPTOR_STRUCT_V2.size  # 48 bytes

# Section 12.1 reference implementation resource limit.
MAX_STREAMS_V2 = 64

# Section 12.2 local reference-implementation read-allocation limits.  These
# are resource-safety policy, not V2 binary-format semantic limits.
MAX_METADATA_BYTES_V2 = 1 * 1024 * 1024
MAX_FORMAT_INFO_BYTES_V2 = 1 * 1024 * 1024

# Defined generic role values. Unknown values remain raw u16 values.
ROLE_UNKNOWN = 0x0000
ROLE_AUDIO_PRIMARY = 0x0001
ROLE_AUDIO_SUPPLEMENTAL = 0x0002
ROLE_METADATA_SIDECAR = 0x0003
