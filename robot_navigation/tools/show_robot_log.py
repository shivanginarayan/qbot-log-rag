#!/usr/bin/env python3
from pathlib import Path


LOG_FILE = Path('/home/nvidia/857_Final_Project_Code/runtime_logs/robot_interaction_log.csv')


def main():
    if not LOG_FILE.exists():
        print(f'No log file found yet: {LOG_FILE}')
        return

    print(f'Reading: {LOG_FILE}\n')
    with LOG_FILE.open('r', encoding='utf-8') as log_handle:
        for line in log_handle:
            print(line.rstrip())


if __name__ == '__main__':
    main()
