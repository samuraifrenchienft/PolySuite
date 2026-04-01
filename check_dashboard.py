import sys
html = sys.stdin.read()
if 'GetaLife' in html:
    print('SUCCESS: Actual wallet names found - data rendered correctly')
elif '${w.nickname}' in html:
    print('PROBLEM: Template literals found - JS not replacing data')
    count = html.count('${w.nickname}')
    print(f'Found {count} instances of unprocessed template literals')
else:
    print('UNCLEAR: Neither actual names nor template literals found')
    if 'wallet-nickname' in html:
        print('Wallet nickname class found in HTML')
    else:
        print('No wallet-related content found')

