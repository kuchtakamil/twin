import sys
import os

def handler(event, context):
    print(f"PYTHONPATH: {sys.path}")
    print(f"CWD: {os.getcwd()}")
    print(f"Directory listing: {os.listdir(os.getcwd())}")

    try:
        from mangum import Mangum
        print("Mangum imported successfully")
    except ImportError as e:
        print(f"Import failed: {e}")
        # Look for mangum in specific subdirectories
        for root, dirs, files in os.walk(os.getcwd()):
            if 'mangum' in dirs:
                print(f"Found mangum directory at: {root}/mangum")

