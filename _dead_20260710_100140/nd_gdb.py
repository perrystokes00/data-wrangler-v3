@"
import fiona
path = r'C:\Users\perry\OneDrive\Documents\PPDM\claude_use_ai\data_wrangler\training\North_Dakota\gdb\NDOGD.gdb'
layers = fiona.listlayers(path)
print(f'Layers: {len(layers)}')
for l in layers:
    print(f'\n  {l}:')
    with fiona.open(path, layer=l) as src:
        print(f'    Records: {len(src):,}')
        schema = src.schema
        print(f'    Geometry: {schema["geometry"]}')
        for k, v in schema['properties'].items():
            print(f'    {k:30s} {v}')
        rec = next(iter(src))
        print(f'    --- Sample ---')
        for k, v in rec['properties'].items():
            print(f'    {k:30s} = {v!r}')
"@ | Out-File -Encoding utf8 check_nd.py
python check_nd.py
