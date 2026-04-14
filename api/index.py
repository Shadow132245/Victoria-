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

DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID") 
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN") 
ADMIN_ROLE_ID = os.environ.get("ADMIN_ROLE_ID") 
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL") 

# ⚠️ ضع هنا أرقام الـ ID الخاصة بالإدارة العليا
ADMIN_IDS = [
    "1207369496923349032", 
    "1271175620172447806",
    "1403187288518951054",
    
]

# ==========================================
# إعداد الخدمات
# ==========================================
client_ai = None
if GROQ_API_KEY:
    client_ai = Groq(api_key=GROQ_API_KEY)

db_collection = None
if MONGO_URI:
    try:
        client_db = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        db_collection = client_db['victoria_db']['contributions']
    except Exception as e:
        print(f"MongoDB Error: {e}")

# ==========================================
# دوال الذكاء الاصطناعي والمساعدة
# ==========================================

def check_content_with_ai(text):
    if not client_ai: return True 
    try:
        chat = client_ai.chat.completions.create(
            messages=[
                {"role": "system", "content": "أنت فلتر حماية. إذا كان النص يحتوي على شتائم واضحة بالعامية المصرية أو الفرانكو أجب بكلمة 'مرفوض'. وإذا كان محترماً وعادياً أجب بكلمة 'مقبول'."},
                {"role": "user", "content": text}
            ],
            model="llama3-70b-8192", temperature=0.1,
        )
        if "مرفوض" in chat.choices[0].message.content.strip(): 
            return False
        return True
    except: return True

def summarize_with_ai(text):
    """توليد عنوان قصير للمساهمة"""
    if len(text) < 30 or not client_ai: return ""
    try:
        chat = client_ai.chat.completions.create(
            messages=[
                {"role": "system", "content": "لخص هذا النص في عنوان قصير جدا وجذاب (أقصى حد 5 كلمات) بالعامية المصرية أو الفصحى البسيطة. لا تضع أقواس أو علامات تنصيص."},
                {"role": "user", "content": text}
            ],
            model="llama3-70b-8192", temperature=0.5,
        )
        return chat.choices[0].message.content.strip()
    except: return ""

def generate_thank_you_with_ai(username, content):
    """توليد رسالة شكر من الإدارة"""
    if not client_ai: return "شكراً لمساهمتك الرائعة في السيرفر!"
    try:
        chat = client_ai.chat.completions.create(
            messages=[
                {"role": "system", "content": f"اكتب رسالة شكر قصيرة جداً ومحفزة بالعامية المصرية لهذا العضو ({username}) على إنجازه. الرد يكون في سطر واحد فقط ومناسب لما قدمه."},
                {"role": "user", "content": f"الإنجاز: {content}"}
            ],
            model="llama3-70b-8192", temperature=0.7,
        )
        return chat.choices[0].message.content.strip()
    except: return "شكراً لمساهمتك الرائعة في السيرفر!"

def get_user_server_data(user_id):
    is_admin = False
    role_name = "" 
    if user_id in ADMIN_IDS:
        is_admin = True
        role_name = "إدارة السيرفر"

    if not DISCORD_GUILD_ID or not DISCORD_BOT_TOKEN:
        return is_admin, role_name

    try:
        member_resp = requests.get(f'https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{user_id}', headers={'Authorization': f'Bot {DISCORD_BOT_TOKEN}'})
        if member_resp.status_code == 200:
            user_roles = [str(r) for r in member_resp.json().get('roles', [])]
            if str(ADMIN_ROLE_ID) in user_roles or user_id in ADMIN_IDS:
                is_admin = True
            roles_resp = requests.get(f'https://discord.com/api/guilds/{DISCORD_GUILD_ID}/roles', headers={'Authorization': f'Bot {DISCORD_BOT_TOKEN}'})
            if roles_resp.status_code == 200:
                all_roles = sorted(roles_resp.json(), key=lambda x: x['position'], reverse=True)
                for role in all_roles:
                    if str(role['id']) in user_roles:
                        role_name = role['name']
                        break
        return is_admin, role_name
    except: return is_admin, role_name

def send_discord_webhook_log(username, avatar, content, post_type, status, image_url):
    if not DISCORD_WEBHOOK_URL: return
    embed_color = 0x23a559 if status == "approved" else 0xffa500
    status_text = "✅ تم النشر تلقائياً (إداري)" if status == "approved" else "⏳ قيد المراجعة (يحتاج موافقتك من الموقع)"
    
    embed = {
        "title": f"📝 مساهمة جديدة: {post_type}", "description": content, "color": embed_color,
        "author": {"name": username, "icon_url": avatar},
        "fields": [{"name": "حالة المساهمة:", "value": status_text, "inline": False}],
        "footer": {"text": "نظام مراجعة Victoria V4.0"}
    }
    if image_url: embed["image"] = {"url": image_url}
    try: requests.post(DISCORD_WEBHOOK_URL, json={"embeds": [embed]})
    except: pass

# ==========================================
# مسارات السيرفر (API Routes)
# ==========================================

@app.route('/api/auth/discord', methods=['POST'])
def discord_auth():
    code = request.json.get('code')
    if not code: return jsonify({'error': 'No code provided'}), 400

    data = {'client_id': DISCORD_CLIENT_ID, 'client_secret': DISCORD_CLIENT_SECRET, 'grant_type': 'authorization_code', 'code': code, 'redirect_uri': DISCORD_REDIRECT_URI}
    token_resp = requests.post('https://discord.com/api/oauth2/token', data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if 'error' in token_resp.json(): return jsonify({'error': 'Discord Auth Failed'}), 400
    
    access_token = token_resp.json()['access_token']
    user_data = requests.get('https://discord.com/api/users/@me', headers={'Authorization': f'Bearer {access_token}'}).json()
    
    user_id = str(user_data['id'])
    avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{user_data['avatar']}.png" if user_data.get('avatar') else "https://cdn.discordapp.com/embed/avatars/0.png"
    is_admin, role_name = get_user_server_data(user_id)

    return jsonify({'status': 'success', 'user': {'id': user_id, 'username': user_data['global_name'] or user_data['username'], 'avatar': avatar_url, 'is_admin': is_admin, 'role_name': role_name}}), 200

@app.route('/api/add_contribution', methods=['POST'])
def add_contribution():
    data = request.json
    discord_id = data.get('discord_id')
    image_url = data.get('image_url', '')
    
    if not data.get('content') or not discord_id: return jsonify({'error': 'بيانات ناقصة'}), 400
    if not check_content_with_ai(data['content']): return jsonify({'status': 'rejected', 'message': 'عذراً، النص يحتوي على كلمات غير لائقة.'}), 406

    is_admin, role_name = get_user_server_data(discord_id)
    post_status = "approved" if is_admin else "pending"
    ai_title = summarize_with_ai(data['content'])

    if db_collection is not None:
        db_collection.insert_one({
            "discord_id": discord_id, "username": data['username'], "avatar": data.get('avatar', ''),
            "type": data['type'], "content": data['content'], "image_url": image_url,
            "ai_title": ai_title, "ai_reply": "", "upvotes": 0, "status": post_status, 
            "is_admin": is_admin, "role_name": role_name
        })
        send_discord_webhook_log(data['username'], data.get('avatar', ''), data['content'], data['type'], post_status, image_url)
        msg = "تم النشر بنجاح!" if is_admin else "تم إرسال مساهمتك وهي الآن قيد المراجعة."
        return jsonify({'status': 'success', 'message': msg}), 201

@app.route('/api/get_contributions', methods=['GET'])
def get_contributions():
    if db_collection is None: return jsonify([])
    
    discord_id = request.args.get('discord_id')
    filter_type = request.args.get('type')
    search_query = request.args.get('search')
    
    is_admin, _ = get_user_server_data(discord_id) if discord_id else (False, "")
    query = {} if is_admin else {"status": "approved"}
    
    # الفلترة والبحث
    if filter_type and filter_type != "الكل":
        query['type'] = filter_type
    if search_query:
        query['content'] = {'$regex': search_query, '$options': 'i'} # بحث تقريبي غير حساس للحالة
    
    cursor = db_collection.find(query).sort('_id', -1).limit(50) 
    results = []
    for item in cursor:
        results.append({
            'id': str(item['_id']), 'username': item.get('username'), 'avatar': item.get('avatar'),
            'type': item.get('type'), 'content': item.get('content'), 'image_url': item.get('image_url', ''),
            'ai_title': item.get('ai_title', ''), 'ai_reply': item.get('ai_reply', ''),
            'upvotes': item.get('upvotes', 0), 'status': item.get('status', 'approved'), 
            'is_admin': item.get('is_admin', False), 'role_name': item.get('role_name', '')
        })
    return jsonify(results), 200

@app.route('/api/upvote/<post_id>', methods=['POST'])
def upvote(post_id):
    if db_collection is not None: db_collection.update_one({'_id': ObjectId(post_id)}, {'$inc': {'upvotes': 1}})
    return jsonify({'status': 'success'}), 200

@app.route('/api/approve/<post_id>', methods=['POST'])
def approve_post(post_id):
    is_admin, _ = get_user_server_data(request.json.get('admin_id'))
    if not is_admin: return jsonify({'error': 'غير مصرح لك'}), 403
    
    if db_collection is not None:
        post = db_collection.find_one({'_id': ObjectId(post_id)})
        if post:
            # توليد رد آلي ذكي عند الموافقة
            ai_reply = generate_thank_you_with_ai(post.get('username', 'العضو'), post.get('content', ''))
            db_collection.update_one({'_id': ObjectId(post_id)}, {'$set': {'status': 'approved', 'ai_reply': ai_reply}})
    return jsonify({'status': 'success'}), 200

@app.route('/api/delete/<post_id>', methods=['DELETE'])
def delete_post(post_id):
    is_admin, _ = get_user_server_data(request.json.get('admin_id'))
    if not is_admin: return jsonify({'error': 'غير مصرح لك'}), 403
    if db_collection is not None: db_collection.delete_one({'_id': ObjectId(post_id)})
    return jsonify({'status': 'success'}), 200

@app.route('/api/leaderboard', methods=['GET'])
def get_leaderboard():
    if db_collection is None: return jsonify([])
    pipeline = [
        {"$match": {"status": "approved"}},
        {"$group": {"_id": "$discord_id", "username": {"$first": "$username"}, "avatar": {"$first": "$avatar"}, "role_name": {"$first": "$role_name"}, "total_upvotes": {"$sum": "$upvotes"}}},
        {"$sort": {"total_upvotes": -1}},
        {"$limit": 5}
    ]
    return jsonify(list(db_collection.aggregate(pipeline))), 200

@app.route('/api/admin_stats', methods=['GET'])
def admin_stats():
    """مسار لإحصائيات لوحة التحكم للإدارة"""
    admin_id = request.args.get('admin_id')
    is_admin, _ = get_user_server_data(admin_id) if admin_id else (False, "")
    
    if not is_admin or db_collection is None: return jsonify({'error': 'Unauthorized'}), 403
    
    total_approved = db_collection.count_documents({"status": "approved"})
    total_pending = db_collection.count_documents({"status": "pending"})
    
    # حساب إجمالي القلوب
    pipeline = [{"$group": {"_id": None, "total_hearts": {"$sum": "$upvotes"}}}]
    hearts_result = list(db_collection.aggregate(pipeline))
    total_hearts = hearts_result[0]['total_hearts'] if hearts_result else 0
    
    return jsonify({
        'total_approved': total_approved,
        'total_pending': total_pending,
        'total_hearts': total_hearts
    }), 200
