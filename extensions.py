from flask_caching import Cache
from flask_login import LoginManager

# Chỉ khởi tạo đối tượng, không liên kết với app
cache = Cache()
login_manager = LoginManager()

# Thiết lập login_view ở đây
login_manager.login_view = 'auth.login'