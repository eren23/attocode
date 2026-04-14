# Correctness — true negatives (safe patterns)
# no-expect: These should NOT trigger correctness rules

def safe_default(items=None):
    if items is None:
        items = []
    items.append(1)
    return items

def safe_specific_except():
    try:
        risky()
    except ValueError:
        pass
    except (TypeError, KeyError) as e:
        log(e)
