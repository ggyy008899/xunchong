# 宠物寻回平台 (Pet Finder)

基于微信公众号的宠物丢失与招领信息匹配平台后端服务。

## 技术栈

*   Python
*   Flask
*   Flask-SQLAlchemy
*   (待定)

## 运行

1.  创建并激活虚拟环境:
    ```bash
    python -m venv venv
    source venv/bin/activate  # macOS/Linux
    # venv\Scripts\activate  # Windows
    ```
2.  安装依赖:
    ```bash
    pip install -r requirements.txt
    ```
3.  (可选) 创建 `.env` 文件并设置环境变量 (如 `SECRET_KEY`, `DATABASE_URL`, `WECHAT_APPID`, `WECHAT_APPSECRET`, `WECHAT_TOKEN`).
4.  运行开发服务器:
    ```bash
    export FLASK_APP=app.py
    export FLASK_ENV=development # Enables debug mode
    flask run
    ```

## 功能 (计划中)

*   用户通过微信公众号菜单触发功能。
*   H5页面用于发布寻宠/招领启事。
*   H5页面用于搜索/浏览启事信息。
*   后端处理微信服务器消息和验证。
*   数据库存储启事信息。
*   (未来) 自动匹配算法。
*   (未来) 图片信息自动识别。
