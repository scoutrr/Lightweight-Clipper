import subprocess, os, time, shutil, ctypes, json, threading, tkinter as tk
from tkinter import ttk
import keyboard

# Native Windows paths inside the user profile directory to enforce write permissions
OUTPUT_FOLDER = os.path.join(os.path.expanduser("~"), "Videos", "MyCustomClips")
BUFFER_FOLDER = os.path.join(OUTPUT_FOLDER, "temp_buffer")
CONFIG_FILE = os.path.join(OUTPUT_FOLDER, "clipper_config.json")
HOTKEY_CLIP = "ctrl+shift+c"
CLIP_DURATION_SECONDS = 30

def find_ffmpeg():
    possible_paths = [shutil.which("ffmpeg"), r"C:\ffmpeg\bin\ffmpeg.exe", r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"]
    winget_base = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
    if os.path.exists(winget_base):
        for root, _, files in os.walk(winget_base):
            if "ffmpeg.exe" in files: return os.path.join(root, "ffmpeg.exe")
    for path in possible_paths:
        if path and os.path.exists(path): return path
    return "ffmpeg"

FFMPEG_PATH = find_ffmpeg()

class ClipperApp:
    def __init__(self):
        self.buffer_process = None
        self.monitors = self.get_all_monitors()
        self.selected_indices = self.load_config()
        self.is_recording = False
        self.chks = []
        
        self.root = tk.Tk()
        self.root.title("Lightweight Clipper")
        self.root.geometry("400x380")
        self.root.configure(bg="#1e1e1e")
        
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure("TLabel", background="#1e1e1e", foreground="#ffffff", font=("Arial", 10))
        self.style.configure("TCheckbutton", background="#1e1e1e", foreground="#ffffff", font=("Arial", 10))
        
        ttk.Label(self.root, text="Select Screen(s) to Record:", font=("Arial", 12, "bold")).pack(pady=10)
        
        self.vars = []
        for i, m in enumerate(self.monitors):
            var = tk.BooleanVar()
            if self.selected_indices and i in self.selected_indices: var.set(True)
            elif not self.selected_indices and m["is_main"]: var.set(True)
            var.trace_add("write", lambda *args: self.validate_checkboxes())
            self.vars.append(var)
            
            tag = " (Main)" if m["is_main"] else ""
            chk = ttk.Checkbutton(self.root, text=f"Screen {i+1}: {m['width']}x{m['height']}{tag}", variable=var)
            chk.pack(anchor="w", padx=20, pady=2)
            self.chks.append(chk)

        self.status_label = ttk.Label(self.root, text="Status: Stopped", font=("Arial", 10, "italic"), foreground="#ff4444")
        self.status_label.pack(pady=10)

        self.btn_toggle = tk.Button(self.root, text="Start Background Service", command=self.toggle_service, bg="#2ea44f", fg="white", font=("Arial", 10, "bold"), borderwidth=0, padx=10, pady=8)
        self.btn_toggle.pack(fill="x", padx=20, pady=5)

        ttk.Label(self.root, text=f"Global Shortcut: {HOTKEY_CLIP.upper()} to save a clip", font=("Arial", 9)).pack(pady=10)
        
        keyboard.unhook_all()
        keyboard.add_hotkey(HOTKEY_CLIP, self.save_clip, suppress=False)
        
        self.validate_checkboxes()
        
        # Disabled the autostart feature here to guarantee the tool boots up deactivated

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def get_all_monitors(self):
        user32 = ctypes.windll.user32
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]
        monitors = []
        def callback(h_monitor, hdc_monitor, lprc_monitor, dw_data):
            info = MONITORINFO()
            info.cbSize = 40
            if user32.GetMonitorInfoW(h_monitor, ctypes.byref(info)):
                monitors.append({"width": info.rcMonitor.right - info.rcMonitor.left, "height": info.rcMonitor.bottom - info.rcMonitor.top, "x": info.rcMonitor.left, "y": info.rcMonitor.top, "is_main": bool(info.dwFlags & 1)})
            return True
        MonitorEnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong)
        user32.EnumDisplayMonitors(0, None, MonitorEnumProc(callback), 0)
        return monitors

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f: return json.load(f)["selected_monitors"]
            except: return None
        return None

    def save_config(self, indices):
        try:
            with open(CONFIG_FILE, "w") as f: json.dump({"selected_monitors": indices}, f)
        except: pass

    def validate_checkboxes(self):
        if self.is_recording: return
        if any(var.get() for var in self.vars):
            self.btn_toggle.config(state="normal", bg="#2ea44f")
            self.status_label.config(text="Status: Stopped", foreground="#ff4444")
        else:
            self.btn_toggle.config(state="disabled", bg="#555555")
            self.status_label.config(text="Status: Select at least one screen", foreground="#cca000")

    def toggle_service(self):
        if self.is_recording:
            self.stop_buffer()
            for chk in self.chks: chk.config(state="normal")
            self.is_recording = False
            self.validate_checkboxes()
        else:
            indices = [i for i, var in enumerate(self.vars) if var.get()]
            if not indices: return
            self.save_config(indices)
            for chk in self.chks: chk.config(state="disabled")
            valid_monitors = [self.monitors[i] for i in indices if i < len(self.monitors)]
            min_x, min_y = min(m["x"] for m in valid_monitors), min(m["y"] for m in valid_monitors)
            max_x, max_y = max(m["x"] + m["width"] for m in valid_monitors), max(m["y"] + m["height"] for m in valid_monitors)
            w, h = max_x - min_x, max_y - min_y
            all_min_x, all_min_y = min(m["x"] for m in self.monitors), min(m["y"] for m in self.monitors)
            all_max_x, all_max_y = max(m["x"] + m["width"] for m in self.monitors), max(m["y"] + m["height"] for m in self.monitors)
            
            os.makedirs(BUFFER_FOLDER, exist_ok=True)
            os.makedirs(OUTPUT_FOLDER, exist_ok=True)
            
            ffmpeg_cmd = [FFMPEG_PATH, "-y", "-f", "gdigrab", "-framerate", "60", "-offset_x", str(all_min_x), "-offset_y", str(all_min_y), "-video_size", f"{all_max_x - all_min_x}x{all_max_y - all_min_y}", "-i", "desktop", "-vf", f"crop={w}:{h}:{min_x - all_min_x}:{min_y - all_min_y}", "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-f", "segment", "-segment_time", "5", "-reset_timestamps", "1", os.path.join(BUFFER_FOLDER, "chunk_%03d.mp4")]
            
            self.buffer_process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            self.status_label.config(text="Status: Recording Active", foreground="#2ea44f")
            self.btn_toggle.config(text="Stop Background Service", bg="#cb2431")
            self.is_recording = True

    def stop_buffer(self):
        if self.buffer_process is not None:
            try: self.buffer_process.communicate(input=b'q', timeout=1)
            except:
                try: self.buffer_process.kill()
                except: pass
            self.buffer_process = None
        if os.path.exists(BUFFER_FOLDER): shutil.rmtree(BUFFER_FOLDER, ignore_errors=True)

    def save_clip(self):
        if not self.is_recording or self.buffer_process is None: return
        threading.Thread(target=self._stitch_worker, daemon=True).start()

    def _stitch_worker(self):
        try:
            chunks = [os.path.join(BUFFER_FOLDER, f) for f in os.listdir(BUFFER_FOLDER) if f.endswith('.mp4')]
            chunks.sort(key=os.path.getmtime)
        except: return
        
        if len(chunks) > 1:
            chunks = chunks[:-1]
            
        needed_chunks_count = max(1, CLIP_DURATION_SECONDS // 5)
        recent_chunks = chunks[-needed_chunks_count:]
        if len(recent_chunks) < 2: return
        
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        output_file = os.path.join(OUTPUT_FOLDER, f"clip_{timestamp}.mp4")
        list_file_path = os.path.join(BUFFER_FOLDER, "concat_list.txt")
        try:
            with open(list_file_path, "w") as f:
                for chunk in recent_chunks: f.write(f"file '{chunk.replace('\\', '/')}'\n")
            merge_cmd = [FFMPEG_PATH, "-y", "-f", "concat", "-safe", "0", "-i", list_file_path, "-c", "copy", output_file]
            p = subprocess.Popen(merge_cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
            p.wait()
        except: pass

    def on_close(self):
        self.stop_buffer()
        self.root.destroy()

if __name__ == "__main__":
    subprocess.run("taskkill /f /im ffmpeg.exe", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    if os.path.exists(BUFFER_FOLDER): shutil.rmtree(BUFFER_FOLDER, ignore_errors=True)
    ClipperApp()
