from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, current_app
from config import Config
from models import db, PetLostReport
from flask_migrate import Migrate
from datetime import datetime
import os
import logging
from werkzeug.utils import secure_filename
import uuid

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # --- 添加日志：检查配置加载后的 API Key --- 
    loaded_key = app.config.get('TENCENT_MAP_API_KEY')
    app.logger.info(f"[create_app] Loaded TENCENT_MAP_API_KEY: {'<Not Set>' if not loaded_key else loaded_key[:5] + '...'}") # 只打印前缀以防意外泄露
    # --------------------------------------

    # Ensure the upload folder exists AFTER config is loaded (using .get() for safety)
    upload_folder_path = app.config.get('UPLOAD_FOLDER')
    if upload_folder_path:
        os.makedirs(upload_folder_path, exist_ok=True)
    else:
        # Log or raise an error if UPLOAD_FOLDER is not configured properly
        app.logger.error("UPLOAD_FOLDER is not configured correctly in Config class!")
        # Optionally raise an exception to halt startup if this is critical
        # raise ValueError("UPLOAD_FOLDER configuration missing")

    db.init_app(app)
    migrate = Migrate(app, db)

    # A simple route for the homepage (will be an H5 page)
    @app.route('/')
    def index():
        # --- 获取搜索参数 --- 
        search_params = request.args.to_dict()
        pet_type = search_params.get('pet_type')
        location = search_params.get('location')
        color = search_params.get('color')
        status = search_params.get('status')

        # --- 构建基础查询 --- 
        query = PetLostReport.query

        # --- 应用过滤条件 --- 
        if pet_type:
            query = query.filter(PetLostReport.pet_type == pet_type)
        if location:
            query = query.filter(PetLostReport.lost_location_text.ilike(f'%{location}%'))
        if color:
            query = query.filter(PetLostReport.color.ilike(f'%{color}%'))
        if status == 'lost':
            query = query.filter(PetLostReport.is_found == False)
        elif status == 'found':
            query = query.filter(PetLostReport.is_found == True)
        # status 为空或无效值时不过滤状态

        # --- 排序并获取结果 --- 
        reports = query.order_by(PetLostReport.created_at.desc()).all()
        
        # --- 获取地图 API Key --- 
        tencent_map_api_key = current_app.config.get('TENCENT_MAP_API_KEY')

        # --- 渲染模板，传递结果、搜索参数和 API Key --- 
        return render_template('index.html', title='首页 - 寻宠启事列表', reports=reports, search_params=search_params, tencent_map_api_key=tencent_map_api_key)

    # Placeholder for WeChat verification endpoint
    @app.route('/wechat', methods=['GET', 'POST'])
    def wechat_interface():
        if request.method == 'GET':
            # WeChat server verification
            # TODO: Implement verification logic using WECHAT_TOKEN
            signature = request.args.get('signature', '')
            timestamp = request.args.get('timestamp', '')
            nonce = request.args.get('nonce', '')
            echostr = request.args.get('echostr', '')
            # if verify_signature(signature, timestamp, nonce):
            #     return echostr
            return 'Failed verification', 401 # Placeholder
        elif request.method == 'POST':
            # Handle incoming messages from users
            # TODO: Implement message handling logic
            xml_data = request.data
            # Process xml_data
            return "success" # Required response by WeChat

    # TODO: Add routes for submitting/viewing pet reports (H5 endpoints)
    @app.route('/report/lost', methods=['GET', 'POST'])
    def report_lost():
        form_data = request.form.to_dict() # Get form data for repopulation on GET or error
        # TODO: 强烈建议从配置或环境变量获取 AK，避免硬编码！
        baidu_map_ak = "TDP9rUBgKJFfKIzHjok05CbJLJ3cDNGP" # 更新为新的浏览器端 AK

        # --- 添加日志：检查路由处理时的 API Key --- 
        current_app.logger.info(f"[report_lost route] BAIDU_MAP_AK used: {'<Not Set>' if not baidu_map_ak else baidu_map_ak[:5] + '...'}")
        # -----------------------------------------

        if request.method == 'POST':
            # --- Validation --- 
            # (Existing validation code remains the same)
            required_fields = ['pet_type', 'breed', 'color', 'gender', 'features', 'lost_time', 'lost_location_text', 'contact_info']
            breed_select = request.form.get('breed')
            other_breed_text = request.form.get('other_breed', '').strip()

            if breed_select == '其他品种' and not other_breed_text:
                flash('选择了“其他品种”时，请填写具体品种。', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data, baidu_map_ak=baidu_map_ak)

            missing_fields = [field for field in required_fields if not request.form.get(field)]
            # Adjust missing fields check if '其他品种' is selected but text is provided
            if breed_select == '其他品种' and 'breed' in missing_fields:
                 missing_fields.remove('breed') # Don't flag 'breed' as missing if 'other_breed' is filled
            
            if missing_fields:
                flash(f'请填写所有必填项: {", ".join(missing_fields)}', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data, baidu_map_ak=baidu_map_ak)
            # --- End Validation ---

            # --- Handle file uploads --- 
            photo_urls = []
            uploaded_files = request.files.getlist('photos')
            # Use current_app to access config within request context
            upload_folder_path = current_app.config.get('UPLOAD_FOLDER')

            if not upload_folder_path:
                flash('服务器上传文件夹配置错误。', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data, baidu_map_ak=baidu_map_ak)

            for file in uploaded_files:
                if file and file.filename != '':
                    try:
                        # Get original filename and extension
                        original_filename = secure_filename(file.filename) # Still use secure_filename for basic cleaning and getting extension safely
                        _, ext = os.path.splitext(original_filename)
                        if not ext: # Handle cases with no extension
                            ext = '.unknown'
                        
                        # Generate unique filename
                        unique_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
                        
                        # Construct save path
                        save_path = os.path.join(upload_folder_path, unique_filename)
                        file.save(save_path)
                        
                        # Generate URL using the unique filename
                        file_url = url_for('static', filename=f'uploads/{unique_filename}')
                        photo_urls.append(file_url)
                    except Exception as e:
                        flash(f'图片上传失败: {e}', 'error')
                        # Consider if partial success is acceptable or should halt
                        # return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data)
            # --- End File Uploads ---

            # --- Determine actual breed value --- 
            actual_breed = breed_select
            if breed_select == '其他品种':
                actual_breed = other_breed_text # Use the user-provided other breed text
            # ---------------------------------- 

            # --- Create new report object --- 
            try:
                lost_time_dt = datetime.strptime(request.form['lost_time'], '%Y-%m-%dT%H:%M')
            except ValueError:
                 flash('丢失时间格式无效，请使用日期时间选择器。', 'error')
                 return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data, baidu_map_ak=baidu_map_ak)
            
            # --- 获取经纬度 --- 
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            lat_float = None
            lon_float = None
            try:
                if latitude:
                    lat_float = float(latitude)
                if longitude:
                    lon_float = float(longitude)
            except ValueError:
                flash('经纬度格式无效。', 'error')
                # 依然允许提交，只是经纬度为空
                pass # Optionally log this error
            # ----------------- 

            try:
                new_report = PetLostReport(
                    pet_type=request.form['pet_type'],
                    breed=actual_breed, # Pass the determined actual_breed
                    # REMOVED invalid keyword: other_breed=request.form.get('other_breed') if request.form['breed'] == '其他品种' else None,
                    color=request.form['color'],
                    gender=request.form['gender'],
                    age=request.form.get('age'),
                    features=request.form['features'],
                    lost_time=lost_time_dt, # Use parsed datetime
                    lost_location_text=request.form['lost_location_text'],
                    latitude=lat_float,   # 保存纬度
                    longitude=lon_float,  # 保存经度
                    contact_info=request.form['contact_info'],
                    photo_urls=photo_urls
                )
                db.session.add(new_report)
                db.session.commit()
                flash('寻宠启事发布成功！', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Error creating report: {e}") # Log the actual error
                flash(f'发布启事时发生数据库错误，请稍后重试。', 'error') # User-friendly message
                return render_template('report_lost_form.html', title='发布寻宠启事 - 错误', form_data=form_data, baidu_map_ak=baidu_map_ak)
            # --- End Create Report ---

        # If GET request, just render the form, passing the API key
        return render_template('report_lost_form.html', title='发布寻宠启事', form_data={}, baidu_map_ak=baidu_map_ak)

    # ------------------ 标记为已找到 ------------------
    @app.route('/report/<int:report_id>/found', methods=['POST'])
    def mark_as_found(report_id):
        report = PetLostReport.query.get_or_404(report_id)
        if not report.is_found:
            report.is_found = True
            report.found_time = datetime.utcnow()
            db.session.commit()
            flash('寻宠启事已成功标记为找到！', 'success')
        else:
            flash('该启事已经被标记为找到了。', 'info')
        return redirect(url_for('index'))
    # -----------------------------------------------

    # Example:
    # @app.route('/search', methods=['GET'])
    # def search_reports():
    #     # Process search query
    #     # Fetch results from DB
    #     return render_template('search_results.html', results=[])

    # Create database tables if they don't exist
    # Use Flask-Migrate for better database schema management in real projects
    # with app.app_context():
    #     db.create_all()

    return app

if __name__ == '__main__':
    app = create_app()
    # Remember to set FLASK_ENV=development and FLASK_APP=app.py in your environment
    # For production, use a proper WSGI server like Gunicorn or uWSGI
    # Explicitly set host and port
    app.run(host='0.0.0.0', port=5002, debug=True) # debug=True is NOT for production!
