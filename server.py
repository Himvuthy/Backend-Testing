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

@app.route("/")
def home():
    return jsonify({"status": "online"})

@app.route("/api/login", methods=["POST"])
def login():
    try:
        data = request.get_json()

        username = data.get("username")
        password = data.get("password")

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

@app.route("/api/admin/stats")
def admin_stats():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM STUDENT")
        total_students = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM BIOMETRIC")
        enrolled = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM CLASS")
        classes = cur.fetchone()[0]

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "totalStudents": total_students,
            "classes": classes,
            "present": enrolled,
            "absent": total_students - enrolled
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/users")
def users():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT e.eid, e.fullname, r.rolename, u.email
            FROM ENTITY e
            JOIN USERACCOUNT u ON e.eid = u.eid
            JOIN ROLE r ON e.roleid = r.roleid
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "users": [
                {
                    "id": r[0],
                    "name": r[1],
                    "role": r[2],
                    "email": r[3]
                }
                for r in rows
            ]
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute(
            "DELETE FROM USERACCOUNT WHERE eid=%s",
            (user_id,)
        )

        cur.execute(
            "DELETE FROM ENTITY WHERE eid=%s",
            (user_id,)
        )

        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/api/students")
def students():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT e.eid,
                   e.fullname,
                   u.email,
                   e.gender,
                   e.phonenumber,
                   b.fingerindex
            FROM ENTITY e
            JOIN ROLE r ON e.roleid = r.roleid
            JOIN USERACCOUNT u ON e.eid = u.eid
            LEFT JOIN STUDENT s ON e.eid = s.eid
            LEFT JOIN BIOMETRIC b ON s.studentid = b.studentid
            WHERE r.rolename = 'Student'
        """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        return jsonify({
            "success": True,
            "users": [
                {
                    "id": r[0],
                    "name": r[1],
                    "email": r[2],
                    "sex": r[3],
                    "phone": r[4],
                    "fingerprint_id": r[5]
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
    app.run(host="0.0.0.0", port=5000)