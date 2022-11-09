
"""A very stupid program convenient to test pipes
"""
import time
import sys

for item in sys.argv[1:]:
    print(item,flush=True)
    time.sleep(1)
