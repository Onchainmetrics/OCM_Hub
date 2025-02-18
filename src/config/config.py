import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DUNE_API_KEY = os.getenv('DUNE_API_KEY')

# Allowed Users (optional)
ALLOWED_USERS = os.getenv('ALLOWED_USERS', '').split(',')

# Dune Query IDs
QUERIES = {
    'token_info': '123456',  # Replace with actual query ID
    'holder_analysis': '789012',  # Replace with actual query ID
    # Add more queries as needed
} 