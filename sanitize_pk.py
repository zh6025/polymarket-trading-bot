import os, re

raw = os.getenv("PRIVATE_KEY", "")
s = (raw or "").strip()

if s.lower().startswith("0x"):
    s = s[2:]

# remove non-hex characters
s2 = re.sub(r"[^0-9a-fA-F]", "", s)

# keep last 64 hex chars if longer
if len(s2) >= 64:
    s2 = s2[-64:]

clean = "0x" + s2

ok_len = (len(clean) == 66)
ok_hex = all(c in "0123456789abcdefABCDEF" for c in clean[2:])

print("raw_len", len(raw))
print("clean_len", len(clean))
print("ok_len66", ok_len)
print("ok_hex", ok_hex)
print("clean_head", clean[:6])
print("clean_tail", clean[-4:])

# convenience output (DO NOT paste this full line back into chat)
print("CLEAN_PRIVATE_KEY=" + clean)
