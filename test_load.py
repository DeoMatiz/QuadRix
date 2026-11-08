from quadrix.world.nbt import read_nbt, TagType

data = read_nbt(open('H:/Test/QuadRix/.local/horizon-client-motion/block-registry.nbt', 'rb').read())
print(f'Keys: {list(data.keys())}')
print(f'DataVersion: {data.get("DataVersion")}')
for k, v in data.items():
    print(f'  {k}: tag_type={v.tag_type}')
    if hasattr(v, 'compound_val') and v.compound_val:
        for ck, cv in v.compound_val.items():
            print(f'    {ck}: type={type(cv).__name__}')
            if hasattr(cv, 'int_val'):
                print(f'      int_val={cv.int_val}')
            elif hasattr(cv, 'str_val'):
                s = cv.str_val
                print(f'      str_val={s[:50] if s else None}')