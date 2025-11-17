import os
from utils.database import create_tables

import yaml
from flask import Flask
from flask_login import LoginManager
from flask_caching import Cache
from yaml.loader import SafeLoader

from models import User  # Chúng ta sẽ tạo file này

# Tải biến môi trường (quan trọng, phải tải trước khi kết nối CSDL)
from dotenv import load_dotenv
load_dotenv(override=True)


# Tải config giống như bạn đã làm
with open("config.yaml") as file:
    app_config = yaml.load(file, Loader=SafeLoader)

cache = Cache(config={'CACHE_TYPE': 'SimpleCache'})
login_manager = LoginManager()
login_manager.login_view = 'auth.login'  # Chuyển hướng đến route login nếu chưa đăng nhập

def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "MỘT_SECRET_KEY_RẤT_MẠNH_VÀ_BÍ_MẬT"
    
    # Khởi tạo extensions
    login_manager.init_app(app)
    cache.init_app(app)

    # Hàm này của Flask-Login cần để biết cách tải user từ session
    @login_manager.user_loader
    def load_user(user_id):
        # Chúng ta cần một cách để lấy user bằng ID
        # User.get(user_id) là một hàm giả định
        return User.get(user_id)

    # Đăng ký Blueprints (các file route)
    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    from .chat import chat as chat_blueprint
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

