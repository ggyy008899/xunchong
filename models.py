from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json # To handle photo_urls

db = SQLAlchemy()

# --- Define your database models here --- 

class PetLostReport(db.Model):
    __tablename__ = 'pet_lost_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_openid = db.Column(db.String(128), index=True, nullable=True) # Optional user link
    # --- 基本信息 ---
    pet_type = db.Column(db.String(50), nullable=False) # 猫, 狗, 其他
    breed = db.Column(db.String(100), nullable=False) # 品种 (如果是'其他品种'，具体描述可能在 features 或单独字段)
    # other_breed = db.Column(db.String(100), nullable=True) # 如果 breed 是 '其他品种'，这里填写具体内容
    color = db.Column(db.String(50), nullable=False) # 颜色
    gender = db.Column(db.String(10), nullable=True) # 性别 (公, 母, 未知)
    age = db.Column(db.String(50), nullable=True) # 年龄描述 (例如 '约2岁', '幼年', '成年')
    features = db.Column(db.Text, nullable=False) # 特征描述

    # --- 丢失/找到信息 ---
    lost_time = db.Column(db.DateTime, nullable=False, default=datetime.utcnow) # 丢失时间
    lost_location_text = db.Column(db.Text, nullable=False) # 丢失地点文字描述
    latitude = db.Column(db.Float, nullable=True)  # 新增：纬度
    longitude = db.Column(db.Float, nullable=True) # 新增：经度

    contact_info = db.Column(db.String(200), nullable=False) # 联系方式
    _photo_urls = db.Column(db.Text, nullable=True) # Store as JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_found = db.Column(db.Boolean, default=False, nullable=False) # 是否已找到
    found_time = db.Column(db.DateTime, nullable=True) # 找到时间

    @property
    def photo_urls(self):
        """Return photo URLs as a list."""
        if self._photo_urls:
            try:
                return json.loads(self._photo_urls)
            except json.JSONDecodeError:
                return [] # Or handle error appropriately
        return []

    @photo_urls.setter
    def photo_urls(self, urls):
        """Store photo URLs as a JSON string."""
        if urls and isinstance(urls, list):
            self._photo_urls = json.dumps(urls)
        else:
            self._photo_urls = None

    def __repr__(self):
        return f'<PetLostReport {self.id}: {self.pet_type} lost at {self.lost_location_text}>'

class PetFoundReport(db.Model):
    __tablename__ = 'pet_found_reports'

    id = db.Column(db.Integer, primary_key=True)
    user_openid = db.Column(db.String(128), index=True, nullable=True) # Optional user link
    pet_type = db.Column(db.String(50), nullable=False)
    breed = db.Column(db.String(100), nullable=True)
    color = db.Column(db.String(50), nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    features = db.Column(db.Text, nullable=False)
    found_time = db.Column(db.DateTime, nullable=False)
    found_location_text = db.Column(db.Text, nullable=False)
    latitude = db.Column(db.Float, nullable=True)  # 新增：纬度
    longitude = db.Column(db.Float, nullable=True) # 新增：经度
    contact_info = db.Column(db.String(255), nullable=False)
    _photo_urls = db.Column(db.Text, nullable=True) # Store as JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def photo_urls(self):
        """Return photo URLs as a list."""
        if self._photo_urls:
            try:
                return json.loads(self._photo_urls)
            except json.JSONDecodeError:
                return [] # Or handle error appropriately
        return []

    @photo_urls.setter
    def photo_urls(self, urls):
        """Store photo URLs as a JSON string."""
        if urls and isinstance(urls, list):
            self._photo_urls = json.dumps(urls)
        else:
            self._photo_urls = None

    def __repr__(self):
        return f'<PetFoundReport {self.id}: {self.pet_type} found at {self.found_location_text}>'

# Example (We will define actual models later):
# class User(db.Model):
#     id = db.Column(db.Integer, primary_key=True)
#     openid = db.Column(db.String(128), unique=True, nullable=False)
#     # ... other fields
