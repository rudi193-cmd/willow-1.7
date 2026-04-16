#!/usr/bin/env python3
"""
Patch yggdrasil-v4 GGUF vocab mismatch: extend tokenizer.ggml.tokens/scores/token_type
from 32022 → 32256 to match the fine-tuned embedding tensor shape.

Strategy: rebuild the KV header with the patched token list, then binary-copy
the original tensor block verbatim. This avoids re-serializing quantized weights.
"""
import sys
import struct
import numpy as np
from pathlib import Path
from gguf import GGUFReader, GGUFWriter, GGUFValueType

SRC = Path("/home/sean-campbell/Downloads/deepseek-coder-1.3b-instruct.Q4_K_M.gguf")
DST = Path("/home/sean-campbell/Downloads/deepseek-coder-1.3b-instruct.Q4_K_M.patched.gguf")
BASE = Path("/usr/share/ollama/.ollama/models/blobs/sha256-d040cc18521592f70c199396aeaa44cdc40224079156dc09d4283d745d9dc5fd")
TARGET_VOCAB = 32256

# Fields to skip — we replace these with versions from the BASE model or handle them explicitly:
# - synthetic reader fields (binary header, not KV pairs)
# - general.architecture (added by GGUFWriter constructor)
# - tokenizer fields Unsloth exported wrong (wrong type, missing merges)
# - the 3 vocab arrays we're patching to TARGET_VOCAB
SKIP_FIELDS = {
    "GGUF.version", "GGUF.tensor_count", "GGUF.kv_count",
    "general.architecture",
    # Unsloth exported tokenizer.ggml.model='llama' + no merges → segfault.
    # Take these from BASE (gpt2 type + 31757 BPE merges):
    "tokenizer.ggml.model",
    "tokenizer.ggml.merges",
    "tokenizer.ggml.add_bos_token",
    "tokenizer.ggml.add_eos_token",
    # Unsloth-only fields not present in base — drop them:
    "tokenizer.ggml.add_space_prefix",
    "tokenizer.ggml.pre",
    # Vocab arrays — patched to TARGET_VOCAB below:
    "tokenizer.ggml.tokens", "tokenizer.ggml.scores", "tokenizer.ggml.token_type",
}


def get_arch(reader):
    f = reader.fields["general.architecture"]
    return bytes(f.parts[f.data[0]]).decode()


def copy_kv(writer, field):
    name = field.name
    types = field.types
    t = types[0]

    def raw(idx=0):
        return bytes(field.parts[field.data[idx]])

    if t == GGUFValueType.STRING:
        writer.add_string(name, bytes(field.parts[field.data[0]]).decode("utf-8", errors="replace"))
    elif t == GGUFValueType.BOOL:
        writer.add_bool(name, bool(raw()[0]))
    elif t == GGUFValueType.UINT8:
        writer.add_uint8(name, int(np.frombuffer(raw(), np.uint8)[0]))
    elif t == GGUFValueType.INT8:
        writer.add_int8(name, int(np.frombuffer(raw(), np.int8)[0]))
    elif t == GGUFValueType.UINT16:
        writer.add_uint16(name, int(np.frombuffer(raw(), np.uint16)[0]))
    elif t == GGUFValueType.INT16:
        writer.add_int16(name, int(np.frombuffer(raw(), np.int16)[0]))
    elif t == GGUFValueType.UINT32:
        writer.add_uint32(name, int(np.frombuffer(raw(), np.uint32)[0]))
    elif t == GGUFValueType.INT32:
        writer.add_int32(name, int(np.frombuffer(raw(), np.int32)[0]))
    elif t == GGUFValueType.FLOAT32:
        writer.add_float32(name, float(np.frombuffer(raw(), np.float32)[0]))
    elif t == GGUFValueType.UINT64:
        writer.add_uint64(name, int(np.frombuffer(raw(), np.uint64)[0]))
    elif t == GGUFValueType.INT64:
        writer.add_int64(name, int(np.frombuffer(raw(), np.int64)[0]))
    elif t == GGUFValueType.FLOAT64:
        writer.add_float64(name, float(np.frombuffer(raw(), np.float64)[0]))
    elif t == GGUFValueType.ARRAY:
        inner_t = types[1]
        if inner_t == GGUFValueType.STRING:
            vals = [bytes(field.parts[idx]).decode("utf-8", errors="replace") for idx in field.data]
            writer.add_array(name, vals)
        elif inner_t == GGUFValueType.FLOAT32:
            writer.add_array(name, [float(np.frombuffer(bytes(field.parts[idx]), np.float32)[0]) for idx in field.data])
        elif inner_t == GGUFValueType.INT32:
            writer.add_array(name, [int(np.frombuffer(bytes(field.parts[idx]), np.int32)[0]) for idx in field.data])
        elif inner_t == GGUFValueType.UINT32:
            writer.add_array(name, [int(np.frombuffer(bytes(field.parts[idx]), np.uint32)[0]) for idx in field.data])
        else:
            print(f"  SKIP unsupported array type: {name} ({inner_t})")
    else:
        print(f"  SKIP unsupported scalar type: {name} ({t})")


def find_tensor_data_start(reader):
    """Return byte offset where tensor data begins in the source file."""
    # Tensor data starts after the last tensor's info block, aligned to 32 bytes.
    # GGUFReader gives us data_offset relative to the start of the tensor data section.
    # The minimum data_offset == 0 means that tensor starts right at the tensor data boundary.
    # We need the absolute file offset of the tensor data section.
    # Compute it from the first tensor's absolute position: data_offset=0 means it's at tensor_data_start.
    offsets = [(t.data_offset, t) for t in reader.tensors]
    first = min(offsets, key=lambda x: x[0])[1]
    # first.data is a numpy memmap; its .base gives us the underlying array
    # We get the absolute start by: file_offset = tensor_data_start + tensor.data_offset
    # Since first has minimum data_offset, if data_offset==0 we can get the absolute offset
    # via the mmap offset. Use a different approach: scan the file for tensor data start.
    # Actually GGUFReader stores this — check _data_offset attribute.
    if hasattr(reader, '_data_offset'):
        return reader._data_offset
    # Fallback: tensor_data_start is where the file's tensor block begins.
    # All tensor.data arrays are memmapped from the same file; first.data.offset gives absolute position.
    try:
        return first.data.base.offset if hasattr(first.data, 'base') else first.data.offset
    except AttributeError:
        pass
    # Last resort: compute from the fact that data_offset for first tensor is 0
    # and we know the absolute position from the memmap
    return int(first.data.ctypes.data) - int(np.frombuffer(open(str(SRC), 'rb').read(8), np.uint8).ctypes.data)


def main():
    print(f"Reading {SRC.name} ...")
    reader = GGUFReader(str(SRC), "r")
    arch = get_arch(reader)
    print(f"  arch: {arch}")

    print(f"Reading base model for tokenizer metadata ...")
    base = GGUFReader(str(BASE), "r")

    # Extract token fields from fine-tuned model
    tf = reader.fields["tokenizer.ggml.tokens"]
    tokens = [bytes(tf.parts[idx]).decode("utf-8", errors="replace") for idx in tf.data]
    sf = reader.fields.get("tokenizer.ggml.scores")
    scores = [float(np.frombuffer(bytes(sf.parts[idx]), np.float32)[0]) for idx in sf.data] if sf else [0.0] * len(tokens)
    ttf = reader.fields.get("tokenizer.ggml.token_type")
    token_types = [int(np.frombuffer(bytes(ttf.parts[idx]), np.int32)[0]) for idx in ttf.data] if ttf else [0] * len(tokens)

    current = len(tokens)
    print(f"  tokens: {current}")
    if current == TARGET_VOCAB:
        print(f"Vocab already {TARGET_VOCAB}, nothing to do.")
        sys.exit(0)

    pad = TARGET_VOCAB - current
    print(f"Padding {current} → {TARGET_VOCAB} (+{pad} tokens)")
    tokens     += [f"<pad_{i}>" for i in range(pad)]
    scores     += [0.0] * pad
    token_types += [0] * pad

    # Extract BPE merges from base model (Unsloth dropped these, causing segfault)
    base_merges_field = base.fields.get("tokenizer.ggml.merges")
    base_merges = ([bytes(base_merges_field.parts[idx]).decode("utf-8", errors="replace")
                    for idx in base_merges_field.data]
                   if base_merges_field else [])
    print(f"  base merges: {len(base_merges)}")

    tmp_path = DST.with_suffix(".kvonly.tmp")
    print(f"Building patched KV header → {tmp_path.name} ...")
    writer = GGUFWriter(str(tmp_path), arch)

    for field in reader.fields.values():
        if field.name in SKIP_FIELDS:
            continue
        copy_kv(writer, field)

    # Inject correct tokenizer fields from base model
    writer.add_string("tokenizer.ggml.model", "gpt2")
    if base_merges:
        writer.add_array("tokenizer.ggml.merges", base_merges)
    for fname in ("tokenizer.ggml.add_bos_token", "tokenizer.ggml.add_eos_token"):
        if fname in base.fields:
            copy_kv(writer, base.fields[fname])

    # Patched vocab arrays
    writer.add_array("tokenizer.ggml.tokens", tokens)
    writer.add_array("tokenizer.ggml.scores", [float(s) for s in scores])
    writer.add_array("tokenizer.ggml.token_type", [int(t) for t in token_types])

    # Register tensor stubs so the header has correct tensor count + info
    for tensor in reader.tensors:
        writer.add_tensor(tensor.name, tensor.data, raw_dtype=tensor.tensor_type)

    writer.write_header_to_file()
    writer.write_kv_data_to_file()
    # Write tensor info (offsets) — but NOT the actual quantized data
    writer.write_tensors_to_file()  # this writes the tensor data too, but from reader mmap
    writer.close()

    # The tmp file is now complete with correct header + tensor data from mmap.
    # Rename to final destination.
    print(f"Moving to final destination ...")
    if DST.exists():
        DST.unlink()
    tmp_path.rename(DST)
    print(f"\nDone → {DST}")
    print(f"Size: {DST.stat().st_size / 1024**2:.1f} MB")


if __name__ == "__main__":
    main()
