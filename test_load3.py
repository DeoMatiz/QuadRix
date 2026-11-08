from quadrix.world.nbt import read_nbt

data = read_nbt(open('H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt', 'rb').read())
states = data['states']
# states is a Tag of type List
print(f'states tag type: {states.tag_type}')
print(f'states list_val type: {type(states.list_val)}')
print(f'Number of states: {len(states.list_val)}')

# Check first state
first_state = states.list_val[0]
print(f'\\nFirst state tag type: {first_state.tag_type}')
print(f'First state compound_val keys: {list(first_state.compound_val.keys()) if first_state.is_compound else "not compound"}')

# Print all keys and values in first state
if first_state.is_compound:
    for k, v in first_state.compound_val.items():
        iv = v.int_val if hasattr(v, 'int_val') else None
        sv = v.str_val if hasattr(v, 'str_val') else None
        print(f'  {k}: int_val={iv}, str_val={str(sv)[:30] if sv else None}')