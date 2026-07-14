# Evidence-Based Playwright Patches

Generated from comparison: **fingerprint_real** vs **fingerprint_playwright**

Total patches: **5**

---

## Navigator: `navigator.webdriver`

**Priority**: ★★★★★

**Description**: Override navigator.webdriver to return false.

**Python (Playwright)**:
```python
# navigator.webdriver
page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>false})");
```

**JavaScript (init script)**:
```javascript
Object.defineProperty(navigator,'webdriver',{get:()=>false,configurable:true});
```

---

## Navigator: `navigator.deviceMemory`

**Priority**: ★★★★☆

**Description**: Set navigator.deviceMemory to 8.

**Python (Playwright)**:
```python
page.add_init_script("Object.defineProperty(navigator,'deviceMemory',{get:()=>8})");
```

**JavaScript (init script)**:
```javascript
Object.defineProperty(navigator,'deviceMemory',{get:()=>8,configurable:true});
```

---

## Window: `window.outerHeight`

**Priority**: ★★★★☆

**Description**: Set window.outerHeight to 798 (0 in headless).

**Python (Playwright)**:
```python
page.add_init_script("Object.defineProperty(window,'outerHeight',{get:()=>798})");
```

**JavaScript (init script)**:
```javascript
Object.defineProperty(window,'outerHeight',{get:()=>798,configurable:true});
```

---

## Window: `window.outerWidth`

**Priority**: ★★★★☆

**Description**: Set window.outerWidth to 1051 (0 in headless).

**Python (Playwright)**:
```python
page.add_init_script("Object.defineProperty(window,'outerWidth',{get:()=>1051})");
```

**JavaScript (init script)**:
```javascript
Object.defineProperty(window,'outerWidth',{get:()=>1051,configurable:true});
```

---

## Navigator: `navigator.languages`

**Priority**: ★★★☆☆

**Description**: Override navigator.languages to match real browser: ["en-US", "en", "id"].

**Python (Playwright)**:
```python
page.add_init_script("Object.defineProperty(navigator,'languages',{get:()=>["en-US", "en", "id"]})");
```

**JavaScript (init script)**:
```javascript
Object.defineProperty(navigator,'languages',{get:()=>["en-US", "en", "id"],configurable:true});
```

---

## Usage

```python
from patches import apply_patches

with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='chrome')
    page = browser.new_page()
    apply_patches(page)   # ← call before goto()
    page.goto('https://target.com')
```