# Style issues — true positives

def bad_dict_keys(d):
    for key in d.keys():  # expect: python/py-dict-keys-iteration
        print(key)

def bad_isinstance_chain(x):
    if isinstance(x, int) or isinstance(x, float):  # expect: python/py-isinstance-chain
        return True
