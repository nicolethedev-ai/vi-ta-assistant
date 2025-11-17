# app/auth.py
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required

from werkzeug.security import check_password_hash

from models import User, config  # Import từ models.py

auth = Blueprint("auth", __name__)

try:
    user_password_map = {
        username: details["password"]
        for username, details in config["credentials"]["usernames"].items()
        if "password" in details
    }
except KeyError:
    print("LỖI: config.yaml thiếu 'password'.")
    print("Vui lòng chạy script 'hash_passwords.py' để tạo hash cho mật khẩu.")
    user_password_map = {}
except Exception as e:
    print(f"Lỗi khi đọc config: {e}")
    user_password_map = {}


@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        # Kiểm tra xem username có tồn tại không
        if username in user_password_map:

            hashed_password = user_password_map[username]

            # SỬ DỤNG HÀM CHECK CỦA WERKZEUG
            # Nó sẽ so sánh password (text) người dùng nhập với hash
            if check_password_hash(hashed_password, password):
                # Lấy user từ CSDL (logic này vẫn như cũ)
                user = User.get_by_username(username)
                if user:
                    login_user(user)  # Đăng nhập user
                    return redirect(
                        url_for("chat.index")
                    )  # Chuyển hướng đến trang chat

        flash("Username hoặc password không chính xác.")

    return render_template("login.html")


@auth.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
