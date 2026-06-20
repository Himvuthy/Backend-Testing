from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import check_password_hash
import psycopg2
import os

app = Flask(__name__)
CORS(app)

def get_db_connection():
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        dbname=os.environ["PGDATABASE"]
    )

# -------------------------
# ROOT
# -------------------------

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "source": "server.py"
    })

# -------------------------
# LOGIN
# -------------------------

@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json()

        username = data["username"]
        password = data["password"]

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT e.roleid, u.passwordhash
            FROM USERACCOUNT u
            JOIN ENTITY e ON u.eid = e.eid
            WHERE u.username = %s
        """, (username,))

        user = cur.fetchone()

        cur.close()
        conn.close()

        if not user:
            return jsonify({
                "success": False,
                "message": "User not found"
            }), 401

        if check_password_hash(user[1], password):
            return jsonify({
                "success": True,
                "role": user[0]
            })

        return jsonify({
            "success": False,
            "message": "Wrong password"
        }), 401

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# DASHBOARD STATS
# -------------------------

@app.route("/api/admin/stats")
def admin_stats():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM STUDENT")
        total_students = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM CLASS")
        total_classes = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM BIOMETRIC")
        enrolled = cur.fetchone()[0]

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "totalStudents": total_students,
            "classes": total_classes,
            "present": enrolled,
            "absent": total_students - enrolled
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# ALL USERS
# -------------------------

@app.route("/api/users")
def users():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                e.eid,
                e.fullname,
                r.rolename,
                u.email
            FROM ENTITY e
            LEFT JOIN USERACCOUNT u ON e.eid = u.eid
            JOIN ROLE r ON e.roleid = r.roleid
            ORDER BY e.eid
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "users": [
                {
                    "id": row[0],
                    "name": row[1],
                    "role": row[2],
                    "email": row[3]
                }
                for row in rows
            ]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# UPDATE USER
# -------------------------

@app.route("/api/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    try:
        data = request.get_json()

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE ENTITY
            SET fullname = %s,
                lastedit = CURRENT_DATE
            WHERE eid = %s
        """, (
            data["name"],
            user_id
        ))

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            "success": True
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# DELETE USER
# -------------------------

@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM USERACCOUNT WHERE eid = %s",
            (user_id,)
        )

        cur.execute(
            "DELETE FROM STUDENT WHERE eid = %s",
            (user_id,)
        )

        cur.execute(
            "DELETE FROM LECTURER WHERE eid = %s",
            (user_id,)
        )

        cur.execute(
            "DELETE FROM ENTITY WHERE eid = %s",
            (user_id,)
        )

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({
            "success": True
        })

    except Exception as e:
        conn.rollback()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# STUDENTS / BIOMETRIC PAGE
# -------------------------

@app.route("/api/students")
def students():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                s.studentid,
                e.fullname,
                u.email,
                e.gender,
                e.phonenumber,
                b.fingerindex
            FROM STUDENT s
            JOIN ENTITY e
                ON s.eid = e.eid
            LEFT JOIN USERACCOUNT u
                ON e.eid = u.eid
            LEFT JOIN BIOMETRIC b
                ON s.studentid = b.studentid
            ORDER BY e.fullname
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "users": [
                {
                    "id": row[0],
                    "name": row[1],
                    "email": row[2],
                    "sex": row[3],
                    "phone": row[4],
                    "fingerprint_id": row[5]
                }
                for row in rows
            ]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# CLASSES
# -------------------------

@app.route("/api/classes")
def classes():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                c.classid,
                c.classname,
                c.classcode,
                m.majorname
            FROM CLASS c
            JOIN MAJOR m
                ON c.majorid = m.majorid
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "classes": [
                {
                    "id": r[0],
                    "name": r[1],
                    "code": r[2],
                    "major": r[3]
                }
                for r in rows
            ]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

# -------------------------
# DEVICES
# -------------------------

@app.route("/api/devices")
def devices():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                deviceid,
                devicename,
                location,
                lastseen
            FROM DEVICE
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "devices": [
                {
                    "id": r[0],
                    "name": r[1],
                    "location": r[2],
                    "lastseen": str(r[3])
                }
                for r in rows
            ]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
