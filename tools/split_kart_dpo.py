#!/usr/bin/env python3
# b17: SKD41
"""
split_kart_dpo.py — Split dpo_pairs_kart.jsonl into valid DPO and SFT.

Pairs with empty rejected (_error_type: sft) are SFT examples stored in
DPO format. This script separates them:

  yggdrasil/dpo_kart_v1.jsonl   — task_failure pairs (genuine DPO)
  yggdrasil/sft_kart_v1.jsonl   — sft pairs (SFT, chosen→response)
"""

import json
from pathlib import Path

REPO   = Path(__file__).parent.parent
INPUT  = REPO / "yggdrasil" / "dpo_pairs_kart.jsonl"
OUT_DPO = REPO / "yggdrasil" / "dpo_kart_v1.jsonl"
OUT_SFT = REPO / "yggdrasil" / "sft_kart_v1.jsonl"

lines = [json.loads(l) for l in INPUT.read_text().splitlines() if l.strip()]

dpo_pairs = []
sft_pairs = []

for pair in lines:
    if pair.get("rejected", "").strip():
        dpo_pairs.append(pair)
    else:
        # Convert to SFT format: prompt → response
        sft_pairs.append({
            "instruction": pair["prompt"],
            "response":    pair["chosen"],
            "source":      "kart_success",
            "source_type": "execution",
            "label":       "kart_task",
            "category":    "kart/execution",
        })

OUT_DPO.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in dpo_pairs) + "\n")
OUT_SFT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in sft_pairs) + "\n")

print(f"Input:   {len(lines)} pairs")
print(f"DPO out: {len(dpo_pairs)} → {OUT_DPO}")
print(f"SFT out: {len(sft_pairs)} → {OUT_SFT}")
