import time
import subprocess
import logging
from datetime import datetime

# Setup basic logging for the scheduler
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scheduler.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

# Name of your main crawler script file
SCRIPT_NAME = "web-crawler.py"  # Change this to whatever you named your main script

def run_scraper():
    logging.info("Starting scheduled scraper run...")
    try:
        # Run the script as a subprocess
        result = subprocess.run(["python", SCRIPT_NAME], capture_output=False, text=True)
        if result.returncode == 0:
            logging.info("Scraper run completed successfully.")
        else:
            logging.error(f"Scraper finished with non-zero exit code: {result.returncode}")
    except Exception as e:
        logging.error(f"Failed to execute scraper: {e}")

if __name__ == "__main__":
    logging.info("Hourly Scraper Scheduler Initialized.")
    while True:
        run_scraper()
        
        # Sleep for 1 hour (3600 seconds)
        logging.info("Waiting 1 hour until the next scheduled run...")
        time.sleep(3600)
