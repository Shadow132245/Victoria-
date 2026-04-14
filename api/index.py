import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from groq import Groq

app = Flask(__name__)
CORS(app)

# ==========================================
# سحب المتغيرات السرية من إعدادات Vercel
# ==========================================
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
MONGO_URI = os.environ.get("MONGO_URI")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# تهيئة الذكاء الاصطناعي (Groq)
# ==========================================
client_ai = None
if GROQ_API_KEY:
    client_ai = Groq(api_key=GROQ_API_KEY)

# ==========================================
# تهيئة قاعدة البيانات (MongoDB)
# ==========================================
db_collection = None
if MONGO_URI:
    try:
        # تحديد مهلة الاتصال بـ 5 ثواني عشان لو فيه مشكلة السيرفر ميهنجش
        client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client_db['victoria_db']
        db_collection = db['contributions']
    except Exception as e:
        print(f"MongoDB Connection Error: {e}")

# ==========================================
# دالة فحص النص بالذكاء الاصطناعي
# ==========================================
def check_content_with_ai(text):
    if not client_ai:
        return True # السماح بالنص لو مفيش مفتاح Groq عشان الموقع ميتعطلش
    
    try:
        chat_completion = client_ai.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "أنت مشرف محتوى مصري حازم جداً في سيرفر ديسكورد. مهمتك قراءة النص وتحديد ما إذا كان يحتوي على شتائم، ألفاظ خارجة، إيحاءات، أو كلمات غير لائقة بالعامية المصرية أو الفرانكو أو الفصحى. إذا كان النص محترماً أجب بكلمة واحدة فقط: مقبول. إذا كان مسيئاً أجب بكلمة واحدة فقط: مرفوض."
                },
                {
                    "role": "user",
                    "content": f'النص: "{text}"'
                }
            ],
            model="llama3-70b-8192", # نموذج ممتاز وسريع جداً في Groq
            temperature=0.1, # تقليل الإبداع عشان الرد يكون مباشر (مقبول/مرفوض)
        )
        result = chat_completion.choices[0].message.content.strip()
        return "مقبول" in result
    except Exception as e:
        print(f"Groq AI Error: {e}")
        return False # رفض كإجراء وقائي عند فشل الذكاء الاصطناعي

# ==========================================
# مسار تسجيل الدخول بواسطة ديسكورد
# ==========================================
@app.route('/api/auth/discord', methods=['POST'])
def discord_auth():
    code = request.json.get('code')
    if not code: 
        return jsonify({'error': 'No code provided'}), 400

    # 1. تبديل الكود بـ Access Token من ديسكورد
    data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    token_resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    
    if 'error' in token_resp.json(): 
        return jsonify({'error': 'Discord Auth Failed'}), 400
    
    access_token = token_resp.json()['access_token']

    # 2. جلب بيانات العضو
    user_resp = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'})
    user_data = user_resp.json()
    
    # تنسيق رابط صورة العضو
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png" if user_data.get('avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"

    return jsonify({
        'status': 'success',
        'user': {
            'id': user_data['id'], 
            'username': user_data['global_name'] or user_data['username'], 
            'avatar': avatar_url
        }
    }), 200

# ==========================================
# مسار نشر مساهمة جديدة
# ==========================================
@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    
    if not data.get('content') or not data.get('username'):
        return jsonify({'error': 'بيانات ناقصة'}), 400

    # الفحص بالذكاء الاصطناعي أولاً
    if not check_content_with_ai(data['content']):
        return jsonify({
            'status': 'rejected', 
            'message': 'عذراً، النص يحتوي على كلمات غير لائقة أو مخالفة للقوانين.'
        }), 406

    # الحفظ في قاعدة البيانات
    if db_collection is not None:
        db_collection.insert_one({
            "username": data['username'],
            "avatar": data.get('avatar', ''),
            "type": data['type'],
            "content": data['content']
        })
        return jsonify({'status': 'success', 'message': 'تم النشر بنجاح'}), 201
    else:
        return jsonify({'error': 'قاعدة البيانات غير متصلة'}), 500

# ==========================================
# مسار جلب المساهمات لعرضها في الموقع
# ==========================================
@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    if db_collection is None: 
        return jsonify({'error': 'Database not connected'}), 500
    
    try:
        # جلب أحدث 50 مساهمة
        cursor = db_collection.find().sort('_id', -1).limit(50) 
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
    except Exception as e:
        print(f"Error fetching data: {e}")
        return jsonify({'error': 'Failed to fetch data'}), 500

# تنبيه: لا نحتاج لكتابة app.run() لأن Vercel هو الذي يدير تشغيل السيرفر
