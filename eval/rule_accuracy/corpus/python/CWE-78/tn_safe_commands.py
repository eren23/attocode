# Command execution — true negatives (safe patterns)
# no-expect: These should NOT trigger command injection rules

import subprocess
import shlex

def safe_list_args(filename):
    subprocess.run(["ls", "-la", filename], check=True)

def safe_no_shell(args):
    subprocess.call(args)  # shell=False is default

def safe_shlex(user_input):
    args = shlex.split(user_input)
    subprocess.run(args, check=True)
