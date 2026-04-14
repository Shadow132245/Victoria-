import os
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson.objectid import ObjectId # استدعينا دي عشان نتعامل مع الـ IDs بتاعت الداتا بيس
from groq import Groq

app = Flask(__name__)
CORS(app)

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI")
MONGO_URI = os.environ.get("MONGO_URI")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ==========================================
# ⚠️ ضع هنا أرقام الـ ID الخاصة بك وباقي الإدارة في ديسكورد
# ==========================================
ADMIN_IDS = [
    "1207369496923349032", 
    "1271175620172447806",
    "1403187288518951054",
]

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

def check_content_with_ai(text):
    if not client_ai: return True 
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
        if "مرفوض" in result: return False
        return True
    except Exception:
        return True # لو حصل عطل في Groq، نعدي النص عشان الموقع ميتعطلش

@app.route('/api/auth/discord', methods=['POST'])
def discord_auth():
    code = request.json.get('code')
    if not code: return jsonify({'error': 'No code provided'}), 400

    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI}
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    
    token_resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers=headers)
    if 'error' in token_resp.json(): return jsonify({'error': 'Discord Auth Failed'}), 400
    
    access_token = token_resp.json()['access_token']
    user_resp = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'})
    user_data = user_resp.json()
    
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png" if user_data.get('avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"
    
    # التحقق هل العضو إداري أم لا
    is_admin = user_data['id'] in ADMIN_IDS

    return jsonify({
        'status': 'success',
        'user': {'id': user_data['id'], 'username': user_data['global_name'] or user_data['username'], 'avatar': avatar_url, 'is_admin': is_admin}
    }), 200

@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    if not data.get('content') or not data.get('username'): return jsonify({'error': 'بيانات ناقصة'}), 400

    if not check_content_with_ai(data['content']):
        return jsonify({'status': 'rejected', 'message': 'عذراً، النص يحتوي على كلمات غير لائقة أو مخالفة للقوانين.'}), 406

    is_admin = data.get('discord_id') in ADMIN_IDS
    # الإدارة مساهمتها بتنزل فوراً، الأعضاء العاديين مساهمتهم بتكون قيد المراجعة
    post_status = "approved" if is_admin else "pending"

    if db_collection is not None:
        db_collection.insert_one({
            "discord_id": data.get('discord_id'),
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
    
    # لو اللي فاتح الموقع إداري، يشوف كل حاجة. لو عضو عادي، يشوف الموافق عليه بس
    user_id = request.args.get('discord_id')
    query = {} if user_id in ADMIN_IDS else {"status": "approved"}
    
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

# مسار للإعجاب بالمساهمة
@app.route('/api/upvote/<post_id>', methods=['POST'])
def upvote(post_id):
    if db_collection is not None:
        db_collection.update_one({'_id': ObjectId(post_id)}, {'$inc': {'upvotes': 1}})
    return jsonify({'status': 'success'}), 200

# مسار لموافقة الإدارة على المساهمة
@app.route('/api/approve/<post_id>', methods=['POST'])
def approve_post(post_id):
    if db_collection is not None:
        db_collection.update_one({'_id': ObjectId(post_id)}, {'$set': {'status': 'approved'}})
    return jsonify({'status': 'success'}), 200

# مسار لحذف المساهمة
@app.route('/api/delete/<post_id>', methods=['DELETE'])
def delete_post(post_id):
    if db_collection is not None:
        db_collection.delete_one({'_id': ObjectId(post_id)})
    return jsonify({'status': 'success'}), 200
