from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response
import psycopg2
import psycopg2.extras
import os
import json
import csv
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'wfa-secret-x9k2p')

ADMIN_PASSWORD = '662997'

def get_db():
    return psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require')

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS submissions (
            id SERIAL PRIMARY KEY,
            phone VARCHAR(20) UNIQUE NOT NULL,
            data JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            completed BOOLEAN DEFAULT FALSE
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# ── Form routes ──────────────────────────────────────────────────

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/enter', methods=['POST'])
def enter():
    phone = request.form.get('phone', '').strip()
    if not phone:
        return render_template('landing.html', error='請輸入手機號碼')
    session['phone'] = phone
    return redirect(url_for('form'))

@app.route('/form')
def form():
    if 'phone' not in session:
        return redirect(url_for('landing'))
    return render_template('form.html', phone=session['phone'])

@app.route('/api/save', methods=['POST'])
def api_save():
    if 'phone' not in session:
        return jsonify({'ok': False, 'error': 'no session'})
    phone = session['phone']
    data = request.get_json()
    try:
        init_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO submissions (phone, data, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (phone) DO UPDATE SET data = %s, updated_at = NOW()
        ''', (phone, json.dumps(data), json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/complete', methods=['POST'])
def api_complete():
    if 'phone' not in session:
        return jsonify({'ok': False})
    phone = session['phone']
    data = request.get_json()
    try:
        init_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO submissions (phone, data, updated_at, completed)
            VALUES (%s, %s, NOW(), TRUE)
            ON CONFLICT (phone) DO UPDATE SET data = %s, updated_at = NOW(), completed = TRUE
        ''', (phone, json.dumps(data), json.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/load')
def api_load():
    if 'phone' not in session:
        return jsonify({'ok': False})
    phone = session['phone']
    try:
        init_db()
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute('SELECT data FROM submissions WHERE phone = %s', (phone,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row['data']:
            return jsonify({'ok': True, 'data': row['data']})
        return jsonify({'ok': True, 'data': {}})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── Admin routes ─────────────────────────────────────────────────

@app.route('/admin', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_list'))
        return render_template('admin_login.html', error='密碼錯誤')
    if session.get('admin'):
        return redirect(url_for('admin_list'))
    return render_template('admin_login.html')

@app.route('/admin/list')
def admin_list():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, phone, created_at, updated_at, completed,
               data->>'p0_name' as name,
               data->>'p0_dept' as dept,
               data->>'p0_title' as title
        FROM submissions ORDER BY updated_at DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('admin_list.html', rows=rows)

@app.route('/admin/view/<int:sub_id>')
def admin_view(sub_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT * FROM submissions WHERE id = %s', (sub_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return '找不到資料', 404
    data_json = json.dumps(row['data'], ensure_ascii=False, indent=2)
    return render_template('admin_detail.html', row=row, data_json=data_json)

@app.route('/admin/export/json')
def export_json():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT phone, data, created_at, updated_at, completed FROM submissions ORDER BY updated_at DESC')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for r in rows:
        result.append({
            'phone': r['phone'],
            'completed': r['completed'],
            'submitted_at': r['updated_at'].isoformat() if r['updated_at'] else None,
            'data': r['data']
        })
    filename = f'workflow_export_{datetime.now().strftime("%Y%m%d")}.json'
    return Response(
        json.dumps(result, ensure_ascii=False, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/admin/export/csv')
def export_csv():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute('SELECT phone, data, updated_at, completed FROM submissions ORDER BY updated_at DESC')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['手機號碼', '姓名', '部門', '職稱', '完成狀態', '最後更新'])
    for r in rows:
        d = r['data'] or {}
        writer.writerow([
            r['phone'],
            d.get('p0_name', ''),
            d.get('p0_dept', ''),
            d.get('p0_title', ''),
            '已完成' if r['completed'] else '填寫中',
            r['updated_at'].strftime('%Y-%m-%d %H:%M') if r['updated_at'] else ''
        ])
    filename = f'workflow_export_{datetime.now().strftime("%Y%m%d")}.csv'
    return Response(
        '\ufeff' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

try:
    init_db()
except Exception as e:
    print(f"init_db error: {e}")

if __name__ == '__main__':
    app.run(debug=True)
