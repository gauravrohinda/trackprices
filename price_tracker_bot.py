# ==============================================================================
# Price Tracker Bot
# A complete desktop application for tracking product prices across
# multiple e-commerce websites with user authentication and notifications.
# ==============================================================================

import requests
from bs4 import BeautifulSoup
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
import os
from concurrent.futures import ThreadPoolExecutor

# External dependencies for platform-specific notifications and MongoDB
from plyer import notification
from pymongo import MongoClient
from bson.objectid import ObjectId
import pymongo

# Configure logging to a file for debugging purposes
logging.basicConfig(filename='price_tracker.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# User agents for rotation to mimic different browsers
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.101 Safari/536.36',
    'Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko'
]

# Get MongoDB connection string. This is hardcoded to ensure it works
# in the packaged executable, as environment variables are unreliable.
MONGO_URI = "mongodb+srv://gjain0279_db_user:L12D3qn8rLwlnfxZ@database.dqluhni.mongodb.net/?retryWrites=true&w=majority&appName=Database"
DB_NAME = "price_tracker_db"
# Use a thread pool for concurrent scraping tasks to improve performance
THREAD_POOL = ThreadPoolExecutor(max_workers=5)


# ==============================================================================
# Database Functions (MongoDB)
# ==============================================================================

def get_db_client():
    """Establishes and returns a MongoDB client."""
    try:
        client = MongoClient(MONGO_URI)
        client.admin.command('ping')  # Test connection to ensure connectivity
        logging.info("Successfully connected to MongoDB.")
        return client[DB_NAME]
    except Exception as e:
        logging.error(f"Failed to connect to MongoDB: {e}")
        return None

def setup_db_indexes():
    """Sets up indexes on MongoDB collections for faster queries."""
    db = get_db_client()
    if db is not None:
        try:
            # Create a unique index for the username
            db.users.create_index([("username", pymongo.ASCENDING)], unique=True)
            # Create a compound index for user_id and url for fast product lookups
            db.products.create_index([("user_id", pymongo.ASCENDING), ("url", pymongo.ASCENDING)], unique=True)
            # Create a compound index for price history lookups
            db.price_history.create_index([("product_id", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)])
            logging.info("Database indexes created or verified.")
        except Exception as e:
            logging.error(f"Failed to set up database indexes: {e}")

def hash_password(password):
    """Hashes a password using SHA-256 for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(username, password):
    """Inserts a new user into the database."""
    db = get_db_client()
    if db is not None:
        users_collection = db.users
        hashed_password = hash_password(password)
        try:
            users_collection.insert_one({"username": username, "password": hashed_password})
            return True
        except pymongo.errors.DuplicateKeyError:
            logging.warning(f"Attempted to create duplicate user: {username}")
            return False
        except Exception as e:
            logging.error(f"Error creating user: {e}")
            return False
    return False

def authenticate_user(username, password):
    """Authenticates a user and returns their ID."""
    db = get_db_client()
    if db is not None:
        users_collection = db.users
        hashed_password = hash_password(password)
        user = users_collection.find_one({"username": username, "password": hashed_password}, {"_id": 1, "username": 1})
        if user:
            return str(user["_id"]), user["username"]
    return None, None

def add_product_to_db(user_id, url, name, low_price, high_price):
    """Adds a new product to the database."""
    db = get_db_client()
    if db is not None:
        products_collection = db.products
        try:
            # Check for a unique URL for the current user
            existing_product = products_collection.find_one({"user_id": user_id, "url": url})
            if existing_product:
                return None  # Product URL already exists for this user
            
            result = products_collection.insert_one({
                "user_id": user_id,
                "url": url,
                "name": name,
                "low_price": low_price,
                "high_price": high_price
            })
            return result.inserted_id
        except Exception as e:
            logging.error(f"Failed to add product: {e}")
    return None

def update_product_prices_in_db(product_id, low_price, high_price):
    """Updates the low and high price values for a product."""
    db = get_db_client()
    if db is not None:
        products_collection = db.products
        try:
            products_collection.update_one(
                {"_id": ObjectId(product_id)},
                {"$set": {"low_price": low_price, "high_price": high_price}}
            )
            return True
        except Exception as e:
            logging.error(f"Failed to update product prices: {e}")
    return False

def get_user_products(user_id):
    """Retrieves all products for a given user."""
    db = get_db_client()
    products = []
    if db is not None:
        products_collection = db.products
        price_history_collection = db.price_history
        for product in products_collection.find({"user_id": user_id}):
            # Find the latest price for each product
            latest_price_doc = price_history_collection.find_one(
                {"product_id": str(product["_id"])},
                sort=[("timestamp", -1)]
            )
            latest_price = latest_price_doc["price"] if latest_price_doc else "N/A"
            products.append({
                "id": str(product["_id"]),
                "name": product.get("name"),
                "url": product.get("url"),
                "low_price": product.get("low_price"),
                "high_price": product.get("high_price"),
                "latest_price": latest_price
            })
    return products

def add_price_history(product_id, price):
    """Adds a new price record to the history."""
    db = get_db_client()
    if db is not None:
        price_history_collection = db.price_history
        price_history_collection.insert_one({
            "product_id": product_id,
            "price": price,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

def get_product_history(product_id):
    """Retrieves the price history for a specific product."""
    db = get_db_client()
    history = []
    if db is not None:
        price_history_collection = db.price_history
        for record in price_history_collection.find({"product_id": product_id}).sort("timestamp", pymongo.DESCENDING):
            history.append((record["price"], record["timestamp"]))
    return history

def delete_product_from_db(product_id):
    """Deletes a product and its history from the database."""
    db = get_db_client()
    if db is not None:
        products_collection = db.products
        price_history_collection = db.price_history
        try:
            products_collection.delete_one({"_id": ObjectId(product_id)})
            price_history_collection.delete_many({"product_id": product_id})
            return True
        except Exception as e:
            logging.error(f"Failed to delete product: {e}")
    return False

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

def check_single_product(product):
    """Scrapes and updates a single product, used by the thread pool."""
    product_id = product["id"]
    url = product["url"]
    name = product["name"]
    low_price = product["low_price"]
    high_price = product["high_price"]
    last_price = product["latest_price"]

    current_name, current_price = scrape_product(url)
    if current_price is None:
        return

    # Check for price drops and increases
    if current_price <= low_price:
        send_notification("Price Drop Alert!", f"The price of {current_name} has dropped to ₹{current_price}!\nOriginal target was ₹{low_price}.")
    elif current_price >= high_price and high_price > 0:
        send_notification("Price Increase Alert!", f"The price of {current_name} has increased to ₹{current_price}!\nOriginal high price was ₹{high_price}.")
    elif last_price != "N/A" and current_price < float(last_price):
        send_notification("Price Drop!", f"The price of {current_name} has dropped to ₹{current_price}.")
    elif last_price != "N/A" and current_price > float(last_price):
        send_notification("Price Increase!", f"The price of {current_name} has increased to ₹{current_price}.")

    # Insert new price history
    add_price_history(product_id, current_price)

def check_prices(user_id):
    """
    Checks the prices of all products for a specific user concurrently.
    """
    products = get_user_products(user_id)
    if not products:
        return

    # Use a ThreadPoolExecutor to check prices concurrently
    THREAD_POOL.map(check_single_product, products)

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
        self.username = None
        
        self.password_visible = False
        
        self.show_login_page()
        
    def show_login_page(self):
        # Destroy all existing frames
        for frame in self.frames.values():
            frame.destroy()
        
        login_frame = tk.Frame(self, bg=self.colors["background"])
        login_frame.pack(fill="both", expand=True)
        self.frames['login'] = login_frame
        
        login_content = ttk.Frame(login_frame, style="TFrame", padding=40)
        login_content.place(relx=0.5, rely=0.5, anchor="center")
        
        tk.Label(login_content, text="Price Tracker Login", font=("Arial", 20, "bold"), bg=self.colors["surface"], fg=self.colors["text"]).pack(pady=(0, 20))
        
        ttk.Label(login_content, text="Username:", style="TLabel").pack(pady=5, anchor="w")
        self.login_entry = ttk.Entry(login_content, width=30, style="TEntry")
        self.login_entry.pack(pady=5)

        ttk.Label(login_content, text="Password:", style="TLabel").pack(pady=5, anchor="w")
        
        # Frame to hold password entry and show/hide button
        password_frame = tk.Frame(login_content, bg=self.colors["surface"])
        password_frame.pack(pady=5)
        
        self.password_entry = ttk.Entry(password_frame, width=25, show="*", style="TEntry")
        self.password_entry.pack(side="left")

        self.show_password_btn = ttk.Button(password_frame, text="👁️", width=3, command=self.toggle_password_visibility)
        self.show_password_btn.pack(side="left", padx=(5, 0))

        
        button_frame = tk.Frame(login_content, bg=self.colors["surface"])
        button_frame.pack(pady=20)
        
        ttk.Button(button_frame, text="Login", command=self.login, style="TButton").pack(side="left", padx=5)
        ttk.Button(button_frame, text="Sign Up", command=self.signup, style="TButton").pack(side="left", padx=5)
    
    def toggle_password_visibility(self):
        if self.password_visible:
            self.password_entry.config(show="*")
            self.show_password_btn.config(text="👁️")
            self.password_visible = False
        else:
            self.password_entry.config(show="")
            self.show_password_btn.config(text="🙈")
            self.password_visible = True
    
    def show_main_app(self):
        for frame in self.frames.values():
            frame.destroy()
        
        main_frame = tk.Frame(self, bg=self.colors["background"])
        main_frame.pack(fill="both", expand=True)
        self.frames['main'] = main_frame
        
        # Header
        header = tk.Frame(main_frame, bg=self.colors["primary"], height=80)
        header.pack(fill="x")
        
        # User and Logout Section
        user_frame = tk.Frame(header, bg=self.colors["primary"])
        user_frame.pack(side="right", padx=20)
        ttk.Label(user_frame, text=f"Welcome, {self.username}!", font=("Arial", 14), background=self.colors["primary"], foreground=self.colors["surface"]).pack(side="left", padx=10)
        ttk.Button(user_frame, text="Logout", command=self.logout, style="TButton").pack(side="left", padx=5)

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
        
        update_btn = ttk.Button(input_frame, text="Update Prices", command=self.update_prices)
        update_btn.pack(side="right", padx=(5,0))

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
        username = self.login_entry.get()
        password = self.password_entry.get()
        
        self.user_id, self.username = authenticate_user(username, password)
        
        if self.user_id:
            self.show_main_app()
        else:
            messagebox.showerror("Error", "Invalid login credentials.")
    
    def signup(self):
        username = self.login_entry.get()
        password = self.password_entry.get()

        if not username or not password:
            messagebox.showerror("Error", "Username and password cannot be empty.")
            return

        if create_user(username, password):
            messagebox.showinfo("Success", "Account created successfully! Please log in.")
        else:
            messagebox.showerror("Error", "Username already exists.")

    def logout(self):
        self.user_id = None
        self.username = None
        for frame in self.frames.values():
            frame.destroy()
        self.show_login_page()
        messagebox.showinfo("Logged Out", "You have been logged out successfully.")

    def start_scheduled_checks(self):
        # Start the initial check and then schedule
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

        product_id = add_product_to_db(self.user_id, url, name, low_price, high_price)
        if product_id:
            add_price_history(str(product_id), price)
            messagebox.showinfo("Success", f"Added {name[:30]}... to tracking list.")
        else:
            messagebox.showerror("Error", "This URL is already being tracked.")
            
        self.url_entry.delete(0, tk.END)
        self.low_price_entry.delete(0, tk.END)
        self.high_price_entry.delete(0, tk.END)
        self.load_products()

    def update_prices(self):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select a product to update.")
            return

        item = self.tree.item(selected_item[0])
        product_id = item['values'][0]

        low_price_str = self.low_price_entry.get().strip()
        high_price_str = self.high_price_entry.get().strip()

        if not low_price_str and not high_price_str:
            messagebox.showwarning("No Changes", "Please enter new low or high price values to update.")
            return
        
        try:
            low_price = float(low_price_str) if low_price_str else float(item['values'][3])
            high_price = float(high_price_str) if high_price_str else float(item['values'][4])
            
            if low_price <= 0:
                raise ValueError("Prices must be positive.")
        except ValueError:
            messagebox.showerror("Error", "Prices must be valid numbers.")
            return
        
        if update_product_prices_in_db(product_id, low_price, high_price):
            messagebox.showinfo("Success", "Product prices updated successfully!")
            self.load_products()
        else:
            messagebox.showerror("Error", "Failed to update prices.")
            
        self.low_price_entry.delete(0, tk.END)
        self.high_price_entry.delete(0, tk.END)

    def load_products(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        products = get_user_products(self.user_id)
        
        for product in products:
            name = product['name'][:30] + "..." if len(product['name']) > 30 else product['name']
            url = product['url'][:40] + "..." if len(product['url']) > 40 else product['url']
            
            latest_price = f"{product['latest_price']:.2f}" if isinstance(product['latest_price'], (int, float)) else "N/A"
            low_price = f"{product['low_price']:.2f}" if product['low_price'] else "N/A"
            high_price = f"{product['high_price']:.2f}" if product['high_price'] else "N/A"
            
            item_id = self.tree.insert("", "end", values=(product['id'], name, url, low_price, high_price, latest_price))
            
            ToolTip(self.tree, f"Name: {product['name']}\nURL: {product['url']}")

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
            if delete_product_from_db(product_id):
                self.load_products()
                messagebox.showinfo("Success", "Product removed.")
            else:
                messagebox.showerror("Error", "Failed to remove product.")

    def view_price_history(self, event=None):
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("No Selection", "Please select a product to view history.")
            return

        item = self.tree.item(selected_item[0])
        product_id = item['values'][0]
        product_name = item['values'][1]

        history = get_product_history(product_id)

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
    setup_db_indexes()
    app = App()
    app.mainloop()