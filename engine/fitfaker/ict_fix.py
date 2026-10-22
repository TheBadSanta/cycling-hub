#!/usr/bin/env python3
"""Byte-level Garmin identity patch for a FIT file (no re-encoding): file_id.manufacturer/product and device_info
manufacturer/product -> Garmin (1) / Edge 840 (4062); every other byte untouched; header + file CRC recomputed.
Why: fit-file-faker re-encodes with fit_tool and corrupts icTrainer's session message (size 83 vs defined 84),
so Garmin never computes a Primary Benefit; a clean identity-only patch (what fitfiletools does) gets the label. 2026-09-29.
Usage: ict_fix.py <in.fit> <out.fit>"""
import struct, sys
GARMIN, EDGE840 = 1, 4062
def crc16(data, crc=0):
    tab = [0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400]
    for b in data:
        tmp = tab[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc = crc ^ tmp ^ tab[b & 0xF]
        tmp = tab[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc = crc ^ tmp ^ tab[(b >> 4) & 0xF]
    return crc
raw = bytearray(open(sys.argv[1], "rb").read())
hsize = raw[0]; data_size = struct.unpack_from("<I", raw, 4)[0]; assert raw[8:12] == b".FIT", "not a FIT file"
pos, end = hsize, hsize + data_size; defs = {}; patched = []
while pos < end:
    h = raw[pos]; pos += 1
    if h & 0x80: raise SystemExit("compressed timestamp headers not supported")   # icTrainer does not use them
    local = h & 0x0F
    if h & 0x40:                                                                   # definition message
        arch = raw[pos + 1]; endian = ">" if arch == 1 else "<"; gnum = struct.unpack_from(endian + "H", raw, pos + 2)[0]; nf = raw[pos + 4]; p = pos + 5
        fields = [(raw[p + 3*i], raw[p + 3*i + 1], raw[p + 3*i + 2]) for i in range(nf)]; p += 3 * nf
        if h & 0x20: nd = raw[p]; p += 1 + 3 * nd
        defs[local] = (gnum, endian, fields, sum(sz for _, sz, _ in fields) + (sum(raw[pos + 5 + 3*nf + 1 + 3*i + 1] for i in range(raw[pos + 5 + 3*nf])) if h & 0x20 else 0))
        pos = p
    else:                                                                          # data message
        gnum, endian, fields, size = defs[local]; off = pos
        if gnum in (0, 23):                                                        # file_id / device_info
            want = {0: {1: GARMIN, 2: EDGE840}, 23: {2: GARMIN, 4: EDGE840}}[gnum]
            for fnum, sz, _ in fields:
                if fnum in want and sz == 2:
                    old = struct.unpack_from(endian + "H", raw, off)[0]; struct.pack_into(endian + "H", raw, off, want[fnum]); patched.append((gnum, fnum, old, want[fnum]))
                off += sz
        pos += size
if hsize >= 14: struct.pack_into("<H", raw, 12, crc16(raw[:12]))                   # header CRC
struct.pack_into("<H", raw, end, crc16(raw[:end]))                                # file CRC
open(sys.argv[2], "wb").write(raw); print("patched", patched, "->", sys.argv[2], len(raw), "bytes")
