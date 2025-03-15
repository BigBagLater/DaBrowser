import os
import json
import uuid
import threading
import zipfile
import shutil
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time

# ------------------------------
# Persistence Layer
# ------------------------------
class PersistenceLayer:
    def __init__(self, filename="profiles.json"):
        self.filename = filename
        self.data = self.load_data()

    def load_data(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r") as f:
                    return json.load(f)
            except Exception as e:
                print("Error loading data:", e)
                return {}
        else:
            return {}

    def save_data(self):
        try:
            with open(self.filename, "w") as f:
                json.dump(self.data, f, indent=4)
        except Exception as e:
            print("Error saving data:", e)

    def get_profiles(self):
        return self.data

    def add_profile(self, profile):
        self.data[profile["fingerprint"]] = profile
        self.save_data()

    def update_profile(self, fingerprint, profile):
        self.data[fingerprint] = profile
        self.save_data()

    def delete_profile(self, fingerprint):
        if fingerprint in self.data:
            del self.data[fingerprint]
            self.save_data()

# ------------------------------
# Profile Manager
# ------------------------------
class ProfileManager:
    def __init__(self, persistence_layer):
        self.persistence = persistence_layer

    def create_profile(self, name, proxy_ip, proxy_port, proxy_user, proxy_pass):
        profile = {
            "fingerprint": str(uuid.uuid4()),
            "name": name,
            "proxy": {
                "ip": proxy_ip,
                "port": proxy_port,
                "username": proxy_user,
                "password": proxy_pass
            },
            "active": False
        }
        self.persistence.add_profile(profile)
        return profile

    def edit_profile(self, fingerprint, name, proxy_ip, proxy_port, proxy_user, proxy_pass):
        existing = self.persistence.get_profiles().get(fingerprint, {})
        active_status = existing.get("active", False)
        profile = {
            "fingerprint": fingerprint,
            "name": name,
            "proxy": {
                "ip": proxy_ip,
                "port": proxy_port,
                "username": proxy_user,
                "password": proxy_pass
            },
            "active": active_status
        }
        self.persistence.update_profile(fingerprint, profile)
        return profile

    def toggle_profile_status(self, fingerprint):
        profiles = self.persistence.get_profiles()
        if fingerprint in profiles:
            profile = profiles[fingerprint]
            profile["active"] = not profile.get("active", False)
            self.persistence.update_profile(fingerprint, profile)
            return profile
        return None

    def delete_profile(self, fingerprint):
        self.persistence.delete_profile(fingerprint)

    def list_profiles(self):
        return list(self.persistence.get_profiles().values())

# ------------------------------
# Browser Launcher with Proxy Authentication
# ------------------------------
def create_proxy_extension(proxy):
    proxy_ip = proxy.get("ip", "")
    proxy_port = proxy.get("port", "")
    proxy_username = proxy.get("username", "")
    proxy_password = proxy.get("password", "")
    
    if not proxy_ip or not proxy_port:
        return None

    temp_dir = os.path.join(os.getcwd(), "temp_extension")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir)
    
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """
    
    background_js = f'''
    var config = {{
        mode: "fixed_servers",
        rules: {{
            singleProxy: {{
                scheme: "http",
                host: "{proxy_ip}",
                port: parseInt("{proxy_port}")
            }},
            bypassList: ["localhost"]
        }}
    }};
    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function(){{}});
    function callbackFn(details) {{
        return {{
            authCredentials: {{
                username: "{proxy_username}",
                password: "{proxy_password}"
            }}
        }};
    }}
    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{urls: ["<all_urls>"]}},
        ['blocking']
    );
    '''
    
    with open(os.path.join(temp_dir, "manifest.json"), "w") as f:
        f.write(manifest_json)
    with open(os.path.join(temp_dir, "background.js"), "w") as f:
        f.write(background_js)
    
    extension_path = os.path.join(os.getcwd(), "proxy_auth_extension.crx")
    with zipfile.ZipFile(extension_path, 'w') as zp:
        for file in ["manifest.json", "background.js"]:
            zp.write(os.path.join(temp_dir, file), file)
    
    shutil.rmtree(temp_dir)
    return extension_path

def launch_browser_for_profile(profile, app, profile_manager):
    base_dir = os.path.join(os.getcwd(), "chrome_profiles")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    user_data_dir = os.path.join(base_dir, profile["fingerprint"])
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)

    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
    
    if profile["proxy"]["username"] and profile["proxy"]["password"]:
        ext_path = create_proxy_extension(profile["proxy"])
        if ext_path:
            chrome_options.add_extension(ext_path)
    elif profile["proxy"]["ip"] and profile["proxy"]["port"]:
        proxy = f"{profile['proxy']['ip']}:{profile['proxy']['port']}"
        chrome_options.add_argument(f"--proxy-server={proxy}")

    try:
        service = Service(log_path=os.devnull)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.get("https://luckybird.io")
        
        # Wait until the browser is closed
        while True:
            try:
                if not driver.window_handles:
                    break
            except Exception:
                break
            time.sleep(1)
        
        # Toggle profile back to inactive after closing
        profile_manager.toggle_profile_status(profile["fingerprint"])
        app.after(0, app.refresh_profile_list)
    except Exception as e:
        messagebox.showerror("Browser Launch Error", f"Failed to launch browser: {e}")

# ------------------------------
# Modern Confirm Dialog
# ------------------------------
class ModernConfirmDialog(ctk.CTkToplevel):
    def __init__(self, master, title, message, colors):
        super().__init__(master)
        self.colors = colors
        # The following line has been removed to omit a separate popup title.
        # self.title(title)
        self.geometry("400x150")
        self.resizable(False, False)
        self.grab_set()
        self.result = False

        self.configure(fg_color=self.colors["bg_main"])
        main_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_content"], corner_radius=8)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        msg_label = ctk.CTkLabel(
            main_frame, text=message, text_color=self.colors["text"],
            font=("Segoe UI", 12)
        )
        msg_label.pack(pady=(10, 20))
        
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(pady=(0, 10))
        
        yes_btn = ctk.CTkButton(
            btn_frame, text="Yes", fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"], corner_radius=6,
            font=("Segoe UI", 12, "bold"), width=120, command=self._on_yes
        )
        yes_btn.pack(side="left", padx=(0, 10))
        
        no_btn = ctk.CTkButton(
            btn_frame, text="No", fg_color=self.colors["bg_header"],
            hover_color=self.colors["bg_selected"], corner_radius=6,
            font=("Segoe UI", 12), width=120, command=self._on_no
        )
        no_btn.pack(side="right", padx=(10, 0))
        
        self.wait_window(self)
    
    def _on_yes(self):
        self.result = True
        self.destroy()
    
    def _on_no(self):
        self.result = False
        self.destroy()

# ------------------------------
# Modern Dashboard UI with Dark Theme
# ------------------------------
class ModernDashboardApp(ctk.CTk):
    def __init__(self, profile_manager, logo_path="Logo.png"):
        super().__init__()
        self.profile_manager = profile_manager
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        # Updated window title to "DaBrowser"
        self.title("DaBrowser")
        self.geometry("900x600")
        self.minsize(800, 500)
        
        if os.path.exists(logo_path):
            try:
                icon_image = Image.open(logo_path)
                icon_photo = ctk.CTkImage(light_image=icon_image, size=(icon_image.width, icon_image.height))
                self.iconphoto(False, icon_photo)

                self.logo_image = icon_photo
            except Exception as e:
                print("Error loading logo:", e)
        
        # Unified dark background color
        self.colors = {
            "bg_main": "#1E1E1E",
            "bg_content": "#1E1E1E",
            "bg_treeview": "#252526",
            "bg_header": "#333333",
            "bg_selected": "#37373D",
            "bg_hover": "#2D2D30",
            "bg_input": "#2B2B2B",
            "accent": "#0D6EFD",
            "accent_hover": "#0B5ED7",
            "text": "#D0D0D0",
            "text_secondary": "#ABABAB",
            "text_header": "#FFFFFF",
            "border": "#3F3F3F",
            "status_active": "#28A745",
            "status_inactive": "#888888",
            "danger": "#DC3545",
            "danger_hover": "#BB2D3B"
        }
        
        self._create_main_layout()
        self._create_header()
        self._create_treeview()
        self._create_status_bar()
        
        # Status indicators
        self.green_dot = self._create_dot(self.colors["status_active"])
        self.grey_dot = self._create_dot(self.colors["status_inactive"])
        
        self.refresh_profile_list()
        self.bind("<Configure>", self._on_resize)
    
    def _create_dot(self, color):
        size = (10, 10)
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((0, 0, size[0]-1, size[1]-1), fill=color)
        return ImageTk.PhotoImage(image)
        
    def _create_main_layout(self):
        self.main_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_main"], corner_radius=0)
        self.main_frame.pack(fill="both", expand=True)
        
        self.content_frame = ctk.CTkFrame(
            self.main_frame, fg_color=self.colors["bg_content"], 
            corner_radius=0, border_width=0
        )
        self.content_frame.pack(fill="both", expand=True, padx=0, pady=0)
    
    def _create_header(self):
        header_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 10), padx=10)
        
        # Left side: "Add Profile" button
        left_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        left_frame.pack(side="left")
        
        plus_icon = self._create_plus_icon()
        add_btn = ctk.CTkButton(
            left_frame, text="  Add Profile", image=plus_icon,
            compound="left", font=("Segoe UI", 14, "bold"),
            fg_color=self.colors["accent"], hover_color=self.colors["accent_hover"],
            corner_radius=6, command=self.on_add_profile, height=32
        )
        add_btn.pack(side="left")
        
        # Right side: Modern Search Bar
        right_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        right_frame.pack(side="right")
        
        self._create_modern_search_bar(right_frame)
    
    def _create_modern_search_bar(self, parent):
        search_container = ctk.CTkFrame(
            parent, fg_color=self.colors["bg_input"],
            corner_radius=8
        )
        search_container.pack(side="right", padx=10)
        
        search_icon = self._create_search_icon()
        search_icon_label = ctk.CTkLabel(search_container, image=search_icon, text="", width=20)
        search_icon_label.pack(side="left", padx=(8, 0))
        
        # Updated width from 200 to 160
        self.search_entry = ctk.CTkEntry(
            search_container, placeholder_text="Search",
            border_width=0, fg_color=self.colors["bg_input"], 
            text_color=self.colors["text"], placeholder_text_color=self.colors["text_secondary"],
            width=160, height=32
        )
        self.search_entry.pack(side="left", padx=8)
        self.search_entry.bind("<KeyRelease>", self._on_search)
    
    def _create_plus_icon(self):
        size = (16, 16)
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((3, 7, 13, 9), fill="white")
        draw.rectangle((7, 3, 9, 13), fill="white")
        return ctk.CTkImage(light_image=image, size=size)

    
    def _create_search_icon(self):
        size = (16, 16)
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((2, 2, 10, 10), outline=self.colors["text_secondary"], width=1)
        draw.line((9, 9, 13, 13), fill=self.colors["text_secondary"], width=1)
        return ctk.CTkImage(light_image=image, size=size)

    def _create_treeview(self):
        tree_frame = ctk.CTkFrame(self.content_frame, fg_color=self.colors["bg_treeview"], corner_radius=0)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", 
                        background=self.colors["bg_treeview"],
                        foreground=self.colors["text"],
                        fieldbackground=self.colors["bg_treeview"],
                        borderwidth=0,
                        font=("Segoe UI", 11))
        style.configure("Treeview.Heading", 
                        background=self.colors["bg_header"],
                        foreground=self.colors["text_secondary"],
                        borderwidth=0,
                        font=("Segoe UI", 10, "bold"))
        style.map("Treeview",
                  background=[("selected", self.colors["bg_selected"])],
                  foreground=[("selected", self.colors["text_header"])])
        
        columns = ("name", "fingerprint", "proxy")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="tree headings", height=20)
        
        # Column #0 (status dot)
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=40, anchor="center", stretch=False)
        
        self.tree.heading("name", text="PROFILE", anchor="w")
        self.tree.column("name", width=200, anchor="w", stretch=True)
        
        self.tree.heading("fingerprint", text="ID", anchor="center")
        self.tree.column("fingerprint", width=80, anchor="center", stretch=False)
        
        self.tree.heading("proxy", text="PROXY", anchor="w")
        self.tree.column("proxy", width=300, anchor="w", stretch=True)
        
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        style.configure("Vertical.TScrollbar", 
                        background=self.colors["bg_treeview"],
                        troughcolor=self.colors["bg_main"],
                        arrowcolor=self.colors["text_secondary"])
        
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        
        # Double-click to launch
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        # Left-click selects
        self.tree.bind("<Button-1>", self._on_tree_click)
        # Right-click anywhere on the row to show the popup menu
        self.tree.bind("<Button-3>", self._on_tree_right_click)
        # Hover effect
        self.tree.bind("<Motion>", self._on_hover)
        
        self.popup_menu = None
        self.current_selected_item = None
        self.hovered_item = None
    
    def _create_status_bar(self):
        status_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent", corner_radius=0)
        status_frame.pack(fill="x", side="bottom", padx=10, pady=(0, 10))
        
        self.status_label = ctk.CTkLabel(
            status_frame, text="", fg_color="transparent",
            text_color=self.colors["text_secondary"], anchor="w",
            font=("Segoe UI", 10)
        )
        self.status_label.pack(side="left")
    
    def refresh_profile_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        self.profiles = self.profile_manager.list_profiles()
        search_term = self.search_entry.get().lower().strip() if hasattr(self, "search_entry") else ""
        
        if search_term:
            self.profiles = [
                p for p in self.profiles
                if search_term in p['name'].lower() or
                   search_term in p['proxy']['ip'] or
                   search_term in p['proxy']['port']
            ]
        
        for p in self.profiles:
            short_fingerprint = p['fingerprint'][:6]
            proxy_text = f"{p['proxy']['ip']}:{p['proxy']['port']}"
            tag = 'active' if p.get('active', False) else 'inactive'
            
            dot_image = self.green_dot if p.get('active', False) else self.grey_dot
            self.tree.insert(
                "", tk.END, iid=p['fingerprint'], text="",
                image=dot_image,
                values=(p['name'], short_fingerprint, proxy_text),
                tags=(tag,)
            )
        
        # Alternate row colors
        for i, item in enumerate(self.tree.get_children()):
            if i % 2 == 0:
                self.tree.item(item, tags=(*self.tree.item(item)['tags'], 'even'))
            else:
                self.tree.item(item, tags=(*self.tree.item(item)['tags'], 'odd'))
                
        self.tree.tag_configure('even', background=self.colors["bg_treeview"])
        self.tree.tag_configure('odd', background=self.colors["bg_hover"])
        
        total = len(self.profiles)
        self.status_label.configure(text=f"{total} Profile{'s' if total != 1 else ''}")
    
    def _on_hover(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region in ("cell", "tree"):
            item = self.tree.identify_row(event.y)
            if item and self.hovered_item != item:
                # Reset the previously hovered row
                if self.hovered_item:
                    tags = self.tree.item(self.hovered_item)['tags']
                    if 'hover' in tags:
                        tags = tuple(t for t in tags if t != 'hover')
                        self.tree.item(self.hovered_item, tags=tags)
                
                self.hovered_item = item
                tags = self.tree.item(item)['tags']
                self.tree.item(item, tags=(*tags, 'hover'))
                self.tree.tag_configure('hover', background=self.colors["bg_hover"])
    
    def _on_tree_click(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region in ("cell", "tree"):
            item = self.tree.identify_row(event.y)
            if item:
                self.tree.selection_set(item)
    
    def _on_tree_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.current_selected_item = item
            self._show_popup_menu(event.x_root, event.y_root)
    
    def _on_tree_double_click(self, event):
        item = self.tree.focus()
        if item:
            self.on_launch_profile(item)
    
    def _show_popup_menu(self, x, y):
        if self.popup_menu:
            self.popup_menu.destroy()
        
        profile = next((p for p in self.profiles if p['fingerprint'] == self.current_selected_item), None)
        if not profile:
            return
        
        self.popup_menu = tk.Menu(
            self, tearoff=0, bg=self.colors["bg_input"], fg=self.colors["text"],
            activebackground=self.colors["bg_selected"], activeforeground=self.colors["text_header"],
            font=("Segoe UI", 10), bd=0, relief="flat"
        )
        self.popup_menu.add_command(label="Edit", command=lambda: self.on_edit_profile(self.current_selected_item))
        self.popup_menu.add_separator()
        self.popup_menu.add_command(label="Delete", foreground=self.colors["danger"],
                                    command=lambda: self.on_delete_profile(self.current_selected_item))
        
        try:
            self.popup_menu.tk_popup(x, y)
        finally:
            self.popup_menu.grab_release()
    
    def _on_search(self, event=None):
        self.refresh_profile_list()
    
    def _on_resize(self, event=None):
        if event.widget == self:
            width = event.width
            self.tree.column("name", width=int(width * 0.25))
            self.tree.column("proxy", width=int(width * 0.35))
    
    def on_add_profile(self):
        ModernProfileForm(self, self.profile_manager, mode="add", callback=self.refresh_profile_list)
    
    def on_edit_profile(self, profile_id=None):
        if not profile_id:
            profile_id = self.tree.focus()
        if not profile_id:
            messagebox.showwarning("Selection Error", "Please select a profile to edit.")
            return
        profile = next((p for p in self.profiles if p['fingerprint'] == profile_id), None)
        if profile:
            ModernProfileForm(self, self.profile_manager, mode="edit", profile=profile, callback=self.refresh_profile_list)
    
    def on_delete_profile(self, profile_id=None):
        if not profile_id:
            profile_id = self.tree.focus()
        if not profile_id:
            messagebox.showwarning("Selection Error", "Please select a profile to delete.")
            return
        profile = next((p for p in self.profiles if p['fingerprint'] == profile_id), None)
        if profile:
            confirm_dialog = ModernConfirmDialog(
                self, "Delete Profile",
                f"Are you sure you want to delete profile '{profile['name']}'?",
                self.colors
            )
            if confirm_dialog.result:
                self.profile_manager.delete_profile(profile["fingerprint"])
                self.refresh_profile_list()
    
    def on_toggle_status(self, profile_id=None):
        if not profile_id:
            profile_id = self.tree.focus()
        if not profile_id:
            return
        updated_profile = self.profile_manager.toggle_profile_status(profile_id)
        if updated_profile:
            self.refresh_profile_list()
    
    def on_launch_profile(self, profile_id=None):
        if not profile_id:
            profile_id = self.tree.focus()
        if not profile_id:
            messagebox.showwarning("Selection Error", "Please select a profile to launch.")
            return
        profile = next((p for p in self.profiles if p['fingerprint'] == profile_id), None)
        if profile:
            if not profile.get('active', False):
                self.profile_manager.toggle_profile_status(profile_id)
                self.refresh_profile_list()
            threading.Thread(
                target=launch_browser_for_profile,
                args=(profile, self, self.profile_manager),
                daemon=True
            ).start()

# ------------------------------
# Modern Profile Form
# ------------------------------
class ModernProfileForm(ctk.CTkToplevel):
    def __init__(self, master, profile_manager, mode="add", profile=None, callback=None):
        super().__init__(master)
        self.profile_manager = profile_manager
        self.mode = mode
        self.profile = profile
        self.callback = callback
        
        self.colors = master.colors
        
        # Keep the window's title, so it shows in the title bar:
        self.title("Add Profile" if mode == "add" else "Edit Profile")
        self.geometry("450x320")
        self.resizable(False, False)
        self.grab_set()
        
        x = master.winfo_x() + (master.winfo_width() // 2) - (450 // 2)
        y = master.winfo_y() + (master.winfo_height() // 2) - (320 // 2)
        self.geometry(f"+{x}+{y}")
        
        self.configure(fg_color=self.colors["bg_main"])
        
        self._create_widgets()
        if mode == "edit" and profile:
            self._populate_fields()
    
    def _create_widgets(self):
        main_frame = ctk.CTkFrame(self, fg_color=self.colors["bg_content"], corner_radius=8)
        main_frame.pack(fill="both", expand=True, padx=15, pady=15)
        
        # Remove the internal title label, so only the window’s title bar shows the text
        # header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        # header_frame.pack(fill="x", pady=(15, 25))
        
        # (No title_label creation here)
        
        form_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=15, pady=(15, 0))  # Moved top padding here
        
        name_label = ctk.CTkLabel(
            form_frame, text="Profile Name", 
            font=("Segoe UI", 12),
            text_color=self.colors["text"], 
            anchor="w"
        )
        name_label.pack(fill="x", pady=(0, 5))
        
        self.name_entry = ctk.CTkEntry(
            form_frame, height=40, 
            placeholder_text="Enter profile name",
            fg_color=self.colors["bg_input"],
            text_color=self.colors["text"],
            border_width=0,
            corner_radius=6
        )
        self.name_entry.pack(fill="x", pady=(0, 15))
        
        proxy_label = ctk.CTkLabel(
            form_frame, text="Proxy", 
            font=("Segoe UI", 12),
            text_color=self.colors["text"], 
            anchor="w"
        )
        proxy_label.pack(fill="x", pady=(0, 5))
        
        self.proxy_entry = ctk.CTkEntry(
            form_frame, height=40, 
            placeholder_text="IP:PORT:USERNAME:PASSWORD",
            fg_color=self.colors["bg_input"],
            text_color=self.colors["text"],
            border_width=0,
            corner_radius=6
        )
        self.proxy_entry.pack(fill="x")
        
        proxy_hint = ctk.CTkLabel(
            form_frame, text="Format: IP:PORT:USERNAME:PASSWORD", 
            font=("Segoe UI", 10), 
            text_color=self.colors["text_secondary"]
        )
        proxy_hint.pack(anchor="w", pady=(5, 0))
        
        buttons_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        buttons_frame.pack(fill="x", pady=(20, 0))
        
        cancel_btn = ctk.CTkButton(
            buttons_frame, text="Cancel", fg_color=self.colors["bg_header"],
            hover_color=self.colors["bg_selected"], corner_radius=6,
            font=("Segoe UI", 12), command=self.destroy
        )
        cancel_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))
        
        save_btn = ctk.CTkButton(
            buttons_frame, text="Save Changes", fg_color=self.colors["accent"],
            hover_color=self.colors["accent_hover"], corner_radius=6,
            font=("Segoe UI", 12, "bold"), command=self.on_save
        )
        save_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))
    
    def _populate_fields(self):
        if not self.profile:
            return
        self.name_entry.insert(0, self.profile["name"])
        proxy = self.profile["proxy"]
        proxy_str = f"{proxy['ip']}:{proxy['port']}:{proxy['username']}:{proxy['password']}"
        self.proxy_entry.insert(0, proxy_str)
    
    def on_save(self):
        name = self.name_entry.get().strip()
        proxy_str = self.proxy_entry.get().strip()
        if not name:
            messagebox.showerror("Input Error", "Profile name is required.")
            return
        if not proxy_str:
            messagebox.showerror("Input Error", "Proxy information is required.")
            return
        try:
            parts = proxy_str.split(":")
            if len(parts) >= 4:
                proxy_ip = parts[0]
                proxy_port = parts[1]
                proxy_user = parts[2]
                proxy_pass = ":".join(parts[3:])
            elif len(parts) == 2:
                proxy_ip = parts[0]
                proxy_port = parts[1]
                proxy_user = ""
                proxy_pass = ""
            else:
                raise ValueError("Invalid format")
        except Exception:
            messagebox.showerror(
                "Input Error",
                "Proxy input must be in the format IP:PORT:USERNAME:PASSWORD"
            )
            return
        
        if self.mode == "add":
            self.profile_manager.create_profile(name, proxy_ip, proxy_port, proxy_user, proxy_pass)
        else:
            self.profile_manager.edit_profile(
                self.profile["fingerprint"], name, proxy_ip, proxy_port, proxy_user, proxy_pass
            )
        
        if self.callback:
            self.callback()
        self.destroy()


# ------------------------------
# Main Entry Point
# ------------------------------
def main():
    persistence = PersistenceLayer("profiles.json")
    profile_manager = ProfileManager(persistence)
    
    # Optionally add default profiles if file is empty
    if not profile_manager.list_profiles():
        default_profiles = {
            "BrittGothier": "198.105.122.24:6597:11112222w:11112222w",
            "KateMate": "209.99.129.41:6029:11112222w:11112222w",
            "Pintowin": "45.192.152.23:5961:11112222w:11112222w",
        }
        for name, proxy_str in default_profiles.items():
            parts = proxy_str.split(":")
            proxy_ip, proxy_port, proxy_user, proxy_pass = parts
            profile_manager.create_profile(name, proxy_ip, proxy_port, proxy_user, proxy_pass)
    
    app = ModernDashboardApp(profile_manager, logo_path="Logo.png")
    app.mainloop()

if __name__ == "__main__":
    main()
