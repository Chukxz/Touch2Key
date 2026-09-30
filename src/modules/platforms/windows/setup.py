def setup_windows(interactive: bool = True, no_restart: bool = False) -> bool:
    """
    Executes full platform setup for Windows.
    Returns True if a reboot is needed for the driver, otherwise False.
    """
    print("--- Windows Platform Setup ---")

    kill_adb()
    download_adb()
    download_interception()

    if not is_admin():
        if interactive:
            print("[!] Elevation required to install Interception driver.")
            if request_elevation():
                sys.exit(0)
            raise PermissionError("UAC elevation prompt was rejected.")
        else:
            raise PermissionError(
                "Driver registration requires Administrator privileges. "
                "Please restart the application as Administrator."
            )

    needs_reboot = register_driver()

    if interactive:
        if needs_reboot and not no_restart:
            print("\n" + "=" * 55)
            print(" SYSTEM RESTART REQUIRED ".center(55, "="))
            print("=" * 55)
            choice = input("Restart PC now in 5 seconds? (y/N): ").strip().lower()
            if choice == "y":
                subprocess.run(
                    [
                        "shutdown",
                        "/r",
                        "/t",
                        "5",
                        "/c",
                        "Driver installation complete.",
                    ]
                )
            else:
                print("[+] Please reboot manually to finalize driver registration.")
        else:
            print("\n[+] Setup finished successfully.")

        input("\nPress Enter to exit...")

    return needs_reboot
