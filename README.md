# 🌿 Mamedica Price Checker

A simple tool to check flower prices on the Mamedica website. Shows you the cheapest products first!

## 📋 What You Need

1. A computer (Windows, Mac, or Linux)
2. Internet connection
3. Python (we'll help you get this!)

## 🛠️ Step 1 Install Python

### Windows
1. Go to [python.org](httpspython.org)
2. Click the big yellow Download Python button
3. Run the downloaded file
4. IMPORTANT Check the box that says Add Python to PATH ✅
5. Click Install Now

### Mac
1. Go to [python.org](httpspython.org)
2. Download Python for Mac
3. Open the downloaded file and follow the instructions

### Already have Python
Open a terminalcommand prompt and type `python --version`
If you see something like Python 3.8 or higher, you're good! 🎉

## 📥 Step 2 Get the Code

1. Download the script Save the Python code as `mamedica.py` on your computer
2. Remember where you saved it (like your Desktop or Documents folder)

## 🏃‍♂️ Step 3 Run the Program

### Windows
1. Press `Windows key + R`
2. Type `cmd` and press Enter
3. Type `cd Desktop` (if you saved the file on your Desktop)
4. Type `python mamedica.py`

### MacLinux
1. Open Terminal (search for Terminal in your applications)
2. Type `cd Desktop` (if you saved the file on your Desktop)
3. Type `python mamedica.py`

## 🎯 What It Does

The program will
1. 📡 Connect to the Mamedica website
2. 🌿 Find all the flower products
3. 💰 Sort them by price (cheapest first)
4. 📊 Show you a nice table

## 🎮 Different Ways to Use It

### Basic Usage (Default)
```bash
python mamedica.py
```
Shows flower products only, sorted by price. Asks if you want a fancy table.

### Pop-up Window (Like a Game!)
```bash
python mamedica.py --gui
```
Opens a cool window with all the data - just like when you open a game! 🎮

### See ALL Products (Not Just Flowers)
```bash
python mamedica.py --gui --all-products
```
Shows everything they sell, not just flowers.

### Save to a File
```bash
python mamedica.py --csv my_prices.csv
```
Saves all the prices to a file you can open in Excel.

### Just the Top 10 Cheapest
```bash
python mamedica.py --limit 10
```
Only shows the 10 cheapest flowers.

## 🎨 Display Options

- Simple Table Basic text table in the terminal
- Rich Table Colorful table with emojis 🌈
- GUI Window Pop-up window like a real app! 🖥️

## 💡 Pro Tips

1. Internet Required Make sure you're connected to the internet
2. Be Patient It takes a few seconds to load all the data
3. Try Different Options Use `--gui` for the coolest experience!
4. Save Your Data Use `--csv filename.csv` to save prices for later

## 🔧 Installing Extra Features (Optional)

For colorful tables, type
```bash
pip install rich
```

## 🆘 Help! Something's Wrong!

### Python is not recognized
- Windows You forgot to check Add Python to PATH when installing
- Solution Reinstall Python and check that box ✅

### No products found
- Cause Website might be down or changed
- Try `python mamedica.py --all-selects --all-products`

### Permission denied
- Cause You don't have permission to run the file
- Solution Save the file somewhere you have permission (like Desktop)

### Still stuck
1. Make sure Python is installed `python --version`
2. Make sure you're in the right folder `dir` (Windows) or `ls` (MacLinux)
3. Make sure the file is called exactly `mamedica.py`

## 🎯 Examples

```bash
# Basic usage - flowers only, cheapest first
python mamedica.py

# Cool pop-up window
python mamedica.py --gui

# Save the 20 cheapest flowers to a file
python mamedica.py --limit 20 --csv cheapest_flowers.csv

# See everything in a pop-up window
python mamedica.py --gui --all-products
```

## 🏆 You Did It!

Once you see the prices, you're done! The program shows you
- 🏅 Rank #1 is the cheapest
- 🌿 Product Name What it's called
- 💰 Price How much it costs in £
- 🧪 THC% The strength
- 📦 Size Usually 10g

Have fun comparing prices! 🎉