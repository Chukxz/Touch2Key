import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json
from pathlib import Path
import tomlkit

# Added TOML_PATH to the imports
from modules.utils import JSONS_FOLDER, TOML_PATH
from modules.database.repositories import (
    LayoutsRepository,
    LayoutZonesRepository,
)
from modules.database.legacy_migration import migrate_json_layout

class LayoutManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Layout Manager")
        self.geometry("300x150")
        self.eval("tk::PlaceWindow . center")
        self.attributes("-topmost", True)

        os.makedirs(JSONS_FOLDER, exist_ok=True)

        # UI Setup
        ttk.Label(self, text="Touch2Key Profiles", font=("Helvetica", 12, "bold")).pack(
            pady=10
        )

        ttk.Button(self, text="Import Layout (.json)", command=self.import_layout).pack(
            fill=tk.X, padx=40, pady=5
        )
        ttk.Button(
            self, text="Export Layout (.json)", command=self.open_export_dialog
        ).pack(fill=tk.X, padx=40, pady=5)

    def select_layout(self): ...

    def import_layout(self):
        file_path_str = filedialog.askopenfilename(
            initialdir=JSONS_FOLDER,
            title="Select JSON Mapping Profile to Import",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )

        if not file_path_str:
            return

        file_path = Path(file_path_str)
        if not file_path.exists():
            messagebox.showerror("Error", f"File '{file_path.name}' not found.")
            return

        image_to_assign = ""

        # ==========================================
        # LEGACY TOML CHECK
        # If they are importing the active layout, save its image!
        # ==========================================
        if TOML_PATH.exists():
            try:
                with open(TOML_PATH, "r", encoding="utf-8") as f:
                    doc = tomlkit.load(f)

                legacy_json_str = doc.get("system", {}).get("json_path")

                # Check if the file they picked matches the active one in the TOML
                if (
                    legacy_json_str
                    and Path(legacy_json_str).resolve() == file_path.resolve()
                ):
                    image_to_assign = doc.get("system", {}).get("image_path", "")
                    print(
                        f"[INFO] Legacy active layout detected. Recovering image: {image_to_assign}"
                    )
            except Exception as e:
                print(f"[WARNING] Could not parse legacy TOML for image path: {e}")
        # ==========================================

        # Inject into SQLite
        layout_id = migrate_json_layout(
            json_path=file_path,
            image_path=image_to_assign,  # Pass the recovered image (or empty string if none)
            set_active=True,
        )

        if layout_id is not None:
            try:
                file_path.unlink()  # Clean up the source file
                messagebox.showinfo(
                    "Success",
                    f"Imported '{file_path.stem}' successfully!\nIt is now your active layout.",
                )
            except OSError:
                messagebox.showwarning(
                    "Warning",
                    f"Imported successfully, but could not delete source file: {file_path.name}",
                )
        else:
            messagebox.showerror(
                "Error", f"Failed to import {file_path.name}. Check terminal logs."
            )

    def open_export_dialog(self):
        layouts_repo = LayoutsRepository()
        all_layouts = layouts_repo.list_all()

        if not all_layouts:
            messagebox.showinfo("Empty", "No layouts found in the database to export.")
            return

        export_win = tk.Toplevel(self)
        export_win.title("Export Layout")
        export_win.geometry("250x200")
        export_win.eval(f"tk::PlaceWindow {str(export_win)} center")
        export_win.attributes("-topmost", True)
        export_win.grab_set()

        ttk.Label(export_win, text="Select Layout to Export:").pack(pady=5)

        listbox = tk.Listbox(export_win, selectmode=tk.SINGLE)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        for layout in all_layouts:
            listbox.insert(tk.END, layout.name)

        def on_export_confirm():
            selection = listbox.curselection()
            if not selection:
                return

            selected_name = listbox.get(selection[0])
            selected_layout = next(l for l in all_layouts if l.name == selected_name)

            self.execute_export(selected_layout)
            export_win.destroy()

        ttk.Button(export_win, text="Save As...", command=on_export_confirm).pack(
            pady=10
        )

    def execute_export(self, layout):
        save_path_str = filedialog.asksaveasfilename(
            initialdir=JSONS_FOLDER,
            initialfile=f"{layout.name}.json",
            title="Save Layout As",
            defaultextension=".json",
            filetypes=(("JSON files", "*.json"), ("All files", "*.*")),
        )

        if not save_path_str:
            return

        zones_repo = LayoutZonesRepository()
        zones = zones_repo.list_for_layout(layout.id)

        output_content = []
        for zone in zones:
            entry = {
                "name": zone.name,
                "scancode": zone.scancode,
                "type": zone.zone_type,
                "cx": zone.cx or 0.0,
                "cy": zone.cy or 0.0,
                "val1": zone.r if zone.zone_type == "CIRCLE" else (zone.x1 or 0.0),
                "val2": zone.y1 or 0.0,
                "val3": zone.x2 or 0.0,
                "val4": zone.y2 or 0.0,
                "move_camera": bool(zone.move_camera),
            }
            output_content.append(entry)

        json_data = {
            "metadata": {
                "width": layout.width,
                "height": layout.height,
                "dpi": layout.dpi,
                "mouse_wheel_radius": layout.mouse_wheel_radius,
                "sprint_distance": layout.sprint_distance,
            },
            "content": output_content,
        }

        try:
            with open(save_path_str, "w", encoding="utf-8") as f:
                json.dump(json_data, f, indent=4)
            messagebox.showinfo(
                "Success", f"Layout exported to:\n{Path(save_path_str).name}"
            )
        except Exception as e:
            messagebox.showerror("Export Failed", str(e))


def run():
    app = LayoutManagerApp()
    app.mainloop()


if __name__ == "__main__":
    run()
