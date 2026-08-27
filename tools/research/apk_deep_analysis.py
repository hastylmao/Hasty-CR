"""Deterministic, bounded static analysis of previously validated APK extractions.

This module treats DEX, ELF, and asset files only as untrusted byte containers.  It
never imports, executes, loads, installs, decompiles, or rebuilds payloads.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import itertools
import json
import lzma
import re
import struct
import sys
import tomllib
import unicodedata
import zipfile
import zlib
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[2]
REFERENCE_ROOT = ROOT / "_references" / "apk_analysis"
DEEP_ROOT = REFERENCE_ROOT / "deep"
REPORT_ROOT = ROOT / "research" / "apk_analysis"
INVENTORY_PATH = REFERENCE_ROOT / "inventory.json"

MAX_DEX_BYTES = 256 * 1024 * 1024
MAX_ELF_BYTES = 512 * 1024 * 1024
MAX_TABLE_ITEMS = 2_000_000
MAX_CODE_ITEMS = 500_000
MAX_INSTRUCTIONS = 4_000_000
MAX_STRING_ITEMS = 500_000
MAX_DEX_STRING_BYTES = 64 * 1024 * 1024
MAX_DATA_BYTES = 32 * 1024 * 1024
MAX_DATA_ROWS = 2_000_000
MAX_DATA_COLUMNS = 16_384
MAX_DATA_CELLS = 8_000_000
MAX_DATA_CELL_CHARS = 1_000_000
MAX_DECODED_DATA_BYTES = 64 * 1024 * 1024
MAX_ELF_RESULT_ITEMS = 750_000
MAX_ELF_RESULT_BYTES = 96 * 1024 * 1024
MAX_PRINTABLE_STRINGS = 20_000
MAX_PRINTABLE_SCAN = 64 * 1024 * 1024
MAX_GRAPH_EDGES_PER_APK = 5_000
MAX_GRAPH_EDGES_PER_LAYER = 1_500
MAX_MECHANICS_CHAINS_PER_APK = 250
MAX_MANIFEST_PATHS = 200
MAX_REPORT_IDENTIFIERS = 40
DATA_SUFFIXES = {".csv", ".toml"}
PROPRIETARY_SUFFIXES = {".sc", ".sctx", ".scw", ".scdb", ".rmat", ".ktx", ".glb", ".bank"}
MECHANICS_TERMS = ("target", "range", "mass", "slow", "dash", "retarget", "bridge", "buff", "ability", "invisible", "projectile", "collision")
CLASSIFICATIONS = ("UNCHANGED_SHARED_CLIENT", "MODIFIED_CLIENT", "PRIVATE_SERVER_SPECIFIC", "CUSTOM_DATA", "UNKNOWN")
EDGE_KINDS = ("direct", "static", "inferred", "unknown")

OFFICIAL_TOOL_LANE = {
    "status": "future-only-not-executed-or-enforced",
    "policy": {
        "network": "deny all",
        "inputs": "read-only, archive-bound, hash-validated",
        "writable_output": "dedicated empty directory only",
        "resource_limits": {"cpu_seconds": 1800, "wall_seconds": 3600, "ram_bytes": 4_294_967_296, "output_bytes": 2_147_483_648},
        "java_limits": ["-Xms64m", "-Xmx3072m", "-XX:MaxMetaspaceSize=512m"],
        "plugins_and_user_config": "disabled; empty HOME and tool config roots",
        "command_allowlist": ["java -jar <pinned-apktool.jar>", "<pinned-jadx>/bin/jadx"],
        "output_revalidation": "reject unsafe paths, links, special files, limit violations, and unexpected executables; hash accepted output",
        "failure_mode": "fail closed before tool start if any control is unavailable",
    },
    "apktool": {
        "version": "3.0.3", "release_date": "2026-07-20",
        "commit": "18b5e99cb56ff9451e8aa55b065dcf5bbd616975",
        "release_url": "https://github.com/iBotPeaches/Apktool/releases/tag/v3.0.3",
        "asset_filename": "apktool_3.0.3.jar",
        "asset_url": "https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar",
        "sha256": "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423",
        "license": "Apache-2.0",
    },
    "jadx": {
        "version": "1.5.6", "release_date": "2026-07-10",
        "commit": "28ff15e4ae69950aebea110a13e5ab895d234dfc",
        "release_url": "https://github.com/skylot/jadx/releases/tag/v1.5.6",
        "asset_filename": "jadx-1.5.6.zip",
        "asset_url": "https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip",
        "sha256": "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974",
        "license": "Apache-2.0",
    },
}
SC_DUMP_STUDY = {
    "repository": "milanmaldini/cr-sc-dump2026",
    "head": "46a4a2d6f0c01bf0549cde70dfcc35e0c9849b7c",
    "relationship": "reported-zero-change-fork-unverified",
    "tree_comparison_evidence": "absent",
    "license": "absent", "tests": "absent", "fixtures": "absent",
    "data": "absent", "provenance": "absent",
    "policy": "study-only; not cloned or run",
}
TRACKED_NAMES = (
    "DEEP_STATIC_ANALYSIS.md", "DEX_RECONSTRUCTION.md", "NATIVE_RECONSTRUCTION.md",
    "DATA_DELTA.md", "SUBSYSTEM_CLASSIFICATION.md", "deep_pairwise.csv",
)


class AnalysisError(RuntimeError):
    pass


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("ascii")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def checked_slice(blob: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(blob) or size > len(blob) - offset:
        raise AnalysisError(f"{label} outside file")
    return blob[offset:offset + size]


def unpack_from(fmt: str, blob: bytes, offset: int, label: str) -> tuple[Any, ...]:
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, checked_slice(blob, offset, size, label))


def read_uleb(blob: bytes, offset: int, label: str) -> tuple[int, int]:
    value = 0
    for index in range(5):
        byte = checked_slice(blob, offset + index, 1, label)[0]
        value |= (byte & 0x7F) << (index * 7)
        if not byte & 0x80:
            return value, offset + index + 1
    raise AnalysisError(f"overlong ULEB128 in {label}")


def bounded_identifier(value: str) -> str | None:
    value = value.strip().replace("\x00", "")
    if not 2 <= len(value) <= 180 or not any(character.isalpha() for character in value):
        return None
    if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$/;<>.:[\]-]*", value):
        return None
    return value


def safe_component(value: str, label: str) -> str:
    if not value or value in {".", ".."} or re.search(r"[\\/:*?\"<>|`\r\n]", value):
        raise AnalysisError(f"unsafe {label}")
    return value


def contained_path(root: Path, parts: Sequence[str], label: str) -> Path:
    clean_parts = [safe_component(part, label) for part in parts]
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*clean_parts).resolve()
    if candidate == resolved_root or resolved_root not in candidate.parents:
        raise AnalysisError(f"{label} escapes expected root")
    return candidate


def markdown_code(value: Any) -> str:
    text = str(value)
    if re.search(r"[`|\r\n]", text):
        raise AnalysisError("unsafe tracked-report identifier")
    return f"`{text}`"


def jaccard(left: set[Any], right: set[Any]) -> float:
    union = left | right
    return round(len(left & right) / len(union), 6) if union else 1.0


def multiset_jaccard(left: Counter[Any], right: Counter[Any]) -> float:
    keys = left.keys() | right.keys()
    denominator = sum(max(left[key], right[key]) for key in keys)
    return round(sum(min(left[key], right[key]) for key in keys) / denominator, 6) if denominator else 1.0


def set_digest(values: Iterable[Any]) -> str:
    return stable_hash(sorted(values))


def table_bounds(count: int, offset: int, width: int, blob: bytes, label: str) -> None:
    if count < 0 or count > MAX_TABLE_ITEMS:
        raise AnalysisError(f"{label} count exceeds bound")
    checked_slice(blob, offset, count * width, label)


def decode_dex_string(blob: bytes, offset: int) -> str:
    declared_utf16, cursor = read_uleb(blob, offset, "DEX string length")
    end = blob.find(b"\0", cursor, min(len(blob), cursor + 1024 * 1024))
    if end < 0:
        raise AnalysisError("unterminated DEX string")
    raw = blob[cursor:end]
    # DEX uses Modified UTF-8: C0 80 represents U+0000. Surrogate sequences are
    # retained through surrogatepass, then combined by UTF-16 decoding.
    raw = raw.replace(b"\xc0\x80", b"\x00")
    try:
        intermediate = raw.decode("utf-8", errors="surrogatepass")
        utf16 = intermediate.encode("utf-16-le", errors="surrogatepass")
        value = utf16.decode("utf-16-le", errors="strict")
    except UnicodeError as exc:
        raise AnalysisError("invalid DEX Modified UTF-8") from exc
    if len(value.encode("utf-16-le")) // 2 != declared_utf16:
        raise AnalysisError("DEX string UTF-16 length mismatch")
    return value


DALVIK_WIDTHS = [1] * 256
for _opcode in (0x02, 0x05, 0x08, 0x13, 0x15, 0x16, 0x19, 0x1A, 0x1C, 0x1F, 0x20, 0x22, 0x23, 0x29): DALVIK_WIDTHS[_opcode] = 2
for _opcode in (0x03, 0x06, 0x09, 0x14, 0x17, 0x1B, 0x24, 0x25, 0x26, 0x2A, 0x2B, 0x2C): DALVIK_WIDTHS[_opcode] = 3
DALVIK_WIDTHS[0x18] = 5
for _opcode in (*range(0x2D, 0x3E), *range(0x44, 0x6E), *range(0x90, 0xB0), *range(0xD0, 0xE3), 0xFE, 0xFF): DALVIK_WIDTHS[_opcode] = 2
for _opcode in (*range(0x6E, 0x79), 0xFC, 0xFD): DALVIK_WIDTHS[_opcode] = 3
for _opcode in (0xFA, 0xFB): DALVIK_WIDTHS[_opcode] = 4


def dalvik_width(opcode: int) -> int:
    return DALVIK_WIDTHS[opcode]


def parse_dex(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_DEX_BYTES:
        raise AnalysisError("DEX exceeds byte bound")
    blob = path.read_bytes()
    if len(blob) < 112 or blob[:4] != b"dex\n" or blob[7] != 0:
        raise AnalysisError("invalid DEX magic")
    expected_checksum = unpack_from("<I", blob, 8, "DEX checksum")[0]
    expected_signature = checked_slice(blob, 12, 20, "DEX signature")
    checksum_valid = zlib.adler32(blob[12:]) & 0xFFFFFFFF == expected_checksum
    signature_valid = hashlib.sha1(blob[32:]).digest() == expected_signature
    if not checksum_valid or not signature_valid:
        raise AnalysisError("DEX checksum/signature integrity failure")
    values = unpack_from("<20I", blob, 32, "DEX header")
    (file_size, header_size, endian_tag, link_size, link_off, map_off,
     string_count, string_off, type_count, type_off, proto_count, proto_off,
     field_count, field_off, method_count, method_off, class_count, class_off,
     data_size, data_off) = values
    if file_size != len(blob) or header_size != 112 or endian_tag != 0x12345678:
        raise AnalysisError("invalid DEX header size/endian/file size")
    if data_off + data_size > len(blob) or (link_size and link_off + link_size > len(blob)):
        raise AnalysisError("invalid DEX data/link bounds")
    table_bounds(string_count, string_off, 4, blob, "string_ids")
    if string_count > MAX_STRING_ITEMS:
        raise AnalysisError("DEX string count exceeds bound")
    table_bounds(type_count, type_off, 4, blob, "type_ids")
    table_bounds(proto_count, proto_off, 12, blob, "proto_ids")
    table_bounds(field_count, field_off, 8, blob, "field_ids")
    table_bounds(method_count, method_off, 8, blob, "method_ids")
    table_bounds(class_count, class_off, 32, blob, "class_defs")

    map_size = unpack_from("<I", blob, map_off, "DEX map size")[0]
    if map_size > 512:
        raise AnalysisError("DEX map count exceeds bound")
    checked_slice(blob, map_off + 4, map_size * 12, "DEX map")
    map_items = []
    previous_offset = -1
    for index in range(map_size):
        item_type, unused, size, offset = unpack_from("<HHII", blob, map_off + 4 + index * 12, "DEX map item")
        if unused != 0 or offset >= len(blob) or size > MAX_TABLE_ITEMS:
            raise AnalysisError("invalid DEX map item")
        if offset < previous_offset:
            raise AnalysisError("DEX map offsets not ordered")
        previous_offset = offset
        map_items.append({"type": item_type, "size": size, "offset": offset})

    strings = []
    decoded_string_bytes = 0
    for index in range(string_count):
        offset = unpack_from("<I", blob, string_off + index * 4, "string_id")[0]
        value = decode_dex_string(blob, offset)
        decoded_string_bytes += len(value.encode("utf-8", errors="surrogatepass"))
        if decoded_string_bytes > MAX_DEX_STRING_BYTES:
            raise AnalysisError("DEX aggregate decoded strings exceed bound")
        strings.append(value)
    types = []
    for index in range(type_count):
        string_index = unpack_from("<I", blob, type_off + index * 4, "type_id")[0]
        if string_index >= string_count:
            raise AnalysisError("DEX type string index out of range")
        types.append(strings[string_index])

    def type_list(offset: int) -> list[str]:
        if offset == 0:
            return []
        count = unpack_from("<I", blob, offset, "type_list size")[0]
        if count > 65535:
            raise AnalysisError("DEX type list exceeds bound")
        checked_slice(blob, offset + 4, count * 2, "type_list")
        result = []
        for item in range(count):
            type_index = unpack_from("<H", blob, offset + 4 + item * 2, "type_list item")[0]
            if type_index >= type_count:
                raise AnalysisError("DEX type list index out of range")
            result.append(types[type_index])
        return result

    protos = []
    for index in range(proto_count):
        shorty_index, return_index, parameters_off = unpack_from("<III", blob, proto_off + index * 12, "proto_id")
        if shorty_index >= string_count or return_index >= type_count:
            raise AnalysisError("DEX proto index out of range")
        params = type_list(parameters_off)
        protos.append(f"({''.join(params)}){types[return_index]}")
    fields = []
    for index in range(field_count):
        class_index, type_index, name_index = unpack_from("<HHI", blob, field_off + index * 8, "field_id")
        if class_index >= type_count or type_index >= type_count or name_index >= string_count:
            raise AnalysisError("DEX field index out of range")
        fields.append(f"{types[class_index]}->{strings[name_index]}:{types[type_index]}")
    methods = []
    method_parts = []
    for index in range(method_count):
        class_index, proto_index, name_index = unpack_from("<HHI", blob, method_off + index * 8, "method_id")
        if class_index >= type_count or proto_index >= proto_count or name_index >= string_count:
            raise AnalysisError("DEX method index out of range")
        method_parts.append((types[class_index], strings[name_index], protos[proto_index]))
        methods.append(f"{types[class_index]}->{strings[name_index]}{protos[proto_index]}")

    classes = []
    packages: Counter[str] = Counter()
    method_refs: set[str] = set()
    string_refs: set[str] = set()
    type_refs: set[str] = set()
    invoke_edges: set[tuple[str, str]] = set()
    native_methods: set[str] = set()
    code_items = 0
    instruction_count = 0
    malformed_code = 0

    def walk_code(owner: str, code_offset: int) -> None:
        nonlocal code_items, instruction_count, malformed_code
        if not code_offset:
            return
        if code_items >= MAX_CODE_ITEMS:
            raise AnalysisError("DEX code item bound exceeded")
        code_items += 1
        try:
            registers, ins, outs, tries, debug_off, insns_size = unpack_from("<HHHHII", blob, code_offset, "code_item")
            if insns_size > MAX_INSTRUCTIONS or instruction_count + insns_size > MAX_INSTRUCTIONS:
                raise AnalysisError("DEX instruction bound exceeded")
            units_blob = checked_slice(blob, code_offset + 16, insns_size * 2, "code_item instructions")
            units = struct.unpack(f"<{insns_size}H", units_blob) if insns_size else ()
            cursor = 0
            while cursor < insns_size:
                first = units[cursor]
                opcode = first & 0xFF
                if opcode == 0 and first >> 8 in {1, 2, 3}:
                    payload_type = first >> 8
                    if payload_type == 1:
                        size = units[cursor + 1] if cursor + 1 < insns_size else 0
                        width = 4 + size * 2
                    elif payload_type == 2:
                        size = units[cursor + 1] if cursor + 1 < insns_size else 0
                        width = 2 + size * 4
                    else:
                        element_width = units[cursor + 1] if cursor + 1 < insns_size else 0
                        size = (units[cursor + 2] | units[cursor + 3] << 16) if cursor + 3 < insns_size else 0
                        width = 4 + (element_width * size + 1) // 2
                else:
                    width = dalvik_width(opcode)
                if width <= 0 or cursor + width > insns_size:
                    malformed_code += 1
                    break
                reference_index = units[cursor + 1] if width > 1 else None
                if opcode == 0x1A and reference_index is not None and reference_index < len(strings):
                    string_refs.add(strings[reference_index])
                elif opcode == 0x1B and cursor + 2 < insns_size:
                    idx = units[cursor + 1] | units[cursor + 2] << 16
                    if idx < len(strings): string_refs.add(strings[idx])
                elif opcode in {0x1C, 0x1F, 0x20, 0x22, 0x23, 0x24, 0x25} and reference_index is not None and reference_index < len(types):
                    type_refs.add(types[reference_index])
                elif (0x6E <= opcode <= 0x72 or 0x74 <= opcode <= 0x78 or opcode in {0xFA, 0xFB}) and reference_index is not None and reference_index < len(methods):
                    method_refs.add(methods[reference_index])
                    invoke_edges.add((owner, methods[reference_index]))
                cursor += width
            instruction_count += insns_size
        except (AnalysisError, struct.error, IndexError):
            malformed_code += 1

    for class_index in range(class_count):
        values = unpack_from("<8I", blob, class_off + class_index * 32, "class_def")
        type_index, access, super_index, interfaces_off, source_index, annotations_off, class_data_off, static_values_off = values
        if type_index >= type_count or (super_index != 0xFFFFFFFF and super_index >= type_count):
            raise AnalysisError("DEX class index out of range")
        descriptor = types[type_index]
        classes.append(descriptor)
        package = descriptor[1:descriptor.rfind("/")] if descriptor.startswith("L") and "/" in descriptor else "[default]"
        packages[package] += 1
        if interfaces_off:
            type_refs.update(type_list(interfaces_off))
        if not class_data_off:
            continue
        cursor = class_data_off
        counts = []
        for label in ("static fields", "instance fields", "direct methods", "virtual methods"):
            count, cursor = read_uleb(blob, cursor, f"class_data {label}")
            if count > MAX_TABLE_ITEMS:
                raise AnalysisError("DEX class_data count exceeds bound")
            counts.append(count)
        for count in counts[:2]:
            field_index = 0
            for _ in range(count):
                diff, cursor = read_uleb(blob, cursor, "encoded field index")
                access_flags, cursor = read_uleb(blob, cursor, "encoded field access")
                field_index += diff
                if field_index >= len(fields):
                    raise AnalysisError("encoded field index out of range")
        for count in counts[2:]:
            method_index = 0
            for _ in range(count):
                diff, cursor = read_uleb(blob, cursor, "encoded method index")
                access_flags, cursor = read_uleb(blob, cursor, "encoded method access")
                code_offset, cursor = read_uleb(blob, cursor, "encoded method code")
                method_index += diff
                if method_index >= len(methods):
                    raise AnalysisError("encoded method index out of range")
                if access_flags & 0x100:
                    native_methods.add(methods[method_index])
                walk_code(methods[method_index], code_offset)

    identifiers = sorted(filter(None, (bounded_identifier(item) for item in itertools.chain(classes, methods, fields))))
    load_methods = sorted(method for method in method_refs if method.startswith("Ljava/lang/System;->load") or "loadLibrary" in method)
    library_strings = sorted({value for value in string_refs if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.+-]{1,100}", value) and (value.startswith("lib") or ".so" in value)})
    semantic = {
        "classes": set_digest(classes), "types": set_digest(types), "protos": set_digest(protos),
        "fields": set_digest(fields), "methods": set_digest(methods),
        "invoked_methods": set_digest(method_refs), "referenced_strings": set_digest(string_refs),
        "referenced_types": set_digest(type_refs), "native_methods": set_digest(native_methods),
    }
    return {
        "path": path.name, "sha256": hashlib.sha256(blob).hexdigest(), "version": blob[4:7].decode("ascii", "replace"),
        "integrity": {"adler32_checksum_valid": checksum_valid, "sha1_signature_valid": signature_valid},
        "parse_status": "success", "header_bounds_valid": True, "map_order_bounds_valid": True, "full_map_header_correspondence_validated": False,
        "map_items": map_items,
        "counts": {"strings": string_count, "types": type_count, "protos": proto_count, "fields": field_count,
                   "methods": method_count, "classes": class_count, "packages": len(packages), "code_items": code_items,
                   "instruction_code_units": instruction_count, "malformed_code_items": malformed_code,
                   "invoke_references": len(method_refs), "string_references": len(string_refs), "type_references": len(type_refs),
                   "native_methods": len(native_methods)},
        "class_inventory": sorted(classes), "package_inventory": dict(sorted(packages.items())),
        "semantic_digests": semantic, "semantic_sets": {
            "classes": sorted(classes), "types": sorted(types), "protos": sorted(protos), "fields": sorted(fields),
            "methods": sorted(methods), "invoked_methods": sorted(method_refs), "referenced_strings": sorted(string_refs),
            "referenced_types": sorted(type_refs), "native_methods": sorted(native_methods)},
        "invoke_edges": [list(edge) for edge in sorted(invoke_edges)[:MAX_GRAPH_EDGES_PER_LAYER]],
        "load_library_candidates": load_methods, "library_string_candidates": library_strings,
        "jni_candidates": sorted(native_methods), "identifier_samples": identifiers[:MAX_REPORT_IDENTIFIERS],
        "interpretation": "bounded static table and instruction-reference traversal; not decompilation",
    }


def c_string(blob: bytes, offset: int, limit: int = 65536) -> str:
    if offset < 0 or offset >= len(blob):
        return ""
    end = blob.find(b"\0", offset, min(len(blob), offset + limit))
    if end < 0:
        end = min(len(blob), offset + limit)
    return blob[offset:end].decode("utf-8", errors="replace")


def printable_strings(blob: bytes) -> list[dict[str, Any]]:
    result = []
    pattern = re.compile(rb"[\x20-\x7e]{4,}")
    for match in pattern.finditer(blob, 0, min(len(blob), MAX_PRINTABLE_SCAN)):
        text = match.group().decode("ascii", errors="strict")
        terms = sorted(term for term in MECHANICS_TERMS if term in text.casefold())
        if terms:
            result.append({"offset": match.start(), "text": text[:240], "terms": terms})
        if len(result) >= MAX_PRINTABLE_STRINGS:
            break
    return result


def parse_elf(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_ELF_BYTES:
        raise AnalysisError("ELF exceeds byte bound")
    blob = path.read_bytes()
    result_items = 0
    result_bytes = 0

    def reserve_result(items: int, byte_estimate: int, label: str) -> None:
        nonlocal result_items, result_bytes
        if items < 0 or byte_estimate < 0 or result_items + items > MAX_ELF_RESULT_ITEMS or result_bytes + byte_estimate > MAX_ELF_RESULT_BYTES:
            raise AnalysisError(f"ELF aggregate {label} result bound exceeded")
        result_items += items
        result_bytes += byte_estimate

    if len(blob) < 52 or blob[:4] != b"\x7fELF" or blob[4] not in (1, 2) or blob[5] not in (1, 2):
        raise AnalysisError("invalid ELF identification")
    bits = 32 if blob[4] == 1 else 64
    endian = "<" if blob[5] == 1 else ">"
    if bits == 32:
        header = unpack_from(endian + "HHIIIIIHHHHHH", blob, 16, "ELF32 header")
        e_type, machine, version, entry, phoff, shoff, flags, ehsize, phentsize, phnum, shentsize, shnum, shstrndx = header
        phfmt, shfmt = endian + "IIIIIIII", endian + "IIIIIIIIII"
    else:
        header = unpack_from(endian + "HHIQQQIHHHHHH", blob, 16, "ELF64 header")
        e_type, machine, version, entry, phoff, shoff, flags, ehsize, phentsize, phnum, shentsize, shnum, shstrndx = header
        phfmt, shfmt = endian + "IIQQQQQQ", endian + "IIQQQQIIQQ"
    if phnum > 65535 or shnum > 65535 or (phnum and phentsize < struct.calcsize(phfmt)) or (shnum and shentsize < struct.calcsize(shfmt)):
        raise AnalysisError("invalid ELF table dimensions")
    if phnum: checked_slice(blob, phoff, phnum * phentsize, "program headers")
    if shnum: checked_slice(blob, shoff, shnum * shentsize, "section headers")
    programs = []
    for index in range(phnum):
        raw = unpack_from(phfmt, blob, phoff + index * phentsize, "program header")
        if bits == 32:
            p_type, offset, vaddr, paddr, filesz, memsz, p_flags, align = raw
        else:
            p_type, p_flags, offset, vaddr, paddr, filesz, memsz, align = raw
        if filesz: checked_slice(blob, offset, filesz, "program segment")
        programs.append({"type": p_type, "flags": p_flags, "offset": offset, "vaddr": vaddr, "filesz": filesz, "memsz": memsz})
    sections_raw = []
    for index in range(shnum):
        raw = unpack_from(shfmt, blob, shoff + index * shentsize, "section header")
        name, section_type, section_flags, address, offset, size, link, info, alignment, entsize = raw
        if section_type != 8 and size: checked_slice(blob, offset, size, "section")
        sections_raw.append({"name_offset": name, "type": section_type, "flags": section_flags, "address": address,
                             "offset": offset, "size": size, "link": link, "info": info, "entsize": entsize})
    shstr = b""
    if sections_raw and shstrndx < len(sections_raw):
        item = sections_raw[shstrndx]
        shstr = checked_slice(blob, item["offset"], item["size"], "section name table")
    for section in sections_raw:
        section["name"] = c_string(shstr, section["name_offset"], 4096) if shstr else ""

    symbols = []
    for section in sections_raw:
        if section["type"] not in (2, 11) or not section["entsize"] or section["link"] >= len(sections_raw):
            continue
        string_section = sections_raw[section["link"]]
        strings = checked_slice(blob, string_section["offset"], string_section["size"], "symbol string table")
        count = section["size"] // section["entsize"]
        expected_symbol_size = 16 if bits == 32 else 24
        if section["size"] % section["entsize"] or section["entsize"] < expected_symbol_size:
            raise AnalysisError("invalid ELF symbol entry size")
        if count > MAX_TABLE_ITEMS: raise AnalysisError("ELF symbol count exceeds bound")
        reserve_result(count, count * 192, "symbol")
        for index in range(count):
            offset = section["offset"] + index * section["entsize"]
            if bits == 32:
                name_off, value, size, info, other, shndx = unpack_from(endian + "IIIBBH", blob, offset, "ELF32 symbol")
            else:
                name_off, info, other, shndx, value, size = unpack_from(endian + "IBBHQQ", blob, offset, "ELF64 symbol")
            name = c_string(strings, name_off) if name_off < len(strings) else ""
            if name:
                symbols.append({"name": name, "bind": info >> 4, "type": info & 0xF, "value": value, "size": size,
                                "section_index": shndx, "table": section["name"]})

    dynamic = []
    for section in sections_raw:
        if section["type"] != 6 or not section["entsize"]:
            continue
        count = section["size"] // section["entsize"]
        expected_dynamic_size = 8 if bits == 32 else 16
        if section["size"] % section["entsize"] or section["entsize"] < expected_dynamic_size or count > MAX_TABLE_ITEMS:
            raise AnalysisError("invalid ELF dynamic entry dimensions")
        reserve_result(count, count * 40, "dynamic")
        for index in range(count):
            fmt = endian + ("iI" if bits == 32 else "qQ")
            tag, value = unpack_from(fmt, blob, section["offset"] + index * section["entsize"], "dynamic tag")
            dynamic.append((tag, value, section.get("link", 0)))
            if tag == 0: break
    dynamic_strings = b""
    dynamic_link = next((link for _, _, link in dynamic if link < len(sections_raw)), None)
    if dynamic_link is not None:
        item = sections_raw[dynamic_link]
        dynamic_strings = checked_slice(blob, item["offset"], item["size"], "dynamic strings")
    needed = sorted(c_string(dynamic_strings, value) for tag, value, _ in dynamic if tag == 1 and value < len(dynamic_strings))
    sonames = sorted(c_string(dynamic_strings, value) for tag, value, _ in dynamic if tag == 14 and value < len(dynamic_strings))

    relocations = []
    for section in sections_raw:
        if section["type"] not in (4, 9) or not section["entsize"]:
            continue
        count = section["size"] // section["entsize"]
        expected_relocation_size = (12 if section["type"] == 4 else 8) if bits == 32 else (24 if section["type"] == 4 else 16)
        if section["size"] % section["entsize"] or section["entsize"] < expected_relocation_size:
            raise AnalysisError("invalid ELF relocation entry size")
        if count > MAX_TABLE_ITEMS: raise AnalysisError("ELF relocation count exceeds bound")
        reserve_result(count, count * 112, "relocation")
        for index in range(count):
            offset = section["offset"] + index * section["entsize"]
            if bits == 32:
                if section["type"] == 4: rel_offset, info, addend = unpack_from(endian + "IIi", blob, offset, "ELF32 RELA")
                else: rel_offset, info = unpack_from(endian + "II", blob, offset, "ELF32 REL"); addend = None
                symbol_index, rel_type = info >> 8, info & 0xFF
            else:
                if section["type"] == 4: rel_offset, info, addend = unpack_from(endian + "QQq", blob, offset, "ELF64 RELA")
                else: rel_offset, info = unpack_from(endian + "QQ", blob, offset, "ELF64 REL"); addend = None
                symbol_index, rel_type = info >> 32, info & 0xFFFFFFFF
            relocations.append({"section": section["name"], "offset": rel_offset, "type": rel_type, "symbol_index": symbol_index, "addend": addend})

    build_ids = []
    for section in sections_raw:
        if section["type"] != 7:
            continue
        cursor, end = section["offset"], section["offset"] + section["size"]
        while cursor + 12 <= end:
            namesz, descsz, note_type = unpack_from(endian + "III", blob, cursor, "ELF note")
            cursor += 12
            name = checked_slice(blob, cursor, namesz, "ELF note name").rstrip(b"\0")
            cursor += (namesz + 3) & ~3
            desc = checked_slice(blob, cursor, descsz, "ELF note desc")
            cursor += (descsz + 3) & ~3
            if name == b"GNU" and note_type == 3:
                build_ids.append(desc.hex())
    imports = sorted((item for item in symbols if item["section_index"] == 0), key=lambda item: (item["name"], item["table"]))
    exports = sorted((item for item in symbols if item["section_index"] != 0 and item["bind"] in (1, 2)), key=lambda item: (item["name"], item["table"]))
    jni = sorted({item["name"] for item in exports if item["name"].startswith("Java_") or item["name"] in {"JNI_OnLoad", "JNI_OnUnload"}})
    focused_strings = printable_strings(blob)
    reserve_result(len(focused_strings), sum(96 + len(item["text"]) for item in focused_strings), "focused string")
    mechanics = Counter(term for item in focused_strings for term in item["terms"])
    return {
        "path": path.name, "sha256": hashlib.sha256(blob).hexdigest(), "class": bits,
        "endianness": "little" if endian == "<" else "big", "type": e_type, "machine": machine,
        "parse_status": "success", "header_bounds_valid": True, "program_header_count": phnum, "section_header_count": shnum,
        "sections": [{key: item[key] for key in ("name", "type", "flags", "address", "offset", "size", "link", "info", "entsize")} for item in sections_raw],
        "dynamic_tags": [{"tag": tag, "value": value} for tag, value, _ in dynamic],
        "needed": needed, "soname": sonames, "build_ids": sorted(build_ids),
        "imports": imports, "exports": exports, "relocations": relocations,
        "stripped": not any(item["name"] == ".symtab" for item in sections_raw),
        "jni_candidates": jni, "mechanics_term_counts": dict(sorted(mechanics.items())),
        "focused_printable_strings": focused_strings,
    }


def decode_text(blob: bytes) -> tuple[str | None, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return blob.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return None, "decode-failed"


def decode_data_container(blob: bytes) -> tuple[bytes | None, dict[str, Any]]:
    text, encoding = decode_text(blob)
    if text is not None and (not blob or blob[:1].isalpha() or blob[:1] in (b'"', b"#", b"[", b"{")):
        return blob, {"raw_decode_status": "text", "container_decode_status": "not-needed", "container_format": "raw", "encoding_probe": encoding}
    if len(blob) < 9:
        return None, {"raw_decode_status": "non-text", "container_decode_status": "invalid-header", "container_format": "unknown"}
    declared_size = int.from_bytes(blob[5:9], "little")
    if declared_size > MAX_DECODED_DATA_BYTES:
        return None, {"raw_decode_status": "non-text", "container_decode_status": "expanded-size-limit", "container_format": "supercell-lzma", "declared_size": declared_size}
    candidates = (("supercell-lzma-4-byte-size", blob[:9] + b"\x00" * 4 + blob[9:]), ("lzma-alone", blob))
    for label, candidate in candidates:
        try:
            decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
            expanded = decoder.decompress(candidate, max_length=MAX_DECODED_DATA_BYTES + 1)
            if len(expanded) > MAX_DECODED_DATA_BYTES:
                return None, {"raw_decode_status": "non-text", "container_decode_status": "expanded-size-limit", "container_format": label, "declared_size": declared_size}
            if not decoder.eof or decoder.unused_data:
                continue
            if label.startswith("supercell") and declared_size != len(expanded):
                continue
            return expanded, {"raw_decode_status": "non-text", "container_decode_status": "success", "container_format": label, "declared_size": declared_size, "expanded_size": len(expanded)}
        except lzma.LZMAError:
            continue
    return None, {"raw_decode_status": "non-text", "container_decode_status": "failed", "container_format": "supercell-lzma-or-lzma-alone", "declared_size": declared_size}


def value_shape(value: Any) -> str:
    if value is None: return "null"
    if isinstance(value, bool): return "boolean"
    if isinstance(value, int): return "integer"
    if isinstance(value, float): return "float"
    if isinstance(value, list): return "array"
    if isinstance(value, dict): return "table"
    stripped = str(value).strip()
    if not stripped: return "empty"
    if stripped.casefold() in {"true", "false"}: return "boolean"
    if re.fullmatch(r"[+-]?\d+", stripped): return "integer"
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?", stripped): return "float"
    return "string"


def normalized_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.strip())
    if isinstance(value, float):
        return format(value, ".17g")
    if isinstance(value, (bool, int)) or value is None:
        return value
    return stable_json(value)


def looks_like_supercell_type_row(row: Sequence[str], width: int) -> bool:
    if len(row) != width or not row:
        return False
    type_pattern = re.compile(r"^(?:string|int(?:eger)?|long|float|double|bool(?:ean)?|date|time|array|list|enum|reference|ref|scid|id|[A-Za-z][A-Za-z0-9_]*(?:\[\])?)$", re.IGNORECASE)
    nonempty = [cell.strip() for cell in row if cell.strip()]
    return bool(nonempty) and len(nonempty) >= max(1, width // 2) and sum(bool(type_pattern.fullmatch(cell)) for cell in nonempty) / len(nonempty) >= 0.8


def analyze_csv(blob: bytes) -> dict[str, Any]:
    decoded, decode = decode_data_container(blob)
    if decoded is None:
        return {**decode, "text_decode_status": "not-attempted", "parse_status": "not-attempted"}
    text, encoding = decode_text(decoded)
    if text is None:
        return {**decode, "text_decode_status": "failed", "encoding": encoding, "parse_status": "not-attempted"}
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader, [])
        if len(header) > MAX_DATA_COLUMNS or any(len(cell) > MAX_DATA_CELL_CHARS for cell in header):
            return {**decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "cell-limit"}
        width = len(header)
        second = next(reader, None)
        cells = len(header) + (len(second) if second is not None else 0)
        if second is not None and (len(second) > MAX_DATA_COLUMNS or any(len(cell) > MAX_DATA_CELL_CHARS for cell in second)):
            return {**decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "cell-limit"}
        has_type_row = second is not None and looks_like_supercell_type_row(second, width)
        normalized_types = ([cell.strip().casefold() for cell in second] if has_type_row else [""] * width)
        schema = [(header[index].strip(), normalized_types[index]) for index in range(width)]
        key_index = next((index for index, name in enumerate(header) if name.strip().casefold() in {"name", "key", "id", "sc_key"}), None)
        rows: Iterator[list[str]] = iter(()) if second is None else itertools.chain(() if has_type_row else (second,), reader)
        keyed_values: dict[str, str] = {}
        duplicate_keys = False
        shapes: Counter[tuple[str, str]] = Counter()
        row_count = 0
        for row in rows:
            row_count += 1
            cells += len(row)
            if row_count > MAX_DATA_ROWS or cells > MAX_DATA_CELLS:
                return {**decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "row-or-cell-limit"}
            if len(row) > MAX_DATA_COLUMNS or any(len(cell) > MAX_DATA_CELL_CHARS for cell in row):
                return {**decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "cell-limit"}
            normalized_row = [normalized_scalar(row[index] if index < len(row) else "") for index in range(width)]
            for index, value in enumerate(normalized_row):
                shapes[(header[index].strip(), value_shape(value))] += 1
            if key_index is not None and key_index < len(normalized_row) and normalized_row[key_index] != "":
                key = str(normalized_row[key_index])
                if key in keyed_values:
                    duplicate_keys = True
                else:
                    keyed_values[key] = stable_hash(normalized_row)
    except (csv.Error, MemoryError) as exc:
        return {**decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "failed", "error": type(exc).__name__}
    key_set = sorted(keyed_values)
    return {
        **decode, "text_decode_status": "success", "encoding": encoding, "parse_status": "success",
        "row_count": row_count, "column_count": width, "type_row_detected": has_type_row,
        "header_hash": stable_hash([cell.strip() for cell in header]), "schema_hash": stable_hash(schema),
        "type_hash": stable_hash(normalized_types), "row_key_hash": stable_hash(key_set),
        "row_key_count": len(key_set), "duplicate_keys": duplicate_keys,
        "keyed_value_digest": stable_hash(sorted(keyed_values.items())) if key_index is not None and not duplicate_keys else None,
        "shape_hash": stable_hash(sorted((list(key), count) for key, count in shapes.items())),
    }


def flatten_toml(value: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], str, Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from flatten_toml(value[key], prefix + (str(key),))
    elif isinstance(value, list):
        yield prefix, "array", [normalized_scalar(item) if not isinstance(item, (dict, list)) else stable_hash(item) for item in value]
    else:
        yield prefix, value_shape(value), normalized_scalar(value)


def analyze_toml(blob: bytes) -> dict[str, Any]:
    decoded, decode = decode_data_container(blob)
    if decoded is None:
        return {**decode, "text_decode_status": "not-attempted", "parse_status": "not-attempted"}
    try:
        document = tomllib.loads(decoded.decode("utf-8-sig"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, MemoryError) as exc:
        return {**decode, "text_decode_status": "failed" if isinstance(exc, UnicodeDecodeError) else "success", "encoding": "utf-8", "parse_status": "failed", "error": type(exc).__name__}
    flattened = list(flatten_toml(document))
    if len(flattened) > MAX_DATA_CELLS:
        return {**decode, "text_decode_status": "success", "encoding": "utf-8", "parse_status": "cell-limit"}
    paths = [".".join(path) for path, _, _ in flattened]
    schema = [(path, shape) for (parts, shape, _), path in zip(flattened, paths)]
    values = [(path, normalized) for (parts, shape, normalized), path in zip(flattened, paths)]
    return {
        **decode, "text_decode_status": "success", "encoding": "utf-8", "parse_status": "success",
        "table_count": sum(isinstance(value, dict) for value in document.values()), "key_count": len(flattened),
        "header_hash": stable_hash(sorted(paths)), "schema_hash": stable_hash(schema), "type_hash": stable_hash(schema),
        "row_key_hash": stable_hash(sorted(paths)), "row_key_count": len(paths), "duplicate_keys": False,
        "keyed_value_digest": stable_hash(values),
    }


def magic_label(blob: bytes) -> str:
    signatures = ((b"\xabKTX 11\xbb\r\n\x1a\n", "KTX1"), (b"\xabKTX 20\xbb\r\n\x1a\n", "KTX2"),
                  (b"glTF", "GLB"), (b"BKHD", "FMOD_BANK"), (b"SQLite format 3\0", "SQLITE"))
    for signature, label in signatures:
        if blob.startswith(signature): return label
    return "UNKNOWN:" + blob[:16].hex()


def validate_entry_manifest(entries: Any, record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    slug = safe_component(str(record["safe_name"]), "APK safe name")
    if not isinstance(entries, list) or len(entries) != record["entry_count"]:
        raise AnalysisError(f"entry count mismatch for {slug}")
    manifest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        relative = PurePosixPath(entry["path"])
        if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise AnalysisError(f"unsafe manifest path for {slug}")
        path_key = "/".join(relative.parts).casefold()
        if path_key in manifest:
            raise AnalysisError(f"duplicate manifest path for {slug}")
        if not isinstance(entry.get("size"), int) or entry["size"] < 0 or not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))):
            raise AnalysisError(f"invalid manifest metadata for {slug}/{entry['path']}")
        manifest[path_key] = entry
    return manifest


def verify_extraction(record: dict[str, Any], verify_archive: bool = True) -> tuple[list[dict[str, Any]], Path, dict[str, Any]]:
    slug = safe_component(str(record["safe_name"]), "APK safe name")
    record_root = contained_path(REFERENCE_ROOT, [slug], "APK record path")
    entries_path = record_root / "entries.json"
    extract_root = record_root / "extracted"
    if not entries_path.is_file() or not extract_root.is_dir():
        raise AnalysisError(f"missing validated extraction for {slug}")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    manifest = validate_entry_manifest(entries, record)
    for path_key, entry in manifest.items():
        relative = PurePosixPath(entry["path"])
        path = contained_path(extract_root, list(relative.parts), "extraction entry")
        if not path.is_file() or path.stat().st_size != entry["size"] or sha256_path(path) != entry["sha256"]:
            raise AnalysisError(f"extraction digest mismatch: {slug}/{entry['path']}")
    binding = {"entries_manifest_sha256": sha256_path(entries_path), "entries_verified": len(entries), "archive_bound": False}
    if verify_archive:
        archive_path = Path(record["source_path"])
        archive_digest = hashlib.sha256()
        zip_seen: set[str] = set()
        with archive_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                archive_digest.update(block)
        if archive_digest.hexdigest() != record["sha256"]:
            raise AnalysisError(f"original APK digest mismatch: {record['filename']}")
        with zipfile.ZipFile(archive_path, "r") as archive:
            for info in archive.infolist():
                relative = PurePosixPath(info.filename)
                if info.is_dir():
                    continue
                if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
                    raise AnalysisError(f"unsafe archive path for {slug}")
                path_key = "/".join(relative.parts).casefold()
                if path_key in zip_seen or path_key not in manifest:
                    raise AnalysisError(f"archive/manifest path mismatch for {slug}/{info.filename}")
                zip_seen.add(path_key)
                expected = manifest[path_key]
                digest = hashlib.sha256()
                size = 0
                with archive.open(info, "r") as member:
                    for block in iter(lambda: member.read(1024 * 1024), b""):
                        size += len(block)
                        if size > expected["size"]:
                            raise AnalysisError(f"archive entry size mismatch: {slug}/{info.filename}")
                        digest.update(block)
                if size != expected["size"] or digest.hexdigest() != expected["sha256"]:
                    raise AnalysisError(f"archive entry digest mismatch: {slug}/{info.filename}")
        if zip_seen != set(manifest):
            raise AnalysisError(f"archive missing manifest entries for {slug}")
        binding.update({"archive_bound": True, "archive_sha256": archive_digest.hexdigest(), "archive_entries_verified": len(zip_seen)})
    return entries, extract_root, binding


def analyze_apk(record: dict[str, Any]) -> dict[str, Any]:
    entries, extract_root, source_binding = verify_extraction(record)
    dex_results, native_results, data_results, proprietary = [], [], [], []
    for entry in entries:
        path = contained_path(extract_root, list(PurePosixPath(entry["path"]).parts), "analysis entry")
        suffix = path.suffix.casefold()
        try:
            if entry["category"] == "dex":
                item = parse_dex(path); item["apk_path"] = entry["path"]; dex_results.append(item)
            elif entry["category"] == "native" and suffix == ".so":
                item = parse_elf(path); item["apk_path"] = entry["path"]; native_results.append(item)
            elif suffix in DATA_SUFFIXES:
                if entry["size"] > MAX_DATA_BYTES:
                    parsed = {"raw_decode_status": "not-attempted", "container_decode_status": "not-attempted", "text_decode_status": "not-attempted", "parse_status": "size-limit"}
                else:
                    blob = path.read_bytes()
                    parsed = analyze_csv(blob) if suffix == ".csv" else analyze_toml(blob)
                parsed.update({"path": entry["path"], "suffix": suffix, "size": entry["size"], "sha256": entry["sha256"]})
                data_results.append(parsed)
            if suffix in PROPRIETARY_SUFFIXES:
                with path.open("rb") as handle: prefix = handle.read(32)
                proprietary.append({"path": entry["path"], "extension": suffix, "magic": magic_label(prefix),
                                    "size": entry["size"], "sha256": entry["sha256"], "status": "unsupported"})
        except (AnalysisError, OSError, UnicodeError, struct.error) as exc:
            target = dex_results if entry["category"] == "dex" else native_results if entry["category"] == "native" else data_results
            target.append({"apk_path" if entry["category"] in {"dex", "native"} else "path": entry["path"],
                           "sha256": entry["sha256"], "parse_status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    dex_results.sort(key=lambda item: item.get("apk_path", "")); native_results.sort(key=lambda item: item.get("apk_path", ""))
    data_results.sort(key=lambda item: item.get("path", "")); proprietary.sort(key=lambda item: item["path"])
    classes = {(dex.get("apk_path"), value) for dex in dex_results for value in dex.get("semantic_sets", {}).get("classes", [])}
    methods = {(dex.get("apk_path"), value) for dex in dex_results for value in dex.get("semantic_sets", {}).get("methods", [])}
    native_components = {(native.get("apk_path"), value) for native in native_results for value in native.get("needed", []) + native.get("soname", [])}
    native_components |= {(native.get("apk_path"), item["name"]) for native in native_results for item in native.get("imports", []) + native.get("exports", [])}
    return {
        "safe_name": record["safe_name"], "filename": record["filename"], "apk_sha256": record["sha256"],
        "manifest": record.get("manifest", {}), "package": record.get("manifest", {}).get("package"), "entry_count": len(entries),
        "source_binding": source_binding,
        "entries": entries, "dex": dex_results, "native": native_results, "data": data_results,
        "proprietary": proprietary,
        "semantic_sets": {"dex_classes": sorted(classes), "dex_methods": sorted(methods), "native_components": sorted(native_components)},
    }


def compare_data(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_map = {item["path"]: item for item in left["data"]}; right_map = {item["path"]: item for item in right["data"]}
    distinctions = Counter()
    changed = []
    for path in sorted(left_map.keys() & right_map.keys()):
        a, b = left_map[path], right_map[path]
        if a["sha256"] == b["sha256"]: distinction = "IDENTICAL"
        elif (a.get("parse_status") != "success" or b.get("parse_status") != "success" or
              a.get("schema_hash") != b.get("schema_hash") or a.get("row_key_hash") != b.get("row_key_hash") or
              a.get("keyed_value_digest") is None or b.get("keyed_value_digest") is None):
            distinction = "UNRESOLVED_CHANGE"
        elif a.get("keyed_value_digest") != b.get("keyed_value_digest"):
            distinction = "VALUE_ONLY_CHANGE"
        else:
            distinction = "NORMALIZED_FORMAT_CHANGE"
        distinctions[distinction] += 1
        if distinction != "IDENTICAL" and len(changed) < MAX_MANIFEST_PATHS:
            changed.append({"path": path, "distinction": distinction, "left_sha256": a["sha256"], "right_sha256": b["sha256"],
                            "left_schema_hash": a.get("schema_hash"), "right_schema_hash": b.get("schema_hash")})
    added = sorted(right_map.keys() - left_map.keys())
    removed = sorted(left_map.keys() - right_map.keys())
    return {"distinctions": dict(sorted(distinctions.items())), "changed": changed,
            "added_count": len(added), "removed_count": len(removed),
            "added": added[:MAX_MANIFEST_PATHS], "removed": removed[:MAX_MANIFEST_PATHS]}


def pair_compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    def entry_map(apk: dict[str, Any]) -> dict[str, str]:
        return {item["path"]: item["sha256"] for item in apk["entries"]}

    def path_hash_multiset(apk: dict[str, Any], suffixes: set[str] | None = None) -> Counter[tuple[str, str]]:
        items = Counter()
        for item in apk["entries"]:
            if suffixes is None or PurePosixPath(item["path"]).suffix.casefold() in suffixes:
                items[(item["path"], item["sha256"])] += 1
        return items

    def content_multiset(apk: dict[str, Any]) -> Counter[str]:
        return Counter(item["sha256"] for item in apk["entries"])

    def valid_dex(apk: dict[str, Any]) -> set[tuple[str, str]]:
        return {(dex.get("apk_path"), dex.get("sha256")) for dex in apk["dex"] if dex.get("parse_status") == "success"}

    def valid_native(apk: dict[str, Any]) -> set[tuple[str, str]]:
        return {(elf.get("apk_path"), elf.get("sha256")) for elf in apk["native"] if elf.get("parse_status") == "success"}

    left_entries, right_entries = entry_map(left), entry_map(right)
    left_names = Counter(PurePosixPath(path).name for path in left_entries)
    right_names = Counter(PurePosixPath(path).name for path in right_entries)
    left_path_hash, right_path_hash = path_hash_multiset(left), path_hash_multiset(right)
    left_data_total = path_hash_multiset(left, DATA_SUFFIXES); right_data_total = path_hash_multiset(right, DATA_SUFFIXES)
    left_data_parseable = Counter((item["path"], item["sha256"]) for item in left["data"] if item.get("parse_status") == "success")
    right_data_parseable = Counter((item["path"], item["sha256"]) for item in right["data"] if item.get("parse_status") == "success")
    left_data_opaque = Counter((item["path"], item["sha256"]) for item in left["data"] if item.get("parse_status") != "success")
    right_data_opaque = Counter((item["path"], item["sha256"]) for item in right["data"] if item.get("parse_status") != "success")
    left_dex_semantics = Counter(left["semantic_sets"]["dex_classes"] + left["semantic_sets"]["dex_methods"])
    right_dex_semantics = Counter(right["semantic_sets"]["dex_classes"] + right["semantic_sets"]["dex_methods"])
    left_native_components = Counter(left["semantic_sets"]["native_components"])
    right_native_components = Counter(right["semantic_sets"]["native_components"])
    added = sorted(right_entries.keys() - left_entries.keys())
    removed = sorted(left_entries.keys() - right_entries.keys())
    changed = sorted(path for path in left_entries.keys() & right_entries.keys() if left_entries[path] != right_entries[path])
    dex_left, dex_right = valid_dex(left), valid_dex(right)
    native_left, native_right = valid_native(left), valid_native(right)
    similarities = {
        "basename_multiplicity_jaccard": multiset_jaccard(left_names, right_names),
        "path_hash_multiplicity_jaccard": multiset_jaccard(left_path_hash, right_path_hash),
        "content_hash_multiplicity_jaccard": multiset_jaccard(content_multiset(left), content_multiset(right)),
        "dex_semantic_path_multiplicity_jaccard": multiset_jaccard(left_dex_semantics, right_dex_semantics),
        "dex_implementation_path_hash_jaccard": jaccard(dex_left, dex_right),
        "native_component_path_multiplicity_jaccard": multiset_jaccard(left_native_components, right_native_components),
        "native_implementation_path_hash_jaccard": jaccard(native_left, native_right),
        "data_total_extension_path_hash_jaccard": jaccard(set(left_data_total), set(right_data_total)),
        "data_parseable_path_hash_jaccard": jaccard(set(left_data_parseable), set(right_data_parseable)),
        "data_opaque_path_hash_jaccard": jaccard(set(left_data_opaque), set(right_data_opaque)),
    }
    pair = {
        "left": left["safe_name"], "right": right["safe_name"], "similarities": similarities,
        "coverage": {
            "dex_both_parseable": bool(dex_left) and bool(dex_right),
            "native_both_parseable": bool(native_left) and bool(native_right),
            "data_both_present": bool(left_data_total) and bool(right_data_total),
            "data_both_parseable": bool(left_data_parseable) and bool(right_data_parseable),
        },
        "counts": {"added_paths": len(added), "removed_paths": len(removed), "changed_paths": len(changed)},
        "path_manifest": {"added": added[:MAX_MANIFEST_PATHS], "removed": removed[:MAX_MANIFEST_PATHS], "changed": changed[:MAX_MANIFEST_PATHS]},
        "data_delta": compare_data(left, right),
    }
    pair["classification"] = classify_pair(pair)
    return pair


def classify_apk(apk: dict[str, Any]) -> dict[str, str]:
    marker = f"{apk['filename']} {apk.get('package') or ''}".casefold()
    application_shell = "PRIVATE_SERVER_SPECIFIC" if any(value in marker for value in ("master", "nulls", "private")) else "UNKNOWN"
    return {"APPLICATION_SHELL": application_shell, "DEX_CLIENT": "UNKNOWN", "NATIVE_CLIENT": "UNKNOWN",
            "SELECTED_DATA": "UNKNOWN", "PROPRIETARY_ASSETS": "UNKNOWN"}


def classify_pair(pair: dict[str, Any]) -> dict[str, str]:
    values = pair["similarities"]
    dex = "UNCHANGED_SHARED_CLIENT" if pair["coverage"]["dex_both_parseable"] and values["dex_implementation_path_hash_jaccard"] == 1.0 else "UNKNOWN"
    native = "UNCHANGED_SHARED_CLIENT" if pair["coverage"]["native_both_parseable"] and values["native_implementation_path_hash_jaccard"] == 1.0 else "UNKNOWN"
    data = "UNCHANGED_SHARED_CLIENT" if pair["coverage"]["data_both_parseable"] and values["data_parseable_path_hash_jaccard"] == 1.0 else "UNKNOWN"
    return {"DEX_CLIENT": dex, "NATIVE_CLIENT": native, "SELECTED_DATA": data, "PROPRIETARY_ASSETS": "UNKNOWN"}


def jni_export_prefix(method: str) -> str | None:
    match = re.fullmatch(r"L([^;]+);->([^<(]+)\(.*", method)
    if not match:
        return None

    def encode(component: str) -> str:
        return component.replace("_", "_1").replace("$", "_00024").replace("/", "_")

    return f"Java_{encode(match.group(1))}_{encode(match.group(2))}"


def evidence_graph(apks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    per_apk_counts: Counter[str] = Counter()
    per_layer_counts: Counter[tuple[str, str]] = Counter()

    def add_node(node_id: str, kind: str, apk_name: str, **extra: Any) -> str:
        nodes.setdefault(node_id, {"kind": kind, "apk": apk_name, **extra})
        return node_id

    def add_edge(source: str, target: str, relation: str, evidence: str, apk_name: str, layer: str, locator: str, label: str) -> None:
        key = (source, target, relation)
        if key in edge_keys or per_apk_counts[apk_name] >= MAX_GRAPH_EDGES_PER_APK or per_layer_counts[(apk_name, layer)] >= MAX_GRAPH_EDGES_PER_LAYER:
            return
        edge_keys.add(key); per_apk_counts[apk_name] += 1; per_layer_counts[(apk_name, layer)] += 1
        edges.append({"source": source, "target": target, "relation": relation, "evidence": evidence, "apk": apk_name, "layer": layer, "source_locator": locator, "label": label})

    for apk in apks:
        name = apk["safe_name"]
        apk_node = add_node(f"apk:{name}", "apk", name)
        app_node = add_node(f"application:{name}", "application", name, package=apk.get("package"), label=apk.get("manifest", {}).get("application_label"))
        add_edge(apk_node, app_node, "declares_application", "direct", name, "manifest", "AndroidManifest.xml", "manifest application record")
        for entry in apk["entries"]:
            if entry["path"] == "AndroidManifest.xml":
                manifest_node = add_node(f"manifest:{name}", "manifest", name, path=entry["path"])
                add_edge(apk_node, manifest_node, "contains", "direct", name, "manifest", entry["path"], "archive manifest")
                add_edge(manifest_node, app_node, "describes", "direct", name, "manifest", entry["path"], "application metadata")
        dex_nodes: list[str] = []
        native_nodes: dict[str, str] = {}
        data_nodes: dict[str, str] = {}
        for dex in apk["dex"]:
            dex_path = dex.get("apk_path", "unknown")
            dex_node = add_node(f"dex:{name}:{dex_path}", "dex", name, path=dex_path, parse_status=dex.get("parse_status")); dex_nodes.append(dex_node)
            add_edge(apk_node, dex_node, "contains_dex", "direct", name, "archive-dex", dex_path, "APK DEX entry")
            loader_methods = dex.get("load_library_candidates", [])
            for loader_method in loader_methods:
                loader_node = add_node(f"method:{name}:{loader_method}", "method", name, name=loader_method)
                add_edge(dex_node, loader_node, "references_loader", "static", name, "dex-native", dex_path, "System load/loadLibrary method reference")
                add_edge(app_node, loader_node, "has_loader_candidate", "inferred", name, "manifest-dex", dex_path, "loader reference inside packaged DEX")
            for class_name in dex.get("class_inventory", [])[:MAX_MECHANICS_CHAINS_PER_APK]:
                class_node = add_node(f"class:{name}:{class_name}", "class", name, name=class_name)
                add_edge(dex_node, class_node, "defines", "static", name, "dex", dex_path, "class definition")
            for source, target in dex.get("invoke_edges", [])[:MAX_GRAPH_EDGES_PER_LAYER]:
                source_node = add_node(f"method:{name}:{source}", "method", name, name=source)
                target_node = add_node(f"method:{name}:{target}", "method", name, name=target)
                add_edge(source_node, target_node, "invokes", "static", name, "dex", dex_path, "method reference")
            for library in dex.get("library_string_candidates", []):
                library_name = library if library.endswith(".so") else f"{library if library.startswith('lib') else 'lib' + library}.so"
                library_node = add_node(f"library:{name}:{library_name}", "library", name, name=library_name)
                owner = dex.get("load_library_candidates", [None])[0] or dex_path
                owner_node = add_node(f"method:{name}:{owner}", "method", name, name=owner)
                add_edge(owner_node, library_node, "loads_library", "static", name, "dex-native", dex_path, "loadLibrary candidate")
        dex_native_methods = [method for dex in apk["dex"] for method in dex.get("jni_candidates", [])]
        for native in apk["native"]:
            native_path = native.get("apk_path", "unknown")
            native_node = add_node(f"elf:{name}:{native_path}", "elf", name, path=native_path, parse_status=native.get("parse_status")); native_nodes[PurePosixPath(native_path).name] = native_node
            add_edge(apk_node, native_node, "contains_native", "direct", name, "archive-native", native_path, "APK native entry")
            for needed in native.get("needed", []):
                lib_node = add_node(f"library:{name}:{needed}", "library", name, name=needed)
                add_edge(native_node, lib_node, "needs_library", "static", name, "native", native_path, "ELF DT_NEEDED")
            for jni_name in native.get("jni_candidates", []):
                jni_node = add_node(f"jni:{name}:{native_path}:{jni_name}", "jni", name, name=jni_name)
                add_edge(native_node, jni_node, "exports_jni", "static", name, "native-jni", native_path, "ELF JNI export")
                for dex_method in dex_native_methods:
                    prefix = jni_export_prefix(dex_method)
                    if prefix and (jni_name == prefix or jni_name.startswith(prefix + "__")):
                        method_node = add_node(f"method:{name}:{dex_method}", "method", name, name=dex_method)
                        add_edge(method_node, jni_node, "may_resolve_to_jni", "inferred", name, "dex-jni", native_path, f"JNI name-mangling match: {jni_name}")
        for data in apk["data"]:
            data_path = data["path"]
            data_node = add_node(f"data:{name}:{data_path}", "data", name, path=data_path, suffix=data.get("suffix"), parse_status=data.get("parse_status")); data_nodes[data_path] = data_node
            add_edge(app_node, data_node, "contains_data", "direct", name, "data", data_path, "CSV/TOML archive entry")
            lower_path = data_path.casefold()
            if any(term in lower_path for term in MECHANICS_TERMS):
                concept = add_node(f"battle-concept:{name}:{next(term for term in MECHANICS_TERMS if term in lower_path)}", "battle_concept", name, name=next(term for term in MECHANICS_TERMS if term in lower_path))
                add_edge(data_node, concept, "describes_concept", "inferred", name, "data-concept", data_path, "mechanics term in path only")
        asset_nodes: dict[str, str] = {}
        for asset in apk["proprietary"]:
            asset_path = asset["path"]
            asset_nodes[asset_path] = add_node(f"asset:{name}:{asset_path}", "asset", name, path=asset_path, format_status="unsupported")
        referenced_paths = {**data_nodes, **asset_nodes}
        for native in apk["native"]:
            native_path = native.get("apk_path", "unknown")
            native_node = native_nodes.get(PurePosixPath(native_path).name)
            if not native_node:
                continue
            static_text = "\n".join(item.get("text", "") for item in native.get("focused_printable_strings", [])).casefold()
            for referenced_path, referenced_node in referenced_paths.items():
                normalized_path = referenced_path.casefold()
                basename = PurePosixPath(referenced_path).name.casefold()
                if normalized_path in static_text or (len(basename) >= 8 and basename in static_text):
                    add_edge(native_node, referenced_node, "references_packaged_path", "static", name, "native-data-asset", native_path, f"exact printable path/name reference: {referenced_path}")
        for edge in list(edges):
            if edge["apk"] != name or edge["relation"] != "loads_library":
                continue
            library_name = nodes[edge["target"]].get("name", "")
            native_node = native_nodes.get(library_name)
            if native_node:
                add_edge(edge["target"], native_node, "resolves_to_elf", "inferred", name, "dex-native", library_name, "matching native basename")
    chain_count = sum(1 for edge in edges if edge["relation"] in {"describes_concept", "resolves_to_elf", "loads_library", "may_resolve_to_jni", "references_packaged_path"})
    return {"nodes": [{"id": key, **nodes[key]} for key in sorted(nodes)], "edges": edges,
            "allowed_evidence_labels": list(EDGE_KINDS), "per_apk_edge_limits": {"total": MAX_GRAPH_EDGES_PER_APK, "layer": MAX_GRAPH_EDGES_PER_LAYER},
            "mechanics_chain_edge_count": chain_count, "conceptual_only": True,
            "coverage_note": "Absent or unsupported cross-layer references are omitted; inferred labels are not direct proof of runtime behavior."}


def report_identifier_samples(values: Iterable[str]) -> str:
    samples = sorted(filter(None, (bounded_identifier(value) for value in values)))[:MAX_REPORT_IDENTIFIERS]
    return ", ".join(f"`{value}`" for value in samples) if samples else "none"


def write_reports(apks: Sequence[dict[str, Any]], pairs: Sequence[dict[str, Any]], graph: dict[str, Any]) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    safety = "Static byte-container analysis only; no APK or native payload was executed, loaded, installed, launched, debugged, emulated, rebuilt, or decompiled. Counts and references do not establish runtime behavior."
    lines = ["# Deep Static APK Analysis", "", safety, "", "## Scope", "",
             f"- APKs: {len(apks)}; pair comparisons: {len(pairs)}; conceptual graph edges: {len(graph['edges'])}.",
             "- Inputs are existing ignored extraction manifests and bytes under `_references/apk_analysis/`; every original ZIP entry is streamed and matched to manifest path, size, and SHA-256 in the same operation.",
             "- CSV/TOML parse coverage and proprietary/ELF unsupported counts are explicit; detailed machine output remains ignored under `_references/apk_analysis/deep/`.", "", "## APK inventory", "",
             "| APK | Entries | DEX | ELF | CSV/TOML | Unsupported proprietary |", "|---|---:|---:|---:|---:|---:|"]
    for apk in apks:
        lines.append(f"| `{apk['safe_name']}` | {apk['entry_count']} | {len(apk['dex'])} | {len(apk['native'])} | {len(apk['data'])} | {len(apk['proprietary'])} |")
    lines += ["", "## Future official-tool lane", "",
              "This lane is explicitly non-executing and fail-closed policy metadata only; no network, tool, Java, plugin, or native payload was run. Controls are not enforced by this analyzer.", "",
              "| Tool | Version | Release URL | Exact asset | Asset URL | Commit | Artifact SHA-256 | License |", "|---|---|---|---|---|---|---|---|"]
    for name in ("apktool", "jadx"):
        item = OFFICIAL_TOOL_LANE[name]
        lines.append(f"| {name.title()} | `{item['version']}` | `{item['release_url']}` | `{item['asset_filename']}` | `{item['asset_url']}` | `{item['commit']}` | `{item['sha256']}` | `{item['license']}` |")
    lines += ["", "## External study note", "",
              f"- `{SC_DUMP_STUDY['repository']}` HEAD `{SC_DUMP_STUDY['head']}` is documented as a {SC_DUMP_STUDY['relationship']}.",
              "- License, tests, fixtures, data, and provenance are absent; it is study-only and was not cloned or run."]
    lines += ["", "## Metric definitions", "",
              "Every Jaccard is intersection weight divided by union weight; two empty collections score 1. `path_hash` items are `(full APK path, SHA-256)`. `content_hash` and basename variants retain duplicate counts. DEX semantic and native component items are `(owning path, item)` with multiplicity. Data total identity includes every `.csv`/`.toml`; parseable identity includes only successful syntax/schema extraction; opaque identity includes only non-successful data entries.", "",
              "## Coverage", "",
              "DEX checks include header bounds plus stored SHA-1/adler integrity, but not full map/header correspondence. ELF and graph inventories are bounded and may be partial. Proprietary formats remain unsupported. Static and inferred edges are not runtime proof."]
    (REPORT_ROOT / "DEEP_STATIC_ANALYSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# DEX Reconstruction", "", safety, "", "This is bounded structural parsing and instruction-reference traversal, not source reconstruction or decompilation.", ""]
    for apk in apks:
        lines += [f"## {apk['safe_name']}", "", "| Path | Header/map | Strings | Types | Protos | Fields | Methods | Classes | Code items | Code units | Invokes | JNI candidates |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for dex in apk["dex"]:
            if dex.get("parse_status") != "success":
                lines.append(f"| `{dex.get('apk_path')}` | failed/unsupported | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
                continue
            count = dex["counts"]
            lines.append(f"| {markdown_code(dex['apk_path'])} | integrity+bounded structure | {count['strings']} | {count['types']} | {count['protos']} | {count['fields']} | {count['methods']} | {count['classes']} | {count['code_items']} | {count['instruction_code_units']} | {count['invoke_references']} | {count['native_methods']} |")
            lines += ["", f"Traversal status: {'complete' if count['malformed_code_items'] == 0 else 'partial'}; malformed code items: {count['malformed_code_items']}. Bounded identifiers: {report_identifier_samples(dex.get('identifier_samples', []))}.", ""]
    (REPORT_ROOT / "DEX_RECONSTRUCTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Native Reconstruction", "", safety, "", "ELF metadata includes parseable headers, tables, dependencies, symbols, relocations, build IDs, stripped state, and bounded mechanics-term strings with offsets retained only in ignored machine output.", ""]
    for apk in apks:
        lines += [f"## {apk['safe_name']}", "", "| Path | Class | Machine | PH | SH | Needed | Imports | Exports | Relocations | Build IDs | Stripped | JNI |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for elf in apk["native"]:
            if elf.get("parse_status") != "success":
                lines.append(f"| `{elf.get('apk_path')}` | failed/unsupported | - | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - | 0 |")
            else:
                lines.append(f"| `{elf['apk_path']}` | {elf['class']} | {elf['machine']} | {elf['program_header_count']} | {elf['section_header_count']} | {len(elf['needed'])} | {len(elf['imports'])} | {len(elf['exports'])} | {len(elf['relocations'])} | {len(elf['build_ids'])} | {elf['stripped']} | {len(elf['jni_candidates'])} |")
    (REPORT_ROOT / "NATIVE_RECONSTRUCTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Data Delta", "", safety, "", "CSV/TOML bodies and values are never reproduced. Decode, syntax, schema, keyed-row-set, normalized-keyed-value, opaque, and extension-identity outcomes are separate.", "",
             "| APK A | APK B | Total extension/path identity | Parseable/path identity | Opaque/path identity | Identical | Unresolved | Value only | Normalized format | Added | Removed |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for pair in pairs:
        distinctions = pair["data_delta"]["distinctions"]
        lines.append(f"| `{pair['left']}` | `{pair['right']}` | {pair['similarities']['data_total_extension_path_hash_jaccard']:.6f} | {pair['similarities']['data_parseable_path_hash_jaccard']:.6f} | {pair['similarities']['data_opaque_path_hash_jaccard']:.6f} | {distinctions.get('IDENTICAL', 0)} | {distinctions.get('UNRESOLVED_CHANGE', 0)} | {distinctions.get('VALUE_ONLY_CHANGE', 0)} | {distinctions.get('NORMALIZED_FORMAT_CHANGE', 0)} | {pair['data_delta']['added_count']} | {pair['data_delta']['removed_count']} |")
    lines += ["", "## Unsupported proprietary inventory", "", "The ignored machine inventory records extension, detected magic, size, SHA-256, path, and `unsupported` status for `.sc`, `.sctx`, `.scw`, `.scdb`, `.rmat`, `.ktx`, `.glb`, and `.bank`."]
    (REPORT_ROOT / "DATA_DELTA.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Subsystem Classification", "", safety, "", "Allowed vocabulary: " + ", ".join(f"`{item}`" for item in CLASSIFICATIONS) + ". Per-APK filename/package/data presence is not component provenance; only manifest branding may support `APPLICATION_SHELL: PRIVATE_SERVER_SPECIFIC`. Pair labels are exact path/hash identity or `UNKNOWN` without an official baseline.", "", "## Per APK", "", "| APK | Application shell | DEX client | Native client | Selected data | Proprietary assets |", "|---|---|---|---|---|---|"]
    for apk in apks:
        classification = apk["classification"]
        lines.append(f"| `{apk['safe_name']}` | `{classification.get('APPLICATION_SHELL', 'UNKNOWN')}` | `{classification['DEX_CLIENT']}` | `{classification['NATIVE_CLIENT']}` | `{classification['SELECTED_DATA']}` | `{classification['PROPRIETARY_ASSETS']}` |")
    lines += ["", "## Per pair", "", "| APK A | APK B | DEX client | Native client | Selected data | Proprietary assets |", "|---|---|---|---|---|---|"]
    for pair in pairs:
        classification = pair["classification"]
        lines.append(f"| `{pair['left']}` | `{pair['right']}` | `{classification['DEX_CLIENT']}` | `{classification['NATIVE_CLIENT']}` | `{classification['SELECTED_DATA']}` | `{classification['PROPRIETARY_ASSETS']}` |")
    lines += ["", "## Evidence graph", "", f"The conceptual graph has {len(graph['nodes'])} nodes and {len(graph['edges'])} bounded edges, including {graph['mechanics_chain_edge_count']} mechanics-focused cross-layer edges. Every edge carries APK, layer, source locator, evidence label, and explanation. Limits apply per APK and layer; unsupported links are omitted rather than fabricated. `inferred` edges are explicitly non-direct."]
    (REPORT_ROOT / "SUBSYSTEM_CLASSIFICATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    output = io.StringIO(newline="")
    fields = ["left", "right", "basename_multiplicity_jaccard", "path_hash_multiplicity_jaccard", "content_hash_multiplicity_jaccard", "dex_semantic_path_multiplicity_jaccard", "dex_implementation_path_hash_jaccard", "native_component_path_multiplicity_jaccard", "native_implementation_path_hash_jaccard", "data_total_extension_path_hash_jaccard", "data_parseable_path_hash_jaccard", "data_opaque_path_hash_jaccard", "added_paths", "removed_paths", "changed_paths", "dex_classification", "native_classification", "data_classification"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n"); writer.writeheader()
    for pair in pairs:
        similarities, counts, classification = pair["similarities"], pair["counts"], pair["classification"]
        writer.writerow({"left": pair["left"], "right": pair["right"], **similarities,
                         "added_paths": counts["added_paths"], "removed_paths": counts["removed_paths"], "changed_paths": counts["changed_paths"],
                         "dex_classification": classification["DEX_CLIENT"], "native_classification": classification["NATIVE_CLIENT"], "data_classification": classification["SELECTED_DATA"]})
    (REPORT_ROOT / "deep_pairwise.csv").write_text(output.getvalue(), encoding="utf-8")


def source_inventory() -> dict[str, Any]:
    if not INVENTORY_PATH.is_file(): raise AnalysisError("missing source inventory.json")
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if inventory.get("apk_count") != 4 or len(inventory.get("apks", [])) != 4:
        raise AnalysisError("expected exactly four source APK records")
    return inventory


def verify_originals(inventory: dict[str, Any]) -> list[dict[str, str]]:
    results = []
    for record in sorted(inventory["apks"], key=lambda item: item["safe_name"]):
        path = Path(record["source_path"])
        if not path.is_file(): raise AnalysisError(f"original APK unavailable for hash-only verification: {record['filename']}")
        actual = sha256_path(path)
        if actual != record["sha256"]: raise AnalysisError(f"original APK digest mismatch: {record['filename']}")
        results.append({"filename": record["filename"], "sha256": actual, "status": "verified-read-only"})
    return results


def generate() -> dict[str, Any]:
    inventory = source_inventory()
    original_validation = verify_originals(inventory)
    apks = [analyze_apk(record) for record in sorted(inventory["apks"], key=lambda item: item["safe_name"])]
    for apk in apks: apk["classification"] = classify_apk(apk)
    pairs = [pair_compare(left, right) for left, right in itertools.combinations(apks, 2)]
    graph = evidence_graph(apks)
    DEEP_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(DEEP_ROOT / "apks.json", apks)
    write_json(DEEP_ROOT / "pairs.json", pairs)
    write_json(DEEP_ROOT / "evidence_graph.json", graph)
    write_json(DEEP_ROOT / "source_validation.json", {"original_apks": original_validation, "extraction_entries_verified": sum(apk["entry_count"] for apk in apks), "archive_manifest_binding": all(apk["source_binding"].get("archive_bound") for apk in apks)})
    write_reports(apks, pairs, graph)
    artifacts = {}
    artifact_paths = [REPORT_ROOT / name for name in TRACKED_NAMES] + [DEEP_ROOT / name for name in ("apks.json", "pairs.json", "evidence_graph.json", "source_validation.json")]
    input_paths = [INVENTORY_PATH, Path(__file__)] + [REFERENCE_ROOT / record["safe_name"] / "entries.json" for record in inventory["apks"]] + [Path(record["source_path"]) for record in inventory["apks"]]
    input_paths = sorted(set(input_paths), key=lambda item: item.as_posix())
    input_digests: dict[str, dict[str, Any]] = {}
    for path in input_paths:
        resolved = path.resolve()
        if resolved == Path(__file__).resolve():
            key = "analyzer/tools/research/apk_deep_analysis.py"
        elif ROOT in resolved.parents:
            key = resolved.relative_to(ROOT).as_posix()
        else:
            key = f"original_apks/{path.name}"
        if key in input_digests:
            raise AnalysisError(f"duplicate stable input key: {key}")
        input_digests[key] = {"sha256": sha256_path(path), "size": path.stat().st_size}
    for path in artifact_paths:
        relative = path.relative_to(ROOT).as_posix()
        artifacts[relative] = {"sha256": sha256_path(path), "size": path.stat().st_size}
    metrics = {
        "apk_count": len(apks), "pair_count": len(pairs), "entry_count": sum(apk["entry_count"] for apk in apks),
        "dex_count": sum(len(apk["dex"]) for apk in apks),
        "dex_parse_failure_count": sum(sum(1 for dex in apk["dex"] if dex.get("parse_status") != "success") for apk in apks),
        "dex_malformed_code_item_count": sum(sum(dex.get("counts", {}).get("malformed_code_items", 0) for dex in apk["dex"]) for apk in apks),
        "elf_count": sum(len(apk["native"]) for apk in apks),
        "elf_parse_success_count": sum(sum(1 for elf in apk["native"] if elf.get("parse_status") == "success") for apk in apks),
        "elf_parse_failure_count": sum(sum(1 for elf in apk["native"] if elf.get("parse_status") != "success") for apk in apks),
        "data_file_count": sum(len(apk["data"]) for apk in apks),
        "data_parse_success_count": sum(sum(1 for item in apk["data"] if item.get("parse_status") == "success") for apk in apks),
        "data_parse_non_success_count": sum(sum(1 for item in apk["data"] if item.get("parse_status") != "success") for apk in apks), "proprietary_file_count": sum(len(apk["proprietary"]) for apk in apks),
        "dex_class_count": sum(sum(dex.get("counts", {}).get("classes", 0) for dex in apk["dex"]) for apk in apks),
        "code_item_count": sum(sum(dex.get("counts", {}).get("code_items", 0) for dex in apk["dex"]) for apk in apks),
        "instruction_code_units": sum(sum(dex.get("counts", {}).get("instruction_code_units", 0) for dex in apk["dex"]) for apk in apks),
        "elf_import_count": sum(sum(len(elf.get("imports", [])) for elf in apk["native"]) for apk in apks),
        "elf_export_count": sum(sum(len(elf.get("exports", [])) for elf in apk["native"]) for apk in apks),
        "elf_relocation_count": sum(sum(len(elf.get("relocations", [])) for elf in apk["native"]) for apk in apks),
        "graph_edge_count": len(graph["edges"]), "graph_mechanics_chain_edge_count": graph["mechanics_chain_edge_count"], "source_archive_manifest_bindings": sum(1 for apk in apks if apk["source_binding"].get("archive_bound")), "real_measurements": 0,
    }
    manifest_core = {"schema_version": 2, "analysis": "deterministic bounded static byte-container analysis",
                     "metrics": metrics, "artifacts": artifacts, "input_digests": input_digests,
                     "classifications": list(CLASSIFICATIONS), "official_tool_future_lane": OFFICIAL_TOOL_LANE, "external_study": SC_DUMP_STUDY,
                     "safety": {"payload_execution": False, "decompilation_claim": False, "real_measurements": 0},
                     "coverage": {"partial_or_unsupported_is_explicit": True, "raw_container_decode_and_parse_status_separate": True,
                                  "dex_integrity_validated": True, "dex_full_map_header_correspondence_validated": False,
                                  "archive_entries_bound_to_originals": True, "graph_edges_source_labeled": True,
                                  "official_tool_controls_enforced_now": False}}
    manifest = {**manifest_core, "manifest_digest": stable_hash(manifest_core)}
    write_json(REPORT_ROOT / "deep_manifest.json", manifest)
    return {"metrics": metrics, "manifest_digest": manifest["manifest_digest"]}


def validate() -> dict[str, Any]:
    inventory = source_inventory()
    originals = verify_originals(inventory)
    extraction_count = 0
    bindings = 0
    for record in sorted(inventory["apks"], key=lambda item: item["safe_name"]):
        entries, _, binding = verify_extraction(record); extraction_count += len(entries); bindings += int(binding.get("archive_bound", False))
    if bindings != len(inventory["apks"]):
        raise AnalysisError("archive-to-extraction manifest binding incomplete")
    manifest_path = REPORT_ROOT / "deep_manifest.json"
    if not manifest_path.is_file(): raise AnalysisError("missing deep_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = manifest.pop("manifest_digest", None)
    if digest != stable_hash(manifest): raise AnalysisError("deep manifest digest mismatch")
    for relative, expected in sorted(manifest["artifacts"].items()):
        path = ROOT / PurePosixPath(relative)
        if not path.is_file() or path.stat().st_size != expected["size"] or sha256_path(path) != expected["sha256"]:
            raise AnalysisError(f"generated artifact digest mismatch: {relative}")
    for relative, expected in sorted(manifest["input_digests"].items()):
        if relative.startswith("original_apks/"):
            filename = relative.removeprefix("original_apks/")
            matches = [Path(record["source_path"]) for record in inventory["apks"] if record["filename"] == filename]
            if len(matches) != 1:
                raise AnalysisError(f"original input mapping mismatch: {relative}")
            path = matches[0]
        elif relative == "analyzer/tools/research/apk_deep_analysis.py":
            path = Path(__file__)
        else:
            path = ROOT / PurePosixPath(relative)
        if not path.is_file() or path.stat().st_size != expected["size"] or sha256_path(path) != expected["sha256"]:
            raise AnalysisError(f"input artifact digest mismatch: {relative}")
    if manifest["metrics"].get("real_measurements") != 0 or manifest["safety"].get("real_measurements") != 0:
        raise AnalysisError("real_measurements must remain zero")
    if manifest["metrics"].get("source_archive_manifest_bindings") != manifest["metrics"].get("apk_count"):
        raise AnalysisError("manifest source binding metric incomplete")
    if manifest.get("coverage", {}).get("official_tool_controls_enforced_now") is not False:
        raise AnalysisError("future tool lane must not claim current enforcement")
    if manifest.get("coverage", {}).get("dex_full_map_header_correspondence_validated") is not False:
        raise AnalysisError("DEX map/header overclaim")
    graph = json.loads((DEEP_ROOT / "evidence_graph.json").read_text(encoding="utf-8"))
    required_kinds = {"manifest", "application", "dex", "jni", "elf", "data", "asset", "battle_concept"}
    if not required_kinds.issubset({node.get("kind") for node in graph.get("nodes", [])}):
        raise AnalysisError("evidence graph typed layer coverage incomplete")
    relations = {edge.get("relation") for edge in graph.get("edges", [])}
    required_relations = {"contains_dex", "references_loader", "loads_library", "resolves_to_elf", "exports_jni", "may_resolve_to_jni", "references_packaged_path", "describes_concept"}
    if not required_relations.issubset(relations):
        raise AnalysisError("evidence graph cross-layer relation coverage incomplete")
    for edge in graph.get("edges", []):
        if not edge.get("source_locator") or edge.get("evidence") not in EDGE_KINDS:
            raise AnalysisError("evidence graph edge lacks typed source evidence")
    similarity_fields = set(next(csv.DictReader((REPORT_ROOT / "deep_pairwise.csv").open("r", encoding="utf-8", newline=""))).keys())
    required_metrics = {"basename_multiplicity_jaccard", "path_hash_multiplicity_jaccard", "data_total_extension_path_hash_jaccard", "data_parseable_path_hash_jaccard", "data_opaque_path_hash_jaccard"}
    if not required_metrics.issubset(similarity_fields):
        raise AnalysisError("pair metric schema incomplete")
    if manifest["metrics"].get("data_parse_non_success_count", 0) and "partial" not in " ".join((REPORT_ROOT / name).read_text(encoding="utf-8").casefold() for name in TRACKED_NAMES):
        raise AnalysisError("partial data coverage not disclosed")
    if tuple(manifest["classifications"]) != CLASSIFICATIONS:
        raise AnalysisError("classification vocabulary mismatch")
    banned = (r"(?<![A-Za-z])[A-Za-z]:[\\/]", r"Python \d", r"generated_at", r"runtime behavior was observed", r"measured live behavior")
    for name in (*TRACKED_NAMES, "deep_manifest.json"):
        text = (REPORT_ROOT / name).read_text(encoding="utf-8")
        for pattern in banned:
            if re.search(pattern, text, flags=re.IGNORECASE): raise AnalysisError(f"forbidden unstable/measured content in {name}: {pattern}")
    pairs = list(csv.DictReader((REPORT_ROOT / "deep_pairwise.csv").open("r", encoding="utf-8", newline="")))
    expected_names = sorted(record["safe_name"] for record in inventory["apks"])
    expected_pairs = {tuple(pair) for pair in itertools.combinations(expected_names, 2)}
    actual_pairs = {tuple(sorted((row.get("left", ""), row.get("right", "")))) for row in pairs}
    if len(pairs) != 6 or actual_pairs != expected_pairs:
        raise AnalysisError("expected exact six unique APK pair comparisons")
    result = {"status": "PASS", "apk_count": 4, "pair_count": 6, "extraction_entries_verified": extraction_count,
              "original_apks_verified": len(originals), "generated_artifacts_verified": len(manifest["artifacts"]),
              "real_measurements": 0, "manifest_digest": digest}
    write_json(DEEP_ROOT / "validation_result.json", result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generate", "validate"))
    args = parser.parse_args(argv)
    try:
        result = generate() if args.operation == "generate" else validate()
    except (AnalysisError, OSError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
