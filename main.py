# ==============================================================================
# Price Tracker Bot
# A complete desktop application for tracking product prices across
# multiple e-commerce websites with user authentication and notifications.
# ==============================================================================

import requests
from bs4 import BeautifulSoup
import sqlite3
import schedule
import time
import logging
import tkinter as tk
from tkinter import ttk, messagebox
import re
from datetime import datetime
import threading
import hashlib
import random
from plyer import notification

# Configure logging to a file for debugging purposes
logging.basicConfig(filename='price_tracker.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# User agents for rotation to mimic different browsers
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.101 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko'
]

# ==============================================================================
# Database Functions
# ==============================================================================

def init_db():
    """Initializes and migrates the SQLite database for users and products."""
    conn = sqlite3.connect('price_tracker.db')
    c = conn.cursor()
    
    # Create users table for sign-up and login
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  phone TEXT UNIQUE,
                  password TEXT NOT NULL)''')

    # Create products table with a unique constraint on url
    c.execute('''CREATE TABLE IF NOT EXISTS products
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  url TEXT UNIQUE NOT NULL,
                  name TEXT,
                  low_price REAL,
                  high_price REAL,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    # Create price_history table to save all price changes
    c.execute('''CREATE TABLE IF NOT EXISTS price_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  product_id INTEGER,
                  price REAL,
                  timestamp TEXT,
                  FOREIGN KEY (product_id) REFERENCES products(id))''')
    
    conn.commit()
    conn.close()
    logging.info("Database initialized successfully.")

def hash_password(password):
    """Hashes a password using SHA-256 for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()

# ==============================================================================
# Scraping Functions
# ==============================================================================

def scrape_product(url):
    """
    Scrapes a product's name and price from supported e-commerce sites.
    
    Args:
        url (str): The URL of the product page.
        
    Returns:
        tuple: (product_name, current_price) or (None, None) if scraping fails.
    """
    try:
        headers = {'User-Agent': random.choice(USER_AGENTS)}
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')

        # Logic for different websites
        if "amazon.in" in url or "amazon.com" in url:
            name_elem = soup.select_one('#productTitle')
            price_elem = soup.select_one('.a-price-whole, #corePrice_feature_div .a-offscreen')
            if name_elem and price_elem:
                name = name_elem.get_text().strip()
                price_text = price_elem.get_text().replace(',', '').strip()
                price_match = re.search(r'\$?(\d+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1))
                    logging.info(f"Scraped from Amazon: {name} at ₹{price}")
                    return name, price

        elif "flipkart.com" in url:
            name_elem = soup.select_one('span.B_NuCI')
            price_elem = soup.select_one('div._30jeq3, div._16Jk6d ._30jeq3')
            if name_elem and price_elem:
                name = name_elem.get_text().strip()
                price_text = price_elem.get_text().replace(',', '').strip()
                price_match = re.search(r'\$?(\d+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1))
                    logging.info(f"Scraped from Flipkart: {name} at ₹{price}")
                    return name, price
                    
        elif "myntra.com" in url:
            name_elem = soup.select_one('.pdp-title')
            price_elem = soup.select_one('.pdp-price .pdp-price-amount')
            if name_elem and price_elem:
                name = name_elem.get_text().strip()
                price_text = price_elem.get_text().replace(',', '').strip()
                price_match = re.search(r'\$?(\d+\.?\d*)', price_text)
                if price_match:
                    price = float(price_match.group(1))
                    logging.info(f"Scraped from Myntra: {name} at ₹{price}")
                    return name, price

        logging.warning(f"Failed to find selectors for URL: {url}")
        return None, None
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error scraping {url}: {e}")
    except Exception as e:
        logging.error(f"Error scraping {url}: {e}")
    return None, None

# ==============================================================================
# Notification Functions
# ==============================================================================

def send_notification(title, message):
    """Sends a desktop notification to the user."""
    try:
        notification.notify(
            title=title,
            message=message,
            timeout=10
        )
        logging.info(f"Notification sent: {title} | {message}")
    except Exception as e:
        logging.error(f"Failed to send notification: {e}")

def check_prices(user_id):
    """
    Checks the prices of all products for a specific user and sends
    notifications based on low and high price triggers.
    """
    conn = sqlite3.connect('price_tracker.db')
    c = conn.cursor()
    c.execute("SELECT id, url, name, low_price, high_price FROM products WHERE user_id = ?", (user_id,))
    products = c.fetchall()

    for product_id, url, name, low_price, high_price in products:
        current_name, current_price = scrape_product(url)
        if current_price is None:
            continue

        # Get last price for comparison
        c.execute("SELECT price FROM price_history WHERE product_id = ? ORDER BY timestamp DESC LIMIT 1", (product_id,))
        last_price = c.fetchone()
        last_price = last_price[0] if last_price else None

        # Check for price drops and increases
        if current_price <= low_price:
            send_notification("Price Drop Alert!", f"The price of {current_name} has dropped to ₹{current_price}!\nOriginal target was ₹{low_price}.")
        elif current_price >= high_price and high_price > 0:
            send_notification("Price Increase Alert!", f"The price of {current_name} has increased to ₹{current_price}!\nOriginal high price was ₹{high_price}.")
        elif last_price is not None:
            if current_price < last_price:
                send_notification("Price Drop!", f"The price of {current_name} has dropped to ₹{current_price}.")
            elif current_price > last_price:
                send_notification("Price Increase!", f"The price of {current_name} has increased to ₹{current_price}.")

        # Insert new price history
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
                  (product_id, current_price, timestamp))

    conn.commit()
    conn.close()

# ==============================================================================
# GUI Classes
# ==============================================================================

class ToolTip:
    """A helper class to create tooltips for widgets."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.widget.bind("<Enter>", self.show_tip)
        self.widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x, y, _, _ = self.widget.bbox("insert") if isinstance(self.widget, tk.Entry) else self.widget.bbox("current")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                         background="#ffffe0", relief=tk.SOLID, borderwidth=1,
                         font=("Arial", 10))
        label.pack()

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Price Tracker Bot")
        self.geometry("1000x800")
        self.configure(bg="#f0f4f8")
        
        # Style Configuration
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Color palette
        self.colors = {
            "primary": "#007bff",
            "secondary": "#28a745",
            "background": "#f0f4f8",
            "surface": "#ffffff",
            "text": "#343a40",
            "muted_text": "#6c757d",
            "border": "#dee2e6",
            "accent": "#ffc107"
        }
        
        # Configure button styles
        self.style.configure("TButton", 
                             font=("Arial", 12, "bold"), 
                             padding=10, 
                             background=self.colors["primary"], 
                             foreground=self.colors["surface"],
                             borderwidth=0)
        self.style.map("TButton", background=[("active", self.colors["secondary"])])
        
        # Configure label styles
        self.style.configure("TLabel", 
                             background=self.colors["background"], 
                             font=("Arial", 12),
                             foreground=self.colors["text"])

        # Configure treeview styles
        self.style.configure("Treeview", 
                             rowheight=28, 
                             font=("Arial", 11),
                             background=self.colors["surface"],
                             foreground=self.colors["text"],
                             fieldbackground=self.colors["surface"])
        self.style.configure("Treeview.Heading", 
                             font=("Arial", 12, "bold"), 
                             background=self.colors["primary"], 
                             foreground=self.colors["surface"])
        
        # Configure entry styles
        self.style.configure("TEntry", 
                             fieldbackground=self.colors["surface"], 
                             foreground=self.colors["text"], 
                             font=("Arial", 12),
                             borderwidth=1,
                             bordercolor=self.colors["border"])
        
        self.style.configure("TFrame", background=self.colors["surface"], borderwidth=2, relief="groove")

        self.frames = {}
        self.user_id = None
        
        self.show_login_page()
        
    def show_login_page(self):
        login_frame = tk.Frame(self, bg=self.colors["background"])
        login_frame.pack(fill="both", expand=True)
        self.frames['login'] = login_frame
        
        login_content = ttk.Frame(login_frame, style="TFrame", padding=40)
        login_content.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(login_content, text="Price Tracker Login", font=("Arial", 20, "bold"), bg=self.colors["surface"], fg=self.colors["text"]).pack(pady=(0, 20))
        
        self.login_method_var = tk.StringVar(value="username")
        
        method_frame = tk.Frame(login_content, bg=self.colors["surface"])
        method_frame.pack(pady=5)
        
        self.username_radio = ttk.Radiobutton(method_frame, text="Use Username", variable=self.login_method_var, value="username", command=self.update_login_fields)
        self.username_radio.pack(side="left", padx=5)
        
        self.phone_radio = ttk.Radiobutton(method_frame, text="Use Phone Number", variable=self.login_method_var, value="phone", command=self.update_login_fields)
        self.phone_radio.pack(side="left", padx=5)
        
        self.login_label = ttk.Label(login_content, text="Username:", style="TLabel")
        self.login_label.pack(pady=5, anchor="w")
        self.login_entry = ttk.Entry(login_content, width=30, style="TEntry")
        self.login_entry.pack(pady=5)

        ttk.Label(login_content, text="Password:", style="TLabel").pack(pady=5, anchor="w")
        self.password_entry = ttk.Entry(login_content, width=30, show="*", style="TEntry")
        self.password_entry.pack(pady=5)
        
        button_frame = tk.Frame(login_content, bg=self.colors["surface"])
        button_frame.pack(pady=20)
        
        ttk.Button(button_frame, text="Login", command=self.login, style="TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="Sign Up", command=self.signup, style="TButton").pack(side="left", padx=5)

        self.update_login_fields()

    def update_login_fields(self):
        if self.login_method_var.get() == "username":
            self.login_label.config(text="Username:")
            self.login_entry.delete(0, tk.END)
        else:
            self.login_label.config(text="Phone Number:")
            self.login_entry.delete(0, tk.END)
    
    def show_main_app(self):
        for frame in self.frames.values():
            frame.destroy()
        
        main_frame = tk.Frame(self, bg=self.colors["background"])
        main_frame.pack(fill="both", expand=True)
        self.frames['main'] = main_frame
        
        # Main App Layout
        header = tk.Frame(main_frame, bg=self.colors["primary"], height=80)
        header.pack(fill="x")
        tk.Label(header, text="Price Tracker Bot", bg=self.colors["primary"], fg=self.colors["surface"], font=("Arial", 24, "bold")).pack(pady=10)

        input_frame = tk.Frame(main_frame, bg=self.colors["background"], padx=20, pady=10)
        input_frame.pack(fill="x")

        ttk.Label(input_frame, text="Product URL:").pack(side="left", padx=(0, 10))
        self.url_entry = ttk.Entry(input_frame, width=50)
        self.url_entry.pack(side="left", padx=(0, 20), expand=True, fill="x")
        ToolTip(self.url_entry, "Enter a product URL from Amazon, Flipkart, or Myntra")

        ttk.Label(input_frame, text="Low Price:").pack(side="left", padx=(0, 10))
        self.low_price_entry = ttk.Entry(input_frame, width=10)
        self.low_price_entry.pack(side="left", padx=(0, 5))
        ToolTip(self.low_price_entry, "Enter the low price for a notification")

        ttk.Label(input_frame, text="High Price:").pack(side="left", padx=(5, 10))
        self.high_price_entry = ttk.Entry(input_frame, width=10)
        self.high_price_entry.pack(side="left", padx=(0, 20))
        ToolTip(self.high_price_entry, "Enter the high price for a notification")

        add_btn = ttk.Button(input_frame, text="Add Product", command=self.add_product)
        add_btn.pack(side="right")

        # Product List
        self.tree = ttk.Treeview(main_frame, columns=("ID", "Name", "URL", "Low Price", "High Price", "Latest Price"), show="headings")
        self.tree.heading("ID", text="ID")
        self.tree.heading("Name", text="Product Name")
        self.tree.heading("URL", text="URL")
        self.tree.heading("Low Price", text="Low Price (₹)")
        self.tree.heading("High Price", text="High Price (₹)")
        self.tree.heading("Latest Price", text="Latest Price (₹)")

        self.tree.column("ID", width=0, stretch=tk.NO)
        self.tree.column("Name", width=200, anchor="w")
        self.tree.column("URL", width=300, anchor="w")
        self.tree.column("Low Price", width=120, anchor="center")
        self.tree.column("High Price", width=120, anchor="center")
        self.tree.column("Latest Price", width=120, anchor="center")
        
        self.tree.bind("<Double-1>", self.view_price_history)

        self.tree.pack(fill="both", expand=True, padx=20, pady=10)
        
        action_frame = tk.Frame(main_frame, bg=self.colors["background"])
        action_frame.pack(fill="x", pady=(0, 10), padx=20)
        ttk.Button(action_frame, text="Remove Selected", command=self.remove_selected).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Check Prices Now", command=self.check_prices_now).pack(side="left", padx=5)
        ttk.Button(action_frame, text="View Price History", command=self.view_price_history).pack(side="right", padx=5)

        self.status_var = tk.StringVar()
        self.status_var.set("Ready.")
        status_bar = tk.Label(main_frame, textvariable=self.status_var, bg=self.colors["border"], fg=self.colors["muted_text"], anchor="w", relief=tk.SUNKEN)
        status_bar.pack(side="bottom", fill="x")
        
        self.load_products()
        self.start_scheduled_checks()
        
    def login(self):
        password = self.password_entry.get()
        hashed_password = hash_password(password)
        
        conn = sqlite3.connect('price_tracker.db')
        c = conn.cursor()
        
        login_field = self.login_entry.get()

        if self.login_method_var.get() == "username":
            c.execute("SELECT id FROM users WHERE username = ? AND password = ?", (login_field, hashed_password))
        else: # phone login
            c.execute("SELECT id FROM users WHERE phone = ? AND password = ?", (login_field, hashed_password))

        user = c.fetchone()
        conn.close()
        
        if user:
            self.user_id = user[0]
            if self.login_method_var.get() == "phone":
                # Simulate OTP for phone login
                self.verify_otp()
            else:
                self.show_main_app()
        else:
            messagebox.showerror("Error", "Invalid login credentials.")
    
    def verify_otp(self):
        # Generate a random 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        print(f"Simulated OTP: {otp_code}")
        
        otp_window = tk.Toplevel(self)
        otp_window.title("OTP Verification")
        otp_window.geometry("300x150")
        otp_window.configure(bg=self.colors["surface"])
        otp_window.grab_set()

        ttk.Label(otp_window, text="Enter OTP:", style="TLabel", background=self.colors["surface"]).pack(pady=10)
        otp_entry = ttk.Entry(otp_window, width=20, style="TEntry")
        otp_entry.pack(pady=5)

        def check_otp():
            if otp_entry.get() == otp_code:
                messagebox.showinfo("Success", "OTP verified successfully!")
                otp_window.destroy()
                self.show_main_app()
            else:
                messagebox.showerror("Error", "Incorrect OTP. Please try again.")
        
        ttk.Button(otp_window, text="Verify", command=check_otp, style="TButton").pack(pady=10)

    def signup(self):
        username = self.login_entry.get() if self.login_method_var.get() == "username" else None
        phone = self.login_entry.get() if self.login_method_var.get() == "phone" else None
        password = self.password_entry.get()

        if not (username or phone) or not password:
            messagebox.showerror("Error", "Username/Phone and password cannot be empty.")
            return

        hashed_password = hash_password(password)
        
        conn = sqlite3.connect('price_tracker.db')
        c = conn.cursor()
        try:
            if username:
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            else:
                c.execute("INSERT INTO users (phone, password) VALUES (?, ?)", (phone, hashed_password))
            conn.commit()
            messagebox.showinfo("Success", "Account created successfully! Please log in.")
        except sqlite3.IntegrityError:
            messagebox.showerror("Error", "Username or phone number already exists.")
        finally:
            conn.close()

    def start_scheduled_checks(self):
        self.check_prices_now()
        schedule.every(12).hours.do(self.check_prices_now)
        
        def run_schedule():
            while True:
                schedule.run_pending()
                time.sleep(1)
        
        threading.Thread(target=run_schedule, daemon=True).start()

    def check_prices_now(self):
        self.status_var.set("Checking prices...")
        
        def run_in_thread():
            check_prices(self.user_id)
            self.load_products()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.status_var.set(f"Last checked: {timestamp} | Next check in 12 hours.")
        
        threading.Thread(target=run_in_thread).start()

    def add_product(self):
        url = self.url_entry.get().strip()
        low_price_str = self.low_price_entry.get().strip()
        high_price_str = self.high_price_entry.get().strip()
        
        if not url or not low_price_str:
            messagebox.showerror("Error", "Please enter a URL and at least a low price.")
            return

        try:
            low_price = float(low_price_str)
            high_price = float(high_price_str) if high_price_str else 0.0
            if low_price <= 0:
                 raise ValueError("Prices must be positive.")
        except ValueError:
            messagebox.showerror("Error", "Prices must be valid numbers.")
            return
            
        name, price = scrape_product(url)
        if not name:
            messagebox.showerror("Error", "Failed to scrape product details. Check the URL or try again.")
            return

        conn = sqlite3.connect('price_tracker.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO products (user_id, url, name, low_price, high_price) VALUES (?, ?, ?, ?, ?)",
                      (self.user_id, url, name, low_price, high_price))
            product_id = c.lastrowid
            c.execute("INSERT INTO price_history (product_id, price, timestamp) VALUES (?, ?, ?)",
                      (product_id, price, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            messagebox.showinfo("Success", f"Added {name[:30]}... to tracking list.")
        except sqlite3.IntegrityError:
            messagebox.showerror("Error", "This URL is already being tracked.")
        finally:
            conn.close()
            
        self.url_entry.delete(0, tk.END)
        self.low_price_entry.delete(0, tk.END)
        self.high_price_entry.delete(0, tk.END)
        self.load_products()

    def load_products(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        conn = sqlite3.connect('price_tracker.db')
        c = conn.cursor()
        c.execute("""
            SELECT p.id, p.name, p.url, p.low_price, p.high_price, ph.price
            FROM products p
            LEFT JOIN (
                SELECT product_id, price, MAX(timestamp)
                FROM price_history
                GROUP BY product_id
            ) ph ON p.id = ph.product_id
            WHERE p.user_id = ?
        """, (self.user_id,))
        
        for row in c.fetchall():
            name = row[1][:30] + "..." if len(row[1]) > 30 else row[1]
            url = row[2][:40] + "..." if len(row[2]) > 40 else row[2]
            
            latest_price = f"{row[5]:.2f}" if row[5] else "N/A"
            low_price = f"{row[3]:.2f}" if row[3] else "N/A"
            high_price = f"{row[4]:.2f}" if row[4] else "N/A"
            
            item_id = self.tree.insert("", "end", values=(row[0], name, url, low_price, high_price, latest_price))
            
            ToolTip(self.tree, f"Name: {row[1]}\nURL: {row[2]}")
        conn.close()

    def remove_selected(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select a product to remove.")
            return

        item = self.tree.item(selected_item[0])
        product_id = item['values'][0]
        name = item['values'][1]

        confirm = messagebox.askyesno("Confirm", f"Are you sure you want to remove {name}?")
        if confirm:
            conn = sqlite3.connect('price_tracker.db')
            c = conn.cursor()
            c.execute("DELETE FROM products WHERE id = ?", (product_id,))
            c.execute("DELETE FROM price_history WHERE product_id = ?", (product_id,))
            conn.commit()
            conn.close()
            self.load_products()
            messagebox.showinfo("Success", "Product removed.")

    def view_price_history(self, event=None):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select a product to view history.")
            return

        item = self.tree.item(selected_item[0])
        product_id = item['values'][0]
        product_name = item['values'][1]

        conn = sqlite3.connect('price_tracker.db')
        c = conn.cursor()
        c.execute("SELECT price, timestamp FROM price_history WHERE product_id = ? ORDER BY timestamp DESC", (product_id,))
        history = c.fetchall()
        conn.close()

        history_window = tk.Toplevel(self)
        history_window.title(f"Price History: {product_name}")
        history_window.geometry("500x400")
        history_window.configure(bg=self.colors["background"])

        history_tree = ttk.Treeview(history_window, columns=("Timestamp", "Price"), show="headings")
        history_tree.heading("Timestamp", text="Timestamp")
        history_tree.heading("Price", text="Price (₹)")
        history_tree.pack(fill="both", expand=True, padx=10, pady=10)

        for price, timestamp in history:
            history_tree.insert("", "end", values=(timestamp, f"{price:.2f}"))

if __name__ == "__main__":
    init_db()
    app = App()
    app.mainloop()
