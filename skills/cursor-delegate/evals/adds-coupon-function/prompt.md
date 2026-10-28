---
tags: [cursor-delegate]
max_turns: 40
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

delegate this to cursor: add an apply_coupon(total, percent) function to shop_utils/pricing.py. percent is 0-100, clamp anything outside that range, and the result has to follow our money rounding. add pytest tests for it in tests/test_pricing.py

Input files: shop_utils/, tests/, AGENTS.md
