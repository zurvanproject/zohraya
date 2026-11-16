Awake Content QA: read-only staging

This local retrieval test uses the existing offline-capable Qwen3-1.7B llama.cpp server on 127.0.0.1:8097. It reads source-cited evidence payloads, questions, and ledger details from the approved Awake SQLite in read-only mode. It does not train the model, write to Awake, call external APIs, create timers or execute retrieved instructions.

Prerequisites: Python 3.11+, readable approved Awake database for nasuraya user, and running local llama-server. The code must be reviewed and installed on the Ubuntu host first. Then as nasuraya: python3 nasu_awake_memory_qa.py status; python3 nasu_awake_memory_qa.py preview --question 'آخرین پرسش‌ها چه هستند؟'; python3 nasu_awake_memory_qa.py ask --question 'آخرین پرسش‌ها چه هستند؟'.

Keyword matching is NOT embedding-based semantic search and can miss synonyms. At most three bounded snippets are sent to localhost. Source candidates are retrieved identifiers, not automatic proof that model citations are faithful; inspect retrieved excerpts before trusting any answer. The 1.7B model may hallucinate. Avoid patient-identifiable inputs. Data are not sent to GitHub.

Run tests: python3 -m unittest discover -s tests -p test_nasu_awake_memory_qa.py -v

No production deployment or six-hour observer integration is claimed. After testing against actual Awake data, separately review a scheduler integration.
