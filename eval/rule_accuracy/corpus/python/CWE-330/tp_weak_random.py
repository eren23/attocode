# Weak random — true positives for rule accuracy testing
import random

def bad_token():
    return random.random()  # expect: security/python_weak_random

def bad_otp():
    return random.randint(100000, 999999)  # expect: security/python_weak_random

def bad_password_char():
    return random.choice("abcdefghijklmnop")  # expect: security/python_weak_random
