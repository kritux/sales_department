#!/usr/bin/env python3
"""Scan project files for accidentally committed secrets."""
import os, re, sys

PATTERNS = [
    (r'sk-[A-Za-z0-9]{32,}', 'Anthropic/OpenAI API key'),
    (r'AC[a-f0-9]{32}', 'Twilio Account SID'),
    (r'eyJ[A-Za-z0-9+/=]{50,}', 'JWT token'),
    (r'(?<![A-Z])[A-Za-z0-9]{40,}(?![A-Z])', 'Possible API key'),
]

SKIP = {'.git', 'venv', '__pycache__', 'node_modules', '.next', 'chroma_db'}
SKIP_FILES = {'.env.example', 'scan_secrets.py'}

issues = []
for root, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in SKIP]
    for f in files:
        if f in SKIP_FILES: continue
        if not f.endswith(('.py', '.ts', '.tsx', '.js', '.env')): continue
        path = os.path.join(root, f)
        try:
            with open(path) as fp:
                for i, line in enumerate(fp, 1):
                    for pattern, name in PATTERNS:
                        if re.search(pattern, line) and '=' not in line[:line.find(re.search(pattern,line).group())][-5:]:
                            issues.append(f"{path}:{i} — possible {name}")
        except: pass

if issues:
    print("SECRETS SCAN — ISSUES FOUND:")
    for i in issues: print(f"  ❌ {i}")
    sys.exit(1)
else:
    print("✅ Secrets scan passed — no issues found")
