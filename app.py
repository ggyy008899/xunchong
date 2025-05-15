from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, current_app
from config import Config
from models import db, PetLostReport, PetFoundReport
from flask_migrate import Migrate
from datetime import datetime
import os
import logging
from werkzeug.utils import secure_filename
import uuid
import json
import hashlib # Import hashlib for SHA1
import xml.etree.ElementTree as ET # For parsing WeChat XML

def create_app(config_class=Config):
    app = Flask(__name__)

    # --- 设置日志级别，尝试与Gunicorn集成 ---
    # 在生产环境中 (非debug模式)，Flask的默认日志级别可能是WARNING
    # 我们希望INFO级别的日志也能被Gunicorn捕获
    if not app.debug:
        import logging # 确保导入
        gunicorn_error_logger = logging.getLogger('gunicorn.error')
        app.logger.handlers = gunicorn_error_logger.handlers
        app.logger.setLevel(gunicorn_error_logger.level if gunicorn_error_logger.level != 0 else logging.INFO) # 如果gunicorn级别未设置(0)，则默认为INFO
        # 为确保我们自己的INFO日志能输出，如果Gunicorn的级别高于INFO，我们可能还是需要强制INFO
        if app.logger.level > logging.INFO:
            app.logger.setLevel(logging.INFO)
        app.logger.info("Flask logger configured to integrate with Gunicorn's error logger.") # 加一条日志确认配置
    # -------------------------------------

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
        location_query = search_params.get('location') # Renamed to avoid conflict if 'location' is used as a var name
        color = search_params.get('color')
        # 'status' query param will be primarily used by the template to switch views

        # --- Query for Lost Pet Reports (active ones) ---
        lost_query = PetLostReport.query.filter(PetLostReport.is_found == False)
        if pet_type:
            lost_query = lost_query.filter(PetLostReport.pet_type == pet_type)
        if location_query:
            lost_query = lost_query.filter(PetLostReport.lost_location_text.ilike(f'%{location_query}%'))
        if color:
            lost_query = lost_query.filter(PetLostReport.color.ilike(f'%{color}%'))
        lost_reports = lost_query.order_by(PetLostReport.created_at.desc()).all()

        # --- Query for Found Pet Reports ---
        found_query = PetFoundReport.query
        if pet_type:
            found_query = found_query.filter(PetFoundReport.pet_type == pet_type)
        if location_query: # Apply location search to found_location_text
            found_query = found_query.filter(PetFoundReport.found_location_text.ilike(f'%{location_query}%'))
        if color:
            found_query = found_query.filter(PetFoundReport.color.ilike(f'%{color}%'))
        found_reports = found_query.order_by(PetFoundReport.created_at.desc()).all()
        
        # --- 获取地图 API Key --- 
        tencent_map_api_key = current_app.config.get('TENCENT_MAP_API_KEY')

        # --- 渲染模板，传递结果、搜索参数和 API Key --- 
        return render_template('index.html', 
                               title='首页 - 寻宠与招领',
                               lost_reports=lost_reports, 
                               found_reports=found_reports, 
                               search_params=search_params, 
                               tencent_map_api_key=tencent_map_api_key)

    # Placeholder for WeChat verification endpoint
    @app.route('/wechat', methods=['GET', 'POST'])
    def wechat_interface():
        if request.method == 'GET':
            # WeChat server verification
            token = current_app.config.get('WECHAT_TOKEN')
            if not token:
                current_app.logger.error('WECHAT_TOKEN is not configured.')
                return 'Configuration error: WECHAT_TOKEN missing', 500

            signature = request.args.get('signature', '')
            timestamp = request.args.get('timestamp', '')
            nonce = request.args.get('nonce', '')
            echostr = request.args.get('echostr', '')

            if not all([signature, timestamp, nonce, echostr]):
                current_app.logger.warning('WeChat verification: Missing parameters')
                return 'Missing parameters', 400

            try:
                # Sort parameters
                params = sorted([token, timestamp, nonce])
                # Concatenate
                string_to_hash = "".join(params)
                # SHA1 hash
                sha1 = hashlib.sha1(string_to_hash.encode('utf-8'))
                calculated_signature = sha1.hexdigest()

                if calculated_signature == signature:
                    current_app.logger.info('WeChat verification successful.')
                    return echostr, 200
                else:
                    current_app.logger.warning(f'WeChat verification failed. Expected: {calculated_signature}, Got: {signature}')
                    return 'Signature verification failed', 401
            except Exception as e:
                current_app.logger.error(f'Error during WeChat verification: {e}')
                return 'Internal server error during verification', 500
                
        elif request.method == 'POST':
            # Handle incoming messages from users (e.g., menu clicks, text messages)
            try:
                xml_data = request.data
                if not xml_data:
                    current_app.logger.warning('WeChat POST: Received empty data')
                    return "success" # WeChat expects 'success' or empty string

                root = ET.fromstring(xml_data)
                msg_type = root.find('MsgType').text if root.find('MsgType') is not None else 'UnknownMsgType'
                to_user_name = root.find('ToUserName').text if root.find('ToUserName') is not None else 'N/A'
                from_user_name = root.find('FromUserName').text if root.find('FromUserName') is not None else 'N/A'

                log_message = f"WeChat POST: FromUser='{from_user_name}', ToUser='{to_user_name}', MsgType='{msg_type}'"

                if msg_type == 'event':
                    event = root.find('Event').text if root.find('Event') is not None else 'UnknownEvent'
                    log_message += f", Event='{event}'"
                    if event == 'CLICK':
                        event_key = root.find('EventKey').text if root.find('EventKey') is not None else 'NoKey'
                        log_message += f", EventKey='{event_key}'"
                elif msg_type == 'text':
                    content = root.find('Content').text if root.find('Content') is not None else 'NoContent'
                    log_message += f", Content='{content[:50]}'" # Log first 50 chars of text
                
                current_app.logger.info(log_message)
                
                # For menu clicks leading to URLs (view events), WeChat handles the redirect.
                # For other events or text messages, we just need to acknowledge receipt.
                # WeChat requires a response of "success" or an empty string.
                # Responding with an empty string is often safer.
                return "", 200 # Return empty string and 200 OK

            except ET.ParseError as e:
                current_app.logger.error(f'WeChat POST: XML ParseError: {e} - Data: {request.data[:200]}')
                return "success" # Still try to satisfy WeChat
            except Exception as e:
                current_app.logger.error(f'WeChat POST: Error processing message: {e}')
                return "success" # Still try to satisfy WeChat

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

    # --- Route for submitting Pet Found reports (招领启事) ---
    @app.route('/report/found', methods=['GET', 'POST'])
    def report_found():
        form_data = request.form.to_dict() # For repopulating form on GET or error

        if request.method == 'POST':
            # --- Handle Photo Uploads (similar to report_lost) ---
            photo_urls = []
            if 'photos' in request.files:
                files = request.files.getlist('photos')
                for file in files:
                    if file and file.filename != '' and '.' in file.filename and \
                       file.filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']:
                        filename = secure_filename(str(uuid.uuid4()) + os.path.splitext(file.filename)[1])
                        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        try:
                            file.save(file_path)
                            photo_urls.append(url_for('static', filename=f'uploads/{filename}', _external=True))
                        except Exception as e:
                            current_app.logger.error(f"Error saving uploaded file: {e}")
                            flash('上传照片时出错，请检查文件或稍后再试。', 'error')
                            return render_template('report_found_form.html', title='发布招领启事 - 文件错误', form_data=form_data)
                    elif file.filename != '': # If file exists but is not allowed
                        flash(f'文件类型 "{file.filename.rsplit('.', 1)[1]}" 不被允许。请上传图片文件。', 'error')
                        return render_template('report_found_form.html', title='发布招领启事 - 文件类型错误', form_data=form_data)
            
            # --- Process 'other_breed' --- 
            breed = request.form.get('breed')
            actual_breed = breed
            if breed == '其他品种':
                other_breed_value = request.form.get('other_breed', '').strip()
                if not other_breed_value:
                    flash('选择了“其他品种”但未填写具体品种名称。', 'error')
                    return render_template('report_found_form.html', title='发布招领启事 - 品种错误', form_data=form_data)
                actual_breed = other_breed_value
            elif not breed: # If breed is optional and not selected, set to None or empty string based on model
                actual_breed = None # Or '' if your model prefers empty strings for nullable charfields

            # --- Parse Found Time ---
            found_time_str = request.form.get('found_time')
            found_time_dt = None
            if found_time_str:
                try:
                    found_time_dt = datetime.fromisoformat(found_time_str)
                except ValueError:
                    flash('拾获时间格式无效，请使用日期时间选择器。', 'error')
                    return render_template('report_found_form.html', title='发布招领启事 - 时间错误', form_data=form_data)
            else:
                flash('拾获时间是必填项。', 'error')
                return render_template('report_found_form.html', title='发布招领启事 - 时间错误', form_data=form_data)

            try:
                new_found_report = PetFoundReport(
                    pet_type=request.form['pet_type'],
                    breed=actual_breed,
                    color=request.form['color'],
                    gender=request.form['gender'],
                    features=request.form['features'],
                    found_time=found_time_dt,
                    found_location_text=request.form['found_location_text'],
                    contact_info=request.form['contact_info'],
                    _photo_urls=json.dumps(photo_urls) if photo_urls else None # Store as JSON string
                )
                db.session.add(new_found_report)
                db.session.commit()
                flash('招领启事发布成功！', 'success')
                return redirect(url_for('index')) # Or a different success page
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating found report: {e}")
                flash('发布招领启事时发生数据库错误，请稍后重试。', 'error')
                return render_template('report_found_form.html', title='发布招领启事 - 错误', form_data=form_data)

        # If GET request, just render the form
        return render_template('report_found_form.html', title='发布招领启事', form_data={})

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
    with app.app_context():
        current_app.logger.info("Ensuring database tables are created via db.create_all()...")
        db.create_all()
        current_app.logger.info("Finished db.create_all(). Tables should now exist if models are defined.")

    return app

if __name__ == '__main__':
    app = create_app()
    # Remember to set FLASK_ENV=development and FLASK_APP=app.py in your environment
    # For production, use a proper WSGI server like Gunicorn or uWSGI
    # Explicitly set host and port
    app.run(host='0.0.0.0', port=5002, debug=True) # debug=True is NOT for production!
