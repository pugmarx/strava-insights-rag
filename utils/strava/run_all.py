import subprocess
import sys

def run_script(name):
    print(f"\n** Running {name} ...")
    result = subprocess.run([sys.executable, name], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {name} failed:")
        print(result.stderr)
        sys.exit(1)
    else:
        print(result.stdout)

def main():
    run_script("utils/strava/fetch_activites.py")
    run_script("utils/strava/store_activities.py")
    print("** All steps completed successfully.")

if __name__ == "__main__":
    main()
