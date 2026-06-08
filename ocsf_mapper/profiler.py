"""Format detection + record profiler for the OCSF mapper.

Detects: jsonl, ndjson, json (single record), json_array, wrapper.
Profiles records into a compact schema that the LLM reasons over.
"""
from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator


def _open(path: str):
    p = Path(path)
    if p.suffix == ".gz":
        return gzip.open(p, "rt", encoding="utf-8")
    return open(p, "r", encoding="utf-8")



# ── auditd support ──────────────────────────────────────────────────────────
import struct as _struct
from collections import OrderedDict as _OrderedDict


_EVENT_RE = re.compile(r"audit\((?P<ts>\d+\.\d+):(?P<serial>\d+)\)")
# stop saddr/value capture before the SADDR={...} human-readable appendix
_KV_RE = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^\s={]+)')


def _hexdecode(v: str) -> str:
    if len(v) >= 2 and len(v) % 2 == 0 and re.fullmatch(r"[0-9A-Fa-f]+", v):
        try:
            return bytes.fromhex(v).decode("utf-8", "replace").replace("\x00", " ").strip()
        except ValueError:
            return v
    return v


def _decode_saddr(hexstr: str) -> dict | None:
    """Unpack the packed sockaddr hex. AF_INET (0x0002) -> ip + port."""
    try:
        raw = bytes.fromhex(hexstr)
    except ValueError:
        return None
    if len(raw) < 8:
        return None
    fam = _struct.unpack_from("<H", raw, 0)[0]  # family is host-byte-order in auditd dumps
    if fam == 2:  # AF_INET
        port = _struct.unpack_from(">H", raw, 2)[0]
        ip = ".".join(str(b) for b in raw[4:8])
        return {"family": "inet", "addr": ip, "port": port}
    if fam == 10:  # AF_INET6
        port = _struct.unpack_from(">H", raw, 2)[0]
        return {"family": "inet6", "port": port}
    return {"family": str(fam)}


def _parse_line(line: str):
    m = _EVENT_RE.search(line)
    if not m:
        return None
    rtype_m = re.match(r"type=(\S+)", line)
    rtype = rtype_m.group(1) if rtype_m else "UNKNOWN"
    # SYSCALL a0-a3 are raw register pointers, NOT hex strings -> never decode
    decode_args = rtype == "EXECVE"
    # cut the SADDR={...} appendix so it isn't double-parsed
    line = re.sub(r"SADDR=\{[^}]*\}", "", line)
    fields = {}
    for k, raw in _KV_RE.findall(line):
        if k in ("type", "msg"):
            continue
        val = raw.strip('"')
        if k == "saddr":
            dec = _decode_saddr(val)
            fields[k] = dec if dec else val
            continue
        if k == "proctitle" or (decode_args and re.fullmatch(r"a\d+", k)):
            fields[k] = _hexdecode(val)
            continue
        fields[k] = val
    return m.group("serial"), m.group("ts"), rtype, fields


def is_auditd(peek: str) -> bool:
    return bool(re.match(r"type=\w+\s+msg=audit\(", peek.lstrip()))


def iter_audit_events(path: str):
    events: "_OrderedDict[str, dict]" = _OrderedDict()
    with open(path, encoding="utf-8") as f:
        for line in f:
            parsed = _parse_line(line)
            if not parsed:
                continue
            serial, ts, rtype, fields = parsed
            ev = events.setdefault(serial, {"event_serial": serial, "event_time": ts})
            if rtype == "SYSCALL":
                ev.update(fields)
            elif rtype in ev:
                if not isinstance(ev[rtype], list):
                    ev[rtype] = [ev[rtype]]
                ev[rtype].append(fields)
            else:
                ev[rtype] = fields
    yield from events.values()




def detect_format(path: str, peek_bytes: int = 8192) -> dict:
    """Return {format, record_path, notes}.

    format  : one of "jsonl" | "json_array" | "json_wrapped" | "json_single"
    record_path : JSONPath-ish to the record array for wrapped/array formats
                  (None for jsonl/json_single)
    """
    with _open(path) as f:
        peek = f.read(peek_bytes)

    stripped = peek.lstrip()
    if not stripped:
        raise ValueError("empty sample file")

    # JSONL: each line is a complete object
    if stripped.startswith("{"):
        # try first two lines
        lines = [ln for ln in peek.splitlines() if ln.strip()]
        try:
            if len(lines) >= 2:
                json.loads(lines[0])
                json.loads(lines[1])
                return {"format": "jsonl", "record_path": None, "notes": "newline-delimited objects"}
        except json.JSONDecodeError:
            pass
        # fall through to single-object detection
        try:
            # full parse — small files only; for large, accept JSONL if line 1 parses
            with _open(path) as f:
                full = json.load(f)
            if isinstance(full, dict):
                # wrapper? find unique array-of-objects field
                array_fields = [
                    k for k, v in full.items()
                    if isinstance(v, list) and v and isinstance(v[0], dict)
                ]
                if len(array_fields) == 1:
                    return {
                        "format": "json_wrapped",
                        "record_path": f"$.{array_fields[0]}[*]",
                        "notes": f"wrapper object with single array field '{array_fields[0]}'",
                    }
                if len(array_fields) > 1:
                    return {
                        "format": "json_wrapped",
                        "record_path": None,
                        "notes": f"AMBIGUOUS: multiple array fields {array_fields}. User must specify record_path.",
                    }
                return {"format": "json_single", "record_path": None, "notes": "single JSON object (one record)"}
        except json.JSONDecodeError:
            # huge file that can't load fully and isn't clean jsonl — flag
            return {"format": "jsonl", "record_path": None, "notes": "assuming jsonl based on leading '{' (file too large to fully parse)"}

    if stripped.startswith("["):
        return {"format": "json_array", "record_path": "$[*]", "notes": "top-level JSON array"}

    if is_auditd(stripped):
        return {"format": "auditd", "record_path": None,
                "notes": "Linux auditd records; reassembled per audit() event serial"}

    raise ValueError(f"unrecognized format; starts with {stripped[:40]!r}")


def iter_records(path: str, fmt: dict) -> Iterator[dict]:
    """Yield records according to detected format."""
    f = fmt["format"]
    if f == "jsonl":
        with _open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)
    elif f == "json_array":
        with _open(path) as fh:
            for rec in json.load(fh):
                yield rec
    elif f == "json_wrapped":
        if not fmt["record_path"]:
            raise ValueError("json_wrapped needs record_path")
        field = fmt["record_path"].split(".", 1)[1].rstrip("[*]")
        with _open(path) as fh:
            for rec in json.load(fh).get(field, []):
                yield rec
    elif f == "auditd":
        yield from iter_audit_events(path)
    elif f == "json_single":
        with _open(path) as fh:
            yield json.load(fh)
    else:
        raise ValueError(f"unknown format {f}")


# ────────────────────────────────────────────────────────────────────────────
# PROFILER
# ────────────────────────────────────────────────────────────────────────────

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _infer_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, str):
        if _TS_RE.match(v):
            return "timestamp"
        return "string"
    if isinstance(v, list):
        if not v:
            return "array<empty>"
        inner = {_infer_type(x) for x in v[:5]}
        return f"array<{'|'.join(sorted(inner))}>"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _walk(rec: Any, prefix: str, out: dict):
    """Flatten record into {path: [observed values]} up to reasonable depth."""
    if isinstance(rec, dict):
        for k, v in rec.items():
            _walk(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(rec, list):
        if not rec:
            out.setdefault(prefix, []).append([])
        else:
            # treat arrays as a single path but record element shape
            out.setdefault(prefix, []).append(rec)
            if isinstance(rec[0], dict):
                # descend into first element to expose nested paths
                _walk(rec[0], f"{prefix}[]", out)
    else:
        out.setdefault(prefix, []).append(rec)


def profile(path: str, fmt: dict, max_records: int = 200) -> dict:
    """Produce a compact schema profile of the sample."""
    paths: dict[str, list] = {}
    n = 0
    for rec in iter_records(path, fmt):
        _walk(rec, "", paths)
        n += 1
        if n >= max_records:
            break

    fields = {}
    for path_key, values in paths.items():
        types = defaultdict(int)
        non_null = 0
        examples = []
        for v in values:
            t = _infer_type(v)
            types[t] += 1
            if v is not None and v != [] and v != {}:
                non_null += 1
                if len(examples) < 3 and not isinstance(v, (dict, list)):
                    examples.append(v)
        fields[path_key] = {
            "types": dict(types),
            "null_rate": round(1 - non_null / len(values), 3),
            "occurrences": len(values),
            "examples": examples[:3],
        }

    return {
        "format": fmt,
        "records_profiled": n,
        "field_count": len(fields),
        "fields": fields,
    }


def render_profile_for_llm(prof: dict, max_fields: int = 120) -> str:
    """Render profile as a compact string suitable for an LLM prompt."""
    lines = [
        f"Format: {prof['format']['format']} ({prof['format']['notes']})",
        f"Records profiled: {prof['records_profiled']}",
        f"Distinct field paths: {prof['field_count']}",
        "",
        "Fields (path : types [null_rate] examples):",
    ]
    # sort: non-array scalars first, then arrays, then nested
    items = sorted(prof["fields"].items(), key=lambda kv: (kv[0].count("[]"), kv[0].count("."), kv[0]))
    for path, meta in items[:max_fields]:
        types_str = ", ".join(f"{t}×{n}" for t, n in meta["types"].items())
        ex = meta["examples"]
        ex_str = ""
        if ex:
            ex_str = " ex=" + json.dumps(ex[0], default=str)[:60]
        lines.append(f"  {path} : {types_str} [null={meta['null_rate']}]{ex_str}")
    if len(prof["fields"]) > max_fields:
        lines.append(f"  ... ({len(prof['fields']) - max_fields} more)")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    fmt = detect_format(p)
    print("DETECTED:", fmt)
    prof = profile(p, fmt, max_records=50)
    print(render_profile_for_llm(prof, max_fields=80))