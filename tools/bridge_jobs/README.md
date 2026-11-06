# Nasuraya remote jobs

Jobs run as the Windows Scheduled Task account. Their source is pinned to a full Git commit SHA and verified against the exact SHA-256 supplied in the GitHub issue command. Only jobs authorized by the server owner should be submitted. Never print keys, passwords, paths, personal information, patient data, or raw logs: issue #149 is public.

Example:
\`\`\`text
nasu: run <40-character-commit-sha> runtime_probe <64-character-file-sha256>
\`\`\`

Current first job: runtime_probe.py prints a small, non-sensitive JSON status for validating the expanded bridge.
