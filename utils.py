import os

def full_path(*args):
    cwd = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(cwd, *args)