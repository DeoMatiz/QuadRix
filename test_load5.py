from quadrix.world.nbt import read_nbt

data = read_nbt(open('H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt', 'rb').read())
states = data["states"].list_val

# Check state 100 properties
s = states[100]
props = s.compound_val.get('properties')
print(f'State 100 properties type: {props.tag_type if hasattr(props, "tag_type") else type(props)}')
if props.is_compound:
    for k, v in props.compound_val.items():
        iv = v.int_val if hasattr(v, 'int_val') else None
        sv = v.str_val if hasattr(v, 'str_val') else None
        print(f'  {k}: int_val={iv}, str_val={str(sv)[:40] if sv else None}')

# Also check a state with no properties
s2 = states[1]
props2 = s2.compound_val.get('properties')
print(f'\\nState 1 has properties: {props2 is not None}')
if props2 is None:
    print('State 1 has no properties key')