# Performance issues — true positives

def bad_string_concat(items):
    result = ""
    for item in items:
        result += "item: "  # expect: python/py-string-concat-loop
    return result

def bad_import_in_function():
    import json  # expect: python/py-global-import-in-function
    return json.dumps({})
