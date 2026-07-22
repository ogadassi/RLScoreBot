
import sys
import importlib.util

def check_import(module_name):
    try:
        if importlib.util.find_spec(module_name) is None:
            print(f"[-] {module_name} is NOT installed.")
        else:
            print(f"[+] {module_name} is installed.")
            module = importlib.import_module(module_name)
            print(f"    Version: {getattr(module, '__version__', 'unknown')}")
            print(f"    File: {getattr(module, '__file__', 'unknown')}")
    except Exception as e:
        print(f"[-] Error checking {module_name}: {e}")

print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")

check_import("discord")
check_import("nacl")
check_import("discord.opus")
