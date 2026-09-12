from modules.utils import ADB


def run():
    if ADB.exists():
        print(f"ADB Executable found at: {ADB}")
    else:
        print("ADB Executable not found.")


if __name__ == "__main__":
    run()
