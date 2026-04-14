# Command injection patterns — true positives
# These are INTENTIONALLY insecure for rule accuracy testing

import os
import subprocess

def bad_os_system(cmd):
    os.system(cmd)  # expect: security/python_os_system  # nosec B605 — intentional test case

def bad_shell_true(user_cmd):
    subprocess.call(user_cmd, shell=True)  # expect: security/python_shell_true  # nosec

def bad_popen_shell(cmd):
    subprocess.Popen(cmd, shell=True)  # expect: security/python_shell_true  # nosec
