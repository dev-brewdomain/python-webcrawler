import os
import requests
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from playwright.sync_api import sync_playwright

def get_urls_from_sitemap(sitemap_url: str):
    """Fetches all URLs from a WordPress XML sitemap recursively."""
    print(f"Fetching sitemap: {sitemap_url}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"[-] Failed to fetch sitemap: {e}")
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

def download_site_with_anti_adblock(start_url: str, output_dir: str = "site_pages_pdf"):
    """
    Crawls a site using sitemaps while injecting mock ad wrappers to prevent
    post-load adblock/bot detection lockouts.
    """
    os.makedirs(output_dir, exist_ok=True)
    state_file = "auth_state.json"
    
    parsed = urlparse(start_url)
    base_sitemap = f"{parsed.scheme}://{parsed.netloc}/sitemap_index.xml"
    
    all_urls = get_urls_from_sitemap(base_sitemap)
    if not all_urls:
        all_urls = get_urls_from_sitemap(f"{parsed.scheme}://{parsed.netloc}/sitemap.xml")
        
    print(f"\nFound {len(all_urls)} total URLs in sitemap.\n")
    
    with sync_playwright() as p:
        needs_verification = not os.path.exists(state_file)
        
        browser = p.chromium.launch(
            headless=True if needs_verification else True,
            args=[
                "--headless=new" if not needs_verification else "",
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
        )
        
        context_args = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US"
        }
        
        if os.path.exists(state_file):
            context_args["storage_state"] = state_file
            
        context = browser.new_context(**context_args)
        
        # INJECT MOCK AD VARIABLES & TRIGGERS BEFORE PAGE LOADS
        # This tricks post-load adblock checkers into thinking ads loaded successfully.
        context.add_init_script("""
            // Mock standard global ad-load flags used by recipe networks
            window.canRunAds = true;
            window.adsLoaded = true;
            window.mediavineLoaded = true;
            
            // Automatically inject dummy ad elements if the script checks DOM dimensions
            document.addEventListener("DOMContentLoaded", () => {
                const fakeAd = document.createElement('div');
                fakeAd.id = 'gpt-ad-leaderboard';
                fakeAd.style.width = '728px';
                fakeAd.style.height = '90px';
                fakeAd.style.display = 'block';
                document.body.appendChild(fakeAd);
            });
        """)
        
        page = context.new_page()
        
        if needs_verification:
            print("\n" + "="*60)
            print("ACTION REQUIRED: A verification window has opened.")
            print("Please solve any verification check in the browser.")
            print("Once you can see the normal website content, come back here and press ENTER.")
            print("="*60 + "\n")
            
            page.goto(start_url, wait_until="domcontentloaded")
            input("Press ENTER after you have successfully passed the verification...")
            
            context.storage_state(path=state_file)
            print(f"-> Session state saved to {state_file}.")
            
            browser.close()
            browser = p.chromium.launch(headless=True, args=["--headless=new", "--disable-blink-features=AutomationControlled"])
            context = browser.new_context(storage_state=state_file, **context_args)
            page = context.new_page()

        for index, url in enumerate(all_urls, 1):
            try:
                print(f"[{index}/{len(all_urls)}] Processing: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Wait for post-load scripts to execute and settle
                page.wait_for_timeout(4000)
                
                # Scroll to trigger any lazy-loaded layout checks
                page.evaluate("window.scrollTo(0, 300);")
                page.wait_for_timeout(1000)
                
                # Safe filename generation
                path_part = urlparse(url).path.strip("/").replace("/", "_")
                filename = f"{path_part}.pdf" if path_part else "index.pdf"
                output_path = os.path.join(output_dir, filename)
                
                counter = 1
                base_out_path = output_path
                while os.path.exists(output_path):
                    name, ext = os.path.splitext(base_out_path)
                    output_path = f"{name}_{counter}{ext}"
                    counter += 1
                
                # Save PDF
                page.pdf(
                    path=output_path,
                    format="A4",
                    print_background=True,
                    margin={"top": "20px", "bottom": "20px", "left": "20px", "right": "20px"}
                )
                print(f"-> Saved: {output_path}")
                
            except Exception as e:
                print(f"[-] Error processing {url}: {e}")
                
        browser.close()
        print(f"\nFinished! All PDFs saved in directory: '{output_dir}/'")

if __name__ == "__main__":
    target_url = "https://www.dinnerthendessert.com"
    download_site_with_anti_adblock(target_url, output_dir="site_pages_pdf")
