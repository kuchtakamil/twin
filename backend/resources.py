from pypdf import PdfReader
import json
import logging

# Configure logging for AWS Lambda
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Read CV PDF
try:
    reader = PdfReader("./data/cv.pdf")
    cv = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            cv += text
    logger.info(f"Loaded CV from PDF ({len(cv)} characters)")
except FileNotFoundError:
    logger.warning("CV PDF not found, using placeholder")
    cv = "CV not available"
except Exception as e:
    logger.error(f"Error reading CV PDF: {e}", exc_info=True)
    cv = "CV not available"

# Read other data files
try:
    with open("./data/summary.txt", "r", encoding="utf-8") as f:
        summary = f.read()
    logger.info(f"Loaded summary.txt ({len(summary)} characters)")
except Exception as e:
    logger.error(f"Error reading summary.txt: {e}", exc_info=True)
    summary = ""

try:
    with open("./data/style.txt", "r", encoding="utf-8") as f:
        style = f.read()
    logger.info(f"Loaded style.txt ({len(style)} characters)")
except Exception as e:
    logger.error(f"Error reading style.txt: {e}", exc_info=True)
    style = ""

try:
    with open("./data/facts.json", "r", encoding="utf-8") as f:
        facts = json.load(f)
    logger.info(f"Loaded facts.json ({len(facts)} keys)")
except Exception as e:
    logger.error(f"Error reading facts.json: {e}", exc_info=True)
    facts = {}