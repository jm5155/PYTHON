"""
All-in-One Python GUI Application
==================================

Features:
  - User Login / Register (passwords hashed, stored in SQLite)
  - Student Management (Add / Remove / List students, stored in SQLite)
  - YouTube Downloader (MP4 video or MP3 audio, saved to a local folder)
  - Simple Tkinter GUI tying it all together

Requirements
------------
Install these before running:

    pip install yt-dlp

You also need "ffmpeg" installed on your system and available on PATH
(needed for MP3 conversion, and for merging video+audio for some MP4s):

    Windows : https://ffmpeg.org/download.html  (add the /bin folder to PATH)
    macOS   : brew install ffmpeg
    Linux   : sudo apt install ffmpeg

Run
---
    python all_in_one_app.py

A folder called "app_data" will be created next to this script the first
time you run it. It contains:
    app_data/app.db          -> SQLite database (users + students)
    app_data/downloads/      -> downloaded MP3/MP4 files
"""

import os
import re
import sqlite3
import hashlib
import hmac
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# --------------------------------------------------------------------------
# Paths / directory setup
# --------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "app_data")
DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# --------------------------------------------------------------------------
# Database layer
# --------------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_no TEXT UNIQUE NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            course TEXT,
            year_level TEXT
        )
        """
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Password hashing helpers (PBKDF2, no extra dependencies needed)
# --------------------------------------------------------------------------

def hash_password(password: str, salt: bytes = None):
    if salt is None:
        salt = os.urandom(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex(), pwd_hash.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    _, computed_hash = hash_password(password, salt)
    return hmac.compare_digest(computed_hash, hash_hex)


# --------------------------------------------------------------------------
# User account operations
# --------------------------------------------------------------------------

def register_user(username: str, password: str):
    username = username.strip()
    if not username or not password:
        raise ValueError("Username and password cannot be empty.")
    salt_hex, hash_hex = hash_password(password)
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO users (username, salt, password_hash) VALUES (?, ?, ?)",
            (username, salt_hex, hash_hex),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Username '{username}' already exists.")
    finally:
        conn.close()


def login_user(username: str, password: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT salt, password_hash FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if row is None:
        return False
    salt_hex, hash_hex = row
    return verify_password(password, salt_hex, hash_hex)


# --------------------------------------------------------------------------
# Student operations
# --------------------------------------------------------------------------

def add_student(student_no, first_name, last_name, course, year_level):
    if not student_no.strip() or not first_name.strip() or not last_name.strip():
        raise ValueError("Student No., First Name, and Last Name are required.")
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO students (student_no, first_name, last_name, course, year_level) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_no.strip(), first_name.strip(), last_name.strip(),
             course.strip(), year_level.strip()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Student No. '{student_no}' already exists.")
    finally:
        conn.close()


def remove_student(student_no: str):
    conn = get_connection()
    cur = conn.execute("DELETE FROM students WHERE student_no = ?", (student_no.strip(),))
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


def list_students():
    conn = get_connection()
    rows = conn.execute(
        "SELECT student_no, first_name, last_name, course, year_level "
        "FROM students ORDER BY last_name, first_name"
    ).fetchall()
    conn.close()
    return rows


# --------------------------------------------------------------------------
# YouTube downloader (uses yt-dlp)
# --------------------------------------------------------------------------

def download_youtube(url: str, as_mp3: bool, progress_callback=None):
    """
    Downloads a YouTube video as MP4 (video+audio) or MP3 (audio only)
    into DOWNLOAD_DIR. Requires yt-dlp and ffmpeg to be installed.
    """
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Run: pip install yt-dlp"
        ) from exc

    def hook(d):
        if progress_callback is None:
            return
        if d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            progress_callback(f"Downloading... {pct}")
        elif d.get("status") == "finished":
            progress_callback("Processing / converting...")

    outtmpl = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    if as_mp3:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "quiet": True,
            "noprogress": True,
        }
    else:
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/mp4/best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "merge_output_format": "mp4",
            "quiet": True,
            "noprogress": True,
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "video")

    if progress_callback:
        progress_callback(f"Done: {title}")
    return title


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("All-in-One App")
        self.geometry("640x520")
        self.resizable(False, False)

        self.current_user = None

        self.container = tk.Frame(self)
        self.container.pack(fill="both", expand=True)

        self.frames = {}
        for F in (LoginFrame, MainFrame):
            frame = F(self.container, self)
            self.frames[F] = frame
            frame.place(relwidth=1, relheight=1)

        self.show_frame(LoginFrame)

    def show_frame(self, frame_class):
        frame = self.frames[frame_class]
        if hasattr(frame, "on_show"):
            frame.on_show()
        frame.tkraise()


class LoginFrame(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app

        tk.Label(self, text="Login / Register", font=("Segoe UI", 18, "bold")).pack(pady=30)

        form = tk.Frame(self)
        form.pack(pady=10)

        tk.Label(form, text="Username:").grid(row=0, column=0, sticky="e", padx=5, pady=8)
        self.username_var = tk.StringVar()
        tk.Entry(form, textvariable=self.username_var, width=30).grid(row=0, column=1, pady=8)

        tk.Label(form, text="Password:").grid(row=1, column=0, sticky="e", padx=5, pady=8)
        self.password_var = tk.StringVar()
        tk.Entry(form, textvariable=self.password_var, show="*", width=30).grid(row=1, column=1, pady=8)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Login", width=12, command=self.do_login).grid(row=0, column=0, padx=8)
        tk.Button(btn_frame, text="Register", width=12, command=self.do_register).grid(row=0, column=1, padx=8)

        self.status_label = tk.Label(self, text="", fg="red")
        self.status_label.pack()

    def on_show(self):
        self.password_var.set("")
        self.status_label.config(text="")

    def do_login(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if login_user(username, password):
            self.app.current_user = username
            self.app.show_frame(MainFrame)
        else:
            self.status_label.config(text="Invalid username or password.")

    def do_register(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()
        try:
            register_user(username, password)
            messagebox.showinfo("Success", "Account created. You can now log in.")
            self.status_label.config(text="")
        except ValueError as e:
            self.status_label.config(text=str(e))


class MainFrame(tk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent)
        self.app = app

        top = tk.Frame(self)
        top.pack(fill="x", pady=10, padx=10)
        self.welcome_label = tk.Label(top, text="", font=("Segoe UI", 12, "bold"))
        self.welcome_label.pack(side="left")
        tk.Button(top, text="Logout", command=self.logout).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.students_tab = StudentsTab(notebook)
        self.download_tab = DownloadTab(notebook)

        notebook.add(self.students_tab, text="Student Management")
        notebook.add(self.download_tab, text="YouTube Downloader")

    def on_show(self):
        self.welcome_label.config(text=f"Logged in as: {self.app.current_user}")
        self.students_tab.refresh_list()

    def logout(self):
        self.app.current_user = None
        self.app.show_frame(LoginFrame)


class StudentsTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        form = tk.LabelFrame(self, text="Add Student")
        form.pack(fill="x", padx=10, pady=10)

        labels = ["Student No.", "First Name", "Last Name", "Course", "Year Level"]
        self.vars = {label: tk.StringVar() for label in labels}

        for i, label in enumerate(labels):
            tk.Label(form, text=label + ":").grid(row=i // 3, column=(i % 3) * 2, sticky="e", padx=5, pady=5)
            tk.Entry(form, textvariable=self.vars[label], width=18).grid(
                row=i // 3, column=(i % 3) * 2 + 1, padx=5, pady=5
            )

        btn_row = tk.Frame(form)
        btn_row.grid(row=2, column=0, columnspan=6, pady=8)
        tk.Button(btn_row, text="Add Student", command=self.add_student).pack(side="left", padx=5)
        tk.Button(btn_row, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=5)
        tk.Button(btn_row, text="Refresh", command=self.refresh_list).pack(side="left", padx=5)

        remove_frame = tk.Frame(self)
        remove_frame.pack(fill="x", padx=10)
        tk.Label(remove_frame, text="Remove by Student No.:").pack(side="left")
        self.remove_var = tk.StringVar()
        tk.Entry(remove_frame, textvariable=self.remove_var, width=15).pack(side="left", padx=5)
        tk.Button(remove_frame, text="Remove", command=self.remove_by_no).pack(side="left")

        columns = ("student_no", "first_name", "last_name", "course", "year_level")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=10)
        for col, text in zip(columns, ["Student No.", "First Name", "Last Name", "Course", "Year Level"]):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=110)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

    def refresh_list(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for student in list_students():
            self.tree.insert("", "end", values=student)

    def add_student(self):
        try:
            add_student(
                self.vars["Student No."].get(),
                self.vars["First Name"].get(),
                self.vars["Last Name"].get(),
                self.vars["Course"].get(),
                self.vars["Year Level"].get(),
            )
            for v in self.vars.values():
                v.set("")
            self.refresh_list()
        except ValueError as e:
            messagebox.showerror("Error", str(e))

    def remove_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No selection", "Select a student row to remove.")
            return
        student_no = self.tree.item(selected[0])["values"][0]
        if remove_student(str(student_no)):
            self.refresh_list()

    def remove_by_no(self):
        student_no = self.remove_var.get().strip()
        if not student_no:
            return
        if remove_student(student_no):
            messagebox.showinfo("Removed", f"Student '{student_no}' removed.")
            self.remove_var.set("")
            self.refresh_list()
        else:
            messagebox.showerror("Not found", f"No student with Student No. '{student_no}'.")


class DownloadTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent)

        tk.Label(self, text="YouTube URL:").pack(pady=(20, 5))
        self.url_var = tk.StringVar()
        tk.Entry(self, textvariable=self.url_var, width=60).pack()

        self.format_var = tk.StringVar(value="mp4")
        fmt_frame = tk.Frame(self)
        fmt_frame.pack(pady=10)
        tk.Radiobutton(fmt_frame, text="MP4 (video)", variable=self.format_var, value="mp4").pack(side="left", padx=10)
        tk.Radiobutton(fmt_frame, text="MP3 (audio only)", variable=self.format_var, value="mp3").pack(side="left", padx=10)

        tk.Button(self, text="Download", command=self.start_download).pack(pady=10)

        self.status_var = tk.StringVar(value="Idle.")
        tk.Label(self, textvariable=self.status_var, fg="blue").pack(pady=5)

        tk.Label(self, text=f"Files are saved to:\n{DOWNLOAD_DIR}", justify="center").pack(pady=20)
        tk.Button(self, text="Open Downloads Folder", command=self.open_folder).pack()

    def open_folder(self):
        try:
            os.startfile(DOWNLOAD_DIR)  # Windows
        except AttributeError:
            os.system(f'open "{DOWNLOAD_DIR}"' if os.uname().sysname == "Darwin" else f'xdg-open "{DOWNLOAD_DIR}"')

    def start_download(self):
        url = self.url_var.get().strip()
        if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", url):
            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
            return

        as_mp3 = self.format_var.get() == "mp3"
        self.status_var.set("Starting download...")

        def update_status(text):
            self.status_var.set(text)

        def worker():
            try:
                title = download_youtube(url, as_mp3, progress_callback=update_status)
                self.status_var.set(f"Finished: {title}")
            except Exception as e:
                self.status_var.set("Error.")
                messagebox.showerror("Download failed", str(e))

        threading.Thread(target=worker, daemon=True).start()


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app = App()
    app.mainloop()
