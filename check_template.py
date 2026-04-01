from pathlib import Path

_root = Path(__file__).resolve().parent
with open(_root / "src" / "dashboard" / "templates" / "index.html", encoding="utf-8") as f:
    content = f.read()

# Check if our console.log statements are in the file
print("console.log in template:", "console.log" in content)
print("initWallets logging:", "console.log('initWallets called" in content)

# Find the line with console.log in initWallets
import re

matches = re.findall(r"function\s+initWallets.*?console\.log[^}]+}", content, re.DOTALL)
if matches:
    print("\nFound console.log in initWallets function")
    print(matches[0][:200])
else:
    print("\nNOT finding console.log in initWallets")
