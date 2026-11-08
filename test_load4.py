from quadrix.world.nbt import read_nbt

data = read_nbt(open('H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt', 'rb').read())
print(f'DataVersion: {data["DataVersion"].int_val}')
print(f'Number of states: {len(data["states"].list_val)}')

states = data["states"].list_val
# Check states 0, 1, 2, and maybe some with properties
for i in [0, 1, 2, 3, 4, 5, 100, 500, 1000]:
    s = states[i]
    print(f'\\nState {i} (tag type: {s.tag_type}):')
    if s.is_compound:
        for k, v in s.compound_val.items():
            iv = v.int_val if hasattr(v, 'int_val') else None
            sv = v.str_val if hasattr(v, 'str_val') else None
            print(f'  {k}: int_val={iv}, str_val={str(sv)[:40] if sv else None}')