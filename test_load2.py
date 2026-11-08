from quadrix.world.nbt import read_nbt

data = read_nbt(open('H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt', 'rb').read())
# Check defaults - data['defaults'] is a compound tag
print('=== DEFAULTS ===')
defaults = data['defaults']
if defaults.is_compound:
    for k, v in defaults.compound_val.items():
        iv = v.int_val if hasattr(v, 'int_val') else None
        print(f'  {k}: int_val={iv}')
# Check first few states
print()
print('=== FIRST 5 STATES ===')
states = data['states']
for i in range(min(5, len(states))):
    s = states[i]
    print(f'State {i}:')
    if s.is_compound:
        for ck, cv in s.compound_val.items():
            iv = cv.int_val if hasattr(cv, 'int_val') else None
            sv = cv.str_val if hasattr(cv, 'str_val') else None
            print(f'  {ck}: int_val={iv}, str_val={str(sv)[:30] if sv else None}')