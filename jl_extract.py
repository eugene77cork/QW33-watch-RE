#!/usr/bin/env python3
"""
jl_extract.py — JieLi firmware & watch face resource extractor
QW33 Fishing Mod Project

Extracts the contents of:
  - upgrade.zip  → update.ufw + res.ori/ containers
  - JLFS resource containers (JL, font, watch, watch1-5)

Usage:
  python jl_extract.py upgrade.zip           # extract everything
  python jl_extract.py res.ori/watch         # extract single container
  python jl_extract.py --list res.ori/watch  # list contents only

Output goes to ./extracted/ by default.
Use --out <dir> to specify a different output directory.
"""

import argparse
import os
import struct
import sys
import zipfile


# ─────────────────────────────────────────────────────────────────────────────
# JLFS container parser
# ─────────────────────────────────────────────────────────────────────────────

JLFS_FILE_FLAG = 0x0000FF02
JLFS_ROOT_FLAG = 0x0000FF03
ENTRY_SIZE = 32


def parse_jlfs(data: bytes) -> list[dict]:
    """
    Parse a JieLi File System (JLFS) container and return a list of file entries.

    Each entry dict contains:
      name       (str)   filename
      offset     (int)   absolute byte offset of file data within container
      size       (int)   file data size in bytes
      flags      (int)   raw flags field
      hdr_crc    (int)   CRC16 of header
      data_crc   (int)   CRC16 of data
    """
    entries = []

    # Container header is at offset 0x00 (32 bytes)
    # Index entries start at 0x20
    pos = ENTRY_SIZE  # skip root entry

    while pos + ENTRY_SIZE <= len(data):
        block = data[pos:pos + ENTRY_SIZE]

        hdr_crc  = struct.unpack_from('<H', block, 0)[0]
        data_crc = struct.unpack_from('<H', block, 2)[0]
        offset   = struct.unpack_from('<I', block, 4)[0]
        size     = struct.unpack_from('<I', block, 8)[0]
        flags    = struct.unpack_from('<I', block, 12)[0]
        name_raw = block[16:32]
        name     = name_raw.split(b'\x00')[0].decode('ascii', errors='ignore')

        if flags == JLFS_FILE_FLAG and name and size > 0 and offset < len(data):
            entries.append({
                'name':     name,
                'offset':   offset,
                'size':     size,
                'flags':    flags,
                'hdr_crc':  hdr_crc,
                'data_crc': data_crc,
            })
        elif flags not in (JLFS_FILE_FLAG, JLFS_ROOT_FLAG, 0):
            # Unexpected flag — likely past end of index
            break

        pos += ENTRY_SIZE

    return entries


def extract_jlfs(data: bytes, out_dir: str, list_only: bool = False) -> list[dict]:
    """Extract all files from a JLFS container to out_dir."""
    entries = parse_jlfs(data)

    if not entries:
        print('  [!] No entries found — may not be a JLFS container')
        return []

    if not list_only:
        os.makedirs(out_dir, exist_ok=True)

    for e in entries:
        file_data = data[e['offset']:e['offset'] + e['size']]
        status = f"  {e['name']:<20} offset=0x{e['offset']:06x}  size={e['size']:8,} bytes"

        if list_only:
            print(status)
        else:
            out_path = os.path.join(out_dir, e['name'])
            with open(out_path, 'wb') as f:
                f.write(file_data)
            print(status + f"  → {out_path}")

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# .view file info
# ─────────────────────────────────────────────────────────────────────────────

def parse_view_header(data: bytes) -> dict | None:
    """Parse the RU21 .view file header and return display info."""
    if len(data) < 0x50 or data[:4] != b'RU21':
        return None

    return {
        'magic':          data[:4].decode(),
        'version':        list(data[4:8]),
        'screen_width':   struct.unpack_from('<H', data, 0x44)[0],
        'screen_height':  struct.unpack_from('<H', data, 0x46)[0],
        'widget_offset':  struct.unpack_from('<H', data, 0x48)[0],
        'palette_size':   struct.unpack_from('<I', data, 0x38)[0],
        'palette_crc':    struct.unpack_from('<I', data, 0x3c)[0],
        'widget_size':    struct.unpack_from('<H', data, 0x4c)[0],
    }


# ─────────────────────────────────────────────────────────────────────────────
# upgrade.zip handler
# ─────────────────────────────────────────────────────────────────────────────

def extract_upgrade_zip(zip_path: str, out_dir: str, list_only: bool = False):
    """Extract upgrade.zip and then recurse into each JLFS container."""
    print(f"\n{'='*60}")
    print(f"upgrade.zip: {zip_path}")
    print(f"{'='*60}")

    with zipfile.ZipFile(zip_path, 'r') as zf:
        members = zf.namelist()
        print(f"  ZIP members: {members}")

        for member in members:
            member_data = zf.read(member)
            member_name = os.path.basename(member) or os.path.dirname(member)

            if member.endswith('/') or not member_name:
                continue

            member_out = os.path.join(out_dir, member_name)

            if list_only:
                print(f"\n  [{member}]  {len(member_data):,} bytes")
            else:
                os.makedirs(os.path.dirname(os.path.join(out_dir, member)) or out_dir,
                            exist_ok=True)
                with open(member_out, 'wb') as f:
                    f.write(member_data)
                print(f"\n  Saved: {member_out}  ({len(member_data):,} bytes)")

            # Recurse into JLFS containers (res.ori/* files)
            if '\x00' not in member_name and '.' not in member_name:
                print(f"\n  Extracting JLFS container: {member_name}")
                container_out = os.path.join(out_dir, member_name + '_extracted')
                extract_jlfs(member_data, container_out, list_only)


# ─────────────────────────────────────────────────────────────────────────────
# Single container handler
# ─────────────────────────────────────────────────────────────────────────────

def extract_container(path: str, out_dir: str, list_only: bool = False):
    """Extract a single JLFS container file."""
    name = os.path.basename(path)
    print(f"\n{'='*60}")
    print(f"Container: {path}  ({os.path.getsize(path):,} bytes)")
    print(f"{'='*60}")

    with open(path, 'rb') as f:
        data = f.read()

    # Check if it looks like a JLFS container
    flags_at_12 = struct.unpack_from('<I', data, 12)[0] if len(data) >= 16 else 0
    if flags_at_12 != JLFS_ROOT_FLAG:
        print(f"  [!] Root entry flags = 0x{flags_at_12:08x} (expected 0x{JLFS_ROOT_FLAG:08x})")
        print(f"  [!] May not be a standard JLFS container — attempting anyway")

    container_out = os.path.join(out_dir, name + '_extracted')
    entries = extract_jlfs(data, container_out, list_only)

    # If we got .view files, parse their headers
    for e in entries:
        if e['name'].endswith('.view'):
            view_data = data[e['offset']:e['offset'] + e['size']]
            info = parse_view_header(view_data)
            if info:
                print(f"\n  .view info for {e['name']}:")
                print(f"    Screen:        {info['screen_width']} × {info['screen_height']} px")
                print(f"    Widget offset: 0x{info['widget_offset']:04x}")
                print(f"    Widget size:   {info['widget_size']} bytes")
                print(f"    Palette:       {info['palette_size']} bytes (CRC=0x{info['palette_crc']:08x})")

    return entries


# ─────────────────────────────────────────────────────────────────────────────
# .sty parser — show widget definitions
# ─────────────────────────────────────────────────────────────────────────────

WIDGET_TYPES = [
    b'rtc', b'strpic', b'text', b'ascii', b'numb',
    b'mulstr', b'time1', b'time2', b'dis_str', b'img',
]


def parse_sty(data: bytes) -> list[dict]:
    """Find and return widget type definitions from a .sty file."""
    widgets = []
    seen_positions = set()

    for wtype in WIDGET_TYPES:
        search = wtype + b'\x00'
        pos = 0
        while True:
            idx = data.find(search, pos)
            if idx == -1:
                break
            if idx not in seen_positions and idx >= 16:
                seen_positions.add(idx)

                pre = data[idx - 16:idx]
                next_off  = struct.unpack_from('<I', pre, 0)[0]
                widget_id = struct.unpack_from('<H', pre, 4)[0]
                flags     = struct.unpack_from('<H', pre, 6)[0]
                color     = struct.unpack_from('<I', pre, 8)[0] & 0xFFFFFF
                data_off  = struct.unpack_from('<I', pre, 12)[0]

                # Get format string (after type name)
                fmt_start = idx + len(search)
                fmt_end   = data.find(b'\x00', fmt_start)
                fmt_str   = data[fmt_start:fmt_end].decode('ascii', errors='ignore') if fmt_end > fmt_start else ''

                widgets.append({
                    'type':      wtype.decode(),
                    'pos':       idx,
                    'widget_id': widget_id,
                    'flags':     flags,
                    'color':     color,
                    'data_off':  data_off,
                    'format':    fmt_str,
                })
            pos = idx + 1

    widgets.sort(key=lambda w: w['pos'])
    return widgets


def show_sty(path: str):
    """Print widget definitions from a .sty file."""
    with open(path, 'rb') as f:
        data = f.read()

    widgets = parse_sty(data)
    print(f"\n  .sty widgets ({len(widgets)} found):")
    print(f"  {'Type':<12} {'ID':>5} {'Flags':>6} {'Color':>8} {'DataOff':>8} {'Format'}")
    print(f"  {'-'*12} {'-'*5} {'-'*6} {'-'*8} {'-'*8} {'-'*20}")
    for w in widgets:
        print(f"  {w['type']:<12} {w['widget_id']:>5} "
              f"0x{w['flags']:04x} #{w['color']:06X} "
              f"0x{w['data_off']:04x}   '{w['format']}'")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='JieLi firmware & watch face resource extractor',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('input', help='upgrade.zip or JLFS container file')
    parser.add_argument('--out', default='extracted', help='Output directory (default: ./extracted)')
    parser.add_argument('--list', action='store_true', help='List contents only, do not extract')
    parser.add_argument('--sty', action='store_true', help='Parse .sty files and show widget info')
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f'Error: file not found: {args.input}')
        sys.exit(1)

    if args.input.endswith('.zip'):
        extract_upgrade_zip(args.input, args.out, args.list)
    else:
        entries = extract_container(args.input, args.out, args.list)

        # Show .sty info if requested or if a .sty was extracted
        if args.sty and not args.list:
            container_out = os.path.join(args.out, os.path.basename(args.input) + '_extracted')
            for e in entries:
                if e['name'].endswith('.sty'):
                    sty_path = os.path.join(container_out, e['name'])
                    if os.path.exists(sty_path):
                        print(f"\nWidget analysis: {sty_path}")
                        show_sty(sty_path)

    print('\nDone.')


if __name__ == '__main__':
    main()
