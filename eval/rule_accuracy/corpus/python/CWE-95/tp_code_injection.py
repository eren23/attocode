# Code injection patterns — true positives
# INTENTIONALLY insecure for rule accuracy testing — nosec

def bad_eval(user_input):  # nosec B307
    result = eval(user_input)  # expect: security/python_dynamic_eval
    return result

def bad_exec(code_str):  # nosec B102
    exec(code_str)  # expect: security/python_dynamic_exec

def bad_eval_compile(source):  # nosec
    code = compile(source, "<string>", "eval")
    eval(code)  # expect: security/python_dynamic_eval
