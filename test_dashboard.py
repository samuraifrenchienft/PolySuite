import requests
import json

# Test if dashboard is serving the data
response = requests.get("http://127.0.0.1:5000/")
html = response.text

print("=== DASHBOARD DEBUG ===")
print(f"Response status: {response.status_code}")
print(f"Length: {len(html)} chars")

# Check if it contains template literals (bad)
if "${w.nickname}" in html:
    print("ERROR: Template literals not replaced - JS not working")
else:
    print("Template literals not found")

# Check if it contains actual wallet names
if "GetaLife" in html:
    print("GOOD: Wallet names rendered")
else:
    print("BAD: No wallet names in HTML")

# Check for table rows
table_rows = html.count("table-row")
print(f"Table rows found: {table_rows}")

# Extract a table row to see what's there
import re

rows = re.findall(r'<div class="table-row">.*?</div>', html, re.DOTALL)
if rows:
    print(f"\nFirst row (500 chars):")
    print(rows[0][:500])
else:
    print("NO table rows found!")
