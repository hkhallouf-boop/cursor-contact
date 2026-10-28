---
tags: [cursor-debate]
max_turns: 40
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

debate this with grok before more callers start using it: apply_coupon in shop_utils/pricing.py silently clamps out-of-range percents. should it raise a ValueError instead?

Input files: shop_utils/, tests/, AGENTS.md
