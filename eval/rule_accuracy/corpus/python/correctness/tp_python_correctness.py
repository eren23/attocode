# Correctness issues — true positives

def bad_mutable_default(items=[]):  # expect: python/py-mutable-default-arg
    items.append(1)
    return items

def bad_mutable_dict(config={}):  # expect: python/py-mutable-default-arg
    config["key"] = "value"
    return config

def bad_bare_except():
    try:
        risky()
    except:  # expect: python/py-bare-except
        pass
