# Code evaluation — true negatives (safe patterns)
# no-expect: These should NOT trigger code injection rules

import ast
import json

def safe_literal(data_str):
    # ast.literal_eval is safe — only evaluates literals
    return ast.literal_eval(data_str)  # ok: security/python_dynamic_eval

def safe_json_parse(json_str):
    return json.loads(json_str)

def safe_int_convert(value_str):
    return int(value_str)
