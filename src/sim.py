
import time
import sys

filename = sys.argv[1]

try:
    with open(filename, 'r') as f:
        for line in f:
            # .strip() removes the extra newline from the file since print() adds one
            print(line.strip())
            sys.stdout.flush() 
            time.sleep(3)
except FileNotFoundError:
    print(f"Error: {filename} not found.")