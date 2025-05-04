import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- 添加调试 Print 语句 --- 
import os # 确保 os 已导入
print(f"[DEBUG config.py] Attempting to load .env. TENCENT_MAP_API_KEY from os.environ: {os.environ.get('TENCENT_MAP_API_KEY')}")
# ---------------------------

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'a-hard-to-guess-string'
    # Example for SQLite, easy to start with
    # For production, consider PostgreSQL or MySQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # WeChat API configuration (placeholders)
    WECHAT_APPID = os.environ.get('WECHAT_APPID')
    WECHAT_APPSECRET = os.environ.get('WECHAT_APPSECRET')
    WECHAT_TOKEN = os.environ.get('WECHAT_TOKEN') or 'your_wechat_token_here' # Token for verifying server URL

    # --- 添加上传文件夹配置 ---
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'static/uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'} # Allowed image extensions
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # Add other configurations as needed, e.g., image storage

    # --- 腾讯地图 API Key ---
    TENCENT_MAP_API_KEY = os.environ.get('TENCENT_MAP_API_KEY')

# --- 文件上传配置 ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
