#!/usr/bin/env python3
import argparse
import csv
import json
import re
import sys
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from typing import List, Optional, Dict, Tuple

try:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

DEFAULT_URL = "https://mamedica.co.uk/repeat-prescription/"

# Look for these specific selects by ID (from the HTML analysis)
TARGET_SELECT_NAMES = {"input_50", "input_71", "input_72", "input_73", "input_74", "input_79", "input_81", "input_82"}
TARGET_SELECT_IDS = {"input_3_50", "input_3_71", "input_3_72", "input_3_73", "input_3_74", "input_3_79", "input_3_81", "input_3_82"}

PRICE_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")

def fetch_html_with_form_data(url: str, timeout: int = 20) -> str:
    """
    Fetch HTML with form data to trigger the dynamic content.
    Based on the HTML analysis, we need to simulate checking the radio buttons.
    """
    try:
        # First, get the initial page to extract any hidden fields
        initial_html = fetch_html(url, timeout)
        
        # Extract any hidden fields from the initial HTML
        hidden_fields = extract_hidden_fields(initial_html)
        
        # Set up form data to simulate checking both "Yes" radio buttons
        # Based on the HTML: input_32 and input_85 are the key fields
        form_data = {
            'input_32': 'Yes',  # Do you need to increase/decrease dosage?
            'input_85': 'Yes',  # Have you been with MAMEDICA for over 12 months?
            'gform_submit': '3',  # Gravity Forms form ID
            'is_submit_3': '1',   # Form submission flag
        }
        
        # Add any discovered hidden fields
        form_data.update(hidden_fields)
        
        # Make POST request to trigger conditional logic
        data = urllib.parse.urlencode(form_data).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": url,
                "X-Requested-With": "XMLHttpRequest",  # Sometimes helps with dynamic content
            },
        )
        
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
            
    except Exception as e:
        print(f"Warning: POST request failed ({e}), trying GET request...", file=sys.stderr)
        # The form content appears to be in the initial HTML, just hidden
        return fetch_html(url, timeout)

def fetch_html(url: str, timeout: int = 20) -> str:
    """Original GET request method"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/127.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")

def extract_hidden_fields(html: str) -> Dict[str, str]:
    """Extract hidden form fields from HTML"""
    class HiddenFieldParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.hidden_fields = {}
            
        def handle_starttag(self, tag, attrs_list):
            attrs = dict(attrs_list)
            if (tag.lower() == "input" and 
                attrs.get("type", "").lower() == "hidden" and
                "name" in attrs and "value" in attrs):
                self.hidden_fields[attrs["name"]] = attrs["value"]
    
    parser = HiddenFieldParser()
    parser.feed(html)
    return parser.hidden_fields

class GFSelectParser(HTMLParser):
    def __init__(self, target_names: set, target_ids: set, all_gf_selects: bool = False):
        super().__init__(convert_charrefs=True)
        self.target_names = target_names
        self.target_ids = target_ids
        self.all_gf_selects = all_gf_selects

        self.in_target_select = False
        self.current_select_label = ""
        self.current_option_value: Optional[str] = None
        self.current_option_is_placeholder = False
        self.current_option_text_parts: List[str] = []

        self.results: List[Tuple[str, Optional[float], str, str]] = []

    @staticmethod
    def _has_class(attrs: Dict[str, str], cls: str) -> bool:
        classes = attrs.get("class", "")
        return any(c == cls for c in classes.split())

    def handle_starttag(self, tag, attrs_list):
        attrs = dict(attrs_list)
        if tag.lower() == "select":
            name = attrs.get("name", "")
            _id = attrs.get("id", "")
            classes = attrs.get("class", "")

            is_gf_select = "gfield_select" in classes.split()
            matches_target = (
                name in self.target_names or _id in self.target_ids
            )

            if self.all_gf_selects:
                self.in_target_select = is_gf_select
            else:
                self.in_target_select = matches_target and is_gf_select

            if self.in_target_select:
                # Keep a label for provenance in results
                self.current_select_label = f'name="{name}" id="{_id}" classes="{classes}"'

        elif self.in_target_select and tag.lower() == "option":
            self.current_option_value = (attrs.get("value") or "").strip()
            self.current_option_is_placeholder = "gf_placeholder" in (attrs.get("class", "")).split()
            self.current_option_text_parts = []

    def handle_data(self, data):
        if self.in_target_select and self.current_option_value is not None:
            self.current_option_text_parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "option" and self.in_target_select and self.current_option_value is not None:
            text = " ".join(part.strip() for part in self.current_option_text_parts).strip()
            raw_value = self.current_option_value

            # Skip placeholder/empty options
            if not self.current_option_is_placeholder and (raw_value or text):
                product = text or (raw_value.split("|", 1)[0].strip())
                price = self._parse_price(raw_value)
                if product:
                    self.results.append((product, price, raw_value, self.current_select_label))

            # Reset option accumulators
            self.current_option_value = None
            self.current_option_is_placeholder = False
            self.current_option_text_parts = []

        elif tag.lower() == "select":
            self.in_target_select = False
            self.current_select_label = ""

    @staticmethod
    def _parse_price(value: str) -> Optional[float]:
        if "|" in value:
            _, price_part = value.split("|", 1)
            m = PRICE_RE.search(price_part)
            if m:
                try:
                    return float(m.group(0))
                except ValueError:
                    return None
        # Fallback: scan entire value
        m = PRICE_RE.search(value)
        return float(m.group(0)) if m else None

def extract_products(html: str, all_gf_selects: bool = False) -> List[Dict]:
    parser = GFSelectParser(TARGET_SELECT_NAMES, TARGET_SELECT_IDS, all_gf_selects=all_gf_selects)
    parser.feed(html)

    # Dedupe by product label (first seen wins)
    dedup: Dict[str, Tuple[str, Optional[float], str, str]] = {}
    for product, price, raw, src in parser.results:
        if product not in dedup:
            dedup[product] = (product, price, raw, src)

    rows = []
    for product, price, raw, src in dedup.values():
        rows.append({
            "product": product,
            "price": price,
            "raw_value": raw,
            "source": src,
        })
    return rows

def extract_product_info(product_name: str) -> Dict[str, Optional[float]]:
    """Extract THC%, CBD%, and weight from product name"""
    # Extract THC percentage
    thc_match = re.search(r'(\d+(?:\.\d+)?)%\s*THC', product_name, re.IGNORECASE)
    thc_percent = float(thc_match.group(1)) if thc_match else None
    
    # Extract CBD percentage
    cbd_match = re.search(r'(\d+(?:\.\d+)?)%\s*CBD', product_name, re.IGNORECASE)
    cbd_percent = float(cbd_match.group(1)) if cbd_match else None
    
    # Extract weight (look for patterns like "10g", "(10g)", etc.)
    weight_match = re.search(r'\(?(\d+(?:\.\d+)?)\s*g\)?', product_name, re.IGNORECASE)
    weight_grams = float(weight_match.group(1)) if weight_match else None
    
    return {
        'thc_percent': thc_percent,
        'cbd_percent': cbd_percent,
        'weight_grams': weight_grams
    }

def calculate_efficiency_metrics(rows: List[Dict]) -> List[Dict]:
    """Add efficiency metrics to product data"""
    enhanced_rows = []
    
    for row in rows:
        enhanced_row = row.copy()
        product_info = extract_product_info(row['product'])
        
        # Add extracted info
        enhanced_row.update(product_info)
        
        # Calculate efficiency metrics
        price = row['price']
        thc_percent = product_info['thc_percent']
        weight_grams = product_info['weight_grams']
        
        # Â£/g calculation
        if price is not None and weight_grams is not None and weight_grams > 0:
            enhanced_row['price_per_gram'] = price / weight_grams
        else:
            enhanced_row['price_per_gram'] = None
            
        # Â£/mg THC calculation (more complex)
        if (price is not None and thc_percent is not None and 
            weight_grams is not None and thc_percent > 0 and weight_grams > 0):
            # Convert weight to mg and calculate THC content
            weight_mg = weight_grams * 1000
            thc_content_mg = weight_mg * (thc_percent / 100)
            enhanced_row['price_per_mg_thc'] = price / thc_content_mg
        else:
            enhanced_row['price_per_mg_thc'] = None
            
        enhanced_rows.append(enhanced_row)
    
    return enhanced_rows

def filter_and_sort_products(rows: List[Dict], flower_only: bool = True, sort_by_price: bool = True) -> List[Dict]:
    """Filter and sort products based on criteria"""
    filtered_rows = rows
    
    # Filter for flower products only
    if flower_only:
        filtered_rows = [r for r in filtered_rows if 'flower' in r['product'].lower()]
    
    # Add efficiency metrics
    filtered_rows = calculate_efficiency_metrics(filtered_rows)
    
    # Sort by price (lowest to highest), with items without prices at the end
    if sort_by_price:
        filtered_rows = sorted(filtered_rows, key=lambda x: (x['price'] is None, x['price'] or float('inf')))
    
    return filtered_rows

def print_table(rows: List[Dict], limit: Optional[int] = None):
    """Original simple table print function"""
    print("=" * 110)
    print(f"{'Product':<95} {'Price':>10}")
    print("-" * 110)
    count = 0
    for r in rows:
        if limit is not None and count >= limit:
            break
        price_str = "" if r["price"] is None else f"Â£{r['price']:.2f}"
        print(f"{r['product']:<95} {price_str:>10}")
        count += 1
    print("=" * 110)
    print(f"Total unique products: {len(rows)}")

def print_rich_table(rows: List[Dict], limit: Optional[int] = None):
    """Enhanced table display using rich library"""
    if not RICH_AVAILABLE:
        print("Rich library not available. Install with: pip install rich")
        print_table(rows, limit)
        return

    console = Console()
    
    # Create table
    table = Table(
        title="ðŸŒ¿ Mamedica Flower Products (Lowest to Highest Price)",
        title_style="bold green",
        show_header=True,
        header_style="bold white on green",
        border_style="green",
        row_styles=["", "dim"],
        expand=True
    )
    
    table.add_column("Rank", style="bold cyan", justify="center", min_width=4)
    table.add_column("Product", style="cyan", no_wrap=False, min_width=40)
    table.add_column("Price", style="bold green", justify="right", min_width=7)
    table.add_column("THC%", style="yellow", justify="center", min_width=5)
    table.add_column("Size", style="blue", justify="center", min_width=5)
    table.add_column("Â£/g", style="bold magenta", justify="right", min_width=6)
    table.add_column("Â£/mg THC", style="bold red", justify="right", min_width=8)
    
    count = 0
    for i, r in enumerate(rows, 1):
        if limit is not None and count >= limit:
            break
            
        # Format price
        price_str = f"Â£{r['price']:.2f}" if r['price'] is not None else "N/A"
            
        # Extract info from enhanced data
        thc_str = f"{r.get('thc_percent', 0):.0f}%" if r.get('thc_percent') else "N/A"
        
        size_match = re.search(r'\((\d+g)\)', r['product'])
        size_str = size_match.group(1) if size_match else "N/A"
        
        # Format efficiency metrics
        price_per_gram = r.get('price_per_gram')
        price_per_g_str = f"Â£{price_per_gram:.2f}" if price_per_gram is not None else "N/A"
        
        price_per_mg_thc = r.get('price_per_mg_thc')
        price_per_mg_thc_str = f"Â£{price_per_mg_thc:.4f}" if price_per_mg_thc is not None else "N/A"
        
        # Truncate very long product names for better display
        display_name = r['product']
        if len(display_name) > 60:
            display_name = display_name[:57] + "..."
            
        table.add_row(str(i), display_name, price_str, thc_str, size_str, 
                     price_per_g_str, price_per_mg_thc_str)
        count += 1
    
    console.print()
    console.print(table)
    console.print(f"\n[bold green]Total flower products found:[/bold green] {len(rows)}")
    
    if limit and len(rows) > limit:
        console.print(f"[dim]Showing first {limit} items. Use --limit 0 or remove --limit to show all.[/dim]")
    
    # Show efficiency leaders
    console.print("\n[bold yellow]ðŸ’° Best Value Analysis:[/bold yellow]")
    
    # Best Â£/g
    valid_per_gram = [r for r in rows if r.get('price_per_gram') is not None]
    if valid_per_gram:
        cheapest_per_gram = min(valid_per_gram, key=lambda x: x['price_per_gram'])
        console.print(f"[green]Cheapest per gram:[/green] {cheapest_per_gram['product'][:50]}... - Â£{cheapest_per_gram['price_per_gram']:.2f}/g")
    
    # Best Â£/mg THC
    valid_per_thc = [r for r in rows if r.get('price_per_mg_thc') is not None]
    if valid_per_thc:
        cheapest_per_thc = min(valid_per_thc, key=lambda x: x['price_per_mg_thc'])
        console.print(f"[green]Best THC value:[/green] {cheapest_per_thc['product'][:50]}... - Â£{cheapest_per_thc['price_per_mg_thc']:.4f}/mg THC")

def show_gui_table(rows: List[Dict]):
    """Display products in a GUI table using tkinter with filters and shopping cart"""
    if not TKINTER_AVAILABLE:
        print("Tkinter not available. GUI display not supported.")
        return
        
    # Create main window
    root = tk.Tk()
    root.title("Mamedica Flower Products - Price Comparison & Shopping Cart")
    root.geometry("1400x800")
    root.configure(bg='#f0f0f0')
    
    # Variables for filters
    price_min = tk.DoubleVar()
    price_max = tk.DoubleVar()
    price_per_g_min = tk.DoubleVar()
    price_per_g_max = tk.DoubleVar()
    thc_min = tk.DoubleVar()
    thc_max = tk.DoubleVar()
    
    # Shopping cart variables
    cart_items = {}  # product_name: quantity
    cart_var = tk.StringVar()
    cart_var.set("Cart: 0 items - £0.00")
    
    # Store filtered rows for easy access
    filtered_rows = rows.copy()
    
    # Calculate initial ranges for filters
    valid_prices = [r['price'] for r in rows if r['price'] is not None]
    valid_price_per_g = [r.get('price_per_gram') for r in rows if r.get('price_per_gram') is not None]
    valid_thc = [r.get('thc_percent') for r in rows if r.get('thc_percent') is not None]
    
    if valid_prices:
        price_min.set(min(valid_prices))
        price_max.set(max(valid_prices))
    if valid_price_per_g:
        price_per_g_min.set(min(valid_price_per_g))
        price_per_g_max.set(max(valid_price_per_g))
    if valid_thc:
        thc_min.set(min(valid_thc))
        thc_max.set(max(valid_thc))
    
    # Create main frame with paned window for resizable sections
    main_paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
    main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # Left panel for filters and cart
    left_panel = ttk.Frame(main_paned, padding="5")
    main_paned.add(left_panel, weight=1)
    
    # Right panel for product table
    right_panel = ttk.Frame(main_paned, padding="5")
    main_paned.add(right_panel, weight=3)
    
    # === LEFT PANEL: FILTERS AND CART ===
    
    # Filters section
    filters_frame = ttk.LabelFrame(left_panel, text="Filters", padding="10")
    filters_frame.pack(fill=tk.X, pady=(0, 10))
    
    def create_range_filter(parent, title, min_var, max_var, min_val, max_val, format_func=lambda x: f"{x:.2f}"):
        """Create a range filter with two sliders"""
        frame = ttk.LabelFrame(parent, text=title, padding="5")
        frame.pack(fill=tk.X, pady=5)
        
        # Min slider
        ttk.Label(frame, text="Min:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        min_label = ttk.Label(frame, text=format_func(min_val))
        min_label.grid(row=0, column=2, sticky=tk.E)
        min_scale = ttk.Scale(frame, from_=min_val, to=max_val, variable=min_var, orient=tk.HORIZONTAL)
        min_scale.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=5)
        frame.columnconfigure(1, weight=1)
        
        # Max slider
        ttk.Label(frame, text="Max:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
        max_label = ttk.Label(frame, text=format_func(max_val))
        max_label.grid(row=1, column=2, sticky=tk.E)
        max_scale = ttk.Scale(frame, from_=min_val, to=max_val, variable=max_var, orient=tk.HORIZONTAL)
        max_scale.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=5)
        
        # Update labels when sliders change
        def update_min_label(*args):
            min_label.config(text=format_func(min_var.get()))
        def update_max_label(*args):
            max_label.config(text=format_func(max_var.get()))
            
        min_var.trace('w', update_min_label)
        max_var.trace('w', update_max_label)
        min_var.trace('w', lambda *args: apply_filters())
        max_var.trace('w', lambda *args: apply_filters())
        
        return frame
    
    # Create filter controls
    if valid_prices:
        create_range_filter(filters_frame, "Price Range", price_min, price_max, 
                          min(valid_prices), max(valid_prices), lambda x: f"£{x:.2f}")
    
    if valid_price_per_g:
        create_range_filter(filters_frame, "Price per Gram", price_per_g_min, price_per_g_max,
                          min(valid_price_per_g), max(valid_price_per_g), lambda x: f"£{x:.2f}/g")
    
    if valid_thc:
        create_range_filter(filters_frame, "THC Content", thc_min, thc_max,
                          min(valid_thc), max(valid_thc), lambda x: f"{x:.1f}%")
    
    # Reset filters button
    def reset_filters():
        if valid_prices:
            price_min.set(min(valid_prices))
            price_max.set(max(valid_prices))
        if valid_price_per_g:
            price_per_g_min.set(min(valid_price_per_g))
            price_per_g_max.set(max(valid_price_per_g))
        if valid_thc:
            thc_min.set(min(valid_thc))
            thc_max.set(max(valid_thc))
        apply_filters()
    
    ttk.Button(filters_frame, text="Reset Filters", command=reset_filters).pack(pady=5)
    
    # Cart section
    cart_frame = ttk.LabelFrame(left_panel, text="Shopping Cart", padding="10")
    cart_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    
    # Cart summary
    cart_summary = ttk.Label(cart_frame, textvariable=cart_var, font=('Arial', 12, 'bold'))
    cart_summary.pack(pady=(0, 10))
    
    # Cart items listbox with scrollbar
    cart_list_frame = ttk.Frame(cart_frame)
    cart_list_frame.pack(fill=tk.BOTH, expand=True)
    
    cart_listbox = tk.Listbox(cart_list_frame, height=15)
    cart_scrollbar = ttk.Scrollbar(cart_list_frame, orient=tk.VERTICAL, command=cart_listbox.yview)
    cart_listbox.configure(yscrollcommand=cart_scrollbar.set)
    
    cart_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    cart_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    # Cart buttons
    cart_buttons_frame = ttk.Frame(cart_frame)
    cart_buttons_frame.pack(fill=tk.X, pady=(10, 0))
    
    def remove_from_cart():
        selection = cart_listbox.curselection()
        if selection:
            idx = selection[0]
            items = list(cart_items.keys())
            if idx < len(items):
                product_name = items[idx]
                del cart_items[product_name]
                update_cart_display()
                refresh_table()
    
    def clear_cart():
        cart_items.clear()
        update_cart_display()
        refresh_table()
    
    ttk.Button(cart_buttons_frame, text="Remove Selected", command=remove_from_cart).pack(side=tk.LEFT, padx=(0, 5))
    ttk.Button(cart_buttons_frame, text="Clear Cart", command=clear_cart).pack(side=tk.LEFT)
    
    # === RIGHT PANEL: PRODUCT TABLE ===
    
    # Title label
    title_label = ttk.Label(right_panel, text="Mamedica Flower Products", font=('Arial', 14, 'bold'))
    title_label.pack(pady=(0, 10))
    
    # Create treeview with scrollbars
    tree_frame = ttk.Frame(right_panel)
    tree_frame.pack(fill=tk.BOTH, expand=True)
    tree_frame.columnconfigure(0, weight=1)
    tree_frame.rowconfigure(0, weight=1)
    
    # Define columns
    columns = ('select', 'rank', 'product', 'price', 'thc', 'cbd', 'size', 'price_per_g', 'price_per_mg_thc', 'brand')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25)
    
    # Define headings
    tree.heading('select', text='Add', anchor=tk.CENTER)
    tree.heading('rank', text='#', anchor=tk.CENTER)
    tree.heading('product', text='Product Name', anchor=tk.W)
    tree.heading('price', text='Price (£)', anchor=tk.E)
    tree.heading('thc', text='THC%', anchor=tk.CENTER)
    tree.heading('cbd', text='CBD%', anchor=tk.CENTER)
    tree.heading('size', text='Size', anchor=tk.CENTER)
    tree.heading('price_per_g', text='£/g', anchor=tk.E)
    tree.heading('price_per_mg_thc', text='£/mg THC', anchor=tk.E)
    tree.heading('brand', text='Brand', anchor=tk.W)
    
    # Configure column widths - optimized for better product name display
    tree.column('select', width=40, minwidth=40, anchor=tk.CENTER)
    tree.column('rank', width=30, minwidth=30, anchor=tk.CENTER)
    tree.column('product', width=320, minwidth=250, anchor=tk.W)  # Increased from 250 to 320
    tree.column('price', width=60, minwidth=60, anchor=tk.E)     # Decreased from 70 to 60
    tree.column('thc', width=45, minwidth=40, anchor=tk.CENTER) # Decreased from 50 to 45
    tree.column('cbd', width=45, minwidth=40, anchor=tk.CENTER) # Decreased from 50 to 45
    tree.column('size', width=40, minwidth=40, anchor=tk.CENTER)# Decreased from 50 to 40
    tree.column('price_per_g', width=55, minwidth=50, anchor=tk.E) # Decreased from 60 to 55
    tree.column('price_per_mg_thc', width=70, minwidth=65, anchor=tk.E) # Decreased from 80 to 70
    tree.column('brand', width=90, minwidth=70, anchor=tk.W)     # Decreased from 100 to 90
    
    # Add scrollbars
    v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
    
    # Grid the treeview and scrollbars
    tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
    
    # Handle tree clicks for adding to cart
    def on_tree_click(event):
        region = tree.identify_region(event.x, event.y)
        if region == "cell":
            column = tree.identify_column(event.x)
            if column == '#1':  # Select column
                item = tree.identify_row(event.y)
                if item:
                    values = tree.item(item, 'values')
                    if values and len(values) > 2:  # Make sure we have product data
                        product_name = values[2]  # Product name is in column 2
                        add_to_cart(product_name)
    
    tree.bind("<Button-1>", on_tree_click)
    
    def add_to_cart(product_name):
        """Add a product to the cart or increment quantity"""
        if product_name in cart_items:
            cart_items[product_name] += 1
        else:
            cart_items[product_name] = 1
        update_cart_display()
        refresh_table()
    
    def update_cart_display():
        """Update the cart listbox and summary"""
        cart_listbox.delete(0, tk.END)
        total_cost = 0
        total_items = 0
        
        for product_name, quantity in cart_items.items():
            # Find the product in our data to get the price
            product_data = next((r for r in rows if r['product'] == product_name), None)
            if product_data and product_data['price'] is not None:
                item_cost = product_data['price'] * quantity
                total_cost += item_cost
                total_items += quantity
                
                # Truncate long product names for display
                display_name = product_name[:40] + "..." if len(product_name) > 40 else product_name
                cart_listbox.insert(tk.END, f"{quantity}x {display_name} - £{item_cost:.2f}")
            else:
                total_items += quantity
                display_name = product_name[:40] + "..." if len(product_name) > 40 else product_name
                cart_listbox.insert(tk.END, f"{quantity}x {display_name} - Price N/A")
        
        cart_var.set(f"Cart: {total_items} items - £{total_cost:.2f}")
    
    def apply_filters():
        """Apply current filter settings to the product list"""
        nonlocal filtered_rows
        filtered_rows = []
        
        for product in rows:
            # Price filter
            if valid_prices and product['price'] is not None:
                if not (price_min.get() <= product['price'] <= price_max.get()):
                    continue
            
            # Price per gram filter
            if valid_price_per_g and product.get('price_per_gram') is not None:
                if not (price_per_g_min.get() <= product['price_per_gram'] <= price_per_g_max.get()):
                    continue
            
            # THC filter
            if valid_thc and product.get('thc_percent') is not None:
                if not (thc_min.get() <= product['thc_percent'] <= thc_max.get()):
                    continue
            
            filtered_rows.append(product)
        
        refresh_table()
    
    def refresh_table():
        """Refresh the table with filtered data"""
        # Clear existing items
        for item in tree.get_children():
            tree.delete(item)
        
        # Populate with filtered data
        for i, product in enumerate(filtered_rows, 1):
            product_name = product['product']
            
            # Clean up product name for display
            display_product_name = product_name
            # Remove "less than" (any case)
            display_product_name = re.sub(r'\bless\s+than\b', '', display_product_name, flags=re.IGNORECASE)
            # Remove "Flower" from "CBD Flower" (any case)
            display_product_name = re.sub(r'\bCBD\s+Flower\b', 'CBD', display_product_name, flags=re.IGNORECASE)
            # Clean up extra spaces
            display_product_name = re.sub(r'\s+', ' ', display_product_name).strip()
            
            # Check if item is in cart
            in_cart = product_name in cart_items
            cart_indicator = "Y" if in_cart else "+"
            
            # Get pre-calculated values
            thc_percent = product.get('thc_percent')
            cbd_percent = product.get('cbd_percent')
            weight_grams = product.get('weight_grams')
            price_per_gram = product.get('price_per_gram')
            price_per_mg_thc = product.get('price_per_mg_thc')
            
            # Format values
            thc_str = f"{thc_percent:.1f}%" if thc_percent is not None else "N/A"
            cbd_str = f"{cbd_percent:.1f}%" if cbd_percent is not None else "<1%"
            size_str = f"{weight_grams:.0f}g" if weight_grams is not None else "N/A"
            
            # Extract brand (first word/words before THC percentage)
            brand_match = re.search(r'^([^0-9]+?)(?=\s+\d+%)', product_name)
            brand_str = brand_match.group(1).strip() if brand_match else "Unknown"
            
            price_str = f"{product['price']:.2f}" if product['price'] is not None else "N/A"
            price_per_g_str = f"{price_per_gram:.2f}" if price_per_gram is not None else "N/A"
            price_per_mg_thc_str = f"{price_per_mg_thc:.4f}" if price_per_mg_thc is not None else "N/A"
            
            # Insert row with alternating colors
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            if in_cart:
                tag = 'in_cart'
            
            tree.insert('', tk.END, values=(
                cart_indicator, i, display_product_name, price_str, thc_str, cbd_str, size_str,
                price_per_g_str, price_per_mg_thc_str, brand_str
            ), tags=(tag,))
        
        # Update title with count
        filtered_count = len(filtered_rows)
        total_count = len(rows)
        title_label.config(text=f"Mamedica Flower Products (Showing {filtered_count} of {total_count})")
    
    # Configure row colors
    tree.tag_configure('oddrow', background='#f9f9f9')
    tree.tag_configure('evenrow', background='#ffffff')
    tree.tag_configure('in_cart', background='#e8f5e8', foreground='#2d5a2d')
    
    # Initial table population
    apply_filters()
    
    # Add summary label at bottom
    summary_frame = ttk.Frame(right_panel)
    summary_frame.pack(fill=tk.X, pady=(10, 0))
    
    instructions_label = ttk.Label(
        summary_frame,
        text="Click the '+' or 'Y' in the first column to add items to your cart",
        font=('Arial', 9, 'italic')
    )
    instructions_label.pack(anchor=tk.W)
    
    # Center the window
    root.update_idletasks()
    x = (root.winfo_screenwidth() // 2) - (root.winfo_width() // 2)
    y = (root.winfo_screenheight() // 2) - (root.winfo_height() // 2)
    root.geometry(f"+{x}+{y}")
    
    # Start the GUI
    root.mainloop()
    
def ask_for_display_preference():
    """Ask user if they want to display a nice rendered table"""
    if not RICH_AVAILABLE:
        return False
        
    while True:
        try:
            choice = input("\nWould you like to display the results in a nice rendered table? (y/n): ").strip().lower()
            if choice in ['y', 'yes']:
                return True
            elif choice in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no.")
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)
        except EOFError:
            return False

def write_csv(rows: List[Dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product", "price", "raw_value", "source"])
        for r in rows:
            w.writerow([r["product"], "" if r["price"] is None else r["price"], r["raw_value"], r["source"]])

def write_json(rows: List[Dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Extract product options (name + price) from Gravity Forms selects.")
    ap.add_argument("--url", default=DEFAULT_URL, help="Page URL to fetch (default: Mamedica repeat prescription page)")
    ap.add_argument("--csv", help="Write results to CSV file")
    ap.add_argument("--json", help="Write results to JSON file")
    ap.add_argument("--limit", type=int, help="Limit rows printed to console")
    ap.add_argument("--all-selects", action="store_true",
                    help="Parse all Gravity Forms selects (class=gfield_select) instead of only the known fields")
    ap.add_argument("--rich-table", action="store_true",
                    help="Force display rich table without prompting")
    ap.add_argument("--simple-table", action="store_true",
                    help="Force display simple table without prompting")
    ap.add_argument("--gui", action="store_true",
                    help="Display results in a GUI table window")
    ap.add_argument("--flowers-only", action="store_true", default=True,
                    help="Filter to show only flower products (default: True)")
    ap.add_argument("--all-products", action="store_true",
                    help="Show all products, not just flowers")
    args = ap.parse_args(argv)

    try:
        print("Fetching data from Mamedica...")
        # Try the enhanced method first, fallback to simple GET
        html = fetch_html_with_form_data(args.url)
        
        # If we get the content but products aren't visible, try the original method
        initial_rows = extract_products(html, all_gf_selects=args.all_selects)
        if not initial_rows:
            print("No products found with form submission, trying direct fetch...")
            html = fetch_html(args.url)
            
        print("Parsing product information...")
        rows = extract_products(html, all_gf_selects=args.all_selects)
        
        # Apply filtering and sorting
        flower_only = args.flowers_only and not args.all_products
        rows = filter_and_sort_products(rows, flower_only=flower_only, sort_by_price=True)
        
        if not rows:
            if flower_only:
                print("âš ï¸  No flower products found. Try using --all-products to see all items.")
            else:
                print("âš ï¸  No products found. Possible reasons:")
                print("  - The form requires JavaScript to show conditional fields")
                print("  - Additional form validation is needed")
                print("  - The target select field names have changed")
            print("\nðŸ” Trying to parse all Gravity Forms selects with --all-selects...")
            
            # Try with all selects as fallback
            fallback_rows = extract_products(html, all_gf_selects=True)
            if fallback_rows:
                rows = filter_and_sort_products(fallback_rows, flower_only=flower_only, sort_by_price=True)
                if rows:
                    print(f"âœ… Found {len(rows)} products using --all-selects mode")
                else:
                    print("âŒ No matching products found even with --all-selects.")
            else:
                print("âŒ Still no products found. The form may require browser interaction.")
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Only proceed if we have data
    if not rows:
        print("\nâŒ No data to display. Try running with --all-products or --all-selects flags.")
        sys.exit(1)

    # Determine display method
    if args.gui:
        show_gui_table(rows)
    elif args.rich_table:
        print_rich_table(rows, args.limit)
    elif args.simple_table:
        print_table(rows, args.limit)
    else:
        # Ask user for preference
        if ask_for_display_preference():
            print_rich_table(rows, args.limit)
        else:
            print_table(rows, args.limit)
    
    # Export files
    if args.csv:
        write_csv(rows, args.csv)
        print(f"ðŸ“„ Wrote CSV: {args.csv}")
    if args.json:
        write_json(rows, args.json)
        print(f"ðŸ“„ Wrote JSON: {args.json}")

if __name__ == "__main__":
    main()

    main()
