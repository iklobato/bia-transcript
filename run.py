#!/usr/bin/env python3
"""
Run script for the Audio Transcription API using Poetry.
"""

import subprocess
import sys


def main():
    """Run the application using Poetry."""
    try:
        # Run the app using Poetry
        subprocess.run(["poetry", "run", "python", "app.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running application: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nApplication stopped by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
