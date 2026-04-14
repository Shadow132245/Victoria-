import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

# سحب البيانات السرية من إعدادات Vercel Environment Variables
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
MONGO_URI = os.environ.get("MONGO_URI")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# تهيئة الذكاء الاصطناعي
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-pro')

# تهيئة قاعدة البيانات
db_collection = None
if MONGO_URI:
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client['victoria_db']
        db_collection = db['contributions']
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")

def check_content_with_ai(text):
    if not GEMINI_API_KEY:
        return True # السماح بالنص إذا لم يتم إعداد المفتاح بعد
    try:
        prompt = f"""
        أنت مشرف محتوى مصري حازم في سيرفر ديسكورد.
        حدد إذا كان النص يحتوي على شتائم أو ألفاظ مسيئة بالعامية المصرية أو الفرانكو.
        إذا كان محترماً أجب: مقبول
        إذا كان مسيئاً أجب: مرفوض
        النص: "{text}"
        """
        response = model.generate_content(prompt)
        return "مقبول" in response.text.strip()
    except Exception:
        return False # رفض كإجراء وقائي عند فشل الـ AI

@app.route('/api/auth/discord', methods=['POST'])
def discord_auth():
    code = request.json.get('code')
    if not code: return jsonify({'error': 'No code provided'}), 400

    # تبديل الكود بالتوكن من ديسكورد
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    token_resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    if 'error' in token_resp.json(): return jsonify({'error': 'Discord Auth Failed'}), 400
    
    access_token = token_resp.json()['access_token']

    # جلب بيانات العضو
    user_resp = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'})
    user_data = user_resp.json()
    
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png" if user_data.get('avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"

    return jsonify({
        'status': 'success',
        'user': {'id': user_data['id'], 'username': user_data['global_name'] or user_data['username'], 'avatar': avatar_url}
    }), 200


@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    if not data.get('content') or not data.get('username'):
        return jsonify({'error': 'بيانات ناقصة'}), 400

    if not check_content_with_ai(data['content']):
        return jsonify({'status': 'rejected', 'message': 'عذراً، النص يحتوي على كلمات غير لائقة.'}), 406

    if db_collection is not None:
        db_collection.insert_one({
            "username": data['username'],
            "avatar": data.get('avatar', ''),
            "type": data['type'],
            "content": data['content']
        })

    return jsonify({'status': 'success', 'message': 'تم النشر بنجاح'}), 201


@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    if db_collection is None: return jsonify([])
    
    cursor = db_collection.find().sort('_id', -1).limit(50) # جلب أحدث 50 مساهمة
    results = []
    for item in cursor:
        results.append({
            'id': str(item['_id']),
            'username': item.get('username'),
            'avatar': item.get('avatar'),
            'type': item.get('type'),
            'content': item.get('content')
        })
    return jsonify(results), 200

# لا نحتاج app.run() هنا لأن Vercel يدير التشغيل
