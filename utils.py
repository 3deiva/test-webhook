import os
from config import CODE_EXT_TO_LANG

def get_language(filename: str):
    ext = filename.split(".")[-1].lower()
    return CODE_EXT_TO_LANG.get(ext)

def safe_read(path, binary=False):
    mode = "rb" if binary else "r"
    try:
        with open(path, mode, encoding=None if binary else "utf-8", errors=None if binary else "ignore") as f:
            return f.read()
    except Exception:
        return "" if not binary else b""

def relpath(repo_root, path):
    try:
        return os.path.relpath(path, repo_root).replace("\\", "/")
    except Exception:
        return path.replace("\\", "/")

def byte_offset_map(text: str):
    """Build a list of starting byte offset per line (1-indexed line numbers)."""
    offsets = [0]
    total = 0
    for line in text.splitlines(True):
        total += len(line.encode("utf-8", errors="ignore"))
        offsets.append(total)
    return offsets

def span_to_bytes(line_start, col_start, line_end, col_end, line_byte_offsets, text):
    """Convert (line, col) span to byte start/end using UTF-8 offsets."""
    try:
        start_byte = line_byte_offsets[line_start-1] + len(text.splitlines(True)[line_start-1][:col_start].encode("utf-8", errors="ignore"))
        end_byte = line_byte_offsets[line_end-1] + len(text.splitlines(True)[line_end-1][:col_end].encode("utf-8", errors="ignore"))
        return start_byte, end_byte
    except Exception:
        return None, None