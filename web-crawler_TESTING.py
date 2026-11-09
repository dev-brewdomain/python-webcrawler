import gc
import logging
import os
import random
import time
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
import requests
from playwright.sync_api import sync_playwright

# Configure Logging to write to both console and a log file
log_filename = "crawler_execution.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Chromium arguments optimized for low memory usage and anti-bot evasion
CHROMIUM_ARGS = [
    "--headless=new",
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-translate",
    "--disable-default-apps",
    "--no-first-run",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--js-flags=--max-old-space-size=256",
    "--window-size=1280,800"
]

def get_urls_from_sitemap(sitemap_url: str):
    """Fetches all URLs from a WordPress XML sitemap recursively."""
    logging.info(f"Fetching sitemap: {sitemap_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"[-] Failed to fetch sitemap: {e}")
        return []

    urls = []
    root = ET.fromstring(response.content)
    tag_name = root.tag
    ns = tag_name[tag_name.find('{'):tag_name.find('}')+1] if '}' in tag_name else ''
    
    sitemaps = root.findall(f".//{ns}sitemap/{ns}loc")
    if sitemaps:
        for sm in sitemaps:
            sub_url = sm.text.strip()
            if "post" in sub_url or "recipe" in sub_url or "sitemap" in sub_url:
                urls.extend(get_urls_from_sitemap(sub_url))
    else:
        locs = root.findall(f".//{ns}url/{ns}loc")
        for loc in locs:
            if loc.text:
                urls.append(loc.text.strip())
                
    return list(set(urls))

def open_interactive_browser_for_challenge(p, url, state_file, context_args):
    """Launches a visible browser window for manual Cloudflare/PerimeterX challenge resolution."""
    logging.info("\n" + "="*60)
    logging.info("INTERVENTION REQUIRED: Opening visible browser window for manual solving...")
    logging.info("="*60 + "\n")
    
    visible_args = [arg for arg in CHROMIUM_ARGS if arg != "--headless=new"]
    interactive_browser = p.chromium.launch(
        headless=False,
        args=visible_args
    )
    
    if os.path.exists(state_file):
        context_args["storage_state"] = state_file
    else:
        context_args.pop("storage_state", None)
        
    interactive_context = interactive_browser.new_context(**context_args)
    interactive_page = interactive_context.new_page()
    
    try:
        interactive_page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception:
        pass
        
    logging.info("\nPlease solve the verification / security check (Cloudflare / PerimeterX) in the open browser window.")
    input("Press ENTER here after you have successfully passed the challenge...")
    
    try:
        interactive_context.storage_state(path=state_file)
        logging.info(f"-> Updated session state saved to {state_file}.")
    except Exception as e:
        logging.error(f"[-] Error saving storage state: {e}")
        
    try:
        interactive_browser.close()
    except Exception:
        pass

def handle_security_challenge(page, browser, context, p, url, state_file, context_args):
    """Detects and handles Cloudflare and PerimeterX security challenges safely, closing old resources."""
    try:
        if page.is_closed():
            return None, None, None
            
        title = page.title()
        content = page.content()
        
        is_challenged = (
            "Attention Required! | Cloudflare" in title or 
            "Checking your browser" in content or 
            "Just a moment..." in content or
            "Verify you are human" in content or
            "Performing security verification" in content or
            "Managed Challenge" in content or
            "Access Denied" in content or
            "Robot or human?" in content or
            "px-captcha" in content or
            "perimeterx" in content or
            "captcha.px-cdn.net" in content or
            ("Cloudflare" in title and ("Verify" in content or "Security" in content))
        )
        
        if is_challenged:
            logging.warning("\n" + "!"*60)
            logging.warning("[!] Security challenge / Cloudflare / PerimeterX block screen detected!")
            logging.warning("[!] Attempting automated resolution...")
            logging.warning("!"*60 + "\n")
            
            time.sleep(3)
            
            try:
                for frame in page.frames:
                    if any(domain in frame.url for domain in ["challenges.cloudflare.com", "cdn-cgi/challenge-platform", "px-cdn.net", "captcha"]):
                        checkbox = frame.locator("input[type='checkbox'], label, span, div[role='checkbox']").first
                        if checkbox.is_visible(timeout=3000):
                            box = checkbox.bounding_box()
                            if box:
                                page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                            checkbox.click()
                            logging.info("[+] Clicked verification target inside challenge frame.")
                            break
            except Exception:
                pass

            try:
                page.wait_for_function(
                    "() => !document.title.includes('Attention Required') && "
                    "!document.body.innerText.includes('Checking your browser') && "
                    "!document.body.innerText.includes('Just a moment...') && "
                    "!document.body.innerText.includes('Verify you are human') && "
                    "!document.body.innerText.includes('Access Denied') && "
                    "!document.body.innerText.includes('Robot or human?') && "
                    "!document.body.innerText.includes('Performing security verification')",
                    timeout=25000
                )
                logging.info("[+] Security challenge cleared successfully!")
                time.sleep(2)
                return None, None, None
            except Exception:
                pass

            logging.warning("\n[-] Automated resolution timed out. Launching interactive browser...")
            
            try:
                page.close()
                context.close()
                browser.close()
            except Exception:
                pass
                
            open_interactive_browser_for_challenge(p, url, state_file, context_args)
            
            logging.info("[*] Resuming headless crawling with updated session...")
            new_browser = p.chromium.launch(
                headless=True, 
                args=CHROMIUM_ARGS
            )
            
            if os.path.exists(state_file):
                context_args["storage_state"] = state_file
            else:
                context_args.pop("storage_state", None)

            new_context = new_browser.new_context(**context_args)
            new_context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
            new_page = new_context.new_page()
            new_page.goto(url, wait_until="domcontentloaded", timeout=60000)
            
            return new_page, new_context, new_browser
            
    except Exception as e:
        logging.error(f"[-] Error checking security challenge: {e}")
    return None, None, None

def simulate_human_behavior(page):
    """Simulates realistic human mouse movements and scrolling."""
    try:
        if not page.is_closed():
            page.mouse.move(random.randint(200, 700), random.randint(200, 500), steps=5)
            page.mouse.down()
            page.mouse.up()
    except Exception:
        pass

def download_site_with_anti_adblock(start_url: str, output_dir: str = "site_pages_pdf"):
    """Crawls a site using sitemaps with strict resource cleanup to prevent host starvation."""
    os.makedirs(output_dir, exist_ok=True)
    state_file = "auth_state.json"
    
    parsed = urlparse(start_url)
    base_sitemap = f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml"
    
    all_urls = get_urls_from_sitemap(base_sitemap)
    if not all_urls:
        all_urls = get_urls_from_sitemap(f"{parsed.scheme}://{parsed.netloc}/sitemap.xml")
        
    logging.info(f"\nFound {len(all_urls)} total URLs in sitemap.\n")
    
    if not all_urls:
        logging.error("[-] No URLs found via sitemaps. Please check the target URL.")
        return

    with sync_playwright() as p:
        needs_verification = not os.path.exists(state_file)
        
        visible_args = [arg for arg in CHROMIUM_ARGS if arg != "--headless=new"]
        browser = p.chromium.launch(
            headless=False if needs_verification else True,
            args=visible_args if needs_verification else CHROMIUM_ARGS
        )
        
        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
            "device_scale_factor": 1,
            "has_touch": False,
            "is_mobile": False
        }
        
        if os.path.exists(state_file):
            context_args["storage_state"] = state_file
            
        context = browser.new_context(**context_args)
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
        
        # Comprehensive Evasions
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });

            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            try {
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) {
                        return 'Intel Inc.';
                    }
                    if (parameter === 37446) {
                        return 'Intel Iris OpenGL Engine';
                    }
                    return getParameter(parameter);
                };
            } catch (e) {}

            if (navigator.permissions && navigator.permissions.query) {
                const originalQuery = navigator.permissions.query;
                navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            }
        """)

        context.add_init_script("""
            window.canRunAds = true;
            window.adsLoaded = true;
            window.mediavineLoaded = true;
        """)
        
        if needs_verification:
            logging.info("\n" + "="*60)
            logging.info("ACTION REQUIRED: A browser window has opened.")
            logging.info("Please solve any initial Cloudflare / security checks.")
            logging.info("Once you can see the normal website content, press ENTER here.")
            logging.info("="*60 + "\n")
            
            init_page = context.new_page()
            init_page.goto(start_url, wait_until="domcontentloaded")
            input("Press ENTER after you have successfully passed the verification...")
            
            context.storage_state(path=state_file)
            logging.info(f"-> Session state saved to {state_file}.")
            init_page.close()
            
            browser.close()
            browser = p.chromium.launch(
                headless=True, 
                args=CHROMIUM_ARGS
            )
            
            if os.path.exists(state_file):
                context_args["storage_state"] = state_file
            else:
                context_args.pop("storage_state", None)

            context = browser.new_context(**context_args)
            context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

        for index, url in enumerate(all_urls, 1):
            page = None
            try:
                # Periodic full memory flush every 50 pages
                if index > 1 and index % 50 == 0:
                    logging.info("[*] Periodic browser memory flush: restarting browser instance...")
                    try:
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                    
                    browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                    if os.path.exists(state_file):
                        context_args["storage_state"] = state_file
                    context = browser.new_context(**context_args)
                    context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())
                    gc.collect()

                path_part = urlparse(url).path.strip("/").replace("/", "_")
                filename = f"{path_part}.pdf" if path_part else "index.pdf"
                output_path = os.path.join(output_dir, filename)

                if os.path.exists(output_path):
                    logging.info(f"[{index}/{len(all_urls)}] Skipping (already exists): {filename}")
                    continue

                if not browser.is_connected():
                    logging.warning("[!] Browser disconnected. Re-launching instance...")
                    browser = p.chromium.launch(
                        headless=True,
                        args=CHROMIUM_ARGS
                    )
                    if os.path.exists(state_file):
                        context_args["storage_state"] = state_file
                    else:
                        context_args.pop("storage_state", None)
                    context = browser.new_context(**context_args)
                    context.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "media", "font"] else route.continue_())

                # Create a fresh page per URL to prevent renderer memory bloat
                page = context.new_page()

                logging.info(f"[{index}/{len(all_urls)}] Processing: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                new_page, new_ctx, new_brw = handle_security_challenge(page, browser, context, p, url, state_file, context_args)
                if new_page:
                    page = new_page
                if new_ctx:
                    context = new_ctx
                if new_brw:
                    browser = new_brw
                
                simulate_human_behavior(page)
                
                try:
                    if not page.is_closed():
                        page.wait_for_timeout(2000)
                        page.evaluate("window.scrollTo(0, 300);")
                        page.wait_for_timeout(500)
                except Exception as nav_err:
                    logging.warning(f"[!] Navigation shift during page settle for {url}: {nav_err}")
                
                # Save PDF
                if not page.is_closed():
                    page.pdf(
                        path=output_path,
                        format="A4",
                        print_background=True,
                        margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"}
                    )
                    logging.info(f"-> Saved: {output_path}")
                
            except Exception as e:
                logging.error(f"[-] Error processing {url}: {e}")
            finally:
                # Ensure each page instance is explicitly closed immediately after processing
                if page and not page.is_closed():
                    try:
                        page.close()
                    except Exception:
                        pass
        
        try:
            context.close()
            browser.close()
        except Exception:
            pass
        logging.info(f"\nFinished! All PDFs saved in directory: '{output_dir}/'")

if __name__ == "__main__":
    print("=" * 60)
    print(" PLAYWRIGHT SITE CRAWLER & PDF ARCHIVER ")
    print("=" * 60)
    
    target_url = input("Enter the target website URL (e.g., https://www.dinnerthendessert.com): ").strip()
    
    if not target_url:
        print("[-] Error: No URL provided. Exiting.")
    else:
        # Prepend https:// if user omitted scheme
        if not target_url.startswith(("http://", "https://")):
            target_url = "https://" + target_url
            
        custom_dir = input("Enter output directory for PDFs [default: site_pages_pdf]: ").strip()
        output_folder = custom_dir if custom_dir else "site_pages_pdf"
        
        download_site_with_anti_adblock(target_url, output_dir=output_folder)
