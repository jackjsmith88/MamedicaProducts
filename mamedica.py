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

def filter_and_sort_products(rows: List[Dict], flower_only: bool = True, sort_by_price: bool = True) -> List[Dict]:
    """Filter and sort products based on criteria"""
    filtered_rows = rows
    
    # Filter for flower products only
    if flower_only:
        filtered_rows = [r for r in filtered_rows if 'flower' in r['product'].lower()]
    
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
        price_str = "" if r["price"] is None else f"£{r['price']:.2f}"
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
        title="🌿 Mamedica Flower Products (Lowest to Highest Price)",
        title_style="bold green",
        show_header=True,
        header_style="bold white on green",
        border_style="green",
        row_styles=["", "dim"],
        expand=True
    )
    
    table.add_column("Rank", style="bold cyan", justify="center", min_width=4)
    table.add_column("Product", style="cyan", no_wrap=False, min_width=50)
    table.add_column("Price", style="bold green", justify="right", min_width=8)
    table.add_column("THC%", style="yellow", justify="center", min_width=6)
    table.add_column("Size", style="blue", justify="center", min_width=6)
    
    count = 0
    for i, r in enumerate(rows, 1):
        if limit is not None and count >= limit:
            break
            
        # Format price
        if r["price"] is None:
            price_str = "N/A"
        else:
            price_str = f"£{r['price']:.2f}"
            
        # Extract THC percentage and size from product name
        product_name = r["product"]
        thc_match = re.search(r'(\d+)%\s*THC', product_name)
        thc_str = thc_match.group(1) + "%" if thc_match else "N/A"
        
        size_match = re.search(r'\((\d+g)\)', product_name)
        size_str = size_match.group(1) if size_match else "N/A"
        
        # Truncate very long product names for better display
        display_name = product_name
        if len(display_name) > 80:
            display_name = display_name[:77] + "..."
            
        table.add_row(str(i), display_name, price_str, thc_str, size_str)
        count += 1
    
    console.print()
    console.print(table)
    console.print(f"\n[bold green]Total flower products found:[/bold green] {len(rows)}")
    
    if limit and len(rows) > limit:
        console.print(f"[dim]Showing first {limit} items. Use --limit 0 or remove --limit to show all.[/dim]")

def show_gui_table(rows: List[Dict]):
    """Display products in a GUI table using tkinter"""
    if not TKINTER_AVAILABLE:
        print("Tkinter not available. GUI display not supported.")
        return
        
    # Create main window
    root = tk.Tk()
    root.title("🌿 Mamedica Flower Products - Price Comparison")
    root.geometry("1200x700")
    root.configure(bg='#f0f0f0')
    
    # Create main frame
    main_frame = ttk.Frame(root, padding="10")
    main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    
    # Configure grid weights
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    main_frame.columnconfigure(0, weight=1)
    main_frame.rowconfigure(1, weight=1)
    
    # Title label
    title_label = ttk.Label(
        main_frame, 
        text="🌿 Mamedica Flower Products (Sorted by Price: Lowest to Highest)",
        font=('Arial', 14, 'bold')
    )
    title_label.grid(row=0, column=0, pady=(0, 10), sticky=tk.W)
    
    # Create treeview with scrollbars
    tree_frame = ttk.Frame(main_frame)
    tree_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    tree_frame.columnconfigure(0, weight=1)
    tree_frame.rowconfigure(0, weight=1)
    
    # Define columns
    columns = ('rank', 'product', 'price', 'thc', 'cbd', 'size', 'brand')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25)
    
    # Define headings
    tree.heading('rank', text='#', anchor=tk.CENTER)
    tree.heading('product', text='Product Name', anchor=tk.W)
    tree.heading('price', text='Price (£)', anchor=tk.E)
    tree.heading('thc', text='THC%', anchor=tk.CENTER)
    tree.heading('cbd', text='CBD%', anchor=tk.CENTER)
    tree.heading('size', text='Size', anchor=tk.CENTER)
    tree.heading('brand', text='Brand', anchor=tk.W)
    
    # Configure column widths
    tree.column('rank', width=40, minwidth=40, anchor=tk.CENTER)
    tree.column('product', width=400, minwidth=300, anchor=tk.W)
    tree.column('price', width=80, minwidth=80, anchor=tk.E)
    tree.column('thc', width=60, minwidth=60, anchor=tk.CENTER)
    tree.column('cbd', width=60, minwidth=60, anchor=tk.CENTER)
    tree.column('size', width=60, minwidth=60, anchor=tk.CENTER)
    tree.column('brand', width=150, minwidth=100, anchor=tk.W)
    
    # Add scrollbars
    v_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    h_scrollbar = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
    
    # Grid the treeview and scrollbars
    tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
    v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
    h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
    
    # Populate the tree
    for i, product in enumerate(rows, 1):
        product_name = product['product']
        
        # Extract information from product name
        thc_match = re.search(r'(\d+)%\s*THC', product_name)
        thc_str = thc_match.group(1) + "%" if thc_match else "N/A"
        
        cbd_match = re.search(r'(\d+)%\s*CBD', product_name)
        cbd_str = cbd_match.group(1) + "%" if cbd_match else "<1%"
        
        size_match = re.search(r'\((\d+g)\)', product_name)
        size_str = size_match.group(1) if size_match else "N/A"
        
        # Extract brand (first word/words before THC percentage)
        brand_match = re.search(r'^([^0-9]+?)(?=\s+\d+%)', product_name)
        brand_str = brand_match.group(1).strip() if brand_match else "Unknown"
        
        price_str = f"{product['price']:.2f}" if product['price'] is not None else "N/A"
        
        # Insert row with alternating colors
        tag = 'evenrow' if i % 2 == 0 else 'oddrow'
        tree.insert('', tk.END, values=(
            i, product_name, price_str, thc_str, cbd_str, size_str, brand_str
        ), tags=(tag,))
    
    # Configure row colors
    tree.tag_configure('oddrow', background='#f9f9f9')
    tree.tag_configure('evenrow', background='#ffffff')
    
    # Add summary label
    summary_frame = ttk.Frame(main_frame)
    summary_frame.grid(row=2, column=0, pady=(10, 0), sticky=tk.W)
    
    total_products = len(rows)
    price_range = ""
    if rows and rows[0]['price'] is not None and rows[-1]['price'] is not None:
        lowest_price = rows[0]['price']
        highest_price = max(r['price'] for r in rows if r['price'] is not None)
        price_range = f" | Price range: £{lowest_price:.2f} - £{highest_price:.2f}"
    
    summary_label = ttk.Label(
        summary_frame,
        text=f"Total flower products: {total_products}{price_range}",
        font=('Arial', 10, 'bold')
    )
    summary_label.pack(side=tk.LEFT)
    
    # Add close button
    button_frame = ttk.Frame(main_frame)
    button_frame.grid(row=3, column=0, pady=(10, 0))
    
    close_button = ttk.Button(button_frame, text="Close", command=root.destroy)
    close_button.pack()
    
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
                print("⚠️  No flower products found. Try using --all-products to see all items.")
            else:
                print("⚠️  No products found. Possible reasons:")
                print("  - The form requires JavaScript to show conditional fields")
                print("  - Additional form validation is needed")
                print("  - The target select field names have changed")
            print("\n🔍 Trying to parse all Gravity Forms selects with --all-selects...")
            
            # Try with all selects as fallback
            fallback_rows = extract_products(html, all_gf_selects=True)
            if fallback_rows:
                rows = filter_and_sort_products(fallback_rows, flower_only=flower_only, sort_by_price=True)
                if rows:
                    print(f"✅ Found {len(rows)} products using --all-selects mode")
                else:
                    print("❌ No matching products found even with --all-selects.")
            else:
                print("❌ Still no products found. The form may require browser interaction.")
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Only proceed if we have data
    if not rows:
        print("\n❌ No data to display. Try running with --all-products or --all-selects flags.")
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
        print(f"📄 Wrote CSV: {args.csv}")
    if args.json:
        write_json(rows, args.json)
        print(f"📄 Wrote JSON: {args.json}")

if __name__ == "__main__":
    main()