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
from sqlalchemy import desc # For explicit descending order
import xml.etree.ElementTree as ET # For parsing WeChat XML
import time # For CreateTime in WeChat messages
from PIL import Image, UnidentifiedImageError

# Helper function for image compression
def compress_image(image_path, max_width=1024, quality_jpeg=85):
    """
    Compresses an image by resizing if it exceeds max_width and adjusting quality.
    Overwrites the original image file.
    """
    try:
        img = Image.open(image_path)
        original_format = img.format # Store original format
        
        # Ensure image is in a mode that supports saving (e.g., convert P mode with palette to RGBA)
        if img.mode == 'P': # Palette mode
            img = img.convert("RGBA")
        elif img.mode == 'LA': # Luminance Alpha
             img = img.convert("RGBA")
        elif img.mode not in ("RGB", "RGBA", "L"): # L is grayscale
            current_app.logger.warning(f"Image {image_path} has an unsupported mode {img.mode} for direct saving, attempting conversion to RGBA.")
            img = img.convert("RGBA")
            original_format = 'PNG' # After conversion to RGBA, PNG is a safer bet for saving

        current_width, current_height = img.size
        if current_width > max_width:
            ratio = max_width / current_width
            new_height = int(current_height * ratio)
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS) 
            current_app.logger.info(f"Resized image {image_path} from {current_width}x{current_height} to {max_width}x{new_height}")

        save_params = {}
        fmt = original_format.upper() if original_format else ''

        if fmt in ['JPEG', 'JPG']:
            save_params['format'] = 'JPEG'
            save_params['quality'] = quality_jpeg
            save_params['optimize'] = True 
        elif fmt == 'PNG':
            save_params['format'] = 'PNG'
            save_params['optimize'] = True
        elif fmt == 'GIF':
            save_params['format'] = 'GIF'
        elif fmt == 'WEBP':
            save_params['format'] = 'WEBP'
            save_params['quality'] = quality_jpeg 
        else:
            if img.mode == "RGBA" and fmt not in ['PNG', 'WEBP']:
                 current_app.logger.warning(f"Image {image_path} (format: {fmt}, mode: {img.mode}) was likely converted or is unhandled; saving as PNG.")
                 save_params['format'] = 'PNG'
                 save_params['optimize'] = True
            elif fmt: 
                save_params['format'] = original_format
                current_app.logger.info(f"Image {image_path} format '{fmt}' not explicitly handled for quality/optimization, saving with original format.")
            else: 
                current_app.logger.warning(f"Image {image_path} has unknown format. Saving as PNG as a fallback.")
                save_params['format'] = 'PNG'
                save_params['optimize'] = True
        
        if save_params.get('format') == 'JPEG' and img.mode == 'RGBA':
            img = img.convert('RGB')
            current_app.logger.info(f"Converted RGBA image {image_path} to RGB for JPEG saving.")

        img.save(image_path, **save_params)
        current_app.logger.info(f"Compressed and saved image {image_path} with parameters: {save_params}")

    except UnidentifiedImageError:
        current_app.logger.error(f"Cannot identify image file {image_path}. It might be corrupted or not a valid image format supported by Pillow.")
    except FileNotFoundError:
        current_app.logger.error(f"Image file not found at {image_path} during compression attempt.")
    except Exception as e:
        current_app.logger.error(f"An unexpected error occurred during image compression for {image_path}: {e}", exc_info=True)
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
    @app.route('/ping')
    def ping():
        return "pong"

    @app.route('/')
    def index():
        # 合规要求首页自动跳转到静态学习演示页
        from flask import send_from_directory
        return send_from_directory('static', 'index.html')

    # --- 获取 report_type 参数，用于区分显示寻宠还是招领 --- 
        report_type_filter = request.args.get('report_type', 'all') # 'lost', 'found', or 'all'

        # --- 获取搜索参数 --- 
        search_params = request.args.to_dict()
        # 如果 report_type_filter 不是 'all'，它应该优先于 search_params 中的 report_type
        # 但我们这里的设计是 report_type_filter 控制查询范围，search_params 用于进一步筛选
        pet_type = search_params.get('pet_type')
        location_query = search_params.get('location')
        color = search_params.get('color')
        status_filter = search_params.get('status') # For lost_reports: '', 'lost', 'found'

        lost_reports = []
        found_reports = []

        # --- 根据 report_type_filter 条件化查询 ---
        if report_type_filter == 'lost' or report_type_filter == 'all':
            lost_query = PetLostReport.query
            # Apply status filter for lost reports
            if status_filter == 'lost': # Explicitly searching for 'lost' (is_found == False)
                lost_query = lost_query.filter(PetLostReport.is_found == False)
            elif status_filter == 'found': # Explicitly searching for 'found' (is_found == True)
                lost_query = lost_query.filter(PetLostReport.is_found == True)
            # If status_filter is empty or not 'lost'/'found', no status filter is applied by default
            # unless the base query for 'lost' type implies active ones (e.g. is_found == False)
            # For 'report_type_filter == lost', we usually want active ones by default, unless 'status' says otherwise
            if report_type_filter == 'lost' and not status_filter: # Default to active if viewing only lost reports and no status specified
                 lost_query = lost_query.filter(PetLostReport.is_found == False)
            
            if pet_type:
                lost_query = lost_query.filter(PetLostReport.pet_type == pet_type)
            if location_query:
                lost_query = lost_query.filter(PetLostReport.lost_location_text.ilike(f'%{location_query}%'))
            if color:
                lost_query = lost_query.filter(PetLostReport.color.ilike(f'%{color}%'))
            lost_reports = lost_query.order_by(PetLostReport.created_at.desc()).all()

        if report_type_filter == 'found' or report_type_filter == 'all':
            found_query = PetFoundReport.query
            if pet_type:
                found_query = found_query.filter(PetFoundReport.pet_type == pet_type)
            if location_query:
                found_query = found_query.filter(PetFoundReport.found_location_text.ilike(f'%{location_query}%'))
            if color:
                found_query = found_query.filter(PetFoundReport.color.ilike(f'%{color}%'))
            # 'status' filter typically doesn't apply to found_reports in the same way
            found_reports = found_query.order_by(PetFoundReport.created_at.desc()).all()
        
        # current_app.logger.info(f"Report type: {report_type_filter}, Lost: {len(lost_reports)}, Found: {len(found_reports)}")

        # --- 新增的日志代码 开始 ---
        current_app.logger.info(f"[index route] Attempting to display lost reports.")
        current_app.logger.info(f"[index route] Number of lost_reports fetched: {len(lost_reports)}")
        if lost_reports:
            current_app.logger.info(f"[index route] Details of first lost_report: ID={lost_reports[0].id}, Type={lost_reports[0].pet_type}, Breed={lost_reports[0].breed}, Location={lost_reports[0].lost_location_text}")
            # 打印更多报告信息，如果需要
            # for i, report in enumerate(lost_reports[:3]): # 打印前3条
            #     current_app.logger.info(f"[index route] Report {i+1}: ID={report.id}, Type={report.pet_type}")
        else:
            current_app.logger.info(f"[index route] lost_reports list is empty before rendering template.")
        current_app.logger.info(f"[index route] Number of found_reports fetched: {len(found_reports)}") # 也打印一下found_reports的数量
        # --- 新增的日志代码 结束 ---

        # --- 渲染模板，传递结果、搜索参数和 report_type --- 
        # --- 获取地图 API Key --- 
        # tencent_map_api_key = current_app.config.get('TENCENT_MAP_API_KEY') # Removed as per user request

        # --- 渲染模板，传递结果、搜索参数和 API Key --- 
        return render_template('index.html', 
                               title='首页 - 寻宠与招领',
                               lost_reports=lost_reports, 
                               found_reports=found_reports, 
                               search_params=search_params)

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
                # For 'CLICK' events, we need to respond with a message (e.g., news/article).
                if msg_type == 'event' and event == 'CLICK':
                    # --- Define menu event keys and their corresponding H5 page URLs --- 
                    # Ensure your domain/IP is correct and publicly accessible
                    base_url = current_app.config.get('APP_BASE_URL', f"http://{request.host}") # Fallback to request.host if not set
                    
                    menu_actions = {
                        'USER_REPORT_LOST': {
                            'title': '发布寻宠启事',
                            'description': '您的爱宠不慎走失？点击这里填写信息，让更多人帮您寻找。',
                            'pic_url': '', # Optional: Add a URL to an image
                            'url': f"{base_url}/report/lost"
                        },
                        'USER_REPORT_FOUND': {
                            'title': '发布招领信息',
                            'description': '您捡到了需要帮助的小可爱？点击这里为它寻找主人。',
                            'pic_url': '',
                            'url': f"{base_url}/report/found"
                        },
                        'VIEW_LOST_REPORTS': {
                            'title': '查看寻宠启事',
                            'description': '看看最近有哪些正在寻找的宠物，也许您能提供线索。',
                            'pic_url': '',
                            'url': f"{base_url}/?report_type=lost"
                        },
                        'VIEW_FOUND_REPORTS': {
                            'title': '查看招领信息',
                            'description': '这些小可爱正在等待主人，快来看看有没有您认识的。',
                            'pic_url': '',
                            'url': f"{base_url}/?report_type=found"
                        }
                    }

                    action_details = menu_actions.get(event_key)

                    if action_details:
                        response_xml = create_news_response(
                            to_user=from_user_name, # Swap sender and receiver
                            from_user=to_user_name,
                            articles=[action_details] # Pass as a list of one article
                        )
                        current_app.logger.info(f"Responding to EventKey '{event_key}' with news message.")
                        return response_xml, 200, {'Content-Type': 'application/xml'}
                    else:
                        current_app.logger.warning(f"No action defined for EventKey: {event_key}")
                        return "", 200 # Fallback: acknowledge if key is unknown
                else:
                    # For other events or text messages, just acknowledge receipt.
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

        # Fetch recent found reports to display on the form page
        recent_found_reports = PetFoundReport.query.order_by(PetFoundReport.created_at.desc()).limit(5).all()

        if request.method == 'POST':
            # --- Validation --- 
            # (Existing validation code remains the same)
            required_fields = ['pet_type', 'breed', 'color', 'gender', 'features', 'lost_time', 'lost_location_text', 'contact_info']
            breed_select = request.form.get('breed')
            other_breed_text = request.form.get('other_breed', '').strip()

            if breed_select == '其他品种' and not other_breed_text:
                flash('选择了“其他品种”时，请填写具体品种。', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)

            missing_fields = [field for field in required_fields if not request.form.get(field)]
            # Adjust missing fields check if '其他品种' is selected but text is provided
            if breed_select == '其他品种' and 'breed' in missing_fields:
                 missing_fields.remove('breed') # Don't flag 'breed' as missing if 'other_breed' is filled
            
            if missing_fields:
                flash(f'请填写所有必填项: {", ".join(missing_fields)}', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)

            # --- Handle file uploads --- 
            photo_urls = []
            uploaded_files_from_form = request.files.getlist('photos')
            actual_uploaded_files = [f for f in uploaded_files_from_form if f and f.filename] # Filter out empty/no-filename entries

            if len(actual_uploaded_files) > 3:
                flash('最多只能上传3张照片。请选择不超过3张照片后重新提交。', 'error')
                # form_data, baidu_map_ak, and recent_found_reports are already in scope
                return render_template('report_lost_form.html',
                                       title='发布寻宠启事 - 图片过多',
                                       form_data=form_data,
                                       baidu_map_ak=baidu_map_ak,
                                       recent_found_reports=recent_found_reports)
            # Use current_app to access config within request context
            upload_folder_path = current_app.config.get('UPLOAD_FOLDER')

            if not upload_folder_path:
                flash('服务器上传文件夹配置错误。', 'error')
                return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)

            for file in actual_uploaded_files: # Iterate over the filtered and validated list
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
                        try:
                            compress_image(save_path)
                            current_app.logger.info(f"Successfully compressed uploaded image: {unique_filename} at {save_path}")
                        except Exception as e:
                            current_app.logger.error(f"Error compressing image {unique_filename} at {save_path}: {e}", exc_info=True)
                        # 只保存文件名，不保存完整url
                        photo_urls.append(unique_filename)
                    except Exception as e:
                        flash(f'图片上传失败: {e}', 'error')
                        # Consider if partial success is acceptable or should halt
                        # return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data)

            # --- Create new report object --- 
            try:
                lost_time_dt = datetime.strptime(request.form['lost_time'], '%Y-%m-%dT%H:%M')
            except ValueError:
                 flash('丢失时间格式无效，请使用日期时间选择器。', 'error')
                 return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)
            
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
                    breed=request.form['breed'],
                    color=request.form['color'],
                    gender=request.form['gender'],
                    age=request.form.get('age'),
                    features=request.form['features'],
                    pet_name=request.form.get('pet_name'), # Optional field
                    additional_info=request.form.get('additional_info'), # Optional field
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
                return render_template('report_lost_form.html', title='发布寻宠启事 - 必填项缺失', form_data=form_data, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)
            # --- End Create Report ---

        # If GET request, just render the form
        return render_template('report_lost_form.html', title='发布寻宠启事', form_data={}, baidu_map_ak=baidu_map_ak, recent_found_reports=recent_found_reports)

    # --- Route for submitting Pet Found reports (招领启事) ---
    @app.route('/report/found', methods=['GET', 'POST'])
    def report_found():
        form_data = request.form.to_dict()  # For repopulating form on GET or error
        baidu_map_ak = current_app.config.get('BAIDU_MAP_API_KEY')
        if not baidu_map_ak:
            current_app.logger.warning("BAIDU_MAP_API_KEY for report_found is not set. Map functionality will be affected.")

        # Query recent lost reports for display on the form page (GET or POST error)
        recent_lost_reports = PetLostReport.query.order_by(desc(PetLostReport.created_at)).limit(5).all()

        if request.method == 'POST':
            # --- Handle Photo Uploads (similar to report_lost) ---
            photo_urls = []
            if 'photos' in request.files:
                files = request.files.getlist('photos')
                for file in files[:3]: # Limit to 3 photos
                    if file and file.filename != '' and '.' in file.filename and \
                       file.filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']:
                        filename = secure_filename(str(uuid.uuid4()) + os.path.splitext(file.filename)[1])
                        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
                        try:
                            file.save(file_path)
                            try:
                                compress_image(file_path)
                                current_app.logger.info(f"Successfully compressed uploaded image: {filename} at {file_path}")
                            except Exception as e:
                                current_app.logger.error(f"Error compressing image {filename} at {file_path}: {e}", exc_info=True)
                            photo_urls.append(url_for('static', filename=f'uploads/{filename}', _external=True))
                        except Exception as e:
                            current_app.logger.error(f"Error saving uploaded file: {e}")
                            flash('上传照片时出错，请检查文件或稍后再试。', 'error')
                            return render_template('report_found_form.html', title='发布招领启事 - 必填项缺失', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)
                    elif file.filename != '':  # If file exists but is not allowed
                        _, ext = os.path.splitext(file.filename)
                        allowed_extensions_str = ', '.join(current_app.config['ALLOWED_EXTENSIONS'])
                        flash(f'文件类型 "{ext}" 不被允许。请上传以下类型的文件: {allowed_extensions_str}。', 'error')
                        return render_template('report_found_form.html', title='发布招领启事 - 文件类型错误', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)
            
            # --- Process 'other_breed' --- 
            breed = request.form.get('breed')
            actual_breed = breed
            if breed == '其他品种':
                other_breed_value = request.form.get('other_breed', '').strip()
                if not other_breed_value:
                    flash('选择了“其他品种”但未填写具体品种名称。', 'error')
                    return render_template('report_found_form.html', title='发布招领启事 - 品种错误', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)
                actual_breed = other_breed_value
            elif not breed:  # If breed is optional and not selected, set to None or empty string based on model
                actual_breed = None  # Or '' if your model prefers empty strings for nullable charfields

            # --- Parse Found Time ---
            found_time_str = request.form.get('found_time')
            found_time_dt = None
            if found_time_str:
                try:
                    found_time_dt = datetime.fromisoformat(found_time_str)
                except ValueError:
                    flash('拾获时间格式无效，请使用日期时间选择器。', 'error')
                    return render_template('report_found_form.html', title='发布招领启事 - 时间错误', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)
            else:
                flash('拾获时间是必填项。', 'error')
                return render_template('report_found_form.html', title='发布招领启事 - 时间错误', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)

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
                current_app.logger.warning(f"Invalid latitude/longitude format received for found pet: lat='{latitude}', lon='{longitude}'")
                # Optionally, flash an error message, but map selection should prevent this.
                pass  # Allow submission, coordinates will be null

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
                    latitude=lat_float,
                    longitude=lon_float,
                    _photo_urls=json.dumps(photo_urls) if photo_urls else None  # Store as JSON string
                )
                db.session.add(new_found_report)
                db.session.commit()
                flash('招领启事发布成功！', 'success')
                return redirect(url_for('index'))  # Or a different success page
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Error creating found report: {e}")
                flash('发布招领启事时发生数据库错误，请稍后重试。', 'error')
                return render_template('report_found_form.html', title='发布招领启事 - 错误', form_data=form_data, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)

        # If GET request, just render the form
        return render_template('report_found_form.html', title='发布招领启事', form_data={}, recent_lost_reports=recent_lost_reports, baidu_map_ak=baidu_map_ak)

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

# --- Helper function to create a news (article) response XML for WeChat --- 
def create_news_response(to_user, from_user, articles):
    """
    Creates an XML string for a WeChat news message.
    :param to_user: The recipient's OpenID.
    :param from_user: The sender's (your app's) OpenID/original ToUserName.
    :param articles: A list of article dictionaries. Each dict should have 'title', 'description', 'pic_url', 'url'.
    :return: XML string.
    """
    xml_response = "<xml>"
    xml_response += f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
    xml_response += f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
    xml_response += f"<CreateTime>{int(time.time())}</CreateTime>"
    xml_response += "<MsgType><![CDATA[news]]></MsgType>"
    xml_response += f"<ArticleCount>{len(articles)}</ArticleCount>"
    xml_response += "<Articles>"
    for article in articles:
        xml_response += "<item>"
        xml_response += f"<Title><![CDATA[{article.get('title', '')}]]></Title>"
        xml_response += f"<Description><![CDATA[{article.get('description', '')}]]></Description>"
        xml_response += f"<PicUrl><![CDATA[{article.get('pic_url', '')}]]></PicUrl>"
        xml_response += f"<Url><![CDATA[{article.get('url', '')}]]></Url>"
        xml_response += "</item>"
    xml_response += "</Articles>"
    xml_response += "</xml>"
    return xml_response

if __name__ == '__main__':
    app = create_app()
    # Remember to set FLASK_ENV=development and FLASK_APP=app.py in your environment
    # For production, use a proper WSGI server like Gunicorn or uWSGI
    # Explicitly set host and port
    app.run(host='0.0.0.0', port=5002, debug=True) # debug=True is NOT for production!
