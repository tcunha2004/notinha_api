import os

from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
AWS_REGION = os.environ["AWS_REGION"]
S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://notinha:notinha@localhost:5432/notinha"
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
