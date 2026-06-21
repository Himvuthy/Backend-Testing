from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
import pg8000.dbapi as psycopg2
import boto3
import os
import uuid
from io import BytesIO
from PIL import Image

# Serve React build from dist/ folder
DIST_DIR = os.path.join(os.path.dirname(__file__), 'dist')

app = Flask(__name__, static_folder=DIST_DIR, static_url_path='')
CORS(app)

# ==============================
# DATABASE CONNECTION
# ==============================
def get_db_connection():
    return psycopg2.connect(
        host="acela.proxy.rlwy.net",
        port=42391,
        user="postgres",
        password="TRGQfYWWHMwtolFwadVkjUjDAJIiiXvn",
        database="railway"
    )

# ==============================
# CLOUDFLARE R2 CONFIG
# ==============================
R2_ACCESS_KEY = "351205bf19a9cb1536f7c1e9dd39a83a"
R2_SECRET_KEY = "3cc04f1b903bc155a906858fb194212997e95a6882630c7b41b10952ed535939"
R2_ENDPOINT   = "https://19ab588d250cb7479c593ca7df30e5ff.r2.cloudflarestorage.com"
R2_BUCKET     = "cloud-png-storage"

# Public URL base — you need to set this in Cloudflare R2 > Settings > Public Access
# For now we use the R2.dev subdomain or your custom domain
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "https://pub-7ab8922a9a2c464b8fafa032bca6c666.r2.dev")

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name="auto"
)

# Ensure bucket exists
try:
    s3.head_bucket(Bucket=R2_BUCKET)
except Exception as e:
    try:
        s3.create_bucket(Bucket=R2_BUCKET)
        print(f"Created R2 bucket: {R2_BUCKET}")
    except Exception as create_err:
        print(f"Could not head/create bucket '{R2_BUCKET}' ({create_err}). Assuming it exists and credentials have bucket-level access.")

# ==============================
# IMAGE LIMITS
# ==============================
PROFILE_SIZE = (512, 512)
BANNER_SIZE  = (1327, 177)
MAX_FILE_MB  = 5  # Max upload size in MB

def resize_and_upload(file_storage, target_size, folder):
    """
    Resize an image to exact target_size (width, height),
    convert to WebP, upload to R2, return the object key.
    """
    img = Image.open(file_storage.stream)
    img = img.convert("RGB")

    # Resize with crop-to-fill (cover mode)
    img_ratio = img.width / img.height
    target_ratio = target_size[0] / target_size[1]

    if img_ratio > target_ratio:
        # Image is wider — crop sides
        new_height = img.height
        new_width = int(new_height * target_ratio)
        left = (img.width - new_width) // 2
        img = img.crop((left, 0, left + new_width, img.height))
    else:
        # Image is taller — crop top/bottom
        new_width = img.width
        new_height = int(new_width / target_ratio)
        top = (img.height - new_height) // 2
        img = img.crop((0, top, img.width, top + new_height))

    img = img.resize(target_size, Image.LANCZOS)

    # Save to buffer as WebP
    buffer = BytesIO()
    img.save(buffer, format="WEBP", quality=85)
    buffer.seek(0)

    # Generate unique filename
    filename = f"{folder}/{uuid.uuid4().hex}.webp"

    s3.upload_fileobj(
        buffer,
        R2_BUCKET,
        filename,
        ExtraArgs={"ContentType": "image/webp"}
    )

    return filename

def get_public_url(key):
    """Build the public URL for an R2 object."""
    if R2_PUBLIC_URL:
        return f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
    # Fallback: generate a presigned URL (valid 7 days)
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": R2_BUCKET, "Key": key},
        ExpiresIn=604800
    )

# ==============================
# LOGIN ROUTE
# ==============================
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT e.roleid, u.passwordhash, u.userid
            FROM USERACCOUNT u 
            JOIN ENTITY e ON u.eid = e.eid 
            WHERE u.username = %s
        """, (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user[1], password):
            # Update last login
            cursor.execute("UPDATE USERACCOUNT SET lastlogin = NOW() WHERE userid = %s", (user[2],))
            conn.commit()
            return jsonify({"success": True, "role": user[0], "userId": user[2]})
        else:
            return jsonify({"success": False, "message": "Invalid username or password."}), 401
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# GET USER PROFILE
# ==============================
@app.route('/api/profile/<int:user_id>', methods=['GET'])
def get_profile(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT e.fullname, u.username, u.email, e.phonenumber, e.gender,
                   e.roleid, e.bio, e.dateofbirth, e.createdat, u.lastlogin,
                   u.profilepicture, u.banner, u.userid
            FROM USERACCOUNT u
            JOIN ENTITY e ON u.eid = e.eid
            WHERE u.userid = %s
        """, (user_id,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"success": False, "message": "User not found"}), 404

        profile = {
            "name": row[0],
            "username": row[1],
            "email": row[2],
            "phone": row[3],
            "gender": row[4],
            "role": row[5],
            "bio": row[6],
            "dateOfBirth": str(row[7]) if row[7] else None,
            "createdAt": str(row[8]) if row[8] else None,
            "lastLogin": str(row[9]) if row[9] else None,
            "profilePicture": get_public_url(row[10]) if row[10] else None,
            "banner": get_public_url(row[11]) if row[11] else None,
            "userId": row[12]
        }

        return jsonify({"success": True, "profile": profile})
    except Exception as e:
        print(f"🚨 GET PROFILE ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# UPLOAD PROFILE PICTURE (512x512)
# ==============================
@app.route('/api/profile/<int:user_id>/picture', methods=['POST'])
def upload_profile_picture(user_id):
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "Empty filename"}), 400

    # Check file size
    file.seek(0, 2)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > MAX_FILE_MB:
        return jsonify({"success": False, "message": f"File too large. Max {MAX_FILE_MB}MB"}), 400

    try:
        # Delete old picture from R2 if exists
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT profilepicture FROM USERACCOUNT WHERE userid = %s", (user_id,))
        old = cursor.fetchone()
        if old and old[0]:
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=old[0])
            except:
                pass

        # Resize and upload new picture
        key = resize_and_upload(file, PROFILE_SIZE, "profiles")

        # Update DB
        cursor.execute("UPDATE USERACCOUNT SET profilepicture = %s WHERE userid = %s", (key, user_id))
        conn.commit()

        return jsonify({
            "success": True,
            "url": get_public_url(key),
            "message": "Profile picture updated"
        })
    except Exception as e:
        print(f"🚨 UPLOAD PFP ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# UPLOAD BANNER (1327x177)
# ==============================
@app.route('/api/profile/<int:user_id>/banner', methods=['POST'])
def upload_banner(user_id):
    if 'file' not in request.files:
        return jsonify({"success": False, "message": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"success": False, "message": "Empty filename"}), 400

    file.seek(0, 2)
    size_mb = file.tell() / (1024 * 1024)
    file.seek(0)
    if size_mb > MAX_FILE_MB:
        return jsonify({"success": False, "message": f"File too large. Max {MAX_FILE_MB}MB"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT banner FROM USERACCOUNT WHERE userid = %s", (user_id,))
        old = cursor.fetchone()
        if old and old[0]:
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=old[0])
            except:
                pass

        key = resize_and_upload(file, BANNER_SIZE, "banners")

        cursor.execute("UPDATE USERACCOUNT SET banner = %s WHERE userid = %s", (key, user_id))
        conn.commit()

        return jsonify({
            "success": True,
            "url": get_public_url(key),
            "message": "Banner updated"
        })
    except Exception as e:
        print(f"🚨 UPLOAD BANNER ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# DELETE PROFILE PICTURE
# ==============================
@app.route('/api/profile/<int:user_id>/picture', methods=['DELETE'])
def delete_profile_picture(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT profilepicture FROM USERACCOUNT WHERE userid = %s", (user_id,))
        old = cursor.fetchone()
        if old and old[0]:
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=old[0])
            except:
                pass
        cursor.execute("UPDATE USERACCOUNT SET profilepicture = NULL WHERE userid = %s", (user_id,))
        conn.commit()
        return jsonify({"success": True, "message": "Profile picture removed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# DELETE BANNER
# ==============================
@app.route('/api/profile/<int:user_id>/banner', methods=['DELETE'])
def delete_banner(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT banner FROM USERACCOUNT WHERE userid = %s", (user_id,))
        old = cursor.fetchone()
        if old and old[0]:
            try:
                s3.delete_object(Bucket=R2_BUCKET, Key=old[0])
            except:
                pass
        cursor.execute("UPDATE USERACCOUNT SET banner = NULL WHERE userid = %s", (user_id,))
        conn.commit()
        return jsonify({"success": True, "message": "Banner removed"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# ADMIN STATS ROUTE
# ==============================
@app.route('/api/admin/stats', methods=['GET'])
def get_admin_stats():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM STUDENT")
        total_students = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM BIOMETRIC")
        enrolled = cursor.fetchone()[0]
        
        notEnrolled_students = total_students - enrolled
        
        cursor.execute("SELECT COUNT(*) FROM CLASS")
        classes = cursor.fetchone()[0]
        
        return jsonify({
            "success": True,
            "totalStudents": total_students,
            "classes": classes,      
            "present": enrolled,    
            "absent": notEnrolled_students 
        })
    except Exception as e:
        print(f"🚨 ADMIN STATS DB ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# GET ALL USERS (For User Management Tab)
# ==============================
@app.route('/api/users', methods=['GET'])
def get_users():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT e.eid, e.fullname, r.rolename, u.email, u.username, e.phonenumber 
            FROM ENTITY e
            JOIN USERACCOUNT u ON e.eid = u.eid
            JOIN ROLE r ON e.roleid = r.roleid
        """)
        rows = cursor.fetchall()
        users_list = []
        for row in rows:
            users_list.append({
                "id": row[0],
                "name": row[1] if row[1] else "Unknown",
                "role": row[2].upper(),
                "email": row[3],
                "username": row[4],
                "phone": row[5] or ''
            })
            
        return jsonify({"success": True, "users": users_list}), 200
    except Exception as e:
        print(f"Get users error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# CREATE USER
# ==============================
@app.route('/api/users', methods=['POST'])
def create_user():
    data = request.get_json()
    name = data.get('name', '').strip()
    role = data.get('role', 'Student').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    if not username or not email or not password or not name:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    role_map = {'ADMIN': 1, 'TEACHER': 2, 'STUDENT': 3}
    roleid = role_map.get(role.upper(), 3)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Insert into ENTITY
        cursor.execute("""
            INSERT INTO ENTITY (roleid, fullname, phonenumber, gender, bio, createdat, lastedit)
            VALUES (%s, %s, %s, NULL, NULL, NOW(), NOW())
            RETURNING eid
        """, (roleid, name, phone))
        eid = cursor.fetchone()[0]

        # Hash password and insert into USERACCOUNT
        pwhash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO USERACCOUNT (eid, username, email, passwordhash, lastlogin, profilepicture, banner)
            VALUES (%s, %s, %s, %s, NULL, NULL, NULL)
        """, (eid, username, email, pwhash))

        # Handle student/lecturer lists
        if roleid == 3:
            cursor.execute("INSERT INTO STUDENT (eid) VALUES (%s)", (eid,))
        elif roleid == 2:
            cursor.execute("INSERT INTO LECTURER (eid) VALUES (%s)", (eid,))

        conn.commit()
        return jsonify({"success": True, "id": eid, "message": "User created successfully"}), 201
    except Exception as e:
        print(f"Create user error: {e}")
        if 'conn' in locals():
            conn.rollback()
        err_msg = str(e)
        if "unique constraint" in err_msg.lower():
            if "username" in err_msg.lower():
                return jsonify({"success": False, "message": "Username already exists"}), 409
            if "email" in err_msg.lower():
                return jsonify({"success": False, "message": "Email already exists"}), 409
        return jsonify({"success": False, "error": err_msg}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# UPDATE USER
# ==============================
@app.route('/api/users/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json()
    name = data.get('name', '').strip()
    role = data.get('role', '').strip()
    email = data.get('email', '').strip()
    phone = data.get('phone', '').strip()
    username = data.get('username', '').strip()

    if not name or not role or not email or not username:
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    role_map = {'ADMIN': 1, 'TEACHER': 2, 'STUDENT': 3}
    roleid = role_map.get(role.upper(), 3)

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Update ENTITY
        cursor.execute("""
            UPDATE ENTITY 
            SET fullname = %s, roleid = %s, phonenumber = %s, lastedit = NOW()
            WHERE eid = %s
        """, (name, roleid, phone, user_id))

        # Update USERACCOUNT
        cursor.execute("""
            UPDATE USERACCOUNT 
            SET email = %s, username = %s
            WHERE eid = %s
        """, (email, username, user_id))

        # Synchronize STUDENT / LECTURER helper tables
        if roleid == 3:
            cursor.execute("SELECT 1 FROM STUDENT WHERE eid = %s", (user_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO STUDENT (eid) VALUES (%s)", (user_id,))
            cursor.execute("DELETE FROM LECTURER WHERE eid = %s", (user_id,))
        elif roleid == 2:
            cursor.execute("SELECT 1 FROM LECTURER WHERE eid = %s", (user_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO LECTURER (eid) VALUES (%s)", (user_id,))
            cursor.execute("DELETE FROM STUDENT WHERE eid = %s", (user_id,))
        else:
            cursor.execute("DELETE FROM STUDENT WHERE eid = %s", (user_id,))
            cursor.execute("DELETE FROM LECTURER WHERE eid = %s", (user_id,))

        conn.commit()
        return jsonify({"success": True, "message": "User updated successfully"}), 200
    except Exception as e:
        print(f"Update user error: {e}")
        if 'conn' in locals():
            conn.rollback()
        err_msg = str(e)
        if "unique constraint" in err_msg.lower():
            if "username" in err_msg.lower():
                return jsonify({"success": False, "message": "Username already exists"}), 409
            if "email" in err_msg.lower():
                return jsonify({"success": False, "message": "Email already exists"}), 409
        return jsonify({"success": False, "error": err_msg}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# DELETE USER
# ==============================
@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Clean up R2 files before deleting
        cursor.execute("SELECT profilepicture, banner FROM USERACCOUNT WHERE eid = %s", (user_id,))
        row = cursor.fetchone()
        if row:
            for key in row:
                if key:
                    try:
                        s3.delete_object(Bucket=R2_BUCKET, Key=key)
                    except:
                        pass

        cursor.execute("DELETE FROM USERACCOUNT WHERE eid = %s", (user_id,))
        cursor.execute("DELETE FROM ENTITY WHERE eid = %s", (user_id,))
        conn.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"🚨 DELETE USER ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# GET ONLY STUDENTS (For Biometric Enrollment Tab)
# ==============================
@app.route('/api/students', methods=['GET'])  
def get_students():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT e.eid, e.fullname, u.email, e.gender, e.phonenumber, b.fingerindex 
            FROM ENTITY e
            JOIN ROLE r ON e.roleid = r.roleid
            JOIN USERACCOUNT u ON e.eid = u.eid
            LEFT JOIN STUDENT s ON e.eid = s.eid
            LEFT JOIN BIOMETRIC b ON s.studentid = b.studentid
            WHERE r.rolename = 'Student'
        """)
        rows = cursor.fetchall()
        users_list = []
        
        for row in rows:
            users_list.append({
                "id": row[0],
                "name": row[1] if row[1] else "Unknown",
                "role": "STUDENT", 
                "email": row[2],
                "sex": row[3],
                "phone": row[4],
                "fingerprint_id": row[5]
            })
            
        return jsonify({"success": True, "users": users_list}), 200
    except Exception as e:
        print(f"🚨 GET STUDENTS ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if 'conn' in locals():
            conn.close()

# ==============================
# SERVE REACT FRONTEND
# ==============================
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react(path):
    if path and os.path.exists(os.path.join(DIST_DIR, path)):
        return send_from_directory(DIST_DIR, path)
    return send_from_directory(DIST_DIR, 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
