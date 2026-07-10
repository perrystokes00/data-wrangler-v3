with open('dv_pipeline.py', encoding='utf-8') as f:
    lines = f.readlines()

print("Lines adding to bad_ids:")
for i, line in enumerate(lines):
    if 'bad_ids.add' in line:
        # Print context - find the rule name nearby
        context = ''.join(lines[max(0,i-10):i+2])
        import re
        rules = re.findall(r'"rule":\s*"(\w+)"', context)
        print(f"  Line {i+1}: rule={rules[-1] if rules else 'UNKNOWN'}")
