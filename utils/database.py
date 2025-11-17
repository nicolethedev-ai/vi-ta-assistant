import psycopg2
import os
import json
from typing import List, Optional, Dict
from dotenv import load_dotenv

# Tải biến môi trường (chứa URL kết nối CSDL)
load_dotenv(override=True)
AIVEN_CONNECTION_URL = os.getenv("URL")

def get_db_connection():
    """
    Tạo và trả về một kết nối CSDL PostgreSQL.
    Sử dụng URL kết nối từ biến môi trường.
    """
    try:
        conn = psycopg2.connect(AIVEN_CONNECTION_URL)
        return conn
    except Exception as e:
        print(f"Lỗi kết nối CSDL: {e}")
        return None

# =============================================================================
# CHỨC NĂNG QUẢN LÝ SCHEMA (CẬP NHẬT - BAO GỒM MEMORY_ENTITIES)
# =============================================================================

def create_tables():
    """
    Tạo tất cả các bảng cần thiết (nếu chưa tồn tại) cho ứng dụng.
    BAO GỒM: users, ta_profiles, candidate_profiles, conversations, messages, memory_entities
    """
    commands = (
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            email VARCHAR(255) UNIQUE,
            hashed_password VARCHAR(255),
            role VARCHAR(50) DEFAULT 'TA',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS ta_profiles (
            profile_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL,
            full_name VARCHAR(255),
            preferences JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS candidate_profiles (
            candidate_profile_id SERIAL PRIMARY KEY,
            first_name VARCHAR(255),
            last_name VARCHAR(255),
            contact_email VARCHAR(255) UNIQUE NOT NULL,
            primary_field VARCHAR(255),
            years_of_experience INTEGER,
            source VARCHAR(100),
            profile_data JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS conversations (
            conversation_id SERIAL PRIMARY KEY,
            ta_user_id INTEGER NOT NULL,
            candidate_profile_id INTEGER,
            title VARCHAR(255) DEFAULT 'Cuộc trò chuyện mới',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ta_user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            FOREIGN KEY (candidate_profile_id) REFERENCES candidate_profiles (candidate_profile_id) ON DELETE SET NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            message_id SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL,
            role VARCHAR(50) NOT NULL, -- 'user' or 'assistant'
            content TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id) ON DELETE CASCADE
        );
        """,
        # ✨ NEW: Memory entities table
        """
        CREATE TABLE IF NOT EXISTS memory_entities (
            entity_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name VARCHAR(500) NOT NULL,
            entity_type VARCHAR(100),
            observations TEXT[],
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            UNIQUE(user_id, name)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS cv_documents (
            cv_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            file_name VARCHAR(255) NOT NULL,
            raw_text TEXT,
            analysis_strengths TEXT,
            analysis_weaknesses TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS jd_documents (
            jd_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            jd_title VARCHAR(500) NOT NULL,
            raw_text TEXT,
            analysis_requirements TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_user_id 
        ON memory_entities(user_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_name 
        ON memory_entities(user_id, name);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_type 
        ON memory_entities(user_id, entity_type);
        """
    )
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
            conn.commit()
        print("✅ Tất cả các bảng đã được tạo thành công (bao gồm memory_entities).")
    except Exception as e:
        print(f"❌ Lỗi khi tạo bảng: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def drop_all_tables():
    """
    Xóa tất cả các bảng (DÙNG CẨN THẬN - CHỈ CHO MÔI TRƯỜNG DEV).
    """
    commands = (
        "DROP TABLE IF EXISTS memory_entities CASCADE;",  # New
        "DROP TABLE IF EXISTS messages CASCADE;",
        "DROP TABLE IF EXISTS conversations CASCADE;",
        "DROP TABLE IF EXISTS candidate_profiles CASCADE;",
        "DROP TABLE IF EXISTS ta_profiles CASCADE;",
        "DROP TABLE IF EXISTS users CASCADE;"
    )
    
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
            conn.commit()
        print("✅ Đã xóa tất cả các bảng (bao gồm memory_entities).")
    except Exception as e:
        print(f"❌ Lỗi khi xóa bảng: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


# =============================================================================
# CHỨC NĂNG USER & AUTHENTICATION
# =============================================================================


def get_or_create_user(username, email, role='TA', hashed_password='managed_by_authenticator'):
    """
    Tìm user bằng username (từ streamlit-authenticator).
    Nếu không tìm thấy, tạo user mới trong bảng 'users'.
    Sau đó, đảm bảo một hồ sơ tương ứng (vd: ta_profiles) được tạo.
    Trả về user_id.
    """
    conn = None
    user_id = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL cho get_or_create_user")
            
        with conn.cursor() as cur:
            # 1. Thử tìm user trong bảng 'users'
            cur.execute("SELECT user_id FROM users WHERE username = %s;", (username,))
            result = cur.fetchone()
            
            if result:
                user_id = result[0]
            else:
                # 2. Không tìm thấy, tạo user mới trong bảng 'users'
                sql_insert_user = """
                    INSERT INTO users (username, email, hashed_password, role) 
                    VALUES (%s, %s, %s, %s) 
                    RETURNING user_id;
                """
                # Nếu bạn đã chạy script hash_passwords.py, 
                # giá trị 'hashed_password' nên được truyền vào từ config
                cur.execute(sql_insert_user, (username, email, hashed_password, role))
                user_id = cur.fetchone()[0]
                
            # 3. Đảm bảo hồ sơ (profile) tương ứng tồn tại
            if role == 'TA' or role == 'ADMIN':
                # Kiểm tra xem ta_profile đã tồn tại chưa
                sql_check_profile = "SELECT 1 FROM ta_profiles WHERE user_id = %s;"
                cur.execute(sql_check_profile, (user_id,))
                if not cur.fetchone():
                    # Nếu chưa, tạo ta_profile mới
                    sql_insert_profile = """
                        INSERT INTO ta_profiles (user_id, full_name, preferences) 
                        VALUES (%s, %s, %s);
                    """
                    # Dùng username làm full_name mặc định
                    cur.execute(sql_insert_profile, (user_id, username, json.dumps({}))) 
            
            conn.commit()
            return user_id

    except Exception as e:
        print(f"❌ Lỗi khi get_or_create_user: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

#
# =======================================================================
# HÀM MỚI ĐƯỢC THÊM VÀO (BẮT BUỘC CHO FLASK-LOGIN)
# =======================================================================
#
def get_user_by_id(user_id):
    """
    Lấy thông tin user từ CSDL bằng user_id.
    Hàm này BẮT BUỘC cho Flask-Login's @login_manager.user_loader.
    Nó được gọi trên MỌI request sau khi đã login để tải 'current_user'.
    """
    conn = None
    try:
        conn = get_db_connection() # Sử dụng hàm kết nối hiện có của bạn
        if not conn:
            raise Exception("Không thể kết nối CSDL cho get_user_by_id")
            
        with conn.cursor() as cur:
            # Lấy thông tin cần thiết để tạo User object trong app/models.py
            cur.execute("SELECT user_id, username, email, role FROM users WHERE user_id = %s;", (user_id,))
            user_data = cur.fetchone()
            
            if user_data:
                # Trả về một tuple (id, username, email, role)
                # để class User(UserMixin) trong models.py có thể khởi tạo
                return (user_data[0], user_data[1], user_data[2], user_data[3])
        
        # Nếu không tìm thấy user
        return None
        
    except Exception as e:
        print(f"❌ Lỗi khi get_user_by_id: {e}")
        return None
    finally:
        if conn:
            conn.close()
        
# =============================================================================
# CHỨC NĂNG HỘI THOẠI (CHAT)
# =============================================================================

def create_conversation(ta_user_id, title="New Conversation"):
    """Tạo một cuộc hội thoại mới, liên kết với một TA user."""
    sql = """
        INSERT INTO conversations (ta_user_id, title) 
        VALUES (%s, %s) RETURNING conversation_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (ta_user_id, title))
            chat_id = cur.fetchone()[0]
            conn.commit()
            return chat_id
    except Exception as e:
        print(f"❌ Lỗi khi tạo hội thoại: {e}")
        return None
    finally:
        if conn:
            conn.close()

def load_chat_list(ta_user_id):
    """Tải danh sách các cuộc hội thoại của một TA user."""
    sql = """
        SELECT conversation_id, title, created_at, updated_at 
        FROM conversations 
        WHERE ta_user_id = %s 
        ORDER BY updated_at DESC;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (ta_user_id,))
            rows = cur.fetchall()
            
            # === SỬA ĐỔI ===
            # Chuyển đổi datetime objects thành strings (ISO format)
            # Giữ nguyên cấu trúc list of lists để khớp với chat.js
            serializable_list = []
            for row in rows:
                serializable_list.append([
                    row[0], # id
                    row[1], # title
                    row[2].isoformat() if row[2] else None, # created_at
                    row[3].isoformat() if row[3] else None  # updated_at
                ])
            return serializable_list
            # === KẾT THÚC SỬA ĐỔI ===
            
    except Exception as e:
        print(f"❌ Lỗi khi tải danh sách hội thoại: {e}")
        return []
    finally:
        if conn:
            conn.close()

def load_messages(conversation_id):
    """
    Tải tất cả các tin nhắn của một cuộc hội thoại.
    Trả về dạng list of dict phù hợp với agent.
    """
    sql = """
        SELECT role, content, created_at 
        FROM messages 
        WHERE conversation_id = %s 
        ORDER BY created_at ASC;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (conversation_id,))
            rows = cur.fetchall()
            messages = []
            for row in rows:
                # === SỬA ĐỔI ===
                # Chuyển đổi datetime object thành string (ISO format)
                messages.append({
                    "role": row[0],
                    "content": row[1],
                    "created_at": row[2].isoformat() if row[2] else None
                })
                # === KẾT THÚC SỬA ĐỔI ===
            return messages
    except Exception as e:
        print(f"❌ Lỗi khi tải tin nhắn: {e}")
        return []
    finally:
        if conn:
            conn.close()

def save_message(conversation_id, role, content):
    """
    Lưu một tin nhắn mới (user hoặc assistant) vào CSDL.
    Đồng thời cập nhật 'updated_at' của cuộc hội thoại cha.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            # 1. Thêm tin nhắn mới vào bảng 'messages'
            sql_msg = """
                INSERT INTO messages (conversation_id, role, content) 
                VALUES (%s, %s, %s);
            """
            cur.execute(sql_msg, (conversation_id, role, content))
            
            # 2. Cập nhật timestamp 'updated_at' của bảng 'conversations'
            sql_conv = """
                UPDATE conversations 
                SET updated_at = CURRENT_TIMESTAMP 
                WHERE conversation_id = %s;
            """
            cur.execute(sql_conv, (conversation_id,))
            
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi lưu tin nhắn: {e}")
    finally:
        if conn:
            conn.close()

def delete_conversation(conversation_id):
    """
    Xóa một cuộc hội thoại.
    (Các tin nhắn liên quan sẽ tự động bị xóa nhờ 'ON DELETE CASCADE').
    """
    sql = "DELETE FROM conversations WHERE conversation_id = %s;"
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (conversation_id,))
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi xóa hội thoại: {e}")
    finally:
        if conn:
            conn.close()

def update_conversation_title(conversation_id, new_title):
    """Cập nhật tiêu đề của một cuộc hội thoại."""
    sql = """
        UPDATE conversations 
        SET title = %s, updated_at = CURRENT_TIMESTAMP 
        WHERE conversation_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (new_title, conversation_id))
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi cập nhật tiêu đề: {e}")
    finally:
        if conn:
            conn.close()

# =============================================================================
# CHỨC NĂNG TALENT ACQUISITION (TA) & ỨNG VIÊN
# =============================================================================

def save_ta_preference(ta_user_id, preferences_dict):
    """Lưu/Cập nhật preferences (dạng JSON) cho TA user vào bảng 'ta_profiles'."""
    sql = "UPDATE ta_profiles SET preferences = %s WHERE user_id = %s;"
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (json.dumps(preferences_dict), ta_user_id))
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi lưu preferences: {e}")
    finally:
        if conn:
            conn.close()

def load_ta_preferences(ta_user_id):
    """Tải preferences (dạng JSON) của một TA user từ 'ta_profiles'."""
    sql = "SELECT preferences FROM ta_profiles WHERE user_id = %s;"
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (ta_user_id,))
            result = cur.fetchone()
            if result and result[0]:
                return result[0]
        return {}
    except Exception as e:
        print(f"❌ Lỗi khi tải preferences: {e}")
        return {}
    finally:
        if conn:
            conn.close()

def create_candidate_profile(first_name, last_name, contact_email, field, 
                               years_exp, source, profile_data={}):
    """
    Tạo một hồ sơ ứng viên mới trong bảng 'candidate_profiles'.
    profile_data là một dict chứa các link (GitHub, LinkedIn) và thông tin khác.
    """
    sql = """
        INSERT INTO candidate_profiles (
            first_name, last_name, contact_email, primary_field, 
            years_of_experience, source, profile_data
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (contact_email) DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            primary_field = EXCLUDED.primary_field,
            years_of_experience = EXCLUDED.years_of_experience,
            source = EXCLUDED.source,
            profile_data = candidate_profiles.profile_data || EXCLUDED.profile_data,
            updated_at = CURRENT_TIMESTAMP
        RETURNING candidate_profile_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (
                first_name, last_name, contact_email, field, 
                years_exp, source, json.dumps(profile_data)
            ))
            candidate_id = cur.fetchone()[0]
            conn.commit()
            return candidate_id
    except Exception as e:
        print(f"❌ Lỗi khi tạo/cập nhật ứng viên: {e}")
        return None
    finally:
        if conn:
            conn.close()

def get_candidate_by_email(email):
    """Tìm một hồ sơ ứng viên bằng email liên hệ."""
    sql = "SELECT * FROM candidate_profiles WHERE contact_email = %s;"
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (email,))
            return cur.fetchone()
    except Exception as e:
        print(f"❌ Lỗi khi tìm ứng viên bằng email: {e}")
        return None
    finally:
        if conn:
            conn.close()

def link_candidate_to_conversation(conversation_id, candidate_profile_id):
    """Gán một ứng viên vào một cuộc hội thoại (để biết đang chat về ai)."""
    sql = """
        UPDATE conversations 
        SET candidate_profile_id = %s 
        WHERE conversation_id = %s;
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(sql, (candidate_profile_id, conversation_id))
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi khi gán ứng viên vào hội thoại: {e}")
    finally:
        if conn:
            conn.close()

# =============================================================================
# MEMORY CRUD OPERATIONS
# =============================================================================

def create_memory_tables():
    """
    Tạo bảng memory_entities để lưu trữ memory thay thế cho file JSON
    Schema tương thích với MCP memory server format
    """
    commands = (
        """
        CREATE TABLE IF NOT EXISTS memory_entities (
            entity_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name VARCHAR(500) NOT NULL,
            entity_type VARCHAR(100),
            observations TEXT[],
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE,
            UNIQUE(user_id, name)
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_user_id 
        ON memory_entities(user_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_name 
        ON memory_entities(user_id, name);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_memory_entities_type 
        ON memory_entities(user_id, entity_type);
        """
    )
    
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            for command in commands:
                cur.execute(command)
            conn.commit()
        print("✅ Memory tables created successfully")
    except Exception as e:
        print(f"❌ Error creating memory tables: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

def create_memory_entities(
    user_id: int,
    entities: List[Dict[str, any]]
) -> Dict[str, any]:
    """
    Tạo hoặc cập nhật memory entities trong database
    
    Args:
        user_id: ID của user (TA)
        entities: List of entity dictionaries với format:
            [
                {
                    "name": "entity_name",
                    "entityType": "person|job_opening|preference|...",
                    "observations": ["observation1", "observation2"]
                }
            ]
    
    Returns:
        Dictionary với status và chi tiết các entities đã tạo/cập nhật
    """
    conn = None
    created_entities = []
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            for entity in entities:
                name = entity.get("name", "")
                entity_type = entity.get("entityType", "general")
                observations = entity.get("observations", [])
                
                # Kiểm tra entity đã tồn tại chưa
                cur.execute(
                    "SELECT entity_id, observations FROM memory_entities WHERE user_id = %s AND name = %s",
                    (user_id, name)
                )
                existing = cur.fetchone()
                
                if existing:
                    # UPDATE: Merge observations mới vào existing
                    entity_id, existing_obs = existing
                    merged_observations = list(set(existing_obs + observations))  # Remove duplicates
                    
                    cur.execute(
                        """
                        UPDATE memory_entities 
                        SET observations = %s, 
                            entity_type = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE entity_id = %s
                        RETURNING entity_id, name, entity_type, observations, created_at, updated_at
                        """,
                        (merged_observations, entity_type, entity_id)
                    )
                else:
                    # INSERT: Tạo entity mới
                    cur.execute(
                        """
                        INSERT INTO memory_entities (user_id, name, entity_type, observations)
                        VALUES (%s, %s, %s, %s)
                        RETURNING entity_id, name, entity_type, observations, created_at, updated_at
                        """,
                        (user_id, name, entity_type, observations)
                    )
                
                result = cur.fetchone()
                created_entities.append({
                    "entity_id": result[0],
                    "name": result[1],
                    "entityType": result[2],
                    "observations": result[3],
                    "created_at": result[4].isoformat() if result[4] else None,
                    "updated_at": result[5].isoformat() if result[5] else None
                })
            
            conn.commit()
        
        return {
            "success": True,
            "message": f"Created/updated {len(created_entities)} entities",
            "entities": created_entities
        }
    
    except Exception as e:
        print(f"❌ Error creating memory entities: {e}")
        if conn:
            conn.rollback()
        return {
            "success": False,
            "error": str(e),
            "entities": []
        }
    finally:
        if conn:
            conn.close()


def search_memory_entities(
    user_id: int,
    query: str,
    entity_type: Optional[str] = None
) -> List[Dict[str, any]]:
    """
    Tìm kiếm memory entities theo query string
    
    Args:
        user_id: ID của user
        query: Search query (tìm trong name và observations)
        entity_type: Optional filter by entity type
    
    Returns:
        List of matching entities
    """
    conn = None
    results = []
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            if entity_type:
                # Search with entity type filter
                sql = """
                    SELECT entity_id, name, entity_type, observations, created_at, updated_at
                    FROM memory_entities
                    WHERE user_id = %s 
                    AND entity_type = %s
                    AND (
                        name ILIKE %s 
                        OR EXISTS (
                            SELECT 1 FROM unnest(observations) AS obs 
                            WHERE obs ILIKE %s
                        )
                    )
                    ORDER BY updated_at DESC
                """
                search_pattern = f"%{query}%"
                cur.execute(sql, (user_id, entity_type, search_pattern, search_pattern))
            else:
                # Search without entity type filter
                sql = """
                    SELECT entity_id, name, entity_type, observations, created_at, updated_at
                    FROM memory_entities
                    WHERE user_id = %s 
                    AND (
                        name ILIKE %s 
                        OR EXISTS (
                            SELECT 1 FROM unnest(observations) AS obs 
                            WHERE obs ILIKE %s
                        )
                    )
                    ORDER BY updated_at DESC
                """
                search_pattern = f"%{query}%"
                cur.execute(sql, (user_id, search_pattern, search_pattern))
            
            rows = cur.fetchall()
            for row in rows:
                results.append({
                    "entity_id": row[0],
                    "name": row[1],
                    "entityType": row[2],
                    "observations": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None
                })
        
        return results
    
    except Exception as e:
        print(f"❌ Error searching memory entities: {e}")
        return []
    finally:
        if conn:
            conn.close()


def list_memory_entities(
    user_id: int,
    entity_type: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, any]]:
    """
    Liệt kê tất cả memory entities của user
    
    Args:
        user_id: ID của user
        entity_type: Optional filter by entity type
        limit: Maximum number of results
    
    Returns:
        List of entities
    """
    conn = None
    results = []
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            if entity_type:
                sql = """
                    SELECT entity_id, name, entity_type, observations, created_at, updated_at
                    FROM memory_entities
                    WHERE user_id = %s AND entity_type = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                """
                cur.execute(sql, (user_id, entity_type, limit))
            else:
                sql = """
                    SELECT entity_id, name, entity_type, observations, created_at, updated_at
                    FROM memory_entities
                    WHERE user_id = %s
                    ORDER BY updated_at DESC
                    LIMIT %s
                """
                cur.execute(sql, (user_id, limit))
            
            rows = cur.fetchall()
            for row in rows:
                results.append({
                    "entity_id": row[0],
                    "name": row[1],
                    "entityType": row[2],
                    "observations": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None
                })
        
        return results
    
    except Exception as e:
        print(f"❌ Error listing memory entities: {e}")
        return []
    finally:
        if conn:
            conn.close()


def delete_memory_entities(
    user_id: int,
    entity_names: List[str]
) -> Dict[str, any]:
    """
    Xóa memory entities theo name
    
    Args:
        user_id: ID của user
        entity_names: List of entity names to delete
    
    Returns:
        Dictionary with deletion status
    """
    conn = None
    deleted_count = 0
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            for name in entity_names:
                cur.execute(
                    "DELETE FROM memory_entities WHERE user_id = %s AND name = %s",
                    (user_id, name)
                )
                deleted_count += cur.rowcount
            
            conn.commit()
        
        return {
            "success": True,
            "message": f"Deleted {deleted_count} entities",
            "deleted_count": deleted_count
        }
    
    except Exception as e:
        print(f"❌ Error deleting memory entities: {e}")
        if conn:
            conn.rollback()
        return {
            "success": False,
            "error": str(e),
            "deleted_count": 0
        }
    finally:
        if conn:
            conn.close()


def get_memory_entity_by_name(
    user_id: int,
    entity_name: str
) -> Optional[Dict[str, any]]:
    """
    Lấy một memory entity cụ thể theo name
    
    Args:
        user_id: ID của user
        entity_name: Name of entity to retrieve
    
    Returns:
        Entity dictionary or None
    """
    conn = None
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT entity_id, name, entity_type, observations, created_at, updated_at
                FROM memory_entities
                WHERE user_id = %s AND name = %s
                """,
                (user_id, entity_name)
            )
            row = cur.fetchone()
            
            if row:
                return {
                    "entity_id": row[0],
                    "name": row[1],
                    "entityType": row[2],
                    "observations": row[3],
                    "created_at": row[4].isoformat() if row[4] else None,
                    "updated_at": row[5].isoformat() if row[5] else None
                }
        
        return None
    
    except Exception as e:
        print(f"❌ Error getting memory entity: {e}")
        return None
    finally:
        if conn:
            conn.close()


# =============================================================================
# CHỨC NĂNG LƯU TRỮ CV & JD (MỚI)
# =============================================================================

def save_cv_document(user_id: int, file_name: str, raw_text: str) -> int:
    """
    Lưu nội dung text thô của CV vào CSDL.
    Trả về ID của CV mới được tạo.
    """
    sql = """
        INSERT INTO cv_documents (user_id, file_name, raw_text)
        VALUES (%s, %s, %s)
        RETURNING cv_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, file_name, raw_text))
            cv_id = cur.fetchone()[0]
            conn.commit()
            return cv_id
    except Exception as e:
        print(f"❌ Lỗi khi lưu CV document: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()

def save_jd_document(user_id: int, jd_title: str, raw_text: str) -> int:
    """
    Lưu nội dung text thô của JD vào CSDL.
    Trả về ID của JD mới được tạo.
    """
    sql = """
        INSERT INTO jd_documents (user_id, jd_title, raw_text)
        VALUES (%s, %s, %s)
        RETURNING jd_id;
    """
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(sql, (user_id, jd_title, raw_text))
            jd_id = cur.fetchone()[0]
            conn.commit()
            return jd_id
    except Exception as e:
        print(f"❌ Lỗi khi lưu JD document: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if conn:
            conn.close()




# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def clear_all_user_memories(user_id: int) -> Dict[str, any]:
    """
    Xóa tất cả memory entities của một user
    CẢNH BÁO: Sử dụng cẩn thận!
    
    Args:
        user_id: ID của user
    
    Returns:
        Dictionary with deletion status
    """
    conn = None
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM memory_entities WHERE user_id = %s",
                (user_id,)
            )
            deleted_count = cur.rowcount
            conn.commit()
        
        return {
            "success": True,
            "message": f"Cleared all memories for user {user_id}",
            "deleted_count": deleted_count
        }
    
    except Exception as e:
        print(f"❌ Error clearing user memories: {e}")
        if conn:
            conn.rollback()
        return {
            "success": False,
            "error": str(e),
            "deleted_count": 0
        }
    finally:
        if conn:
            conn.close()


def get_memory_stats(user_id: int) -> Dict[str, any]:
    """
    Lấy thống kê về memory entities của user
    
    Args:
        user_id: ID của user
    
    Returns:
        Dictionary with statistics
    """
    conn = None
    
    try:
        conn = get_db_connection()
        if not conn:
            raise Exception("Không thể kết nối CSDL")
        with conn.cursor() as cur:
            # Total entities
            cur.execute(
                "SELECT COUNT(*) FROM memory_entities WHERE user_id = %s",
                (user_id,)
            )
            total_entities = cur.fetchone()[0]
            
            # Entities by type
            cur.execute(
                """
                SELECT entity_type, COUNT(*) 
                FROM memory_entities 
                WHERE user_id = %s 
                GROUP BY entity_type
                """,
                (user_id,)
            )
            by_type = {row[0]: row[1] for row in cur.fetchall()}
            
            # Most recent update
            cur.execute(
                """
                SELECT MAX(updated_at) 
                FROM memory_entities 
                WHERE user_id = %s
                """,
                (user_id,)
            )
            last_updated = cur.fetchone()[0]
        
        return {
            "total_entities": total_entities,
            "by_type": by_type,
            "last_updated": last_updated.isoformat() if last_updated else None
        }
    
    except Exception as e:
        print(f"❌ Error getting memory stats: {e}")
        return {
            "total_entities": 0,
            "by_type": {},
            "last_updated": None
        }
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    """
    Cho phép chạy file này như một script để khởi tạo hoặc xóa CSDL.
    Cách dùng:
    1. Khởi tạo bảng: python database.py
    2. Xóa tất cả bảng: python database.py drop
    """
    import sys

    # Kiểm tra xem có đối số 'drop' không
    if len(sys.argv) > 1 and sys.argv[1] == 'drop':
        print("⚠️  CẢNH BÁO: BẠN SẮP XÓA TẤT CẢ CÁC BẢNG! ⚠️")
        confirm = input("Nhập 'DELETE' để xác nhận: ")
        if confirm == 'DELETE':
            print("Đang xóa tất cả các bảng...")
            try:
                drop_all_tables()
                print("="*50)
                print("✅ Đã xóa sạch CSDL.")
                print("="*50)
            except Exception as e:
                print(f"❌ Lỗi khi xóa CSDL: {e}")
        else:
            print("Đã hủy. Không có gì bị xóa.")
    
    # Mặc định: Khởi tạo
    else:
        print("Đang kết nối tới CSDL và tạo bảng...")
        try:
            create_tables()
            print("="*50)
            print("✅ Hoàn tất! CSDL đã sẵn sàng (bao gồm memory_entities).")
            print("="*50)
        except Exception as e:
            print(f"❌ Lỗi nghiêm trọng khi khởi tạo CSDL: {e}")
            sys.exit(1)