import os
from utils.database import create_tables

import yaml
from flask import Flask
from flask_login import LoginManager
from flask_caching import Cache
from yaml.loader import SafeLoader

from models import User  # Chúng ta sẽ tạo file này
from extensions import cache, login_manager

# Tải biến môi trường (quan trọng, phải tải trước khi kết nối CSDL)
from dotenv import load_dotenv
load_dotenv(override=True)


# Tải config giống như bạn đã làm
with open("config.yaml") as file:
    app_config = yaml.load(file, Loader=SafeLoader)


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "MỘT_SECRET_KEY_RẤT_MẠNH_VÀ_BÍ_MẬT"
    
    # Thêm config cache vào app.config
    app.config["CACHE_TYPE"] = "SimpleCache"
    
    # Khởi tạo extensions
    login_manager.init_app(app)
    cache.init_app(app) # Dòng này vẫn giữ nguyên

    @login_manager.user_loader
    def load_user(user_id):
        return User.get(user_id)

    # Đăng ký Blueprints
    from auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from chat import chat as chat_blueprint # Dòng 44 của bạn
    app.register_blueprint(chat_blueprint)

    return app


if __name__ == "__main__":
    # 1. Đảm bảo các bảng CSDL tồn tại
    # Đây là bước quan trọng mà bạn đang thiếu
    print("Initializing database...")
    try:
        create_tables()
        print("Database tables checked/created successfully.")
    except Exception as e:
        print(f"CRITICAL ERROR: Could not initialize database tables: {e}")
        # Bạn có thể quyết định thoát ứng dụng nếu không thể tạo bảng
        # import sys
        # sys.exit(1)

    # 2. Tạo và chạy ứng dụng Flask
    app = create_app()
    
    # Lấy port từ biến môi trường hoặc dùng port 5000 mặc định
    port = int(os.environ.get("PORT", 5050))
    
    print(f"Starting Flask app on http://localhost:{port}...")
    # Chạy app với debug=True để xem lỗi chi tiết
    app.run(host="0.0.0.0", port=port, debug=True)

