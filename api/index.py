import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId
from groq import Groq

app = Flask(__name__)
CORS(app)

# ==========================================
# المتغيرات السرية (Environment Variables)
# ==========================================
DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
MONGO_URI = os.environ.get("MONGO_URI")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# المتغيرات الجديدة الخاصة بالبوت والسيرفر
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID") # ايدي سيرفر Victoria
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") # توكن البوت
ADMIN_ROLE_ID = os.environ.get("ADMIN_ROLE_ID") # ايدي رتبة الإدارة

# ==========================================
# إعداد الخدمات (Groq & MongoDB)
# ==========================================
client_ai = None
if GROQ_API_KEY:
    client_ai = Groq(api_key=GROQ_API_KEY)

db_collection = None
if MONGO_URI:
    try:
        client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db = client_db['victoria_db']
        db_collection = db['contributions']
    except Exception as e:
        print(f"MongoDB Error: {e}")

# ==========================================
# دوال مساعدة (Helpers)
# ==========================================

def check_content_with_ai(text):
    """فحص النص بالذكاء الاصطناعي"""
    if not client_ai: 
        return True 
    try:
        chat_completion = client_ai.chat.completions.create(
            messages=[
                {"role": "system", "content": "أنت فلتر حماية. إذا كان النص يحتوي على شتائم واضحة بالعامية المصرية أو الفرانكو أجب بكلمة 'مرفوض'. وإذا كان محترماً وعادياً أجب بكلمة 'مقبول'."},
                {"role": "user", "content": text}
            ],
            model="llama3-70b-8192", 
            temperature=0.1,
        )
        result = chat_completion.choices[0].message.content.strip()
        print(f"AI Response: {result}")
        if "مرفوض" in result: 
            return False
        return True
    except Exception as e:
        print(f"Groq AI Error: {e}")
        return True # السماح بالنص كإجراء وقائي لو السيرفر وقع

def is_user_admin(user_id):
    """دالة للتأكد من رتبة العضو داخل السيرفر باستخدام البوت"""
    if not DISCORD_GUILD_ID or not DISCORD_BOT_TOKEN or not ADMIN_ROLE_ID:
        return False
        
    try:
        resp = requests.get(
            f'https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{user_id}',
            headers={'Authorization': f'Bot {DISCORD_BOT_TOKEN}'}
        )
        if resp.status_code == 200:
            member_data = resp.json()
            user_roles = member_data.get('roles', [])
            return ADMIN_ROLE_ID in user_roles
        return False
    except:
        return False

# ==========================================
# مسارات السيرفر (API Routes)
# ==========================================

@app.route('/api/auth/discord', methods=['POST'])
def discord_auth():
    code = request.json.get('code')
    if not code: return jsonify({'error': 'No code provided'}), 400

    # 1. التوثيق من ديسكورد
    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    token_resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    if 'error' in token_resp.json(): return jsonify({'error': 'Discord Auth Failed'}), 400
    
    access_token = token_resp.json()['access_token']
    
    # 2. جلب البيانات العامة
    user_resp = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'})
    user_data = user_resp.json()
    user_id = user_data['id']
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{user_data['avatar']}.png" if user_data.get('avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"
    
    # 3. التحقق من التواجد في السيرفر والرتبة
    in_server = False
    admin_status = False

    if DISCORD_GUILD_ID and DISCORD_BOT_TOKEN:
        member_resp = requests.get(
            f'https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{user_id}',
            headers={'Authorization': f'Bot {DISCORD_BOT_TOKEN}'}
        )
        if member_resp.status_code == 200:
            in_server = True
            admin_status = ADMIN_ROLE_ID in member_resp.json().get('roles', [])

    if not in_server and DISCORD_GUILD_ID: # لو متفعل نظام السيرفر والعضو مش فيه
        return jsonify({'error': 'يجب أن تكون عضواً في سيرفر Victoria لتتمكن من تسجيل الدخول.'}), 403

    return jsonify({
        'status': 'success',
        'user': {
            'id': user_id, 
            'username': user_data['global_name'] or user_data['username'], 
            'avatar': avatar_url, 
            'is_admin': admin_status
        }
    }), 200

@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    discord_id = data.get('discord_id')
    
    if not data.get('content') or not data.get('username') or not discord_id: 
        return jsonify({'error': 'بيانات ناقصة'}), 400

    # الفحص بالذكاء الاصطناعي
    if not check_content_with_ai(data['content']):
        return jsonify({'status': 'rejected', 'message': 'عذراً، النص يحتوي على كلمات غير لائقة.'}), 406

    # التحقق من الرتبة في الخلفية بأمان
    is_admin = is_user_admin(discord_id)
    post_status = "approved" if is_admin else "pending"

    if db_collection is not None:
        db_collection.insert_one({
            "discord_id": discord_id,
            "username": data['username'],
            "avatar": data.get('avatar', ''),
            "type": data['type'],
            "content": data['content'],
            "upvotes": 0,
            "status": post_status,
            "is_admin": is_admin
        })
        msg = "تم النشر بنجاح!" if is_admin else "تم إرسال مساهمتك بنجاح وهي الآن قيد المراجعة من الإدارة."
        return jsonify({'status': 'success', 'message': msg}), 201

@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    if db_collection is None: return jsonify([])
    
    discord_id = request.args.get('discord_id')
    
    # لو العضو إداري بيشوف الكل، لو مش إداري بيشوف الموافق عليه بس
    is_admin = is_user_admin(discord_id) if discord_id else False
    query = {} if is_admin else {"status": "approved"}
    
    cursor = db_collection.find(query).sort('_id', -1).limit(50) 
    results = []
    for item in cursor:
        results.append({
            'id': str(item['_id']),
            'username': item.get('username'),
            'avatar': item.get('avatar'),
            'type': item.get('type'),
            'content': item.get('content'),
            'upvotes': item.get('upvotes', 0),
            'status': item.get('status', 'approved'),
            'is_admin': item.get('is_admin', False)
        })
    return jsonify(results), 200

@app.route('/api/upvote/<post_id>', methods=['POST'])
def upvote(post_id):
    if db_collection is not None:
        db_collection.update_one({'_id': ObjectId(post_id)}, {'$inc': {'upvotes': 1}})
    return jsonify({'status': 'success'}), 200

@app.route('/api/approve/<post_id>', methods=['POST'])
def approve_post(post_id):
    # طبقة حماية للتأكد إن اللي بيوافق هو إداري فعلاً
    admin_id = request.json.get('admin_id')
    if not is_user_admin(admin_id):
        return jsonify({'error': 'غير مصرح لك بذلك'}), 403

    if db_collection is not None:
        db_collection.update_one({'_id': ObjectId(post_id)}, {'$set': {'status': 'approved'}})
    return jsonify({'status': 'success'}), 200

@app.route('/api/delete/<post_id>', methods=['DELETE'])
def delete_post(post_id):
    # طبقة حماية للتأكد إن اللي بيحذف هو إداري فعلاً
    admin_id = request.json.get('admin_id')
    if not is_user_admin(admin_id):
        return jsonify({'error': 'غير مصرح لك بذلك'}), 403

    if db_collection is not None:
        db_collection.delete_one({'_id': ObjectId(post_id)})
    return jsonify({'status': 'success'}), 200
