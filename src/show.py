from mapper_module.utils import ADB_EXE

def show_adb_exe():
    return ADB_EXE

if __name__ == "__main__":
    print(f"ADB Executable: {show_adb_exe()}")