---
tags: [cursor-delegate]
max_turns: 40
timeout_seconds: 2400
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

/cursor-delegate --model composer --effort medium paginate() in shop_utils/listing.py drops an item on every page after the first. have cursor fix it and add a regression test

Input files: shop_utils/, tests/, AGENTS.md
