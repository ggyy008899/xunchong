import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

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
    # --- 百度地图 API Key (新增) ---
    BAIDU_MAP_API_KEY = os.environ.get('BAIDU_MAP_API_KEY')
    # 微信公众号配置
WECHAT_APPID = 'wxe07ebc51757de00c'  # 替换成您的 AppID
WECHAT_APPSECRET = 'f4243f138d39cfcc4211b648cfaef078'  # 替换成您的 AppSecret
WECHAT_REDIRECT_URI = 'http://hebpet.online/wechat/callback' # 微信授权后的回调地址，域名部分需要与公众号后台配置一致
