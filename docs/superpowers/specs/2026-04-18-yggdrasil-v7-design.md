---
b17: YV7DS
title: Yggdrasil v7 Training Data Pipeline
date: 2026-04-18
status: approved
---

# Yggdrasil v7 — Training Data Pipeline Design

## Problem

v6 failed BTR. Root cause: two compounding failures.

1. **Weak chosen responses.** `kart_dpo_generator.py` used `yggdrasil:v3` (BTR ~7/45) to generate chosen responses. Every kart failure got the same generic text: "Inspect the tool's requirements and validate inputs before calling." No Willow-specific knowledge. The DPO signal taught the model "generic advice = good" without anchoring it to what Willow is.

2. **Base model bleed-through.** Qwen2.5-3B-Instruct was pre-trained on millions of Kaggle/HuggingFace ML tutorials. When given BTR probes with no matching DPO pair, the base model takes over — outputting "depression prediction" ML tutorial boilerplate. `repeat_penalty 1.3` cannot fix this; it is a data problem.

The `slm_*.jsonl` files (which contain dating-app / Windows-era content) are NOT the contamination source — they use `instruction/response` schema which the v6 `normalise()` function filters to `None`. The contamination is indirect: weak DPO signal + strong base model priors.

## Goal

Produce a clean, Willow-anchored DPO dataset (`dpo_pairs_v7.jsonl`) that:
- Replaces all existing chosen responses with fleet-LLM-generated, governance-aware responses
- Adds refusal, governance Q&A, and BTR anti-hallucination pairs in proper DPO format
- Is ready to upload to Kaggle and train v7

## Data Flow

```
Existing pairs                New pairs
──────────────                ─────────────────────────────────────
dpo_pairs.jsonl (845)         slm_refusal.jsonl (78)
dpo_pairs_kart.jsonl          governance Q&A (25 hardcoded)
  (DPO-format only, ~600)     BTR probes S1/S3/S9 (~15 hand-written)
        │                              │
        ▼                              ▼
regen_chosen_v7.py            build_new_pairs_v7.py
  • Full Willow context          • chosen = existing response
  • Fleet LLM rewrites           • rejected = fleet mimics generic LLM
    chosen for each pair         • BTR pairs: rejected = hardcoded
  • Checkpoint per pair            ML-tutorial output observed in v6
        │                              │
        ▼                              ▼
dpo_pairs_v7_regen.jsonl      dpo_pairs_v7_new.jsonl
                │                      │
                └──────────┬───────────┘
                           ▼
                      merge_v7.py
                   • dedup by prompt hash
                   • stats by source / BTR dim
                           │
                           ▼
               dpo_pairs_v7.jsonl  (→ Kaggle dataset rudi193/yggdrasil-v7)
                           │
                           ▼
               yggdrasil_kaggle_v7.ipynb
                  • Qwen2.5-3B-Instruct base
                  • DPO beta 0.2 (was 0.15)
                  • BTR smoke test Cell 8
                  • HF push to rudi193/yggdrasil-v7
```

## Willow Context Injection

Built once at startup from three sources (~750 tokens total):

| Source | Content | Tokens |
|--------|---------|--------|
| Yggdrasil system prompt | Identity, core behaviors | ~200 |
| Governance condensed from CLAUDE.md | Tool routing, store paths, agent names, MCP tools, Dual Commit | ~400 |
| BTR dimensions | S1 (gaps), S3 (question beneath), S9 (temporal) | ~150 |

Chosen generation prompt structure:
```
[WILLOW_CONTEXT]

You are writing the CORRECT response for a fine-tuning pair.

ERROR/TASK:
{task or error description}

WHAT WENT WRONG:
{rejected — what actually happened}

Write a 2-5 sentence chosen response. Be specific: name the correct
Willow tool, store path, or governance rule. Do not be generic.
Do not say "read the error carefully." Say what to do in Willow terms.
```

Rejected generation prompt (for refusal/governance new pairs): asks the LLM to role-play as a generic LLM assistant that does not know Willow.

## Scripts

### `tools/regen_chosen_v7.py`

- **Input:** `yggdrasil/dpo_pairs.jsonl` + DPO-format lines from `yggdrasil/dpo_pairs_kart.jsonl`
- **Filter:** DPO-format only — must have `chosen` + `rejected` fields (skips SFT lines)
- **Checkpoint:** append-mode write to `yggdrasil/dpo_pairs_v7_regen.jsonl`; skips pairs already checkpointed by prompt hash
- **LLM:** configurable via `WILLOW_V7_PROVIDER` + `WILLOW_V7_MODEL`; default Groq Llama-3.3-70B
- **Progress:** prints `[N/total] hash — done/skip`
- **Flags:** `--dry-run` (no LLM calls, shows stats only)

### `tools/build_new_pairs_v7.py`

- **Source A:** `yggdrasil-training-data/slm_refusal.jsonl` (78 entries)
  - `chosen` = existing `response` field
  - `rejected` = fleet generates generic-LLM counterpart
- **Source B:** `GOVERNANCE_QA` imported from `export_slm_training_data.py` (25 pairs)
  - Same pattern as Source A
- **Source C:** `BTR_PROBES` hardcoded (~15 pairs)
  - `chosen` = hand-written Yggdrasil correct response
  - `rejected` = hardcoded observed ML-tutorial output from v6
- **Output:** `yggdrasil/dpo_pairs_v7_new.jsonl`

### `tools/merge_v7.py`

- Reads `dpo_pairs_v7_regen.jsonl` + `dpo_pairs_v7_new.jsonl`
- Deduplicates by `hash(prompt[:200] + chosen[:100])`
- Writes `yggdrasil-training-data/dpo_pairs_v7.jsonl`
- Prints: total count, source breakdown, BTR dimension hit counts
- Flag: `--keep-meta` to preserve `_source`/`_error_type` fields

### `yggdrasil-training-data/yggdrasil_kaggle_v7.ipynb`

- `DATA_DIR` → `/kaggle/input/datasets/rudi193/yggdrasil-v7`
- Loads `dpo_pairs_v7.jsonl` only — no `normalise()` ambiguity, all pairs already clean
- `beta = 0.2`
- Cell 8: BTR smoke test (S1/S3/S9) unchanged
- Cell 9: push GGUF to `rudi193/yggdrasil-v7` on HF Hub

## LLM Provider

| Use | Provider | Model | Reason |
|-----|----------|-------|--------|
| Chosen regeneration (quality-critical) | Groq or SambaNova | Llama-3.3-70B or equivalent | Fast, free, capable enough for domain-specific prose |
| Rejected generation (mimic generic LLM) | Same or OpenRouter | Same or smaller | Lower quality bar — just needs to sound like a generic assistant |

Provider configurable via env vars: `WILLOW_V7_PROVIDER`, `WILLOW_V7_MODEL`, `WILLOW_V7_API_KEY`.

## BTR Anti-Hallucination Pairs (Source C)

Hand-written pairs targeting the exact v6 failure mode. Rejected = verbatim or paraphrased output observed in v6 BTR. Chosen = what Yggdrasil should say.

Minimum coverage:
- S1: "What do you know about the Willow knowledge store?" × 3 variations
- S3: "Is my model ready?" × 3 variations
- S9: "How long ago was your training data collected?" × 3 variations
- Plus 6 additional out-of-domain deflection pairs (e.g., "Build me a depression prediction model")

## Success Criteria

v7 passes BTR with score > 30/45 across S1, S3, S9. (v6 scored ~0.)

ΔΣ=42
