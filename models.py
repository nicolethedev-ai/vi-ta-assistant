# app/models.py
from flask_login import UserMixin
import yaml
from yaml.loader import SafeLoader
import utils.database as db # Import DB của bạn

# Tải config credentials
with open("config.yaml") as file:
    config = yaml.load(file, Loader=SafeLoader)
    credentials = config.get("credentials", {}).get("usernames", {})

class User(UserMixin):
    def __init__(self, id, username, email, role):
        self.id = id
        self.username = username
        self.email = email
        self.role = role

    @staticmethod
    def get(user_id):
        """Lấy user từ CSDL bằng ID (cho Flask-Login)"""
        # Bạn cần implement hàm 'db.get_user_by_id' trong utils/database.py
        user_data = db.get_user_by_id(user_id) # Giả định hàm này trả về (id, username, email, role)
        if user_data:
            return User(id=user_data[0], username=user_data[1], email=user_data[2], role=user_data[3])
        return None

    @staticmethod
    def get_by_username(username):
        """Lấy user từ CSDL bằng username (cho việc login)"""
        # Đây là phần bạn đã làm trong main.py
        user_details = credentials.get(username)
        if user_details:
            # Lấy hoặc tạo user và lấy ID
            user_id = db.get_or_create_user(
                username=username,
                email=user_details.get("email"),
                role=user_details.get("roles", ["TA"])[0]
            )
            if user_id:
                return User(id=user_id, username=username, email=user_details.get("email"), role=user_details.get("roles", ["TA"])[0])
        return None
